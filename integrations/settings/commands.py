"""CoreDevice-only Settings navigation for one exact model/build profile."""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from ipad_agent.core import commands as shared


COMMANDS = (
    "open",
    "general",
    "about",
    "wifi",
    "bluetooth",
    "battery",
    "accessibility",
    "show",
)

_SHORTCUTS = {
    "general": "general",
    "about": "general-about",
    "wifi": "wi-fi",
    "bluetooth": "bluetooth",
    "battery": "battery",
    "accessibility": "accessibility",
}

_PROVEN_ROUTE_IDS = frozenset(
    {
        "accessibility",
        "accessibility-motion-title",
        "apps-com-apple-mobilesafari",
        "apps-com-apple-mobilesafari-row-private-browsing-uses-normal-browsing-search-engine-selection",
        "battery",
        "bluetooth",
        "general",
        "general-about",
        "general-international",
        "general-keyboard",
        "wi-fi",
    }
)
_PROFILE_REF = "device-profiles/ipad-pro-11-inch-m5-wifi-ipados-26.6.1-23g83.json"
_DIRECTORY = Path(__file__).parent
_PROFILE_PATH = _DIRECTORY / _PROFILE_REF
_CATALOG_PATH = _DIRECTORY / "route-catalog.json"
_PROFILE_SCHEMA = "ipad-agent.settings-device-profile/v1"
_CATALOG_SCHEMA = "ipad-agent.settings-route-catalog/v2"
_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_AUTHORITY = re.compile(r"^com\.apple\.Settings(?:\.[A-Za-z0-9][A-Za-z0-9.]*)?$")
_ALLOWED_KINDS = {"page", "row", "action", "dynamic"}
_ALLOWED_POLICIES = {"normal", "explicit", "blocked"}
_ALLOWED_AVAILABILITY = {"proven", "candidate", "incompatible", "template"}
_EVIDENCE_ORDER = {
    "runtime-literal": 0,
    "user-visual-pass": 1,
    "observer-screenshot-pass": 2,
    "user-visual-fail": 3,
    "profile-capability-mismatch": 4,
}
_RUNTIME_ENVIRONMENT = {
    "platform": "iOS simulator",
    "os_version": "26.5",
    "os_build": "23F77",
    "xcode_version": "26.6",
}
_PROFILE_CAPABILITIES = {
    "form_factor",
    "cellular",
    "personal_hotspot",
    "face_id",
    "home_button",
    "action_button",
    "camera_control",
    "standby",
    "top_button",
    "apple_pencil",
    "usb_c",
}


def _object_without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate catalogue key: {key}")
        value[key] = item
    return value


def _read_json(path: Path, label: str) -> dict[str, object]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_object_without_duplicate_keys)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Settings {label} cannot be read: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"Settings {label} must be an object")
    return value


def _nonempty_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"invalid catalogue {field}")
    if any(character.isspace() and character != " " for character in value):
        raise ValueError(f"invalid catalogue {field}")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"invalid catalogue {field}")
    return value


def _load_device_profile(path: Path = _PROFILE_PATH) -> dict[str, object]:
    profile = _read_json(path, "device profile")
    required = {
        "schema",
        "version",
        "profile_id",
        "scope_type",
        "marketing_model",
        "product_type",
        "hardware_model",
        "os_version",
        "os_build",
        "capabilities",
        "sources",
    }
    if set(profile) != required:
        raise ValueError("Settings device profile has unknown or missing fields")
    if profile.get("schema") != _PROFILE_SCHEMA or profile.get("version") != 1:
        raise ValueError("Settings device profile schema is unsupported")
    if profile.get("scope_type") != "model-build":
        raise ValueError("Settings device profile must be non-unique model/build scope")
    for field in (
        "profile_id",
        "marketing_model",
        "product_type",
        "hardware_model",
        "os_version",
        "os_build",
    ):
        _nonempty_text(profile.get(field), f"profile {field}")
    capabilities = profile.get("capabilities")
    if not isinstance(capabilities, dict) or set(capabilities) != _PROFILE_CAPABILITIES:
        raise ValueError("Settings device profile capabilities are invalid")
    if capabilities.get("form_factor") != "ipad" or any(
        not isinstance(value, bool)
        for key, value in capabilities.items()
        if key != "form_factor"
    ):
        raise ValueError("Settings device profile capability values are invalid")
    sources = profile.get("sources")
    if not isinstance(sources, list) or len(sources) != 2:
        raise ValueError("Settings device profile sources are invalid")
    expected_kinds = ("devicectl", "apple-technical-specification")
    for source, kind in zip(sources, expected_kinds, strict=True):
        if not isinstance(source, dict) or set(source) != {"kind", "note"}:
            raise ValueError("Settings device profile source is invalid")
        if source.get("kind") != kind:
            raise ValueError("Settings device profile source kind is invalid")
        _nonempty_text(source.get("note"), "profile source note")
    return profile


