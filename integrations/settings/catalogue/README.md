# Settings route catalogue

Use this index to find one section, then read only that section’s `ROUTES.md`. The machine authority is [`../route-catalog.json`](../route-catalog.json); section files intentionally omit raw URLs.

Ordinary navigation is limited to routes marked `proven` for the exact proof scope: product `iPad17,1`, hardware `J817AP`, OS build `23G83` (iPad Pro 11-inch (M5, Wi-Fi), iPadOS 26.6.1). This is not a claim for another device profile or build.

Availability and safety answer different questions. Availability is `proven`, `candidate`, `incompatible`, or `template`; dispatch policy remains `normal`, `explicit`, or `blocked`. Candidates are development-only and ordinary commands reject them. Incompatible and template entries never dispatch.

Evidence is structured. `runtime-literal` records byte-exact discovery in the iOS 26.5 simulator runtime (23F77) under Xcode 26.6, not physical behavior. `user-visual-pass` and `user-visual-fail` record the user’s observed result and exact proof scope. `profile-capability-mismatch` compares a route requirement with [`../device-profiles/ipad-pro-11-inch-m5-wifi-ipados-26.6.1-23g83.json`](../device-profiles/ipad-pro-11-inch-m5-wifi-ipados-26.6.1-23g83.json). CoreDevice acceptance alone never becomes visual proof.

| Section | Proven | Candidate | Incompatible | Template | Read |
|---|---:|---:|---:|---:|---|
| Settings | 0 | 1 | 0 | 0 | [`settings/ROUTES.md`](settings/ROUTES.md) |
| Accessibility | 2 | 1 | 0 | 0 | [`accessibility/ROUTES.md`](accessibility/ROUTES.md) |
| ActionButton | 0 | 0 | 1 | 0 | [`action-button/ROUTES.md`](action-button/ROUTES.md) |
| AppStore | 0 | 1 | 0 | 0 | [`app-store/ROUTES.md`](app-store/ROUTES.md) |
| AppleAccount | 0 | 11 | 0 | 4 | [`apple-account/ROUTES.md`](apple-account/ROUTES.md) |
| Apps | 2 | 59 | 1 | 4 | [`apps/ROUTES.md`](apps/ROUTES.md) |
| Battery | 1 | 0 | 0 | 0 | [`battery/ROUTES.md`](battery/ROUTES.md) |
| Bluetooth | 1 | 0 | 0 | 0 | [`bluetooth/ROUTES.md`](bluetooth/ROUTES.md) |
| Camera | 0 | 5 | 1 | 0 | [`camera/ROUTES.md`](camera/ROUTES.md) |
| Cellular | 0 | 0 | 2 | 0 | [`cellular/ROUTES.md`](cellular/ROUTES.md) |
| ClassKit | 0 | 1 | 0 | 0 | [`class-kit/ROUTES.md`](class-kit/ROUTES.md) |
| Classroom | 0 | 1 | 0 | 0 | [`classroom/ROUTES.md`](classroom/ROUTES.md) |
| Contactless | 0 | 2 | 0 | 0 | [`contactless/ROUTES.md`](contactless/ROUTES.md) |
| ControlCenter | 0 | 1 | 0 | 0 | [`control-center/ROUTES.md`](control-center/ROUTES.md) |
| Developer | 0 | 3 | 0 | 1 | [`developer/ROUTES.md`](developer/ROUTES.md) |
| Display | 0 | 8 | 0 | 0 | [`display/ROUTES.md`](display/ROUTES.md) |
| Ethernet | 0 | 1 | 0 | 0 | [`ethernet/ROUTES.md`](ethernet/ROUTES.md) |
| ExposureNotifications | 0 | 1 | 0 | 0 | [`exposure-notifications/ROUTES.md`](exposure-notifications/ROUTES.md) |
| Family | 0 | 3 | 0 | 0 | [`family/ROUTES.md`](family/ROUTES.md) |
| Focus | 0 | 2 | 0 | 1 | [`focus/ROUTES.md`](focus/ROUTES.md) |
| GameCenter | 0 | 2 | 0 | 0 | [`game-center/ROUTES.md`](game-center/ROUTES.md) |
| General | 4 | 38 | 2 | 2 | [`general/ROUTES.md`](general/ROUTES.md) |
| HomeScreenAndAppLibrary | 0 | 1 | 0 | 0 | [`home-screen-and-app-library/ROUTES.md`](home-screen-and-app-library/ROUTES.md) |
| Internal.Classic | 0 | 1 | 0 | 0 | [`internal-classic/ROUTES.md`](internal-classic/ROUTES.md) |
| InternetAccounts | 0 | 0 | 0 | 2 | [`internet-accounts/ROUTES.md`](internet-accounts/ROUTES.md) |
| MultitaskingAndGestures | 0 | 1 | 0 | 0 | [`multitasking-and-gestures/ROUTES.md`](multitasking-and-gestures/ROUTES.md) |
| Notifications | 0 | 2 | 0 | 0 | [`notifications/ROUTES.md`](notifications/ROUTES.md) |
| Passcode | 0 | 1 | 0 | 0 | [`passcode/ROUTES.md`](passcode/ROUTES.md) |
| Pencil | 0 | 1 | 0 | 0 | [`pencil/ROUTES.md`](pencil/ROUTES.md) |
| PersonalHotspot | 0 | 0 | 1 | 0 | [`personal-hotspot/ROUTES.md`](personal-hotspot/ROUTES.md) |
| PrivacyAndSecurity | 0 | 24 | 0 | 2 | [`privacy-and-security/ROUTES.md`](privacy-and-security/ROUTES.md) |
| SOS | 0 | 2 | 0 | 0 | [`sos/ROUTES.md`](sos/ROUTES.md) |
| ScreenTime | 0 | 11 | 0 | 0 | [`screen-time/ROUTES.md`](screen-time/ROUTES.md) |
| Search | 0 | 1 | 0 | 0 | [`search/ROUTES.md`](search/ROUTES.md) |
| SideButton | 0 | 1 | 0 | 0 | [`side-button/ROUTES.md`](side-button/ROUTES.md) |
| Siri | 0 | 13 | 0 | 3 | [`siri/ROUTES.md`](siri/ROUTES.md) |
| Sounds | 0 | 4 | 0 | 2 | [`sounds/ROUTES.md`](sounds/ROUTES.md) |
| StandBy | 0 | 0 | 2 | 0 | [`stand-by/ROUTES.md`](stand-by/ROUTES.md) |
| VPN | 0 | 1 | 0 | 0 | [`vpn/ROUTES.md`](vpn/ROUTES.md) |
| Wallet | 0 | 1 | 0 | 0 | [`wallet/ROUTES.md`](wallet/ROUTES.md) |
| Wallpaper | 0 | 1 | 0 | 0 | [`wallpaper/ROUTES.md`](wallpaper/ROUTES.md) |
| WiFi | 1 | 1 | 0 | 0 | [`wi-fi/ROUTES.md`](wi-fi/ROUTES.md) |
| iCloud | 0 | 1 | 0 | 0 | [`i-cloud/ROUTES.md`](i-cloud/ROUTES.md) |

Catalogue totals: **251 routes** — **11 proven**, **209 candidate**, **10 incompatible**, and **21 template**.

`observer-screenshot-pass` records direct agent inspection of an authorized screenshot on the exact profile.
