# Integration maintenance

Maintainers change the public command surface only through a reviewed application package, shared-core boundary, tests, and operator documentation. Maps is the first v2 URL-policy package; seven route families are proven for its exact profile, while navigation and report-a-problem remain explicit candidates. Legacy generated/local-content display compatibility, browser tab control, and arbitrary app automation remain outside current semantic integration work.

## Application package contract

Each of the 15 applications named by `integrations/index.json`, 14 core plus optional Brave, owns `__init__.py`, `commands.py`, `integration.json`, `SKILL.md`, `WORKFLOWS.md`, and offline tests under `integrations/<app>/`. Mail is unsupported and has no indexed package. This document governs contribution workflow outside the application packages. Generated documentation uses another path and never overwrites an app's `WORKFLOWS.md`.

`commands.py` is trusted repository code and owns application-specific argument normalization and command selection. Shared validation, configuration, registry loading, unlock gates, dispatch, transports, and result projection stay under `ipad_agent/`. Manifests and URL policies are inert policy authority: they may constrain an adapter or the lab, but they do not enlarge the public Python surface.

Each application `SKILL.md` names one application, documents only its current public wrapper commands, and uses bare one-call examples. It remains colocated source material rather than an independently installed Pi skill. `package.json` declares only `skills/use-ipad`; that gateway resolves the requested app and reads its skill on demand. App-local tests prove wrapper forwarding, the explicit command surface, and skill alignment without contacting a device. Cross-application and shared-core contracts stay in `tests/`. Read [`lessons.md`](lessons.md) when transport, evidence, privacy, cleanup, or stale-state failures affect maintenance.

## Maintenance order

Use this order for integration work:

1. define or amend the safety boundary;
2. validate it and inspect a static plan;
3. add adapter or workflow details only when needed;
4. gather bounded evidence with explicit authorization;
5. publish only a redacted projection and run the release gate.

A declared capability defines a testing ceiling; it is not proof that the route works. Candidate helpers either return sealed plans or reject without dispatch. A direct route is preferred to selectors. Settings and current Maps handling are CoreDevice-only; no current semantic app integration starts WDA or Appium. Optional WDA infrastructure remains dormant for maintenance and possible future selector integrations. A response lost after a transient action is uncertain and must not be replayed.

## Production URL policies

The production registry reads only integrations named by `integrations/index.json`. A trusted app-local adapter asks it to load `url-policy.json` beside an active manifest. A disabled addon remains index metadata until configuration enables it; neither its manifest nor its policy is opened.

Use `schemas/url-policy-v1.json` only for the existing Safari and Brave scheme policies. New endpoint-aware integrations use the reusable `schemas/url-policy-v2.json`. A v2 policy declares:

- one exact indexed target bundle;
- one canonical command for each launch or `open-url` action, plus explicit aliases;
- positional and keyword argument binding from raw Python values;
- canonical lowercase schemes and authorities: HTTP(S) needs a strict multi-label DNS host and absolute path; non-HTTP schemes may use a safe single-label authority and an empty path (for example `shortcuts://run-shortcut?...`);
- exact-link actions with the manifest value `{url}` and explicit canonical build commands;
- ordered query fields, types, enum values, and repeated fields;
- endpoint dependencies and exclusion rules;
- a UTF-8 byte limit no greater than 2,048.

The parser rejects unknown fields at every policy level. It also rejects duplicate normalized commands, aliases, parameter names, query keys, missing action coverage, bundle drift, credentials, ports, fragments, malformed escapes, controls, and noncanonical completed URLs. Do not put caller-encoded placeholders in a v2 manifest. The policy builder encodes raw values once.

A thin semantic wrapper may add Python conveniences such as underscore keyword aliases or a latitude/longitude tuple. It must pass those raw values to `IntegrationRegistry.resolve_url_route`. Only `ValidatedURLRoute` may cross `open_validated_route_when_unlocked`. Keep the full URL out of public result evidence; report the integration, action, URL shape, and policy digest.

Production dispatch selects one manifest action. It never executes a scenario. A scenario can contain several actions for lab work and must not become a production shortcut.

