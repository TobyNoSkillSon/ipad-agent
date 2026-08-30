"""Strict, side-effect-free configuration for the iPad controller."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import errno
import ipaddress
import json
import os
from pathlib import Path
import stat
import tomllib
from typing import Any, Mapping

from .paths import CACHE_DIR, DEFAULT_CONFIG_PATH, RUNTIME_ROOT

# Compatibility names for modules that have not yet moved to ipad_agent.paths.
DEFAULT_SUPPORT_DIR = RUNTIME_ROOT
DEFAULT_CACHE_DIR = CACHE_DIR

_DEFAULT_BROWSER = "safari"
_DEFAULT_DISPLAY_PORT = 8766
_DEFAULT_APPIUM_URL = "http://127.0.0.1:4723"
_DEFAULT_AIRDROP_TIMEOUT = 120
_CONFIG_SNAPSHOT_SCHEMA = "ipad-agent.config-snapshot/v3"
_LEGACY_BROWSER_MIGRATION = (
    "legacy browser bundle overrides are unsupported; set apps.browser (or "
    "IPAD_AGENT_BROWSER) to an enabled browser integration ID such as 'safari'; "
    "use an exact bundle ID only with low-level ip/open"
)
_LEGACY_BROWSER_SNAPSHOT_KEYS = frozenset({
    "browser_bundle", "_browser_bundle", "browser_bundle_override",
    "_browser_bundle_override",
})
_LEGACY_BROWSER_ENV_KEYS = frozenset({"IPAD_AGENT_BROWSER_BUNDLE"})
_RFC1918_NETWORKS = tuple(
    ipaddress.ip_network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


class ConfigError(ValueError):
    """Raised when configuration is malformed or unsafe."""


@dataclass(frozen=True)
class Config:
    device: str | None = None
    browser: str = _DEFAULT_BROWSER
    enabled_addons: list[str] = field(default_factory=list)
    bundle_aliases: dict[str, str] = field(default_factory=dict)
    display_host: str | None = None
    display_port: int = _DEFAULT_DISPLAY_PORT
    appium: str | None = None
    appium_url: str = _DEFAULT_APPIUM_URL
    team_id: str | None = None
    wda_bundle_id: str | None = None
    xctestrun: str | None = None
    # Host-local only: these fields are intentionally absent from daemon snapshots.
    airdrop_allowed_roots: list[str] = field(default_factory=list)
    airdrop_allowed_extensions: list[str] = field(default_factory=list)
    airdrop_max_bytes: int | None = None
    airdrop_timeout_seconds: int = _DEFAULT_AIRDROP_TIMEOUT

    def __post_init__(self) -> None:
        _enforce_addon_alias_gates(self.enabled_addons, self.bundle_aliases)
        canonical_browser = _canonical_browser_id(
            self.browser, self.enabled_addons, reject_disabled=False
        )
        if canonical_browser != self.browser:
            object.__setattr__(self, "browser", canonical_browser)

    @property
    def device_id(self) -> str | None:
        """Explicit CoreDevice identifier, when one was configured."""
        return self.device

    @property
    def app_aliases(self) -> dict[str, str]:
        """Backward-compatible name for low-level bundle aliases."""
        return self.bundle_aliases

    @property
    def browser_bundle(self) -> str:
        """Return the primary bundle for the configured browser integration ID."""
        from .registry import IntegrationNotFoundError, load_registry

        registry = load_registry(enabled_addons=self.enabled_addons)
        try:
            integration = registry.resolve(self.browser)
        except IntegrationNotFoundError as error:
            raise ConfigError(
                f"configured browser must be an enabled browser integration ID: {self.browser!r}"
            ) from error
        if integration.id != self.browser:
            raise ConfigError(
                f"configured browser must use integration ID {integration.id!r}, not {self.browser!r}"
            )
        if integration.category != "browser":
            raise ConfigError(f"configured integration is not a browser: {self.browser!r}")
        return integration.bundle_id

    @property
    def profiles(self) -> None:
        """Retained temporarily for callers that still inspect this field."""
        return None


def load_config(
    path: str | os.PathLike[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Config:
    """Load and validate config, then apply typed environment overrides.

    The default file is ``.runtime/config/config.toml``.  A path supplied by
    ``IPAD_AGENT_CONFIG`` is treated as private application state and therefore
    must be an owner-only regular file.  An explicit function argument is a
    trusted fixture/input path, but is still forbidden from being a symlink or
    non-regular file.
    """
    source_environment: Mapping[str, str] = os.environ if environ is None else environ
    selected, require_private = _select_path(path, source_environment)
    raw = _read_toml(selected, require_private=require_private)
    config = _parse_document(raw)
    return _apply_overrides(config, source_environment)


def config_snapshot(config: Config) -> dict[str, Any]:
    """Return a strict JSON-safe snapshot for a detached runtime process."""
    if not isinstance(config, Config):
        raise TypeError("config must be a Config")
    return {
        "schema": _CONFIG_SNAPSHOT_SCHEMA,
        "device": config.device,
        "browser": config.browser,
        "enabled_addons": list(config.enabled_addons),
        "bundle_aliases": dict(config.bundle_aliases),
        "display_host": config.display_host,
        "display_port": config.display_port,
        "appium": config.appium,
        "appium_url": config.appium_url,
        "team_id": config.team_id,
        "wda_bundle_id": config.wda_bundle_id,
        "xctestrun": config.xctestrun,
    }


def config_from_snapshot(value: Mapping[str, Any]) -> Config:
    """Validate and restore a detached-runtime config snapshot."""
    if not isinstance(value, Mapping):
        raise ConfigError("config snapshot must be an object")
    legacy_keys = sorted(str(key) for key in set(value) & _LEGACY_BROWSER_SNAPSHOT_KEYS)
    if legacy_keys:
        raise ConfigError(
            f"{_LEGACY_BROWSER_MIGRATION} (snapshot key(s): {', '.join(legacy_keys)})"
        )
    if value.get("schema") in {
        "ipad-agent.config-snapshot/v1", "ipad-agent.config-snapshot/v2"
    }:
        raise ConfigError(
            f"legacy config snapshots are unsupported; {_LEGACY_BROWSER_MIGRATION}"
        )
    expected = {
        "schema", "device", "browser", "enabled_addons", "bundle_aliases",
        "display_host", "display_port", "appium", "appium_url", "team_id",
        "wda_bundle_id", "xctestrun",
    }
    unknown = set(value) - expected
    missing = expected - set(value)
    if missing or unknown:
        details = []
        if missing:
            details.append("missing " + ", ".join(sorted(missing)))
        if unknown:
            details.append("unknown " + ", ".join(sorted(str(item) for item in unknown)))
        raise ConfigError("invalid config snapshot: " + "; ".join(details))
    if value.get("schema") != _CONFIG_SNAPSHOT_SCHEMA:
        raise ConfigError("unsupported config snapshot schema")
    config = Config(
        device=_optional_string(value.get("device"), "snapshot.device"),
        browser=_required_string(value.get("browser"), "snapshot.browser"),
        enabled_addons=_string_list(value.get("enabled_addons"), "snapshot.enabled_addons"),
        bundle_aliases=_string_mapping(value.get("bundle_aliases"), "snapshot.bundle_aliases"),
        display_host=_optional_string(value.get("display_host"), "snapshot.display_host"),
        display_port=_integer(value.get("display_port"), "snapshot.display_port"),
        appium=_optional_string(value.get("appium"), "snapshot.appium"),
        appium_url=_required_string(value.get("appium_url"), "snapshot.appium_url"),
        team_id=_optional_string(value.get("team_id"), "snapshot.team_id"),
        wda_bundle_id=_optional_string(value.get("wda_bundle_id"), "snapshot.wda_bundle_id"),
        xctestrun=_optional_string(value.get("xctestrun"), "snapshot.xctestrun"),
    )
    return _validate(config)


def environment_for(config: Config, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build a subprocess environment without mutating ``os.environ``."""
    result = dict(os.environ if base is None else base)
    legacy_keys = sorted(_LEGACY_BROWSER_ENV_KEYS & result.keys())
    if legacy_keys:
        raise ConfigError(
            f"{_LEGACY_BROWSER_MIGRATION} (environment: {', '.join(legacy_keys)})"
        )
    values: dict[str, str | None] = {
        "IPAD_AGENT_DEVICE": config.device,
        "IPAD_AGENT_BROWSER": config.browser if config.browser != _DEFAULT_BROWSER else None,
        "IPAD_AGENT_ENABLED_ADDONS": (
            json.dumps(config.enabled_addons, separators=(",", ":")) if config.enabled_addons else None
        ),
        "IPAD_AGENT_BUNDLE_ALIASES": (
            json.dumps(config.bundle_aliases, separators=(",", ":")) if config.bundle_aliases else None
        ),
        "IPAD_AGENT_DISPLAY_HOST": config.display_host,
        "IPAD_AGENT_DISPLAY_PORT": (
            str(config.display_port) if config.display_port != _DEFAULT_DISPLAY_PORT else None
        ),
        "IPAD_AGENT_APPIUM": config.appium,
        "IPAD_AGENT_APPIUM_URL": config.appium_url if config.appium_url != _DEFAULT_APPIUM_URL else None,
        "IPAD_AGENT_TEAM_ID": config.team_id,
        "IPAD_AGENT_WDA_BUNDLE_ID": config.wda_bundle_id,
        "IPAD_AGENT_XCTESTRUN": config.xctestrun,
    }
    for name, value in values.items():
        if value is not None:
            result.setdefault(name, value)
    return result


