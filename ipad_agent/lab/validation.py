"""Strict static validation for manifests and lab artifacts."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping
from urllib.parse import urlsplit

from ipad_agent.registry import RegistryError, _validate_manifest


class LabValidationError(ValueError):
    pass


def _reject_constant(value: str) -> None:
    raise LabValidationError(f"non-finite JSON number is not allowed: {value}")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise LabValidationError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _digest(value: Any) -> str:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise LabValidationError("artifact must contain only finite JSON values") from error
    return hashlib.sha256(encoded).hexdigest()


def _keys(value: Mapping[str, Any], required: set[str], optional: set[str], context: str) -> None:
    missing = required - set(value)
    extra = set(value) - required - optional
    if missing or extra:
        raise LabValidationError(f"{context} fields invalid; missing={sorted(missing)} extra={sorted(extra)}")


def read_json_strict(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        with source.open("r", encoding="utf-8") as handle:
            value = json.load(handle, object_pairs_hook=_strict_object, parse_constant=_reject_constant)
    except LabValidationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise LabValidationError(f"cannot load {source}: {error}") from error
    if not isinstance(value, dict):
        raise LabValidationError(f"{source} must contain a JSON object")
    return value


_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*$")


def _url_policy_path(path: Path, integration_id: str, kind: str) -> Path:
    if path.name == "integration.json" and path.is_absolute():
        return path.with_name("url-policy.json")
    root = Path(__file__).resolve().parents[2]
    base = root / ("addons" if kind == "addon" else "integrations") / integration_id
    return base / "url-policy.json"


def _validate_url_policy(
    value: Mapping[str, Any], *, integration_id: str, open_url_actions: set[str], context: str,
) -> dict[str, list[str]]:
    _keys(
        value, {"$schema", "schema", "version", "integration_id", "actions"}, set(),
        f"{context} URL policy",
    )
    if (
        value["$schema"] != "../../schemas/url-policy-v1.json"
        or value["schema"] != "ipad-agent.url-policy/v1"
        or isinstance(value["version"], bool) or value["version"] != 1
        or value["integration_id"] != integration_id
    ):
        raise LabValidationError(f"{context} URL policy identity is invalid")
    actions = value["actions"]
    if not isinstance(actions, dict) or set(actions) != open_url_actions:
        missing = sorted(open_url_actions - set(actions if isinstance(actions, dict) else {}))
        extra = sorted(set(actions if isinstance(actions, dict) else {}) - open_url_actions)
        raise LabValidationError(
            f"{context} URL policy must bind every and only open-url action; missing={missing} extra={extra}"
        )
    normalized: dict[str, list[str]] = {}
    for action_id, schemes in actions.items():
        if (
            not isinstance(action_id, str) or not action_id
            or not isinstance(schemes, list) or not schemes
            or not all(isinstance(item, str) and _SCHEME.fullmatch(item) for item in schemes)
            or schemes != sorted(set(schemes))
        ):
            raise LabValidationError(
                f"{context} URL policy action {action_id!r} requires sorted unique lowercase schemes"
            )
        normalized[action_id] = list(schemes)
    return normalized


def manifest_digest(value: Mapping[str, Any]) -> str:
    """Digest the normalized integration and its strict URL-policy sidecar."""
    plain = {key: item for key, item in value.items() if key != "_lab_url_policy"}
    return _digest({"integration": plain, "url_policy": value.get("_lab_url_policy", {})})


def validate_manifest(source: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    """Return the normalized manifest or reject any structural/semantic drift."""
    embedded_policy = None
    if isinstance(source, Mapping):
        try:
            value = json.loads(json.dumps(dict(source), allow_nan=False))
        except (TypeError, ValueError) as error:
            raise LabValidationError("manifest must contain only finite JSON values") from error
        embedded_policy = value.pop("_lab_url_policy", None)
        path = Path("integration.json")
    else:
        path = Path(source).expanduser().resolve()
        value = read_json_strict(path)
    integration_id = value.get("id")
    kind = value.get("kind")
    if not isinstance(integration_id, str) or not isinstance(kind, str):
        raise LabValidationError("manifest requires string id and kind fields")
    try:
        normalized = _validate_manifest(value, path, {
            "id": integration_id, "kind": kind,
            "aliases": value.get("aliases"), "bundle_ids": value.get("bundle_ids"),
        })
    except RegistryError as error:
        raise LabValidationError(str(error)) from error

    open_url_actions = {
        action_id for action_id, action in normalized["actions"].items()
        if any(step["operation"] == "open-url" for step in action["steps"])
    }
    if open_url_actions:
        if embedded_policy is None:
            policy_path = _url_policy_path(path, integration_id, kind)
            if not policy_path.is_file():
                raise LabValidationError(f"{path}: open-url actions require url-policy.json")
            embedded_policy = read_json_strict(policy_path)
        if not isinstance(embedded_policy, Mapping):
            raise LabValidationError(f"{path}: URL policy must be an object")
        if set(embedded_policy) == open_url_actions:
            embedded_policy = {
                "$schema": "../../schemas/url-policy-v1.json",
                "schema": "ipad-agent.url-policy/v1", "version": 1,
                "integration_id": integration_id, "actions": dict(embedded_policy),
            }
        normalized["_lab_url_policy"] = _validate_url_policy(
            embedded_policy, integration_id=integration_id,
            open_url_actions=open_url_actions, context=str(path),
        )
    elif embedded_policy not in (None, {}):
        raise LabValidationError(f"{path}: URL policy is forbidden without open-url actions")
    else:
        normalized["_lab_url_policy"] = {}

    # The registry deliberately infers executable policy for unindexed drafts.  The
    # lab must not silently normalize a false safety/retry label before planning it.
    for action_id, action in normalized["actions"].items():
        raw = value["actions"][action_id]
        for field in ("safety", "retry"):
            if raw[field] != action[field]:
                raise LabValidationError(
                    f"action {action_id!r} {field} must exactly match executable behavior: {action[field]!r}"
                )
    for scenario_id, scenario in normalized["scenarios"].items():
        raw = value["scenarios"][scenario_id]
        for field in ("safety", "retry"):
            if raw[field] != scenario[field]:
                raise LabValidationError(
                    f"scenario {scenario_id!r} {field} must exactly match executable behavior: {scenario[field]!r}"
                )
        declared = {item.casefold() for item in scenario["capabilities"]}
        used = {normalized["actions"][action_id]["capability"].casefold() for action_id in scenario["actions"]}
        if used != declared:
            missing = sorted(used - declared)
            unused = sorted(declared - used)
            details = []
            if missing:
                details.append("missing " + ", ".join(missing))
            if unused:
                details.append("unused " + ", ".join(unused))
            raise LabValidationError(
                f"scenario {scenario_id!r} capability set does not exactly match its actions: " + "; ".join(details)
            )
    if value["retry"]["default"] != normalized["retry"]["default"]:
        raise LabValidationError(
            f"manifest retry.default must exactly match executable behavior: {normalized['retry']['default']!r}"
        )
    return normalized


def _parse_offset_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip() or len(value) > 40:
        raise LabValidationError(f"{field} must be a bounded ISO-8601 timestamp")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise LabValidationError(f"{field} must be ISO-8601") from error
    if timestamp.utcoffset() is None:
        raise LabValidationError(f"{field} must include a UTC offset")
    return timestamp.astimezone(timezone.utc)


def _validate_authorization(
    value: Any, binding: Mapping[str, Any], *, mode: str, metrics: Mapping[str, Any],
    started_at: str, finished_at: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LabValidationError("physical evidence requires an authorization object")
    required = {
        "actor", "request", "integration_id", "manifest_digest", "plan_digest",
        "scenario_id", "parameters", "safety_ceiling", "confirmations", "authorized_at",
        "expires_at", "run_count", "benchmark_parameters", "benchmark_control_plan",
    }
    _keys(value, required, set(), "authorization")
    for field in ("actor", "request", "integration_id", "scenario_id", "authorized_at"):
        if not isinstance(value[field], str) or not value[field].strip():
            raise LabValidationError(f"authorization.{field} must be non-empty")
    authorized = _parse_offset_time(value["authorized_at"], "authorization.authorized_at")
    expires = _parse_offset_time(value["expires_at"], "authorization.expires_at")
    if expires <= authorized:
        raise LabValidationError("authorization.expires_at must be after authorized_at")
    if _parse_offset_time(started_at, "evidence.started_at") < authorized:
        raise LabValidationError("physical evidence started before authorization")
    if _parse_offset_time(finished_at, "evidence.finished_at") > expires:
        raise LabValidationError("physical evidence finished after authorization expiry")
    if isinstance(value["run_count"], bool) or not isinstance(value["run_count"], int) or value["run_count"] < 1:
        raise LabValidationError("authorization.run_count must be a positive integer")
    for field in ("manifest_digest", "plan_digest"):
        if not isinstance(value[field], str) or not re.fullmatch(r"[a-f0-9]{64}", value[field]):
            raise LabValidationError(f"authorization.{field} must be a SHA-256 digest")
    if value["safety_ceiling"] not in {"observe", "navigate", "transient"}:
        raise LabValidationError("authorization safety ceiling exceeds the lab")
    if not isinstance(value["parameters"], dict):
        raise LabValidationError("authorization.parameters must be an object")
    confirmations = value["confirmations"]
    if (
        not isinstance(confirmations, list)
        or not all(isinstance(item, str) and item.strip() == item and item for item in confirmations)
        or len(confirmations) != len(set(confirmations))
        or confirmations != binding.get("requires_confirmation")
    ):
        raise LabValidationError("authorization.confirmations are not exactly bound to manifest requirements")
    for field in ("integration_id", "scenario_id", "manifest_digest", "plan_digest", "parameters"):
        if value[field] != binding[field]:
            raise LabValidationError(f"authorization.{field} is not bound to evidence")
    plan_ceiling = binding.get("safety_ceiling")
    if plan_ceiling is not None and value["safety_ceiling"] != plan_ceiling:
        raise LabValidationError("authorization.safety_ceiling is not bound to evidence")
    if mode == "benchmark":
        expected_parameters = {"warmups": metrics.get("warmups"), "runs": metrics.get("runs")}
        if value["benchmark_parameters"] != expected_parameters:
            raise LabValidationError("authorization benchmark parameters are not bound to evidence")
        if value["run_count"] != metrics.get("warmups", 0) + metrics.get("runs", 0):
            raise LabValidationError("authorization run_count is not bound to benchmark executions")
        if value["benchmark_control_plan"] != metrics.get("control_plan"):
            raise LabValidationError("authorization benchmark control plan is not bound to evidence")
        _validate_benchmark_control_plan(value["benchmark_control_plan"], binding)
    elif (
        value["run_count"] != 1 or value["benchmark_parameters"] is not None
        or value["benchmark_control_plan"] is not None
    ):
        raise LabValidationError("non-benchmark authorization must bind exactly one run")
    return value


_STEP_SAFETY = {
    "inspect": "observe", "wait": "observe", "activate": "navigate",
    "open-url": "transient", "tap": "transient", "clear-type": "transient",
    "type": "transient", "swipe": "transient",
}
_SAFETY_RANK = {"observe": 0, "navigate": 1, "transient": 2}
_RETRY = {"safe_repeat", "inspect_then_decide"}


def _validate_serialized_plan(plan: Mapping[str, Any], integration_id: str, scenario_id: str) -> None:
    if plan.get("integration_id") != integration_id or plan.get("scenario_id") != scenario_id:
        raise LabValidationError("evidence plan identity is not bound to the evidence identity")
    if not isinstance(plan.get("manifest_digest"), str) or not re.fullmatch(r"[a-f0-9]{64}", plan["manifest_digest"]):
        raise LabValidationError("evidence.plan.manifest_digest must be a SHA-256 digest")
    if not isinstance(plan.get("steps"), list) or not plan["steps"]:
        raise LabValidationError("evidence.plan.steps must be a non-empty array")
    metadata = plan.get("metadata")
    policies = metadata.get("action_policies") if isinstance(metadata, dict) else None
    if not isinstance(policies, dict):
        raise LabValidationError("evidence plan must carry action policies")
    confirmations = metadata.get("requires_confirmation")
    if (
        not isinstance(confirmations, list)
        or not all(isinstance(item, str) and item.strip() == item and item for item in confirmations)
        or len(confirmations) != len(set(confirmations))
    ):
        raise LabValidationError("evidence plan confirmation requirements are invalid")
    ceiling = plan.get("safety_ceiling")
    if ceiling not in _SAFETY_RANK:
        raise LabValidationError("evidence plan exceeds the lab safety ceiling")
    action_step_safety: dict[str, list[str]] = {}
    action_retries: dict[str, set[str]] = {}
    instruction_fields = {
        "activate": (set(), set()),
        "open-url": ({"value", "allowed_schemes"}, {"value", "allowed_schemes"}),
        "tap": ({"selector"}, {"selector"}),
        "clear-type": ({"selector", "value"}, {"selector", "value"}),
        "type": ({"value"}, {"value"}),
        "wait": ({"selector", "seconds"}, {"selector", "seconds"}),
        "swipe": ({"direction"}, {"direction"}),
        "inspect": (set() if scenario_id == "selector-discovery" else {"selector"}, {"selector"}),
    }
    for index, step in enumerate(plan["steps"]):
        if not isinstance(step, dict):
            raise LabValidationError(f"evidence.plan.steps[{index}] must be an object")
        _keys(step, {"action_id", "index", "operation", "instruction", "selector"}, set(), f"evidence.plan.steps[{index}]")
        action_id = step["action_id"]
        operation = step["operation"]
        instruction = step["instruction"]
        if not isinstance(action_id, str) or action_id not in policies or step["index"] != index:
            raise LabValidationError("evidence plan step order/action policy is invalid")
        if not isinstance(operation, dict) or not isinstance(instruction, dict):
            raise LabValidationError("evidence plan operation/instruction must be objects")
        _keys(operation, {"operation_id", "name", "safety_class", "retry_class", "authority", "metadata"}, set(), "evidence plan operation")
        operation_name = instruction.get("operation")
        expected_safety = _STEP_SAFETY.get(operation_name)
        if expected_safety is not None:
            required_fields, optional_fields = instruction_fields[operation_name]
            fields = set(instruction) - {"operation"}
            if not required_fields <= fields or fields - optional_fields:
                raise LabValidationError("evidence instruction fields do not match its operation")
        if operation_name == "open-url":
            schemes = instruction.get("allowed_schemes")
            url = instruction.get("value")
            if (
                not isinstance(schemes, list) or not schemes
                or not all(isinstance(item, str) and _SCHEME.fullmatch(item) for item in schemes)
                or schemes != sorted(set(schemes))
                or not isinstance(url, str) or not url or url != url.strip()
                or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in url)
                or re.search(r"%(?![0-9A-Fa-f]{2})", url) or "\\" in url
            ):
                raise LabValidationError("evidence open-url instruction lacks a strict URL-policy binding")
            try:
                parsed = urlsplit(url)
                hostname = parsed.hostname
                _ = parsed.port
            except ValueError as error:
                raise LabValidationError("evidence open-url instruction contains a malformed URL") from error
            if (
                parsed.scheme not in schemes or parsed.scheme != parsed.scheme.casefold()
                or parsed.username is not None or parsed.password is not None
                or (parsed.scheme in {"http", "https"} and (not parsed.netloc or not hostname))
            ):
                raise LabValidationError("evidence open-url instruction violates its URL policy")
        if expected_safety is None or operation["safety_class"] != expected_safety:
            raise LabValidationError("evidence instruction-operation safety invariant failed")
        if _SAFETY_RANK[expected_safety] > _SAFETY_RANK[ceiling]:
            raise LabValidationError("evidence plan step exceeds its safety ceiling")
        policy = policies[action_id]
        if (
            not isinstance(policy, dict)
            or policy.get("safety") not in _SAFETY_RANK
            or _SAFETY_RANK[policy["safety"]] < _SAFETY_RANK[expected_safety]
        ):
            raise LabValidationError("evidence plan action safety does not cover its executable steps")
        retry = operation.get("retry_class")
        if retry not in _RETRY or policy.get("retry") != retry:
            raise LabValidationError("evidence plan retry policy is not bound to its operation")
        if operation.get("authority") is not None:
            raise LabValidationError("lab plan operations must not carry persistent/protected authority")
        if operation.get("operation_id") != f"{integration_id}.{scenario_id}.{index}":
            raise LabValidationError("evidence operation ID is not bound to its plan position")
        selector_name = instruction.get("selector")
        if isinstance(selector_name, str) != isinstance(step.get("selector"), dict):
            raise LabValidationError("evidence instruction selector is not bound to a selector recipe")
        action_step_safety.setdefault(action_id, []).append(expected_safety)
        action_retries.setdefault(action_id, set()).add(retry)
        metadata = operation.get("metadata")
        expected_metadata = {
            "integration_id": integration_id, "scenario_id": scenario_id,
            "action_id": action_id, "step_index": index,
            "instruction_operation": operation_name, "declared_action_safety": policy["safety"],
        }
        if not isinstance(metadata, dict) or any(metadata.get(key) != item for key, item in expected_metadata.items()):
            raise LabValidationError("evidence plan operation metadata is not bound to its instruction")
    for action_id, safety_values in action_step_safety.items():
        expected = max(safety_values, key=_SAFETY_RANK.__getitem__)
        if policies[action_id].get("safety") != expected or action_retries[action_id] != {policies[action_id].get("retry")}:
            raise LabValidationError("evidence action policy does not exactly summarize its steps")


def _validate_benchmark_control_plan(value: Any, binding: Mapping[str, Any]) -> None:
    if not isinstance(value, dict):
        raise LabValidationError("physical benchmark requires a typed control plan")
    _keys(value, {"baseline", "reset", "cleanup", "control_plan_digest"}, set(), "benchmark control plan")
    phases = {name: value[name] for name in ("baseline", "reset", "cleanup")}
    if value["control_plan_digest"] != _digest(phases):
        raise LabValidationError("benchmark control plan digest is invalid")
    operation_ids: set[str] = set()
    for phase_name, steps in phases.items():
        if not isinstance(steps, list) or not steps:
            raise LabValidationError(f"benchmark control {phase_name} must contain typed plan steps")
        for step in steps:
            if not isinstance(step, dict):
                raise LabValidationError("benchmark control step must be an object")
            _keys(step, {"action_id", "index", "operation", "instruction", "selector"}, set(), "benchmark control step")
            operation, instruction = step["operation"], step["instruction"]
            if not isinstance(operation, dict) or not isinstance(instruction, dict):
                raise LabValidationError("benchmark control operation/instruction must be objects")
            operation_name = instruction.get("operation")
            if operation_name == "open-url":
                raise LabValidationError("benchmark control steps cannot dispatch URLs outside manifest actions")
            safety = _STEP_SAFETY.get(operation_name)
            if safety is None or operation.get("safety_class") != safety:
                raise LabValidationError("benchmark control instruction-operation safety invariant failed")
            if _SAFETY_RANK[safety] > _SAFETY_RANK[binding["safety_ceiling"]]:
                raise LabValidationError("benchmark control step exceeds authorized safety")
            if operation.get("retry_class") not in _RETRY or operation.get("authority") is not None:
                raise LabValidationError("benchmark control retry/authority is invalid")
            operation_id = operation.get("operation_id")
            if not isinstance(operation_id, str) or not operation_id.strip() or operation_id in operation_ids:
                raise LabValidationError("benchmark control operation IDs must be non-empty and unique")
            operation_ids.add(operation_id)
            metadata = operation.get("metadata")
            if (
                not isinstance(metadata, dict)
                or metadata.get("integration_id") != binding["integration_id"]
                or metadata.get("instruction_operation") != operation_name
            ):
                raise LabValidationError("benchmark control step cannot escape the authorized integration")
            selector_name = instruction.get("selector")
            if isinstance(selector_name, str) != isinstance(step.get("selector"), dict):
                raise LabValidationError("benchmark control selector is not bound to its recipe")


def _validate_step_outcomes(outcomes: Any, steps: list[Mapping[str, Any]], context: str) -> bool:
    if not isinstance(outcomes, list) or len(outcomes) != len(steps):
        raise LabValidationError(f"{context} must contain one outcome for every planned step")
    all_ok = True
    for index, (outcome, step) in enumerate(zip(outcomes, steps)):
        if not isinstance(outcome, dict):
            raise LabValidationError(f"{context}[{index}] must be an object")
        projection = outcome.get("_operation")
        operation = step["operation"]
        if not isinstance(projection, dict):
            raise LabValidationError(f"{context}[{index}] lacks operation binding")
        expected = {
            "schema": "ipad_agent.operation/v1",
            "operation_id": operation["operation_id"],
            "name": operation["name"],
            "safety_class": operation["safety_class"],
            "retry_class": operation["retry_class"],
            "authority_id": None,
        }
        if any(projection.get(key) != value for key, value in expected.items()):
            raise LabValidationError(f"{context}[{index}] does not match the planned step order")
        phase = projection.get("phase")
        if phase not in {"not_sent", "sent", "response_received", "response_lost"}:
            raise LabValidationError(f"{context}[{index}] has an invalid operation phase")
        uncertain = phase == "response_lost"
        ok = outcome.get("ok") is True
        if projection.get("uncertain") is not uncertain or bool(outcome.get("uncertain", False)) is not uncertain:
            raise LabValidationError(f"{context}[{index}] uncertainty is inconsistent")
        if projection.get("complete") is not (phase != "sent"):
            raise LabValidationError(f"{context}[{index}] completion phase is inconsistent")
        if ok != (phase == "response_received" and projection.get("response_received") is True):
            if ok:
                raise LabValidationError(f"{context}[{index}] success phase is inconsistent")
        all_ok = all_ok and ok and not uncertain
    return all_ok


def _validate_outcomes(value: Mapping[str, Any]) -> bool:
    plan_steps = value["plan"]["steps"]
    outcomes = value["outcomes"]
    if value["mode"] != "benchmark":
        return _validate_step_outcomes(outcomes, plan_steps, "evidence.outcomes")
    metrics = value["metrics"]
    warmups, runs = metrics.get("warmups"), metrics.get("runs")
    completed_warmups = metrics.get("completed_warmups")
    completed_runs = metrics.get("completed_runs")
    if (
        isinstance(warmups, bool) or not isinstance(warmups, int) or warmups < 0
        or isinstance(runs, bool) or not isinstance(runs, int) or runs < 1
        or isinstance(completed_warmups, bool) or not isinstance(completed_warmups, int) or completed_warmups < 0
        or isinstance(completed_runs, bool) or not isinstance(completed_runs, int) or completed_runs < 0
        or len(outcomes) != warmups + runs
    ):
        raise LabValidationError("benchmark outcomes do not cover every planned execution")
    all_ok = True
    for index, outcome in enumerate(outcomes):
        if not isinstance(outcome, dict):
            raise LabValidationError("benchmark outcome must be an object")
        expected_kind = "warmup" if index < warmups else "measured"
        if (
            outcome.get("kind") != expected_kind or outcome.get("execution_index") != index
            or not isinstance(outcome.get("executed"), bool)
        ):
            raise LabValidationError("benchmark outcomes are not in planned execution order")
        steps_ok = _validate_step_outcomes(outcome.get("steps"), plan_steps, f"evidence.outcomes[{index}].steps")
        if outcome.get("ok") is not steps_ok:
            raise LabValidationError("benchmark aggregate outcome does not match its planned steps")
        uncertain = any(item.get("_operation", {}).get("uncertain") is True for item in outcome["steps"])
        if bool(outcome.get("uncertain", False)) is not uncertain:
            raise LabValidationError("benchmark aggregate uncertainty does not match its planned steps")
        elapsed = outcome.get("elapsed_seconds")
        if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or elapsed < 0:
            raise LabValidationError("benchmark elapsed_seconds must be a non-negative finite number")
        if outcome["executed"] is False and (steps_ok or any(
            item.get("_operation", {}).get("phase") != "not_sent" for item in outcome["steps"]
        )):
            raise LabValidationError("unexecuted benchmark outcomes must record every step as not_sent")
        all_ok = all_ok and outcome["executed"] and steps_ok and not uncertain
    executed_warmups = sum(item["executed"] for item in outcomes[:warmups])
    executed_runs = sum(item["executed"] for item in outcomes[warmups:])
    if executed_warmups != completed_warmups or executed_runs != completed_runs:
        raise LabValidationError("benchmark executed outcomes do not match completed execution counts")
    return bool(outcomes) and all_ok


def _wda_records(device: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    records: list[Mapping[str, Any]] = []
    wda = device.get("wda")
    if isinstance(wda, Mapping):
        records.append(wda)
    for collection_name in ("benchmark_runs", "benchmark_controls"):
        environments = device.get(collection_name)
        if isinstance(environments, list):
            for environment in environments:
                if isinstance(environment, Mapping) and isinstance(environment.get("wda"), Mapping):
                    records.append(environment["wda"])
    return records


def _teardown_evidenced(device: Mapping[str, Any]) -> bool:
    records = _wda_records(device)
    if not records:
        return False
    for wda in records:
        if wda.get("teardown_complete") is not True:
            return False
        if wda.get("started") is True and not (
            wda.get("owned") is True and wda.get("teardown_attempted") is True
        ):
            return False
    return True


def validate_evidence(source: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    value = read_json_strict(source) if not isinstance(source, Mapping) else dict(source)
    required = {
        "$schema", "schema", "version", "evidence_id", "integration_id", "scenario_id",
        "mode", "started_at", "finished_at", "host", "device", "plan", "binding",
        "authorization", "safety_gate", "outcomes", "metrics", "redaction", "complete",
    }
    _keys(value, required, set(), "evidence")
    if value["$schema"] != "schemas/evidence-v1.json" or value["schema"] != "ipad-agent.lab-evidence/v1" or isinstance(value["version"], bool) or value["version"] != 1:
        raise LabValidationError("unsupported evidence schema")
    if value["mode"] not in {"fake", "physical", "discovery", "benchmark"}:
        raise LabValidationError("evidence.mode is invalid")
    for field in ("evidence_id", "integration_id", "scenario_id", "started_at", "finished_at"):
        if not isinstance(value[field], str) or not value[field].strip():
            raise LabValidationError(f"evidence.{field} must be a non-empty string")
    if not re.fullmatch(r"[a-f0-9]{32}", value["evidence_id"]):
        raise LabValidationError("evidence.evidence_id must be 32 lowercase hexadecimal characters")
    if not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", value["integration_id"]):
        raise LabValidationError("evidence.integration_id is not canonical")
    started = _parse_offset_time(value["started_at"], "evidence.started_at")
    finished = _parse_offset_time(value["finished_at"], "evidence.finished_at")
    if finished < started:
        raise LabValidationError("evidence.finished_at must not precede started_at")
    for field in ("host", "device", "plan", "binding", "safety_gate", "metrics", "redaction"):
        if not isinstance(value[field], dict):
            raise LabValidationError(f"evidence.{field} must be an object")
    if not isinstance(value["outcomes"], list) or not all(isinstance(item, dict) for item in value["outcomes"]):
        raise LabValidationError("evidence.outcomes must be an array of objects")
    if not isinstance(value["complete"], bool):
        raise LabValidationError("evidence.complete must be boolean")
    if value["redaction"] != {"state": "raw-private", "commit": False}:
        raise LabValidationError("evidence.redaction must mark the document raw-private and uncommittable")

    plan = value["plan"]
    required_plan = {
        "integration_id", "scenario_id", "bundle_id", "max_attempts", "safety_ceiling",
        "steps", "metadata", "parameters", "manifest_digest", "plan_digest",
    }
    _keys(plan, required_plan, set(), "evidence.plan")
    digest_payload = {key: item for key, item in plan.items() if key != "plan_digest"}
    if not isinstance(plan["plan_digest"], str) or plan["plan_digest"] != _digest(digest_payload):
        raise LabValidationError("evidence.plan_digest does not match the plan")
    if not isinstance(plan["parameters"], dict):
        raise LabValidationError("evidence.plan.parameters must be an object")
    _validate_serialized_plan(plan, value["integration_id"], value["scenario_id"])

    binding = value["binding"]
    required_binding = {
        "integration_id", "scenario_id", "manifest_digest", "plan_digest", "parameters",
        "parameters_digest", "environment_digest",
    }
    _keys(binding, required_binding, set(), "evidence.binding")
    expected_binding = {
        "integration_id": value["integration_id"],
        "scenario_id": value["scenario_id"],
        "manifest_digest": plan["manifest_digest"],
        "plan_digest": plan["plan_digest"],
        "parameters": plan["parameters"],
        "parameters_digest": _digest(plan["parameters"]),
        "environment_digest": _digest({"host": value["host"], "device": value["device"]}),
    }
    if binding != expected_binding:
        raise LabValidationError("evidence binding does not match integration, plan, parameters, or environment")
    # Expose ceiling to authorization validation without changing the evidence schema.
    auth_binding = dict(binding)
    auth_binding["safety_ceiling"] = plan["safety_ceiling"]
    auth_binding["requires_confirmation"] = plan.get("metadata", {}).get("requires_confirmation")

    physical = value["mode"] in {"physical", "discovery"} or (
        value["mode"] == "benchmark" and value["metrics"].get("physical") is True
    )
    if physical:
        _validate_authorization(
            value["authorization"], auth_binding, mode=value["mode"], metrics=value["metrics"],
            started_at=value["started_at"], finished_at=value["finished_at"],
        )
    elif value["authorization"] is not None:
        raise LabValidationError("non-physical evidence must not contain physical authorization")

    gate = value["safety_gate"]
    _keys(gate, {
        "passed", "ceiling", "maximum_lab_ceiling", "step_count", "prohibition_count",
        "prohibitions_digest", "plan_digest", "persistent_or_protected",
        "instruction_operation_invariants",
    }, set(), "evidence.safety_gate")
    if gate["passed"] is not True or gate["maximum_lab_ceiling"] != "transient" or gate["persistent_or_protected"] is not False or gate["instruction_operation_invariants"] is not True:
        raise LabValidationError("evidence safety gate did not prove the lab invariants")
    if gate["ceiling"] != plan["safety_ceiling"] or gate["step_count"] != len(plan["steps"]):
        raise LabValidationError("evidence safety gate is not bound to the plan")
    prohibited = plan.get("metadata", {}).get("prohibited")
    if (
        not isinstance(prohibited, list)
        or gate["prohibition_count"] != len(prohibited)
        or gate["prohibitions_digest"] != _digest(prohibited)
        or gate["plan_digest"] != plan["plan_digest"]
    ):
        raise LabValidationError("evidence safety gate is not bound to the plan and manifest prohibitions")

    outcomes_ok = _validate_outcomes(value)
    benchmark_complete = True
    if value["mode"] == "benchmark":
        metrics = value["metrics"]
        benchmark_complete = (
            metrics.get("completed_warmups") == metrics.get("warmups")
            and metrics.get("completed_runs") == metrics.get("runs")
            and metrics.get("successful_warmups") == metrics.get("warmups")
            and metrics.get("successful_runs") == metrics.get("runs")
            and metrics.get("uncertain_runs") == 0
            and metrics.get("hooks", {}).get("cleanup_ok") is True
            and all(event.get("ok") is True for event in metrics.get("hooks", {}).get("events", []))
        )
    if value["complete"] and not (outcomes_ok and benchmark_complete):
        raise LabValidationError(
            "complete evidence requires successful, certain outcomes for every planned step and benchmark phase"
        )
    if physical:
        coredevice_captured = (
            value["device"].get("source") == "CoreDevice"
            and value["device"].get("capture") == "device info details"
        )
        if value["complete"] and not coredevice_captured:
            raise LabValidationError("complete physical evidence environment must come from CoreDevice device info details")
        teardown_records = _wda_records(value["device"])
        if value["complete"] and not teardown_records:
            raise LabValidationError("complete physical evidence requires WDA teardown records")
        for wda in teardown_records:
            if not isinstance(wda.get("started"), bool) or not isinstance(wda.get("teardown_complete"), bool):
                raise LabValidationError("physical WDA teardown state must be explicit")
            if wda.get("started") is True and not (
                wda.get("owned") is True and wda.get("teardown_attempted") is True
            ):
                raise LabValidationError("started WDA requires owned teardown-attempt evidence")
        if value["complete"] and not _teardown_evidenced(value["device"]):
            raise LabValidationError("complete physical evidence requires successful WDA teardown")
        if value["complete"] and value["device"].get("capture_error"):
            raise LabValidationError("complete physical evidence requires successful CoreDevice environment capture")
    _digest(value)
    return value


_COMPAT_SCHEMA = "schemas/compatibility-v1.json"
_COMPAT_EXCLUDED = [
    "device identifiers", "hostnames", "user or team values", "tokens", "paths",
    "URLs", "UI source", "raw responses", "authorization actors and requests",
]
_COMPAT_POLICY = "strict field allow-list plus SHA-256 evidence references only"

_COMPAT_METRICS = {
    "warmups", "runs", "minimum_seconds", "median_seconds", "p95_seconds",
    "maximum_seconds", "successful_runs", "uncertain_runs", "elapsed_seconds",
    "candidate_count", "repeatable_candidate_count",
}


def validate_compatibility(source: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    value = read_json_strict(source) if not isinstance(source, Mapping) else dict(source)
    _keys(value, {"$schema", "schema", "version", "generated_at", "source_evidence", "integrations", "redaction"}, set(), "compatibility")
    if value["$schema"] != _COMPAT_SCHEMA or value["schema"] != "ipad-agent.compatibility/v1" or isinstance(value["version"], bool) or value["version"] != 1:
        raise LabValidationError("unsupported compatibility schema")
    _parse_offset_time(value["generated_at"], "compatibility.generated_at")
    if not isinstance(value["source_evidence"], list):
        raise LabValidationError("compatibility.source_evidence must be an array")
    source_digests: list[str] = []
    for source_item in value["source_evidence"]:
        if not isinstance(source_item, dict):
            raise LabValidationError("compatibility source must be an object")
        _keys(source_item, {"sha256"}, set(), "compatibility source")
        if not isinstance(source_item["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", source_item["sha256"]):
            raise LabValidationError("compatibility source digest is invalid")
        source_digests.append(source_item["sha256"])
    if source_digests != sorted(set(source_digests)):
        raise LabValidationError("compatibility source digests must be unique and sorted")
    if not isinstance(value["integrations"], list):
        raise LabValidationError("compatibility.integrations must be an array")
    integration_ids = [item.get("id") for item in value["integrations"] if isinstance(item, dict)]
    if integration_ids != sorted(set(integration_ids), key=repr):
        raise LabValidationError("compatibility integrations must be unique and sorted")
    for integration in value["integrations"]:
        if not isinstance(integration, dict):
            raise LabValidationError("compatibility integration must be an object")
        _keys(integration, {"id", "physical_tested", "platform", "os_versions", "locales", "scenarios", "limitations"}, set(), "compatibility integration")
        if not isinstance(integration["id"], str) or not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", integration["id"]):
            raise LabValidationError("compatibility integration ID is invalid")
        if not isinstance(integration["physical_tested"], bool) or integration["platform"] != "iPadOS":
            raise LabValidationError("compatibility integration physical/platform fields are invalid")
        for field in ("os_versions", "locales", "limitations"):
            if not isinstance(integration[field], list) or not all(isinstance(item, str) for item in integration[field]):
                raise LabValidationError(f"compatibility integration {field} is invalid")
        if integration["limitations"]:
            raise LabValidationError("compatibility limitations are not an allow-listed projection")
        if any(not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}(?:[-+][A-Za-z0-9.-]+)?", item) for item in integration["os_versions"]):
            raise LabValidationError("compatibility OS version is invalid")
        if any(not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", item) for item in integration["locales"]):
            raise LabValidationError("compatibility locale is invalid")
        if (
            integration["os_versions"] != sorted(set(integration["os_versions"]))
            or integration["locales"] != sorted(set(integration["locales"]))
        ):
            raise LabValidationError("compatibility OS versions and locales must be unique and sorted")
        if not isinstance(integration["scenarios"], list):
            raise LabValidationError("compatibility scenarios must be an array")
        scenario_keys = [
            (item.get("id"), item.get("mode"), item.get("evidence_sha256"))
            for item in integration["scenarios"] if isinstance(item, dict)
        ]
        if scenario_keys != sorted(set(scenario_keys), key=repr):
            raise LabValidationError("compatibility scenarios must be unique and sorted")
        for scenario in integration["scenarios"]:
            if not isinstance(scenario, dict):
                raise LabValidationError("compatibility scenario must be an object")
            _keys(scenario, {"id", "mode", "status", "evidence_sha256", "metrics"}, set(), "compatibility scenario")
            if not isinstance(scenario.get("id"), str) or not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", scenario["id"]):
                raise LabValidationError("compatibility scenario ID is invalid")
            if scenario["mode"] not in {"fake", "physical", "discovery", "benchmark"} or scenario["status"] not in {"pass", "fail"}:
                raise LabValidationError("compatibility scenario mode/status is invalid")
            if scenario["evidence_sha256"] not in source_digests:
                raise LabValidationError("compatibility scenario is not bound to source evidence")
            if not isinstance(scenario["metrics"], dict) or set(scenario["metrics"]) - _COMPAT_METRICS:
                raise LabValidationError("compatibility metrics are not allow-listed")
            if any(
                isinstance(item, bool) or not isinstance(item, (int, float))
                or not math.isfinite(item) or item < 0
                for item in scenario["metrics"].values()
            ):
                raise LabValidationError("compatibility metric value is invalid")
        if integration["physical_tested"] is False and (integration["os_versions"] or integration["locales"]):
            raise LabValidationError("non-physical compatibility cannot claim OS or locale coverage")
    redaction = value["redaction"]
    if not isinstance(redaction, dict):
        raise LabValidationError("compatibility.redaction must be an object")
    _keys(redaction, {"raw_evidence_committed", "excluded", "policy"}, set(), "compatibility.redaction")
    if redaction != {
        "raw_evidence_committed": False,
        "excluded": _COMPAT_EXCLUDED,
        "policy": _COMPAT_POLICY,
    }:
        raise LabValidationError("compatibility redaction policy must exactly match the allow-list contract")
    _digest(value)
    return value


__all__ = [
    "LabValidationError", "manifest_digest", "read_json_strict", "validate_compatibility",
    "validate_evidence", "validate_manifest",
]
