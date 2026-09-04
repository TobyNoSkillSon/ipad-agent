# Camera Settings routes

Read this section only when the requested destination belongs here. Raw URLs remain in the machine catalogue. Compatibility is proven only for product `iPad17,1`, hardware `J817AP`, and OS build `23G83`.

`proven` routes are available to ordinary `show` calls on that exact scope. `candidate` routes are retained for explicit, controlled development testing only. `incompatible` routes conflict with this profile or have negative visual evidence. `template` routes contain dynamic placeholders and never dispatch. Safety policy remains separate: `normal`, `explicit`, or `blocked`.

| Route ID | Label | Availability | Scoped evidence | Kind / policy |
|---|---|---|---|---|
| `camera` | Camera | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `camera-camera-button-settings` | Settings.Camera > CAMERA BUTTON SETTINGS | **incompatible** | runtime-literal (iOS 26.5 simulator, 23F77)<br>profile-capability-mismatch (camera_control required=true, observed=false; scope iPad17,1 / J817AP / 23G83) | page / normal |
| `camera-camera-formats-settings-list` | Camera > Formats | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `camera-camera-preserve-settings-switch` | Camera > Preserve Settings | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `camera-camera-slomo-settings-list` | Camera > Record Slo-mo | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `camera-camera-video-settings-list` | Camera > Record Video | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |

This section has no ordinary deep-link route for the target profile/build.
