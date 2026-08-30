# Dependencies

iPad Agent runs directly from a macOS checkout. Its Python runtime uses the standard library, so there is no pip installation step.

## Core routes

App launches, deep links, Maps, and App Store destinations require:

| Component | Requirement | Installed by this project? |
|---|---|---:|
| macOS | Required for Xcode CoreDevice | No |
| Full Xcode | Supplies `xcrun devicectl` and physical-device support | No |
| Python | 3.11 or newer | No |
| Physical iPad | Paired with and trusted by the Mac | No |

Xcode, Apple SDKs, Apple accounts, credentials, certificates, and provisioning profiles are never downloaded or redistributed by this project.

## AirDrop route

The AirDrop backend builds `native/airdrop-share/AirDropShare.swift` into project-owned `.runtime/native/` using the Swift toolchain supplied by Xcode. It uses `NSSSharingService` and downloads no Swift package.

The operator selects the recipient in the macOS AirDrop picker. Host completion does not prove target receipt.

## Optional Settings automation

Settings subsection navigation additionally requires:

| Component | Current project version or requirement |
|---|---|
| Developer Mode | Enabled manually on the iPad |
| Apple Development signing | Local identity and provisioning |
| Node.js/npm | npm 10 or newer and a compatible Node.js release |
| Appium | 3.7.0, installed under `.runtime/node` |
| Appium XCUITest Driver | 12.8.2, installed under `.runtime/appium-home` |
| WebDriverAgent | Supplied by the XCUITest driver, built and signed locally |

The project does not vendor or fork Appium, the XCUITest driver, or WebDriverAgent. WDA builds, provenance, verification receipts, and server state remain under `.runtime/`.

## Optional applications

Brave must already be installed on the iPad and enabled in private runtime configuration. Other app integrations may have their own installation and account requirements; the project does not install App Store applications or manage user accounts.

See [`README.md`](README.md) for setup commands, [`SECURITY.md`](SECURITY.md) for trust boundaries, and [`THIRD_PARTY.md`](THIRD_PARTY.md) for external licences and terms.