Maps statically covers every documented Unified URL family. For `iPad17,1` / `J817AP` / iPadOS `26.6.1` (`23G83`), its compatibility authority marks frame, search/show, place, Look Around, directions preview, guides, and validated links as proven. Navigation start and report-a-problem remain explicit candidates and production rejects them before dispatch; ordinary `ipadmaps("open")` remains available. Static validation, plan construction, fake execution, or CoreDevice dispatch is not user-visible rendering proof.

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
python3 -m ipad_agent.lab validate integrations/example-app/integration.json --json
```

Build a scenario plan without contacting the iPad:

```python
from ipad_agent.lab import plan_scenario

plan = plan_scenario(
    "integrations/example-app/integration.json",
    "search",
    parameters={"query": "bounded test value"},
)
plan.to_dict()
```

The lab ceiling is transient. Persistent, destructive, payment, account/security, and protected-confirmation work is excluded. Observation can repeat safely. Typing, taps, URL delivery, clears, and swipes get one attempt unless the reviewed declaration proves idempotence.

Inspect declared direct routes or selectors from existing captured JSON without physical work:

```python
from ipad_agent.lab import discover_direct_routes, discover_selectors

discover_direct_routes("integrations/example-app/integration.json")
discover_selectors(source_json)
```

Retain a selector only after two unchanged-state inspections each produce one exact match with consistent path, type, label, and name context. Prefer accessibility identifiers, then bounded predicates.

## Fake execution

Exercise planning, operation contracts, stopping rules, batching, and evidence shape without contacting an iPad:

```python
from ipad_agent.lab import run_fake_scenario

run = run_fake_scenario(
    "integrations/example-app/integration.json",
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
    "integrations/example-app/integration.json",
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

Authorization binds a cryptographically random identifier, the integration data, plan, parameters, safety ceiling, expiry of at most 15 minutes, and run count. One canonical checkout-owned receipt store consumes the grant before dispatch, regardless of any separate evidence output root, making it single-use across objects, serialized copies, threads, and processes. Physical execution also requires the literal `physical=True`; a general approval, candidate flag, or old authorization cannot substitute for the exact short-lived grant. For v2 URL actions, planning invokes the production policy builder on raw scenario parameters and stores the serialized `ValidatedURLRoute` in the plan; physical execution reconstructs it and revalidates it against the active indexed policy and exact bundle immediately before dispatch. Safari and Brave retain the legacy v1 plan shape. Direct CoreDevice work runs first. An explicitly authorized maintenance selector scenario may use one bounded optional WDA session with teardown evidence; current semantic app integrations do not. Preserve user files, tabs, and app state.

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

Physical evidence is complete only when every planned step succeeds with a certain result, the environment fields are present, and WDA teardown is proven when optional WDA maintenance ran. CoreDevice raw discovery output, raw responses, UI source, URLs, paths, identifiers, tokens, and authorization text stay private. Screenshots are confined to owner-private `.runtime/artifacts/`, written atomically, and removed when the evidence procedure no longer needs them.

App `route-compatibility.json` sidecars are release-validated metadata attestations for exact non-unique profiles. They may contain only the allowlisted route status, method, outcome, and proof scope. Because screenshots and raw physical evidence remain private, a sidecar is not independently reproducible proof. It cannot support a broader app version, OS build, file format, route variant, content-fidelity claim, Files ownership claim, or Photos `show` claim.

Generate a projection from the reviewed integration data, never over an existing `WORKFLOWS.md`:

```bash
python3 -m ipad_agent.lab docs integrations/example-app/integration.json \
  --output docs/integrations/example-app.md --json
python3 -m ipad_agent.lab docs integrations/example-app/integration.json \
  --output docs/integrations/example-app.md --apply --json
python3 -m ipad_agent.lab docs integrations/example-app/integration.json \
  --output docs/integrations/example-app.md --check --json
```

The final completion report must remain false until static validation, safe plans, fake evidence, required physical evidence, stable benchmark evidence, the bound redacted projection, current generated docs, and teardown invariants all pass.

## Maintainer checks

```bash
python3 -m ipad_agent.lab validate integrations/safari/integration.json --json
python3 scripts/release_check.py
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 -m unittest discover -s integrations -t . -p 'test_*.py' -v
python3 -m compileall -q ipad_agent integrations tests scripts
```

Physical scenarios never run in unattended tests or CI. Complete the fresh-clone release gate in the README's [Development](../../README.md#development) section before release.
