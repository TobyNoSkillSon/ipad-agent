"""CoreDevice-only Brave commands with strict custom-route builders."""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any
import unicodedata
from urllib.parse import parse_qsl, quote, urlsplit

from ipad_agent.core import commands as shared


COMMANDS = (
    "website",
    "youtube",
    "search",
    "private-website",
    "ipfs",
    "ipns",
)

_DIRECTORY = Path(__file__).parent
_PROFILE_REF = "device-profiles/ipad17-1-j817ap-brave-1.93-136-ipados-26.6.1-23g83.json"
_PROFILE_PATH = _DIRECTORY / _PROFILE_REF
_COMPATIBILITY_PATH = _DIRECTORY / "route-compatibility.json"
_PROFILE_SCHEMA = "ipad-agent.brave-device-profile/v1"
_COMPATIBILITY_SCHEMA = "ipad-agent.brave-route-compatibility/v1"
_ROUTE_COMMANDS = COMMANDS
_ALLOWED_AVAILABILITY = frozenset({"candidate", "proven", "incompatible"})
_EXPECTED_PRODUCTION = {
    "website": "admitted",
    "youtube": "legacy-admitted",
    "search": "admitted",
    "private-website": "candidate-gated",
    "ipfs": "candidate-gated",
    "ipns": "candidate-gated",
}
_CUSTOM_ROUTE_ACTIONS = {
    "search": "open-search",
    "private-website": "open-private-website",
    "ipfs": "open-ipfs",
    "ipns": "open-ipns",
}
_EVIDENCE_ORDER = {
    "vendor-source": 0,
    "vendor-issue": 1,
    "vendor-pull-request": 2,
    "user-visual-pass": 3,
    "observer-screenshot-pass": 4,
    "observer-screenshot-fail": 5,
    "user-visual-fail": 6,
}
_POSITIVE_EVIDENCE = frozenset({"user-visual-pass", "observer-screenshot-pass"})
_NEGATIVE_EVIDENCE = frozenset({"observer-screenshot-fail", "user-visual-fail"})
_EXPECTED_PROFILE = {
    "profile_id": "ipad17-1-j817ap-brave-1.93-136-ipados-26.6.1-23g83",
    "scope_type": "model-build",
    "app_name": "Brave",
    "app_version": "1.93",
    "app_build": "136",
    "product_type": "iPad17,1",
    "hardware_model": "J817AP",
    "os_version": "26.6.1",
    "os_build": "23G83",
}
_NAVIGATION_ROUTER = "Sources/Brave/Frontend/Browser/NavigationRouter.swift"
_INFO_PLIST = "App/iOS/Supporting Files/Info.plist"
_EXPECTED_SOURCE_FILES = {
    "website": [
        {"path": _INFO_PLIST, "declaration": "http-https-url-payloads"},
        {"path": _NAVIGATION_ROUTER, "declaration": "http-https-navigation"},
    ],
    "youtube": [
        {"path": _INFO_PLIST, "declaration": "http-https-url-payloads"},
        {"path": _NAVIGATION_ROUTER, "declaration": "http-https-navigation"},
    ],
    "search": [
        {"path": _NAVIGATION_ROUTER, "declaration": "brave-search-query"},
    ],
    "private-website": [
        {"path": _NAVIGATION_ROUTER, "declaration": "brave-open-url-private-true"},
    ],
    "ipfs": [
        {"path": _INFO_PLIST, "declaration": "ipfs-url-scheme"},
        {"path": _NAVIGATION_ROUTER, "declaration": "ipfs-navigation"},
    ],
    "ipns": [
        {"path": _INFO_PLIST, "declaration": "ipns-url-scheme"},
        {"path": _NAVIGATION_ROUTER, "declaration": "ipns-navigation"},
    ],
}
_BAD_ESCAPE_RE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_CIDV0_RE = re.compile(r"Qm[1-9A-HJ-NP-Za-km-z]{44}")
_CIDV1_BASE32_RE = re.compile(r"b[a-z2-7]{20,120}")
_DNS_LABEL_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_MAX_URL_BYTES = 2048


def _object_without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate Brave authority key: {key}")
        value[key] = item
    return value


def _invalid_constant(value: str) -> None:
    raise ValueError(f"non-finite Brave authority number: {value}")


def _read_json(path: Path, label: str) -> dict[str, object]:
    try:
        raw = path.read_bytes()
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_invalid_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Brave {label} cannot be read: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"Brave {label} must be an object")
    return value


def _nonempty_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"invalid Brave {field}")
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise ValueError(f"invalid Brave {field}")
    return value


