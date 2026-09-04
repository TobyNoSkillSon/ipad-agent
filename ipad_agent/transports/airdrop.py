"""Bounded, fail-closed AirDrop transfer of one validated local file.

The native helper uses only macOS ``NSSSharingService``.  V1 deliberately does
not automate an iPad acceptance prompt and does not pretend that AirDrop's
sharing service accepts a recipient argument: it does not.
"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
from dataclasses import dataclass
import errno
import fcntl
import json
import os
from pathlib import Path
import queue
import re
import stat
import subprocess
import threading
import time
from typing import Any, Iterator, Protocol, Sequence
import uuid

from ipad_agent.core.paths import REPO_ROOT, RUNTIME_ROOT, has_extended_acl, private_mkdir
from ipad_agent.core.projection import public_result

HELPER_SOURCE = REPO_ROOT / "native" / "airdrop-share" / "AirDropShare.swift"
HELPER_BUILD_SCRIPT = REPO_ROOT / "native" / "airdrop-share" / "build.sh"
HELPER_BINARY = RUNTIME_ROOT / "native" / "airdrop-share" / "airdrop-share"
_RESULT_SCHEMA = "ipad-agent.airdrop-result/v1"
_MAX_PROTOCOL_LINE = 16_384
_EXTENSION = re.compile(r"^\.[A-Za-z0-9][A-Za-z0-9._+-]{0,31}$")
_ATTEMPT_ID = re.compile(r"^[0-9a-f]{32}$")
_ATTEMPTS_ROOT = RUNTIME_ROOT / "airdrop" / "attempts"
_SEND_LOCK = RUNTIME_ROOT / "airdrop" / "send.lock"
_COPY_CHUNK_BYTES = 1024 * 1024
_SEMANTIC_REJECTED = "AirDrop request failed before dispatch"
_SEMANTIC_FAILED = "AirDrop attempt failed"
_SEMANTIC_UNCERTAIN = "AirDrop outcome is unknown"
_CONTROL_LOST = "native helper control was lost after invocation may have started"


class AirDropError(RuntimeError):
    """Base class for local AirDrop backend errors."""


class AirDropValidationError(AirDropError, ValueError):
    """The requested file or transfer boundary is unsafe."""


class AirDropBuildError(AirDropError):
    """The project-owned native helper could not be built safely."""


class AirDropSnapshotError(AirDropError):
    """A private, immutable-for-attempt source snapshot could not be made."""


class ExactReceiverSelector(Protocol):
    """Optional future Accessibility hook with an exact-match-only contract.

    Implementations must locate one Accessibility element whose exposed label
    exactly equals ``receiver`` and activate only that element.  Coordinates,
    ordinal positions, fuzzy matching, and "first recipient" fallbacks violate
    this contract.  V1 ships no implementation.
    """

    def select_exact_receiver(
        self, *, receiver: str, timeout_seconds: float
    ) -> "AccessibilitySelection": ...


@dataclass(frozen=True)
class AccessibilitySelection:
    """Evidence returned by an exact Accessibility selector implementation."""

    requested_receiver: str
    observed_label: str | None
    exact_match_count: int
    activated: bool


@dataclass(frozen=True)
class ValidatedFile:
    path: Path
    size: int
    device: int
    inode: int
    modified_ns: int
    changed_ns: int
    extension: str
    allowed_roots: tuple[Path, ...]


@dataclass(frozen=True)
class AttemptSnapshot:
    attempt_id: str
    directory: Path
    file: ValidatedFile
    method: str


def validate_local_file(
    path: str | os.PathLike[str],
    *,
    allowed_roots: Sequence[str | os.PathLike[str]],
    allowed_extensions: Sequence[str],
    max_bytes: int,
) -> ValidatedFile:
    """Validate an exact, canonical, readable local regular-file request.

    The send path then snapshots a still-matching source descriptor. The Swift
    helper separately validates that private snapshot immediately before it
    invokes ``NSSSharingService`` and also rejects non-local mounts.
    """
    if not isinstance(path, (str, os.PathLike)):
        raise AirDropValidationError("path must be a string or path-like object")
    raw_path = os.fspath(path)
    if not isinstance(raw_path, str) or not raw_path or "\x00" in raw_path:
        raise AirDropValidationError("path must be a non-empty filesystem path")
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        raise AirDropValidationError("path must be absolute")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise AirDropValidationError("max_bytes must be a positive integer")

    roots = _validate_roots(allowed_roots)
    extensions = _validate_extensions(allowed_extensions)
    canonical = candidate.resolve(strict=True)
    lexical = Path(os.path.abspath(raw_path))
    if candidate != lexical or canonical != lexical:
        raise AirDropValidationError("path must be canonical and contain no symlink components")
    if not any(_is_below(canonical, root) for root in roots):
        raise AirDropValidationError("path is outside the configured allowed roots")

    try:
        before = os.lstat(canonical)
    except OSError as error:
        raise AirDropValidationError(f"cannot inspect file: {error.strerror or error}") from error
    if not stat.S_ISREG(before.st_mode):
        raise AirDropValidationError("path must name a regular file")
    if before.st_uid != os.getuid():
        raise AirDropValidationError("file must be owned by the current user")
    if has_extended_acl(canonical):
        raise AirDropValidationError("file must not carry an extended ACL")
    if stat.S_IMODE(before.st_mode) & 0o022:
        raise AirDropValidationError("file must not be writable by group or other users")

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(canonical, flags)
    except OSError as error:
        raise AirDropValidationError(f"file is not safely readable: {error.strerror or error}") from error
    try:
        opened = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if not stat.S_ISREG(opened.st_mode):
        raise AirDropValidationError("opened object is not a regular file")
    if (
        opened.st_dev,
        opened.st_ino,
        opened.st_size,
        opened.st_mtime_ns,
        opened.st_ctime_ns,
    ) != (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ):
        raise AirDropValidationError("file changed while it was being validated")
    if opened.st_size > max_bytes:
        raise AirDropValidationError(
            f"file size {opened.st_size} exceeds max_bytes {max_bytes}"
        )

    folded_name = canonical.name.casefold()
    matched = next((item for item in extensions if folded_name.endswith(item.casefold())), None)
    if matched is None:
        raise AirDropValidationError("file extension is not allowed")
    return ValidatedFile(
        path=canonical,
        size=opened.st_size,
        device=opened.st_dev,
        inode=opened.st_ino,
        modified_ns=opened.st_mtime_ns,
        changed_ns=opened.st_ctime_ns,
        extension=matched,
        allowed_roots=roots,
    )


def build_helper(*, timeout_seconds: float = 60.0) -> Path:
    """Build the official-framework Swift helper into Git-ignored ``.runtime``."""
    timeout = _positive_timeout(timeout_seconds, "timeout_seconds")
    for source in (HELPER_SOURCE, HELPER_BUILD_SCRIPT):
        _require_project_regular_file(source)
    try:
        completed = subprocess.run(
            ["/bin/sh", str(HELPER_BUILD_SCRIPT)],
            cwd=REPO_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
            env=_native_environment(),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise AirDropBuildError(f"native helper build failed: {error}") from error
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[-1000:]
        raise AirDropBuildError(
            f"native helper build failed with exit {completed.returncode}: {detail}"
        )
    _require_runtime_executable(HELPER_BINARY)
    return HELPER_BINARY


def airdrop(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Host-side semantic entry point used by the lazy local-file route.

    Transfer is disabled until an explicit allowlist, extension list, and byte
    ceiling are all present in the project-local ``[airdrop]`` configuration.
    V1 has no Accessibility selector implementation, so the macOS AirDrop UI
    (or same-account auto-accept) determines the receiver.
    """
    from ipad_agent.core.config import load_config

    config = load_config()
    if not (
        config.airdrop_allowed_roots
        and config.airdrop_allowed_extensions
        and config.airdrop_max_bytes is not None
    ):
        return {
            "ok": False,
            "route": "airdrop",
            "error": "AirDrop is disabled until its local-file policy is fully configured",
            "uncertain": False,
        }
    try:
        result = send_file(
            path,
            allowed_roots=config.airdrop_allowed_roots,
            allowed_extensions=config.airdrop_allowed_extensions,
            max_bytes=config.airdrop_max_bytes,
            timeout_seconds=config.airdrop_timeout_seconds,
        )
    except AirDropError:
        # Validation, build, and snapshot errors can embed source or recovery
        # paths. The semantic surface reports only the stable phase outcome.
        return {
            "ok": False,
            "route": "airdrop",
            "error": _SEMANTIC_REJECTED,
            "uncertain": False,
        }

    status = result.get("status")
    public = _semantic_projection(result)
    if status == "completed":
        return {**public, "ok": True, "route": "airdrop"}
    if status == "uncertain":
        return {
            **public,
            "reason": _SEMANTIC_UNCERTAIN,
            "ok": False,
            "route": "airdrop",
            "error": _SEMANTIC_UNCERTAIN,
            "uncertain": True,
        }
    error = _SEMANTIC_REJECTED if result.get("dispatch") == "not_attempted" else _SEMANTIC_FAILED
    return {
        **public,
        "ok": False,
        "route": "airdrop",
        "error": error,
        "uncertain": False,
    }


