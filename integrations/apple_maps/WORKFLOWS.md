# Maps route maintenance

## Authority and target

Ordinary `ipadmaps("open")` activation targets `com.apple.Maps` without a page or rendering claim. Route construction is owned by [`url-policy.json`](url-policy.json): exact `https://maps.apple.com` paths and parameters, canonical encoding, bundle binding, and the 2,048-byte UTF-8 limit. The inert manifest declares only the activation and direct URL actions required to bind that policy; selectors remain empty, and the two candidate scenarios exist only for sealed-lab planning and execution. These declarations do not bypass the compatibility gate in `commands.py`.

Compatibility is separate in [`route-compatibility.json`](route-compatibility.json). It is bound to the non-unique model/build profile in [`device-profiles/ipad-pro-11-inch-m5-wifi-ipados-26.6.1-23g83.json`](device-profiles/ipad-pro-11-inch-m5-wifi-ipados-26.6.1-23g83.json): product `iPad17,1`, hardware `J817AP`, iPadOS `26.6.1`, build `23G83`. The profile contains no unique identifier.

## Instructions

### Command grammar

All values passed to the Python adapter are raw; the policy percent-encodes them once.

### Open and frame

- `ipadmaps("open")` — ordinary app activation; no arguments.
- `ipadmaps("frame", center=(lat, lon), span=(lat_delta, lon_delta), mode=..., heading=..., pitch=..., distance=..., map=...)`
- `ipadmaps("frame", lat, lon)` — coordinate convenience.

`frame` requires at least one field. `span`, `heading`, `pitch`, and `distance` require `center`. Coordinates use geographic latitude/longitude bounds; span deltas are positive; heading and pitch are finite; distance is finite and non-negative. Tracking `mode` is `follow`, `follow-with-heading`, or `none`. Map style is `explore`, `driving`, `transit`, `satellite`, or `hybrid`; `map_type=` aliases `map=`. The adapter preserves supplied tracking, camera, span, and style fields rather than inventing defaults.

### Search, place, and Look Around

- `ipadmaps("search", query, center=(lat, lon), span=(lat_delta, lon_delta))`
- `ipadmaps("show", query, ...)` — exact alias of `search`; it inherits search compatibility.
- `ipadmaps("place", address=..., coordinate=(lat, lon), place_id=..., name=..., map=...)`
- `ipadmaps("place", lat, lon)` or `ipadmaps("place", lat, lon, name)`
- `ipadmaps("look-around", address=...)`, `coordinate=(lat, lon)`, or `place_id=...`
- `ipadmaps("look-around", lat, lon)`

Search requires a non-empty query; its `span` requires `center`. Place requires at least one of address, coordinate, or Place ID and may also carry a name and map style. Look Around requires exactly one locator. Place IDs are opaque and are not resolved offline. The documented `my-location` and `parked-car` IDs depend on Maps state and permissions and can expose sensitive location information.

### Directions and navigation

- `ipadmaps("directions", destination, source)`
- `ipadmaps("directions", destination, source=..., source_place_id=..., destination_place_id=..., waypoint=[...], waypoint_place_id=[...], mode=..., avoid=[...], transit_preferences=[...])`
- `origin=` aliases `source=`; `waypoints=` aliases `waypoint=`; `waypoint_place_ids=` aliases `waypoint_place_id=`.
- `ipadmaps("navigate", destination, ..., start=non_negative_integer)` accepts the same route fields and uniquely requires `start`.

Destination is required. Source Place ID requires source. Waypoint Place IDs require waypoints and must match their count and order. Modes are `driving`, `walking`, `transit`, and `cycling`. Avoidances are `tolls`, `highways`, `hills`, `busy-roads`, and `stairs`. Transit preferences are `bus`, `subway`, `commuter`, and `ferry`, and require transit mode. An omitted source lets Maps use current location only if permission already exists. `directions` rejects `start`; only `navigate` can include it.

### Guides, report sheet, and links

- `ipadmaps("guides")` — no arguments.
- `ipadmaps("report-a-problem", address=...)`, `coordinate=(lat, lon)`, or `place_id=...`; positional latitude/longitude is accepted.
- `ipadmaps("link", url)` or `ipadmaps("link", url=...)`.

Report requires exactly one locator and stops at Apple’s sheet. `link` accepts one canonicalizable full Unified Maps URL covering frame, search, place, Look Around, directions preview, or guides. It rejects credentials, ports, fragments, malformed escapes, duplicates, unknown fields, invalid parameter combinations, directions containing `start`, and report-sheet URLs. Use the explicit commands for navigation and report requests.