def _load_device_profile(path: Path = _PROFILE_PATH) -> dict[str, object]:
    profile = _read_json(path, "device profile")
    required = {"schema", "version", *_EXPECTED_PROFILE, "sources"}
    if set(profile) != required:
        raise ValueError("Brave device profile has unknown or missing fields")
    if profile.get("schema") != _PROFILE_SCHEMA or profile.get("version") != 1:
        raise ValueError("Brave device profile schema is unsupported")
    for field, expected in _EXPECTED_PROFILE.items():
        if _nonempty_text(profile.get(field), f"profile {field}") != expected:
            raise ValueError(f"Brave device profile {field} is outside the exact authority")
    sources = profile.get("sources")
    expected_kinds = ("devicectl", "installed-application-metadata")
    if not isinstance(sources, list) or len(sources) != len(expected_kinds):
        raise ValueError("Brave device profile sources are invalid")
    for source, expected_kind in zip(sources, expected_kinds, strict=True):
        if not isinstance(source, dict) or set(source) != {"kind", "note"}:
            raise ValueError("Brave device profile source is invalid")
        if source.get("kind") != expected_kind:
            raise ValueError("Brave device profile source kind is invalid")
        _nonempty_text(source.get("note"), "profile source note")
    return profile


def _proof_scope(profile: dict[str, object]) -> dict[str, str]:
    return {
        "product_type": str(profile["product_type"]),
        "hardware_model": str(profile["hardware_model"]),
        "os_build": str(profile["os_build"]),
    }


def _validate_scope(value: object, profile: dict[str, object]) -> None:
    if value != _proof_scope(profile):
        raise ValueError(
            "Brave visual evidence does not match the exact product/hardware/build scope"
        )


