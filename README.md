# iPad Agent

[![CI](https://github.com/TobyNoSkillSon/ipad-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/TobyNoSkillSon/ipad-agent/actions/workflows/ci.yml)

Open installed apps, websites, proven Settings destinations, and supported content routes on a paired physical iPad with one Python call. Local-file routes use AirDrop.

Give the repository link to a coding agent on the Mac that will control the iPad:

```text
Install https://github.com/TobyNoSkillSon/ipad-agent on this Mac using the README's
“Default installation: CoreDevice only” instructions. Do not install or configure
Appium, WebDriverAgent, Node.js, npm packages, or Apple signing. Stop for every
human-only gate, and ask before the single Safari test.
```

The [default installation contract](#default-installation-coredevice-only) uses CoreDevice and installs no automation stack. Appium and WebDriverAgent have a separate, explicitly optional maintenance path.

```python
from ipad_agent import ipadmaps
ipadmaps("open")
```

iPad Agent is a macOS-only alpha. Current semantic integrations use Apple CoreDevice for launches and deep links; local files use AirDrop. Settings and Maps are CoreDevice-only. Optional WebDriverAgent (WDA) infrastructure remains dormant for maintenance and possible future selector integrations. The project is not affiliated with or endorsed by Apple Inc. iPad is an Apple trademark.

## Security in brief

Ordinary semantic commands do not jailbreak the iPad, disable its passcode, install apps or profiles, automate protected prompts, or start an iPad-control server. They can launch apps and URLs, create browser history or app state, and import files that remain on the device.

Pairing trust persists beyond one command. Developer Mode belongs to the optional WDA path; Apple states that enabling it reduces device security. WDA adds arbitrary UI inspection, screenshots, taps, swipes, and typing, so it stays dormant unless a person explicitly requests maintenance and accepts that risk. [`SECURITY.md`](SECURITY.md) explains the exact attack surface, shutdown procedure, and manual revocation steps.

## Routes and result scope

| Request | Primary route | What success proves |
|---|---|---|
| Open an installed app | CoreDevice | Launch request accepted |
| Open a website or app deep link | CoreDevice URL payload | URL dispatch accepted |
| Open a proven Settings destination | CoreDevice URL payload | Dispatch accepted for a profile-bound route |
| Open an App Store or Books product | CoreDevice URL payload | Product URL dispatch accepted |
| Transfer a local file | AirDrop | Mac-side sharing callback completed |

CoreDevice acceptance does not prove foreground state or rendering. Validation and discovery can reject a request with certainty before dispatch. Once a `devicectl launch` subprocess starts, a timeout or nonzero exit is conservatively `uncertain` because delivery cannot be disproved. Inspect state instead of replaying the action.

## Python commands

Run Python from the checkout root. Each function call performs one requested operation. Application adapters live under `integrations/<app>/`; shared validation, unlock gates, dispatch, transports, and result projection remain under `ipad_agent/`.

| Destination | Calls |
|---|---|
| Core | `ipadc("open", "Preview")` · `ipadc("drop", "/absolute/path/report.pdf")` · `ipadc("status")` |
| Preview | `ipadpreview("open")` · `ipadpreview("drop", path)` · `ipadpreview("show", path)` |
| Books | `ipadbooks("open")` · `ipadbooks("item", product)` · `ipadbooks("drop", path)` · `ipadbooks("show", path)` |
| Files | `ipadfiles("open")` · `ipadfiles("drop", path)` · `ipadfiles("show", path)` |
| Settings | `ipadsettings("open")` · `ipadsettings("general")` · `ipadsettings("about")` · `ipadsettings("wifi")` · `ipadsettings("bluetooth")` · `ipadsettings("battery")` · `ipadsettings("accessibility")` |
| Clock | `ipadclock("open")` |
| App Store | `ipadappstore("open")` · `ipadappstore("show", 123456789)` |
| Safari | `ipadsafari("website", url)` · `ipadsafari("youtube", url, at=90)` |
| Brave, optional | `ipadbrave("website", url)` · `ipadbrave("search", query)` · `ipadbrave("youtube", url, at=90)` |
| Apple Maps | `ipadmaps("open")` plus the proven map routes below |
| Google Maps | `ipadgooglemaps("search", query)` · `ipadgooglemaps("map", coordinate, ...)` · `ipadgooglemaps("directions", destination, ...)` · `ipadgooglemaps("street-view", coordinate, ...)` · `ipadgooglemaps("link", url)` |
| Pages | `ipadpages("open")` · `ipadpages("drop", path)` · `ipadpages("show", path)` |
| Numbers | `ipadnumbers("open")` · `ipadnumbers("drop", path)` · `ipadnumbers("show", path)` |
| Keynote | `ipadkeynote("open")` · `ipadkeynote("drop", path)` · `ipadkeynote("show", path)` |
| Photos | `ipadphotos("open")` · `ipadphotos("drop", path)` · `ipadphotos("show", path)` |
| Messages | `ipadmessages("compose")` |

Website calls accept explicit HTTP or HTTPS URLs. YouTube timestamps are non-negative seconds. App Store `show` accepts a positive product ID or canonical `apps.apple.com` app-product URL. Books `item` accepts an exact Books asset ID or canonical product URL. File extensions are checked by the destination package before the shared AirDrop policy runs.

The index contains 15 application packages: 14 core packages and optional Brave. Mail is unsupported and is not indexed. App-local `SKILL.md` files are on-demand instructions, not independently registered Pi skills.

### Maps status

For product `iPad17,1`, hardware `J817AP`, iPadOS `26.6.1`, build `23G83`, Apple Maps has seven proven Unified URL route families: frame, search/show, place, Look Around, directions preview, guides, and validated full links. `navigate` and `report-a-problem` remain candidate-gated. Ordinary `ipadmaps("open")` remains available.

```python
ipadmaps("frame", center=(52.2297, 21.0122), span=(0.05, 0.08), map="explore")
ipadmaps("search", "coffee & breakfast", center=(52.2297, 21.0122))
ipadmaps("place", place_id="opaque-apple-place-id", name="Meeting point")
ipadmaps("look-around", address="Eiffel Tower, Paris")
ipadmaps("directions", "Gdańsk", origin="Warsaw", waypoints=["Łódź", "Toruń"], mode="driving")
ipadmaps("guides")
ipadmaps("link", "https://maps.apple.com/place?place-id=opaque-id")
```

`directions` stops at route preview. Apple Maps navigation start and report remain maintenance candidates. Google Maps search, map, directions preview, Street View, and canonical links are proven on the same profile; Google Maps `navigate` remains a candidate. Candidate helpers do not provide an ordinary dispatch shortcut. See [`SECURITY.md`](SECURITY.md) for their authorization boundary.

Brave website and search routes are proven on the recorded profile. Private browsing remains a candidate. IPFS and IPNS are incompatible on that profile.

## Local files

`drop` sends one allowlisted local file. Destination packages restrict file types, while private configuration sets allowed roots, extensions, maximum size, and timeout. The macOS picker, or same-Apple-Account auto-accept behaviour, determines the receiver. A person can choose the iPad only when the picker appears.

Mac-side completion does not prove recipient choice, receipt, import, or opening. Exact-profile representative file evidence is limited to:

| Route | Proven scope |
|---|---|
| Preview PDF `show` | Received and opened in Preview |
| Books EPUB `show` | Received and opened in Books |
| Pages DOCX `show` | Received, imported, and opened; no broader content-fidelity claim |
| Numbers XLSX `show` | Received, imported, and opened; no broader content-fidelity claim |
| Keynote PPTX `show` | Received, imported, and opened; no broader content-fidelity claim |
| Files ZIP `drop` | Received and opened in the generic system preview; Files ownership is not proven |
| Photos PNG `drop` | Persistent import and opening; content fidelity is not proven |

Other admitted formats and Files/Photos `show` remain unproven. [`SECURITY.md`](SECURITY.md) defines private evidence handling and uncertain-transfer recovery.

## Result semantics

Calls return `IPadResult`, a dictionary with a compact terminal representation.

- `accepted`: CoreDevice accepted the launch or URL request. Visible state is unproved.
- `locked`: the iPad requires manual authentication.
- `pending`: one stage completed but the requested visible handoff remains unproved.
- `uncertain`: the action may have happened before the response was lost. Inspect before any new action.
- `failed: reason`: a certain pre-dispatch validation or discovery boundary rejected the request.

## Application skills

`package.json` exposes only `skills/use-ipad`. That gateway resolves the requested application through `integrations/index.json`, then reads only the app-local `SKILL.md`. Those 15 app-local skills stay out of `pi.skills` and enter context only when requested. Maintenance guidance remains in app-local `WORKFLOWS.md` and [`docs/integrations/`](docs/integrations/authoring.md).

Installing the Pi package registers this gateway. It does not install the `ipad_agent` Python package. Python imports work directly from the repository root; there is no pip installation step. To retire the checkout, run `pi remove "$PWD"` from its root and confirm its absence with `pi list` before moving or deleting it.

## Optional WDA infrastructure

No current semantic app integration starts WDA or Appium. Direct app, URL, Settings, and Maps routes do not need them. Do not install the automation stack during normal setup. The optional maintenance path exists only for automated screenshots, rendered-state checks, and investigation of a new integration when CoreDevice dispatch plus human confirmation is insufficient. See [Optional maintenance: Appium and WDA](#optional-maintenance-appium-and-wda).

## Default installation: CoreDevice only

This is the normal installation contract for an agent running on the Mac paired with the iPad. It installs no Node.js packages, Appium, WDA, or Apple signing material. Follow the steps in order and keep a short record of each check. Reading files, creating private local configuration, and running `doctor` do not authorize a device action.

1. Clone the repository and enter its root.

   ```bash
   git clone https://github.com/TobyNoSkillSon/ipad-agent.git
   cd ipad-agent
   ```

   Read `AGENTS.md`, this section, [`SECURITY.md`](SECURITY.md), [`DEPENDENCIES.md`](DEPENDENCIES.md), and `config.example.toml` before changing local state. Confirm that `package.json` exposes only `./skills/use-ipad`.

2. Check prerequisites without installing or upgrading them on the user's behalf.

   ```bash
   test "$(uname -s)" = Darwin
   python3 -c 'import sys; assert sys.version_info >= (3, 11); print(sys.version.split()[0])'
   xcode-select -p
   xcodebuild -version
   xcrun devicectl --version
   command -v pi
   ```

   The required host tools are macOS, Python 3.11 or newer, and full Xcode selected through `xcode-select`. Pi is required only for skill registration. If any prerequisite is absent, report it and wait for the user to install or approve it.

3. Create private configuration. Preserve an existing file and reject unsafe existing state instead of blindly changing it.

   ```bash
   python3 - <<'PY'
   import os, stat
   from ipad_agent.core.config import DEFAULT_CONFIG_PATH
   from ipad_agent.core.paths import descriptor_has_extended_acl, private_mkdir, private_write_text

   private_mkdir(DEFAULT_CONFIG_PATH.parent)
   if os.path.lexists(DEFAULT_CONFIG_PATH):
       flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
       descriptor = os.open(DEFAULT_CONFIG_PATH, flags)
       try:
           info = os.fstat(descriptor)
           if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
               raise RuntimeError("existing config is not a current-user-owned regular file")
           if descriptor_has_extended_acl(descriptor):
               raise RuntimeError("existing config carries an extended ACL")
           if stat.S_IMODE(info.st_mode) & 0o077:
               raise RuntimeError("existing config grants group or other permissions")
           os.fchmod(descriptor, 0o600)
       finally:
           os.close(descriptor)
   else:
       private_write_text(DEFAULT_CONFIG_PATH, open("config.example.toml", encoding="utf-8").read())
   print("private config ready")
   PY
   stat -f '%Lp %N' .runtime .runtime/config .runtime/config/config.toml
   ```

   `private_mkdir` rejects symlinks, non-directories, foreign ownership, extended ACLs, and group or other permissions anywhere in `.runtime/config`. Stop and inspect any rejection; never follow or chmod an unverified path.

   Keep device and signing identifiers inside `.runtime/`. Do not print the file or copy its private values into chat or reports. A device ID may stay unset when CoreDevice sees exactly one paired iPad. If several are present, ask the user which one to use and store only that choice in the private file.

4. Run the read-only readiness check from the repository root.

   ```bash
   python3 -m ipad_agent doctor --json
   ```

   Doctor reports CoreDevice, AirDrop, and optional WDA readiness separately. It reads installed npm package metadata without executing optional Appium or driver code, and its public report does not expose raw CoreDevice discovery output. Treat optional AirDrop or WDA failures as optional unless the user requested those routes.

5. Stop at human trust and unlock gates. Ask the user to pair the iPad, choose **Trust This Computer**, unlock it, accept Xcode licence or first-launch prompts, or make any other protected choice shown by the tools. The agent must not enter a passcode, use biometrics, enter Apple Account credentials or 2FA, approve signing, or click protected Apple prompts. After the user confirms completion, rerun `doctor`; do not infer that a prompt was accepted.

6. Register the checkout as a Pi package.

   ```bash
   pi install "$PWD"
   pi list
   ```

   This adds the local package to Pi settings and exposes the `use-ipad` gateway. It is separate from Python setup and does not make `ipad_agent` importable outside the checkout.

7. Verify Python from the repository root. Do not run `pip install`, `pip install -e`, or an npm install for the Python runtime.

   ```bash
   python3 -m ipad_agent --help
   python3 -c 'from ipad_agent import ipadc, ipadsafari, ipadmaps; print("python imports ok")'
   ```

   Every later Python example must run with this repository as the working directory.

8. Configure AirDrop only if the user requests local-file routes. Use a dedicated, current-user-owned directory that is not writable by group or other users. Never allow `/`, `/Users`, the home directory, a shared directory, a broad cloud-sync root, or another aggregate collection. Put only files intentionally available for transfer in that directory. Then set explicit extensions and a byte ceiling in `.runtime/config/config.toml`, retaining mode `0600`.

   ```toml
   [airdrop]
   allowed_roots = ["/Users/example/iPad-Agent-Transfer"]
   allowed_extensions = [".pdf", ".epub", ".png"]
   max_bytes = 524288000
   timeout_seconds = 120
   ```

   Rerun `doctor`. The picker or same-Apple-Account auto-accept determines the receiver. A person chooses the recipient only when a picker appears; the agent cannot infer the outcome from the callback.

9. Enable Brave only if the user confirms that Brave is installed and requests it.

   ```toml
   [addons]
   enabled = ["brave"]
   ```

   This private configuration enables semantic Brave commands. It does not install Brave or change the legacy display browser. Leave the addon list empty otherwise.

10. Request authorization for one harmless physical test. State the exact operation and wait for an explicit yes: `ipadc("open", "Safari")` once. After approval, run it once from the repository root.

    ```bash
    python3 - <<'PY'
    from ipad_agent import ipadc
    print(ipadc("open", "Safari"))
    PY
    ```

    `accepted` proves dispatch only, so ask the user whether Safari became visible if visible confirmation matters. If the result is `locked`, let the user unlock the iPad before any new authorized attempt. If it is `uncertain`, do not replay it. Inspect with the user and report the unresolved state.

11. Verify skill discovery in a fresh Pi session without contacting the device.

    ```bash
    pi --no-session "Use the installed use-ipad skill for Safari. Do not contact the iPad. Report the Python call you would run and the app-local skill you loaded."
    ```

    The answer should identify the gateway, resolve Safari through `integrations/index.json`, load `integrations/safari/SKILL.md`, and prepare a bare Python call that must run from the checkout root. It must not claim that Pi package installation installed Python.

12. Declare the default CoreDevice setup complete only when required prerequisites pass, the private runtime directories are mode `0700`, the config is mode `0600`, CoreDevice readiness is known, the Pi package appears in `pi list`, root-level Python imports pass, the fresh session finds the gateway and Safari skill, and the single approved test has a recorded certain result. Record WDA as skipped unless the user separately approved the maintenance installation. Mark AirDrop and Brave as enabled, skipped, or blocked. If the user declines the physical test, report setup as configured but not physically verified.

On any failure, stop at the failing step and report the command, a redacted error summary, what remains unknown, and the exact human action or prerequisite needed. Never paste credentials, private paths, device identifiers, raw device output, or physical evidence. Never guess that a prompt succeeded, broaden authorization, or repeat an uncertain device action. [`SECURITY.md`](SECURITY.md) is authoritative for recovery and evidence handling.

## Optional maintenance: Appium and WDA

Skip this section for normal use. Existing app commands already have their route policies and exact-profile evidence. CoreDevice dispatch plus the user's visual confirmation is enough for a harmless new-route pilot when no captured screenshot is required.

Use the automation stack only when the user explicitly requests automated screenshot evidence, rendered-state observation, or selector research that CoreDevice cannot provide. Ask before installing it. The host phase downloads pinned Appium and XCUITest packages from npm and may execute third-party installation code as the current Mac user. The full path also requires Developer Mode, local Apple Development signing, a locally built WDA, and human handling of every Xcode, keychain, provisioning, trust, and protected-confirmation gate.

After that approval, run each phase separately and stop at any human gate:

```bash
python3 -m ipad_agent setup --phase host --apply --json
python3 -m ipad_agent setup --phase wda --apply --json
python3 -m ipad_agent setup --phase verify --apply --json
```

Successful bounded verification stops its owned Appium server. After a failed verification, or when retiring WDA, inspect the cleanup plan before applying it:

```bash
python3 -m ipad_agent cleanup --json
python3 -m ipad_agent cleanup --apply --json
```

Cleanup is owned-only and can be partial. It first requires receipt-owned Appium to stop, or proves that no unreceipted project Appium state is present, before removing ownership-metadata-matching WDA artifacts. It does not remove host npm packages, private configuration, AirDrop recovery snapshots, the development-signed runner from the iPad, Developer Mode, computer trust, certificates, or profiles. Follow [`SECURITY.md`](SECURITY.md#stop-and-decommission) for full manual shutdown and revocation.

## Development

Run the offline release gate from the checkout root:

```bash
python3 scripts/release_check.py
python3 -c 'from ipad_agent import ipadc, ipadpreview, ipadbooks, ipadfiles, ipadsettings, ipadclock, ipadappstore, ipadbrave, ipadsafari, ipadmaps, ipadgooglemaps, ipadpages, ipadnumbers, ipadkeynote, ipadphotos, ipadmessages'
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 -m unittest discover -s integrations -t . -p 'test_*.py' -v
python3 -m compileall -q ipad_agent integrations tests scripts
```

CI runs the offline test boundaries and never runs physical actions. Integration maintenance and physical evidence procedures live in [`docs/integrations/authoring.md`](docs/integrations/authoring.md).

## Alpha scope

The alpha does not support browser tab control, generated display pages, automatic file association, general UI automation, recipient-bearing Messages, or Mail. Blank Messages compose is proven and cannot send. Current file and map limits are listed above; candidate routes remain gated even when vendor documentation exists.

Runtime configuration, identifiers, signing material, build products, logs, screenshots, and raw physical evidence stay under the Git-ignored `.runtime/` directory.

Licensed under Apache-2.0. See [`LICENSE`](LICENSE), [`THIRD_PARTY.md`](THIRD_PARTY.md), and [`SECURITY.md`](SECURITY.md).
