# URL integration roadmap

CoreDevice can request an installed app launch by bundle identifier. Richer control depends on vendor-documented URLs or associated Universal Links. This roadmap separates production routes from candidates; it does not expand the public API.

## Admission rule

A vendor URL route may enter production only when:

1. Apple or the app vendor documents the URL, or the vendor publishes a matching Apple App Site Association file.
2. A parser allowlists the exact scheme, host, path, required fields, and target bundle.
3. The route is classified as navigation, mutation, or protected action.
4. A trusted app-local adapter exposes only reviewed commands, with a local skill and offline contract tests.
5. Static release checks prove parser and dispatch invariants.
6. A bounded physical pilot supplies exact-profile visible evidence before any compatibility claim.
7. Public documentation states what success proves and what remains unknown.

Private schemes copied from forums, guessed paths, credential-bearing links, payment routes, and account mutations are excluded. Candidate helpers return sealed plans or remain non-dispatching. Physical work needs an exact short-lived plan-bound authorization as specified in [`SECURITY.md`](SECURITY.md).

## Indexed applications

The index contains 15 packages: 14 core packages plus optional Brave. `package.json` registers only the `use-ipad` gateway; each app's `SKILL.md` is loaded on demand through `integrations/index.json`.

| Integration | Current boundary |
|---|---|
| Safari | HTTP and HTTPS websites |
| Brave, optional | Website and search proven; private browsing candidate; IPFS/IPNS incompatible on the recorded profile |
| Apple Maps | Open plus seven proven Unified URL route families; navigation and report candidates |
| Google Maps | Open, search, map, directions preview, Street View, and canonical links proven; navigation candidate |
| Settings | Profile-bound proven `settings-navigation://` destinations through CoreDevice |
| Files | Open and AirDrop; ZIP `drop` proven only as generic system-preview receipt, not Files ownership; `show` unproven |
| Clock | App launch |
| Preview | Open and AirDrop; PDF `show` proven |
| Books | Product pages and AirDrop; EPUB `show` proven |
| App Store | Strict product page by positive ID or canonical product URL |
| Pages | DOCX `show` proven for receipt/import/open, not general content fidelity |
| Numbers | XLSX `show` proven for receipt/import/open, not general content fidelity |
| Keynote | PPTX `show` proven for receipt/import/open, not general content fidelity |
| Photos | PNG `drop` proven for persistent import/open, not content fidelity; `show` unproven |
| Messages | Blank compose proven; recipient routes remain outside V1 |

Mail is unsupported and not indexed. No Mail application adapter, skill, or draft flow remains; separate candidate Settings destinations may still refer to Mail settings.

The app `route-compatibility.json` files are release-validated metadata attestations for their recorded profiles. Raw physical evidence remains private, so these sidecars are not independently reproducible proof and must not be generalized to other versions, formats, or route variants.

## Maps status

For product `iPad17,1`, hardware `J817AP`, iPadOS `26.6.1`, build `23G83`, Apple Maps proves frame, search/show, place, Look Around, directions preview, guides, and validated full links. `navigate` and `report-a-problem` remain explicit candidates. Ordinary `ipadmaps("open")` remains available.

The static Apple Maps policy also understands vendor-documented navigation and report grammar so it can validate sealed maintenance plans. Static validation, plan construction, fake execution, or CoreDevice acceptance does not prove rendering or authorize physical execution.

Google Maps proves search, map, directions preview, Street View, and canonical-link routes on the recorded profile. `navigate` remains an explicit candidate and production rejects it before dispatch.

## Deferred candidates

| App | Documented or associated URL surface | Candidate operation |
|---|---|---|
| Google Drive | Associated Drive file and folder links | Open an exact accessible file or folder |
| Discord | Associated `/channels/` and `/users/` links | Open a channel, message, or profile |
| Chess.com | Associated member, game, analysis, lesson, puzzle, and TV paths | Open read-only chess content |
| Allegro | Associated offer and listing paths | Open an offer or search results; exclude purchase flows |
| Pinterest | Associated Pin, board, and profile links | Open exact content |
| ChatGPT | Documented `/share/` links | Open a shared conversation snapshot |
| Apple News | `https://apple.news/<token>` | Open an exact article |
| Concepts | Vendor-generated `https://concepts.app/s/<id>` links | Open shared content |
| T3 Code | `t3code://` navigation routes | Open home, settings, connections, threads, or files |
| Shortcuts | Documented `shortcuts://` routes | Open or run an existing saved shortcut after a public API is added |

## Generated-link candidates

These apps expose opaque links created by the app. A future controller must accept an exact caller-owned link rather than constructing an identifier:

- Freeform board collaboration links
- Find My Share Item Location links
- Photos and shared-album iCloud links
- Pages, Numbers, and Keynote collaboration links
- Concepts shared-object links

## Explicit-only routes

These documented schemes can trigger communication, imports, or account actions. Any future work needs an explicit request for the exact operation:

- recipient-bearing `sms:` flows; blank Messages compose is the only admitted Messages route
- `facetime:` and `facetime-audio:` calls
- `tel:` calls
- UTM VM import or control
- credential-manager links
- financial account or trading destinations

`mailto:` is outside V1 because Mail is unsupported and absent from the index.

## Launch-only applications

No stable vendor-public content URL surface has been established for Calculator, Camera, Clock, Files, Health, Journal, Notes, Passwords, Preview, Reminders, Translate, Voice Memos, Weather, or Adobe Fresco. A low-level bundle or installed-name launch may remain available without adding an indexed semantic package. Settings' profile-bound catalogue is not a general vendor-public URL surface. Private schemes such as `prefs:` and `mobilenotes:` are excluded.

## Sources

- [Apple unified Maps URLs](https://developer.apple.com/documentation/mapkit/unified-map-urls)
- [Apple URL Scheme Reference](https://developer.apple.com/library/archive/featuredarticles/iPhoneURLScheme_Reference/Introduction/Introduction.html)
- [Run a shortcut using a URL](https://support.apple.com/guide/shortcuts/run-a-shortcut-from-a-url-apd624386f42/ios)
- [Google Maps URL Scheme for iOS](https://developers.google.com/maps/documentation/urls/ios-urlscheme)
- [Google Maps URLs](https://developers.google.com/maps/documentation/urls/get-started)
- [Supporting Universal Links](https://developer.apple.com/documentation/xcode/supporting-universal-links-in-your-app)

Verify vendor documentation and the current Apple App Site Association file again before implementation. Source coverage allows design and testing; exact-profile compatibility authority decides whether a route is proven, candidate, or incompatible.
