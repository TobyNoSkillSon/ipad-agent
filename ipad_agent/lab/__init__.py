"""Repository-native integration optimizer and evidence lab.

Static authoring is also available through ``python3 -m ipad_agent.lab``.
Physical execution and discovery are deliberately available only from Python
and require the literal keyword argument ``physical=True``.
"""
from .benchmark import benchmark, benchmark_scenario
from .discovery import (
    discover_direct_routes, discover_physical_selectors, discover_selectors,
    plan_selector_discovery, selector_observations,
)
from .docs import check_integration_docs, generate_integration_docs, integration_docs
from .evidence import compatibility_summary, private_evidence_root, record_evidence, write_compatibility_summary
from .gates import check_completion, completion_report, write_completion_report
from .model import BenchmarkControlPlan, LabRun, PhysicalAuthorization, PlannedStep, ScenarioPlan
from .planning import MAX_PHYSICAL_SAFETY, plan_scenario
from .runner import FakeExecutor, PhysicalExecutor, run_fake_scenario, run_physical_scenario
from .scaffold import scaffold_integration
from .validation import LabValidationError, validate_compatibility, validate_evidence, validate_manifest

__all__ = [
    "BenchmarkControlPlan", "FakeExecutor", "LabRun", "LabValidationError", "MAX_PHYSICAL_SAFETY", "PhysicalAuthorization",
    "PhysicalExecutor", "PlannedStep", "ScenarioPlan", "benchmark", "benchmark_scenario", "check_completion",
    "check_integration_docs", "compatibility_summary", "completion_report", "discover_direct_routes",
    "discover_physical_selectors", "discover_selectors", "generate_integration_docs", "integration_docs",
    "plan_scenario", "plan_selector_discovery", "private_evidence_root", "record_evidence",
    "run_fake_scenario", "run_physical_scenario", "scaffold_integration", "selector_observations",
    "validate_compatibility", "validate_evidence", "validate_manifest",
    "write_compatibility_summary", "write_completion_report",
]
