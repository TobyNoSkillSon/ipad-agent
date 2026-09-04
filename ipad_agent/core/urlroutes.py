"""Strict declarative URL routes for production app integrations.

Policies are data.  This module does not import or execute integration code and
never runs lab scenarios.  It binds raw Python values, constructs one canonical
URL, and validates the completed URL before it can cross the CoreDevice route
boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from types import MappingProxyType
from typing import Any, Iterable, Mapping
from urllib.parse import quote, unquote_to_bytes, urlencode, urlsplit
import unicodedata


MAX_URL_BYTES = 2048
_V1_SCHEMA = "ipad-agent.url-policy/v1"
_V2_SCHEMA = "ipad-agent.url-policy/v2"
_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_COMMAND_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_QUERY_RE = re.compile(r"^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$")
_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*$")
_BAD_ESCAPE_RE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_PARAMETER_TYPES = frozenset({
    "text", "coordinate", "span", "finite-number", "nonnegative-integer",
    "enum", "place-id", "enum-list",
})
_CONSTRAINTS = frozenset({
    "at-least-one", "exactly-one", "requires", "forbids-together",
    "same-length", "requires-value",
})
_SAFETY_RANK = {"observe": 0, "navigate": 1, "transient": 2, "persistent": 3, "protected": 4}
_RETRY_RANK = {"safe_repeat": 0, "inspect_then_decide": 1, "never_automated": 2}


class URLPolicyError(ValueError):
    """A URL policy or a route request violates the production contract."""


def _normalize_command(value: str) -> str:
    if not isinstance(value, str):
        raise URLPolicyError("command must be a string")
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    return "-".join(normalized.replace("_", " ").replace("-", " ").split())


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise URLPolicyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise URLPolicyError(f"non-finite JSON number is not allowed: {value}")


def _keys(value: Mapping[str, Any], required: set[str], optional: set[str], context: str) -> None:
    missing = required - set(value)
    extra = set(value) - required - optional
    if missing:
        raise URLPolicyError(f"{context} is missing: {', '.join(sorted(missing))}")
    if extra:
        raise URLPolicyError(f"{context} has unknown fields: {', '.join(sorted(extra))}")


def _object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise URLPolicyError(f"{context} must be an object")
    return value


def _string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise URLPolicyError(f"{context} must be a non-empty string")
    _controls(value, context)
    return value


def _boolean(value: Any, context: str) -> bool:
    if not isinstance(value, bool):
        raise URLPolicyError(f"{context} must be a boolean")
    return value


def _integer(value: Any, context: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise URLPolicyError(f"{context} must be an integer at least {minimum}")
    if maximum is not None and value > maximum:
        raise URLPolicyError(f"{context} must be at most {maximum}")
    return value


def _finite(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise URLPolicyError(f"{context} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise URLPolicyError(f"{context} must be a finite number")
    return number


def _controls(value: str, context: str) -> None:
    for character in value:
        if unicodedata.category(character) == "Cc":
            raise URLPolicyError(f"{context} must not contain control characters")


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


@dataclass(frozen=True)
class URLRouteSpec:
    integration_id: str
    command: str
    action_id: str
    bundle_id: str
    kind: str
    scheme: str | None
    host: str | None
    path: str | None
    paths: tuple[str, ...]
    canonical_commands: tuple[str, ...]
    parameters: tuple[Mapping[str, Any], ...]
    constraints: tuple[Mapping[str, Any], ...]
    max_url_bytes: int
    policy_sha256: str
    safety: str
    retry: str


@dataclass(frozen=True)
class ValidatedURLRoute:
    """One policy-authorized URL, suitable for plan/evidence serialization."""

    integration_id: str
    command: str
    action_id: str
    bundle_id: str
    url: str
    policy_sha256: str
    safety: str
    retry: str
    url_shape: str

    _SCHEMA = "ipad-agent.validated-url-route/v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self._SCHEMA,
            "integration_id": self.integration_id,
            "command": self.command,
            "action_id": self.action_id,
            "bundle_id": self.bundle_id,
            "url": self.url,
            "policy_sha256": self.policy_sha256,
            "safety": self.safety,
            "retry": self.retry,
            "url_shape": self.url_shape,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ValidatedURLRoute":
        """Reconstruct a strict record; policy revalidation remains mandatory."""
        if not isinstance(value, Mapping):
            raise URLPolicyError("validated URL route record must be an object")
        required = {
            "schema", "integration_id", "command", "action_id", "bundle_id", "url",
            "policy_sha256", "safety", "retry", "url_shape",
        }
        if set(value) != required or value.get("schema") != cls._SCHEMA:
            raise URLPolicyError("validated URL route record fields are invalid")
        integration_id = _string(value["integration_id"], "validated route integration_id")
        command = _string(value["command"], "validated route command")
        action_id = _string(value["action_id"], "validated route action_id")
        bundle_id = _string(value["bundle_id"], "validated route bundle_id")
        policy_sha256 = value["policy_sha256"]
        safety = value["safety"]
        retry = value["retry"]
        if not _ID_RE.fullmatch(integration_id) or not _COMMAND_RE.fullmatch(command) or not _ID_RE.fullmatch(action_id):
            raise URLPolicyError("validated URL route identity is not canonical")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*(?:\.[A-Za-z0-9][A-Za-z0-9-]*)+", bundle_id):
            raise URLPolicyError("validated URL route bundle is invalid")
        if not isinstance(policy_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", policy_sha256):
            raise URLPolicyError("validated URL route policy digest is invalid")
        if safety not in {"navigate", "transient"} or retry not in {"safe_repeat", "inspect_then_decide"}:
            raise URLPolicyError("validated URL route safety or retry contract is invalid")
        url = _string(value["url"], "validated route URL")
        url_shape = _string(value["url_shape"], "validated route URL shape")
        try:
            shape = urlsplit(url_shape)
        except ValueError as error:
            raise URLPolicyError("validated URL route shape is invalid") from error
        if shape.query or shape.fragment or not shape.scheme or not shape.netloc or shape.username is not None or shape.password is not None:
            raise URLPolicyError("validated URL route shape is invalid")
        scheme = shape.scheme
        if scheme != scheme.casefold() or not _SCHEME_RE.fullmatch(scheme):
            raise URLPolicyError("validated URL route scheme is invalid")
        host = _canonical_authority(
            shape.hostname or "", "validated route authority",
            require_multilabel=scheme in {"http", "https"},
        )
        path = _canonical_path(
            shape.path, "validated route path", allow_empty=scheme not in {"http", "https"},
        )
        _validate_url_shape(url, scheme, host, (path,), MAX_URL_BYTES)
        if url_shape != f"{scheme}://{host}{path}":
            raise URLPolicyError("validated URL route shape is not canonical")
        return cls(
            integration_id, command, action_id, bundle_id, url, policy_sha256,
            safety, retry, url_shape,
        )


@dataclass(frozen=True)
class URLPolicy:
    schema: str
    integration_id: str
    target_bundle: str | None
    max_url_bytes: int
    routes: Mapping[str, URLRouteSpec]
    aliases: Mapping[str, str]
    actions: Mapping[str, tuple[str, ...]]
    sha256: str
    normalized: Mapping[str, Any]

    def resolve(self, command: str) -> URLRouteSpec:
        wanted = _normalize_command(command)
        canonical = self.aliases.get(wanted, wanted)
        route = self.routes.get(canonical)
        if route is None:
            choices = ", ".join(sorted(set(self.routes) | set(self.aliases)))
            raise URLPolicyError(f"unknown command {command!r}; choose: {choices}")
        return route


def _parse_json_bytes(policy_bytes: bytes, context: str) -> dict[str, Any]:
    try:
        text = policy_bytes.decode("utf-8")
        value = json.loads(text, object_pairs_hook=_strict_object, parse_constant=_invalid_constant)
    except URLPolicyError:
        raise
    except (UnicodeError, json.JSONDecodeError) as error:
        raise URLPolicyError(f"cannot load {context}: {error}") from error
    return _object(value, context)


def _validate_v1(raw: dict[str, Any], integration_id: str, digest: str) -> URLPolicy:
    context = f"{integration_id} URL policy"
    _keys(raw, {"$schema", "schema", "version", "integration_id", "actions"}, set(), context)
    if raw["$schema"] != "../../schemas/url-policy-v1.json" or raw["schema"] != _V1_SCHEMA or raw["version"] != 1 or isinstance(raw["version"], bool):
        raise URLPolicyError(f"{context} has an unsupported v1 schema declaration")
    if raw["integration_id"] != integration_id:
        raise URLPolicyError(f"{context} integration_id must match {integration_id!r}")
    actions_raw = _object(raw["actions"], f"{context}.actions")
    actions: dict[str, tuple[str, ...]] = {}
    for action, schemes_raw in actions_raw.items():
        if not _ID_RE.fullmatch(action):
            raise URLPolicyError(f"{context}.actions has an invalid action ID: {action}")
        if not isinstance(schemes_raw, list) or not schemes_raw:
            raise URLPolicyError(f"{context}.actions.{action} must be a non-empty scheme array")
        schemes: list[str] = []
        for scheme in schemes_raw:
            text = _string(scheme, f"{context}.actions.{action}")
            if not _SCHEME_RE.fullmatch(text) or text != text.casefold() or text in schemes:
                raise URLPolicyError(f"{context}.actions.{action} contains an invalid or duplicate scheme")
            schemes.append(text)
        actions[action] = tuple(schemes)
    normalized = {
        "$schema": raw["$schema"], "schema": _V1_SCHEMA, "version": 1,
        "integration_id": integration_id,
        "actions": {key: list(value) for key, value in actions.items()},
    }
    return URLPolicy(
        _V1_SCHEMA, integration_id, None, MAX_URL_BYTES,
        MappingProxyType({}), MappingProxyType({}), MappingProxyType(actions), digest,
        _freeze(normalized),
    )


def _validate_parameter(raw: Any, context: str) -> dict[str, Any]:
    parameter = _object(raw, context)
    _keys(
        parameter,
        {"name", "query", "type", "required", "positional", "repeatable"},
        {"values", "minimum", "maximum"},
        context,
    )
    name = _string(parameter["name"], f"{context}.name")
    query = _string(parameter["query"], f"{context}.query")
    kind = _string(parameter["type"], f"{context}.type")
    if not _COMMAND_RE.fullmatch(name) or not _QUERY_RE.fullmatch(query):
        raise URLPolicyError(f"{context} name and query must be canonical identifiers")
    if kind not in _PARAMETER_TYPES:
        raise URLPolicyError(f"{context}.type is unsupported: {kind}")
    result: dict[str, Any] = {
        "name": name, "query": query, "type": kind,
        "required": _boolean(parameter["required"], f"{context}.required"),
        "positional": _boolean(parameter["positional"], f"{context}.positional"),
        "repeatable": _boolean(parameter["repeatable"], f"{context}.repeatable"),
    }
    if result["repeatable"] and kind not in {"text", "place-id"}:
        raise URLPolicyError(f"{context}.repeatable is supported only for text and place-id")
    if "values" in parameter:
        values = parameter["values"]
        if kind not in {"enum", "enum-list"} or not isinstance(values, list) or not values:
            raise URLPolicyError(f"{context}.values is valid only as a non-empty enum array")
        checked: list[str] = []
        for index, item in enumerate(values):
            text = _string(item, f"{context}.values[{index}]")
            _controls(text, f"{context}.values[{index}]")
            if text in checked:
                raise URLPolicyError(f"{context}.values contains a duplicate")
            checked.append(text)
        result["values"] = checked
    elif kind in {"enum", "enum-list"}:
        raise URLPolicyError(f"{context}.values is required for enum parameters")
    for field in ("minimum", "maximum"):
        if field in parameter:
            if kind not in {"finite-number", "nonnegative-integer"}:
                raise URLPolicyError(f"{context}.{field} is valid only for numeric parameters")
            number = _finite(parameter[field], f"{context}.{field}")
            if kind == "nonnegative-integer" and not number.is_integer():
                raise URLPolicyError(f"{context}.{field} must be an integer")
            result[field] = int(number) if kind == "nonnegative-integer" else number
    if kind == "nonnegative-integer" and result.get("minimum", 0) < 0:
        raise URLPolicyError(f"{context}.minimum must be nonnegative")
    if result.get("minimum") is not None and result.get("maximum") is not None and result["minimum"] > result["maximum"]:
        raise URLPolicyError(f"{context}.minimum must not exceed maximum")
    return result


def _validate_constraint(raw: Any, names: set[str], context: str) -> dict[str, Any]:
    constraint = _object(raw, context)
    _keys(constraint, {"kind", "fields"}, {"value"}, context)
    kind = _string(constraint["kind"], f"{context}.kind")
    if kind not in _CONSTRAINTS:
        raise URLPolicyError(f"{context}.kind is unsupported: {kind}")
    fields = constraint["fields"]
    if not isinstance(fields, list) or len(fields) < 2 or not all(isinstance(item, str) for item in fields):
        raise URLPolicyError(f"{context}.fields must contain at least two parameter names")
    if len(fields) != len(set(fields)) or not set(fields) <= names:
        raise URLPolicyError(f"{context}.fields contains duplicate or unknown parameters")
    if kind in {"requires", "same-length", "requires-value"} and len(fields) != 2:
        raise URLPolicyError(f"{context}.{kind} requires exactly two fields")
    result = {"kind": kind, "fields": list(fields)}
    if kind == "requires-value":
        result["value"] = _string(constraint.get("value"), f"{context}.value")
    elif "value" in constraint:
        raise URLPolicyError(f"{context}.value is valid only for requires-value")
    return result


def _canonical_authority(value: str, context: str, *, require_multilabel: bool) -> str:
    host = _string(value, context)
    if host != host.casefold() or len(host) > 253 or host.endswith("."):
        raise URLPolicyError(f"{context} must be a lowercase canonical authority")
    labels = host.split(".")
    if (require_multilabel and len(labels) < 2) or any(
        not label or len(label) > 63
        or re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label) is None
        for label in labels
    ):
        qualifier = " multi-label DNS" if require_multilabel else ""
        raise URLPolicyError(f"{context} must be a lowercase canonical{qualifier} authority")
    return host


def _canonical_path(value: Any, context: str, *, allow_empty: bool = False) -> str:
    if value == "" and allow_empty:
        return ""
    path = _string(value, context)
    if (
        not path.startswith("/") or "?" in path or "#" in path or "\\" in path
        or _BAD_ESCAPE_RE.search(path)
    ):
        raise URLPolicyError(f"{context} must be one canonical absolute URL path")
    try:
        canonical = quote(
            unquote_to_bytes(path), safe="/:@!$&'()*+,;=-._~",
        )
    except (UnicodeError, ValueError) as error:
        raise URLPolicyError(f"{context} must be one canonical absolute URL path") from error
    if canonical != path or any(segment in {".", ".."} for segment in path.split("/")):
        raise URLPolicyError(f"{context} must be one canonical absolute URL path")
    return path


def _validate_v2(
    raw: dict[str, Any], integration_id: str, bundle_ids: tuple[str, ...],
    actions: Mapping[str, Mapping[str, Any]], digest: str,
) -> URLPolicy:
    context = f"{integration_id} URL policy"
    _keys(raw, {"$schema", "schema", "version", "integration_id", "target_bundle", "max_url_bytes", "commands"}, set(), context)
    if raw["$schema"] != "../../schemas/url-policy-v2.json" or raw["schema"] != _V2_SCHEMA or raw["version"] != 2 or isinstance(raw["version"], bool):
        raise URLPolicyError(f"{context} has an unsupported v2 schema declaration")
    if raw["integration_id"] != integration_id:
        raise URLPolicyError(f"{context} integration_id must match {integration_id!r}")
    target_bundle = _string(raw["target_bundle"], f"{context}.target_bundle")
    if target_bundle not in bundle_ids or target_bundle != bundle_ids[0]:
        raise URLPolicyError(f"{context}.target_bundle must be the integration primary bundle")
    max_bytes = _integer(raw["max_url_bytes"], f"{context}.max_url_bytes", minimum=1, maximum=MAX_URL_BYTES)
    commands_raw = _object(raw["commands"], f"{context}.commands")
    if not commands_raw:
        raise URLPolicyError(f"{context}.commands must not be empty")

    preliminary: dict[str, dict[str, Any]] = {}
    aliases: dict[str, str] = {}
    action_routes: dict[str, list[str]] = {}
    for command_name, raw_command in commands_raw.items():
        if not _COMMAND_RE.fullmatch(command_name) or _normalize_command(command_name) != command_name:
            raise URLPolicyError(f"{context}.commands has a noncanonical command: {command_name}")
        command_context = f"{context}.commands.{command_name}"
        command = _object(raw_command, command_context)
        _keys(command, {"action", "aliases", "kind", "scheme", "host", "path", "paths", "canonical_commands", "parameters", "constraints"}, set(), command_context)
        action_id = _string(command["action"], f"{command_context}.action")
        if action_id not in actions:
            raise URLPolicyError(f"{command_context}.action is not declared by the manifest")
        action = actions[action_id]
        steps = action.get("steps")
        if not isinstance(steps, list) or len(steps) != 1:
            raise URLPolicyError(f"{command_context}.action must contain exactly one step")
        kind = _string(command["kind"], f"{command_context}.kind")
        if kind not in {"launch", "build", "exact"}:
            raise URLPolicyError(f"{command_context}.kind is unsupported")
        expected_operation = "activate" if kind == "launch" else "open-url"
        if steps[0].get("operation") != expected_operation:
            raise URLPolicyError(f"{command_context}.action must be a single {expected_operation} step")
        aliases_raw = command["aliases"]
        if not isinstance(aliases_raw, list):
            raise URLPolicyError(f"{command_context}.aliases must be an array")
        checked_aliases: list[str] = []
        for index, alias in enumerate(aliases_raw):
            text = _string(alias, f"{command_context}.aliases[{index}]")
            normalized = _normalize_command(text)
            if not _COMMAND_RE.fullmatch(normalized) or normalized in checked_aliases or normalized == command_name:
                raise URLPolicyError(f"{command_context}.aliases contains an invalid or duplicate command")
            checked_aliases.append(normalized)

        scheme = command["scheme"]
        host = command["host"]
        path = command["path"]
        paths = command["paths"]
        canonical_commands_raw = command["canonical_commands"]
        parameters_raw = command["parameters"]
        constraints_raw = command["constraints"]
        if not all(isinstance(item, list) for item in (paths, canonical_commands_raw, parameters_raw, constraints_raw)):
            raise URLPolicyError(f"{command_context} paths, canonical_commands, parameters, and constraints must be arrays")
        if kind == "launch":
            if any(value is not None for value in (scheme, host, path)) or paths or canonical_commands_raw or parameters_raw or constraints_raw:
                raise URLPolicyError(f"{command_context} launch commands cannot declare URL fields")
            checked_scheme = checked_host = checked_path = None
            checked_paths: list[str] = []
            checked_canonical_commands: list[str] = []
        else:
            checked_scheme = _string(scheme, f"{command_context}.scheme")
            if checked_scheme != checked_scheme.casefold() or not _SCHEME_RE.fullmatch(checked_scheme):
                raise URLPolicyError(f"{command_context}.scheme must be canonical")
            is_http = checked_scheme in {"http", "https"}
            checked_host = _canonical_authority(
                host, f"{command_context}.host", require_multilabel=is_http,
            )
            if kind == "build":
                checked_path = _canonical_path(
                    path, f"{command_context}.path", allow_empty=not is_http,
                )
                if paths or canonical_commands_raw:
                    raise URLPolicyError(f"{command_context}.path must be one exact absolute path")
                checked_paths = []
                checked_canonical_commands = []
            else:
                if path is not None or not paths:
                    raise URLPolicyError(f"{command_context} exact commands require paths and no path")
                checked_path = None
                checked_paths = []
                for index, item in enumerate(paths):
                    item_path = _canonical_path(
                        item, f"{command_context}.paths[{index}]", allow_empty=not is_http,
                    )
                    if item_path in checked_paths:
                        raise URLPolicyError(f"{command_context}.paths contains a duplicate path")
                    checked_paths.append(item_path)
                checked_canonical_commands = []
                for index, item in enumerate(canonical_commands_raw):
                    item_command = _string(item, f"{command_context}.canonical_commands[{index}]")
                    if not _COMMAND_RE.fullmatch(item_command) or item_command in checked_canonical_commands:
                        raise URLPolicyError(f"{command_context}.canonical_commands contains an invalid command")
                    checked_canonical_commands.append(item_command)
                if not checked_canonical_commands:
                    raise URLPolicyError(f"{command_context}.canonical_commands must not be empty")

        parameters = [_validate_parameter(item, f"{command_context}.parameters[{index}]") for index, item in enumerate(parameters_raw)]
        names = [item["name"] for item in parameters]
        queries = [item["query"] for item in parameters]
        if len(names) != len(set(names)) or len(queries) != len(set(queries)):
            raise URLPolicyError(f"{command_context}.parameters contains duplicate names or query keys")
        positional = [item for item in parameters if item["positional"]]
        if any(not item["positional"] for item in parameters[:len(positional)]) or any(
            not earlier["required"] and later["required"] for earlier, later in zip(positional, positional[1:])
        ):
            raise URLPolicyError(f"{command_context} positional parameters must be first with required values before optional values")
        constraints = [
            _validate_constraint(item, set(names), f"{command_context}.constraints[{index}]")
            for index, item in enumerate(constraints_raw)
        ]
        action_template = steps[0].get("value")
        if kind == "build":
            expected_template = f"{checked_scheme}://{checked_host}{checked_path}"
            required_parameters = [item for item in parameters if item["required"]]
            if required_parameters:
                expected_template += "?" + "&".join(
                    f"{item['query']}={{{item['name'].replace('-', '_')}}}"
                    for item in required_parameters
                )
            if action_template != expected_template:
                raise URLPolicyError(
                    f"{command_context}.action template must be exactly {expected_template!r}"
                )
        elif kind == "exact":
            if action_template != "{url}" or len(parameters) != 1 or any((
                parameters[0]["name"] != "url", parameters[0]["query"] != "url",
                parameters[0]["type"] != "text", not parameters[0]["required"],
                not parameters[0]["positional"], parameters[0]["repeatable"],
            )):
                raise URLPolicyError(
                    f"{command_context} exact actions require the canonical {{url}} manifest placeholder contract"
                )
        preliminary[command_name] = {
            "action": action_id, "aliases": checked_aliases, "kind": kind,
            "scheme": checked_scheme, "host": checked_host, "path": checked_path,
            "paths": checked_paths, "canonical_commands": checked_canonical_commands,
            "parameters": parameters, "constraints": constraints,
        }
        action_routes.setdefault(action_id, []).append(command_name)

    for canonical, command in preliminary.items():
        for alias in command["aliases"]:
            if alias in preliminary or alias in aliases:
                raise URLPolicyError(f"{context} has a duplicate normalized command or alias: {alias}")
            aliases[alias] = canonical

    for command_name, command in preliminary.items():
        if command["kind"] != "exact":
            continue
        underlying = []
        for canonical in command["canonical_commands"]:
            candidate = preliminary.get(canonical)
            if candidate is None or candidate["kind"] != "build":
                raise URLPolicyError(
                    f"{context}.commands.{command_name}.canonical_commands must reference build commands"
                )
            if candidate["scheme"] != command["scheme"] or candidate["host"] != command["host"]:
                raise URLPolicyError(
                    f"{context}.commands.{command_name} canonical command authority does not match"
                )
            exact_action = actions[command["action"]]
            canonical_action = actions[candidate["action"]]
            exact_safety = str(exact_action.get("safety"))
            canonical_safety = str(canonical_action.get("safety"))
            exact_retry = str(exact_action.get("retry"))
            canonical_retry = str(canonical_action.get("retry"))
            if (
                exact_safety not in _SAFETY_RANK or canonical_safety not in _SAFETY_RANK
                or _SAFETY_RANK[exact_safety] < _SAFETY_RANK[canonical_safety]
            ):
                raise URLPolicyError(
                    f"{context}.commands.{command_name} may not weaken canonical action safety"
                )
            if (
                exact_retry not in _RETRY_RANK or canonical_retry not in _RETRY_RANK
                or _RETRY_RANK[exact_retry] < _RETRY_RANK[canonical_retry]
            ):
                raise URLPolicyError(
                    f"{context}.commands.{command_name} may not weaken canonical action retry policy"
                )
            underlying.append(candidate["path"])
        if set(underlying) != set(command["paths"]):
            raise URLPolicyError(
                f"{context}.commands.{command_name}.paths must exactly match canonical command paths"
            )

    open_or_activate_actions = {
        action_id for action_id, action in actions.items()
        if any(step.get("operation") in {"open-url", "activate"} for step in action.get("steps", []))
    }
    if set(action_routes) != open_or_activate_actions:
        missing = open_or_activate_actions - set(action_routes)
        extra = set(action_routes) - open_or_activate_actions
        detail = []
        if missing:
            detail.append("missing " + ", ".join(sorted(missing)))
        if extra:
            detail.append("extra " + ", ".join(sorted(extra)))
        raise URLPolicyError(f"{context} must bind every and only launch/open-url action: {'; '.join(detail)}")
    if any(len(commands) != 1 for commands in action_routes.values()):
        raise URLPolicyError(f"{context} must bind each action to exactly one canonical command")

    routes: dict[str, URLRouteSpec] = {}
    normalized_commands: dict[str, Any] = {}
    for command_name, command in preliminary.items():
        action = actions[command["action"]]
        routes[command_name] = URLRouteSpec(
            integration_id, command_name, command["action"], target_bundle, command["kind"],
            command["scheme"], command["host"], command["path"], tuple(command["paths"]),
            tuple(command["canonical_commands"]),
            tuple(_freeze(item) for item in command["parameters"]),
            tuple(_freeze(item) for item in command["constraints"]), max_bytes, digest,
            str(action["safety"]), str(action["retry"]),
        )
        normalized_commands[command_name] = command
    normalized = {
        "$schema": raw["$schema"], "schema": _V2_SCHEMA, "version": 2,
        "integration_id": integration_id, "target_bundle": target_bundle,
        "max_url_bytes": max_bytes, "commands": normalized_commands,
    }
    return URLPolicy(
        _V2_SCHEMA, integration_id, target_bundle, max_bytes,
        MappingProxyType(routes), MappingProxyType(aliases), MappingProxyType({}), digest,
        _freeze(normalized),
    )


def load_url_policy(
    policy_bytes: bytes, *, integration_id: str, bundle_ids: Iterable[str],
    actions: Mapping[str, Mapping[str, Any]], context: str = "url-policy.json",
) -> URLPolicy:
    """Parse one strict v1 or v2 policy from its exact UTF-8 bytes."""
    if not isinstance(policy_bytes, bytes):
        raise TypeError("policy_bytes must be bytes")
    digest = hashlib.sha256(policy_bytes).hexdigest()
    raw = _parse_json_bytes(policy_bytes, context)
    schema = raw.get("schema")
    if schema == _V1_SCHEMA:
        return _validate_v1(raw, integration_id, digest)
    if schema == _V2_SCHEMA:
        return _validate_v2(raw, integration_id, tuple(bundle_ids), actions, digest)
    raise URLPolicyError(f"{context} has an unsupported URL policy schema")


def _number_text(number: float) -> str:
    if number == 0:
        return "0"
    return format(number, ".15g")


def _pair(value: Any, context: str, *, coordinate: bool) -> str:
    if isinstance(value, str):
        _controls(value, context)
        parts: list[Any] = value.split(",")
    elif isinstance(value, (tuple, list)):
        parts = list(value)
    else:
        raise URLPolicyError(f"{context} must be a two-item pair")
    if len(parts) != 2:
        raise URLPolicyError(f"{context} must contain exactly two values")
    try:
        first = float(parts[0]) if not isinstance(parts[0], bool) else math.nan
        second = float(parts[1]) if not isinstance(parts[1], bool) else math.nan
    except (TypeError, ValueError) as error:
        raise URLPolicyError(f"{context} must contain finite numbers") from error
    if not math.isfinite(first) or not math.isfinite(second):
        raise URLPolicyError(f"{context} must contain finite numbers")
    if coordinate:
        if not -90 <= first <= 90 or not -180 <= second <= 180:
            raise URLPolicyError(f"{context} latitude/longitude is out of range")
    elif first <= 0 or second <= 0:
        raise URLPolicyError(f"{context} span deltas must be positive")
    return f"{_number_text(first)},{_number_text(second)}"


def _string_value(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise URLPolicyError(f"{context} must be a non-empty string")
    _controls(value, context)
    return value


def _one_value(parameter: Mapping[str, Any], value: Any, context: str) -> str:
    kind = parameter["type"]
    if kind in {"text", "place-id"}:
        return _string_value(value, context)
    if kind == "coordinate":
        return _pair(value, context, coordinate=True)
    if kind == "span":
        return _pair(value, context, coordinate=False)
    if kind == "finite-number":
        if isinstance(value, str):
            _controls(value, context)
            try:
                number = float(value)
            except ValueError as error:
                raise URLPolicyError(f"{context} must be a finite number") from error
            if not math.isfinite(number):
                raise URLPolicyError(f"{context} must be a finite number")
        else:
            number = _finite(value, context)
        if "minimum" in parameter and number < parameter["minimum"]:
            raise URLPolicyError(f"{context} is below the allowed minimum")
        if "maximum" in parameter and number > parameter["maximum"]:
            raise URLPolicyError(f"{context} exceeds the allowed maximum")
        return _number_text(number)
    if kind == "nonnegative-integer":
        if isinstance(value, str):
            _controls(value, context)
            if not re.fullmatch(r"[0-9]+", value):
                raise URLPolicyError(f"{context} must be a nonnegative integer")
            number = int(value)
            if number < int(parameter.get("minimum", 0)):
                raise URLPolicyError(f"{context} is below the allowed minimum")
        else:
            number = _integer(value, context, minimum=int(parameter.get("minimum", 0)))
        if "maximum" in parameter and number > parameter["maximum"]:
            raise URLPolicyError(f"{context} exceeds the allowed maximum")
        return str(number)
    if kind == "enum":
        text = _string_value(value, context)
        if text not in parameter["values"]:
            raise URLPolicyError(f"{context} must be one of: {', '.join(parameter['values'])}")
        return text
    if kind == "enum-list":
        if isinstance(value, str):
            values = value.split(",")
        elif isinstance(value, (tuple, list)):
            values = list(value)
        else:
            raise URLPolicyError(f"{context} must be a string or ordered list")
        if not values:
            raise URLPolicyError(f"{context} must not be empty")
        checked: list[str] = []
        for item in values:
            text = _string_value(item, context)
            if text not in parameter["values"]:
                raise URLPolicyError(f"{context} contains unsupported value {text!r}")
            if text in checked:
                raise URLPolicyError(f"{context} contains duplicate value {text!r}")
            checked.append(text)
        return ",".join(checked)
    raise URLPolicyError(f"{context} has an unsupported parameter type")


def _bind(route: URLRouteSpec, arguments: Iterable[Any], options: Mapping[str, Any]) -> dict[str, Any]:
    args = tuple(arguments)
    if not isinstance(options, Mapping):
        raise URLPolicyError("options must be a mapping")
    parameters = {parameter["name"]: parameter for parameter in route.parameters}
    positional = [parameter for parameter in route.parameters if parameter["positional"]]
    if len(args) > len(positional):
        raise URLPolicyError(f"{route.command} takes at most {len(positional)} positional arguments")
    values: dict[str, Any] = {}
    for parameter, value in zip(positional, args):
        values[parameter["name"]] = value
    for raw_name, value in options.items():
        if not isinstance(raw_name, str):
            raise URLPolicyError("keyword names must be strings")
        name = raw_name.replace("_", "-")
        if name not in parameters:
            raise URLPolicyError(f"unknown argument {raw_name!r} for {route.command}")
        if name in values:
            raise URLPolicyError(f"argument {raw_name!r} was assigned more than once")
        values[name] = value
    missing = [
        parameter["name"] for parameter in route.parameters
        if parameter["required"] and not _present(values, parameter["name"])
    ]
    if missing:
        raise URLPolicyError(f"{route.command} requires: {', '.join(missing)}")
    return values


def _present(values: Mapping[str, Any], field: str) -> bool:
    return field in values and values[field] is not None


def _apply_constraints(route: URLRouteSpec, values: Mapping[str, Any]) -> None:
    for constraint in route.constraints:
        kind = constraint["kind"]
        fields = tuple(constraint["fields"])
        present = [_present(values, field) for field in fields]
        if kind == "at-least-one" and not any(present):
            raise URLPolicyError(f"{route.command} requires at least one of: {', '.join(fields)}")
        if kind == "exactly-one" and sum(present) != 1:
            raise URLPolicyError(f"{route.command} requires exactly one of: {', '.join(fields)}")
        if kind == "requires" and present[0] and not present[1]:
            raise URLPolicyError(f"{fields[0]} requires {fields[1]}")
        if kind == "forbids-together" and all(present):
            raise URLPolicyError(f"{', '.join(fields)} cannot be combined")
        if kind == "same-length" and present[1]:
            if not present[0]:
                raise URLPolicyError(f"{fields[1]} requires {fields[0]}")
            left = values[fields[0]]
            right = values[fields[1]]
            left_length = len(left) if isinstance(left, (tuple, list)) else 1
            right_length = len(right) if isinstance(right, (tuple, list)) else 1
            if left_length != right_length:
                raise URLPolicyError(f"{fields[0]} and {fields[1]} must have matching lengths")
        if kind == "requires-value" and present[0] and values.get(fields[1]) != constraint["value"]:
            raise URLPolicyError(f"{fields[0]} requires {fields[1]}={constraint['value']}")


def _completed_url(route: URLRouteSpec, pairs: list[tuple[str, str]]) -> str:
    if route.scheme is None or route.host is None or route.path is None:
        raise URLPolicyError("route has no buildable URL")
    query = urlencode(pairs, doseq=False, safe=",", quote_via=quote)
    url = f"{route.scheme}://{route.host}{route.path}"
    if query:
        url += "?" + query
    _validate_url_shape(url, route.scheme, route.host, (route.path,), route.max_url_bytes)
    return url


def _build(route: URLRouteSpec, arguments: Iterable[Any], options: Mapping[str, Any]) -> ValidatedURLRoute:
    values = _bind(route, arguments, options)
    _apply_constraints(route, values)
    pairs: list[tuple[str, str]] = []
    for parameter in route.parameters:
        name = parameter["name"]
        if not _present(values, name):
            continue
        value = values[name]
        if parameter["repeatable"]:
            raw_values = list(value) if isinstance(value, (tuple, list)) else [value]
            if not raw_values:
                raise URLPolicyError(f"{name} must not be empty")
            for index, item in enumerate(raw_values):
                pairs.append((parameter["query"], _one_value(parameter, item, f"{name}[{index}]")))
        else:
            pairs.append((parameter["query"], _one_value(parameter, value, name)))
    url = _completed_url(route, pairs)
    return ValidatedURLRoute(
        route.integration_id, route.command, route.action_id, route.bundle_id, url,
        route.policy_sha256, route.safety, route.retry, f"{route.scheme}://{route.host}{route.path}",
    )


def _validate_url_shape(url: str, scheme: str, host: str, paths: tuple[str, ...], max_bytes: int) -> None:
    if not isinstance(url, str) or not url:
        raise URLPolicyError("URL must be a non-empty string")
    _controls(url, "URL")
    if "\\" in url:
        raise URLPolicyError("URL must not contain backslashes")
    if _BAD_ESCAPE_RE.search(url):
        raise URLPolicyError("URL contains a malformed percent escape")
    if "#" in url:
        raise URLPolicyError("URL fragments are not allowed")
    if len(url.encode("utf-8")) > max_bytes:
        raise URLPolicyError(f"URL exceeds the {max_bytes}-byte UTF-8 encoded limit")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise URLPolicyError(f"URL authority is invalid: {error}") from error
    if parsed.scheme != scheme:
        raise URLPolicyError(f"URL scheme must be exactly {scheme}")
    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        raise URLPolicyError("URL credentials are not allowed")
    if port is not None or parsed.netloc != host or parsed.hostname != host:
        raise URLPolicyError(f"URL host must be exactly {host} with no port")
    if parsed.path not in paths:
        raise URLPolicyError("URL path is not allowed")
    if parsed.fragment:
        raise URLPolicyError("URL fragments are not allowed")


def _literal_query_pairs(query: str) -> list[tuple[str, str]]:
    """Parse an RFC 3986 query without form-urlencoded ``+`` conversion."""
    if not query:
        return []
    result: list[tuple[str, str]] = []
    for index, field in enumerate(query.split("&")):
        if not field or "=" not in field:
            raise URLPolicyError(f"URL query field {index} must contain a name and value")
        raw_key, raw_value = field.split("=", 1)
        try:
            key = unquote_to_bytes(raw_key).decode("utf-8", "strict")
            value = unquote_to_bytes(raw_value).decode("utf-8", "strict")
        except (UnicodeError, ValueError) as error:
            raise URLPolicyError("URL query is not valid UTF-8 percent encoding") from error
        _controls(key, "URL query name")
        _controls(value, f"URL query value {key!r}")
        result.append((key, value))
    return result


def _values_from_pairs(route: URLRouteSpec, pairs: list[tuple[str, str]]) -> dict[str, Any]:
    by_query = {parameter["query"]: parameter for parameter in route.parameters}
    values: dict[str, Any] = {}
    counts: dict[str, int] = {}
    for key, value in pairs:
        parameter = by_query.get(key)
        if parameter is None:
            raise URLPolicyError(f"unknown query parameter {key!r} for {route.path}")
        counts[key] = counts.get(key, 0) + 1
        if counts[key] > 1 and not parameter["repeatable"]:
            raise URLPolicyError(f"duplicate singleton query parameter {key!r}")
        name = parameter["name"]
        if parameter["repeatable"]:
            values.setdefault(name, []).append(value)
        else:
            values[name] = value
    return values


def _exact(route: URLRouteSpec, arguments: Iterable[Any], options: Mapping[str, Any], policy: URLPolicy) -> ValidatedURLRoute:
    values = _bind(route, arguments, options)
    raw_url = _string_value(values["url"], "url")
    if route.scheme is None or route.host is None:
        raise URLPolicyError("exact route has no URL authority")
    _validate_url_shape(raw_url, route.scheme, route.host, route.paths, route.max_url_bytes)
    parsed = urlsplit(raw_url)
    pairs = _literal_query_pairs(parsed.query)

    matches: list[ValidatedURLRoute] = []
    for command in route.canonical_commands:
        candidate = policy.routes[command]
        if candidate.path != parsed.path:
            continue
        try:
            rebuilt = _build(candidate, (), _values_from_pairs(candidate, pairs))
        except URLPolicyError:
            continue
        matches.append(rebuilt)
    if len(matches) != 1:
        raise URLPolicyError("URL does not resolve to one safe canonical build route")
    validated = matches[0]
    return ValidatedURLRoute(
        route.integration_id, route.command, route.action_id, route.bundle_id,
        validated.url, route.policy_sha256, route.safety, route.retry, validated.url_shape,
    )


def resolve_url_route(
    policy: URLPolicy, command: str, arguments: Iterable[Any] = (),
    options: Mapping[str, Any] | None = None,
) -> ValidatedURLRoute:
    """Resolve and validate one v2 URL command from raw values."""
    if policy.schema != _V2_SCHEMA:
        raise URLPolicyError("v1 policies do not declare production commands")
    route = policy.resolve(command)
    if route.kind == "launch":
        raise URLPolicyError(f"{route.command} is a launch command, not a URL route")
    supplied = {} if options is None else options
    if route.kind == "build":
        return _build(route, arguments, supplied)
    return _exact(route, arguments, supplied, policy)


def revalidate_validated_route(policy: URLPolicy, route: ValidatedURLRoute) -> None:
    """Fail closed if a route object was forged or changed after validation."""
    if not isinstance(route, ValidatedURLRoute):
        raise URLPolicyError("CoreDevice URL dispatch requires a ValidatedURLRoute")
    if policy.schema != _V2_SCHEMA:
        raise URLPolicyError("validated routes require a v2 policy")
    spec = policy.resolve(route.command)
    expected_identity = (
        spec.integration_id, spec.command, spec.action_id, spec.bundle_id,
        spec.policy_sha256, spec.safety, spec.retry,
    )
    actual_identity = (
        route.integration_id, route.command, route.action_id, route.bundle_id,
        route.policy_sha256, route.safety, route.retry,
    )
    if actual_identity != expected_identity or spec.kind not in {"build", "exact"}:
        raise URLPolicyError("validated route identity does not match its policy")
    if spec.kind == "exact":
        rebuilt = _exact(spec, (route.url,), {}, policy)
    else:
        _validate_url_shape(route.url, spec.scheme or "", spec.host or "", (spec.path or "",), spec.max_url_bytes)
        parsed = urlsplit(route.url)
        pairs = _literal_query_pairs(parsed.query)
        rebuilt = _build(spec, (), _values_from_pairs(spec, pairs))
    if rebuilt != route:
        raise URLPolicyError("validated route is not in canonical policy form")


def validate_v1_url(policy: URLPolicy, action_id: str, url: str) -> str:
    """Keep v1 scheme policies usable while applying strict generic URL checks."""
    if policy.schema != _V1_SCHEMA:
        raise URLPolicyError("policy is not v1")
    schemes = policy.actions.get(action_id)
    if schemes is None:
        raise URLPolicyError(f"action {action_id!r} is not covered by the v1 URL policy")
    text = _string_value(url, "url")
    if len(text.encode("utf-8")) > policy.max_url_bytes:
        raise URLPolicyError(f"URL exceeds the {policy.max_url_bytes}-byte UTF-8 encoded limit")
    if _BAD_ESCAPE_RE.search(text) or "\\" in text:
        raise URLPolicyError("URL contains malformed escaping or backslashes")
    try:
        parsed = urlsplit(text)
        port = parsed.port
    except ValueError as error:
        raise URLPolicyError(f"URL is invalid: {error}") from error
    if parsed.scheme not in schemes or not parsed.netloc:
        raise URLPolicyError(f"URL scheme must be one of: {', '.join(schemes)}")
    if parsed.username is not None or parsed.password is not None:
        raise URLPolicyError("URL credentials are not allowed")
    # V1 intentionally remains scheme-only for Safari and Brave. Web URLs may
    # use application ports and fragments; richer endpoint policy belongs in v2.
    return text


__all__ = [
    "MAX_URL_BYTES", "URLPolicy", "URLPolicyError", "URLRouteSpec",
    "ValidatedURLRoute", "load_url_policy", "resolve_url_route",
    "revalidate_validated_route", "validate_v1_url",
]
