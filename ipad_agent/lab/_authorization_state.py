"""Owner-private, repository-local consumption receipts for physical grants."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any, Mapping

from ipad_agent.core.paths import descriptor_has_extended_acl


_RECEIPT_DIRECTORY = (".runtime", "state", "physical-authorizations")


def _open_directory(path: Path) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise PermissionError("authorization receipt repository root is not a safe directory") from error
    details = os.fstat(descriptor)
    if details.st_uid != os.getuid() or descriptor_has_extended_acl(descriptor):
        os.close(descriptor)
        raise PermissionError("authorization receipt repository root must be owned without an extended ACL")
    return descriptor


def _open_private_child(parent: int, name: str) -> int:
    try:
        os.mkdir(name, 0o700, dir_fd=parent)
    except FileExistsError:
        pass
    except OSError as error:
        raise PermissionError("authorization receipt directory could not be created safely") from error
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        descriptor = os.open(name, flags, dir_fd=parent)
    except OSError as error:
        raise PermissionError("authorization receipt directory is not a safe directory") from error
    details = os.fstat(descriptor)
    if (
        details.st_uid != os.getuid()
        or stat.S_IMODE(details.st_mode) & 0o077
        or descriptor_has_extended_acl(descriptor)
    ):
        os.close(descriptor)
        raise PermissionError("authorization receipt directories must be owner-private")
    return descriptor


def consume_authorization_receipt(
    repository_root: str | Path, authorization_id: str, receipt: Mapping[str, Any],
) -> Path:
    """Atomically create the durable one-use receipt or reject an existing grant."""
    root = Path(repository_root).expanduser().absolute()
    descriptors: list[int] = []
    created = False
    filename = f"{authorization_id}.json"
    try:
        current = _open_directory(root)
        descriptors.append(current)
        for component in _RECEIPT_DIRECTORY:
            current = _open_private_child(current, component)
            descriptors.append(current)
        payload = json.dumps(
            dict(receipt), sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8") + b"\n"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        try:
            output = os.open(filename, flags, 0o600, dir_fd=current)
        except FileExistsError as error:
            raise PermissionError("physical authorization has already been consumed") from error
        except OSError as error:
            raise PermissionError("physical authorization receipt could not be created safely") from error
        created = True
        try:
            details = os.fstat(output)
            if (
                details.st_uid != os.getuid()
                or stat.S_IMODE(details.st_mode) != 0o600
                or descriptor_has_extended_acl(output)
            ):
                raise PermissionError("physical authorization receipt must be owner-private")
            view = memoryview(payload)
            while view:
                written = os.write(output, view)
                if written <= 0:
                    raise OSError("short authorization receipt write")
                view = view[written:]
            os.fsync(output)
        finally:
            os.close(output)
        os.fsync(current)
    except Exception:
        # Once O_EXCL succeeds, retain even a failed/partial receipt: fail closed
        # rather than restoring authority after an uncertain local write.
        raise
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
    if not created:  # pragma: no cover - every non-created path raises above
        raise PermissionError("physical authorization was not consumed")
    return root.joinpath(*_RECEIPT_DIRECTORY, filename)


__all__ = ["consume_authorization_receipt"]