def apply_environment(config: Config) -> dict[str, str]:
    """Compatibility wrapper returning, rather than applying, an environment.

    Older package code calls this during import.  Keeping it pure guarantees
    that importing :mod:`ipad_agent` cannot mutate process environment state.
    """
    return environment_for(config)


def _select_path(
    path: str | os.PathLike[str] | None,
    environment: Mapping[str, str],
) -> tuple[Path, bool]:
    if path is not None:
        if isinstance(path, (str, os.PathLike)):
            return Path(path).expanduser(), False
        raise TypeError("config path must be a string or path-like object")
    configured = environment.get("IPAD_AGENT_CONFIG")
    if configured is None:
        return DEFAULT_CONFIG_PATH, True
    if not isinstance(configured, str) or not configured.strip():
        raise ConfigError("IPAD_AGENT_CONFIG must be a non-empty path")
    return Path(configured).expanduser(), True


def _read_toml(path: Path, *, require_private: bool) -> dict[str, Any]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        return {}
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise ConfigError(f"config file must not be a symlink: {path}") from error
        raise ConfigError(f"cannot open config file {path}: {error.strerror or error}") from error

    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise ConfigError(f"config file must be a regular file: {path}")
        if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
            raise ConfigError(f"config file is not owned by the current user: {path}")
        if require_private and stat.S_IMODE(info.st_mode) & ~0o600:
            raise ConfigError(f"config file permissions must be owner-only: {path}")
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = -1
            try:
                parsed = tomllib.load(handle)
            except tomllib.TOMLDecodeError as error:
                raise ConfigError(f"invalid TOML in {path}: {error}") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not isinstance(parsed, dict):  # tomllib currently guarantees this.
        raise ConfigError("config document must be a table")
    return parsed


