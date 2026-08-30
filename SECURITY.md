# Security policy

## V1 command boundary

Use one documented semantic function call for each request. The allowlisted command surface limits destinations and argument forms before CoreDevice, AirDrop, or WDA runs. Generated Now content, browser tab control or cleanup, Maps directions, and other app automation are outside V1.

CoreDevice launch or URL acceptance proves dispatch only. It does not prove that an app is foreground, a page rendered, or a destination became visible. If a response is lost after dispatch, the result is uncertain: inspect state once and do not repeat the mutation blindly.

Settings allowlisted navigation uses one hidden WDA session and tears it down after the call. Keep Appium on loopback HTTP (`127.0.0.1`, `localhost`, or `::1`); never expose or proxy it to a LAN or the internet.

## AirDrop boundary

AirDrop is the preferred transport for local files. Configure explicit allowed roots, extensions, and a maximum byte count. The backend validates a canonical regular file, creates a private attempt snapshot, and makes one bounded sharing attempt.

V1 has no recipient-selection implementation. The macOS picker or same-Apple-Account auto-accept determines the receiver. A completed sharing callback is not proof of target selection or receipt. Opening Preview, Books, or Files after transfer is not proof that the exact file appeared there. Keep those claims unverified until live evidence establishes them.

A file around 2 GB may normally take an estimated 40–100 seconds, but this is not a security timeout or performance guarantee. Benchmark the actual setup. After a dispatched timeout or lost callback, retain the uncertain result and do not send again without inspecting the receiving state.

## Local trust boundaries

Run only a repository and integrations you trust. Declarative integration data can direct local device control, and executable addon code runs with the local macOS account's permissions.

`.runtime/` is project-owned, Git-ignored sensitive state. It may contain configuration, WDA/Appium products and receipts, AirDrop attempt snapshots, logs, display tokens, identifiers, URLs, and private lab evidence. Keep it out of commits and reports. Restrict local configuration and tokens to the current user.

The display service uses plain HTTP on one reachable private IPv4 address. Use it only on a trusted private LAN. Do not port-forward it, bind it publicly, or expose its URLs or short-lived tokens.

A person handles Trust This Computer, Xcode licence and first launch, Developer Mode and restart confirmation, device unlock, Apple Account/2FA, signing, provisioning, device registration, keychain approval, Developer App trust, biometrics, passcodes, payments, account changes, and protected confirmations. The project does not need, collect, or accept those credentials or approvals.

Physical lab evidence remains private under `.runtime/lab/`. Only the allowlisted, redacted `compatibility-v1.json` projection may enter release content. Empty, failed, or incomplete evidence is not compatibility proof.

## Reporting a vulnerability

Use **Report a vulnerability** on the repository's GitHub **Security** tab when private vulnerability reporting is available. Include affected versions, impact, reproduction steps, and a proposed mitigation. Remove credentials, passcodes, personal data, private URLs, signing identifiers, and device identifiers.

If private reporting is unavailable, open a minimal public issue asking the maintainer for a private channel. Do not include exploit details or sensitive evidence in that issue.
