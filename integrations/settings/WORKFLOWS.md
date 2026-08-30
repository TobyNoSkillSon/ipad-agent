# Settings workflows

## Scope

Settings support is top-level navigation only. The allowed destinations are General, Wi-Fi, Bluetooth, Battery, and Accessibility. Selecting one destination does not authorize reading its details or operating anything in the detail pane.

Search is absent by design. A generic Settings search can route into account, privacy, security, passcode, or software-update controls that this integration prohibits.

## Instructions

1. Activate Settings.
2. Choose one requested top-level action: `open-general`, `open-wifi`, `open-bluetooth`, `open-battery`, or `open-accessibility`.
3. Verify only the selected pane heading or selected sidebar row.
4. Stop. Do not enter child rows or touch a switch, picker, button, text field, network, or device.

Additional limits apply to each pane:

- General: stop before About, Software Update, VPN and Device Management, and Transfer or Reset.
- Wi-Fi: do not collect network names, open a network row, join a network, or touch the switch.
- Bluetooth: do not collect device names, pair, connect, disconnect, open details, or touch the switch.
- Battery: do not inspect per-app activity or touch Low Power Mode.
- Accessibility: do not enter or change a feature.

Accounts, Apple Account, Family, passwords, passcodes, biometrics, payments, Privacy & Security, Location Services, updates, profiles, and reset flows are prohibited even for inspection.

Apple's current guide describes the Settings search field and confirms that it can route directly to settings: <https://support.apple.com/guide/ipad/find-settings-ipadba23b9b4/ipados>. This integration omits that route because its destination is not bounded.

## Selector rationale

The `com.apple.settings.*` identifiers are app-owned accessibility IDs, so they avoid English row text and sidebar coordinates. They also match the identifiers already exposed through the project registry. The runtime must resolve them in the Settings bundle and must not reuse cached elements after a pane change.

The identifiers are private implementation details, not a public Apple automation contract. The workflow stops if an ID is absent or resolves to more than one visible row. It must not substitute coordinates, XPath, Settings URLs, or a broad text search.

## State, locale, and version caveats

Settings retains its selected pane. Activating the app can therefore reveal a previously open prohibited page. If that happens, use only the allowed top-level sidebar destination. If the sidebar is hidden and cannot be exposed without an unbounded gesture, stop.

The accessibility IDs are expected to be less locale-sensitive than labels. They target English and iPadOS 17 or later, but compatibility is explicitly `unverified` and lists no verified Settings app version. iPadOS can change Settings sections, identifiers, and split-view layout. Supervised devices, configuration profiles, Screen Time restrictions, and first-run prompts can add rows or gates. Stop on every prompt and never attempt to clear a restriction.

These selectors and workflows have not been exercised on a physical iPad in this change. Schema and registry tests confirm structure, not behavior on a device or any iPadOS point release.

## Safety and retry classes

- `activate` and every allowed pane action: navigate.
- every toggle, child row, network, device, form, install action, and confirmation: prohibited.
- after a dispatched pane tap, inspect only the selected heading. Never tap again to “make sure.”
- after a lost response, assume the pane may already be selected. Do not compensate inside the detail pane.

The manifest permits one attempt and lists only `activate` as idempotent. Pane selection is harmless when repeated in principle, but the workflow still inspects first because stale hierarchy and split-view state can redirect a tap.

## Benchmark scenarios

These are completion criteria for later physical runs. They are not physical results from this implementation.

| Scenario | Start state | Exercise | Pass condition |
|---|---|---|---|
| General boundary | Settings on another allowed pane | open General | General heading visible; no child row opens |
| Connectivity boundary | Settings sidebar visible | open Wi-Fi or Bluetooth | requested heading visible; no names collected and no state changes |
| Battery boundary | Settings on General | open Battery | Battery heading visible; activity details are not inspected |
| Accessibility boundary | Settings on Battery | open Accessibility | top-level heading visible; no feature opens |
| Prohibited prior state | Settings initially on Privacy & Security or Software Update | navigate to one allowed top-level pane | workflow leaves prohibited pane without inspecting it |
| Selector mismatch | changed or localized hierarchy | selector preflight | workflow stops without coordinates, search, or child-row fallback |
| Lost response | transport closes after pane tap | heading-only inspection | no repeated tap and no detail control touched |

Benchmark artifacts may record the requested pane and selector outcome. They must exclude screenshots, page source, network names, device names, account data, identifiers, installed-profile data, and activity details.

## Completion gates

A Settings task is complete only when:

- exactly one allowed top-level pane is selected;
- no child row, toggle, picker, button, text field, network, or device was operated;
- no account, privacy, security, passcode, biometric, payment, update, profile, VPN-management, or reset pane was entered;
- no network, device, app-activity, or identifier data was collected;
- any WDA burst was torn down; and
- the report says that physical verification was not performed for this implementation.
