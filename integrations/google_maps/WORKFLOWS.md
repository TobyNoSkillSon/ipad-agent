# Google Maps maintenance

## Architecture

The application package owns semantic normalization, [`url-policy.json`](url-policy.json), exact-profile compatibility, instructions, and tests. Shared v2 routing owns declarative validation, canonical construction/parsing, manifest binding, unlock gating, and exactly-once CoreDevice dispatch. The target is always `com.google.Maps`; this is not an unrestricted web launcher.

## Commands

- `search`/`show`: `/maps/search/` with fixed `api=1`, required raw query, and optional query place ID.
- `directions`: `/maps/dir/` with fixed `api=1`, required destination, optional origin/place IDs, up to three ordered waypoints with matching IDs, travel mode, and avoid list. It omits `dir_action` and is a preview request.
- `map`: `/maps/@` with fixed `api=1`, fixed `map_action=map`, required center, and bounded zoom/basemap/layer.
- `street-view`: `/maps/@` with fixed `api=1`, fixed `map_action=pano`, required viewpoint, and bounded heading/pitch/fov.
- `link`: exact canonical parsing against those four command grammars. Routes containing `dir_action=navigate`, unknown fields, alternate hosts, ports, credentials, fragments, or undocumented paths fail.
- `navigate`: separate `/maps/dir/` grammar with fixed `dir_action=navigate`; explicit candidate only.

Raw values are encoded once. Callers supply waypoint lists; the adapter rejects pipes inside entries, enforces a mobile maximum of three, and validates matching place-ID cardinality before the policy builds `%7C` separators.

## Evidence

Google documentation establishes grammar, not installed-app rendering. Compatibility evidence is bound to Google Maps 26.33.1 on `iPad17,1` / `J817AP` / build `23G83`. Only inspected pixels can promote a route. Capture status and CoreDevice acceptance alone are insufficient.

Public evidence stores no query, URL, place, coordinate, route, screenshot, app/account state, or unique device identifier. Unknown post-dispatch state is uncertain and is never replayed.

## Protected boundary

`navigate` can start guidance and audio. The private maintenance probe is planning-only and rejects the old `allow_explicit=True` boolean. It returns a digest-bound `ScenarioPlan` and never dispatches. Review that exact plan, create a short-lived `PhysicalAuthorization.for_plan(...)` with the manifest's exact confirmation, then execute it once through `run_physical_scenario(..., physical=True, authorization=...)`. The manifest fixes one attempt; never reuse the authorization or retry an uncertain result. Permission, sign-in, and location prompts remain human-controlled. Saving, reviewing, sharing location, timeline access, and account mutation are outside the integration.
