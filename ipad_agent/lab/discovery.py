"""Static route candidates and authorized, repeatable selector discovery."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ipad_agent.operations import OperationError, OperationResult, OperationSpec, SafetyClass

from .evidence import evidence_document, record_evidence, utc_now
from .model import PhysicalAuthorization, PlannedStep, ScenarioPlan
from .planning import assert_step_invariant, verify_plan_safety
from .runner import PhysicalExecutor
from .validation import manifest_digest, validate_manifest


def discover_direct_routes(manifest: str | Path | Mapping[str, Any]) -> list[dict[str, Any]]:
    """List declared CoreDevice candidates without contacting a device."""
    value = validate_manifest(manifest)
    candidates: list[dict[str, Any]] = []
    for action_id, action in value["actions"].items():
        for index, step in enumerate(action["steps"]):
            if step["operation"] in {"activate", "open-url"}:
                candidates.append({
                    "action_id": action_id, "step_index": index,
                    "operation": step["operation"], "template": step.get("value"),
                    "allowed_schemes": (
                        value.get("_lab_url_policy", {}).get(action_id, [])
                        if step["operation"] == "open-url" else []
                    ),
                    "bundle_id": value["bundle_ids"][0],
                })
    return candidates


def _walk_nodes(value: Any, path: str = "root"):
    if isinstance(value, Mapping):
        yield value, path
        for key, item in value.items():
            yield from _walk_nodes(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_nodes(item, f"{path}[{index}]")


def _inspection_candidates(source: Mapping[str, Any]) -> dict[tuple[str, str], list[str]]:
    found: dict[tuple[str, str], list[str]] = {}
    for node, path in _walk_nodes(source):
        context_bits = []
        for name in ("type", "label", "name"):
            item = node.get(name)
            if isinstance(item, str) and item.strip():
                context_bits.append(f"{name}={item.strip()[:120]}")
        context = path + (" (" + ", ".join(context_bits) + ")" if context_bits else "")
        for key in ("identifier", "name", "label", "value"):
            value = node.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            text = value.strip()
            recipes: list[tuple[str, str]] = []
            if key == "identifier" or (key == "name" and len(text) <= 120):
                recipes.append(("accessibility id", text))
            if key in {"label", "name"} and len(text) <= 120 and "'" not in text:
                recipes.append(("-ios predicate string", f"{key} == '{text}'"))
            for recipe in set(recipes):
                contexts = found.setdefault(recipe, [])
                if context not in contexts:
                    contexts.append(context)
    return found


def selector_observations(*sources: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Record per-inspection cardinality/context and cross-inspection repeatability."""
    if not sources:
        raise ValueError("at least one source inspection is required")
    inspections = [_inspection_candidates(source) for source in sources]
    recipes = sorted(set().union(*(set(item) for item in inspections)))
    observations: list[dict[str, Any]] = []
    for using, value in recipes:
        records = []
        cardinalities = []
        for index, inspection in enumerate(inspections, start=1):
            contexts = inspection.get((using, value), [])
            cardinalities.append(len(contexts))
            records.append({"inspection": index, "cardinality": len(contexts), "contexts": contexts})
        context_sets = [record["contexts"] for record in records]
        repeatable = (
            len(inspections) >= 2
            and all(count == cardinalities[0] and count > 0 for count in cardinalities)
            and all(contexts == context_sets[0] for contexts in context_sets[1:])
        )
        observations.append({
            "using": using, "value": value, "inspections": records,
            "repeatable": repeatable, "unique": all(count == 1 for count in cardinalities),
        })
    return observations


def discover_selectors(
    source: Mapping[str, Any], repeated_source: Mapping[str, Any] | None = None, *,
    include_observations: bool = False,
) -> list[dict[str, Any]]:
    """Extract candidates; optionally prove cardinality/context across two inspections.

    The one-source default retains the original compact API. Such candidates are
    suggestions only and carry no repeatability claim.
    """
    observations = selector_observations(source) if repeated_source is None else selector_observations(source, repeated_source)
    if include_observations:
        return observations
    if repeated_source is None:
        return [{"using": item["using"], "value": item["value"]} for item in observations]
    return [
        {"using": item["using"], "value": item["value"]}
        for item in observations if item["unique"] and item["repeatable"]
    ]


