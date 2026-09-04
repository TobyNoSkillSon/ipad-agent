"""CoreDevice-only Safari commands with exact-profile route evidence."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ipad_agent.core import commands as shared


COMMANDS = ("website", "youtube")

_DIRECTORY = Path(__file__).parent
_PROFILE_REF = "device-profiles/ipad17-1-j817ap-safari-26.6.1-ipados-26.6.1-23g83.json"
_PROFILE_PATH = _DIRECTORY / _PROFILE_REF
_COMPATIBILITY_PATH = _DIRECTORY / "route-compatibility.json"
_PROFILE_SCHEMA = "ipad-agent.safari-device-profile/v1"
_COMPATIBILITY_SCHEMA = "ipad-agent.safari-route-compatibility/v1"
_OFFICIAL_SOURCE = (
    "https://developer.apple.com/library/archive/featuredarticles/"
    "iPhoneURLScheme_Reference/Introduction/Introduction.html"
)
_ROUTE_COMMANDS = COMMANDS
_ALLOWED_AVAILABILITY = frozenset({"candidate", "proven", "incompatible"})
_EXPECTED_PRODUCTION = {
    "website": "admitted",
    # Preserve the established public convenience while its own rendered
    # compatibility remains a candidate. The underlying HTTP(S) policy is unchanged.
    "youtube": "legacy-admitted",
}
_EVIDENCE_ORDER = {
    "official-documentation": 0,
    "user-visual-pass": 1,
    "observer-screenshot-pass": 2,
    "user-visual-fail": 3,
}
_POSITIVE_EVIDENCE = frozenset({"user-visual-pass", "observer-screenshot-pass"})
_NEGATIVE_EVIDENCE = frozenset({"user-visual-fail"})
_EXPECTED_PROFILE = {
    "profile_id": "ipad17-1-j817ap-safari-26.6.1-ipados-26.6.1-23g83",
    "scope_type": "model-build",
    "app_name": "Safari",
    "app_version": "26.6.1",
    "product_type": "iPad17,1",
    "hardware_model": "J817AP",
    "os_version": "26.6.1",
    "os_build": "23G83",
}


def _object_without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate Safari authority key: {key}")
        value[key] = item
    return value


def _invalid_constant(value: str) -> None:
    raise ValueError(f"non-finite Safari authority number: {value}")


def _read_json(path: Path, label: str) -> dict[str, object]:
    try:
        raw = path.read_bytes()
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_invalid_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Safari {label} cannot be read: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"Safari {label} must be an object")
    return value


def _nonempty_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"invalid Safari {field}")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"invalid Safari {field}")
    return value


def _load_device_profile(path: Path = _PROFILE_PATH) -> dict[str, object]:
    profile = _read_json(path, "device profile")
    required = {"schema", "version", *_EXPECTED_PROFILE, "sources"}
    if set(profile) != required:
        raise ValueError("Safari device profile has unknown or missing fields")
    if profile.get("schema") != _PROFILE_SCHEMA or profile.get("version") != 1:
        raise ValueError("Safari device profile schema is unsupported")
    for field, expected in _EXPECTED_PROFILE.items():
        if _nonempty_text(profile.get(field), f"profile {field}") != expected:
            raise ValueError(f"Safari device profile {field} is outside the exact authority")
    sources = profile.get("sources")
    expected_kinds = ("devicectl", "installed-application-metadata")
    if not isinstance(sources, list) or len(sources) != len(expected_kinds):
        raise ValueError("Safari device profile sources are invalid")
    for source, expected_kind in zip(sources, expected_kinds, strict=True):
        if not isinstance(source, dict) or set(source) != {"kind", "note"}:
            raise ValueError("Safari device profile source is invalid")
        if source.get("kind") != expected_kind:
            raise ValueError("Safari device profile source kind is invalid")
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
            "Safari visual evidence does not match the exact product/hardware/build scope"
        )


def _validate_evidence(value: object, profile: dict[str, object]) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Safari route evidence must be an object")
    kind = value.get("kind")
    if kind == "official-documentation":
        if set(value) != {"kind", "source", "syntax"}:
            raise ValueError("Safari official-documentation evidence is invalid")
        if value.get("source") != _OFFICIAL_SOURCE:
            raise ValueError("Safari official-documentation source is invalid")
        if value.get("syntax") != "http-https-browser-url":
            raise ValueError("Safari official-documentation syntax is invalid")
    elif kind == "user-visual-pass":
        if set(value) != {"kind", "actor", "result", "proof_scope"}:
            raise ValueError("Safari user-visual-pass evidence is invalid")
        if value.get("actor") != "user" or value.get("result") != "expected-route-visible":
            raise ValueError("Safari user-visual-pass outcome is invalid")
        _validate_scope(value.get("proof_scope"), profile)
    elif kind == "observer-screenshot-pass":
        if set(value) != {"kind", "actor", "method", "result", "proof_scope"}:
            raise ValueError("Safari observer-screenshot-pass evidence is invalid")
        if (
            value.get("actor") != "agent"
            or value.get("method") != "authorized-coredevice-observer-screenshot"
            or value.get("result") != "expected-website-visible"
        ):
            raise ValueError("Safari observer-screenshot-pass outcome is invalid")
        _validate_scope(value.get("proof_scope"), profile)
    elif kind == "user-visual-fail":
        if set(value) != {"kind", "actor", "result", "proof_scope"}:
            raise ValueError("Safari user-visual-fail evidence is invalid")
        if value.get("actor") != "user" or value.get("result") != "expected-route-not-visible":
            raise ValueError("Safari user-visual-fail outcome is invalid")
        _validate_scope(value.get("proof_scope"), profile)
    else:
        raise ValueError("Safari route evidence kind is invalid")
    return value


def _load_compatibility(
    path: Path = _COMPATIBILITY_PATH,
    profile_path: Path = _PROFILE_PATH,
) -> dict[str, dict[str, object]]:
    profile = _load_device_profile(profile_path)
    authority = _read_json(path, "route compatibility authority")
    if set(authority) != {"schema", "version", "profile", "routes"}:
        raise ValueError(
            "Safari route compatibility authority has unknown or missing fields"
        )
    if authority.get("schema") != _COMPATIBILITY_SCHEMA or authority.get("version") != 1:
        raise ValueError("Safari route compatibility schema is unsupported")
    if authority.get("profile") != _PROFILE_REF:
        raise ValueError("Safari route compatibility authority references the wrong profile")
    routes = authority.get("routes")
    if not isinstance(routes, list) or len(routes) != len(_ROUTE_COMMANDS):
        raise ValueError("Safari route compatibility authority has the wrong route count")

    indexed: dict[str, dict[str, object]] = {}
    for position, route in enumerate(routes):
        if not isinstance(route, dict) or set(route) != {
            "command", "availability", "production", "evidence"
        }:
            raise ValueError("Safari compatibility route has unknown or missing fields")
        command = route.get("command")
        if command != _ROUTE_COMMANDS[position]:
            raise ValueError(
                "Safari compatibility commands are missing, duplicated, or out of order"
            )
        availability = route.get("availability")
        if availability not in _ALLOWED_AVAILABILITY:
            raise ValueError("Safari route availability is invalid")
        if route.get("production") != _EXPECTED_PRODUCTION[str(command)]:
            raise ValueError("Safari route production status is invalid")
        evidence = route.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("Safari route evidence is invalid")
        validated = [_validate_evidence(item, profile) for item in evidence]
        kinds = [str(item["kind"]) for item in validated]
        if (
            kinds[0] != "official-documentation"
            or len(kinds) != len(set(kinds))
            or kinds != sorted(kinds, key=_EVIDENCE_ORDER.__getitem__)
        ):
            raise ValueError(
                "Safari route evidence kinds are missing, duplicated, or out of order"
            )
        evidence_kinds = set(kinds)
        has_positive = bool(evidence_kinds & _POSITIVE_EVIDENCE)
        has_negative = bool(evidence_kinds & _NEGATIVE_EVIDENCE)
        if has_positive and has_negative:
            raise ValueError("Safari route has conflicting compatibility evidence")
        expected = "incompatible" if has_negative else "proven" if has_positive else "candidate"
        if availability != expected:
            raise ValueError("Safari route availability conflicts with its evidence")
        indexed[str(command)] = route
    return indexed


def safari(command: object, *args: object, **options: object) -> Any:
    """Deliver one validated website or YouTube URL to Safari."""
    try:
        operation = shared._command(command)
        if operation == "website":
            if len(args) != 1 or options:
                raise ValueError("website requires exactly one HTTP or HTTPS URL")
            url = shared._http_url(args[0])
        elif operation == "youtube":
            if len(args) != 1 or set(options) - {"at"}:
                raise ValueError("youtube requires one URL and optional at=seconds")
            url = shared._youtube_url(args[0], options.get("at"))
        else:
            return shared._unsupported(operation, COMMANDS)

        route = _load_compatibility()[operation]
        if (
            route["availability"] == "incompatible"
            or route["production"] not in {"admitted", "legacy-admitted"}
        ):
            raise ValueError(f"Safari route {operation!r} is not admitted")
        validated_url = shared._browser_policy_url("Safari", url)
        return shared._direct_open("Safari", validated_url)
    except (TypeError, ValueError, OSError, KeyError) as error:
        return shared._failed(error)


__all__ = ["safari"]
