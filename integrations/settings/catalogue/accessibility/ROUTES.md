# Accessibility Settings routes

Read this section only when the requested destination belongs here. Raw URLs remain in the machine catalogue. Compatibility is proven only for product `iPad17,1`, hardware `J817AP`, and OS build `23G83`.

`proven` routes are available to ordinary `show` calls on that exact scope. `candidate` routes are retained for explicit, controlled development testing only. `incompatible` routes conflict with this profile or have negative visual evidence. `template` routes contain dynamic placeholders and never dispatch. Safety policy remains separate: `normal`, `explicit`, or `blocked`.

| Route ID | Label | Availability | Scoped evidence | Kind / policy |
|---|---|---|---|---|
| `accessibility` | Accessibility | **proven** | runtime-literal (iOS 26.5 simulator, 23F77)<br>user-visual-pass (actor=user; expected-target-visible; scope iPad17,1 / J817AP / 23G83)<br>observer-screenshot-pass (actor=agent; method=project-owned-wda-screenshot; expected-target-visible; scope iPad17,1 / J817AP / 23G83) | page / normal |
| `accessibility-motion-title` | Accessibility > Motion | **proven** | user-visual-pass (actor=user; expected-target-visible; scope iPad17,1 / J817AP / 23G83)<br>observer-screenshot-pass (actor=agent; method=project-owned-wda-screenshot; expected-target-visible; scope iPad17,1 / J817AP / 23G83) | page / normal |
| `accessibility-sound-recognition-title-sounds` | Settings.Accessibility > SOUND RECOGNITION TITLE > Sounds | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |

Ordinary exact-scope example:

```python
ipadsettings("show", "accessibility")
```
