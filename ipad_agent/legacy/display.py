"""Legacy multi-application display semantics for compatibility callers.

Generated and local content goes to a private-LAN Now page. URLs, maps,
media, and native app launches use CoreDevice directly. Normal display never
starts XCTest or WebDriverAgent.
"""
from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import hashlib
import ipaddress
import json
import mimetypes
import os
from pathlib import Path
import signal
import socket
import stat
import subprocess
import sys
import time
from typing import Any, TYPE_CHECKING
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.error import HTTPError, URLError

from ipad_agent.transports.coredevice import open_ipad
from ipad_agent.core.paths import (
    REPO_ROOT, descriptor_has_extended_acl, private_mkdir, private_read_text,
    private_write_bytes, runtime_path,
)

if TYPE_CHECKING:
    from ipad_agent.core.config import Config
    from ipad_agent.core.registry import IntegrationRegistry

REPOSITORY_ROOT = REPO_ROOT
SERVER_MODULE = "ipad_agent.runtime.server"
RUNTIME_DIR = runtime_path("display")
META_PATH = RUNTIME_DIR / "server.json"
LOG_PATH = RUNTIME_DIR / "server.log"
OPS = {"t", "q", "r", "c", "d", "p", "u", "m", "v", "a", "s", "x"}
_DEVICE_CACHE: str | None = None
_FORCE_FOREGROUND = False


class IPadShowError(RuntimeError):
    """The display router could not confirm its promised outcome."""


