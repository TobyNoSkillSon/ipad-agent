# iPad Agent contributor instructions

Use this workflow for every review or change in the repository. Load only the references required by the task.

## Workflow

1. Classify the request and load its authoritative references:
   - Public commands, result meanings, setup, cleanup, or release work: read [`README.md`](README.md).
   - Device mutation, AirDrop, WDA, sensitive state, or physical evidence: read [`SECURITY.md`](SECURITY.md).
   - Dependencies and installation ownership: read [`DEPENDENCIES.md`](DEPENDENCIES.md).
   - Configuration behavior: inspect [`config.example.toml`](config.example.toml) and the owning code in `ipad_agent/`.
   - App integration work: read [`docs/integrations/authoring.md`](docs/integrations/authoring.md), [`ROADMAP.md`](ROADMAP.md), and the affected integration's `WORKFLOWS.md` when present.

   Complete this step when every affected branch has an authoritative reference.

2. Inspect the implementation and tests that own the behavior before editing.

   Complete this step when you have identified the source of truth, callers, and relevant tests.

3. Make the smallest scoped change. Preserve semantic one-call operation, CoreDevice-first routing, evidence boundaries, and human control over protected actions.

   Complete this step when the requested behavior works without unrelated changes or an undocumented expansion of the public API.

4. Run the narrowest relevant tests first. For release work, run the complete release gate in the README. Physical-device work requires explicit authorization for the exact action and must follow the security and integration evidence rules.

   Complete this step when the required checks pass or each unresolved failure has concrete evidence.

5. Update only the authoritative documentation. Link to command help, schemas, configuration, or integration documentation instead of copying volatile values into this file.

   Complete this step when each changed meaning has one source of truth.

6. Report changed files, checks, residual uncertainty, and any required human action.

## Invariants

- Prefer a documented CoreDevice launch or deep link over UI automation.
- Dispatch each mutation once. A lost response is uncertain, not permission to retry.
- CoreDevice acceptance does not prove rendered visibility.
- AirDrop host completion does not prove recipient selection, receipt, or file opening.
- Keep credentials, device identifiers, signing values, tokens, logs, generated artifacts, and physical evidence under `.runtime/` and out of Git.
- Never automate passcodes, biometrics, Apple Account authentication, signing approval, purchases, or protected confirmations.
- CI and unattended tests must not contact or mutate a physical device.