def _validate_evidence(
    value: object,
    command: str,
    profile: dict[str, object],
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Brave route evidence must be an object")
    kind = value.get("kind")
    if kind == "vendor-source":
        if set(value) != {"kind", "repository", "ref", "files"}:
            raise ValueError("Brave vendor-source evidence is invalid")
        if value.get("repository") != "brave/brave-ios" or value.get("ref") != "development":
            raise ValueError("Brave vendor-source identity is invalid")
        if value.get("files") != _EXPECTED_SOURCE_FILES[command]:
            raise ValueError("Brave vendor-source declarations are invalid")
    elif kind in {"vendor-issue", "vendor-pull-request"}:
        if set(value) != {"kind", "repository", "number", "subject"}:
            raise ValueError("Brave vendor change evidence is invalid")
        expected_number = 627 if kind == "vendor-issue" else 3582
        if (
            command != "search"
            or value.get("repository") != "brave/brave-ios"
            or value.get("number") != expected_number
            or isinstance(value.get("number"), bool)
            or value.get("subject") != "search-url-scheme"
        ):
            raise ValueError("Brave vendor change evidence is invalid")
    elif kind == "user-visual-pass":
        if set(value) != {"kind", "actor", "result", "proof_scope"}:
            raise ValueError("Brave user-visual-pass evidence is invalid")
        if value.get("actor") != "user" or value.get("result") != "expected-route-visible":
            raise ValueError("Brave user-visual-pass outcome is invalid")
        _validate_scope(value.get("proof_scope"), profile)
    elif kind == "observer-screenshot-pass":
        if set(value) != {"kind", "actor", "method", "result", "proof_scope"}:
            raise ValueError("Brave observer-screenshot-pass evidence is invalid")
        if (
            value.get("actor") != "agent"
            or value.get("method") != "authorized-coredevice-observer-screenshot"
            or value.get("result") != "expected-route-visible"
        ):
            raise ValueError("Brave observer-screenshot-pass outcome is invalid")
        _validate_scope(value.get("proof_scope"), profile)
    elif kind == "observer-screenshot-fail":
        if set(value) != {"kind", "actor", "method", "result", "proof_scope"}:
            raise ValueError("Brave observer-screenshot-fail evidence is invalid")
        if (
            value.get("actor") != "agent"
            or value.get("method") != "project-owned-wda-screenshot"
            or value.get("result") != "prior-route-remained-visible"
        ):
            raise ValueError("Brave observer-screenshot-fail outcome is invalid")
        _validate_scope(value.get("proof_scope"), profile)
    elif kind == "user-visual-fail":
        if set(value) != {"kind", "actor", "result", "proof_scope"}:
            raise ValueError("Brave user-visual-fail evidence is invalid")
        if value.get("actor") != "user" or value.get("result") != "expected-route-not-visible":
            raise ValueError("Brave user-visual-fail outcome is invalid")
        _validate_scope(value.get("proof_scope"), profile)
    else:
        raise ValueError("Brave route evidence kind is invalid")
    return value


def _load_compatibility(
    path: Path = _COMPATIBILITY_PATH,
    profile_path: Path = _PROFILE_PATH,
) -> dict[str, dict[str, object]]:
    profile = _load_device_profile(profile_path)
    authority = _read_json(path, "route compatibility authority")
    if set(authority) != {"schema", "version", "profile", "routes"}:
        raise ValueError("Brave route compatibility authority has unknown or missing fields")
    if authority.get("schema") != _COMPATIBILITY_SCHEMA or authority.get("version") != 1:
        raise ValueError("Brave route compatibility schema is unsupported")
    if authority.get("profile") != _PROFILE_REF:
        raise ValueError("Brave route compatibility authority references the wrong profile")
    routes = authority.get("routes")
    if not isinstance(routes, list) or len(routes) != len(_ROUTE_COMMANDS):
        raise ValueError("Brave route compatibility authority has the wrong route count")

    indexed: dict[str, dict[str, object]] = {}
    for position, route in enumerate(routes):
        if not isinstance(route, dict) or set(route) != {
            "command", "availability", "production", "evidence"
        }:
            raise ValueError("Brave compatibility route has unknown or missing fields")
        command = route.get("command")
        if command != _ROUTE_COMMANDS[position]:
            raise ValueError(
                "Brave compatibility commands are missing, duplicated, or out of order"
            )
        availability = route.get("availability")
        if availability not in _ALLOWED_AVAILABILITY:
            raise ValueError("Brave route availability is invalid")
        if route.get("production") != _EXPECTED_PRODUCTION[str(command)]:
            raise ValueError("Brave route production status is invalid")
        evidence = route.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("Brave route evidence is invalid")
        validated = [
            _validate_evidence(item, str(command), profile) for item in evidence
        ]
        kinds = [str(item["kind"]) for item in validated]
        if (
            kinds[0] != "vendor-source"
            or len(kinds) != len(set(kinds))
            or kinds != sorted(kinds, key=_EVIDENCE_ORDER.__getitem__)
        ):
            raise ValueError(
                "Brave route evidence kinds are missing, duplicated, or out of order"
            )
        evidence_kinds = set(kinds)
        has_positive = bool(evidence_kinds & _POSITIVE_EVIDENCE)
        has_negative = bool(evidence_kinds & _NEGATIVE_EVIDENCE)
        if has_positive and has_negative:
            raise ValueError("Brave route has conflicting compatibility evidence")
        expected = "incompatible" if has_negative else "proven" if has_positive else "candidate"
        if availability != expected:
            raise ValueError("Brave route availability conflicts with its evidence")
        indexed[str(command)] = route
    return indexed


def _canonical_command(operation: str) -> str | None:
    return {shared._command(command): command for command in COMMANDS}.get(operation)


def _check_common_uri_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise ValueError(f"{name} must not contain control characters")
    if any(character.isspace() for character in value):
        raise ValueError(f"{name} must not contain whitespace")
    if "\\" in value or _BAD_ESCAPE_RE.search(value):
        raise ValueError(f"{name} contains malformed escaping or backslashes")
    if len(value.encode("utf-8")) > _MAX_URL_BYTES:
        raise ValueError(f"{name} exceeds the {_MAX_URL_BYTES}-byte UTF-8 limit")
    return value


def _strict_web_url(value: object) -> str:
    url = _check_common_uri_text(shared._http_url(value), "website URL")
    try:
        parsed = urlsplit(url)
        port = parsed.port
        host = parsed.hostname
    except ValueError as error:
        raise ValueError(f"website URL is invalid: {error}") from error
    if port is not None:
        raise ValueError("website URL must not contain a port")
    if not host:
        raise ValueError("website URL must contain a host")
    return url


def _raw_query(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("search requires one non-empty raw query string")
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise ValueError("search query must not contain control characters")
    return value


def _build_search(value: object) -> str:
    query = _raw_query(value)
    url = f"brave://search?q={quote(query, safe='')}"
    if len(url.encode("utf-8")) > _MAX_URL_BYTES:
        raise ValueError(f"search URL exceeds the {_MAX_URL_BYTES}-byte UTF-8 limit")
    parsed = urlsplit(url)
    fields = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    if (
        parsed.scheme != "brave"
        or parsed.netloc != "search"
        or parsed.path
        or parsed.fragment
        or fields != [("q", query)]
        or parsed.query != f"q={quote(query, safe='')}"
    ):
        raise ValueError("search route is not canonical")
    return url


def _build_private_website(value: object) -> str:
    destination = _strict_web_url(value)
    encoded = quote(destination, safe="")
    url = f"brave://open-url?url={encoded}&private=true"
    if len(url.encode("utf-8")) > _MAX_URL_BYTES:
        raise ValueError(f"private website URL exceeds the {_MAX_URL_BYTES}-byte UTF-8 limit")
    parsed = urlsplit(url)
    fields = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    if (
        parsed.scheme != "brave"
        or parsed.netloc != "open-url"
        or parsed.path
        or parsed.fragment
        or fields != [("url", destination), ("private", "true")]
        or parsed.query != f"url={encoded}&private=true"
    ):
        raise ValueError("private website route is not canonical")
    return url


def _valid_dns_name(value: str) -> bool:
    if len(value) > 253 or value != value.casefold() or value.endswith("."):
        return False
    labels = value.split(".")
    return len(labels) >= 2 and all(_DNS_LABEL_RE.fullmatch(label) for label in labels)


def _valid_cid(value: str) -> bool:
    return bool(_CIDV0_RE.fullmatch(value) or _CIDV1_BASE32_RE.fullmatch(value))


def _strict_content_uri(value: object, scheme: str) -> str:
    uri = _check_common_uri_text(value, f"{scheme} URI")
    if not uri.startswith(f"{scheme}://"):
        raise ValueError(f"{scheme} URI must use exact lowercase {scheme}:// syntax")
    try:
        parsed = urlsplit(uri)
        port = parsed.port
    except ValueError as error:
        raise ValueError(f"{scheme} URI is invalid: {error}") from error
    authority = parsed.netloc
    if (
        parsed.scheme != scheme
        or not authority
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or "@" in authority
        or ":" in authority
    ):
        raise ValueError(f"{scheme} URI requires one authority and no credentials or port")
    if scheme == "ipfs":
        if not _valid_cid(authority):
            raise ValueError("ipfs URI authority must be a supported CIDv0 or base32 CIDv1")
    elif not (_valid_cid(authority) or _valid_dns_name(authority)):
        raise ValueError("ipns URI authority must be a supported CID or lowercase DNS name")
    return uri


def _custom_route_argument(
    command: str,
    args: tuple[object, ...],
    options: dict[str, object],
) -> str:
    if len(args) != 1 or options:
        raise ValueError(f"{command} requires exactly one positional value")
    if command == "search":
        return _build_search(args[0])
    if command == "private-website":
        return _build_private_website(args[0])
    if command in {"ipfs", "ipns"}:
        return _strict_content_uri(args[0], command)
    raise ValueError("custom route command is unsupported")


def _custom_policy_url(action_id: str, url: str) -> str:
    """Apply addon enablement and the exact v1 action scheme before dispatch."""
    from ipad_agent.core.config import load_config
    from ipad_agent.core.registry import (
        AddonNotEnabledError,
        IntegrationNotFoundError,
        RegistryError,
        load_registry,
    )

    try:
        config = load_config()
        registry = load_registry(enabled_addons=config.enabled_addons)
        return registry.validate_v1_url("Brave", action_id, url)
    except (AddonNotEnabledError, IntegrationNotFoundError, RegistryError) as error:
        raise ValueError(str(error)) from error



def brave(command: object, *args: object, **options: object) -> Any:
    """Deliver one admitted URL to enabled Brave; reject gated routes pre-dispatch."""
    try:
        operation = shared._command(command)
        canonical = _canonical_command(operation)
        if canonical is None:
            return shared._unsupported(operation, COMMANDS)
        route = _load_compatibility()[canonical]
        if route["availability"] == "incompatible":
            raise ValueError(f"Brave route {canonical!r} is incompatible on this profile")
        if route["production"] == "candidate-gated":
            raise ValueError(
                f"Brave route {canonical!r} is {route['availability']} for product "
                "iPad17,1, hardware J817AP, build 23G83"
            )

        if canonical == "website":
            if len(args) != 1 or options:
                raise ValueError("website requires exactly one HTTP or HTTPS URL")
            url = shared._http_url(args[0])
            validated_url = shared._browser_policy_url("Brave", url)
        elif canonical == "youtube":
            if len(args) != 1 or set(options) - {"at"}:
                raise ValueError("youtube requires one URL and optional at=seconds")
            url = shared._youtube_url(args[0], options.get("at"))
            validated_url = shared._browser_policy_url("Brave", url)
        elif canonical == "search":
            url = _custom_route_argument(canonical, tuple(args), dict(options))
            validated_url = _custom_policy_url(_CUSTOM_ROUTE_ACTIONS[canonical], url)
        else:
            raise ValueError(f"Brave route {canonical!r} is not admitted")
        return shared._direct_open("Brave", validated_url)
    except (TypeError, ValueError, OSError, KeyError) as error:
        return shared._failed(error)


__all__ = ["brave"]