def _parse_document(raw: dict[str, Any]) -> Config:
    _known_keys(raw, {"device", "apps", "addons", "display", "automation", "airdrop"}, "root")
    device = _section(raw, "device", {"id"})
    raw_apps = raw.get("apps", {})
    if isinstance(raw_apps, dict) and "browser_bundle" in raw_apps:
        raise ConfigError(f"apps.browser_bundle is unsupported; {_LEGACY_BROWSER_MIGRATION}")
    apps = _section(raw, "apps", {"browser", "aliases"})
    addons = _section(raw, "addons", {"enabled"})
    display = _section(raw, "display", {"host", "port"})
    automation = _section(
        raw,
        "automation",
        {"appium", "appium_url", "team_id", "wda_bundle_id", "xctestrun"},
    )
    airdrop = _section(
        raw,
        "airdrop",
        {"allowed_roots", "allowed_extensions", "max_bytes", "timeout_seconds"},
    )

    aliases_value = apps.get("aliases", {})
    aliases = _string_mapping(aliases_value, "apps.aliases")
    enabled = _string_list(addons.get("enabled", []), "addons.enabled")
    config = Config(
        device=_optional_string(device.get("id"), "device.id"),
        browser=_required_string(apps.get("browser", _DEFAULT_BROWSER), "apps.browser"),
        enabled_addons=enabled,
        bundle_aliases=aliases,
        display_host=_optional_string(display.get("host"), "display.host"),
        display_port=_integer(display.get("port", _DEFAULT_DISPLAY_PORT), "display.port"),
        appium=_optional_string(automation.get("appium"), "automation.appium"),
        appium_url=_required_string(
            automation.get("appium_url", _DEFAULT_APPIUM_URL), "automation.appium_url"
        ),
        team_id=_optional_string(automation.get("team_id"), "automation.team_id"),
        wda_bundle_id=_optional_string(
            automation.get("wda_bundle_id"), "automation.wda_bundle_id"
        ),
        xctestrun=_optional_string(automation.get("xctestrun"), "automation.xctestrun"),
        airdrop_allowed_roots=_string_list(
            airdrop.get("allowed_roots", []), "airdrop.allowed_roots"
        ),
        airdrop_allowed_extensions=_string_list(
            airdrop.get("allowed_extensions", []), "airdrop.allowed_extensions"
        ),
        airdrop_max_bytes=_optional_integer(
            airdrop.get("max_bytes"), "airdrop.max_bytes"
        ),
        airdrop_timeout_seconds=_integer(
            airdrop.get("timeout_seconds", _DEFAULT_AIRDROP_TIMEOUT),
            "airdrop.timeout_seconds",
        ),
    )
    return config