def plan_selector_discovery(manifest: str | Path | Mapping[str, Any]) -> ScenarioPlan:
    value = validate_manifest(manifest)
    metadata = {
        "integration_id": value["id"], "scenario_id": "selector-discovery",
        "action_id": "activate", "step_index": 0,
        "instruction_operation": "activate", "declared_action_safety": "navigate",
    }
    activate = PlannedStep(
        "activate", 0,
        OperationSpec(f"{value['id']}.selector-discovery.0", "activate for selector discovery", SafetyClass.NAVIGATE, metadata=metadata),
        {"operation": "activate"},
    )
    inspections = []
    for index in (1, 2):
        step_metadata = dict(metadata)
        step_metadata.update({
            "action_id": "inspect", "instruction_operation": "inspect",
            "declared_action_safety": "observe", "step_index": index,
        })
        inspections.append(PlannedStep(
            "inspect", index,
            OperationSpec(f"{value['id']}.selector-discovery.{index}", f"accessibility inspection {index}", SafetyClass.OBSERVE, metadata=step_metadata),
            {"operation": "inspect"},
        ))
    path = None if isinstance(manifest, Mapping) else Path(manifest).expanduser().resolve()
    plan = ScenarioPlan(
        value["id"], "selector-discovery", value["bundle_ids"][0],
        (activate, *inspections), 1, SafetyClass.NAVIGATE, path,
        {
            "description": "Two repeatability inspections of one unchanged visible state.",
            "scenario_safety": "navigate", "scenario_retry": "safe_repeat",
            "action_policies": {
                "activate": {"safety": "navigate", "retry": "safe_repeat", "declared_class": "navigate"},
                "inspect": {"safety": "observe", "retry": "safe_repeat", "declared_class": "observe"},
            },
            "manifest_classification": value["safety"]["classification"],
            "mutates_user_data": False, "requires_confirmation": value["safety"]["requires_confirmation"],
            "prohibited": value["safety"]["prohibited"],
            "uncertain_outcome": value["safety"]["uncertain_outcome"],
        },
        {}, manifest_digest(value),
    )
    verify_plan_safety(plan)
    return plan


def discover_physical_selectors(
    manifest: str | Path | Mapping[str, Any], *, physical: bool = False,
    authorization: PhysicalAuthorization | None = None,
    repository_root: str | Path = Path(__file__).resolve().parents[2], record: bool = True,
) -> dict[str, Any]:
    if physical is not True:
        raise PermissionError("physical selector discovery requires physical=True")
    plan = plan_selector_discovery(manifest)
    if not isinstance(authorization, PhysicalAuthorization):
        raise PermissionError("physical selector discovery requires a PhysicalAuthorization record")
    authorization.verify(plan)
    started = utc_now()
    results: list[OperationResult] = []
    runner = PhysicalExecutor(physical=True, authorization=authorization, plan=plan)
    with runner:
        for step in plan.steps:
            assert_step_invariant(step)
            result = runner.execute(step, plan.bundle_id)
            results.append(result)
            if result.ok is not True:
                break
        if len(results) < len(plan.steps):
            for skipped in plan.steps[len(results):]:
                results.append(OperationResult.not_sent(
                    skipped.operation,
                    OperationError("skipped", "step was not sent because an earlier planned step failed"),
                ))
    finished = utc_now()
    sources: list[Mapping[str, Any]] = []
    for result in results[1:]:
        source = result.response.get("source", {}) if result.ok and isinstance(result.response, Mapping) else {}
        if isinstance(source, Mapping):
            sources.append(source)
    observations = selector_observations(*sources) if sources else []
    candidates = [
        {"using": item["using"], "value": item["value"]}
        for item in observations if item["unique"] and item["repeatable"]
    ]
    evidence_path = None
    if record:
        document = evidence_document(
            mode="discovery", plan=plan, outcomes=[item.to_plain_result() for item in results],
            started_at=started, finished_at=finished,
            metrics={
                "candidate_count": len(observations),
                "repeatable_candidate_count": len(candidates),
                "inspections": len(sources), "selector_observations": observations,
            },
            device=dict(runner.environment),
            complete=len(results) == 3 and all(item.complete and item.ok is True for item in results),
            authorization=authorization,
        )
        evidence_path = record_evidence(document, repository_root=repository_root)
    result = results[-1]
    wda = runner.environment.get("wda")
    teardown_ok = not isinstance(wda, Mapping) or wda.get("teardown_complete") is True
    return {
        "ok": len(results) == 3 and all(item.ok is True for item in results) and teardown_ok,
        "uncertain": any(item.uncertain for item in results), "candidates": candidates,
        "observations": observations, "evidence_path": evidence_path, "result": result,
    }


__all__ = [
    "discover_direct_routes", "discover_physical_selectors", "discover_selectors",
    "plan_selector_discovery", "selector_observations",
]