def _proof_scope(profile: dict[str, object]) -> dict[str, str]:
    return {
        "product_type": str(profile["product_type"]),
        "hardware_model": str(profile["hardware_model"]),
        "os_build": str(profile["os_build"]),
    }


def _section_from_url(url: str) -> str:
    parsed = urlsplit(url)
    suffix = parsed.netloc.removeprefix("com.apple.Settings").lstrip(".")
    return suffix or "Settings"


def _has_dynamic_placeholder(url: str) -> bool:
    parsed = urlsplit(url)
    segments = parsed.path[1:].split("/") if parsed.path.startswith("/") and parsed.path else []
    return (
        "%" in parsed.path
        or bool(parsed.path and parsed.path.endswith("/"))
        or any(value == "" for _, value in parse_qsl(parsed.query, keep_blank_values=True))
        or "com.apple.Dataclass" in segments
    )


def _validate_url(route: dict[str, object]) -> str:
    url = _nonempty_text(route.get("url"), "URL")
    if len(url.encode("utf-8")) > 2048:
        raise ValueError("catalogue URL is too long")
    if any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in url):
        raise ValueError("catalogue URL contains whitespace or a control character")
    if not url.startswith("settings-navigation://com.apple.Settings"):
        raise ValueError("catalogue URL is outside the Settings navigation scheme")

    parsed = urlsplit(url)
    if parsed.scheme != "settings-navigation" or not _AUTHORITY.fullmatch(parsed.netloc):
        raise ValueError("catalogue URL has an invalid Settings authority")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("catalogue URL contains credentials")
    try:
        if parsed.port is not None:
            raise ValueError("catalogue URL contains a port")
    except ValueError as error:
        raise ValueError("catalogue URL has an invalid authority") from error
    if parsed.path and not parsed.path.startswith("/"):
        raise ValueError("catalogue URL path is not absolute")

    malformed_percent = re.search(r"%(?![0-9A-Fa-f]{2})", url)
    if malformed_percent:
        placeholder_path = re.sub(r"(?:^|/)%$", "", parsed.path)
        if not (
            route.get("target_kind") == "dynamic"
            and route.get("dispatch_policy") == "blocked"
            and "%" not in placeholder_path
            and not parsed.query
            and not parsed.fragment
        ):
            raise ValueError("catalogue URL has a malformed percent escape")
    return url


def _validate_scope(value: object, profile: dict[str, object]) -> None:
    if value != _proof_scope(profile):
        raise ValueError("catalogue evidence does not match the exact target profile scope")


def _validate_evidence(value: object, profile: dict[str, object]) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("catalogue evidence must be an object")
    kind = value.get("kind")
    if kind == "runtime-literal":
        if set(value) != {"kind", "environment"} or value.get("environment") != _RUNTIME_ENVIRONMENT:
            raise ValueError("runtime-literal evidence is invalid")
    elif kind == "user-visual-pass":
        if set(value) != {"kind", "actor", "result", "proof_scope"}:
            raise ValueError("user-visual-pass evidence is invalid")
        if value.get("actor") != "user" or value.get("result") != "expected-target-visible":
            raise ValueError("user-visual-pass outcome is invalid")
        _validate_scope(value.get("proof_scope"), profile)
    elif kind == "observer-screenshot-pass":
        if set(value) != {"kind", "actor", "method", "result", "proof_scope"}:
            raise ValueError("observer-screenshot-pass evidence is invalid")
        if (
            value.get("actor") != "agent"
            or value.get("method") != "project-owned-wda-screenshot"
            or value.get("result") != "expected-target-visible"
        ):
            raise ValueError("observer-screenshot-pass outcome is invalid")
        _validate_scope(value.get("proof_scope"), profile)
    elif kind == "user-visual-fail":
        if set(value) != {"kind", "actor", "result", "observed_page", "proof_scope"}:
            raise ValueError("user-visual-fail evidence is invalid")
        if (
            value.get("actor") != "user"
            or value.get("result") != "settings-launched-prior-page-remained-visible"
            or value.get("observed_page") != "Apple Intelligence & Siri"
        ):
            raise ValueError("user-visual-fail outcome is invalid")
        _validate_scope(value.get("proof_scope"), profile)
    elif kind == "profile-capability-mismatch":
        if set(value) != {"kind", "capability", "required", "observed", "proof_scope"}:
            raise ValueError("profile-capability-mismatch evidence is invalid")
        capability = value.get("capability")
        capabilities = profile["capabilities"]
        if (
            not isinstance(capability, str)
            or capability not in capabilities
            or not isinstance(value.get("required"), bool)
            or not isinstance(value.get("observed"), bool)
            or value.get("observed") != capabilities[capability]
            or value.get("required") == value.get("observed")
        ):
            raise ValueError("profile capability mismatch is invalid")
        _validate_scope(value.get("proof_scope"), profile)
    else:
        raise ValueError("catalogue evidence kind is invalid")
    return value


