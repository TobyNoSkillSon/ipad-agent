"""CoreDevice-only Apple Maps commands with profile-bound route evidence."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from ipad_agent.core import commands as shared
from ipad_agent.transports.http import RedirectResolutionError, resolve_one_redirect


COMMANDS = (
    "open",
    "frame",
    "search",
    "show",
    "place",
    "look-around",
    "directions",
    "navigate",
    "guides",
    "report-a-problem",
    "link",
)

_BUNDLE = "com.apple.Maps"
_ROUTE_COMMANDS = (
    "frame",
    "search",
    "place",
    "look-around",
    "directions",
    "navigate",
    "guides",
    "report-a-problem",
    "link",
)
_CANDIDATE_SCENARIOS = {
    "navigate": "navigate-candidate",
    "report-a-problem": "report-problem-candidate",
}
_DIRECTORY = Path(__file__).parent
_PROFILE_REF = "device-profiles/ipad-pro-11-inch-m5-wifi-ipados-26.6.1-23g83.json"
_PROFILE_PATH = _DIRECTORY / _PROFILE_REF
_COMPATIBILITY_PATH = _DIRECTORY / "route-compatibility.json"
_PROFILE_SCHEMA = "ipad-agent.maps-device-profile/v1"
_COMPATIBILITY_SCHEMA = "ipad-agent.maps-route-compatibility/v1"
_ALLOWED_AVAILABILITY = frozenset({"candidate", "proven", "incompatible"})
_EVIDENCE_ORDER = {
    "official-documentation": 0,
    "user-visual-pass": 1,
    "observer-screenshot-pass": 2,
    "user-visual-fail": 3,
    "profile-capability-mismatch": 4,
}
_POSITIVE_EVIDENCE = frozenset({"user-visual-pass", "observer-screenshot-pass"})
_NEGATIVE_EVIDENCE = frozenset({"user-visual-fail", "profile-capability-mismatch"})
_OFFICIAL_SOURCE = "https://developer.apple.com/documentation/mapkit/unified-map-urls"
_OFFICIAL_ENDPOINTS = {
    "frame": "frame",
    "search": "search",
    "place": "place",
    "look-around": "look-around",
    "directions": "directions",
    "navigate": "directions-start",
    "guides": "guides",
    "report-a-problem": "report-a-problem",
    "link": "full-and-short-links",
}
_PROFILE_CAPABILITIES = frozenset({"form_factor", "wifi", "cellular"})


def _object_without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate Maps authority key: {key}")
        value[key] = item
    return value


def _invalid_constant(value: str) -> None:
    raise ValueError(f"non-finite Maps authority number: {value}")


def _read_json(path: Path, label: str) -> dict[str, object]:
    try:
        raw = path.read_bytes()
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_invalid_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Maps {label} cannot be read: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"Maps {label} must be an object")
    return value


def _nonempty_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"invalid Maps {field}")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"invalid Maps {field}")
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
        raise ValueError("Maps device profile has unknown or missing fields")
    if profile.get("schema") != _PROFILE_SCHEMA or profile.get("version") != 1:
        raise ValueError("Maps device profile schema is unsupported")
    if profile.get("scope_type") != "model-build":
        raise ValueError("Maps device profile must use non-unique model/build scope")
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
        raise ValueError("Maps device profile capabilities are invalid")
    if capabilities.get("form_factor") != "ipad" or not all(
        isinstance(capabilities.get(name), bool) for name in ("wifi", "cellular")
    ):
        raise ValueError("Maps device profile capability values are invalid")
    sources = profile.get("sources")
    expected_kinds = ("devicectl", "apple-technical-specification")
    if not isinstance(sources, list) or len(sources) != len(expected_kinds):
        raise ValueError("Maps device profile sources are invalid")
    for source, expected_kind in zip(sources, expected_kinds, strict=True):
        if not isinstance(source, dict) or set(source) != {"kind", "note"}:
            raise ValueError("Maps device profile source is invalid")
        if source.get("kind") != expected_kind:
            raise ValueError("Maps device profile source kind is invalid")
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
        raise ValueError("Maps visual evidence does not match the exact product/hardware/build scope")


def _validate_evidence(
    value: object,
    command: str,
    profile: dict[str, object],
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Maps route evidence must be an object")
    kind = value.get("kind")
    if kind == "official-documentation":
        if set(value) != {"kind", "source", "endpoint"}:
            raise ValueError("Maps official-documentation evidence is invalid")
        if value.get("source") != _OFFICIAL_SOURCE:
            raise ValueError("Maps official-documentation source is invalid")
        if value.get("endpoint") != _OFFICIAL_ENDPOINTS[command]:
            raise ValueError("Maps official-documentation endpoint is invalid")
    elif kind == "user-visual-pass":
        if set(value) != {"kind", "actor", "result", "proof_scope"}:
            raise ValueError("Maps user-visual-pass evidence is invalid")
        if value.get("actor") != "user" or value.get("result") != "expected-route-visible":
            raise ValueError("Maps user-visual-pass outcome is invalid")
        _validate_scope(value.get("proof_scope"), profile)
    elif kind == "observer-screenshot-pass":
        if set(value) != {"kind", "actor", "method", "result", "proof_scope"}:
            raise ValueError("Maps observer-screenshot-pass evidence is invalid")
        if (
            value.get("actor") != "agent"
            or value.get("method") != "project-owned-wda-screenshot"
            or value.get("result") != "expected-route-visible"
        ):
            raise ValueError("Maps observer-screenshot-pass outcome is invalid")
        _validate_scope(value.get("proof_scope"), profile)
    elif kind == "user-visual-fail":
        if set(value) != {"kind", "actor", "result", "observed", "proof_scope"}:
            raise ValueError("Maps user-visual-fail evidence is invalid")
        if value.get("actor") != "user" or value.get("result") != "expected-route-not-visible":
            raise ValueError("Maps user-visual-fail outcome is invalid")
        _nonempty_text(value.get("observed"), "visual failure observation")
        _validate_scope(value.get("proof_scope"), profile)
    elif kind == "profile-capability-mismatch":
        if set(value) != {"kind", "capability", "required", "observed", "proof_scope"}:
            raise ValueError("Maps profile-capability-mismatch evidence is invalid")
        capabilities = profile["capabilities"]
        capability = value.get("capability")
        if (
            not isinstance(capabilities, dict)
            or not isinstance(capability, str)
            or capability not in capabilities
            or not isinstance(capabilities[capability], bool)
            or not isinstance(value.get("required"), bool)
            or not isinstance(value.get("observed"), bool)
            or value.get("observed") != capabilities[capability]
            or value.get("required") == value.get("observed")
        ):
            raise ValueError("Maps profile capability mismatch is invalid")
        _validate_scope(value.get("proof_scope"), profile)
    else:
        raise ValueError("Maps route evidence kind is invalid")
    return value


def _load_compatibility(
    path: Path = _COMPATIBILITY_PATH,
    profile_path: Path = _PROFILE_PATH,
) -> dict[str, dict[str, object]]:
    profile = _load_device_profile(profile_path)
    authority = _read_json(path, "route compatibility authority")
    if set(authority) != {"schema", "version", "profile", "routes"}:
        raise ValueError("Maps route compatibility authority has unknown or missing fields")
    if authority.get("schema") != _COMPATIBILITY_SCHEMA or authority.get("version") != 1:
        raise ValueError("Maps route compatibility schema is unsupported")
    if authority.get("profile") != _PROFILE_REF:
        raise ValueError("Maps route compatibility authority references the wrong profile")
    routes = authority.get("routes")
    if not isinstance(routes, list) or len(routes) != len(_ROUTE_COMMANDS):
        raise ValueError("Maps route compatibility authority has the wrong route count")

    indexed: dict[str, dict[str, object]] = {}
    for position, route in enumerate(routes):
        if not isinstance(route, dict) or set(route) != {"command", "availability", "evidence"}:
            raise ValueError("Maps compatibility route has unknown or missing fields")
        command = route.get("command")
        if command != _ROUTE_COMMANDS[position]:
            raise ValueError("Maps compatibility commands are missing, duplicated, or out of order")
        availability = route.get("availability")
        if availability not in _ALLOWED_AVAILABILITY:
            raise ValueError("Maps route availability is invalid")
        evidence = route.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("Maps route evidence is invalid")
        validated = [_validate_evidence(item, str(command), profile) for item in evidence]
        kinds = [str(item["kind"]) for item in validated]
        if (
            kinds[0] != "official-documentation"
            or len(kinds) != len(set(kinds))
            or kinds != sorted(kinds, key=_EVIDENCE_ORDER.__getitem__)
        ):
            raise ValueError("Maps route evidence kinds are missing, duplicated, or out of order")
        evidence_kinds = set(kinds)
        has_positive = bool(evidence_kinds & _POSITIVE_EVIDENCE)
        has_negative = bool(evidence_kinds & _NEGATIVE_EVIDENCE)
        if has_positive and has_negative:
            raise ValueError("Maps route has conflicting compatibility evidence")
        if has_negative:
            expected = "incompatible"
        elif has_positive:
            expected = "proven"
        else:
            expected = "candidate"
        if availability != expected:
            raise ValueError("Maps route availability conflicts with its evidence")
        indexed[str(command)] = route
    return indexed


def _short_maps_host(host: str) -> bool:
    labels = host.casefold().rstrip(".").split(".")
    return labels == ["maps", "apple"] or (
        len(labels) > 2 and labels[-2:] == ["maps", "apple"] and all(labels[:-2])
    )


def _resolve_short_maps_url(url: object, *, timeout: float = 3.0) -> str:
    """Resolve one documented ``*.maps.apple`` redirect without following it."""
    text = shared._http_url(url, name="Maps link")
    parsed = urlparse(text)
    if (
        parsed.scheme != "https"
        or not _short_maps_host(parsed.hostname or "")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Apple Maps short links require HTTPS, a clean *.maps.apple authority, "
            "and no query or fragment"
        )
    try:
        return resolve_one_redirect(text, timeout=timeout)
    except RedirectResolutionError as error:
        raise ValueError(f"Apple Maps short link {error}") from error


def _maps_arguments(
    operation: str,
    args: tuple[object, ...],
    options: dict[str, object],
    *,
    resolver: Callable[[object], str] | None = None,
) -> tuple[tuple[object, ...], dict[str, object]]:
    """Apply the established Python conveniences before policy binding."""
    values = tuple(args)
    keywords = dict(options)
    aliases = {
        "origin": "source",
        "waypoints": "waypoint",
        "waypoint_place_ids": "waypoint_place_id",
        "map_type": "map",
    }
    for alias, canonical in aliases.items():
        if alias in keywords:
            if canonical in keywords:
                raise ValueError(f"{alias} and {canonical} cannot both be supplied")
            keywords[canonical] = keywords.pop(alias)
    if operation == "frame" and len(values) == 2:
        values = ((values[0], values[1]),)
    if operation == "link":
        positional_candidate = len(values) == 1 and not keywords
        keyword_candidate = not values and set(keywords) == {"url"}
        candidate = values[0] if positional_candidate else keywords.get("url") if keyword_candidate else None
        if isinstance(candidate, str):
            parsed = urlparse(candidate)
            if _short_maps_host(parsed.hostname or ""):
                if resolver is None:
                    raise ValueError(
                        "Apple Maps short links require an explicitly authorized maintenance resolver"
                    )
                resolved = resolver(candidate)
                if positional_candidate:
                    values = (resolved,)
                else:
                    keywords["url"] = resolved
    if operation in {"place", "look-around", "report-a-problem"} and len(values) in {2, 3}:
        if "coordinate" in keywords:
            raise ValueError("coordinate was assigned more than once")
        keywords["coordinate"] = (values[0], values[1])
        if len(values) == 3:
            if operation != "place" or "name" in keywords:
                raise ValueError(f"{operation} does not accept a third positional value")
            keywords["name"] = values[2]
        values = ()
    return values, keywords


def _canonical_route_command(operation: str) -> str | None:
    normalized = {shared._command(command): command for command in _ROUTE_COMMANDS}
    normalized[shared._command("show")] = "search"
    return normalized.get(operation)


def _validated_route_dispatch(
    command: str,
    args: tuple[object, ...],
    options: dict[str, object],
) -> Any:
    """Resolve against one active registry snapshot and dispatch through its gate."""
    route_args, route_options = _maps_arguments(command, args, options)
    from ipad_agent.core.config import load_config
    from ipad_agent.core.registry import load_registry

    config = load_config()
    registry = load_registry(enabled_addons=config.enabled_addons)
    route = registry.resolve_url_route("maps", command, route_args, route_options)
    return shared._validated_route_open(
        route, config=config, registry=registry, terminate=True,
    )


def _candidate_plan_parameters(
    command: str,
    args: tuple[object, ...],
    options: dict[str, object],
) -> dict[str, object]:
    """Bind Python conveniences to named lab parameters without dispatching."""
    if "allow_explicit" in options:
        raise ValueError("allow_explicit is not candidate authorization; review and authorize the bound lab plan")
    route_args, parameters = _maps_arguments(command, args, options)
    positional = {
        "navigate": ("destination", "source"),
        "report-a-problem": ("address",),
    }[command]
    if len(route_args) > len(positional):
        raise ValueError(f"{command} received too many positional arguments")
    for name, value in zip(positional, route_args, strict=False):
        if name in parameters:
            raise ValueError(f"{name} was assigned more than once")
        parameters[name] = value
    return parameters


def _plan_candidate(command: object, *args: object, **options: object) -> Any:
    """Return a sealed-lab plan for one candidate; never dispatch a device action."""
    operation = ""
    try:
        operation = shared._command(command)
        canonical = _canonical_route_command(operation)
        scenario = _CANDIDATE_SCENARIOS.get(canonical or "")
        if scenario is None:
            raise ValueError("candidate probe accepts explicit candidate routes only")
        route = _load_compatibility().get(canonical)
        if route is None or route["availability"] != "candidate":
            raise ValueError("candidate probe accepts candidate routes only")
        parameters = _candidate_plan_parameters(canonical, tuple(args), dict(options))
        from ipad_agent.lab import plan_scenario

        return plan_scenario(_DIRECTORY / "integration.json", scenario, parameters=parameters)
    except (TypeError, ValueError, OSError, KeyError) as error:
        return shared._rejected_route("maps", operation, error, display_name="Maps")


def maps(command: object, *args: object, **options: object) -> Any:
    """Activate Maps or dispatch a route proven for the exact target profile/build."""
    operation = ""
    try:
        operation = shared._command(command)
        if operation == "open":
            if args or options:
                raise ValueError("open takes no arguments")
            return shared._direct_open(_BUNDLE)
        canonical = _canonical_route_command(operation)
        if canonical is None:
            return shared._unsupported(operation, COMMANDS)
        availability = _load_compatibility()[canonical]["availability"]
        if availability != "proven":
            raise ValueError(
                f"Maps route {canonical!r} is {availability} for product iPad17,1, "
                "hardware J817AP, build 23G83"
            )
        return _validated_route_dispatch(canonical, tuple(args), dict(options))
    except (TypeError, ValueError, OSError, KeyError) as error:
        return shared._rejected_route("maps", operation, error, display_name="Maps")


__all__ = ["maps"]
