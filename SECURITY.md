# Security policy

## What this changes on the iPad

Ordinary iPad Agent commands do not jailbreak the iPad, disable its passcode, bypass Apple’s sandbox, install configuration profiles, expose a network listener on the iPad, or automate protected confirmations. The project does not call CoreDevice operations for pairing, unpairing, installing or uninstalling apps, rebooting, erasing, copying device files, or terminating arbitrary processes.

The ordinary production path can:

- inspect the paired-device list, installed-app inventory, and lock state;
- launch an installed app, sometimes with a policy-validated URL;
- terminate and relaunch Maps to avoid stale foreground state;
- offer one allowlisted Mac file through AirDrop; and
- leave normal app state behind, including browser history or tabs, opened routes, and imported files.

The larger security decisions happen before those commands run:

- **Trust This Computer persists.** Apple says a trusted computer can sync with the device and access photos, videos, contacts, and other content. The trust remains until it is reset or the device is erased. See [Apple’s trust guidance](https://support.apple.com/en-us/109054).
- **Developer Mode reduces device security.** Apple describes it as permission for development-signed software and developer-only functionality, and explicitly says enabling it reduces device security. Turn it off in **Settings > Privacy & Security > Developer Mode**, then restart, when development access is no longer needed. Some iPad Agent or Xcode functions may stop working afterward. See [Apple’s Developer Mode documentation](https://developer.apple.com/documentation/Xcode/enabling-developer-mode-on-a-device).
- **Optional WDA control is powerful.** Private maintenance and legacy modules can use WebDriverAgent to inspect the visible UI, take screenshots, tap, swipe, clear fields, and type. No current semantic app integration uses those controls. Do not enable WDA for ordinary operation, and never run untrusted Python while WDA or Appium is available.

Installing the repository does not leave a remote iPad-control service open. Ordinary semantic calls do not start Appium, WDA, the legacy display server, or the legacy runtime daemon. Optional maintenance can start local services, and Apple trust or Developer Mode can remain after the process exits. The sections below state exactly what persists and how to close it.

The expected resting state is: no Appium process, no WDA session, no legacy daemon or display server, and no unresolved AirDrop snapshot. Keep WDA dormant. Leave Developer Mode enabled only while you knowingly need development access, and trust only a Mac and checkout you control.

## Trust model

Run only a checkout and integrations you trust. Repository-owned Python runs with the macOS account’s permissions. A malicious process running as the same Mac user can call CoreDevice or Appium directly, regardless of this project’s Python checks. `PhysicalAuthorization`, route policies, and candidate gates prevent mistakes in supported project paths; they are not an operating-system sandbox and cannot contain hostile local code.

Pi packages can instruct an agent to run local code. Review the checkout before `pi install`, and keep the installed package pointed at a checkout you control. Do not let pages, messages, downloaded files, or repository content grant device-action authority.

## Command and URL boundary

Use one documented semantic function call for each request. Public calls select the configured or sole paired iPad; callers do not supply a device identifier. Unknown commands, arguments, and URL fields fail before a transport runs.

Production applications use reviewed, repository-owned Python adapters beside inert manifests and policies. The integration index defines route authority. The runtime does not scan integration directories, execute manifest code, load third-party plugins, or run lab scenarios. Disabled addons remain unopened until private configuration enables them.

URL policies allowlist the exact scheme, authority, path, fields, target bundle, and length. They reject credentials, malformed escapes, controls, unknown fields, and invalid combinations. Exact Apple Maps and Google Maps links pass through the same policy as constructed routes. Ordinary production rejects `maps.apple` short links before network access. An explicitly authorized maintenance resolver may follow one redirect; its target must then pass the full `https://maps.apple.com` policy.

Opening a website still contacts that site and can create cookies, history, downloads, tracking exposure, or a phishing page. The project validates route shape, not the truth or safety of arbitrary web content.

Apple Maps `directions` stops at preview. `navigate` and `report-a-problem` remain gated; report stops at Apple’s sheet and never submits it. Google Maps navigation and Brave private browsing also remain gated. Messages admits blank composition only. Recipient-bearing Messages routes are outside V1, and Mail is unsupported.

Evidence status and dispatch authority are separate. A route may remain evidence-candidate while an older compatibility surface still admits it, as with Safari YouTube. Explicit candidate-gated routes do not gain dispatch authority from their metadata label.

CoreDevice acceptance proves dispatch only. It does not prove foreground state, rendering, navigation, or visibility. Validation, policy, and discovery may reject with certainty before launch. After the `devicectl launch` subprocess starts, a timeout, lost response, or nonzero exit is `uncertain` because delivery cannot be disproved. Inspect state once and do not repeat the action blindly.

Public CoreDevice results contain phase-based reasons and bounded route metadata, not raw stdout, stderr, commands, full URLs, or device identifiers. Raw discovery output remains private diagnostic state.

## Candidate and physical execution boundary

Candidate helpers either return a sealed lab plan or reject the request without dispatch. They do not grant permission to contact a device. Physical execution requires the exact reviewed plan, literal `physical=True`, and a `PhysicalAuthorization` bound to that plan, its parameters, safety ceiling, expiry, and run count. Grants expire within 15 minutes and carry a random identifier consumed atomically at one canonical checkout-owned receipt store before dispatch. Every physical step also consumes its own durable operation-and-attempt receipt before contacting a transport, so copying or forking a partially used executor cannot replay the remaining steps. Changing an evidence output root, copying or serializing the grant, or reusing it in another thread or process cannot restore authority.

The authorization object records a caller’s assertion; it does not prove that a person consented. Private lab support can represent low-level taps and typing without understanding whether the selected control is destructive. Current bundled scenarios contain only activation and URL-opening steps. A future UI-control scenario requires separate semantic review, exact human approval, and protected prompts left to the person.

Review one plan at a time. Execute it once and preserve an uncertain result without replay. Fake runs, static plans, and dispatch acceptance are not compatibility proof.

## AirDrop boundary

AirDrop accepts one canonical regular file under configured roots, extension allowlists, and a byte ceiling. Each root and file must be owned by the current Mac user, carry no extended ACL, and must not be writable by group or other users. A root cannot be `/`, `/Users`, or the user’s home directory. Use a dedicated narrow transfer directory. The validator rejects obvious aggregate roots, but it cannot infer whether a user-owned folder such as Documents or an iCloud directory is too broad. Do not configure shared, aggregate, or cloud-synchronised roots, and place only intentionally transferable files there.

The backend creates a private attempt snapshot and makes one bounded sharing attempt. `NSSSharingService` has no recipient argument. The macOS picker, or same-Apple-Account auto-accept behaviour, determines the receiver. A person can choose the recipient only when the picker appears. A callback does not prove recipient selection, receipt, import, or exact opening.

Public results remove attempt IDs, snapshot paths, raw command data, and cleanup details. An uncertain attempt intentionally retains an owner-private copy under `.runtime/`. The general WDA cleanup command does not delete that copy. Inspect the receiving state before considering another transfer, then remove the retained snapshot only after its uncertainty is resolved.

Representative evidence remains route-specific. Preview PDF, Books EPUB, Pages DOCX, Numbers XLSX, and Keynote PPTX `show` are proven only for the recorded receipt/import/open result. Files ZIP `drop` proves receipt and opening in the generic system preview, not Files ownership. Photos PNG `drop` proves persistent import and opening, not content fidelity. Files and Photos `show` remain unproven.

## WDA, Appium, and local control services

No semantic application adapter starts WDA or Appium. WDA requires an explicit maintenance setup, Developer Mode, local signing, and protected choices completed by a person.

The host setup phase downloads pinned Appium and XCUITest packages from npm into `.runtime/`. npm and driver installation can execute third-party package lifecycle or installation code as the current Mac user. Check the registry, versions, and provenance before approving this phase. Leave WDA blocked if that trust decision has not been made.

Appium uses loopback HTTP only, and the WDA client disables inherited HTTP proxies for that traffic. It has no application-level authentication, so loopback excludes remote network hosts but not other local processes or accounts. Before sending session metadata, the project requires the receipt-owned Appium PID to be the sole TCP listener on the configured loopback port and rejects an occupied or mismatched endpoint. A successful bounded verification now stops its owned Appium server before writing the verification receipt. A failed verification or a private runtime session may leave owned Appium state that requires explicit cleanup.

A WDA session deletes its Appium session and terminates receipt-owned WDA build descendants when teardown succeeds. This does not prove that iPadOS removed the development-signed WebDriverAgent runner from the device. The project does not automate removal of that app, Developer App trust, Developer Mode, pairing trust, signing certificates, or provisioning profiles.

The private legacy WDA API can tap, type, swipe, inspect UI source, and capture screenshots without `PhysicalAuthorization`. It exists for compatibility and is not part of the root semantic API. Treat it as manual maintenance code, never as an always-on service.

The legacy runtime daemon uses a checkout-bound owner-private Unix socket and nonce. It has no idle shutdown. Stop it explicitly when legacy work ends. The legacy display server uses plaintext HTTP on one configured RFC1918 address and can remain running until explicitly stopped. Each server start creates a new bearer token under `.runtime/display/token`; the token remains valid in memory until that server stops. Never expose or port-forward the server. If the token may have leaked, stop the server and confirm shutdown. Deleting the token file while the server runs does not revoke the in-memory token.

## Private runtime state

`.runtime/` is Git-ignored sensitive state. It may contain configuration, WDA/Appium products and receipts, AirDrop snapshots, logs, identifiers, URLs, screenshots, and raw lab evidence. Security-sensitive runtime paths validate current-user ownership, owner-only modes, symlink boundaries, and extended ACLs before reuse. Config, raw evidence, display credentials, screenshots, and transport state use those private path controls; unsafe pre-existing state fails closed. Screenshots are confined to `.runtime/artifacts/` and written atomically.

Raw physical evidence stays under `.runtime/lab/`. App `route-compatibility.json` sidecars contain release-validated metadata attestations only. They omit screenshots, raw responses, private routes, and unique identifiers. Empty, failed, conflicting, or incomplete evidence cannot support a compatibility claim.

## Stop and decommission

For ordinary app and URL routes, no project server needs shutdown. Close browser tabs, remove imported files, or restore app state manually if those effects matter.

After legacy work, stop both optional local services from the checkout root:

```python
from ipad_agent.legacy import ipad, show
print(show("x"))  # legacy LAN display server
print(ipad("x"))  # legacy Unix-socket runtime daemon
```

Plan WDA cleanup before applying it:

```bash
python3 -m ipad_agent cleanup --json
python3 -m ipad_agent cleanup --apply --json
```

Applied cleanup first stops the receipt-owned Appium server. A pre-spawn marker also blocks artifact removal if Appium started but its ownership receipt could not be completed; without a receipt, cleanup checks for that marker, the configured listener, and a repository-local Appium process. If absence or shutdown cannot be proved, cleanup returns failure and leaves WDA artifacts in place. It then removes only ownership-metadata-matching project WDA build artifacts and matching verification receipts. It does not remove npm packages, configuration, AirDrop recovery snapshots, legacy display state, the WDA runner from the iPad, Developer Mode, pairing trust, developer certificates, or profiles. A later artifact-removal error can still leave partial cleanup, so inspect the result rather than assuming rollback.

For a full manual decommission:

1. Stop the legacy daemon and display server. Confirm their results report `stopped: true` or that no owned server exists. If the display token may have leaked, remove `.runtime/display/token` only after that confirmation.
2. Apply owned WDA cleanup and resolve any uncertain AirDrop attempt. Then review and remove the checkout’s `.runtime/` data if it is no longer needed.
3. Remove any development-signed WDA runner from the iPad if present.
4. Turn off Developer Mode and restart the iPad if development access is no longer required.
5. If the Mac should no longer be trusted, use **Settings > General > Transfer or Reset iPad > Reset > Reset Location & Privacy**. Apple notes that this resets trust for previously trusted computers and also resets other location and privacy settings.
6. Review development certificates, provisioning profiles, and Apple account access separately if the Mac or signing identity is no longer trusted.
7. Remove the local Pi package registration with `pi remove "$PWD"`, then verify that the checkout no longer appears in `pi list` before moving or deleting it.

Do not automate those iPad, account, or certificate decisions. They can affect other development work and privacy settings.

## Human-only gates

A person handles Trust This Computer, Xcode licence and first launch, Developer Mode and restart confirmation, device unlock, Apple Account and 2FA, signing, provisioning, device registration, keychain approval, Developer App trust, biometrics, passcodes, payments, account changes, and protected confirmations. The project does not need, collect, or accept those credentials or approvals.

## Reporting a vulnerability

Use **Report a vulnerability** on the repository’s GitHub **Security** tab when private vulnerability reporting is available. Include affected versions, impact, reproduction steps, and a proposed mitigation. Remove credentials, passcodes, personal data, private URLs, signing identifiers, and device identifiers.

If private reporting is unavailable, open a minimal public issue asking for a private channel. Do not include exploit details or sensitive evidence in that issue.