def _validate_route(value: object, profile: dict[str, object]) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("catalogue route must be an object")
    required = {
        "id",
        "section",
        "label",
        "url",
        "target_kind",
        "dispatch_policy",
        "availability",
        "evidence",
    }
    if set(value) != required:
        raise ValueError("catalogue route has unknown or missing fields")

    route_id = _nonempty_text(value.get("id"), "route id")
    if not _ID.fullmatch(route_id):
        raise ValueError("catalogue route id is malformed")
    section = _nonempty_text(value.get("section"), "section")
    _nonempty_text(value.get("label"), "label")
    if value.get("target_kind") not in _ALLOWED_KINDS:
        raise ValueError("catalogue target kind is invalid")
    if value.get("dispatch_policy") not in _ALLOWED_POLICIES:
        raise ValueError("catalogue dispatch policy is invalid")
    if value.get("availability") not in _ALLOWED_AVAILABILITY:
        raise ValueError("catalogue availability is invalid")

    evidence = value.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("catalogue evidence is invalid")
    validated = [_validate_evidence(item, profile) for item in evidence]
    kinds = [str(item["kind"]) for item in validated]
    if len(kinds) != len(set(kinds)) or kinds != sorted(kinds, key=_EVIDENCE_ORDER.__getitem__):
        raise ValueError("catalogue evidence kinds are duplicated or out of order")
    positive_visual = {"user-visual-pass", "observer-screenshot-pass"} & set(kinds)
    if positive_visual and "user-visual-fail" in kinds:
        raise ValueError("catalogue route has conflicting visual evidence")

    url = _validate_url(value)
    if section != _section_from_url(url):
        raise ValueError("catalogue route section does not match its URL")
    dynamic = _has_dynamic_placeholder(url)
    if dynamic != (value.get("target_kind") == "dynamic"):
        raise ValueError("catalogue dynamic classification does not match its URL")
    if dynamic and value.get("dispatch_policy") != "blocked":
        raise ValueError("dynamic catalogue routes must remain blocked")

    if dynamic:
        expected_availability = "template"
    elif "profile-capability-mismatch" in kinds or "user-visual-fail" in kinds:
        expected_availability = "incompatible"
    elif positive_visual:
        expected_availability = "proven"
    else:
        expected_availability = "candidate"
    if value.get("availability") != expected_availability:
        raise ValueError("catalogue availability conflicts with its evidence")

    if parsed_fragment := urlsplit(url).fragment:
        if value.get("target_kind") != "row":
            raise ValueError(f"fragment route {parsed_fragment} must be classified as a row")
        if value.get("dispatch_policy") == "normal":
            raise ValueError("row routes require explicit or blocked dispatch")
    if any(token in urlsplit(url).query for token in ("aaaction=", "view=")) and not dynamic:
        if value.get("target_kind") != "action" or value.get("dispatch_policy") != "blocked":
            raise ValueError("query action must be classified as a blocked action")
    if value.get("target_kind") == "action" and value.get("dispatch_policy") == "normal":
        raise ValueError("action targets cannot use normal dispatch")

    sensitive_sections = {
        "AppleAccount",
        "PrivacyAndSecurity",
        "Passcode",
        "iCloud",
        "InternetAccounts",
        "ScreenTime",
        "VPN",
        "Developer",
        "Family",
        "Wallet",
        "Contactless",
        "SOS",
        "GameCenter",
    }
    if section in sensitive_sections and value.get("dispatch_policy") == "normal":
        raise ValueError("sensitive Settings sections cannot use normal dispatch")
    blocked_tokens = (
        "privacy_reset",
        "managedconfigurationlist",
        "software_update_link",
        "/Reset",
        "exitBuddy",
        "prebuddyBegin",
        "Wallet",
        "Contactless",
        "INVITE_FRIENDS",
        "SAFETY_CHECK",
        "voiceProfileRepairCFU",
        "setupFamily",
        "subscriptions",
        "upgradePlan",
        "ICLOUD_MAIL_CLEANUP",
        "ADD_PREFERRED_LANGUAGE",
        "AddNewKeyboard",
        "SharedLibrarySettingsButton",
    )
    if (
        section == "Passcode"
        or any(token.casefold() in url.casefold() for token in blocked_tokens)
    ) and value.get("dispatch_policy") != "blocked":
        raise ValueError("sensitive mutation-adjacent target must be blocked")
    return value