def _private_ipv4(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
        networks = (ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("172.16.0.0/12"), ipaddress.ip_network("192.168.0.0/16"))
        return address.version == 4 and any(address in network for network in networks)
    except ValueError:
        return False


def _discover_host(config: "Config") -> str:
    configured = config.display_host
    if configured:
        if not _private_ipv4(configured):
            raise IPadShowError("IPAD_AGENT_DISPLAY_HOST must be a reachable private IPv4 address")
        return configured
    interfaces: list[str] = []
    try:
        route = subprocess.run(
            ["/sbin/route", "-n", "get", "default"], capture_output=True, text=True, timeout=3
        ).stdout
        for line in route.splitlines():
            if "interface:" in line:
                interfaces.append(line.split(":", 1)[1].strip())
    except (OSError, subprocess.TimeoutExpired):
        pass
    interfaces.extend(["en0", "en1", "en2", "en3"])
    for interface in dict.fromkeys(interfaces):
        try:
            result = subprocess.run(
                ["/usr/sbin/ipconfig", "getifaddr", interface], capture_output=True, text=True, timeout=3
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        candidate = result.stdout.strip()
        if result.returncode == 0 and _private_ipv4(candidate):
            return candidate
    try:
        candidates = {item[4][0] for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
    except socket.gaierror:
        candidates = set()
    private = sorted(value for value in candidates if _private_ipv4(value))
    if len(private) == 1:
        return private[0]
    raise IPadShowError("Could not select one private Mac IPv4 address; set IPAD_AGENT_DISPLAY_HOST")


def _read_meta() -> dict[str, Any] | None:
    try:
        value = json.loads(private_read_text(META_PATH))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    required = {"pid", "host", "port", "token"}
    return value if isinstance(value, dict) and required.issubset(value) else None


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _api(meta: dict[str, Any], method: str, path: str, body: dict[str, Any] | None = None, timeout: float = 3.0) -> Any:
    url = f"http://{meta['host']}:{meta['port']}{path}"
    data = None if body is None else json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()
    headers = {"Authorization": f"Bearer {meta['token']}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)
    with build_opener(_RejectRedirects()).open(request, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw) if raw else None


def _healthy(meta: dict[str, Any]) -> bool:
    try:
        value = _api(meta, "GET", "/health", timeout=.5)
        return isinstance(value, dict) and value.get("ok") is True and value.get("pid") == meta.get("pid")
    except (OSError, HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return False


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        waited, _ = os.waitpid(pid, os.WNOHANG)
        if waited == pid:
            return False
    except ChildProcessError:
        pass
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        state = subprocess.run(
            ["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True, timeout=1
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return True
    return bool(state) and not state.startswith("Z")


def _owned_server_pid(pid: int) -> bool:
    if not _pid_alive(pid):
        return False
    try:
        command = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=2
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    return f"-m {SERVER_MODULE}" in command and str(RUNTIME_DIR) in command


def _terminate_owned(meta: dict[str, Any], timeout: float = 3.0) -> bool:
    pid = int(meta.get("pid", 0) or 0)
    if not _pid_alive(pid):
        return True
    if not _owned_server_pid(pid):
        raise IPadShowError(f"refusing to terminate unverified process {pid}")
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(.025)
    return not _pid_alive(pid)


def _open_private_startup_lock():
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(RUNTIME_DIR / "startup.lock", flags, 0o600)
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & ~0o600
            or descriptor_has_extended_acl(descriptor)
        ):
            raise IPadShowError("legacy display startup lock is not private")
        return os.fdopen(descriptor, "a+", closefd=True)
    except BaseException:
        os.close(descriptor)
        raise


def _ensure_server(config: "Config") -> tuple[dict[str, Any], float, bool]:
    started = time.perf_counter()
    private_mkdir(RUNTIME_DIR)
    with _open_private_startup_lock() as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        meta = _read_meta()
        if meta and _healthy(meta):
            return meta, (time.perf_counter() - started) * 1000, False
        if meta:
            pid = int(meta.get("pid", 0) or 0)
            if _pid_alive(pid):
                if not _terminate_owned(meta):
                    raise IPadShowError(f"iPad display process {pid} did not stop")
            try:
                META_PATH.unlink()
            except FileNotFoundError:
                pass
        host = _discover_host(config)
        private_write_bytes(LOG_PATH, b"")
        log_fd = os.open(
            LOG_PATH,
            os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0),
        )
        log = os.fdopen(log_fd, "ab", buffering=0)
        process = subprocess.Popen(
            [sys.executable, "-m", SERVER_MODULE, "--host", host, "--port", str(config.display_port), "--runtime-dir", str(RUNTIME_DIR)],
            cwd=str(REPOSITORY_ROOT),
            stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True, close_fds=True,
        )
        log.close()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            meta = _read_meta()
            if meta and meta.get("pid") == process.pid and _healthy(meta):
                return meta, (time.perf_counter() - started) * 1000, True
            if process.poll() is not None:
                try:
                    detail = private_read_text(LOG_PATH, encoding="utf-8", max_bytes=2_000_000)[-1000:]
                except (OSError, ValueError, PermissionError, UnicodeError):
                    detail = ""
                raise IPadShowError(f"iPad display server exited during startup: {detail.strip()}")
            time.sleep(.025)
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
        raise IPadShowError("iPad display server did not become ready")


def _status(meta: dict[str, Any], timeout: float = 1.0) -> dict[str, Any]:
    value = _api(meta, "GET", "/api/status", timeout=timeout)
    if not isinstance(value, dict):
        raise IPadShowError("display status was not an object")
    return value


def _wait_ready(meta: dict[str, Any], revision: str, deadline: float) -> dict[str, Any] | None:
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        status = _status(meta, timeout=max(.01, min(1.0, remaining)))
        if status.get("ready_revision") == revision and status.get("visible") is True:
            return status
        time.sleep(.015)
    return None


def _launch(
    app: str, url: str | None, device: str | None,
    config: "Config", registry: "IntegrationRegistry",
):
    global _DEVICE_CACHE
    selected = device or config.device or _DEVICE_CACHE
    try:
        launch = open_ipad(
            app, url=url, device=selected, timeout=20.0,
            config=config, registry=registry,
        )
    except Exception:
        if device is None and config.device is None:
            _DEVICE_CACHE = None
        raise
    if device is None and config.device is None:
        _DEVICE_CACHE = launch.device_id
    return launch


def _display_context(
    config: "Config | None", registry: "IntegrationRegistry | None"
) -> tuple["Config", "IntegrationRegistry"]:
    if config is None:
        from ipad_agent.core.config import load_config
        config = load_config()
    if registry is None:
        from ipad_agent.core.registry import load_registry
        registry = load_registry(enabled_addons=config.enabled_addons)
    return config, registry


def _browser_identity(config: "Config", registry: "IntegrationRegistry") -> tuple[str, str]:
    from ipad_agent.core.registry import AddonNotEnabledError, IntegrationNotFoundError

    try:
        integration = registry.resolve(config.browser)
    except AddonNotEnabledError:
        raise
    except IntegrationNotFoundError as error:
        raise IPadShowError(
            f"configured browser must be an enabled browser integration ID: {config.browser!r}; "
            "exact bundle IDs are supported only by low-level ip/open"
        ) from error
    if integration.id != config.browser:
        raise IPadShowError(
            f"configured browser must use integration ID {integration.id!r}, not {config.browser!r}"
        )
    if integration.category != "browser":
        raise IPadShowError(f"configured integration is not a browser: {config.browser!r}")
    return integration.id, integration.bundle_id


def _remaining(deadline: float, cap: float) -> float:
    return max(.01, min(cap, deadline - time.monotonic()))


def _publish(
    payload: dict[str, Any], *, device: str | None, ready_timeout: float,
    config: "Config", registry: "IntegrationRegistry",
) -> dict[str, Any]:
    global _FORCE_FOREGROUND
    if ready_timeout <= 0:
        raise ValueError("ready_timeout must be positive")
    total_start = time.perf_counter()
    deadline = time.monotonic() + ready_timeout
    browser, _browser_bundle = _browser_identity(config, registry)
    meta, server_ms, server_started = _ensure_server(config)
    before = _status(meta, timeout=_remaining(deadline, 1.0))
    seen_age = before.get("last_seen_age_ms")
    recently_visible = (
        not _FORCE_FOREGROUND and not bool(before.get("invalidated"))
        and before.get("visible") is True and isinstance(seen_age, (int, float))
        and seen_age < 3000
    )
    publish_start = time.perf_counter()
    published = _api(
        meta, "POST", "/api/show", {"payload": payload},
        timeout=_remaining(deadline, 3.0),
    )
    publish_ms = (time.perf_counter() - publish_start) * 1000
    if not isinstance(published, dict) or not isinstance(published.get("revision"), str):
        raise IPadShowError("display server rejected the artifact")
    revision = published["revision"]

    # A visible page gets the first chance to acknowledge the new revision.
    grace = .30 if recently_visible else (.70 if server_started else 0.0)
    status = _wait_ready(meta, revision, min(deadline, time.monotonic() + grace)) if grace else None
    foreground_ms = 0.0
    launch_ms = 0.0
    foregrounded = False
    delivered_url = False

    if status is None and time.monotonic() < deadline:
        page_url = f"http://{meta['host']}:{meta['port']}/now#{meta['token']}"
        # Foreground the selected browser first, without URL delivery.  This
        # preserves tabs and gives an existing Now page a chance to respond.
        foreground_start = time.perf_counter()
        launch = _launch(browser, None, device, config, registry)
        foreground_ms += (time.perf_counter() - foreground_start) * 1000
        launch_ms += launch.elapsed_seconds * 1000
        foregrounded = True
        if launch.locked is True:
            return {
                "ok": False, "route": "now", "verified": "device-locked",
                "locked": True, "error": "the iPad is locked; Now was not delivered",
                "revision": revision, "foregrounded": False, "launch_accepted": True,
                "server_started": server_started,
                "timings_ms": {
                    "server": round(server_ms, 1), "publish": round(publish_ms, 1),
                    "foreground": round(foreground_ms, 1), "coredevice": round(launch_ms, 1),
                    "publish_to_ready": None,
                    "total": round((time.perf_counter() - total_start) * 1000, 1),
                },
            }
        _api(meta, "POST", "/api/activate", {}, timeout=_remaining(deadline, .5))
        _FORCE_FOREGROUND = False
        republished = _api(
            meta, "POST", "/api/show", {"payload": payload},
            timeout=_remaining(deadline, 3.0),
        )
        if not isinstance(republished, dict) or not isinstance(republished.get("revision"), str):
            raise IPadShowError("display server rejected the foreground revision")
        revision = republished["revision"]
        status = _wait_ready(meta, revision, min(deadline, time.monotonic() + 1.2))

        if status is None and time.monotonic() < deadline:
            # Deliver the fixed Now URL at most once, then publish a fresh
            # revision so a stale page cannot satisfy the acknowledgement.
            foreground_start = time.perf_counter()
            launch = _launch(browser, page_url, device, config, registry)
            delivered_url = True
            foreground_ms += (time.perf_counter() - foreground_start) * 1000
            launch_ms += launch.elapsed_seconds * 1000
            if launch.locked is True:
                return {
                    "ok": False, "route": "now", "verified": "device-locked",
                    "locked": True, "error": "the iPad is locked; Now was not confirmed",
                    "revision": revision, "foregrounded": False, "launch_accepted": True,
                    "server_started": server_started,
                    "url_delivered": True,
                    "timings_ms": {
                        "server": round(server_ms, 1), "publish": round(publish_ms, 1),
                        "foreground": round(foreground_ms, 1), "coredevice": round(launch_ms, 1),
                        "publish_to_ready": None,
                        "total": round((time.perf_counter() - total_start) * 1000, 1),
                    },
                }
            republished = _api(
                meta, "POST", "/api/show", {"payload": payload},
                timeout=_remaining(deadline, 3.0),
            )
            if not isinstance(republished, dict) or not isinstance(republished.get("revision"), str):
                raise IPadShowError("display server rejected the fallback revision")
            revision = republished["revision"]
            status = _wait_ready(meta, revision, deadline)

    if status is None:
        raise IPadShowError(
            f"{browser} accepted the Now recovery but revision {revision} did not become visible"
        )
    ready_ns = int(status.get("ready_ns", 0) or 0)
    published_ns = int(status.get("published_ns", 0) or 0)
    ready_ms = (ready_ns - published_ns) / 1_000_000 if ready_ns >= published_ns else None
    return {
        "ok": True,
        "route": "now",
        "verified": "browser-visible-ready",
        "revision": revision,
        "foregrounded": foregrounded,
        "url_delivered": delivered_url,
        "server_started": server_started,
        "peer": status.get("last_peer"),
        "timings_ms": {
            "server": round(server_ms, 1),
            "publish": round(publish_ms, 1),
            "foreground": round(foreground_ms, 1),
            "coredevice": round(launch_ms, 1),
            "publish_to_ready": round(ready_ms, 1) if ready_ms is not None else None,
            "total": round((time.perf_counter() - total_start) * 1000, 1),
        },
    }


def _direct_route(
    route: Any, *, device: str | None, config: "Config", registry: "IntegrationRegistry",
) -> dict[str, Any]:
    """Dispatch one policy-built route without exposing or reconstructing its URL."""
    from ipad_agent.transports.coredevice import open_validated_route_when_unlocked

    started = time.perf_counter()
    outcome = open_validated_route_when_unlocked(
        route, device=device, config=config, registry=registry,
    )
    if outcome.status == "locked":
        raise IPadShowError("iPad is locked")
    if outcome.status == "unknown":
        raise IPadShowError("iPad lock state is unavailable")
    launch = outcome.value
    if launch is None or launch.bundle_id != route.bundle_id:
        raise IPadShowError("CoreDevice returned an invalid route result")
    return {
        "ok": True, "route": "coredevice", "verified": "launch-accepted",
        "locked": launch.locked, "bundle": launch.bundle_id,
        "dispatch_accepted": True, "visible": False,
        "integration_id": route.integration_id, "action_id": route.action_id,
        "policy_sha256": route.policy_sha256, "url_shape": route.url_shape,
        "timings_ms": {
            "coredevice": round(launch.elapsed_seconds * 1000, 1),
            "total": round((time.perf_counter() - started) * 1000, 1),
        },
    }


def _direct(
    app: str, url: str | None = None, *, device: str | None = None,
    config: "Config", registry: "IntegrationRegistry",
) -> dict[str, Any]:
    global _FORCE_FOREGROUND
    started = time.perf_counter()
    launch = _launch(app, url, device, config, registry)
    _FORCE_FOREGROUND = True
    meta = _read_meta()
    if meta and _healthy(meta):
        try:
            _browser, browser_bundle = _browser_identity(config, registry)
            resume = "url" if launch.bundle_id == browser_bundle else "app"
            _api(meta, "POST", "/api/hide", {"resume": resume}, timeout=.5)
        except (OSError, HTTPError, URLError, TimeoutError):
            pass
    result = {
        "ok": True,
        "route": "coredevice",
        "verified": "device-locked" if launch.locked is True else "launch-accepted",
        "locked": launch.locked,
        "bundle": launch.bundle_id,
        "timings_ms": {
            "coredevice": round(launch.elapsed_seconds * 1000, 1),
            "total": round((time.perf_counter() - started) * 1000, 1),
        },
    }
    if launch.locked is True:
        # CoreDevice accepting dispatch does not prove foreground or render.
        result["foregrounded"] = False
        result["launch_accepted"] = True
    return result


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalize_report(value: object, title: str | None) -> dict[str, Any]:
    if isinstance(value, dict):
        report_title = str(value.get("title") or title or "Report")
        raw_sections = value.get("sections")
        if isinstance(raw_sections, list):
            sections = []
            for item in raw_sections:
                if isinstance(item, dict):
                    heading = str(item.get("heading") or "")
                    body = item.get("body", "")
                    if isinstance(body, list):
                        body = [str(part) for part in body]
                    else:
                        body = str(body)
                    sections.append({"heading": heading, "body": body})
            return {"kind": "report", "title": report_title, "sections": sections, "generated": _timestamp()}
        sections = [{"heading": str(key), "body": str(item)} for key, item in value.items() if key != "title"]
        return {"kind": "report", "title": report_title, "sections": sections, "generated": _timestamp()}
    if isinstance(value, (list, tuple)):
        sections = []
        for index, item in enumerate(value, 1):
            if isinstance(item, dict):
                sections.append({"heading": str(item.get("heading") or index), "body": item.get("body", "")})
            else:
                sections.append({"heading": str(index), "body": str(item)})
        return {"kind": "report", "title": title or "Report", "sections": sections, "generated": _timestamp()}
    return {"kind": "report", "title": title or "Report", "sections": [{"heading": "", "body": str(value)}], "generated": _timestamp()}


def _normalize_table(value: object, title: str | None) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        try:
            value = value.to_dict(orient="records")
        except TypeError:
            value = value.to_dict()
    if isinstance(value, dict):
        columns = [str(key) for key in value]
        rows = [[str(value[key]) for key in value]]
    elif isinstance(value, (list, tuple)) and value and all(isinstance(row, dict) for row in value):
        columns = list(dict.fromkeys(str(key) for row in value for key in row))
        rows = [[str(row.get(key, "")) for key in columns] for row in value]
    elif isinstance(value, (list, tuple)):
        rows = [[str(cell) for cell in row] if isinstance(row, (list, tuple)) else [str(row)] for row in value]
        width = max((len(row) for row in rows), default=1)
        columns = [str(index + 1) for index in range(width)]
    else:
        columns, rows = ["Value"], [[str(value)]]
    return {"kind": "table", "title": title or "Data", "columns": columns, "rows": rows, "generated": _timestamp()}


def _copy_asset(path: Path, meta: dict[str, Any]) -> tuple[str, str]:
    if not path.is_file():
        raise IPadShowError(f"local display file does not exist: {path}")
    maximum = int(os.environ.get("IPAD_AGENT_DISPLAY_MAX_ASSET_MB", "100")) * 1024 * 1024
    if path.stat().st_size > maximum:
        raise IPadShowError(f"local display assets are limited to {maximum // (1024 * 1024)} MiB")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    suffix = path.suffix.lower()
    name = f"{digest.hexdigest()[:24]}{suffix}"
    assets = private_mkdir(RUNTIME_DIR / "assets")
    target = assets / name
    if not target.exists() or target.stat().st_size != path.stat().st_size:
        private_write_bytes(target, path.read_bytes())
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    url = f"http://{meta['host']}:{meta['port']}/a/{meta['token']}/{name}"
    return url, mime


def show(op: object, *args: object, title: str | None = None, source: str | None = None,
         device: str | None = None, ready_timeout: float = 8.0,
         config: "Config | None" = None, registry: "IntegrationRegistry | None" = None,
         **options: object) -> dict[str, Any]:
    """Show one semantic artifact or destination on the iPad.

    Opcodes: t text, q quote, r report, c code, d table/data, p local file,
    u URL, m map destination, v video URL, a app launch, s status, x stop server.
    """
    config, registry = _display_context(config, registry)
    browser, _browser_bundle = _browser_identity(config, registry)
    inferred: str
    values = list(args)
    if isinstance(op, str) and op.casefold() in OPS:
        inferred = op.casefold()
    else:
        values.insert(0, op)
        if isinstance(op, Path) or (isinstance(op, str) and Path(op).expanduser().is_file()): inferred = "p"
        elif isinstance(op, str) and urlparse(op).scheme in {"http", "https"}: inferred = "u"
        elif isinstance(op, (dict, list, tuple)) or hasattr(op, "to_dict"): inferred = "r"
        else: inferred = "t"
    if inferred == "s":
        meta, server_ms, started = _ensure_server(config); status = _status(meta)
        revision = status.get("revision")
        return {"ok": True, "route": "now-status", "server_started": started, "visible": status.get("visible"), "revision": revision, "ready": bool(revision) and status.get("visible") is True and status.get("ready_revision") == revision, "timings_ms": {"total": round(server_ms, 1)}}
    if inferred == "x":
        meta = _read_meta()
        if not meta:
            return {"ok": True, "route": "now-stop", "stopped": False}
        pid = int(meta.get("pid", 0) or 0)
        if _healthy(meta):
            _api(meta, "POST", "/api/shutdown", {}, timeout=2.0)
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and _pid_alive(pid):
                time.sleep(.025)
        elif _pid_alive(pid):
            _terminate_owned(meta)
        stopped = not _pid_alive(pid)
        if not stopped:
            raise IPadShowError(f"iPad display process {pid} did not stop")
        try:
            LOG_PATH.unlink()
        except FileNotFoundError:
            pass
        return {"ok": True, "route": "now-stop", "stopped": True}
    if inferred == "u":
        url = str(values[0]) if values else ""
        target = str(options.get("app") or browser)
        url = registry.validate_v1_url(target, "open-url", url)
        return _direct(target, url, device=device, config=config, registry=registry)
    if inferred == "a":
        if not values: raise ValueError("show a requires an app name")
        return _direct(str(values[0]), device=device, config=config, registry=registry)
    if inferred == "m":
        if len(values) != 1: raise ValueError("show m requires exactly one destination")
        destination = values[0]
        directions = options.pop("directions", False)
        if not isinstance(directions, bool):
            raise ValueError("directions must be a boolean")
        route_options: dict[str, Any] = {}
        if directions:
            if options.get("origin") is not None: route_options["source"] = options.pop("origin")
            if options.get("mode") is not None: route_options["mode"] = options.pop("mode")
            command = "directions"
        else:
            if "origin" in options or "mode" in options:
                raise ValueError("origin and mode require directions=True")
            command = "search"
        if options:
            raise ValueError("show m received unknown options: " + ", ".join(sorted(options)))
        route = registry.resolve_url_route("maps", command, (destination,), route_options)
        return _direct_route(route, device=device, config=config, registry=registry)
    if inferred == "v":
        if not values: raise ValueError("show v requires a video URL")
        url = str(values[0]); parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}: raise ValueError("video URL must be http(s)")
        at = options.get("at")
        if at is not None:
            query = dict(parse_qsl(parsed.query, keep_blank_values=True)); query["t"] = f"{int(float(at))}s"; parsed = parsed._replace(query=urlencode(query)); url = urlunparse(parsed)
        target = str(options.get("app") or browser)
        url = registry.validate_v1_url(target, "open-url", url)
        return _direct(target, url, device=device, config=config, registry=registry)
    if inferred == "p":
        if not values: raise ValueError("show p requires a local file path")
        path = Path(str(values[0])).expanduser().resolve()
        if not path.is_file():
            raise IPadShowError(f"local display file does not exist: {path}")
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if mime.startswith("text/") or path.suffix.casefold() in {".md", ".json", ".csv", ".log"}:
            if path.stat().st_size > 2 * 1024 * 1024:
                raise IPadShowError("text display files are limited to 2 MiB")
            payload = {"kind": "code" if path.suffix.casefold() in {".json", ".csv", ".log"} else "text", "title": title or path.name, "text": path.read_text(errors="replace"), "generated": _timestamp()}
        else:
            meta, _, _ = _ensure_server(config); url, mime = _copy_asset(path, meta)
            payload = {"kind": "file", "title": title or path.name, "name": path.name, "url": url, "mime": mime, "caption": str(options.get("caption") or ""), "generated": _timestamp()}
        return _publish(payload, device=device, ready_timeout=ready_timeout, config=config, registry=registry)
    if not values: raise ValueError(f"show {inferred} requires content")
    if inferred == "q":
        text = str(values[0]); quote_source = str(values[1]) if len(values) > 1 else (source or ""); payload = {"kind": "quote", "title": title or "", "text": text, "source": quote_source, "generated": _timestamp()}
    elif inferred == "r": payload = _normalize_report(values[0], title)
    elif inferred == "c": payload = {"kind": "code", "title": title or "Code", "text": str(values[0]), "generated": _timestamp()}
    elif inferred == "d": payload = _normalize_table(values[0], title)
    else: payload = {"kind": "text", "title": title or "", "text": str(values[0]), "generated": _timestamp()}
    return _publish(payload, device=device, ready_timeout=ready_timeout, config=config, registry=registry)


__all__ = ["IPadShowError", "show"]
