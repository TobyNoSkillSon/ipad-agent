"""Application-owned Google Maps semantic routes."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ipad_agent.core import commands as shared

COMMANDS = ("open", "search", "show", "directions", "map", "street-view", "link", "navigate")
_ROUTE_COMMANDS = ("open", "search", "directions", "map", "street-view", "link", "navigate")
_DIRECTORY = Path(__file__).parent
_COMPATIBILITY_PATH = _DIRECTORY / "route-compatibility.json"
_PROFILE_REF = "device-profiles/ipad17-1-j817ap-google-maps-26.33.1-ipados-26.6.1-23g83.json"
_BUNDLE = "Google Maps"
_CANDIDATE_SCENARIOS = {"navigate": "navigate-candidate"}


def _load_compatibility() -> dict[str, dict[str, object]]:
    data = json.loads(_COMPATIBILITY_PATH.read_text(encoding="utf-8"))
    if data.get("schema") != "ipad-agent.google-maps-route-compatibility/v1" or data.get("version") != 1 or data.get("profile") != _PROFILE_REF:
        raise ValueError("Google Maps compatibility identity is invalid")
    routes = data.get("routes")
    if not isinstance(routes, list) or [item.get("command") for item in routes if isinstance(item, dict)] != list(_ROUTE_COMMANDS):
        raise ValueError("Google Maps compatibility routes are invalid")
    indexed = {str(item["command"]): item for item in routes}
    for command, route in indexed.items():
        if route.get("availability") not in {"candidate", "proven", "incompatible"}:
            raise ValueError(f"Google Maps route {command} availability is invalid")
        if route.get("production") not in {"admitted", "candidate-gated"}:
            raise ValueError(f"Google Maps route {command} production status is invalid")
        if route["production"] == "admitted" and route["availability"] != "proven":
            raise ValueError(f"Google Maps route {command} cannot be admitted without proof")
    return indexed


def _canonical(operation: str) -> str | None:
    if operation == shared._command("show"):
        return "search"
    return {shared._command(name): name for name in _ROUTE_COMMANDS}.get(operation)


def _join_ordered(value: object, name: str, *, maximum: int) -> tuple[str, int]:
    if not isinstance(value, (tuple, list)) or not value or len(value) > maximum:
        raise ValueError(f"{name} must be an ordered list of 1 to {maximum} values")
    checked: list[str] = []
    for item in value:
        text = shared._text(item, name)
        if "|" in text:
            raise ValueError(f"{name} entries must not contain pipe separators")
        checked.append(text)
    return "|".join(checked), len(checked)


def _route_arguments(command: str, args: tuple[object, ...], options: dict[str, object]) -> tuple[tuple[object, ...], dict[str, object]]:
    values = tuple(args)
    keywords = dict(options)
    if command not in {"link", "open"}:
        keywords["api"] = "1"
    if command == "map":
        keywords["map_action"] = "map"
    elif command == "street-view":
        keywords["map_action"] = "pano"
    elif command == "navigate":
        keywords["dir_action"] = "navigate"
    if command in {"directions", "navigate"}:
        waypoint_count = None
        if "waypoints" in keywords:
            keywords["waypoints"], waypoint_count = _join_ordered(keywords["waypoints"], "waypoints", maximum=3)
        if "waypoint_place_ids" in keywords:
            keywords["waypoint_place_ids"], place_count = _join_ordered(keywords["waypoint_place_ids"], "waypoint_place_ids", maximum=3)
            if waypoint_count is None or place_count != waypoint_count:
                raise ValueError("waypoint_place_ids must match waypoints in count and order")
    return values, keywords


def _dispatch(command: str, args: tuple[object, ...], options: dict[str, object]) -> Any:
    from ipad_agent.core.config import load_config
    from ipad_agent.core.registry import load_registry
    config = load_config()
    registry = load_registry(enabled_addons=config.enabled_addons)
    route_args, route_options = _route_arguments(command, args, options)
    route = registry.resolve_url_route("google-maps", command, route_args, route_options)
    return shared._validated_route_open(route, config=config, registry=registry)


def _candidate_plan_parameters(
    command: str,
    args: tuple[object, ...],
    options: dict[str, object],
) -> dict[str, object]:
    if "allow_explicit" in options:
        raise ValueError("allow_explicit is not candidate authorization; review and authorize the bound lab plan")
    route_args, parameters = _route_arguments(command, args, options)
    if len(route_args) != 1:
        raise ValueError("navigate requires exactly one destination")
    if "destination" in parameters:
        raise ValueError("destination was assigned more than once")
    parameters["destination"] = route_args[0]
    return parameters


def _plan_candidate(command: object, *args: object, **options: object) -> Any:
    """Return a sealed-lab plan for one candidate; never dispatch a device action."""
    operation = ""
    try:
        operation = shared._command(command)
        canonical = _canonical(operation)
        scenario = _CANDIDATE_SCENARIOS.get(canonical or "")
        if scenario is None:
            raise ValueError("candidate probe accepts explicit Google Maps candidates only")
        route = _load_compatibility()[canonical]
        if route["availability"] != "candidate" or route["production"] != "candidate-gated":
            raise ValueError("candidate probe accepts candidate-gated routes only")
        parameters = _candidate_plan_parameters(canonical, tuple(args), dict(options))
        from ipad_agent.lab import plan_scenario

        return plan_scenario(_DIRECTORY / "integration.json", scenario, parameters=parameters)
    except (TypeError, ValueError, OSError, KeyError, json.JSONDecodeError) as error:
        return shared._rejected_route("google-maps", operation, error, display_name=_BUNDLE)


def google_maps(command: object, *args: object, **options: object) -> Any:
    operation = ""
    try:
        operation = shared._command(command)
        canonical = _canonical(operation)
        if canonical is None:
            return shared._unsupported(operation, COMMANDS)
        route = _load_compatibility()[canonical]
        if route["availability"] != "proven" or route["production"] != "admitted":
            raise ValueError(f"Google Maps route {canonical!r} is {route['availability']} for product iPad17,1, hardware J817AP, build 23G83")
        if canonical == "open":
            if args or options:
                raise ValueError("open takes no arguments")
            return shared._direct_open(_BUNDLE)
        return _dispatch(canonical, tuple(args), dict(options))
    except (TypeError, ValueError, OSError, KeyError, json.JSONDecodeError) as error:
        return shared._rejected_route("google-maps", operation, error, display_name=_BUNDLE)


__all__ = ["google_maps"]