def _semantic_projection(result: dict[str, Any]) -> dict[str, Any]:
    """Allowlist public AirDrop fields without forwarding diagnostic strings."""
    projected = public_result(result)
    if not isinstance(projected, dict):  # pragma: no cover - send_file contract
        return {}

    safe: dict[str, Any] = {}
    exact_strings = {
        "schema": {_RESULT_SCHEMA},
        "status": {"completed", "failed", "uncertain"},
        "dispatch": {"attempted", "not_attempted", "unknown"},
        "callback": {"completed", "failed"},
        "metrics_scope": {"nominal_source_not_target_receipt"},
        "target_receipt": {"not_proven"},
        "receiver_selection": {
            "not_requested", "exact_accessibility_match", "failed_closed", "unknown",
        },
        "snapshot_method": {"apfs_clone", "bounded_fd_copy"},
    }
    for key, allowed in exact_strings.items():
        value = projected.get(key)
        if isinstance(value, str) and value in allowed:
            safe[key] = value
    for key in (
        "attempts", "nominal_source_bytes", "elapsed_seconds",
        "nominal_source_bytes_per_second",
    ):
        value = projected.get(key)
        if not isinstance(value, bool) and isinstance(value, (int, float)) and value >= 0:
            safe[key] = value
    if isinstance(projected.get("snapshot_retained"), bool):
        safe["snapshot_retained"] = projected["snapshot_retained"]
    return safe


