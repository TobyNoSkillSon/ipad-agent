"""Lazy application forwards for the historical :mod:`ipad_agent.commands` API."""
from __future__ import annotations

import importlib
from typing import Any


def _application_command(
    module: str, function: str, *args: object, **options: object
) -> Any:
    implementation = importlib.import_module(f"integrations.{module}.commands")
    return getattr(implementation, function)(*args, **options)


def preview(command: object, *args: object, **options: object) -> Any:
    return _application_command("preview", "preview", command, *args, **options)


def books(command: object, *args: object, **options: object) -> Any:
    return _application_command("books", "books", command, *args, **options)


def files(command: object, *args: object, **options: object) -> Any:
    return _application_command("files", "files", command, *args, **options)


def settings(command: object, *args: object, **options: object) -> Any:
    return _application_command("settings", "settings", command, *args, **options)


def clock(command: object, *args: object, **options: object) -> Any:
    return _application_command("clock", "clock", command, *args, **options)


def browser(
    target: str, command: object, *args: object, **options: object
) -> Any:
    """Compatibility browser selector backed by the active integration index."""
    from ipad_agent.core import commands as shared

    try:
        from ipad_agent.core.config import load_config
        from ipad_agent.core.registry import load_registry

        config = load_config()
        registry = load_registry(enabled_addons=config.enabled_addons)
        integration = registry.resolve(target)
        if integration.category != "browser":
            raise ValueError(f"integration {integration.id!r} is not a browser")
        module = integration.path.parent.name
        function = integration.id.replace("-", "_")
        return _application_command(
            module, function, command, *args, **options
        )
    except (TypeError, ValueError, OSError, KeyError) as error:
        return shared._failed(error)


def _resolve_short_maps_url(url: object, *, timeout: float = 3.0) -> str:
    implementation = importlib.import_module("integrations.apple_maps.commands")
    return implementation._resolve_short_maps_url(url, timeout=timeout)


def _maps_arguments(
    operation: str,
    args: tuple[object, ...],
    options: dict[str, object],
) -> tuple[tuple[object, ...], dict[str, object]]:
    facade = importlib.import_module("ipad_agent.commands")
    implementation = importlib.import_module("integrations.apple_maps.commands")
    return implementation._maps_arguments(
        operation, args, options, resolver=facade._resolve_short_maps_url
    )


def maps(command: object, *args: object, **options: object) -> Any:
    return _application_command("apple_maps", "maps", command, *args, **options)


def app_store(command: object, *args: object, **options: object) -> Any:
    return _application_command("appstore", "app_store", command, *args, **options)


APPLICATION_FORWARDS = {
    "app_store": app_store,
    "books": books,
    "browser": browser,
    "clock": clock,
    "files": files,
    "maps": maps,
    "preview": preview,
    "settings": settings,
    "_maps_arguments": _maps_arguments,
    "_resolve_short_maps_url": _resolve_short_maps_url,
}
