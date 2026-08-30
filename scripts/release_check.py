#!/usr/bin/env python3
"""Fail closed when a repository release contains private or unsafe material.

This script uses only the Python standard library and inspects the Git release
candidate (tracked files plus non-ignored untracked files). Ignored local state
is deliberately not treated as release content.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tomllib
from typing import Any, Iterable


DOCUMENTED_READINESS_EXITS = frozenset({0, 10, 20, 30, 40})
RUNTIME_DIRECTORIES = frozenset({
    ".runtime", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".tox", ".venv", ".eggs", "node_modules", "DerivedData", "appium-home",
    "xcuserdata", "build", "dist", "htmlcov", "logs",
})
FORBIDDEN_SUFFIXES = (
    ".pyc", ".pyo", ".xctestrun", ".log", ".trace", ".mobileprovision",
    ".ipa", ".pem", ".key", ".p12", ".cer", ".tmp",
)
FORBIDDEN_FILE_NAMES = frozenset({
    ".env", ".coverage", "config.toml", "config.json", "config.yaml",
    "config.yml", "token", "token.txt", "token.json", "credentials",
    "credentials.json", "secrets.json", "server.json", "server.tmp",
})
FORBIDDEN_DIRECTORY_SUFFIXES = (".xcarchive", ".dsym", ".xcresult", ".app")
TEXT_SUFFIXES = frozenset({
    "", ".cfg", ".css", ".html", ".ini", ".js", ".json", ".md",
    ".py", ".rst", ".sh", ".toml", ".txt", ".yaml", ".yml",
})
GENERIC_USERNAMES = frozenset({
    "example", "name", "runner", "user", "username", "yourname",
    "your-name", "your_username",
})
KNOWN_SECRET_PATTERNS = (
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("private key", re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
)
ASSIGNED_SECRET = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|"
    r"password|passwd|secret)\b[\"']?\s*(?:=|:)\s*(?:"
    r"\"([A-Za-z0-9_./+=:-]{16,})\"|'([A-Za-z0-9_./+=:-]{16,})'|"
    r"([A-Za-z0-9_./+=:-]{16,})(?=\s*(?:[#;,}\]]|\r?$)))",
    re.MULTILINE,
)
PRIVATE_PATH = re.compile(
    r"(?P<path>(?:/Users/|/home/)(?P<unix>[A-Za-z0-9._-]+)(?:/[^\s\"'`<>]*)?"
    r"|[A-Za-z]:\\Users\\(?P<windows>[A-Za-z0-9._-]+)(?:\\[^\s\"'`<>]*)?)"
)
TEAM_ID = re.compile(
    r"(?i)\b(?:team[_ -]?id|development_team)\b[\"']?\s*(?:=|:)\s*[\"']?([A-Z0-9]{10})\b"
)
MODERN_DEVICE_ID = re.compile(r"\b[0-9A-Fa-f]{8}-[0-9A-Fa-f]{16}\b")
CONTEXT_DEVICE_ID = re.compile(
    r"(?i)\b(?:device[_ -]?id|udid|coredevice[_ -]?identifier)\b[\"']?\s*"
    r"(?:=|:)\s*[\"']?([0-9A-Fa-f-]{24,40})\b"
)
ASSIGNED_USERNAME = re.compile(
    r"(?i)\b(?:local[_ -]?user|user[_ -]?name|username)\b[\"']?\s*(?:=|:)\s*"
    r"[\"']([A-Za-z0-9._-]{2,})[\"']"
)
PLACEHOLDER_WORDS = ("example", "placeholder", "redacted", "changeme", "dummy", "sample")
SCHEMA_KEYWORDS = frozenset({
    "$schema", "$id", "$ref", "$defs", "title", "description", "type",
    "required", "properties", "additionalProperties", "propertyNames",
    "items", "minItems", "maxItems", "uniqueItems", "minLength",
    "maxLength", "pattern", "minimum", "maximum", "enum", "const",
    "allOf", "if", "then", "else", "default", "examples", "format",
})


class CheckFailure(ValueError):
    """A release or schema invariant was violated."""


def _git(root: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as error:
        raise CheckFailure(f"git is required: {error}") from error
    if check and result.returncode:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise CheckFailure(f"git {' '.join(arguments)} failed: {detail}")
    return result


def release_paths(root: Path) -> list[Path]:
    """Return tracked and non-ignored untracked release candidates."""
    root = root.resolve()
    probe = _git(root, "rev-parse", "--show-toplevel")
    top = Path(probe.stdout.decode().strip()).resolve()
    if top != root:
        raise CheckFailure(f"root must be the Git worktree root: {top}")
    output = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").stdout
    relative_names = sorted({item for item in output.decode("utf-8", "surrogateescape").split("\0") if item})
    return [root / PurePosixPath(name) for name in relative_names]


def index_modes(root: Path) -> dict[str, int]:
    """Return Git index modes so staged release permissions cannot be hidden by chmod."""
    output = _git(root, "ls-files", "--stage", "-z").stdout
    result: dict[str, int] = {}
    for record in output.decode("utf-8", "surrogateescape").split("\0"):
        if not record:
            continue
        metadata, separator, relative = record.partition("\t")
        fields = metadata.split()
        if not separator or len(fields) != 3:
            raise CheckFailure("git returned an invalid index record")
        result[relative] = int(fields[0], 8)
    return result


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _forbidden_path_reason(relative: str) -> str | None:
    path = PurePosixPath(relative)
    parts = path.parts
    lowered = tuple(part.casefold() for part in parts)
    runtime = {item.casefold() for item in RUNTIME_DIRECTORIES}
    for part in lowered[:-1]:
        if part in runtime:
            return f"runtime/generated directory {part!r}"
        if part.endswith(tuple(item.casefold() for item in FORBIDDEN_DIRECTORY_SUFFIXES)):
            return f"generated Xcode directory {part!r}"
    name = lowered[-1] if lowered else ""
    if name in {item.casefold() for item in FORBIDDEN_FILE_NAMES}:
        return f"local token/config file {parts[-1]!r}"
    if name.startswith(".env."):
        return "local environment file"
    if name.endswith(tuple(item.casefold() for item in FORBIDDEN_SUFFIXES)):
        return f"generated/private artifact {parts[-1]!r}"
    if any("webdriveragent" in part for part in lowered[:-1]):
        return "WebDriverAgent build directory"
    if "webdriveragent" in name and path.suffix.casefold() not in {".md", ".rst", ".txt"}:
        return "WebDriverAgent build artifact"
    return None


def _is_ignored(root: Path, path: Path) -> bool:
    relative = _relative(path, root)
    return _git(root, "check-ignore", "-q", "--no-index", "--", relative, check=False).returncode == 0


def _special_files(root: Path, candidates: set[Path]) -> list[str]:
    """Find unignored links, sockets, and devices that Git cannot represent."""
    issues: list[str] = []
    candidate_names = {_relative(path, root) for path in candidates}
    for directory, names, files in os.walk(root, topdown=True, followlinks=False):
        here = Path(directory)
        retained: list[str] = []
        for name in names:
            path = here / name
            relative = _relative(path, root)
            if here == root and name == ".git":
                continue
            contains_candidate = any(
                item == relative or item.startswith(relative.rstrip("/") + "/")
                for item in candidate_names
            )
            if not contains_candidate and _is_ignored(root, path):
                continue
            retained.append(name)
        names[:] = retained
        for name in names + files:
            path = here / name
            try:
                mode = path.lstat().st_mode
            except OSError as error:
                issues.append(f"{_relative(path, root)}: cannot inspect: {error}")
                continue
            if stat.S_ISDIR(mode) or stat.S_ISREG(mode):
                continue
            if path not in candidates and _is_ignored(root, path):
                continue
            kind = "symlink" if stat.S_ISLNK(mode) else (
                "socket" if stat.S_ISSOCK(mode) else "special file"
            )
            issues.append(f"{_relative(path, root)}: {kind} is not release-safe")
    return issues


def _looks_placeholder(value: str) -> bool:
    lowered = value.casefold()
    if any(word in lowered for word in PLACEHOLDER_WORDS):
        return True
    compact = re.sub(r"[^A-Za-z0-9]", "", value).casefold()
    if not compact:
        return False
    sequences = (
        "abcdefghijklmnopqrstuvwxyz" * 2,
        "zyxwvutsrqponmlkjihgfedcba" * 2,
        "0123456789" * 3,
        "9876543210" * 3,
    )
    return len(set(compact)) <= 2 or any(compact in sequence for sequence in sequences)


def content_issues(path: Path, relative: str) -> list[str]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        return [f"{relative}: cannot read: {error}"]
    if b"\0" in raw:
        return []
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        if path.suffix.casefold() in TEXT_SUFFIXES:
            return [f"{relative}: text-like file is not UTF-8"]
        return []

    issues: list[str] = []
    for match in PRIVATE_PATH.finditer(text):
        username = match.group("unix") or match.group("windows") or ""
        if username.casefold() not in GENERIC_USERNAMES and not _looks_placeholder(username):
            issues.append(f"{relative}: private home path {match.group('path')!r}")
    for match in ASSIGNED_USERNAME.finditer(text):
        candidate_user = match.group(1).casefold()
        if candidate_user not in GENERIC_USERNAMES and not _looks_placeholder(candidate_user):
            issues.append(f"{relative}: contains an assigned local username")

    for label, pattern in KNOWN_SECRET_PATTERNS:
        if pattern.search(text):
            issues.append(f"{relative}: contains a {label}")
    for match in ASSIGNED_SECRET.finditer(text):
        value = next(group for group in match.groups() if group is not None)
        if not _looks_placeholder(value):
            issues.append(f"{relative}: contains an assigned secret-like value")

    for match in TEAM_ID.finditer(text):
        value = match.group(1)
        if value != "ABCDE12345" and not _looks_placeholder(value):
            issues.append(f"{relative}: contains an Apple team ID")
    for match in MODERN_DEVICE_ID.finditer(text):
        if not _looks_placeholder(match.group(0)):
            issues.append(f"{relative}: contains a device identifier")
    for match in CONTEXT_DEVICE_ID.finditer(text):
        if not _looks_placeholder(match.group(1)):
            issues.append(f"{relative}: contains a configured device identifier")
    return sorted(set(issues))


def _strict_json(path: Path) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise CheckFailure(f"{path}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    def constant(value: str) -> None:
        raise CheckFailure(f"{path}: non-finite JSON number {value}")

    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle, object_pairs_hook=pairs, parse_constant=constant)
    except CheckFailure:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CheckFailure(f"{path}: invalid JSON: {error}") from error


def _json_equal(left: Any, right: Any) -> bool:
    """Compare JSON values without Python's bool/int equality shortcut."""
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return not isinstance(left, bool) and not isinstance(right, bool) and left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, list):
        return len(left) == len(right) and all(_json_equal(a, b) for a, b in zip(left, right))
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_json_equal(left[key], right[key]) for key in left)
    return left == right