def _apply_overrides(config: Config, environment: Mapping[str, str]) -> Config:
    legacy_keys = sorted(_LEGACY_BROWSER_ENV_KEYS & environment.keys())
    if legacy_keys:
        raise ConfigError(
            f"{_LEGACY_BROWSER_MIGRATION} (environment: {', '.join(legacy_keys)})"
        )
    text_fields = {
        "device": ("IPAD_AGENT_DEVICE", True),
        "browser": ("IPAD_AGENT_BROWSER", False),
        "display_host": ("IPAD_AGENT_DISPLAY_HOST", True),
        "appium": ("IPAD_AGENT_APPIUM", True),
        "appium_url": ("IPAD_AGENT_APPIUM_URL", False),
        "team_id": ("IPAD_AGENT_TEAM_ID", True),
        "wda_bundle_id": ("IPAD_AGENT_WDA_BUNDLE_ID", True),
        "xctestrun": ("IPAD_AGENT_XCTESTRUN", True),
    }
    changes: dict[str, Any] = {}
    for field_name, (name, optional) in text_fields.items():
        if name not in environment:
            continue
        raw = environment[name]
        if not isinstance(raw, str):
            raise ConfigError(f"{name} must be a string")
        changes[field_name] = (
            _optional_string(raw, name) if optional else _required_string(raw, name)
        )

    if "IPAD_AGENT_DISPLAY_PORT" in environment:
        raw_port = environment["IPAD_AGENT_DISPLAY_PORT"]
        if not isinstance(raw_port, str) or not raw_port or not raw_port.isascii() or not raw_port.isdecimal():
            raise ConfigError("IPAD_AGENT_DISPLAY_PORT must be a decimal integer")
        changes["display_port"] = int(raw_port, 10)

    if "IPAD_AGENT_ENABLED_ADDONS" in environment:
        changes["enabled_addons"] = _json_string_list(
            environment["IPAD_AGENT_ENABLED_ADDONS"], "IPAD_AGENT_ENABLED_ADDONS"
        )

    alias_names = [
        name
        for name in ("IPAD_AGENT_BUNDLE_ALIASES", "IPAD_AGENT_APP_ALIASES")
        if name in environment
    ]
    if len(alias_names) > 1:
        raise ConfigError("set only IPAD_AGENT_BUNDLE_ALIASES, not both bundle alias overrides")
    if alias_names:
        name = alias_names[0]
        changes["bundle_aliases"] = _json_string_mapping(environment[name], name)

    return _validate(replace(config, **changes))


