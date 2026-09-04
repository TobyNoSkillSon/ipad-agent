# Dependencies

iPad Agent runs directly from a macOS checkout. Its Python runtime uses the standard library. There is no pip installation step, and Python commands must run from the repository root.

## Core routes

App launches, admitted deep links, Maps routes, Settings destinations, and App Store or Books products require:

| Component | Requirement | Installed by this project? |
|---|---|---:|
| macOS | Required for Xcode CoreDevice | No |
| Full Xcode | Supplies `xcrun devicectl` and physical-device support | No |
| Python | 3.11 or newer | No |
| Physical iPad | Paired with and trusted by the Mac | No |

Xcode, Apple SDKs, Apple accounts, credentials, certificates, and provisioning profiles are never downloaded or redistributed by this project. A person completes trust, unlock, account, signing, and protected-confirmation steps.

## Pi package

Pi is optional for direct Python use. To make the iPad instructions available to Pi, run this from the checkout root:

```bash
pi install "$PWD"
```

This registers the local Pi package. It does not install Python, copy `ipad_agent` into site-packages, or remove the requirement to run Python from the checkout root.

`package.json` exposes only `skills/use-ipad`. The gateway resolves one of the 15 indexed application packages, 14 core plus optional Brave, then reads that package's local `SKILL.md` on demand. App-local skills are not independently installed. Mail is unsupported and not indexed. The Pi package has no npm dependencies, generated composite skill, or alternate skill source.

## AirDrop route

The AirDrop backend builds `native/airdrop-share/AirDropShare.swift` into project-owned `.runtime/native/` using Xcode's Swift toolchain. It uses `NSSSharingService` and downloads no Swift package.

Private configuration must define narrow, current-user-owned allowed roots that are not writable by group or other users, plus allowed extensions and a maximum size. Do not configure broad shared, aggregate, or cloud-synchronised roots. The macOS picker or same-Apple-Account behaviour determines the receiver; a person can select it only when a picker appears. Host completion does not prove target receipt. See [`SECURITY.md`](SECURITY.md) for snapshot, redaction, and uncertainty rules.

## Optional applications

Brave must already be installed on the iPad and enabled in `.runtime/config/config.toml`. The project does not install App Store applications or manage application accounts. Brave website and search are proven on the recorded profile; private browsing remains a candidate, and IPFS/IPNS are incompatible there.

## Dormant WDA infrastructure

Current semantic app integrations do not invoke WDA or Appium. Settings and Maps are CoreDevice-only. The dormant maintenance path requires:

| Component | Current project version or requirement |
|---|---|
| Developer Mode | Enabled manually on the iPad |
| Apple Development signing | Local identity and provisioning |
| Node.js/npm | npm 10 or newer and a compatible Node.js release |
| Appium | 3.7.0, installed under `.runtime/node` |
| Appium XCUITest Driver | 12.8.2, installed under `.runtime/appium-home` |
| WebDriverAgent | Supplied by the XCUITest driver, built and signed locally |

The project does not vendor or fork Appium, the XCUITest driver, or WDA. The explicit host setup phase downloads the pinned npm packages and may execute their lifecycle or installation code as the current Mac user; version pinning alone is not an integrity guarantee. Review the intended npm registry, versions, and provenance before approving that phase.

Builds, provenance, verification receipts, and server state remain under `.runtime/`. Setup stops at Apple trust, Developer Mode, account, keychain, signing, and provisioning gates for a person to complete. Successful bounded verification stops its owned Appium server, but failed or private sessions may require explicit cleanup.

See [`README.md`](README.md#default-installation-coredevice-only) for ordered setup, [`SECURITY.md`](SECURITY.md) for trust boundaries, and [`THIRD_PARTY.md`](THIRD_PARTY.md) for external licences and terms.
