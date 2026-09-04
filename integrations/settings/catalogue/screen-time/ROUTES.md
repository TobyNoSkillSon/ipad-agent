# ScreenTime Settings routes

Read this section only when the requested destination belongs here. Raw URLs remain in the machine catalogue. Compatibility is proven only for product `iPad17,1`, hardware `J817AP`, and OS build `23G83`.

`proven` routes are available to ordinary `show` calls on that exact scope. `candidate` routes are retained for explicit, controlled development testing only. `incompatible` routes conflict with this profile or have negative visual evidence. `template` routes contain dynamic placeholders and never dispatch. Safety policy remains separate: `normal`, `explicit`, or `blocked`.

| Route ID | Label | Availability | Scoped evidence | Kind / policy |
|---|---|---|---|---|
| `screen-time` | Screen Time | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / explicit |
| `screen-time-always-allowed` | Screen Time > Always Allowed If App & Website Activity is enabled | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / explicit |
| `screen-time-app-limits` | Screen Time > App Limits If App & Website Activity is enabled | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / explicit |
| `screen-time-communication-limits` | Screen Time > Communication Limits | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / explicit |
| `screen-time-communication-safety` | Screen Time > Communication Safety | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / explicit |
| `screen-time-content-privacy` | Screen Time > Content & Privacy Restrictions | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / explicit |
| `screen-time-content-privacy-allowed-apps` | Screen Time > Content & Privacy Restrictions > Allowed Apps & Features | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / explicit |
| `screen-time-content-privacy-content-restrictions-app-rating` | Settings.Screen Time > CONTENT PRIVACY > CONTENT RESTRICTIONS > APP RATING | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / explicit |
| `screen-time-downtime` | Screen Time > Downtime If App & Website Activity is enabled | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / explicit |
| `screen-time-eye-distance` | Screen Time > Screen Distance | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / explicit |
| `screen-time-screen-time-summary` | Screen Time > See All App & Website Activity If App & Website Activity is enabled | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / explicit |

This section has no ordinary deep-link route for the target profile/build.