def _canonical_browser_id(
    browser: str,
    enabled_addons: list[str],
    *,
    reject_disabled: bool,
) -> str:
    """Canonicalize enabled browser aliases without enabling an addon implicitly."""
    text = _required_string(browser, "apps.browser")
    if text == _DEFAULT_BROWSER:
        return text

    from .registry import (
        AddonNotEnabledError,
        IntegrationNotFoundError,
        RegistryError,
        load_registry,
    )

    try:
        integration = load_registry().resolve(text)
    except AddonNotEnabledError:
        integration = None
    except IntegrationNotFoundError:
        return text
    except RegistryError as error:
        raise ConfigError(f"cannot resolve configured browser: {error}") from error
    else:
        if integration.category != "browser":
            return text
        if text.casefold() in {bundle.casefold() for bundle in integration.bundle_ids}:
            return text
        return integration.id

    for enabled_reference in enabled_addons:
        try:
            registry = load_registry(enabled_addons=[enabled_reference])
        except RegistryError as error:
            # Unknown addon names remain deferred so setup can install them later.
            if str(error).startswith("unknown addon(s):"):
                continue
            raise ConfigError(f"cannot resolve configured browser: {error}") from error
        try:
            integration = registry.resolve(text)
        except AddonNotEnabledError:
            continue
        except IntegrationNotFoundError:
            continue
        if integration.category != "browser":
            return text
        if text.casefold() in {bundle.casefold() for bundle in integration.bundle_ids}:
            return text
        return integration.id

    if reject_disabled:
        raise ConfigError(
            f"configured browser belongs to a disabled addon: {text!r}; "
            "enable the addon explicitly in addons.enabled"
        )
    return text


def _enforce_addon_alias_gates(
    enabled_addons: list[str],
    bundle_aliases: Mapping[str, str],
) -> None:
    """Reject low-level routes to known addon bundles unless enabled.

    Only index metadata is consulted.  Disabled addon manifests are never read
    as a side effect of parsing configuration.
    """
    candidates = list(bundle_aliases.values())
    if not candidates:
        return
    from .registry import RegistryError, indexed_addon_for_bundle, normalize_name

    enabled_references = {normalize_name(item) for item in enabled_addons}
    for bundle in candidates:
        try:
            owner = indexed_addon_for_bundle(bundle)
        except RegistryError as error:
            raise ConfigError(f"cannot validate addon bundle aliases: {error}") from error
        if owner is None:
            continue
        addon_id, aliases = owner
        accepted = {normalize_name(addon_id), *(normalize_name(alias) for alias in aliases)}
        if enabled_references.isdisjoint(accepted):
            raise ConfigError(
                f"bundle {bundle!r} belongs to disabled addon {addon_id!r}; enable the addon instead of using a low-level alias"
            )


