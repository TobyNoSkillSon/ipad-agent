# iPad Agent contributor instructions

Use this workflow for every review or change in the repository. Load only the references required by the task.

## Workflow

1. Classify the request and load its authority:
   - Installation or operator setup: follow [`README.md#default-installation-coredevice-only`](README.md#default-installation-coredevice-only), then read [`SECURITY.md`](SECURITY.md) and [`DEPENDENCIES.md`](DEPENDENCIES.md). Stop at human trust, unlock, account, signing, and protected-confirmation gates. A live test needs separate approval for the exact action.
   - Public commands, results, cleanup, or release work: read [`README.md`](README.md).
   - Device mutation, AirDrop, WDA, sensitive state, or physical evidence: read [`SECURITY.md`](SECURITY.md).
   - Dependencies and installation ownership: read [`DEPENDENCIES.md`](DEPENDENCIES.md).
   - Configuration behavior: inspect [`config.example.toml`](config.example.toml) and the owning code under `ipad_agent/`.
   - App integration or skill work: read [`docs/integrations/authoring.md`](docs/integrations/authoring.md), [`ROADMAP.md`](ROADMAP.md), and the affected app's `WORKFLOWS.md` and `SKILL.md`.

   Complete this step when every affected branch has an authoritative reference.

2. Inspect the implementation and tests that own the behavior before editing.

   Complete this step when the source of truth, callers, and relevant tests are identified.

3. Make the smallest scoped change. Preserve one-call semantics, CoreDevice-first routing, evidence boundaries, and human control over protected actions.

   Complete this step when the request works without unrelated changes or an undocumented public API expansion.

4. Run the narrowest relevant tests first. For release work, run the complete release gate in the README. Physical-device work requires explicit authorization for the exact action and must follow the security and evidence rules.

   Complete this step when required checks pass or every unresolved failure has concrete evidence.

5. Update only authoritative documentation. Link to command help, schemas, configuration, or integration docs instead of caching volatile details here.

   Complete this step when each changed meaning has one source of truth.

6. Report changed files, checks, residual uncertainty, and required human action.

## Invariants

- Prefer a documented CoreDevice launch or deep link over UI automation.
- Settings and current Maps handling are CoreDevice-only. No current semantic app integration starts WDA or Appium; optional WDA infrastructure stays dormant for maintenance and possible future selector integrations.
- Candidate helpers return sealed lab plans or reject without dispatch. Physical execution requires the exact plan, literal `physical=True`, and a short-lived plan-bound authorization. Dispatch each mutation once; a lost response is uncertain and is never permission to retry.
- Apple Maps proves seven Unified URL families for `iPad17,1` / `J817AP` / iPadOS `26.6.1` (`23G83`): frame, search/show, place, Look Around, directions preview, guides, and validated links. Navigation and report remain candidates. Ordinary `ipadmaps("open")` remains available.
- Google Maps proves open, search, map, directions preview, Street View, and canonical links for the same exact profile. `navigate` remains a candidate.
- Brave website and search are proven. Private browsing remains a candidate; IPFS/IPNS are incompatible on the recorded profile.
- Representative file proof is limited to Preview PDF `show`, Books EPUB `show`, Pages DOCX `show`, Numbers XLSX `show`, Keynote PPTX `show`, Files ZIP `drop`, and Photos PNG `drop`. The office routes do not prove general content fidelity. Files ZIP proves generic system-preview receipt, not Files ownership. Photos PNG proves persistent import/open, not content fidelity. Files and Photos `show` remain unproven.
- Messages admits blank compose only. Recipient-bearing routes remain outside V1, and the integration cannot send. Mail is unsupported and not indexed.
- CoreDevice acceptance does not prove rendering. Discovery and pre-dispatch rejection are certain; a timeout or nonzero result after launch subprocess start is uncertain. Public output never copies raw CoreDevice discovery, stdout, or stderr.
- AirDrop host completion does not prove recipient selection, receipt, import, or opening. Public AirDrop output removes attempt IDs and private recovery paths. A person chooses the recipient.
- Keep configuration, identifiers, signing data, tokens, logs, screenshots, generated artifacts, and raw physical evidence under `.runtime/`. Screenshots stay in owner-private `.runtime/artifacts/` and use atomic writes.
- The runtime socket uses a bounded owner-private checkout-specific endpoint under `/tmp`; ownership metadata stays under `.runtime/state/`.
- App `route-compatibility.json` sidecars are release-validated metadata attestations, not independently reproducible physical proof. Raw evidence remains private.
- A person enters credentials and handles Apple trust, unlock, signing, account, purchase, and protected-confirmation gates.
- CI and unattended tests do not contact or mutate a physical device.
- The index contains 15 app packages: 14 core plus optional Brave. Each owns its adapter, inert manifest/policy authority, local `SKILL.md`, and offline tests under `integrations/<app>/`; shared routing and transports remain under `ipad_agent/`.
- `package.json` exposes only `skills/use-ipad`. That gateway resolves the requested app through `integrations/index.json` and reads its local skill on demand. Pi package installation does not install Python; run Python from the repository root without pip installation.
