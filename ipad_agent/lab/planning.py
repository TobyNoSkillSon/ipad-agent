"""Scenario planning with manifest, instruction, safety, and retry invariants."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from ipad_agent.operations import OperationSpec, RetryClass, SafetyClass

from .model import PlannedStep, ScenarioPlan, canonical_digest
from .validation import manifest_digest, validate_manifest

MAX_PHYSICAL_SAFETY = SafetyClass.TRANSIENT
_SAFETY_ORDER = {
    SafetyClass.OBSERVE: 0,
    SafetyClass.NAVIGATE: 1,
    SafetyClass.TRANSIENT: 2,
    SafetyClass.PERSISTENT: 3,
    SafetyClass.PROTECTED: 4,
}
_STEP_SAFETY = {
    "inspect": SafetyClass.OBSERVE,
    "wait": SafetyClass.OBSERVE,
    "activate": SafetyClass.NAVIGATE,
    "open-url": SafetyClass.TRANSIENT,
    "tap": SafetyClass.TRANSIENT,
    "clear-type": SafetyClass.TRANSIENT,
    "type": SafetyClass.TRANSIENT,
    "swipe": SafetyClass.TRANSIENT,
}
_PLACEHOLDER = re.compile(r"\{([a-zA-Z][a-zA-Z0-9_-]*)\}")


def _substitute(value: Any, parameters: Mapping[str, Any]) -> Any:
    if not isinstance(value, str):
        return value
    names = _PLACEHOLDER.findall(value)
    missing = sorted(set(names) - set(parameters))
    if missing:
        raise ValueError("missing scenario parameter(s): " + ", ".join(missing))
    rendered = value
    for name in names:
        replacement = parameters[name]
        if not isinstance(replacement, (str, int, float)) or isinstance(replacement, bool):
            raise ValueError(f"scenario parameter {name!r} must be string or number")
        rendered = rendered.replace("{" + name + "}", str(replacement))
    return rendered


def _validated_url(value: Any, allowed_schemes: Any, *, action_id: str) -> tuple[str, list[str]]:
    if (
        not isinstance(value, str) or not value or value != value.strip()
        or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ValueError(f"open-url action {action_id!r} requires a non-empty URL without whitespace or controls")
    if (
        not isinstance(allowed_schemes, list) or not allowed_schemes
        or not all(isinstance(item, str) and re.fullmatch(r"[a-z][a-z0-9+.-]*", item) for item in allowed_schemes)
        or allowed_schemes != sorted(set(allowed_schemes))
    ):
        raise ValueError(f"open-url action {action_id!r} has an invalid allowed-schemes declaration")
    if re.search(r"%(?![0-9A-Fa-f]{2})", value) or "\\" in value:
        raise ValueError(f"open-url action {action_id!r} contains malformed URL escaping")
    try:
        parsed = urlsplit(value)
        scheme = parsed.scheme.casefold()
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as error:
        raise ValueError(f"open-url action {action_id!r} contains a malformed URL") from error
    if not scheme or scheme != parsed.scheme or scheme not in allowed_schemes:
        raise ValueError(f"open-url action {action_id!r} uses unsupported scheme {parsed.scheme!r}")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"open-url action {action_id!r} must not contain URL credentials")
    if scheme in {"http", "https"} and (not parsed.netloc or not hostname):
        raise ValueError(f"open-url action {action_id!r} requires an absolute HTTP(S) URL with a host")
    return value, list(allowed_schemes)


def _declared_action_safety(text: str) -> SafetyClass | None:
    normalized = text.casefold()
    if re.search(r"\bprotected\b|\bconfirmation\b", normalized):
        return SafetyClass.PROTECTED
    if re.search(r"\bpersistent\b|\bpermanent\b", normalized):
        return SafetyClass.PERSISTENT
    if re.search(r"\btransient\b", normalized):
        return SafetyClass.TRANSIENT
    if re.search(r"\bnavigat(?:e|ion)\b", normalized):
        return SafetyClass.NAVIGATE
    if re.search(r"\bobserve\b|\bread[- ]only\b", normalized):
        return SafetyClass.OBSERVE
    return None


def assert_step_invariant(step: PlannedStep) -> None:
    """Reject any mismatch that could disguise a mutating instruction as observation."""
    operation_name = step.instruction.get("operation")
    expected = _STEP_SAFETY.get(operation_name)
    if expected is None:
        raise ValueError(f"unsupported lab instruction operation: {operation_name!r}")
    if step.operation.safety_class is not expected:
        raise ValueError(
            f"instruction-operation invariant failed for {operation_name}: "
            f"instruction is {expected.value}, operation spec is {step.operation.safety_class.value}"
        )
    declared = step.operation.metadata.get("declared_action_safety")
    if declared == SafetyClass.OBSERVE.value and expected is not SafetyClass.OBSERVE:
        raise ValueError(f"observe-labelled action {step.action_id!r} cannot dispatch {operation_name}")
    if declared in {SafetyClass.PERSISTENT.value, SafetyClass.PROTECTED.value}:
        raise ValueError(f"lab rejects {declared} action {step.action_id!r}")


def verify_plan_safety(
    plan: ScenarioPlan, *, requested_ceiling: SafetyClass | str | None = None,
) -> dict[str, Any]:
    """Run the actual lab safety gate and return its evidence-ready result."""
    ceiling = plan.safety_ceiling if requested_ceiling is None else SafetyClass(requested_ceiling)
    if _SAFETY_ORDER[ceiling] > _SAFETY_ORDER[MAX_PHYSICAL_SAFETY]:
        raise ValueError(f"lab safety ceiling cannot exceed {MAX_PHYSICAL_SAFETY.value}")
    if _SAFETY_ORDER[plan.safety_ceiling] > _SAFETY_ORDER[ceiling]:
        raise ValueError("plan safety ceiling exceeds the requested safety ceiling")
    for step in plan.steps:
        assert_step_invariant(step)
        if step.operation.safety_class in {SafetyClass.PERSISTENT, SafetyClass.PROTECTED}:
            raise ValueError("persistent and protected operations are unavailable in the integration lab")
        if _SAFETY_ORDER[step.operation.safety_class] > _SAFETY_ORDER[ceiling]:
            raise ValueError(
                f"{step.action_id}[{step.index}] is {step.operation.safety_class.value}, above ceiling {ceiling.value}"
            )
    prohibited = plan.metadata.get("prohibited", [])
    if not isinstance(prohibited, list) or not all(isinstance(item, str) and item.strip() for item in prohibited):
        raise ValueError("plan must carry the manifest prohibition list")
    return {
        "passed": True,
        "ceiling": ceiling.value,
        "maximum_lab_ceiling": MAX_PHYSICAL_SAFETY.value,
        "step_count": len(plan.steps),
        "prohibition_count": len(prohibited),
        "prohibitions_digest": canonical_digest(prohibited),
        "plan_digest": plan.plan_digest,
        "persistent_or_protected": False,
        "instruction_operation_invariants": True,
    }


def plan_scenario(
    manifest: str | Path | Mapping[str, Any],
    scenario_id: str,
    *,
    parameters: Mapping[str, Any] | None = None,
    safety_ceiling: SafetyClass = MAX_PHYSICAL_SAFETY,
) -> ScenarioPlan:
    normalized = validate_manifest(manifest)
    url_policy = normalized.get("_lab_url_policy", {})
    try:
        ceiling = SafetyClass(safety_ceiling)
    except (TypeError, ValueError) as error:
        raise ValueError("invalid safety_ceiling") from error
    if _SAFETY_ORDER[ceiling] > _SAFETY_ORDER[MAX_PHYSICAL_SAFETY]:
        raise ValueError(f"lab safety ceiling cannot exceed {MAX_PHYSICAL_SAFETY.value}")
    scenario = normalized["scenarios"].get(scenario_id)
    if scenario is None:
        raise KeyError(f"unknown scenario {scenario_id!r}")
    values = {} if parameters is None else dict(parameters)
    # Ensure the complete parameter record is finite JSON before it can bind authority/evidence.
    canonical_digest(values)
    steps: list[PlannedStep] = []
    idempotent = {item.casefold() for item in normalized["retry"]["idempotent_actions"]}
    ordinal = 0
    action_policies: dict[str, dict[str, Any]] = {}
    for action_id in scenario["actions"]:
        action = normalized["actions"][action_id]
        declared = SafetyClass(action["safety"])
        if declared in {SafetyClass.PERSISTENT, SafetyClass.PROTECTED}:
            raise ValueError(f"lab rejects {declared.value} manifest action {action_id!r}")
        action_policies[action_id] = {
            "safety": action["safety"], "retry": action["retry"],
            "declared_class": None if declared is None else declared.value,
        }
        for raw in action["steps"]:
            instruction = {key: _substitute(value, values) for key, value in raw.items()}
            operation_name = instruction["operation"]
            if operation_name == "open-url":
                url, allowed = _validated_url(
                    instruction.get("value"), url_policy.get(action_id), action_id=action_id,
                )
                instruction = {"operation": "open-url", "value": url, "allowed_schemes": allowed}
            safety = _STEP_SAFETY[operation_name]
            if declared is SafetyClass.OBSERVE and safety is not SafetyClass.OBSERVE:
                raise ValueError(f"observe-labelled action {action_id!r} cannot dispatch {operation_name}")
            if _SAFETY_ORDER[safety] > _SAFETY_ORDER[ceiling]:
                raise ValueError(f"{action_id}[{ordinal}] is {safety.value}, above ceiling {ceiling.value}")
            # Every step inherits the manifest action retry contract.  In
            # particular, an observational wait inside a transient action must
            # not become independently safe-repeatable.
            retry = RetryClass(action["retry"])
            if (retry is RetryClass.SAFE_REPEAT) != (action_id.casefold() in idempotent):
                raise ValueError(f"action {action_id!r} retry/idempotence invariant failed")
            operation = OperationSpec(
                operation_id=f"{normalized['id']}.{scenario_id}.{ordinal}",
                name=f"{action_id}:{operation_name}",
                safety_class=safety,
                retry_class=retry,
                metadata={
                    "integration_id": normalized["id"], "scenario_id": scenario_id,
                    "action_id": action_id, "step_index": ordinal,
                    "instruction_operation": operation_name,
                    "declared_action_safety": None if declared is None else declared.value,
                },
            )
            selector = None
            selector_name = instruction.get("selector")
            if isinstance(selector_name, str):
                selector = normalized["selectors"][selector_name]
            step = PlannedStep(action_id, ordinal, operation, instruction, selector)
            assert_step_invariant(step)
            steps.append(step)
            ordinal += 1
    source_path = None if isinstance(manifest, Mapping) else Path(manifest).expanduser().resolve()
    plan = ScenarioPlan(
        normalized["id"], scenario_id, normalized["bundle_ids"][0], tuple(steps),
        normalized["retry"]["max_attempts"], ceiling, source_path,
        {
            "description": scenario["description"], "scenario_safety": scenario["safety"],
            "scenario_retry": scenario["retry"], "action_policies": action_policies,
            "manifest_classification": normalized["safety"]["classification"],
            "mutates_user_data": normalized["safety"]["mutates_user_data"],
            "requires_confirmation": normalized["safety"]["requires_confirmation"],
            "prohibited": normalized["safety"]["prohibited"],
            "uncertain_outcome": normalized["safety"]["uncertain_outcome"],
        },
        values,
        manifest_digest(normalized),
    )
    verify_plan_safety(plan, requested_ceiling=ceiling)
    return plan


__all__ = ["MAX_PHYSICAL_SAFETY", "assert_step_invariant", "plan_scenario", "verify_plan_safety"]
