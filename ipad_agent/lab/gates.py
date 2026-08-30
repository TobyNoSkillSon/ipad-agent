"""Binary integration completion gates and report emission."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from .docs import generate_integration_docs
from .evidence import compatibility_summary, utc_now
from .planning import plan_scenario, verify_plan_safety
from .validation import (
    LabValidationError, manifest_digest, read_json_strict, validate_compatibility,
    validate_evidence, validate_manifest,
)


def completion_report(
    manifest: str | Path | Mapping[str, Any], *,
    evidence: Iterable[str | Path | Mapping[str, Any]] = (),
    compatibility: str | Path | Mapping[str, Any] | None = None,
    docs_path: str | Path | None = None,
    require_physical: bool = True,
    generated_at: str | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    evidence_items = list(evidence)
    try:
        value = validate_manifest(manifest)
        checks.append({"id": "manifest.strict", "passed": True, "detail": "strict structural and semantic validation passed"})
    except Exception as error:
        return _report(
            "unknown", [{"id": "manifest.strict", "passed": False, "detail": str(error)}],
            generated_at,
        )

    plans_ok = True; plan_detail = []; safety_results = []
    for scenario_id in value["scenarios"]:
        try:
            plan = plan_scenario(value, scenario_id, parameters=_placeholder_examples(value, scenario_id))
            safety_results.append(verify_plan_safety(plan))
            plan_detail.append(scenario_id)
        except Exception as error:
            plans_ok = False; plan_detail.append(f"{scenario_id}: {error}")
    checks.append({"id": "scenarios.planned", "passed": plans_ok, "detail": ", ".join(plan_detail)})

    current_manifest_digest = manifest_digest(value)
    documents = []
    evidence_digests: list[str] = []
    for item in evidence_items:
        try:
            document = validate_evidence(item if isinstance(item, Mapping) else read_json_strict(item))
            if (
                document["integration_id"] != value["id"]
                or document["binding"]["integration_id"] != value["id"]
                or document["binding"]["manifest_digest"] != current_manifest_digest
                or document["plan"]["manifest_digest"] != current_manifest_digest
            ):
                raise LabValidationError("evidence is not bound to the current integration ID and manifest digest")
            documents.append(document)
            evidence_digests.append(
                hashlib.sha256(Path(item).read_bytes()).hexdigest()
                if not isinstance(item, Mapping) else canonical_report_digest(document)
            )
        except Exception as error:
            checks.append({"id": "evidence.valid", "passed": False, "detail": str(error)})
            documents = []; evidence_digests = []; break
    if not any(item["id"] == "evidence.valid" for item in checks):
        checks.append({"id": "evidence.valid", "passed": bool(documents), "detail": f"{len(documents)} valid evidence document(s)"})
    scenario_ids = set(value["scenarios"])
    fake_pass = {
        item["scenario_id"] for item in documents
        if item["mode"] == "fake" and item["complete"] and item["outcomes"] and all(outcome.get("ok") is True for outcome in item["outcomes"])
    }
    checks.append({"id": "scenarios.fake", "passed": scenario_ids <= fake_pass, "detail": f"covered {sorted(fake_pass)}"})
    physical_pass = {
        item["scenario_id"] for item in documents
        if item["mode"] == "physical" and item["device"].get("source") == "CoreDevice"
        and item["device"].get("capture") == "device info details"
        and isinstance(item["device"].get("os_version"), str)
        and re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}(?:[-+][A-Za-z0-9.-]+)?", item["device"]["os_version"])
        and isinstance(item["device"].get("locale"), str)
        and re.fullmatch(r"[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})*", item["device"]["locale"])
        and item["complete"] and item["outcomes"] and all(outcome.get("ok") is True and outcome.get("uncertain") is not True for outcome in item["outcomes"])
    }
    checks.append({"id": "scenarios.physical", "passed": (not require_physical or scenario_ids <= physical_pass), "detail": "not required" if not require_physical else f"covered {sorted(physical_pass)}"})
    benchmark_pass = any(
        item["mode"] == "benchmark" and item["complete"]
        and (not require_physical or item["metrics"].get("physical") is True)
        and (
            not require_physical
            or (
                item["device"].get("source") == "CoreDevice"
                and item["device"].get("capture") == "device info details"
                and isinstance(item["device"].get("os_version"), str)
                and re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}(?:[-+][A-Za-z0-9.-]+)?", item["device"]["os_version"])
                and isinstance(item["device"].get("locale"), str)
                and re.fullmatch(r"[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})*", item["device"]["locale"])
            )
        )
        and item["metrics"].get("warmups", 0) >= 1
        and item["metrics"].get("runs", 0) >= 3
        and item["metrics"].get("completed_warmups") == item["metrics"].get("warmups")
        and item["metrics"].get("completed_runs") == item["metrics"].get("runs")
        and item["metrics"].get("successful_warmups") == item["metrics"].get("warmups")
        and item["metrics"].get("successful_runs") == item["metrics"].get("runs")
        and item["metrics"].get("uncertain_runs", 0) == 0
        and item["metrics"].get("hooks", {}).get("cleanup_ok") is True
        for item in documents
    )
    checks.append({"id": "benchmark.stable", "passed": benchmark_pass, "detail": "requires >=1 warmup, >=3 measured runs, all successful, none uncertain"})

    compat_value = None
    try:
        if compatibility is not None:
            compat_value = validate_compatibility(compatibility)
    except Exception:
        compat_value = None
    compat_ids = {item.get("id") for item in (compat_value or {}).get("integrations", []) if isinstance(item, Mapping)}
    compat_safe = False
    if compat_value is not None:
        try:
            expected_compatibility = compatibility_summary(
                evidence_items, generated_at=compat_value["generated_at"]
            )
            compat_safe = compat_value == expected_compatibility and value["id"] in compat_ids
        except Exception:
            compat_safe = False
    checks.append({
        "id": "compatibility.redacted", "passed": compat_safe,
        "detail": "summary exactly binds selected evidence digests, physical flag, OS/locale, and scenario statuses",
    })

    docs_ok = False
    if docs_path is not None:
        path = Path(docs_path)
        docs_ok = path.exists() and path.read_text(encoding="utf-8") == generate_integration_docs(value)
    checks.append({"id": "docs.current", "passed": docs_ok, "detail": "generated documentation exactly matches the manifest"})
    safety_ok = (
        plans_ok and len(safety_results) == len(value["scenarios"])
        and all(item.get("passed") is True and item.get("maximum_lab_ceiling") == "transient" for item in safety_results)
        and all(
            document["safety_gate"].get("passed") is True
            and document["safety_gate"].get("plan_digest") == document["plan"]["plan_digest"]
            for document in documents
        )
    )
    checks.append({
        "id": "safety.ceiling", "passed": safety_ok,
        "detail": f"executed {len(safety_results)} plan safety gate(s); evidence gates are plan-bound",
    })
    compatibility_digest = None if compat_value is None else canonical_report_digest(compat_value)
    return _report(
        value["id"], checks, generated_at, manifest_digest=current_manifest_digest,
        evidence_digests=evidence_digests, compatibility_digest=compatibility_digest,
    )


def _placeholder_examples(value: Mapping[str, Any], scenario_id: str) -> dict[str, str]:
    import re
    names: set[str] = set()
    for action_id in value["scenarios"][scenario_id]["actions"]:
        for step in value["actions"][action_id]["steps"]:
            for item in step.values():
                if isinstance(item, str): names.update(re.findall(r"\{([a-zA-Z][a-zA-Z0-9_]*)\}", item))
    return {name: f"example-{name}" for name in names}


def canonical_report_digest(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _report(
    integration_id: str, checks: list[dict[str, Any]], generated_at: str | None, *,
    manifest_digest: str | None = None, evidence_digests: list[str] | None = None,
    compatibility_digest: str | None = None,
) -> dict[str, Any]:
    return {
        "$schema": "schemas/lab-report-v1.json", "schema": "ipad-agent.lab-report/v1", "version": 1,
        "generated_at": generated_at or utc_now(), "integration_id": integration_id,
        "binding": {
            "integration_id": integration_id, "manifest_digest": manifest_digest,
            "evidence_sha256": sorted(evidence_digests or []),
            "compatibility_sha256": compatibility_digest,
        },
        "complete": bool(checks) and all(item["passed"] is True for item in checks), "checks": checks,
        "rule": "complete is true only when every listed gate passes",
    }


def write_completion_report(report: Mapping[str, Any], *, output: str | Path) -> Path:
    target = Path(output); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(report), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


check_completion = completion_report

__all__ = ["check_completion", "completion_report", "write_completion_report"]
