# Developer Settings routes

Read this section only when the requested destination belongs here. Raw URLs remain in the machine catalogue. Compatibility is proven only for product `iPad17,1`, hardware `J817AP`, and OS build `23G83`.

`proven` routes are available to ordinary `show` calls on that exact scope. `candidate` routes are retained for explicit, controlled development testing only. `incompatible` routes conflict with this profile or have negative visual evidence. `template` routes contain dynamic placeholders and never dispatch. Safety policy remains separate: `normal`, `explicit`, or `blocked`.

| Route ID | Label | Availability | Scoped evidence | Kind / policy |
|---|---|---|---|---|
| `developer` | Settings.Developer | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / explicit |
| `developer-empty` | Settings.Developer > | **template** | runtime-literal (iOS 26.5 simulator, 23F77) | dynamic / blocked |
| `developer-l4-s-settings` | Settings.Developer > L4 S SETTINGS | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / explicit |
| `developer-magnify` | Settings.Developer > MAGNIFY | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / explicit |

This section has no ordinary deep-link route for the target profile/build.
