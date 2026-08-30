# URL integration roadmap

CoreDevice can request the launch of an installed application by bundle identifier. Richer control depends on URLs that the receiving app documents or associates through Universal Links. This roadmap records candidates for source-backed integrations. It does not expand the current public API.

## Admission rule

An integration may enter the public surface only when all of these are true:

1. Apple or the app vendor documents the URL, or the vendor publishes a matching Apple App Site Association file.
2. The parser allowlists the exact scheme, host, path shape, and necessary parameters.
3. The route is classified as navigation, mutation, or protected action.
4. A bounded physical pilot confirms dispatch behavior without relying on retries.
5. The documentation states what acceptance proves and what remains unverified.

Private schemes copied from forum posts, guessed URL paths, credential-bearing links, payment routes, and account mutations are excluded.

## Current direct routes

| Integration | Route |
|---|---|
| Safari | HTTP and HTTPS websites |
| Brave | HTTP and HTTPS websites delivered to Brave |
| Apple Maps | Search query through `maps://` |
| App Store | Product page by App Store ID |

## Priority candidates

| App | Documented or associated URL surface | Candidate operation |
|---|---|---|
| Apple Maps | `https://maps.apple.com/search`, `/place`, `/directions` | Search, coordinates, place, directions and travel mode |
| Google Maps | `comgooglemaps://` and Google Maps HTTPS URLs | Search, map position and directions |
| Google Drive | Associated Drive file and folder links | Open an exact accessible file or folder |
| Discord | Associated `/channels/` and `/users/` links | Open a channel, message or profile |
| Chess.com | Associated member, game, analysis, lesson, puzzle and TV paths | Open read-only chess content |
| Allegro | Associated offer and listing paths | Open an offer or search results; exclude purchase flows |
| Pinterest | Associated Pin, board and profile links | Open exact content |
| ChatGPT | Documented `/share/` links | Open a shared conversation snapshot |
| Apple News | `https://apple.news/<token>` | Open an exact article |
| Apple Books | `https://books.apple.com/.../id<ID>` | Open a store item |
| Concepts | Vendor-generated `https://concepts.app/s/<id>` links | Open shared content |
| T3 Code | `t3code://` navigation routes | Open home, settings, connections, threads or files |
| Shortcuts | Documented `shortcuts://` routes | Open or run an existing saved shortcut after a public API is added |

## Generated-link candidates

These apps expose opaque links created by the app. The controller must accept an exact link rather than constructing identifiers:

- Freeform board collaboration links
- Find My Share Item Location links
- Photos and shared-album iCloud links
- Pages, Numbers and Keynote collaboration links
- Concepts shared-object links

## Explicit-only routes

These documented URL schemes can trigger calls, messages, imports, or account actions. Invoke them only when the user explicitly requests the exact operation:

- `mailto:` compose flows
- `sms:` recipient flows
- `facetime:` and `facetime-audio:` calls
- `tel:` calls
- UTM VM import or control
- credential-manager links
- financial account or trading destinations

## Launch-only applications

No stable public URL surface has been established for Calculator, Camera, Clock, Files, Health, Journal, Notes, Passwords, Preview, Reminders, Settings, Translate, Voice Memos, Weather, or Adobe Fresco. Bundle launch remains available. Private schemes such as `prefs:` and `mobilenotes:` are not candidates.

## Sources

- [Apple unified Maps URLs](https://developer.apple.com/documentation/mapkit/unified-map-urls)
- [Apple URL Scheme Reference](https://developer.apple.com/library/archive/featuredarticles/iPhoneURLScheme_Reference/Introduction/Introduction.html)
- [Run a shortcut using a URL](https://support.apple.com/guide/shortcuts/run-a-shortcut-from-a-url-apd624386f42/ios)
- [Google Maps URL Scheme for iOS](https://developers.google.com/maps/documentation/urls/ios-urlscheme)
- [Google Maps URLs](https://developers.google.com/maps/documentation/urls/get-started)
- [Supporting Universal Links](https://developer.apple.com/documentation/xcode/supporting-universal-links-in-your-app)

Before implementing an integration, verify its vendor documentation and Apple App Site Association file again.
