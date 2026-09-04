# General Settings routes

Read this section only when the requested destination belongs here. Raw URLs remain in the machine catalogue. Compatibility is proven only for product `iPad17,1`, hardware `J817AP`, and OS build `23G83`.

`proven` routes are available to ordinary `show` calls on that exact scope. `candidate` routes are retained for explicit, controlled development testing only. `incompatible` routes conflict with this profile or have negative visual evidence. `template` routes contain dynamic placeholders and never dispatch. Safety policy remains separate: `normal`, `explicit`, or `blocked`.

| Route ID | Label | Availability | Scoped evidence | Kind / policy |
|---|---|---|---|---|
| `general` | General | **proven** | runtime-literal (iOS 26.5 simulator, 23F77)<br>user-visual-pass (actor=user; expected-target-visible; scope iPad17,1 / J817AP / 23G83)<br>observer-screenshot-pass (actor=agent; method=project-owned-wda-screenshot; expected-target-visible; scope iPad17,1 / J817AP / 23G83) | page / normal |
| `general-airdrop-link` | General > AirDrop | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `general-airdrop-link-row-airdrop-cellular-usage-id` | General > AirDrop > Out of Range – Use Cellular Data (switch) almost unnoticeable highlighting | **incompatible** | runtime-literal (iOS 26.5 simulator, 23F77)<br>profile-capability-mismatch (cellular required=true, observed=false; scope iPad17,1 / J817AP / 23G83) | row / explicit |
| `general-airdrop-link-row-airdrop-group-id` | Settings.General > AIRDROP LINK > AIRDROP GROUP ID | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | row / explicit |
| `general-airdrop-link-row-airdrop-nfc-id` | General > AirDrop > Start Sharing By – Bringing Devices Together (switch) almost unnoticeable highlighting | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | row / explicit |
| `general-autofill` | General > AutoFill & Passwords | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / explicit |
| `general-auto-content-download` | General > Background App Refresh | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `general-about` | General > About | **proven** | runtime-literal (iOS 26.5 simulator, 23F77)<br>user-visual-pass (actor=user; expected-target-visible; scope iPad17,1 / J817AP / 23G83)<br>observer-screenshot-pass (actor=agent; method=project-owned-wda-screenshot; expected-target-visible; scope iPad17,1 / J817AP / 23G83) | page / normal |
| `general-about-sw-version-specifier` | General > About > iOS Version | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `general-carplay` | Settings.General > CARPLAY | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `general-continuity-spec` | General > AirPlay & Continuity | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `general-date-and-time` | General > Date & Time | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `general-dictionary` | General > Dictionary | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `general-font-setting` | General > Fonts | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `general-health-data` | Settings.General > HEALTH DATA | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / explicit |
| `general-home-button` | Settings.General > HOME BUTTON | **incompatible** | runtime-literal (iOS 26.5 simulator, 23F77)<br>profile-capability-mismatch (home_button required=true, observed=false; scope iPad17,1 / J817AP / 23G83) | page / normal |
| `general-international` | General > Language & Region | **proven** | runtime-literal (iOS 26.5 simulator, 23F77)<br>user-visual-pass (actor=user; expected-target-visible; scope iPad17,1 / J817AP / 23G83)<br>observer-screenshot-pass (actor=agent; method=project-owned-wda-screenshot; expected-target-visible; scope iPad17,1 / J817AP / 23G83) | page / normal |
| `general-international-placeholder` | Settings.General > INTERNATIONAL > % | **template** | runtime-literal (iOS 26.5 simulator, 23F77) | dynamic / blocked |
| `general-international-add-preferred-language` | General > Language & Region > Add Language | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | action / blocked |
| `general-international-locale` | General > Language & Region > Region | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `general-keyboard` | General > Keyboard | **proven** | runtime-literal (iOS 26.5 simulator, 23F77)<br>user-visual-pass (actor=user; expected-target-visible; scope iPad17,1 / J817AP / 23G83)<br>observer-screenshot-pass (actor=agent; method=project-owned-wda-screenshot; expected-target-visible; scope iPad17,1 / J817AP / 23G83) | page / normal |
| `general-keyboard-placeholder` | Settings.General > Keyboard > % | **template** | runtime-literal (iOS 26.5 simulator, 23F77) | dynamic / blocked |
| `general-keyboard-dictation-settings` | General > Keyboard > Dictation Languages | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `general-keyboard-fuzzy-pinyin-option` | Settings.General > Keyboard > FUZZY PINYIN OPTION | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `general-keyboard-keyboards` | General > Keyboard > Keyboards | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `general-keyboard-keyboards-add-new-keyboard` | Settings.General > Keyboard > KEYBOARDS > Add New Keyboard | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | action / blocked |
| `general-keyboard-user-dictionary` | General > Keyboard > Text Replacement | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `general-legal-and-regulatory` | General > Legal & Regulatory | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `general-matter-accessories` | General > Matter Accessories | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `general-managed-configuration-list` | General > VPN & Device Management | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / blocked |
| `general-managed-configuration-list-downloaded-profile` | Settings.General > Managed Configuration List > Downloaded Profile | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | action / blocked |
| `general-managed-configuration-list-mdmmigration` | Settings.General > Managed Configuration List > MDMMigration | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / blocked |
| `general-managed-configuration-list-managed-account` | Settings.General > Managed Configuration List > Managed Account | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | action / blocked |
| `general-nfc-link` | Settings.General > NFC LINK | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `general-pointers` | General > Trackpad & Mouse | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `general-pi-p-spec` | General > Picture in Picture | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `general-reset` | General > Transfer or Reset iPhone | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / blocked |
| `general-reset-exit-buddy` | Settings.General > Reset > exit Buddy | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | action / blocked |
| `general-reset-exit-buddy-up-sell-trade-in` | Settings.General > Reset > exit Buddy Up Sell Trade In | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | action / blocked |
| `general-reset-prebuddy-begin` | Settings.General > Reset > prebuddy Begin | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | action / blocked |
| `general-screen-capture` | General > Screen Capture | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `general-software-update-link` | General > Software Update | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / blocked |
| `general-software-update-link-suautomatic-update-button` | General > Software Update > Automatic Updates | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / blocked |
| `general-software-update-link-subeta-updates-button` | Settings.General > SOFTWARE UPDATE LINK > SUBeta Updates Button | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / blocked |
| `general-storage-mgmt` | General > iPhone Storage | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `general-tv-provider` | Settings.General > TV PROVIDER | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |

Ordinary exact-scope example:

```python
ipadsettings("show", "general")
```