def _validate(config: Config) -> Config:
    _enforce_addon_alias_gates(config.enabled_addons, config.bundle_aliases)
    canonical_browser = _canonical_browser_id(
        config.browser, config.enabled_addons, reject_disabled=True
    )
    if canonical_browser != config.browser:
        object.__setattr__(config, "browser", canonical_browser)
    if not 1 <= config.display_port <= 65535:
        raise ConfigError("display port must be between 1 and 65535")
    if config.display_host is not None:
        try:
            address = ipaddress.ip_address(config.display_host)
        except ValueError as error:
            raise ConfigError("display host must be an RFC1918 IPv4 address") from error
        if address.version != 4 or not any(address in network for network in _RFC1918_NETWORKS):
            raise ConfigError("display host must be an RFC1918 IPv4 address")

    policy_parts = (
        bool(config.airdrop_allowed_roots),
        bool(config.airdrop_allowed_extensions),
        config.airdrop_max_bytes is not None,
    )
    if any(policy_parts) and not all(policy_parts):
        raise ConfigError(
            "airdrop allowed_roots, allowed_extensions, and max_bytes must be configured together"
        )
    if config.airdrop_max_bytes is not None and config.airdrop_max_bytes < 1:
        raise ConfigError("airdrop max_bytes must be positive")
    if not 1 <= config.airdrop_timeout_seconds <= 600:
        raise ConfigError("airdrop timeout_seconds must be between 1 and 600")
    for root in config.airdrop_allowed_roots:
        if not Path(root).is_absolute():
            raise ConfigError("airdrop allowed_roots must contain absolute paths")
    for extension in config.airdrop_allowed_extensions:
        if not extension.startswith(".") or "/" in extension or "\\" in extension:
            raise ConfigError("airdrop allowed_extensions must contain dotted file extensions")
    return config


def _section(raw: dict[str, Any], name: str, keys: set[str]) -> dict[str, Any]:
    value = raw.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"{name} must be a table")
    _known_keys(value, keys, name)
    return value


def _known_keys(value: dict[str, Any], allowed: set[str], location: str) -> None:
    unknown = sorted(key for key in value if not isinstance(key, str) or key not in allowed)
    if unknown:
        rendered = ", ".join(repr(key) for key in unknown)
        raise ConfigError(f"unknown {location} configuration key(s): {rendered}")


def _optional_string(value: Any, location: str) -> str | None:
    if value is None or value == "":
        return None
    return _required_string(value, location)


def _required_string(value: Any, location: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{location} must be a string")
    if not value.strip() or value != value.strip() or "\x00" in value:
        raise ConfigError(f"{location} must be a non-empty trimmed string")
    return value


def _integer(value: Any, location: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{location} must be an integer")
    return value


def _optional_integer(value: Any, location: str) -> int | None:
    if value is None:
        return None
    return _integer(value, location)


def _string_list(value: Any, location: str) -> list[str]:
    if not isinstance(value, list):
        raise ConfigError(f"{location} must be a list of strings")
    result = [_required_string(item, f"{location} item") for item in value]
    normalized = [" ".join(item.casefold().replace("_", " ").replace("-", " ").split()) for item in result]
    if len(normalized) != len(set(normalized)):
        raise ConfigError(f"{location} must not contain normalized duplicates")
    return result


def _string_mapping(value: Any, location: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ConfigError(f"{location} must map names to bundle IDs")
    result: dict[str, str] = {}
    for key, item in value.items():
        clean_key = _required_string(key, f"{location} name")
        result[clean_key] = _required_string(item, f"{location}.{clean_key}")
    return result


def _decode_json(value: Any, location: str) -> Any:
    if not isinstance(value, str):
        raise ConfigError(f"{location} must be a JSON string")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ConfigError(f"{location} contains duplicate key {key!r}")
            result[key] = item
        return result

    try:
        return json.loads(value, object_pairs_hook=reject_duplicate_keys)
    except json.JSONDecodeError as error:
        raise ConfigError(f"{location} must contain valid JSON") from error


def _json_string_list(value: Any, location: str) -> list[str]:
    return _string_list(_decode_json(value, location), location)


def _json_string_mapping(value: Any, location: str) -> dict[str, str]:
    return _string_mapping(_decode_json(value, location), location)


__all__ = [
    "Config",
    "ConfigError",
    "DEFAULT_CACHE_DIR",
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_SUPPORT_DIR",
    "apply_environment",
    "config_from_snapshot",
    "config_snapshot",
    "environment_for",
    "load_config",
]