def _json_type(value: Any, wanted: str) -> bool:
    return {
        "null": value is None,
        "boolean": isinstance(value, bool),
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value),
    }.get(wanted, False)


def _resolve_ref(schema_root: dict[str, Any], reference: str) -> dict[str, Any]:
    if not reference.startswith("#/"):
        raise CheckFailure(f"unsupported non-local schema reference {reference!r}")
    value: Any = schema_root
    for token in reference[2:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or token not in value:
            raise CheckFailure(f"unresolved schema reference {reference!r}")
        value = value[token]
    if not isinstance(value, dict):
        raise CheckFailure(f"schema reference {reference!r} does not select an object")
    return value


def validate_schema(instance: Any, schema: dict[str, Any], *, name: str = "document", root: dict[str, Any] | None = None) -> None:
    """Validate the JSON Schema subset used by this repository."""
    schema_root = schema if root is None else root
    unknown = set(schema) - SCHEMA_KEYWORDS
    if unknown:
        raise CheckFailure(f"{name}: unsupported schema keyword(s): {', '.join(sorted(unknown))}")
    if "$ref" in schema:
        validate_schema(instance, _resolve_ref(schema_root, schema["$ref"]), name=name, root=schema_root)
    for index, child in enumerate(schema.get("allOf", [])):
        validate_schema(instance, child, name=f"{name}.allOf[{index}]", root=schema_root)
    if "if" in schema:
        try:
            validate_schema(instance, schema["if"], name=name, root=schema_root)
        except CheckFailure:
            branch = schema.get("else")
        else:
            branch = schema.get("then")
        if branch is not None:
            validate_schema(instance, branch, name=name, root=schema_root)

    wanted = schema.get("type")
    if wanted is not None:
        choices = [wanted] if isinstance(wanted, str) else wanted
        if not isinstance(choices, list) or not choices or not all(isinstance(item, str) for item in choices):
            raise CheckFailure(f"{name}: schema has invalid type declaration")
        if not any(_json_type(instance, item) for item in choices):
            raise CheckFailure(f"{name}: expected type {' or '.join(choices)}")
    if "const" in schema and not _json_equal(instance, schema["const"]):
        raise CheckFailure(f"{name}: must equal {schema['const']!r}")
    if "enum" in schema and not any(_json_equal(instance, choice) for choice in schema["enum"]):
        raise CheckFailure(f"{name}: value is not in the allowed enum")

    if isinstance(instance, dict):
        required = schema.get("required", [])
        missing = [key for key in required if key not in instance]
        if missing:
            raise CheckFailure(f"{name}: missing required field(s): {', '.join(missing)}")
        properties = schema.get("properties", {})
        for key, child in properties.items():
            if key in instance:
                validate_schema(instance[key], child, name=f"{name}.{key}", root=schema_root)
        extra = set(instance) - set(properties)
        additional = schema.get("additionalProperties", True)
        if additional is False and extra:
            raise CheckFailure(f"{name}: unknown field(s): {', '.join(sorted(extra))}")
        if isinstance(additional, dict):
            for key in extra:
                validate_schema(instance[key], additional, name=f"{name}.{key}", root=schema_root)
        if "propertyNames" in schema:
            for key in instance:
                validate_schema(key, schema["propertyNames"], name=f"{name} property {key!r}", root=schema_root)

    if isinstance(instance, list):
        if len(instance) < schema.get("minItems", 0):
            raise CheckFailure(f"{name}: has too few items")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            raise CheckFailure(f"{name}: has too many items")
        if schema.get("uniqueItems"):
            encoded = [json.dumps(item, sort_keys=True, separators=(",", ":")) for item in instance]
            if len(encoded) != len(set(encoded)):
                raise CheckFailure(f"{name}: items must be unique")
        if isinstance(schema.get("items"), dict):
            for index, item in enumerate(instance):
                validate_schema(item, schema["items"], name=f"{name}[{index}]", root=schema_root)

    if isinstance(instance, str):
        if len(instance) < schema.get("minLength", 0):
            raise CheckFailure(f"{name}: string is too short")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            raise CheckFailure(f"{name}: string is too long")
        if "pattern" in schema and re.search(schema["pattern"], instance) is None:
            raise CheckFailure(f"{name}: does not match required pattern")
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            raise CheckFailure(f"{name}: is below minimum")
        if "maximum" in schema and instance > schema["maximum"]:
            raise CheckFailure(f"{name}: is above maximum")


def _validate_schema_document(schema: Any, path: Path) -> dict[str, Any]:
    if not isinstance(schema, dict):
        raise CheckFailure(f"{path}: schema must be a JSON object")
    if not isinstance(schema.get("$schema"), str):
        raise CheckFailure(f"{path}: schema must declare $schema")

    def walk(value: Any, context: str, root: dict[str, Any]) -> None:
        if not isinstance(value, dict):
            raise CheckFailure(f"{context}: schema node must be an object")
        unknown = set(value) - SCHEMA_KEYWORDS
        if unknown:
            raise CheckFailure(f"{context}: unsupported schema keyword(s): {', '.join(sorted(unknown))}")
        if "$ref" in value:
            if not isinstance(value["$ref"], str):
                raise CheckFailure(f"{context}: $ref must be a string")
            _resolve_ref(root, value["$ref"])
        if "type" in value:
            choices = [value["type"]] if isinstance(value["type"], str) else value["type"]
            valid = {"null", "boolean", "object", "array", "string", "integer", "number"}
            if (
                not isinstance(choices, list) or not choices
                or not all(isinstance(item, str) for item in choices)
                or not set(choices) <= valid or len(set(choices)) != len(choices)
            ):
                raise CheckFailure(f"{context}: invalid JSON Schema type")
        if "required" in value and (
            not isinstance(value["required"], list)
            or not all(isinstance(item, str) for item in value["required"])
            or len(value["required"]) != len(set(value["required"]))
        ):
            raise CheckFailure(f"{context}: required must contain unique strings")
        if "enum" in value and (not isinstance(value["enum"], list) or not value["enum"]):
            raise CheckFailure(f"{context}: enum must be a non-empty array")
        for key in ("properties", "$defs"):
            mapping = value.get(key, {})
            if not isinstance(mapping, dict):
                raise CheckFailure(f"{context}.{key}: must be an object")
            for name, child in mapping.items():
                if not isinstance(name, str):
                    raise CheckFailure(f"{context}.{key}: property names must be strings")
                walk(child, f"{context}.{key}.{name}", root)
        for key in ("items", "propertyNames", "if", "then", "else"):
            if key in value:
                walk(value[key], f"{context}.{key}", root)
        if "additionalProperties" in value:
            additional = value["additionalProperties"]
            if not isinstance(additional, bool):
                walk(additional, f"{context}.additionalProperties", root)
        if "allOf" in value:
            if not isinstance(value["allOf"], list) or not value["allOf"]:
                raise CheckFailure(f"{context}.allOf: must be a non-empty array")
            for index, child in enumerate(value["allOf"]):
                walk(child, f"{context}.allOf[{index}]", root)
        if "pattern" in value:
            if not isinstance(value["pattern"], str):
                raise CheckFailure(f"{context}.pattern: must be a string")
            try:
                re.compile(value["pattern"])
            except re.error as error:
                raise CheckFailure(f"{context}.pattern: invalid regular expression: {error}") from error
        for key in ("minItems", "maxItems", "minLength", "maxLength"):
            if key in value and (not isinstance(value[key], int) or isinstance(value[key], bool) or value[key] < 0):
                raise CheckFailure(f"{context}.{key}: must be a non-negative integer")
        for key in ("minimum", "maximum"):
            number = value.get(key)
            if key in value and (
                not isinstance(number, (int, float)) or isinstance(number, bool) or not math.isfinite(number)
            ):
                raise CheckFailure(f"{context}.{key}: must be a finite number")
        for key in ("uniqueItems",):
            if key in value and not isinstance(value[key], bool):
                raise CheckFailure(f"{context}.{key}: must be a boolean")

    walk(schema, str(path), schema)
    return schema


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    import hashlib
    return hashlib.sha256(encoded).hexdigest()


def _manifest_claim_digest(root: Path, manifest_relative: str) -> str:
    manifest = _strict_json(root / manifest_relative)
    policy_path = (root / manifest_relative).with_name("url-policy.json")
    policy_actions: dict[str, Any] = {}
    if policy_path.is_file():
        policy = _strict_json(policy_path)
        if isinstance(policy, dict) and isinstance(policy.get("actions"), dict):
            policy_actions = policy["actions"]
    return _canonical_digest({"integration": manifest, "url_policy": policy_actions})


def validate_manifests(root: Path, candidate_relatives: set[str]) -> list[str]:
    issues: list[str] = []
    try:
        index_path = root / "integrations/index.json"
        if "integrations/index.json" not in candidate_relatives:
            raise CheckFailure("integrations/index.json is not in the release candidate")
        required_release_files = {
            "schemas/integrations-index-v1.json", "schemas/integration-v1.json",
        }
        missing_release_files = required_release_files - candidate_relatives
        if missing_release_files:
            raise CheckFailure(
                "release is missing manifest schema file(s): "
                + ", ".join(sorted(missing_release_files))
            )
        index = _strict_json(index_path)
        index_schema = _strict_json(root / "schemas/integrations-index-v1.json")
        manifest_schema = _strict_json(root / "schemas/integration-v1.json")
        _validate_schema_document(index_schema, root / "schemas/integrations-index-v1.json")
        _validate_schema_document(manifest_schema, root / "schemas/integration-v1.json")
        validate_schema(index, index_schema, name="integrations/index.json")
        if not isinstance(index, dict):
            raise CheckFailure("integrations/index.json must be an object")

        indexed: set[str] = set()
        ids: set[str] = set()
        for position, entry in enumerate(index["integrations"]):
            manifest_relative = (PurePosixPath("integrations") / entry["manifest"]).as_posix()
            normalized = PurePosixPath(manifest_relative)
            if normalized.is_absolute() or ".." in normalized.parts:
                # The sole allowed parent hop is normalized into addons below.
                if not manifest_relative.startswith("integrations/../addons/"):
                    raise CheckFailure(f"index entry {position} escapes manifest roots")
                manifest_relative = PurePosixPath(*normalized.parts[2:]).as_posix()
            expected_prefix = "integrations/" if entry["kind"] == "core" else "addons/"
            if not manifest_relative.startswith(expected_prefix):
                raise CheckFailure(f"index entry {position} has a kind/path mismatch")
            if manifest_relative in indexed:
                raise CheckFailure(f"duplicate indexed manifest {manifest_relative}")
            if entry["id"] in ids:
                raise CheckFailure(f"duplicate indexed integration ID {entry['id']}")
            indexed.add(manifest_relative)
            ids.add(entry["id"])
            if manifest_relative not in candidate_relatives:
                raise CheckFailure(f"indexed manifest is missing from release: {manifest_relative}")
            manifest = _strict_json(root / manifest_relative)
            validate_schema(manifest, manifest_schema, name=manifest_relative)
            if manifest.get("id") != entry["id"] or manifest.get("kind") != entry["kind"]:
                raise CheckFailure(f"{manifest_relative}: id/kind does not match integrations/index.json")
            if PurePosixPath(manifest_relative).parent.name != entry["id"]:
                raise CheckFailure(f"{manifest_relative}: directory must match integration ID")

            open_url_actions = {
                action_id for action_id, action in manifest["actions"].items()
                if any(step.get("operation") == "open-url" for step in action["steps"])
            }
            policy_relative = str(PurePosixPath(manifest_relative).with_name("url-policy.json"))
            if open_url_actions:
                if policy_relative not in candidate_relatives:
                    raise CheckFailure(f"{manifest_relative}: open-url actions require url-policy.json")
                policy = _strict_json(root / policy_relative)
                if not isinstance(policy, dict) or set(policy) != {
                    "$schema", "schema", "version", "integration_id", "actions"
                }:
                    raise CheckFailure(f"{policy_relative}: URL policy fields are invalid")
                if (
                    policy.get("$schema") != "../../schemas/url-policy-v1.json"
                    or policy.get("schema") != "ipad-agent.url-policy/v1"
                    or policy.get("version") != 1
                    or isinstance(policy.get("version"), bool)
                    or policy.get("integration_id") != entry["id"]
                    or not isinstance(policy.get("actions"), dict)
                    or set(policy["actions"]) != open_url_actions
                ):
                    raise CheckFailure(f"{policy_relative}: URL policy is not bound to every open-url action")
                for action_id, schemes in policy["actions"].items():
                    if (
                        not isinstance(schemes, list) or not schemes
                        or schemes != sorted(set(schemes))
                        or not all(
                            isinstance(scheme, str)
                            and re.fullmatch(r"[a-z][a-z0-9+.-]*", scheme)
                            for scheme in schemes
                        )
                    ):
                        raise CheckFailure(f"{policy_relative}: {action_id} schemes are not strict")
            elif policy_relative in candidate_relatives:
                raise CheckFailure(f"{policy_relative}: URL policy exists without an open-url action")

        discovered = {
            relative for relative in candidate_relatives
            if (relative.startswith("integrations/") or relative.startswith("addons/"))
            and relative.endswith("/integration.json")
        }
        missing = discovered - indexed
        stale = indexed - discovered
        if missing:
            raise CheckFailure("unindexed integration manifest(s): " + ", ".join(sorted(missing)))
        if stale:
            raise CheckFailure("missing indexed integration manifest(s): " + ", ".join(sorted(stale)))
    except CheckFailure as error:
        issues.append(str(error))
    return issues


def validate_documents(root: Path, paths: Iterable[Path]) -> list[str]:
    issues: list[str] = []
    for path in paths:
        relative = _relative(path, root)
        try:
            if path.suffix.casefold() == ".json":
                value = _strict_json(path)
                if relative.startswith("schemas/"):
                    _validate_schema_document(value, path)
                elif isinstance(value, dict) and isinstance(value.get("$schema"), str):
                    reference = value["$schema"]
                    if reference.endswith(".json") and not reference.startswith(("http://", "https://")):
                        schema_path = (path.parent / reference).resolve()
                        try:
                            schema_path.relative_to(root)
                        except ValueError as error:
                            raise CheckFailure(f"{relative}: $schema escapes the repository") from error
                        schema_relative = _relative(schema_path, root)
                        if not schema_path.is_file() or schema_relative not in {
                            _relative(item, root) for item in paths
                        }:
                            raise CheckFailure(
                                f"{relative}: referenced schema is not in the release: {schema_relative}"
                            )
                        schema = _strict_json(schema_path)
                        _validate_schema_document(schema, schema_path)
                        validate_schema(value, schema, name=relative)
            elif path.suffix.casefold() == ".toml":
                with path.open("rb") as handle:
                    value = tomllib.load(handle)
                if not isinstance(value, dict):
                    raise CheckFailure(f"{relative}: TOML root must be a table")
        except (CheckFailure, OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
            issues.append(str(error))
    return issues


def validate_public_lab_claims(root: Path, candidate_relatives: set[str]) -> list[str]:
    """Bind public claims to current manifests and release-available evidence.

    Raw evidence is private and forbidden from a release candidate. Therefore a
    public release cannot honestly carry physical/cleanup claims until a
    separately designed verifiable redacted evidence format exists.
    """
    issues: list[str] = []
    try:
        required = {
            "compatibility-v1.json", "lab-report-v1.json",
            "schemas/compatibility-v1.json", "schemas/lab-report-v1.json",
        }
        missing = required - candidate_relatives
        if missing:
            raise CheckFailure("release is missing public lab claim file(s): " + ", ".join(sorted(missing)))
        compatibility = _strict_json(root / "compatibility-v1.json")
        report = _strict_json(root / "lab-report-v1.json")
        if not isinstance(compatibility, dict) or not isinstance(report, dict):
            raise CheckFailure("public lab claims must be JSON objects")
        if (
            compatibility.get("schema") != "ipad-agent.compatibility/v1"
            or compatibility.get("version") != 1 or isinstance(compatibility.get("version"), bool)
            or report.get("schema") != "ipad-agent.lab-report/v1"
            or report.get("version") != 1 or isinstance(report.get("version"), bool)
        ):
            raise CheckFailure("public lab claim schema identity is invalid")
        for label, timestamp in (
            ("compatibility.generated_at", compatibility.get("generated_at")),
            ("lab-report.generated_at", report.get("generated_at")),
        ):
            try:
                parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except (AttributeError, ValueError) as error:
                raise CheckFailure(f"{label} must be an ISO-8601 timestamp") from error
            if parsed.utcoffset() is None:
                raise CheckFailure(f"{label} must include a UTC offset")

        # There is no release-safe evidence object in v1. Any non-empty public
        # source or integration claim is therefore unsupported, even if its JSON
        # shape looks convincing.
        if compatibility.get("source_evidence") != [] or compatibility.get("integrations") != []:
            raise CheckFailure(
                "compatibility-v1.json must remain empty/unverified without release-verifiable evidence"
            )
        binding = report.get("binding")
        if not isinstance(binding, dict) or binding.get("integration_id") != report.get("integration_id"):
            raise CheckFailure("lab-report-v1.json binding identity is inconsistent")
        if binding.get("compatibility_sha256") != _canonical_digest(compatibility):
            raise CheckFailure("lab-report-v1.json is not bound to the current compatibility document")
        evidence_digests = binding.get("evidence_sha256")
        if not isinstance(evidence_digests, list) or evidence_digests != sorted(set(evidence_digests)):
            raise CheckFailure("lab-report-v1.json evidence digests must be unique and sorted")
        if evidence_digests:
            raise CheckFailure("lab-report-v1.json references evidence unavailable in the release")
        checks = report.get("checks")
        if not isinstance(checks, list) or not checks:
            raise CheckFailure("lab-report-v1.json requires completion checks")
        expected_complete = all(isinstance(item, dict) and item.get("passed") is True for item in checks)
        if report.get("complete") is not expected_complete:
            raise CheckFailure("lab-report-v1.json complete does not equal all completion gates")
        if report.get("complete") is True:
            raise CheckFailure("a complete lab report cannot be released without verifiable bound evidence")
        unsupported_passes = {
            item.get("id") for item in checks if isinstance(item, dict) and item.get("passed") is True
            and any(
                word in (str(item.get("id", "")) + " " + str(item.get("detail", ""))).casefold()
                for word in ("physical", "cleanup", "benchmark")
            )
        }
        if unsupported_passes:
            raise CheckFailure(
                "lab-report-v1.json contains unsupported physical/cleanup passes: "
                + ", ".join(sorted(str(item) for item in unsupported_passes))
            )

        manifest_digest = binding.get("manifest_digest")
        integration_id = report.get("integration_id")
        if manifest_digest is not None:
            index = _strict_json(root / "integrations/index.json")
            entries = [item for item in index.get("integrations", []) if item.get("id") == integration_id]
            if len(entries) != 1:
                raise CheckFailure("lab-report-v1.json integration is not current in integrations/index.json")
            entry = entries[0]
            relative = (PurePosixPath("integrations") / entry["manifest"]).as_posix()
            normalized = PurePosixPath(relative)
            if ".." in normalized.parts:
                relative = PurePosixPath(*normalized.parts[2:]).as_posix()
            if manifest_digest != _manifest_claim_digest(root, relative):
                raise CheckFailure("lab-report-v1.json manifest digest is stale or fabricated")
    except (CheckFailure, KeyError, TypeError, ValueError) as error:
        issues.append(str(error))
    return issues


def check_release(root: Path) -> list[str]:
    root = root.resolve()
    paths = release_paths(root)
    modes = index_modes(root)
    candidates = set(paths)
    issues = _special_files(root, candidates)
    relatives: set[str] = set()
    for path in paths:
        relative = _relative(path, root)
        relatives.add(relative)
        try:
            info = path.lstat()
        except OSError as error:
            issues.append(f"{relative}: cannot inspect: {error}")
            continue
        index_mode = modes.get(relative)
        if index_mode is not None and stat.S_IFMT(index_mode) == stat.S_IFLNK:
            issues.append(f"{relative}: symlink in Git index is not release-safe")
            continue
        if not stat.S_ISREG(info.st_mode):
            # Symlinks and special files are already described by _special_files.
            if stat.S_ISDIR(info.st_mode):
                issues.append(f"{relative}: directories cannot be release files")
            continue
        reason = _forbidden_path_reason(relative)
        if reason:
            issues.append(f"{relative}: {reason}")
        executable_mode = index_mode if index_mode is not None else info.st_mode
        if executable_mode & 0o111:
            try:
                with path.open("rb") as handle:
                    first_line = handle.readline(256)
            except OSError:
                first_line = b""
            safe_script = (
                relative.startswith("scripts/")
                or relative in {"ipad_agent/runtime.py", "ipad_agent/server.py"}
            ) and path.suffix.casefold() in {".py", ".sh"}
            if not safe_script or not first_line.startswith(b"#!"):
                issues.append(f"{relative}: unsafe executable bit")
        issues.extend(content_issues(path, relative))
    issues.extend(validate_documents(root, paths))
    issues.extend(validate_manifests(root, relatives))
    issues.extend(validate_public_lab_claims(root, relatives))
    return sorted(set(issues))


def validate_doctor_report(path: Path, root: Path, process_exit: int | None) -> None:
    report = _strict_json(path)
    if not isinstance(report, dict):
        raise CheckFailure(f"{path}: doctor report must be an object")
    schema_files = {
        "ipad-agent.doctor/v1": "schemas/doctor-v1.json",
        "ipad-agent.doctor/v2": "schemas/doctor-v2.json",
    }
    schema_relative = schema_files.get(report.get("schema"))
    if schema_relative is None:
        raise CheckFailure(f"{path}: unsupported doctor schema {report.get('schema')!r}")
    schema_path = root / schema_relative
    schema = _strict_json(schema_path)
    _validate_schema_document(schema, schema_path)
    validate_schema(report, schema, name=str(path))
    exit_code = report["exit_code"]
    if exit_code not in DOCUMENTED_READINESS_EXITS:
        raise CheckFailure(f"doctor reported undocumented readiness exit {exit_code}")
    if process_exit is not None and process_exit != exit_code:
        raise CheckFailure(f"doctor process exit {process_exit} does not match JSON exit_code {exit_code}")
    bad = [item for item in report["checks"] if item["status"] in {"fail", "action_required", "unknown"}]
    if report["ready"] != (exit_code == 0 and not bad):
        raise CheckFailure("doctor ready/exit/check status fields are inconsistent")
    if report["next"] != [item["id"] for item in bad]:
        raise CheckFailure("doctor next must list non-ready checks in report order")
    if report["schema"] == "ipad-agent.doctor/v2":
        if not bad:
            expected_state, expected_exit = "ready", 0
        elif any(item["status"] == "fail" for item in bad):
            expected_state, expected_exit = "needs_agent_action", 20
        elif any(item["status"] == "unknown" for item in bad):
            expected_state, expected_exit = "blocked", 30
        else:
            expected_state, expected_exit = "action_required", 10
        if report["state"] != expected_state or exit_code != expected_exit:
            raise CheckFailure("doctor v2 state/exit/check status fields are inconsistent")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--doctor-json", type=Path)
    parser.add_argument("--doctor-exit", type=int)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        if args.doctor_json is not None:
            validate_doctor_report(args.doctor_json, root, args.doctor_exit)
            print("doctor JSON is valid")
            return 0
        issues = check_release(root)
    except CheckFailure as error:
        issues = [str(error)]
    if issues:
        print("release check failed:", file=sys.stderr)
        for issue in issues:
            print(f"- {issue}", file=sys.stderr)
        return 1
    print("release check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
