# Siri Settings routes

Read this section only when the requested destination belongs here. Raw URLs remain in the machine catalogue. Compatibility is proven only for product `iPad17,1`, hardware `J817AP`, and OS build `23G83`.

`proven` routes are available to ordinary `show` calls on that exact scope. `candidate` routes are retained for explicit, controlled development testing only. `incompatible` routes conflict with this profile or have negative visual evidence. `template` routes contain dynamic placeholders and never dispatch. Safety policy remains separate: `normal`, `explicit`, or `blocked`.

| Route ID | Label | Availability | Scoped evidence | Kind / policy |
|---|---|---|---|---|
| `siri` | Siri | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `siri-empty` | Settings.Siri > | **template** | runtime-literal (iOS 26.5 simulator, 23F77) | dynamic / blocked |
| `siri-activation-compact-id` | Settings.Siri > ACTIVATION COMPACT ID | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `siri-assistant-apps-settings-id` | Settings.Siri > ASSISTANT APPS SETTINGS ID | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `siri-assistant-app-clips-settings-id` | Settings.Siri > ASSISTANT APP CLIPS SETTINGS ID | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `siri-external-aimodel` | Settings.Siri > External AIModel | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / explicit |
| `siri-external-aimodel-query-partner-empty` | Settings.Siri > External AIModel > partner= | **template** | runtime-literal (iOS 26.5 simulator, 23F77) | dynamic / blocked |
| `siri-external-aimodel-query-view-change-selection-partner-empty` | Settings.Siri > External AIModel > view=change Selection&partner= | **template** | runtime-literal (iOS 26.5 simulator, 23F77) | dynamic / blocked |
| `siri-external-aimodel-query-view-upgrade-plan` | Settings.Siri > External AIModel > view=upgrade Plan | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | action / blocked |
| `siri-history` | Settings.Siri > HISTORY | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `siri-language-detail` | Settings.Siri > LANGUAGE DETAIL | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `siri-language-id` | Settings.Siri > LANGUAGE ID | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `siri-siri-in-call-id` | Settings.Siri > SIRI IN CALL ID | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `siri-voice-feedback-id` | Settings.Siri > VOICE FEEDBACK ID | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `siri-voice-id` | Settings.Siri > VOICE ID | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `siri-voice-profile-repair-cfu` | Settings.Siri > voice Profile Repair CFU | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | action / blocked |

This section has no ordinary deep-link route for the target profile/build.
