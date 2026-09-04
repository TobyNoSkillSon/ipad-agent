"""Repository-owned paths and private filesystem primitives.

Importing this module only computes paths.  It never creates repository state.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
RUNTIME_ROOT: Final[Path] = REPO_ROOT / ".runtime"
RUNTIME_DIR: Final[Path] = RUNTIME_ROOT
CONFIG_DIR: Final[Path] = RUNTIME_ROOT / "config"
DEFAULT_CONFIG_PATH: Final[Path] = CONFIG_DIR / "config.toml"
CONFIG_PATH: Final[Path] = DEFAULT_CONFIG_PATH
CACHE_DIR: Final[Path] = RUNTIME_ROOT / "cache"
STATE_DIR: Final[Path] = RUNTIME_ROOT / "state"
ARTIFACT_DIR: Final[Path] = RUNTIME_ROOT / "artifacts"
AF_UNIX_PATH_BUDGET: Final[int] = 96


def repo_path(*parts: str | os.PathLike[str]) -> Path:
    """Return a repository-contained path without following symlinks."""
    return _contained(REPO_ROOT, parts)


def runtime_path(*parts: str | os.PathLike[str]) -> Path:
    """Return a path below ``.runtime``, rejecting escapes and symlinks."""
    return _contained(RUNTIME_ROOT, parts)


def require_runtime_path(path: str | os.PathLike[str]) -> Path:
    """Validate and return an absolute path contained below ``.runtime``."""
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = RUNTIME_ROOT / candidate
    return _validate_contained(RUNTIME_ROOT, candidate)


def require_runtime_artifact_path(path: str | os.PathLike[str]) -> Path:
    """Return one non-traversing file path below ``.runtime/artifacts``."""
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = ARTIFACT_DIR / candidate
    validated = _validate_contained(ARTIFACT_DIR, candidate)
    if validated == Path(os.path.abspath(ARTIFACT_DIR)):
        raise ValueError("artifact output must name a file below the artifact directory")
    return validated


def private_runtime_socket_path(
    repository_root: str | os.PathLike[str] | None = None,
) -> Path:
    """Return a deterministic, AF_UNIX-safe endpoint for this checkout.

    Darwin's ``sockaddr_un.sun_path`` is too small for arbitrarily deep
    checkouts.  The endpoint therefore lives in a checkout-specific owner-only
    directory below the system's short temporary prefix; callers create and
    validate that directory immediately before binding.
    """
    root = REPO_ROOT if repository_root is None else Path(repository_root)
    identity = os.path.abspath(os.fspath(root))
    digest = hashlib.sha256(os.fsencode(identity)).hexdigest()[:16]
    uid = os.geteuid() if hasattr(os, "geteuid") else os.getuid()
    candidate = Path("/tmp") / f"ipad-agent-{uid}-{digest}" / "runtime.sock"
    if len(os.fsencode(candidate)) > AF_UNIX_PATH_BUDGET:
        raise RuntimeError("private runtime socket path exceeds the AF_UNIX safety budget")
    return candidate


def has_extended_acl(path: str | os.PathLike[str]) -> bool:
    """Return whether a macOS filesystem object carries an extended ACL."""
    try:
        result = subprocess.run(
            ["/bin/ls", "-lde", os.fspath(path)],
            capture_output=True,
            text=True,
            timeout=5,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "CLICOLOR": "0", "TERM": "dumb"},
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError("cannot inspect filesystem ACL") from error
    fields = result.stdout.split(None, 1)
    if result.returncode != 0 or not fields:
        raise RuntimeError("cannot inspect filesystem ACL")
    mode = fields[0]
    if len(mode) < 10 or mode[0] not in "-dlcbps":
        raise RuntimeError("filesystem ACL query returned an invalid result")
    return mode.endswith("+")


def descriptor_has_extended_acl(descriptor: int) -> bool:
    """Return whether an open macOS filesystem object carries an extended ACL."""
    if isinstance(descriptor, bool) or not isinstance(descriptor, int) or descriptor < 0:
        raise ValueError("descriptor must be a non-negative integer")
    try:
        result = subprocess.run(
            ["/bin/ls", "-lde", f"/dev/fd/{descriptor}"],
            capture_output=True,
            text=True,
            timeout=5,
            pass_fds=(descriptor,),
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "CLICOLOR": "0", "TERM": "dumb"},
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError("cannot inspect filesystem ACL") from error
    fields = result.stdout.split(None, 1)
    if result.returncode != 0 or not fields:
        raise RuntimeError("cannot inspect filesystem ACL")
    mode = fields[0]
    if len(mode) < 10 or mode[0] not in "-dlcbps":
        raise RuntimeError("filesystem ACL query returned an invalid result")
    return mode.endswith("+")


def private_mkdir(path: str | os.PathLike[str], *, mode: int = 0o700) -> Path:
    """Create an owner-only directory tree inside ``.runtime``.

    Existing components must be real directories owned by the current user and
    must not grant any permissions to group or other users.
    """
    _validate_private_mode(mode, directory=True)
    target = require_runtime_path(path)
    root_parent = RUNTIME_ROOT.parent
    current = root_parent
    relative = target.relative_to(root_parent)
    for part in relative.parts:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            try:
                os.mkdir(current, mode)
            except FileExistsError:
                info = current.lstat()
            else:
                info = current.lstat()
        _require_owned_directory(current, info)
    return target


def private_read_text(
    path: str | os.PathLike[str], *, encoding: str = "utf-8", max_bytes: int = 1_000_000,
) -> str:
    """Read one owner-private regular file below ``.runtime`` without following links."""
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    target = require_runtime_path(path)
    current = RUNTIME_ROOT
    for part in target.parent.relative_to(RUNTIME_ROOT).parts:
        current = current / part
        _require_owned_directory(current, current.lstat())
    before = target.lstat()
    _validate_existing_private_file(target)
    descriptor = os.open(
        target,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise PermissionError("private runtime file changed before opening")
        if opened.st_size > max_bytes or descriptor_has_extended_acl(descriptor):
            raise PermissionError("private runtime file is not safe to read")
        with os.fdopen(descriptor, "r", encoding=encoding, closefd=True) as handle:
            descriptor = -1
            return handle.read(max_bytes + 1)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def private_write_bytes(path: str | os.PathLike[str], data: bytes, *, mode: int = 0o600) -> Path:
    """Atomically write owner-only bytes to a regular file below ``.runtime``."""
    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")
    _validate_private_mode(mode, directory=False)
    target = require_runtime_path(path)
    parent = private_mkdir(target.parent)
    _validate_existing_private_file(target)

    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        # Recheck after creating the temporary file to narrow replacement races.
        require_runtime_path(target)
        _validate_existing_private_file(target)
        os.replace(temporary, target)
        directory_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return target


def private_write_text(
    path: str | os.PathLike[str],
    text: str,
    *,
    encoding: str = "utf-8",
    mode: int = 0o600,
) -> Path:
    """Atomically write owner-only text below ``.runtime``."""
    if not isinstance(text, str):
        raise TypeError("text must be str")
    return private_write_bytes(path, text.encode(encoding), mode=mode)


def _contained(root: Path, parts: tuple[str | os.PathLike[str], ...]) -> Path:
    candidate = root
    for raw_part in parts:
        part = Path(raw_part)
        if part.is_absolute():
            raise ValueError(f"absolute path is not allowed: {part}")
        candidate = candidate / part
    return _validate_contained(root, candidate)


def _validate_contained(root: Path, candidate: Path) -> Path:
    # Reject traversal syntax itself, even when normalisation would land back
    # inside the trusted tree.  This keeps path authority explicit to callers.
    if ".." in Path(candidate).parts:
        raise ValueError(f"path escapes its trusted tree through unsafe traversal: {candidate}")
    root = Path(os.path.abspath(root))
    candidate = Path(os.path.abspath(candidate))
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise ValueError(f"path escapes {root}: {candidate}") from error

    current = root
    _reject_symlink_if_present(current)
    for part in relative.parts:
        if part in {"", ".", ".."}:
            raise ValueError(f"unsafe path component: {part!r}")
        current = current / part
        _reject_symlink_if_present(current)
    return candidate


def _reject_symlink_if_present(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode):
        raise ValueError(f"symlinks are not allowed in runtime paths: {path}")


def _require_owned_directory(path: Path, info: os.stat_result) -> None:
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError(f"expected a directory: {path}")
    if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
        raise PermissionError(f"directory is not owned by the current user: {path}")
    if has_extended_acl(path):
        raise PermissionError(f"directory has an extended ACL: {path}")
    if stat.S_IMODE(info.st_mode) & ~0o700:
        raise PermissionError(f"directory is not private: {path}")


def _validate_existing_private_file(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ValueError(f"expected a regular non-symlink file: {path}")
    if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
        raise PermissionError(f"file is not owned by the current user: {path}")
    if has_extended_acl(path):
        raise PermissionError(f"file has an extended ACL: {path}")
    if stat.S_IMODE(info.st_mode) & ~0o600:
        raise PermissionError(f"file is not private: {path}")


def _validate_private_mode(mode: int, *, directory: bool) -> None:
    if isinstance(mode, bool) or not isinstance(mode, int):
        raise TypeError("mode must be an integer")
    allowed = 0o700 if directory else 0o600
    if mode < 0 or mode & ~allowed or mode == 0:
        raise ValueError(f"mode must be owner-only (within {allowed:o})")


# Readable aliases for callers that prefer action-oriented names.
ensure_private_dir = private_mkdir
ensure_private_directory = private_mkdir
atomic_write_private = private_write_bytes
write_private_bytes = private_write_bytes
write_private_text = private_write_text

__all__ = [
    "AF_UNIX_PATH_BUDGET",
    "ARTIFACT_DIR",
    "CACHE_DIR",
    "CONFIG_DIR",
    "CONFIG_PATH",
    "DEFAULT_CONFIG_PATH",
    "REPO_ROOT",
    "RUNTIME_DIR",
    "RUNTIME_ROOT",
    "STATE_DIR",
    "atomic_write_private",
    "descriptor_has_extended_acl",
    "ensure_private_dir",
    "has_extended_acl",
    "ensure_private_directory",
    "private_mkdir",
    "private_read_text",
    "private_runtime_socket_path",
    "private_write_bytes",
    "private_write_text",
    "repo_path",
    "require_runtime_artifact_path",
    "require_runtime_path",
    "runtime_path",
    "write_private_bytes",
    "write_private_text",
]
