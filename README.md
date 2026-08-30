# iPad Agent

[![CI](https://github.com/TobyNoSkillSon/ipad-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/TobyNoSkillSon/ipad-agent/actions/workflows/ci.yml)

Open installed apps, websites, and locations on a paired physical iPad, or send it a local file through AirDrop, with one Python call.

```python
from ipad_agent import ipadmaps
ipadmaps("show", "Warsaw Chopin Airport")
```

iPad Agent is a macOS-only alpha. It uses Apple CoreDevice for app launches and deep links, and AirDrop for local files. WebDriverAgent is optional and used only to navigate to allowlisted Settings panes. The project is not affiliated with or endorsed by Apple Inc. iPad is an Apple trademark.

## Routes

| Request | Primary route | Evidence returned |
|---|---|---|
| Open an installed app | CoreDevice | Launch accepted |
| Open a website or app deep link | CoreDevice URL payload | URL dispatch accepted |
| Show a location | CoreDevice URL payload (`maps://`) | Maps dispatch accepted |
| Open an App Store product | CoreDevice URL payload | Product URL dispatch accepted |
| Transfer a local file | AirDrop | Host sharing callback completed |
| Navigate to an allowlisted Settings pane | Optional short-lived WDA session | Expected pane observed |

A successful CoreDevice command proves that the iPad accepted the launch request. It does not prove that a page finished rendering or that an exact browser tab is visible.

## Quick start

### Requirements

- macOS
- Python 3.11 or newer
- full Xcode selected through `xcode-select`
- a physical iPad paired with and trusted by the Mac

Clone the repository and create private runtime configuration:

```bash
git clone https://github.com/TobyNoSkillSon/ipad-agent.git
cd ipad-agent
mkdir -p .runtime/config
cp config.example.toml .runtime/config/config.toml
chmod 600 .runtime/config/config.toml
```

Inspect host and device readiness:

```bash
python3 -m ipad_agent doctor --json
```

Doctor reports CoreDevice, AirDrop, and optional WDA readiness separately. Direct app and URL routes do not require Appium or a WDA build.

Try a harmless launch from the checkout root:

```bash
python3 - <<'PY'
from ipad_agent import ipadc
ipadc("open", "Safari")
PY
```

The iPad may ask the operator to unlock it or trust the Mac. The project never supplies passcodes, credentials, biometric confirmation, or protected approvals.

## Python commands

Import the destination family you need. Each function call performs one requested operation.

| Destination | Calls |
|---|---|
| Core | `ipadc("open", "Preview")` · `ipadc("drop", "/absolute/path/report.pdf")` · `ipadc("status")` |
| Preview | `ipadpreview("open")` · `ipadpreview("drop", path)` · `ipadpreview("show", path)` |
| Books | `ipadbooks("open")` · `ipadbooks("drop", path)` · `ipadbooks("show", path)` |
| Files | `ipadfiles("open")` · `ipadfiles("drop", path)` · `ipadfiles("show", path)` |
| Settings | `ipadsettings("open")` · `ipadsettings("general")` · `ipadsettings("about")` · `ipadsettings("wifi")` · `ipadsettings("bluetooth")` · `ipadsettings("battery")` · `ipadsettings("accessibility")` |
| Clock | `ipadclock("open")` |
| App Store | `ipadappstore("open")` · `ipadappstore("show", 123456789)` |
| Brave | `ipadbrave("website", url)` · `ipadbrave("youtube", url, at=90)` |
| Safari | `ipadsafari("website", url)` · `ipadsafari("youtube", url, at=90)` |
| Apple Maps | `ipadmaps("show", "Warsaw Chopin Airport")` |

Website calls accept explicit HTTP or HTTPS URLs. YouTube timestamps are non-negative seconds. App Store `show` accepts a positive product ID or an `apps.apple.com` URL containing one.

Brave is an optional integration. Enable it in `.runtime/config/config.toml`:

```toml
[apps]
browser = "Brave Browser"

[addons]
enabled = ["brave"]
```

## Local files

`drop` sends one allowlisted local file through AirDrop. `show` sends the file and then opens Preview, Books, or Files.

Configure allowed roots, extensions, and the maximum size in `.runtime/config/config.toml`. macOS presents the AirDrop recipient picker; the operator selects the iPad. The project does not automate that selection.

AirDrop completion confirms the Mac-side sharing callback. It does not prove which recipient was selected, that the iPad received the file, or that the destination app opened that exact file. `show` reports that unresolved handoff honestly.

## Optional Settings navigation

Only Settings subsections need the current WDA backend. This path requires Developer Mode, Node.js/npm, local Apple Development signing, Appium, and a locally built WebDriverAgent.

You can rerun setup. It stops when Apple requires the operator to act:

```bash
python3 -m ipad_agent setup --phase host --apply --json
python3 -m ipad_agent setup --phase wda --apply --json
python3 -m ipad_agent setup --phase verify --apply --json
```

The operator handles Trust This Computer, device unlock, Developer Mode, Apple Account authentication, signing, provisioning, keychain prompts, and Developer App trust. See [`DEPENDENCIES.md`](DEPENDENCIES.md) and [`SECURITY.md`](SECURITY.md).

## Give the repository to an agent

Use this prompt with a coding agent on the Mac that will control the iPad:

```text
Clone https://github.com/TobyNoSkillSon/ipad-agent and read AGENTS.md. Run the
read-only doctor first. Configure CoreDevice and only the integrations I request.
Keep device identifiers, signing data, logs, and runtime evidence under .runtime/.
Do not print credentials or automate Apple security prompts. Stop when a person
must unlock, trust, sign, approve, purchase, or enter account information. Before
changing code, run the relevant offline tests. Do not run a live iPad action
without my explicit approval for that action.
```

## Result semantics

Calls return `IPadResult`, a dictionary with a compact terminal representation.

- `accepted` means CoreDevice accepted the launch or URL.
- `locked` means the iPad requires manual authentication.
- `pending` means one stage completed but the requested visible handoff remains unproved.
- `uncertain` means the operation may have happened before the response was lost. Do not replay it blindly.
- `failed: reason` means dispatch did not complete to its documented evidence boundary.

## Development

Run the offline release gate from the checkout root:

```bash
python3 scripts/release_check.py
python3 -c 'from ipad_agent import ipadc, ipadpreview, ipadbooks, ipadfiles, ipadsettings, ipadclock, ipadappstore, ipadbrave, ipadsafari, ipadmaps'
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 -m compileall -q ipad_agent tests scripts
```

CI does not run live device actions. Integration maintenance and physical evidence procedures live in [`docs/integrations/authoring.md`](docs/integrations/authoring.md).

## Alpha scope

The alpha does not support browser tab control, generated display pages, automatic file association, or general UI automation.

See [`ROADMAP.md`](ROADMAP.md) for proposed Maps routes and vendor-documented content links.

Runtime configuration, device identifiers, signing material, build products, tokens, logs, and physical evidence stay under the Git-ignored `.runtime/` directory.

Licensed under Apache-2.0. See [`LICENSE`](LICENSE), [`THIRD_PARTY.md`](THIRD_PARTY.md), and [`SECURITY.md`](SECURITY.md).
