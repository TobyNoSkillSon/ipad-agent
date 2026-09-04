"""Strict, explicit integration manifest registry.

Only ``integrations/index.json`` is used for discovery.  The registry never
walks integration directories and never imports integration code.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any
import unicodedata

from ipad_agent.core.paths import REPO_ROOT

REPOSITORY_ROOT = REPO_ROOT
DEFAULT_INDEX_PATH = REPOSITORY_ROOT / "integrations" / "index.json"
CORE_INTEGRATIONS = frozenset({
    "safari", "maps", "google-maps", "pages", "numbers", "keynote", "photos", "messages", "files", "settings", "clock", "preview", "books", "appstore",
})
_INDEX_SCHEMA = "ipad-agent.integrations-index/v1"
_MANIFEST_SCHEMA = "ipad-agent.integration/v1"
_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_BUNDLE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*(?:\.[A-Za-z0-9][A-Za-z0-9-]*)+$")
_SELECTOR_USING = frozenset({
    "accessibility id", "-ios predicate string", "xpath", "class name",
    "-ios class chain", "id", "name",
})
_SAFETY_CLASSES = ("observe", "navigate", "transient", "persistent", "protected")
_RETRY_CLASSES = ("safe_repeat", "inspect_then_decide", "never_automated")
_SAFETY_RANK = {name: rank for rank, name in enumerate(_SAFETY_CLASSES)}
_RETRY_RANK = {name: rank for rank, name in enumerate(_RETRY_CLASSES)}
_STEP_SAFETY = {
    "inspect": "observe",
    "wait": "observe",
    "activate": "navigate",
    "open-url": "transient",
    "tap": "transient",
    "clear-type": "transient",
    "type": "transient",
    "swipe": "transient",
}
# Manifest-level profiles describe the integration as a whole.  Executable
# action/scenario safety uses the operation classes above.
_INTEGRATION_SAFETY_PROFILES = frozenset({
    "bounded-ui-navigation",
    "navigate-and-transient-map-query",
    "bounded-files-navigation",
    "settings-navigation-only",
    "clock-navigation-and-transient-stopwatch",
    "optional-browser-navigation-with-persistent-tab-state",
})
_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z][A-Za-z0-9_]*)\}")
_PLACEHOLDER_TOKEN_RE = re.compile(r"\{[^{}]*\}")


class RegistryError(ValueError):
    """The explicit registry or one of its manifests is invalid."""


class IntegrationNotFoundError(KeyError):
    """No enabled integration matches the supplied name or bundle ID."""


class AddonNotEnabledError(IntegrationNotFoundError):
    """The requested integration is an installed but disabled addon."""


def normalize_name(value: str) -> str:
    """Normalize human aliases and selector names without changing bundle IDs."""
    if not isinstance(value, str):
        raise TypeError("name must be a string")
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    return " ".join(normalized.replace("_", " ").replace("-", " ").split())


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RegistryError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise RegistryError(f"non-finite JSON number is not allowed: {value}")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle, object_pairs_hook=_strict_object, parse_constant=_invalid_constant)
    except RegistryError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RegistryError(f"cannot load {path}: {error}") from error
    if not isinstance(value, dict):
        raise RegistryError(f"{path} must contain a JSON object")
    return value


def _object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RegistryError(f"{context} must be an object")
    return value


def _string(value: Any, context: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value.strip()):
        raise RegistryError(f"{context} must be a non-empty string")
    return value.strip() if nonempty else value


def _boolean(value: Any, context: str) -> bool:
    if not isinstance(value, bool):
        raise RegistryError(f"{context} must be a boolean")
    return value


def _integer(value: Any, context: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise RegistryError(f"{context} must be an integer greater than or equal to {minimum}")
    return value


def _keys(value: dict[str, Any], required: set[str], optional: set[str], context: str) -> None:
    missing = required - value.keys()
    extra = value.keys() - required - optional
    if missing:
        raise RegistryError(f"{context} is missing: {', '.join(sorted(missing))}")
    if extra:
        raise RegistryError(f"{context} has unknown fields: {', '.join(sorted(extra))}")


def _string_list(value: Any, context: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        qualification = "non-empty " if not allow_empty else ""
        raise RegistryError(f"{context} must be a {qualification}array of strings")
    result: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        text = _string(item, f"{context}[{index}]")
        normalized = normalize_name(text)
        if normalized in seen:
            raise RegistryError(f"{context} contains a duplicate value: {text}")
        seen.add(normalized)
        result.append(text)
    return result


def _validate_index(value: dict[str, Any], path: Path) -> list[dict[str, Any]]:
    context = str(path)
    _keys(value, {"$schema", "schema", "version", "integrations"}, set(), context)
    if value["$schema"] != "../schemas/integrations-index-v1.json":
        raise RegistryError(f"{context}.$schema must reference ../schemas/integrations-index-v1.json")
    if value["schema"] != _INDEX_SCHEMA:
        raise RegistryError(f"{context}.schema must be {_INDEX_SCHEMA!r}")
    if _integer(value["version"], f"{context}.version", minimum=1) != 1:
        raise RegistryError(f"{context}.version must be 1")
    entries = value["integrations"]
    if not isinstance(entries, list) or not entries:
        raise RegistryError(f"{context}.integrations must be a non-empty array")
    result: list[dict[str, Any]] = []
    ids: set[str] = set()
    paths: set[str] = set()
    alias_owners: dict[str, str] = {}
    bundle_owners: dict[str, str] = {}
    for position, raw in enumerate(entries):
        entry_context = f"{context}.integrations[{position}]"
        entry = _object(raw, entry_context)
        _keys(entry, {"id", "kind", "manifest", "category", "aliases", "bundle_ids"}, set(), entry_context)
        integration_id = _string(entry["id"], f"{entry_context}.id")
        if not _ID_RE.fullmatch(integration_id):
            raise RegistryError(f"{entry_context}.id is not a canonical integration ID")
        kind = entry["kind"]
        if kind not in {"core", "addon"}:
            raise RegistryError(f"{entry_context}.kind must be 'core' or 'addon'")
        category = entry["category"]
        if category not in {"application", "browser"}:
            raise RegistryError(f"{entry_context}.category must be 'application' or 'browser'")
        manifest = _string(entry["manifest"], f"{entry_context}.manifest")
        manifest_parts = Path(manifest).parts
        if (
            len(manifest_parts) != 2
            or manifest_parts[0] in {"", ".", ".."}
            or manifest_parts[1] != "integration.json"
        ):
            raise RegistryError(
                f"{entry_context}.manifest must name one application package integration.json"
            )
        if integration_id in ids:
            raise RegistryError(f"duplicate integration ID in index: {integration_id}")
        canonical_path = manifest.casefold()
        if canonical_path in paths:
            raise RegistryError(f"duplicate manifest path in index: {manifest}")
        aliases = _string_list(entry["aliases"], f"{entry_context}.aliases", allow_empty=False)
        if normalize_name(integration_id) not in {normalize_name(alias) for alias in aliases}:
            raise RegistryError(f"{entry_context}.aliases must include the integration ID")
        bundle_ids = _string_list(entry["bundle_ids"], f"{entry_context}.bundle_ids", allow_empty=False)
        for alias in aliases:
            key = normalize_name(alias)
            previous = alias_owners.get(key)
            if previous is not None and previous != integration_id:
                raise RegistryError(f"duplicate integration alias {alias!r}: {previous} and {integration_id}")
            alias_owners[key] = integration_id
        for bundle in bundle_ids:
            if not _BUNDLE_RE.fullmatch(bundle):
                raise RegistryError(f"{entry_context}.bundle_ids contains an invalid bundle ID: {bundle}")
            key = bundle.casefold()
            previous = bundle_owners.get(key)
            if previous is not None and previous != integration_id:
                raise RegistryError(f"duplicate bundle ID {bundle!r}: {previous} and {integration_id}")
            bundle_owners[key] = integration_id
        ids.add(integration_id)
        paths.add(canonical_path)
        result.append({
            "id": integration_id, "kind": kind, "manifest": manifest,
            "category": category, "aliases": aliases, "bundle_ids": bundle_ids,
        })
    indexed_core = {
        entry["id"] for entry in result
        if entry["id"] in CORE_INTEGRATIONS and entry["kind"] == "core"
    }
    missing_core = CORE_INTEGRATIONS - indexed_core
    if missing_core:
        raise RegistryError(
            "required core integration(s) must remain indexed as core: "
            + ", ".join(sorted(missing_core))
        )
    return result


def _manifest_path(index_path: Path, entry: Mapping[str, Any]) -> Path:
    repository = index_path.parent.parent.resolve()
    candidate = (index_path.parent / entry["manifest"]).resolve()
    integrations_root = (repository / "integrations").resolve()
    if not _is_relative_to(candidate, integrations_root):
        raise RegistryError(f"{entry['id']} manifest must stay under {integrations_root}")
    return candidate


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _validate_selector(raw: Any, context: str) -> dict[str, Any]:
    selector = _object(raw, context)
    _keys(selector, {"using", "value"}, {"cache"}, context)
    using = _string(selector["using"], f"{context}.using")
    if using not in _SELECTOR_USING:
        raise RegistryError(f"{context}.using is unsupported: {using}")
    result: dict[str, Any] = {"using": using, "value": _string(selector["value"], f"{context}.value")}
    if "cache" in selector:
        result["cache"] = _boolean(selector["cache"], f"{context}.cache")
    return result


def _enum(value: Any, context: str, allowed: tuple[str, ...] | frozenset[str]) -> str:
    text = _string(value, context)
    if text not in allowed:
        raise RegistryError(f"{context} must be one of: {', '.join(allowed)}")
    return text


def _validate_placeholders(value: str, context: str) -> None:
    tokens = _PLACEHOLDER_TOKEN_RE.findall(value)
    valid_tokens = [match.group(0) for match in _PLACEHOLDER_RE.finditer(value)]
    if tokens != valid_tokens or value.count("{") != len(tokens) or value.count("}") != len(tokens):
        raise RegistryError(
            f"{context} contains an unsupported placeholder; use identifiers like {{query_name}}"
        )


def _validate_step(raw: Any, context: str, selectors: Mapping[str, str]) -> dict[str, Any]:
    step = _object(raw, context)
    _keys(step, {"operation"}, {"selector", "value", "seconds", "direction"}, context)
    operation = _enum(step["operation"], f"{context}.operation", tuple(_STEP_SAFETY))
    required_fields = {
        "activate": set(),
        "open-url": {"value"},
        "tap": {"selector"},
        "clear-type": {"selector", "value"},
        "type": {"value"},
        "wait": {"selector", "seconds"},
        "swipe": {"direction"},
        "inspect": {"selector"},
    }[operation]
    allowed_fields = required_fields | {"operation"}
    supplied = set(step)
    missing = required_fields - supplied
    extra = supplied - allowed_fields
    if missing:
        raise RegistryError(f"{context} is missing fields for {operation}: {', '.join(sorted(missing))}")
    if extra:
        raise RegistryError(f"{context} has fields not valid for {operation}: {', '.join(sorted(extra))}")

    result: dict[str, Any] = {"operation": operation}
    if "selector" in step:
        selector = _string(step["selector"], f"{context}.selector")
        canonical_selector = selectors.get(normalize_name(selector))
        if canonical_selector is None:
            raise RegistryError(f"{context}.selector references an unknown selector: {selector}")
        result["selector"] = canonical_selector
    if "value" in step:
        value = _string(step["value"], f"{context}.value")
        _validate_placeholders(value, f"{context}.value")
        result["value"] = value
    if "seconds" in step:
        seconds = step["seconds"]
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not 0 < seconds <= 120:
            raise RegistryError(f"{context}.seconds must be a number greater than 0 and at most 120")
        result["seconds"] = seconds
    if "direction" in step:
        result["direction"] = _enum(
            step["direction"], f"{context}.direction", ("up", "down", "left", "right")
        )
    return result


def _validate_manifest(value: dict[str, Any], path: Path, entry: Mapping[str, Any]) -> dict[str, Any]:
    context = str(path)
    required = {
        "$schema", "schema", "version", "id", "name", "kind", "bundle_ids", "aliases",
        "capabilities", "selectors", "actions", "scenarios", "safety", "retry",
        "requirements", "compatibility", "privacy",
    }
    _keys(value, required, set(), context)
    if value["$schema"] != "../../schemas/integration-v1.json":
        raise RegistryError(f"{context}.$schema must reference ../../schemas/integration-v1.json")
    if value["schema"] != _MANIFEST_SCHEMA:
        raise RegistryError(f"{context}.schema must be {_MANIFEST_SCHEMA!r}")
    if _integer(value["version"], f"{context}.version", minimum=1) != 1:
        raise RegistryError(f"{context}.version must be 1")
    integration_id = _string(value["id"], f"{context}.id")
    if integration_id != entry["id"] or not _ID_RE.fullmatch(integration_id):
        raise RegistryError(f"{context}.id must match index ID {entry['id']!r}")
    if value["kind"] != entry["kind"]:
        raise RegistryError(f"{context}.kind must match index kind {entry['kind']!r}")
    name = _string(value["name"], f"{context}.name")
    bundle_ids = _string_list(value["bundle_ids"], f"{context}.bundle_ids", allow_empty=False)
    bundle_keys: set[str] = set()
    for bundle in bundle_ids:
        if not _BUNDLE_RE.fullmatch(bundle):
            raise RegistryError(f"{context}.bundle_ids contains an invalid bundle ID: {bundle}")
        key = bundle.casefold()
        if key in bundle_keys:
            raise RegistryError(f"{context}.bundle_ids contains a duplicate bundle ID: {bundle}")
        bundle_keys.add(key)
    aliases = _string_list(value["aliases"], f"{context}.aliases", allow_empty=False)
    alias_keys = {normalize_name(alias) for alias in aliases}
    if normalize_name(integration_id) not in alias_keys:
        raise RegistryError(f"{context}.aliases must include the integration ID")
    indexed_descriptor = "aliases" in entry and "bundle_ids" in entry
    if indexed_descriptor and aliases != entry["aliases"]:
        raise RegistryError(
            f"{context}.aliases has a duplicate integration alias or does not match the index descriptor"
        )
    if indexed_descriptor and bundle_ids != entry["bundle_ids"]:
        raise RegistryError(f"{context}.bundle_ids must exactly match the index descriptor")
    capabilities = _string_list(value["capabilities"], f"{context}.capabilities", allow_empty=False)
    capability_keys = {normalize_name(item): item for item in capabilities}

    selectors_raw = _object(value["selectors"], f"{context}.selectors")
    selectors: dict[str, dict[str, Any]] = {}
    selector_keys: dict[str, str] = {}
    for selector_name, raw in selectors_raw.items():
        _string(selector_name, f"{context}.selectors key")
        key = normalize_name(selector_name)
        if not key or key in selector_keys:
            raise RegistryError(f"{context}.selectors has a duplicate normalized name: {selector_name}")
        selector_keys[key] = selector_name
        selectors[selector_name] = _validate_selector(raw, f"{context}.selectors.{selector_name}")

    actions_raw = _object(value["actions"], f"{context}.actions")
    actions: dict[str, dict[str, Any]] = {}
    action_keys: set[str] = set()
    for action_name, raw in actions_raw.items():
        action_context = f"{context}.actions.{action_name}"
        action_id = _string(action_name, f"{context}.actions key")
        if not _ID_RE.fullmatch(action_id):
            raise RegistryError(f"{action_context} is not a canonical action ID")
        key = normalize_name(action_id)
        if key in action_keys:
            raise RegistryError(f"{context}.actions has a duplicate normalized name: {action_name}")
        action_keys.add(key)
        action = _object(raw, action_context)
        _keys(action, {"description", "capability", "steps", "safety", "retry"}, set(), action_context)
        capability = _string(action["capability"], f"{action_context}.capability")
        canonical_capability = capability_keys.get(normalize_name(capability))
        if canonical_capability is None:
            raise RegistryError(f"{action_context}.capability is not declared")
        capability = canonical_capability
        steps_raw = action["steps"]
        if not isinstance(steps_raw, list) or not steps_raw:
            raise RegistryError(f"{action_context}.steps must be a non-empty array")
        steps = [
            _validate_step(step, f"{action_context}.steps[{i}]", selector_keys)
            for i, step in enumerate(steps_raw)
        ]
        executable_safety = max(
            (_STEP_SAFETY[step["operation"]] for step in steps), key=_SAFETY_RANK.__getitem__
        )
        declared_safety = (
            _enum(action["safety"], f"{action_context}.safety", _SAFETY_CLASSES)
            if indexed_descriptor else executable_safety
        )
        if declared_safety != executable_safety:
            raise RegistryError(
                f"{action_context}.safety must be {executable_safety!r} for its executable steps"
            )
        declared_retry = (
            _enum(action["retry"], f"{action_context}.retry", _RETRY_CLASSES)
            if indexed_descriptor else (
                "safe_repeat" if executable_safety in {"observe", "navigate"}
                else "inspect_then_decide"
            )
        )
        if declared_safety == "persistent" and declared_retry == "safe_repeat":
            raise RegistryError(f"{action_context}.retry cannot be safe_repeat for persistent work")
        if declared_safety == "protected" and declared_retry != "never_automated":
            raise RegistryError(f"{action_context}.retry must be never_automated for protected work")
        actions[action_name] = {
            "description": _string(action["description"], f"{action_context}.description"),
            "capability": capability,
            "steps": steps,
            "safety": declared_safety,
            "retry": declared_retry,
        }

    scenarios_raw = _object(value["scenarios"], f"{context}.scenarios")
    scenarios: dict[str, dict[str, Any]] = {}
    scenario_keys: set[str] = set()
    for scenario_name, raw in scenarios_raw.items():
        scenario_context = f"{context}.scenarios.{scenario_name}"
        scenario_id = _string(scenario_name, f"{context}.scenarios key")
        if not _ID_RE.fullmatch(scenario_id):
            raise RegistryError(f"{scenario_context} is not a canonical scenario ID")
        key = normalize_name(scenario_id)
        if key in scenario_keys:
            raise RegistryError(f"{context}.scenarios has a duplicate normalized name: {scenario_name}")
        scenario_keys.add(key)
        scenario = _object(raw, scenario_context)
        _keys(scenario, {"description", "capabilities", "actions", "safety", "retry"}, set(), scenario_context)
        scenario_capabilities = _string_list(scenario["capabilities"], f"{scenario_context}.capabilities", allow_empty=False)
        unknown_capabilities = {normalize_name(item) for item in scenario_capabilities} - set(capability_keys)
        if unknown_capabilities:
            raise RegistryError(f"{scenario_context}.capabilities references undeclared capabilities")
        scenario_capabilities = [capability_keys[normalize_name(item)] for item in scenario_capabilities]
        scenario_actions = _string_list(scenario["actions"], f"{scenario_context}.actions", allow_empty=False)
        action_names = {normalize_name(name): name for name in actions}
        unknown_actions = {normalize_name(item) for item in scenario_actions} - set(action_names)
        if unknown_actions:
            raise RegistryError(f"{scenario_context}.actions references unknown actions")
        scenario_actions = [action_names[normalize_name(item)] for item in scenario_actions]
        executable_safety = max(
            (actions[action]["safety"] for action in scenario_actions), key=_SAFETY_RANK.__getitem__
        )
        executable_retry = max(
            (actions[action]["retry"] for action in scenario_actions), key=_RETRY_RANK.__getitem__
        )
        declared_safety = (
            _enum(scenario["safety"], f"{scenario_context}.safety", _SAFETY_CLASSES)
            if indexed_descriptor else executable_safety
        )
        declared_retry = (
            _enum(scenario["retry"], f"{scenario_context}.retry", _RETRY_CLASSES)
            if indexed_descriptor else executable_retry
        )
        if declared_safety != executable_safety:
            raise RegistryError(
                f"{scenario_context}.safety must be {executable_safety!r} for its actions"
            )
        if declared_retry != executable_retry:
            raise RegistryError(
                f"{scenario_context}.retry must be {executable_retry!r} for its actions"
            )
        scenarios[scenario_name] = {
            "description": _string(scenario["description"], f"{scenario_context}.description"),
            "capabilities": scenario_capabilities,
            "actions": scenario_actions,
            "safety": declared_safety,
            "retry": declared_retry,
        }

    safety = _object(value["safety"], f"{context}.safety")
    _keys(safety, {"classification", "mutates_user_data", "requires_confirmation", "prohibited", "uncertain_outcome"}, set(), f"{context}.safety")
    normalized_safety = {
        "classification": _enum(
            safety["classification"], f"{context}.safety.classification",
            _INTEGRATION_SAFETY_PROFILES,
        ),
        "mutates_user_data": _boolean(safety["mutates_user_data"], f"{context}.safety.mutates_user_data"),
        "requires_confirmation": _string_list(safety["requires_confirmation"], f"{context}.safety.requires_confirmation"),
        "prohibited": _string_list(safety["prohibited"], f"{context}.safety.prohibited"),
        "uncertain_outcome": _string(safety["uncertain_outcome"], f"{context}.safety.uncertain_outcome"),
    }
    retry = _object(value["retry"], f"{context}.retry")
    _keys(retry, {"default", "max_attempts", "idempotent_actions"}, set(), f"{context}.retry")
    idempotent = _string_list(retry["idempotent_actions"], f"{context}.retry.idempotent_actions")
    action_names = {normalize_name(name): name for name in actions}
    if {normalize_name(item) for item in idempotent} - set(action_names):
        raise RegistryError(f"{context}.retry.idempotent_actions references unknown actions")
    idempotent = [action_names[normalize_name(item)] for item in idempotent]
    safe_repeat_actions = {
        normalize_name(name) for name, action in actions.items() if action["retry"] == "safe_repeat"
    }
    if {normalize_name(item) for item in idempotent} != safe_repeat_actions:
        raise RegistryError(
            f"{context}.retry.idempotent_actions must exactly list actions classified safe_repeat"
        )
    normalized_retry = {
        "default": (
            _enum(retry["default"], f"{context}.retry.default", _RETRY_CLASSES)
            if indexed_descriptor else "inspect_then_decide"
        ),
        "max_attempts": _integer(retry["max_attempts"], f"{context}.retry.max_attempts", minimum=1),
        "idempotent_actions": idempotent,
    }
    requirements = _object(value["requirements"], f"{context}.requirements")
    _keys(requirements, {"host", "device", "permissions"}, set(), f"{context}.requirements")
    normalized_requirements = {key: _string_list(requirements[key], f"{context}.requirements.{key}") for key in ("host", "device", "permissions")}
    compatibility = _object(value["compatibility"], f"{context}.compatibility")
    compatibility_required = {"platform", "minimum_os", "maximum_os", "locales"}
    if indexed_descriptor:
        compatibility_required |= {"verification", "app_versions"}
    _keys(
        compatibility,
        compatibility_required,
        set() if indexed_descriptor else {"verification", "app_versions"},
        f"{context}.compatibility",
    )
    maximum_os = compatibility["maximum_os"]
    if maximum_os is not None:
        maximum_os = _string(maximum_os, f"{context}.compatibility.maximum_os")
    platform = _string(compatibility["platform"], f"{context}.compatibility.platform")
    if platform != "iPadOS":
        raise RegistryError(f"{context}.compatibility.platform must be 'iPadOS'")
    verification = _enum(
        compatibility.get("verification", "unverified"),
        f"{context}.compatibility.verification",
        ("unverified",),
    )
    app_versions = _string_list(
        compatibility.get("app_versions", []), f"{context}.compatibility.app_versions"
    )
    if verification == "unverified" and app_versions:
        raise RegistryError(f"{context}.compatibility.app_versions must be empty while unverified")
    normalized_compatibility = {
        "verification": verification,
        "platform": platform,
        "minimum_os": _string(compatibility["minimum_os"], f"{context}.compatibility.minimum_os"),
        "maximum_os": maximum_os,
        "locales": _string_list(compatibility["locales"], f"{context}.compatibility.locales", allow_empty=False),
        "app_versions": app_versions,
    }
    privacy = _object(value["privacy"], f"{context}.privacy")
    _keys(privacy, {"data_access", "data_sent", "retention", "notes"}, set(), f"{context}.privacy")
    normalized_privacy = {
        "data_access": _string_list(privacy["data_access"], f"{context}.privacy.data_access"),
        "data_sent": _string_list(privacy["data_sent"], f"{context}.privacy.data_sent"),
        "retention": _string(privacy["retention"], f"{context}.privacy.retention"),
        "notes": _string(privacy["notes"], f"{context}.privacy.notes"),
    }
    return {
        "$schema": value["$schema"], "schema": _MANIFEST_SCHEMA, "version": 1,
        "id": integration_id, "name": name, "kind": entry["kind"],
        "bundle_ids": bundle_ids, "aliases": aliases, "capabilities": capabilities,
        "selectors": selectors, "actions": actions, "scenarios": scenarios,
        "safety": normalized_safety, "retry": normalized_retry,
        "requirements": normalized_requirements, "compatibility": normalized_compatibility,
        "privacy": normalized_privacy,
    }


@dataclass(frozen=True)
class Integration(Mapping[str, Any]):
    """A validated manifest and its inert, declarative URL policy sidecar."""

    _data: Mapping[str, Any]
    path: Path
    category: str
    url_policy: Any = None
    policy_path: Path | None = None
    policy_bytes: bytes | None = None

    @property
    def policy_sha256(self) -> str | None:
        return None if self.url_policy is None else self.url_policy.sha256

    @property
    def id(self) -> str:
        return self._data["id"]

    @property
    def name(self) -> str:
        return self._data["name"]

    @property
    def kind(self) -> str:
        return self._data["kind"]

    @property
    def bundle_ids(self) -> tuple[str, ...]:
        return tuple(self._data["bundle_ids"])

    @property
    def bundle_id(self) -> str:
        return self.bundle_ids[0]

    @property
    def aliases(self) -> tuple[str, ...]:
        return tuple(self._data["aliases"])

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(dict(self._data))


class IntegrationRegistry:
    """Validated core integrations plus an explicit set of enabled addons."""

    def __init__(self, index_path: str | Path = DEFAULT_INDEX_PATH, *, enabled_addons: Iterable[str] = ()) -> None:
        if isinstance(enabled_addons, (str, bytes)):
            raise TypeError("enabled_addons must be an iterable of addon IDs, not a string")
        self.index_path = Path(index_path).expanduser().resolve()
        index = _read_json(self.index_path)
        entries = _validate_index(index, self.index_path)
        requested = {normalize_name(item) for item in enabled_addons}
        if "" in requested:
            raise RegistryError("enabled addon IDs must be non-empty strings")

        addon_entries = {entry["id"]: entry for entry in entries if entry["kind"] == "addon"}
        addon_references: dict[str, str] = {}
        for addon_id, entry in addon_entries.items():
            for alias in entry["aliases"]:
                addon_references[normalize_name(alias)] = addon_id
        enabled_ids: set[str] = set()
        unknown: set[str] = set()
        for reference in requested:
            addon_id = addon_references.get(reference)
            if addon_id is None:
                unknown.add(reference)
            else:
                enabled_ids.add(addon_id)
        if unknown:
            raise RegistryError(f"unknown addon(s): {', '.join(sorted(unknown))}")

        active: dict[str, Integration] = {}
        alias_owner: dict[str, Integration] = {}
        bundle_owner: dict[str, Integration] = {}
        for entry in entries:
            # A disabled addon is index metadata only.  Its manifest path is not
            # resolved, opened, parsed, or validated and therefore cannot break
            # core registry loading or introduce runtime requirements.
            if entry["kind"] == "addon" and entry["id"] not in enabled_ids:
                continue
            path = _manifest_path(self.index_path, entry)
            manifest = _validate_manifest(_read_json(path), path, entry)
            open_url_actions = {
                action_id for action_id, action in manifest["actions"].items()
                if any(step["operation"] == "open-url" for step in action["steps"])
            }
            policy_path = path.with_name("url-policy.json")
            policy = None
            policy_bytes = None
            if open_url_actions:
                try:
                    policy_bytes = policy_path.read_bytes()
                except OSError as error:
                    raise RegistryError(f"cannot load {policy_path}: {error}") from error
                try:
                    from ipad_agent.core.urlroutes import load_url_policy
                    policy = load_url_policy(
                        policy_bytes,
                        integration_id=manifest["id"],
                        bundle_ids=manifest["bundle_ids"],
                        actions=manifest["actions"],
                        context=str(policy_path),
                    )
                except (TypeError, ValueError) as error:
                    raise RegistryError(str(error)) from error
                if policy.schema == "ipad-agent.url-policy/v1":
                    if manifest["id"] not in {"safari", "brave"}:
                        raise RegistryError(
                            f"{policy_path} URL policy v1 is reserved for legacy Safari and Brave integrations"
                        )
                    if set(policy.actions) != open_url_actions:
                        raise RegistryError(
                            f"{policy_path} must bind every and only manifest open-url action"
                        )
            elif policy_path.exists():
                raise RegistryError(f"{policy_path} exists without a manifest open-url action")
            integration = Integration(
                MappingProxyType(manifest), path, entry["category"], policy,
                policy_path if policy is not None else None, policy_bytes,
            )
            active[integration.id] = integration
            aliases = set(integration.aliases) | {integration.id, integration.name}
            for alias in aliases:
                key = normalize_name(alias)
                previous = alias_owner.get(key)
                if previous is not None and previous.id != integration.id:
                    raise RegistryError(f"duplicate integration alias {alias!r}: {previous.id} and {integration.id}")
                alias_owner[key] = integration
            for bundle in integration.bundle_ids:
                key = bundle.casefold()
                previous = bundle_owner.get(key)
                if previous is not None and previous.id != integration.id:
                    raise RegistryError(f"duplicate bundle ID {bundle!r}: {previous.id} and {integration.id}")
                bundle_owner[key] = integration

        disabled_aliases: dict[str, str] = {}
        disabled_bundles: dict[str, str] = {}
        for addon_id, entry in addon_entries.items():
            if addon_id in enabled_ids:
                continue
            for alias in entry["aliases"]:
                disabled_aliases[normalize_name(alias)] = addon_id
            for bundle in entry["bundle_ids"]:
                disabled_bundles[bundle.casefold()] = addon_id
        self._integrations = MappingProxyType(active)
        self._aliases = MappingProxyType(alias_owner)
        self._bundles = MappingProxyType(bundle_owner)
        self._disabled_aliases = MappingProxyType(disabled_aliases)
        self._disabled_bundles = MappingProxyType(disabled_bundles)
        self._enabled_addons = frozenset(enabled_ids)

    @classmethod
    def load(cls, index_path: str | Path = DEFAULT_INDEX_PATH, *, enabled_addons: Iterable[str] = ()) -> "IntegrationRegistry":
        return cls(index_path, enabled_addons=enabled_addons)

    @property
    def integrations(self) -> Mapping[str, Integration]:
        return self._integrations

    @property
    def enabled_addons(self) -> frozenset[str]:
        return self._enabled_addons

    def __iter__(self) -> Iterator[str]:
        return iter(self._integrations)

    def __len__(self) -> int:
        return len(self._integrations)

    def _enforce_enabled(self, integration: Integration, requested: str) -> Integration:
        if integration.kind == "addon" and integration.id not in self._enabled_addons:
            raise AddonNotEnabledError(f"addon {integration.id!r} is not enabled (requested as {requested!r})")
        return integration

    def resolve(self, value: str) -> Integration:
        """Resolve an ID, human alias, display name, or bundle ID."""
        text = _string(value, "integration reference")
        integration = self._bundles.get(text.casefold()) or self._aliases.get(normalize_name(text))
        if integration is not None:
            return integration
        disabled_id = self._disabled_bundles.get(text.casefold()) or self._disabled_aliases.get(normalize_name(text))
        if disabled_id is not None:
            raise AddonNotEnabledError(f"addon {disabled_id!r} is not enabled (requested as {text!r})")
        raise IntegrationNotFoundError(text)

    resolve_alias = resolve

    def resolve_bundle(self, value: str) -> str:
        """Return the primary bundle ID for an enabled integration reference."""
        return self.resolve(value).bundle_id

    def resolve_action(self, app: str, command: str) -> dict[str, Any]:
        """Resolve one declared v2 command to its owning manifest action."""
        integration = self.resolve(app)
        policy = integration.url_policy
        if policy is None or policy.schema != "ipad-agent.url-policy/v2":
            raise RegistryError(f"integration {integration.id!r} has no v2 command policy")
        route = policy.resolve(command)
        action = deepcopy(integration["actions"][route.action_id])
        action.update({
            "_integration": integration.id,
            "_action": route.action_id,
            "_bundle": route.bundle_id,
            "_command": route.command,
            "_policy_sha256": route.policy_sha256,
        })
        return action

    def resolve_url_route(
        self, app: str, command: str, arguments: Iterable[Any] = (),
        options: Mapping[str, Any] | None = None,
    ) -> Any:
        """Bind raw values and return one immutable, fully validated URL route."""
        integration = self.resolve(app)
        policy = integration.url_policy
        if policy is None:
            raise RegistryError(f"integration {integration.id!r} has no URL policy")
        from ipad_agent.core.urlroutes import resolve_url_route
        return resolve_url_route(policy, command, arguments, options)

    def validate_v1_url(self, app: str, action_id: str, url: str) -> str:
        """Validate a legacy v1 URL action without widening its scheme policy."""
        integration = self.resolve(app)
        policy = integration.url_policy
        if policy is None:
            raise RegistryError(f"integration {integration.id!r} has no URL policy")
        from ipad_agent.core.urlroutes import validate_v1_url
        return validate_v1_url(policy, action_id, url)

    def resolve_selector(self, app_or_reference: str, selector: str | None = None) -> dict[str, Any]:
        """Resolve ``app.selector`` or a separate app and selector pair.

        The returned recipe is a copy and includes ``_bundle``, ``_integration``
        and ``_selector`` routing metadata for the runtime.
        """
        if selector is None:
            reference = _string(app_or_reference, "selector reference")
            integration: Integration | None = None
            selector_name: str | None = None
            # Try every dot boundary so aliases remain deterministic while
            # bundle IDs can still be used in the two-argument form.
            positions = [index for index, character in enumerate(reference) if character == "."]
            for position in positions:
                app = reference[:position]
                candidate = reference[position + 1:]
                if not candidate:
                    continue
                try:
                    integration = self.resolve(app)
                except AddonNotEnabledError:
                    raise
                except IntegrationNotFoundError:
                    continue
                selector_name = candidate
                break
            if integration is None or selector_name is None:
                raise IntegrationNotFoundError(f"qualified selector required: {reference!r}")
        else:
            integration = self.resolve(app_or_reference)
            selector_name = _string(selector, "selector")
        selectors = integration["selectors"]
        wanted = normalize_name(selector_name)
        matches = [(name, recipe) for name, recipe in selectors.items() if normalize_name(name) == wanted]
        if not matches:
            raise KeyError(f"unknown selector {selector_name!r} for integration {integration.id!r}")
        canonical_name, recipe = matches[0]
        result = deepcopy(recipe)
        result.update({"_bundle": integration.bundle_id, "_integration": integration.id, "_selector": canonical_name})
        return result

    selector = resolve_selector


def load_registry(index_path: str | Path = DEFAULT_INDEX_PATH, *, enabled_addons: Iterable[str] = ()) -> IntegrationRegistry:
    """Load the repository registry without scanning or importing integrations."""
    return IntegrationRegistry(index_path, enabled_addons=enabled_addons)


def indexed_addon_for_bundle(
    bundle_id: str, index_path: str | Path = DEFAULT_INDEX_PATH
) -> tuple[str, tuple[str, ...]] | None:
    """Return ``(addon_id, aliases)`` using index metadata only.

    This helper deliberately never resolves or reads a manifest.  Configuration
    uses it to prevent a low-level alias from routing to a known disabled addon.
    """
    text = _string(bundle_id, "bundle ID")
    entries = _validate_index(_read_json(Path(index_path).expanduser().resolve()), Path(index_path).expanduser().resolve())
    for entry in entries:
        if entry["kind"] == "addon" and text.casefold() in {
            bundle.casefold() for bundle in entry["bundle_ids"]
        }:
            return entry["id"], tuple(entry["aliases"])
    return None


__all__ = [
    "AddonNotEnabledError", "CORE_INTEGRATIONS", "DEFAULT_INDEX_PATH", "Integration",
    "IntegrationNotFoundError", "IntegrationRegistry", "RegistryError", "indexed_addon_for_bundle",
    "load_registry", "normalize_name",
]