def _load_catalog(
    path: Path = _CATALOG_PATH,
    profile_path: Path = _PROFILE_PATH,
) -> dict[str, dict[str, object]]:
    profile = _load_device_profile(profile_path)
    data = _read_json(path, "route catalogue")
    if set(data) != {"schema", "version", "profile", "source", "routes"}:
        raise ValueError("Settings route catalogue has unknown or missing top-level fields")
    if data.get("schema") != _CATALOG_SCHEMA or data.get("version") != 2:
        raise ValueError("Settings route catalogue schema is unsupported")
    if data.get("profile") != _PROFILE_REF:
        raise ValueError("Settings route catalogue references the wrong device profile")
    expected_source = {
        "scheme": "settings-navigation",
        "status": "private-unsupported",
        "runtime_literal_source": _RUNTIME_ENVIRONMENT,
        "user_visual_source": {"actor": "user", "proof_scope": _proof_scope(profile)},
    }
    if data.get("source") != expected_source:
        raise ValueError("Settings route catalogue source metadata does not match the exact target profile scope")
    values = data.get("routes")
    if not isinstance(values, list) or not values:
        raise ValueError("Settings route catalogue has no routes")

    indexed: dict[str, dict[str, object]] = {}
    urls: set[str] = set()
    for value in values:
        route = _validate_route(value, profile)
        route_id = str(route["id"])
        url = str(route["url"])
        if route_id in indexed or url in urls:
            raise ValueError("Settings route catalogue contains a duplicate id or URL")
        indexed[route_id] = route
        urls.add(url)
    proven = {route_id for route_id, route in indexed.items() if route["availability"] == "proven"}
    if proven != _PROVEN_ROUTE_IDS:
        raise ValueError("Settings proven route allowlist has drifted")
    for command, route_id in _SHORTCUTS.items():
        route = indexed.get(route_id)
        if (
            route is None
            or route["availability"] != "proven"
            or route["dispatch_policy"] == "blocked"
            or route["target_kind"] in {"action", "dynamic"}
        ):
            raise ValueError(f"Settings shortcut {command} is not safely proven")
    return indexed


def _open_proven(route: dict[str, object]) -> Any:
    if (
        route["id"] not in _PROVEN_ROUTE_IDS
        or route["availability"] != "proven"
        or route["dispatch_policy"] == "blocked"
        or route["target_kind"] in {"action", "dynamic"}
    ):
        raise ValueError(f"Settings destination {route['id']} is not proven for this profile/build")
    return shared._direct_open("Settings", str(route["url"]))



def settings(command: object, *args: object, **options: object) -> Any:
    """Open Settings or one exact destination proven for the target profile/build."""
    try:
        operation = shared._command(command)
        if operation == "open":
            if args or options:
                raise ValueError("open takes no arguments")
            return shared._direct_open("Settings")
        if operation == "show":
            if len(args) != 1 or options or not isinstance(args[0], str):
                raise ValueError("show requires exactly one destination id")
            destination_id = args[0]
            catalog = _load_catalog()
            route = catalog.get(destination_id)
            if route is None:
                raise ValueError(f"unknown Settings destination id: {destination_id}")
            return _open_proven(route)
        if operation in _SHORTCUTS:
            if args or options:
                raise ValueError(f"{operation} takes no arguments")
            return _open_proven(_load_catalog()[_SHORTCUTS[operation]])
        return shared._unsupported(operation, COMMANDS)
    except (TypeError, ValueError, OSError) as error:
        return shared._failed(error)


__all__ = ["settings"]