A clean `https://maps.apple/<path>` short link or true subdomain may be resolved once on the Mac during an explicitly authorized candidate test. The redirect is not followed further; its target must pass the same full-link policy. Offline tests replace this resolver.

## Evidence lifecycle

The structured evidence kinds are:

- `official-documentation`: Apple’s source for the endpoint shape; never rendered proof.
- `user-visual-pass`: the user saw the expected route on the exact product, hardware, and build scope.
- `observer-screenshot-pass`: the agent directly inspected a project-owned WDA screenshot and saw the expected route on that exact scope.
- `user-visual-fail`: the user saw a different or absent target on that exact scope.
- `profile-capability-mismatch`: the route requires a boolean capability absent from that exact profile.

Evidence is strictly shaped and deterministically ordered: documentation, user pass, observer screenshot pass, user fail, capability mismatch. A positive is either exact-scope pass. A negative is either fail or mismatch. Positive and negative evidence on one route conflict and invalidate the authority.

Availability is derived from evidence:

- `candidate` — source-backed with no direct rendered result;
- `proven` — at least one exact-scope positive and no negative;
- `incompatible` — at least one negative and no positive.

The current exact-profile authority has seven proven route families: `frame`, `search` (including `show`), `place`, `look-around`, `directions`, `guides`, and `link`. `navigate` and `report-a-problem` remain candidates. Production rejects candidate and incompatible routes before configuration, registry loading, route resolution, or device dispatch.

Observer screenshots are direct rendered evidence, not transport evidence. Screenshot files are private ephemeral `.runtime/` state and are deleted after testing. The public authority stores only the evidence kind, fixed actor and method, fixed outcome, and exact non-unique proof scope. It stores no screenshot, hash, URL, locator, query, or route detail. CoreDevice acceptance, static validation, official documentation, or a successful URL build cannot promote a route.

After a proven production gate, the adapter lazily loads configuration and one active registry snapshot, resolves the canonical command through that snapshot, and sends the resulting validated route through the shared validated CoreDevice boundary. Route dispatch terminates existing Maps app state before launch to isolate the requested view; this was required for the proven directions preview. The boundary preserves policy-digest and target revalidation, lock gating, structural results, and one dispatch.

The internal maintenance probe is absent from exports, public wrappers, `COMMANDS`, and the skill. It is planning-only: it accepts only `navigate` and `report-a-problem` while they remain candidates, applies the normal argument conveniences, and returns a sealed-lab `ScenarioPlan` whose parameters and validated route are digest-bound. It never loads device configuration or dispatches. The old `allow_explicit=True` boolean is rejected because it is not authorization. Review the plan, create a short-lived `PhysicalAuthorization.for_plan(...)` containing the exact required confirmation, and execute it once only through `run_physical_scenario(..., physical=True, authorization=...)`. Proven, incompatible, open, unknown, and arbitrary inputs are rejected.

## Candidate test matrix

Build and review the private probe plan for only the displayed row, then create its short-lived plan-bound authorization and pass both to the sealed physical lab runner. The manifest fixes `max_attempts` at one. Test one row at a time, inspect the rendered result, record redacted evidence, and resolve any uncertain result before another attempt. Never batch, reuse an authorization for a second runner invocation, or replay.

| Order | Candidate | Minimal reviewed exercise | Pass condition |
|---:|---|---|---|
| 1 | `report-a-problem` | Reviewed locator with explicit report-sheet intent | Sheet is visible; nothing is entered or submitted |
| 2 | `navigate` | Reviewed route and delay with explicit guidance intent | Maps handles the start request; no retry follows uncertainty |

Record only the route command, evidence kind, fixed verdict fields, and exact proof scope in repository authority. Keep screenshot files and private route inputs under `.runtime/`, then delete ephemeral screenshots after testing.

## Safety and uncertainty

A route call may affect Maps Recents. Never share a route, change permissions, edit guides or saved places, select ambiguous results, authenticate, pay, or approve a protected action. The report command never authorizes form submission.

CoreDevice acceptance proves only that the launch request was accepted. It does not prove Maps came forward, content rendered, a route preview appeared, navigation started, or a report sheet opened. A response lost after dispatch is `uncertain`; inspect with the user and do not send the URL again.

## Official sources

- [Unified Maps URLs](https://developer.apple.com/documentation/mapkit/unified-map-urls)
- [Identifying unique locations with Place IDs](https://developer.apple.com/documentation/mapkit/identifying-unique-locations-with-place-ids)
- [Coordinate validity](https://developer.apple.com/documentation/corelocation/cllocationcoordinate2disvalid(_:))

These sources establish syntax and semantics. They do not establish rendered behavior on the target profile/build.
