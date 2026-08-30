"""Repository-owned paths and private filesystem primitives.

Importing this module only computes paths.  It never creates repository state.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat
import tempfile
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
RUNTIME_ROOT: Final[Path] = REPO_ROOT / ".runtime"
RUNTIME_DIR: Final[Path] = RUNTIME_ROOT
CONFIG_DIR: Final[Path] = RUNTIME_ROOT / "config"
DEFAULT_CONFIG_PATH: Final[Path] = CONFIG_DIR / "config.toml"
CONFIG_PATH: Final[Path] = DEFAULT_CONFIG_PATH
CACHE_DIR: Final[Path] = RUNTIME_ROOT / "cache"
STATE_DIR: Final[Path] = RUNTIME_ROOT / "state"


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
    "CACHE_DIR",
    "CONFIG_DIR",
    "CONFIG_PATH",
    "DEFAULT_CONFIG_PATH",
    "REPO_ROOT",
    "RUNTIME_DIR",
    "RUNTIME_ROOT",
    "STATE_DIR",
    "atomic_write_private",
    "ensure_private_dir",
    "ensure_private_directory",
    "private_mkdir",
    "private_write_bytes",
    "private_write_text",
    "repo_path",
    "require_runtime_path",
    "runtime_path",
    "write_private_bytes",
    "write_private_text",
]
