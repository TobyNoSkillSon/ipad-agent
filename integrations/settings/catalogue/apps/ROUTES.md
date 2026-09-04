# Apps Settings routes

Read this section only when the requested destination belongs here. Raw URLs remain in the machine catalogue. Compatibility is proven only for product `iPad17,1`, hardware `J817AP`, and OS build `23G83`.

`proven` routes are available to ordinary `show` calls on that exact scope. `candidate` routes are retained for explicit, controlled development testing only. `incompatible` routes conflict with this profile or have negative visual evidence. `template` routes contain dynamic placeholders and never dispatch. Safety policy remains separate: `normal`, `explicit`, or `blocked`.

| Route ID | Label | Availability | Scoped evidence | Kind / policy |
|---|---|---|---|---|
| `apps` | Apps | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-empty` | Settings.Apps > | **template** | runtime-literal (iOS 26.5 simulator, 23F77) | dynamic / blocked |
| `apps-placeholder` | Settings.Apps > % | **template** | runtime-literal (iOS 26.5 simulator, 23F77) | dynamic / blocked |
| `apps-com-apple-fitness-fitness-plus` | Settings.Apps > com.apple.Fitness > fitness-plus | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-fitness-workout-controls` | Settings.Apps > com.apple.Fitness > workout-controls | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-health` | General > Health Data | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / explicit |
| `apps-com-apple-health-medical-id-item` | General > Health Data > Medical ID | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / explicit |
| `apps-com-apple-maps` | Apps > Maps | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-maps-cycling-link-preference-id` | Apps > Maps > Directions – Cycling | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-maps-driving-link-preference-id` | Apps > Maps > Directions – Driving | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-maps-navigation-guidance-link-preference-id` | Apps > Maps > Spoken Directions | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-maps-transit-link-preference-id` | Apps > Maps > Directions – Transit | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-maps-walking-link-preference-id` | Apps > Maps > Directions – Walking | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-mobile-address-book` | Apps > Contacts | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-mobile-sms-row-conversation-backgrounds-enabled-switch` | Settings.Apps > com.apple.Mobile SMS > CONVERSATION BACKGROUNDS ENABLED SWITCH | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | row / explicit |
| `apps-com-apple-mobile-sms-row-filter-new-senders-switch` | Apps > Messages > Screen Unknown Senders (switch) | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | row / explicit |
| `apps-com-apple-mobile-sms-row-notificattions-unkown-senders-button` | Settings.Apps > com.apple.Mobile SMS > NOTIFICATTIONS UNKOWN SENDERS BUTTON | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | row / explicit |
| `apps-com-apple-passwords` | Apps > Passwords | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / explicit |
| `apps-com-apple-settings-apps-app-clips` | Settings.Apps > Settings.Apps.App Clips | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-settings-apps-default-apps` | Apps > Default Apps | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-translate` | Apps > Translate | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-translate-empty` | Settings.Apps > com.apple.Translate > | **template** | runtime-literal (iOS 26.5 simulator, 23F77) | dynamic / blocked |
| `apps-com-apple-translate-downloaded-languages-specifier` | Apps > Translate > Languages | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-voice-memos` | Apps > Voice Memos | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-facetime-row-filter-as-new-callers` | Apps > FaceTime > Call Filtering – Unknow Callers (switch) | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | row / explicit |
| `apps-com-apple-facetime-blocklist-settings-main-specifier-identifier` | Apps > FaceTime > Blocked Contacts | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-mobilecal` | Apps > Calendar | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-mobilecal-delegate-calendars` | Settings.Apps > com.apple.mobilecal > DELEGATE CALENDARS | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-mobilecal-alternate-calendars` | Apps > Calendar > Alternate Calendars | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-mobilecal-default-alert-times` | Apps > Calendar > Default Alert Times | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-mobilecal-default-alert-times-all-day-events-default-alert-times` | Apps > Calendar > Default Alert Times > All-Day Events | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-mobilecal-default-alert-times-birthdays-default-alert-times` | Apps > Calendar > Default Alert Times > Birthdays | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-mobilecal-default-alert-times-timed-events-default-alert-times` | Apps > Calendar > Default Alert Times > Events | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-mobilecal-default-calendar` | Apps > Calendar > Default Calendar | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-mobilecal-duration-for-new-events` | Apps > Calendar > Duration for New Events | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-mobilecal-start-week-on` | Apps > Calendar > Start Week On | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-mobilecal-sync-duration` | Apps > Calendar > Sync | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-mobilecal-time-zone-override` | Apps > Calendar > Time Zone Override | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-mobilemail` | Apps > Mail | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-mobilephone-row-filter-as-new-callers` | Apps > Phone > Call Filtering – Unknown Callers (switch) | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | row / explicit |
| `apps-com-apple-mobilesafari` | Apps > Safari | **proven** | user-visual-pass (actor=user; expected-target-visible; scope iPad17,1 / J817AP / 23G83)<br>observer-screenshot-pass (actor=agent; method=project-owned-wda-screenshot; expected-target-visible; scope iPad17,1 / J817AP / 23G83) | page / normal |
| `apps-com-apple-mobilesafari-row-private-browsing-uses-normal-browsing-search-engine-selection` | Apps > Safari > Also Use in Private Browsing (switch) | **proven** | user-visual-pass (actor=user; expected-target-visible; scope iPad17,1 / J817AP / 23G83)<br>observer-screenshot-pass (actor=agent; method=project-owned-wda-screenshot; expected-target-visible; scope iPad17,1 / J817AP / 23G83) | row / explicit |
| `apps-com-apple-mobileslideshow` | Apps > Photos | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-mobileslideshow-shared-library-settings-button` | Apps > Photos > Shared Library (dialog) | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | action / blocked |
| `apps-com-apple-news` | Settings.Apps > com.apple.news | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-news-automatic-downloads-link` | Settings.Apps > com.apple.news > AUTOMATIC DOWNLOADS LINK | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-podcasts` | Apps > Podcasts | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-podcasts-backward` | Settings.Apps > com.apple.podcasts > BACKWARD | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-podcasts-cellular-downloads` | Settings.Apps > com.apple.podcasts > CELLULAR DOWNLOADS | **incompatible** | runtime-literal (iOS 26.5 simulator, 23F77)<br>profile-capability-mismatch (cellular required=true, observed=false; scope iPad17,1 / J817AP / 23G83) | page / normal |
| `apps-com-apple-podcasts-forward` | Settings.Apps > com.apple.podcasts > FORWARD | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-podcasts-podcasts-and-privacy` | Settings.Apps > com.apple.podcasts > PODCASTS AND PRIVACY | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / explicit |
| `apps-com-apple-reminders` | Apps > Reminders | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-reminders-notifications` | Settings.Apps > com.apple.reminders > NOTIFICATIONS | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-shortcuts` | Apps > Shortcuts | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-shortcuts-shortcuts-advanced-settings` | Apps > Shortcuts > Advanced | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-shortcuts-shortcuts-legal-notices` | Apps > Shortcuts > Legal Notices | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-sports` | Settings.Apps > com.apple.sports | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-stocks` | Settings.Apps > com.apple.stocks | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-tv` | Settings.Apps > com.apple.tv | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-tv-empty` | Settings.Apps > com.apple.tv > | **template** | runtime-literal (iOS 26.5 simulator, 23F77) | dynamic / blocked |
| `apps-com-apple-tv-com-apple-videos-top-level-audio-and-subtitle-languages` | Settings.Apps > com.apple.tv > com.apple.videos:Top Level Audio And Subtitle Languages | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-weather` | Apps > Weather | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / normal |
| `apps-com-apple-weather-row-home-work-show-labels` | Apps > Weather > Locations – Home and Work (switch) | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | row / explicit |
| `apps-com-apple-weather-row-privacy-reset` | Apps > Weather > Privacy – Reset Indentifier (switch) | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | row / blocked |
| `apps-com-apple-weather-row-temperature-unit` | Apps > Weather > Temperature Unit | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | row / explicit |
| `apps-com-apple-weather-row-use-significant-locations` | Apps > Weather > Locations – Suggested Locations (switch) | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | row / explicit |

Ordinary exact-scope example:

```python
ipadsettings("show", "apps-com-apple-mobilesafari")
```
