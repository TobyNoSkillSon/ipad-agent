# Integration maintenance

This is a maintainer-only branch. It does not extend the corrected V1 operator surface in [`README.md`](../../README.md#command-surface). Generated Now content, tab control or cleanup, directions, and arbitrary app automation remain outside V1 unless the public scope is reviewed and changed separately.

Existing app `WORKFLOWS.md` files are hand-maintained evidence. Keep them intact. Generated documentation must use another path.

## Maintenance order

Use this order for integration work:

1. define or amend the safety boundary;
2. validate it and inspect a static plan;
3. add adapter or workflow details only when needed;
4. gather bounded evidence with explicit authorization;
5. publish only a redacted projection and run the release gate.

A declared capability is permission to test within its ceiling, not proof that it works. A direct route is preferred to selectors. A response lost after a transient action is uncertain and must not be replayed.

## Static work

Scaffolding previews by default and refuses to overwrite files:

```bash
python3 -m ipad_agent.lab scaffold example-app \
  --name "Example App" --kind addon --bundle-id com.example.app --json

python3 -m ipad_agent.lab scaffold example-app \
  --name "Example App" --kind addon --bundle-id com.example.app --apply --json
```

Review every placeholder and add any index entry as a separate reviewed change. Validate before writing adapter code:

```bash
python3 -m ipad_agent.lab validate addons/example-app/integration.json --json
```

Build a scenario plan without contacting the iPad:

```python
from ipad_agent.lab import plan_scenario

plan = plan_scenario(
    "addons/example-app/integration.json",
    "search",
    parameters={"query": "bounded test value"},
)
plan.to_dict()
```

The lab ceiling is transient. Persistent, destructive, payment, account/security, and protected-confirmation work is excluded. Observation can repeat safely. Typing, taps, URL delivery, clears, and swipes get one attempt unless the reviewed declaration proves idempotence.

Inspect declared direct routes or selectors from existing captured JSON without physical work:

```python
from ipad_agent.lab import discover_direct_routes, discover_selectors

discover_direct_routes("addons/example-app/integration.json")
discover_selectors(source_json)
```

Retain a selector only after two unchanged-state inspections each produce one exact match with consistent path, type, label, and name context. Prefer accessibility identifiers, then bounded predicates.

## Fake execution

Exercise planning, operation contracts, stopping rules, batching, and evidence shape without contacting an iPad:

```python
from ipad_agent.lab import run_fake_scenario

run = run_fake_scenario(
    "addons/example-app/integration.json",
    "search",
    parameters={"query": "bounded test value"},
)
assert run.ok and not run.uncertain
```

Fake success verifies the harness path, not physical compatibility.

## Authorized physical evidence

Physical discovery and scenario execution require a reviewed plan, short-lived plan-bound authorization, and the literal `physical=True`:

```python
from datetime import datetime, timedelta, timezone
from ipad_agent.lab import PhysicalAuthorization, plan_scenario, run_physical_scenario

plan = plan_scenario(
    "addons/example-app/integration.json",
    "search",
    parameters={"query": "bounded test value"},
)
# Review plan.to_dict() before creating authorization.
now = datetime.now(timezone.utc)
authorization = PhysicalAuthorization.for_plan(
    plan,
    actor="reviewer",
    request="Run the displayed plan once with the displayed parameters",
    authorized_at=now.isoformat(),
    expires_at=(now + timedelta(minutes=15)).isoformat(),
    run_count=1,
)
run = run_physical_scenario(
    plan,
    physical=True,
    authorization=authorization,
    safety_ceiling=plan.safety_ceiling,
)
assert run.ok and not run.uncertain
```

Authorization binds the integration data, plan, parameters, safety ceiling, expiry, and run count. Direct CoreDevice work runs first. Selector work gets one bounded WDA session with teardown evidence. Preserve user files, tabs, and app state.

Physical selector discovery follows the same rule: inspect and review its plan first, create one bound authorization, and call `discover_physical_selectors(..., physical=True, authorization=authorization)`. A selector candidate is not compatibility proof.

## Benchmarks

Use fake benchmarks for harness regressions:

```python
from ipad_agent.lab import benchmark_scenario

fake = benchmark_scenario(plan, warmups=1, runs=5)
```

A physical benchmark needs explicit benchmark authorization, at least one warmup, at least three measured runs, and reviewed baseline, reset, and cleanup plans. Cleanup failure makes the benchmark incomplete. Physical benchmarks are capped at 20 measured runs.

AirDrop timing needs its own live benchmark. The operator guide's likely 40–100 second range for a file around 2 GB is an estimate, not compatibility evidence.

## Evidence and publication

Write raw evidence only below `.runtime/lab/` with owner-only permissions:

```python
from pathlib import Path
from ipad_agent.lab import write_compatibility_summary

evidence = sorted(Path(".runtime/lab/example-app").glob("*/evidence.json"))
write_compatibility_summary(evidence, output="compatibility-v1.json")
```

Physical evidence is complete only when every planned step succeeds with a certain result, the environment fields are present, and WDA teardown is proven when WDA ran. The committed projection may contain allowlisted IDs, statuses, metrics, OS/locale fields, physical flags, and SHA-256 evidence references. Keep raw responses, UI source, URLs, paths, identifiers, tokens, and authorization text private.

Generate a projection from the reviewed integration data, never over an existing `WORKFLOWS.md`:

```bash
python3 -m ipad_agent.lab docs addons/example-app/integration.json \
  --output docs/integrations/example-app.md --json
python3 -m ipad_agent.lab docs addons/example-app/integration.json \
  --output docs/integrations/example-app.md --apply --json
python3 -m ipad_agent.lab docs addons/example-app/integration.json \
  --output docs/integrations/example-app.md --check --json
```

The final completion report must remain false until static validation, safe plans, fake evidence, required physical evidence, stable benchmark evidence, the bound redacted projection, current generated docs, and teardown invariants all pass.

## Maintainer checks

```bash
python3 -m ipad_agent.lab validate integrations/safari/integration.json --json
python3 scripts/release_check.py
python3 -m unittest discover -s tests -p 'test_integration_lab_*.py' -v
python3 -m compileall -q ipad_agent/lab tests/test_integration_lab_*.py
```

Physical scenarios never run in unattended tests or CI. Complete the fresh-clone release gate in the README's [Release checks](../../README.md#release-checks) section before release.