def send_file(
    path: str | os.PathLike[str],
    *,
    allowed_roots: Sequence[str | os.PathLike[str]],
    allowed_extensions: Sequence[str],
    max_bytes: int,
    timeout_seconds: float = 120.0,
    helper_path: str | os.PathLike[str] | None = None,
    target_receiver: str | None = None,
    accessibility_selector: ExactReceiverSelector | None = None,
    selector_timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    """Make exactly one bounded AirDrop send attempt from a private snapshot.

    The timeout covers lock acquisition, helper build, snapshot creation, and
    the native attempt (apart from filesystem calls the OS does not make
    interruptible). ``target_receiver`` is never passed to
    ``NSSSharingService`` because that API has no recipient parameter.
    """
    timeout = _positive_timeout(timeout_seconds, "timeout_seconds")
    selector_timeout = _positive_timeout(selector_timeout_seconds, "selector_timeout_seconds")
    receiver = _validate_receiver_configuration(target_receiver, accessibility_selector)
    validated = validate_local_file(
        path,
        allowed_roots=allowed_roots,
        allowed_extensions=allowed_extensions,
        max_bytes=max_bytes,
    )
    deadline = time.monotonic() + timeout
    attempt_id = uuid.uuid4().hex

    try:
        with _serialized_send(deadline):
            if helper_path is None:
                remaining = _remaining(deadline)
                if remaining <= 0:
                    return _failed_not_dispatched("AirDrop timeout expired before helper build")
                helper = build_helper(timeout_seconds=min(60.0, remaining))
            else:
                helper = Path(helper_path)
                _require_runtime_executable(helper)

            remaining = _remaining(deadline)
            if remaining <= 0:
                return _failed_not_dispatched("AirDrop timeout expired before snapshot creation")
            snapshot = _create_attempt_snapshot(
                validated,
                attempt_id=attempt_id,
                deadline=deadline,
            )
            invocation_may_have_started = False
            try:
                arguments = [
                    str(helper),
                    "--path", str(snapshot.file.path),
                    "--size", str(snapshot.file.size),
                    "--device", str(snapshot.file.device),
                    "--inode", str(snapshot.file.inode),
                    "--mtime-ns", str(snapshot.file.modified_ns),
                    "--ctime-ns", str(snapshot.file.changed_ns),
                    "--max-bytes", str(max_bytes),
                    "--timeout", str(max(0.001, _remaining(deadline))),
                    "--attempt-id", attempt_id,
                    "--attempt-root", str(snapshot.directory),
                    "--source-basename", validated.path.name,
                    "--root", str(snapshot.directory),
                    "--extension", validated.extension,
                ]
                remaining = _remaining(deadline)
                if remaining <= 0:
                    result = _failed_not_dispatched(
                        "AirDrop timeout expired before native helper launch"
                    )
                else:
                    # From this assignment onward the caller cannot prove that
                    # Popen did not start the one native sharing attempt.
                    invocation_may_have_started = True
                    result = _run_one_attempt(
                        arguments,
                        validated=snapshot.file,
                        timeout_seconds=remaining,
                        receiver=receiver,
                        accessibility_selector=accessibility_selector,
                        selector_timeout_seconds=min(selector_timeout, remaining),
                        attempt_id=attempt_id,
                        snapshot_path=snapshot.file.path,
                    )
                result["attempt_id"] = attempt_id
                result["snapshot_method"] = snapshot.method
            except BaseException:
                if invocation_may_have_started:
                    result = _uncertain(_CONTROL_LOST, "unknown", dispatch="unknown")
                    result["attempt_id"] = attempt_id
                    result["snapshot_method"] = snapshot.method
                    result["snapshot_retained"] = True
                    result["snapshot_path"] = str(snapshot.file.path)
                    return result
                _cleanup_snapshot(snapshot)
                raise
            if result.get("status") == "uncertain":
                result["snapshot_retained"] = True
                result["snapshot_path"] = str(snapshot.file.path)
                return result

            cleanup_error = _cleanup_snapshot(snapshot)
            result["snapshot_retained"] = cleanup_error is not None
            if cleanup_error is not None:
                result["snapshot_path"] = str(snapshot.file.path)
                result["snapshot_cleanup_error"] = cleanup_error
            return result
    except TimeoutError:
        return _failed_not_dispatched("another AirDrop attempt held the send lock until timeout")
    except AirDropError:
        raise
    except (OSError, ValueError) as error:
        raise AirDropSnapshotError(f"AirDrop private attempt setup failed: {error}") from error


def _run_one_attempt(
    arguments: list[str],
    *,
    validated: ValidatedFile,
    timeout_seconds: float,
    receiver: str | None,
    accessibility_selector: ExactReceiverSelector | None,
    selector_timeout_seconds: float,
    attempt_id: str = "0" * 32,
    snapshot_path: Path | None = None,
) -> dict[str, Any]:
    """Run one helper process; only a native rejection proves no dispatch."""
    started = time.monotonic()
    expected_snapshot = snapshot_path or validated.path
    try:
        process = subprocess.Popen(
            arguments,
            cwd=REPO_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=_native_environment(),
        )
    except OSError as error:
        return _failed_not_dispatched(f"could not start native helper: {error}")
    except BaseException:
        # Popen may have created the helper before local control was cancelled.
        return _uncertain(_CONTROL_LOST, "unknown", dispatch="unknown")

    assert process.stdout is not None
    dispatching = False
    selection_state = "not_requested"
    deadline = started + timeout_seconds
    events_seen = 0
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _stop_process(process)
                return _timeout_result(
                    dispatching,
                    "native helper exceeded the bounded timeout",
                    helper_started=True,
                )

            line_box: queue.Queue[str | BaseException] = queue.Queue(maxsize=1)

            def read_line() -> None:
                try:
                    line_box.put(process.stdout.readline())
                except BaseException as error:  # pragma: no cover - defensive pipe failure
                    line_box.put(error)

            reader = threading.Thread(target=read_line, daemon=True)
            reader.start()
            try:
                item = line_box.get(timeout=remaining)
            except queue.Empty:
                _stop_process(process)
                return _timeout_result(
                    dispatching,
                    "native helper exceeded the bounded timeout",
                    helper_started=True,
                )
            if isinstance(item, BaseException):
                _stop_process(process)
                return _timeout_result(
                    dispatching,
                    f"native helper output failed: {item}",
                    helper_started=True,
                )
            line = item
            if line == "":
                try:
                    return_code = process.wait(timeout=max(0.1, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    _stop_process(process)
                    return _timeout_result(
                        dispatching,
                        "native helper output closed without process exit",
                        helper_started=True,
                    )
                detail = _bounded_stderr(process)
                reason = f"native helper exited {return_code} without a final callback"
                if detail:
                    reason += f": {detail}"
                return _timeout_result(dispatching, reason, helper_started=True)
            if len(line) > _MAX_PROTOCOL_LINE:
                _stop_process(process)
                return _timeout_result(
                    dispatching,
                    "native helper emitted an oversized event",
                    helper_started=True,
                )
            events_seen += 1
            if events_seen > 3:
                _stop_process(process)
                return _timeout_result(
                    dispatching,
                    "native helper emitted too many events",
                    helper_started=True,
                )
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                _stop_process(process)
                return _timeout_result(
                    dispatching,
                    "native helper emitted invalid JSON",
                    helper_started=True,
                )
            if not isinstance(event, dict) or not isinstance(event.get("event"), str):
                _stop_process(process)
                return _timeout_result(
                    dispatching,
                    "native helper emitted an invalid event",
                    helper_started=True,
                )

            kind = event["event"]
            if kind == "rejected" and not dispatching:
                _stop_process(process)
                return _failed_not_dispatched(_event_message(event, "native helper rejected request"))
            if kind == "dispatching" and not dispatching:
                # The helper emits and flushes this immediately before perform().
                # From this point onward, any lost response is structurally uncertain.
                dispatching = True
                if (
                    event.get("attempt_id") != attempt_id
                    or event.get("snapshot_path") != str(expected_snapshot)
                    or event.get("nominal_source_bytes") != validated.size
                ):
                    _stop_process(process)
                    return _uncertain(
                        "native helper did not prove it dispatched the expected attempt snapshot",
                        "unknown",
                    )
                if accessibility_selector is not None:
                    assert receiver is not None
                    remaining = deadline - time.monotonic()
                    selection = _call_selector_bounded(
                        accessibility_selector,
                        receiver=receiver,
                        timeout_seconds=min(selector_timeout_seconds, max(0.0, remaining)),
                    )
                    if not _selection_is_exact(selection, receiver):
                        _stop_process(process)
                        return _uncertain(
                            "exact receiver selection was not proven", "failed_closed"
                        )
                    selection_state = "exact_accessibility_match"
                continue
            if kind == "completed" and dispatching:
                if event.get("nominal_source_bytes") != validated.size:
                    _stop_process(process)
                    return _uncertain(
                        "completion callback reported inconsistent nominal source bytes",
                        selection_state,
                    )
                elapsed = event.get("elapsed_seconds")
                if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or elapsed < 0:
                    _stop_process(process)
                    return _uncertain(
                        "completion callback reported invalid elapsed time", selection_state
                    )
                _stop_process(process)
                seconds = float(elapsed)
                nominal_rate = validated.size / seconds if seconds > 0 else 0.0
                return {
                    "schema": _RESULT_SCHEMA,
                    "status": "completed",
                    "attempts": 1,
                    "dispatch": "attempted",
                    "callback": "completed",
                    "nominal_source_bytes": validated.size,
                    "elapsed_seconds": round(seconds, 6),
                    "nominal_source_bytes_per_second": round(nominal_rate, 2),
                    "metrics_scope": "nominal_source_not_target_receipt",
                    "target_receipt": "not_proven",
                    "receiver_selection": selection_state,
                }
            if kind == "failed" and dispatching:
                _stop_process(process)
                return {
                    "schema": _RESULT_SCHEMA,
                    "status": "failed",
                    "attempts": 1,
                    "dispatch": "attempted",
                    "callback": "failed",
                    "error": _event_message(event, "AirDrop callback reported failure"),
                    "receiver_selection": selection_state,
                }
            if kind == "uncertain" and dispatching:
                _stop_process(process)
                return _uncertain(
                    _event_message(event, "callback outcome is unknown"), selection_state
                )
            _stop_process(process)
            return _timeout_result(
                dispatching,
                f"unexpected native helper event {kind!r}",
                helper_started=True,
            )
    except BaseException:
        return _uncertain(
            _CONTROL_LOST,
            "unknown",
            dispatch="attempted" if dispatching else "unknown",
        )
    finally:
        try:
            running = process.poll() is None
        except BaseException:
            running = True
        if running:
            try:
                _stop_process(process)
            except BaseException:
                # Control is already classified as uncertain; cleanup failure
                # cannot make replay safe or justify deleting the snapshot.
                pass


@contextmanager
def _serialized_send(deadline: float) -> Iterator[None]:
    """Serialize helper build and send across threads and processes."""
    private_mkdir(_SEND_LOCK.parent)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(_SEND_LOCK, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or (
            hasattr(os, "geteuid") and info.st_uid != os.geteuid()
        ):
            raise AirDropSnapshotError("AirDrop send lock is not a current-user regular file")
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if _remaining(deadline) <= 0:
                    raise TimeoutError("AirDrop send lock timeout")
                time.sleep(min(0.025, _remaining(deadline)))
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _create_attempt_snapshot(
    source: ValidatedFile, *, attempt_id: str, deadline: float
) -> AttemptSnapshot:
    """Clone, or safely copy, a pinned source fd into a private attempt dir."""
    if not _ATTEMPT_ID.fullmatch(attempt_id):
        raise AirDropSnapshotError("invalid AirDrop attempt ID")
    private_mkdir(_ATTEMPTS_ROOT)
    directory = _ATTEMPTS_ROOT / attempt_id
    try:
        os.mkdir(directory, 0o700)
    except FileExistsError as error:
        raise AirDropSnapshotError("AirDrop attempt ID already exists") from error
    destination = directory / source.path.name
    source_fd = -1
    directory_fd = -1
    method = ""
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        source_fd = os.open(source.path, flags)
        opened_before = os.fstat(source_fd)
        if (
            not stat.S_ISREG(opened_before.st_mode)
            or (
                opened_before.st_dev,
                opened_before.st_ino,
                opened_before.st_size,
                opened_before.st_mtime_ns,
                opened_before.st_ctime_ns,
            )
            != (
                source.device,
                source.inode,
                source.size,
                source.modified_ns,
                source.changed_ns,
            )
        ):
            raise AirDropSnapshotError("source changed before attempt snapshot creation")
        if _remaining(deadline) <= 0:
            raise AirDropSnapshotError("AirDrop timeout expired during snapshot creation")

        directory_fd = os.open(
            directory,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        method = _clone_from_fd(source_fd, directory_fd, destination.name)
        if not method:
            _copy_from_fd(
                source_fd,
                destination,
                expected_size=source.size,
                source_before=opened_before,
                deadline=deadline,
            )
            method = "bounded_fd_copy"
        elif _stat_signature(os.fstat(source_fd)) != _stat_signature(opened_before):
            raise AirDropSnapshotError("source changed during APFS snapshot clone")

        snapshot_fd = os.open(destination, flags)
        try:
            os.fchmod(snapshot_fd, 0o400)
            snap = os.fstat(snapshot_fd)
        finally:
            os.close(snapshot_fd)
        if not stat.S_ISREG(snap.st_mode) or snap.st_size != source.size:
            raise AirDropSnapshotError("attempt snapshot identity or size is invalid")
        if hasattr(os, "geteuid") and snap.st_uid != os.geteuid():
            raise AirDropSnapshotError("attempt snapshot is not owned by the current user")
        snapshot_file = ValidatedFile(
            path=destination,
            size=snap.st_size,
            device=snap.st_dev,
            inode=snap.st_ino,
            modified_ns=snap.st_mtime_ns,
            changed_ns=snap.st_ctime_ns,
            extension=source.extension,
            allowed_roots=(directory,),
        )
        return AttemptSnapshot(attempt_id, directory, snapshot_file, method)
    except BaseException:
        _cleanup_partial_snapshot(directory, destination)
        raise
    finally:
        if directory_fd >= 0:
            os.close(directory_fd)
        if source_fd >= 0:
            os.close(source_fd)


def _clone_from_fd(source_fd: int, directory_fd: int, basename: str) -> str:
    """Use APFS clone/COW when fclonefileat is available; otherwise signal fallback."""
    libc = ctypes.CDLL(None, use_errno=True)
    function = getattr(libc, "fclonefileat", None)
    if function is None:
        return ""
    function.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
    function.restype = ctypes.c_int
    if function(source_fd, directory_fd, os.fsencode(basename), 0) == 0:
        return "apfs_clone"
    error_number = ctypes.get_errno()
    try:
        os.stat(basename, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise AirDropSnapshotError("failed clone left an unexpected destination")
    if error_number in {
        errno.ENOSYS,
        errno.EXDEV,
        errno.EINVAL,
        getattr(errno, "ENOTSUP", errno.EINVAL),
        getattr(errno, "EOPNOTSUPP", errno.EINVAL),
    }:
        return ""
    raise AirDropSnapshotError(f"APFS snapshot clone failed: {os.strerror(error_number)}")


def _copy_from_fd(
    source_fd: int,
    destination: Path,
    *,
    expected_size: int,
    source_before: os.stat_result,
    deadline: float,
) -> None:
    """Bounded fallback: pinned fd, exclusive destination, and mutation checks."""
    os.lseek(source_fd, 0, os.SEEK_SET)
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    destination_fd = os.open(destination, flags, 0o600)
    copied = 0
    try:
        while copied < expected_size:
            if _remaining(deadline) <= 0:
                raise AirDropSnapshotError("AirDrop timeout expired during snapshot fallback copy")
            chunk = os.read(source_fd, min(_COPY_CHUNK_BYTES, expected_size - copied))
            if not chunk:
                raise AirDropSnapshotError("source ended during snapshot fallback copy")
            view = memoryview(chunk)
            while view:
                written = os.write(destination_fd, view)
                if written <= 0:
                    raise AirDropSnapshotError("snapshot fallback copy made no progress")
                view = view[written:]
                copied += written
        if os.read(source_fd, 1):
            raise AirDropSnapshotError("source grew during snapshot fallback copy")
        os.fchmod(destination_fd, 0o400)
    finally:
        os.close(destination_fd)

    source_after = os.fstat(source_fd)
    if _stat_signature(source_before) != _stat_signature(source_after):
        raise AirDropSnapshotError("source changed during snapshot fallback copy")


def _stat_signature(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _cleanup_partial_snapshot(directory: Path, destination: Path) -> None:
    try:
        info = destination.lstat()
    except FileNotFoundError:
        pass
    else:
        if stat.S_ISREG(info.st_mode) and (
            not hasattr(os, "geteuid") or info.st_uid == os.geteuid()
        ):
            destination.unlink()
    try:
        directory.rmdir()
    except OSError:
        pass


def _cleanup_snapshot(snapshot: AttemptSnapshot) -> str | None:
    """Remove only the exact snapshot identity and its now-empty attempt dir."""
    try:
        info = snapshot.file.path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or (info.st_dev, info.st_ino) != (snapshot.file.device, snapshot.file.inode)
        ):
            return "snapshot identity changed; retained for inspection"
        snapshot.file.path.unlink()
        snapshot.directory.rmdir()
        return None
    except OSError as error:
        return f"could not remove completed attempt snapshot: {error}"


def _remaining(deadline: float) -> float:
    return max(0.0, deadline - time.monotonic())


def _validate_roots(values: Sequence[str | os.PathLike[str]]) -> tuple[Path, ...]:
    if isinstance(values, (str, bytes, os.PathLike)) or not isinstance(values, Sequence) or not values:
        raise AirDropValidationError("allowed_roots must be a non-empty sequence")
    roots: list[Path] = []
    for value in values:
        if not isinstance(value, (str, os.PathLike)):
            raise AirDropValidationError("allowed root must be a string or path-like object")
        raw = os.fspath(value)
        root = Path(raw)
        if not root.is_absolute():
            raise AirDropValidationError("allowed roots must be absolute")
        canonical = root.resolve(strict=True)
        if root != Path(os.path.abspath(raw)) or canonical != root:
            raise AirDropValidationError("allowed roots must be canonical and contain no symlinks")
        broad_roots = {Path("/").resolve(), Path.home().resolve()}
        users_root = Path("/Users")
        if users_root.exists():
            broad_roots.add(users_root.resolve())
        if canonical in broad_roots:
            raise AirDropValidationError("allowed root is too broad")
        try:
            info = canonical.lstat()
        except OSError as error:
            raise AirDropValidationError("allowed root cannot be inspected") from error
        if not stat.S_ISDIR(info.st_mode):
            raise AirDropValidationError("allowed roots must be directories")
        if info.st_uid != os.getuid():
            raise AirDropValidationError("allowed roots must be owned by the current user")
        if has_extended_acl(canonical):
            raise AirDropValidationError("allowed roots must not carry an extended ACL")
        if stat.S_IMODE(info.st_mode) & 0o022:
            raise AirDropValidationError(
                "allowed roots must not be writable by group or other users"
            )
        roots.append(canonical)
    return tuple(dict.fromkeys(roots))


def _validate_extensions(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence) or not values:
        raise AirDropValidationError("allowed_extensions must be a non-empty sequence")
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or not _EXTENSION.fullmatch(value):
            raise AirDropValidationError("allowed extensions must look like '.pdf' or '.tar.gz'")
        folded = value.casefold()
        if folded not in {item.casefold() for item in result}:
            result.append(value)
    return tuple(sorted(result, key=len, reverse=True))


def _validate_receiver_configuration(
    receiver: str | None, selector: ExactReceiverSelector | None
) -> str | None:
    if receiver is not None:
        if not isinstance(receiver, str) or receiver != receiver.strip() or not receiver or "\x00" in receiver:
            raise AirDropValidationError("target_receiver must be an exact non-empty trimmed label")
    if (receiver is None) != (selector is None):
        raise AirDropValidationError(
            "target_receiver and an exact Accessibility selector must be configured together; "
            "NSSSharingService itself cannot select a recipient"
        )
    return receiver


def _call_selector_bounded(
    selector: ExactReceiverSelector, *, receiver: str, timeout_seconds: float
) -> AccessibilitySelection | None:
    if timeout_seconds <= 0:
        return None
    box: queue.Queue[AccessibilitySelection | BaseException] = queue.Queue(maxsize=1)

    def invoke() -> None:
        try:
            box.put(selector.select_exact_receiver(receiver=receiver, timeout_seconds=timeout_seconds))
        except BaseException as error:
            box.put(error)

    thread = threading.Thread(target=invoke, daemon=True)
    thread.start()
    try:
        value = box.get(timeout=timeout_seconds)
    except queue.Empty:
        return None
    return value if isinstance(value, AccessibilitySelection) else None


def _selection_is_exact(selection: AccessibilitySelection | None, receiver: str) -> bool:
    return bool(
        selection is not None
        and selection.requested_receiver == receiver
        and selection.observed_label == receiver
        and selection.exact_match_count == 1
        and selection.activated
    )


def _require_project_regular_file(path: Path) -> None:
    try:
        resolved = path.resolve(strict=True)
        info = path.lstat()
    except OSError as error:
        raise AirDropBuildError(f"missing project helper source: {path}") from error
    if resolved != path or not stat.S_ISREG(info.st_mode):
        raise AirDropBuildError(f"project helper source must be a regular non-symlink file: {path}")
    if not _is_below(path, REPO_ROOT):
        raise AirDropBuildError(f"helper source is outside the repository: {path}")


def _require_runtime_executable(path: Path) -> None:
    try:
        resolved = path.resolve(strict=True)
        info = path.lstat()
    except OSError as error:
        raise AirDropBuildError(f"native helper is missing: {path}") from error
    if resolved != path or not _is_below(path, RUNTIME_ROOT):
        raise AirDropBuildError("native helper must be a non-symlink path below .runtime")
    if not stat.S_ISREG(info.st_mode) or not os.access(path, os.X_OK):
        raise AirDropBuildError("native helper must be an executable regular file")
    if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
        raise AirDropBuildError("native helper is not owned by the current user")


def _is_below(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return path != root


def _positive_timeout(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0 or value > 600:
        raise AirDropValidationError(f"{name} must be greater than zero and at most 600 seconds")
    return float(value)


def _native_environment() -> dict[str, str]:
    """Keep session essentials while dropping loader and tool injection variables."""
    result = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}
    for name in (
        "HOME", "TMPDIR", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE",
        "DEVELOPER_DIR",
    ):
        value = os.environ.get(name)
        if value:
            result[name] = value
    return result


def _event_message(event: dict[str, Any], fallback: str) -> str:
    value = event.get("message")
    return value[:1000] if isinstance(value, str) and value else fallback


def _bounded_stderr(process: subprocess.Popen[str]) -> str:
    if process.stderr is None:
        return ""
    try:
        return process.stderr.read(4096).strip()
    except OSError:
        return ""


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=0.5)


def _failed_not_dispatched(reason: str) -> dict[str, Any]:
    return {
        "schema": _RESULT_SCHEMA,
        "status": "failed",
        "attempts": 0,
        "dispatch": "not_attempted",
        "error": reason,
    }


def _uncertain(
    reason: str, selection_state: str, *, dispatch: str = "attempted"
) -> dict[str, Any]:
    return {
        "schema": _RESULT_SCHEMA,
        "status": "uncertain",
        "attempts": 1,
        "dispatch": dispatch,
        "reason": reason,
        "receiver_selection": selection_state,
    }


def _timeout_result(
    dispatching: bool, reason: str, *, helper_started: bool = False
) -> dict[str, Any]:
    if dispatching:
        return _uncertain(reason, "unknown")
    if helper_started:
        # A host-side loss can race the helper's flushed pre-perform marker.
        # Without a native rejection, non-dispatch is not proven.
        return _uncertain(reason, "unknown", dispatch="unknown")
    return _failed_not_dispatched(reason)


__all__ = [
    "AccessibilitySelection",
    "AirDropBuildError",
    "AirDropError",
    "AirDropSnapshotError",
    "AirDropValidationError",
    "ExactReceiverSelector",
    "AttemptSnapshot",
    "ValidatedFile",
    "airdrop",
    "build_helper",
    "send_file",
    "validate_local_file",
]
