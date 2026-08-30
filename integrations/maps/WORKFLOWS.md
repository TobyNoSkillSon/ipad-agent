# Maps workflows

## Scope

Use Maps for an explicit search, destination, or route preview. Prefer a Maps URL through CoreDevice. Start WebDriverAgent only when direct delivery is unavailable, and end the fallback after one query reaches visible suggestions.

This integration does not start turn-by-turn guidance, select an ambiguous suggestion, share a route, or edit Maps data. A search or destination may still appear in Maps Recents, so the manifest records map queries as user-data mutations.

## Instructions

### Search or show a destination

1. Percent-encode the caller's query as a URL parameter. Do not concatenate raw address text into a URL.
2. Dispatch `open-search` for a broad query or `open-destination` for a named destination. These actions use `maps://?q=...`.
3. Inspect only enough visible state to establish that Maps accepted the request and shows the intended text or place.
4. Stop. Do not select a different suggestion to make the result look plausible.
5. If URL delivery was confirmed unavailable, run `search-ui-fallback` once. Stop at suggestions. `dismiss-ui-fallback` may close the sheet when no result should remain open.

### Preview directions

1. Percent-encode `daddr`. If the caller supplied an origin, build `saddr` in the same way before dispatch. An omitted origin means “from here” and can invoke location access already granted to Maps.
2. Add `dirflg=d`, `w`, or `r` only for an explicit driving, walking, or transit request.
3. Dispatch one Maps URL. The core manifest shows the minimum `maps://?daddr=...` form; the caller constructs optional parameters.
4. Stop at route preview. Do not tap **Go**.

Apple's archived Map Links reference documents `q`, `saddr`, `daddr`, and `dirflg`: <https://developer.apple.com/library/archive/featuredarticles/iPhoneURLScheme_Reference/MapLinks/MapLinks.html>.

## Selector rationale

`MapsSearchTextField` is an app-owned accessibility identifier and avoids depending on where the search sheet sits. It is used only for fallback input. The Dismiss predicate includes `visible == 1` to avoid a hidden duplicate. Neither selector is cached because Maps rebuilds sheets while a query changes.

The manifest has no result-row selector. Result layouts, sponsored entries, guides, and search suggestions can make positional or label-only selection ambiguous. XPath and coordinates would make that worse.

## State, locale, and version caveats

Direct URLs are the least layout-dependent route, but Maps can choose its own sheet, map region, and recent-history behavior. Route availability and mode depend on the destination and network state. Current-origin directions depend on existing Maps location permission; this workflow cannot grant or change it.

The fallback selectors target an English UI and iPadOS 17 or later, but compatibility is explicitly `unverified` and lists no verified Maps app version. The Dismiss label is localized. Apple can change private accessibility identifiers without notice. Split View, Stage Manager, an existing route sheet, and a first-run prompt can change what is visible. Stop on any prompt or selector mismatch.

These selectors and workflows have not been exercised on a physical iPad in this change. Static schema and contract tests do not establish device compatibility.

## Safety and retry classes

- `activate`: navigate, safe to repeat only when it was not dispatched or Maps is demonstrably not foreground.
- direct URL actions: transient map query with possible Recents persistence, `inspect_then_decide` after dispatch.
- UI input and Dismiss: transient UI state, `inspect_then_decide` after dispatch.
- lost response: assume the URL or query may have arrived. Do not send it again until visible state proves otherwise.

One action attempt is the manifest limit. A UI fallback is a different route, not an automatic retry, and requires evidence that direct delivery did not occur.

## Benchmark scenarios

These are proposed device benchmarks, not measured results.

| Scenario | Start state | Exercise | Pass condition |
|---|---|---|---|
| Direct place search | Maps backgrounded, network available | encoded `q` URL | intended query or place is visible; WDA never starts |
| Directions preview | Maps backgrounded, location permission unchanged | encoded `daddr`, optional `saddr` and mode | route preview is visible; guidance has not started |
| Bounded fallback | direct delivery unavailable, English UI | one search-field entry | suggestions are visible after one WDA burst; no row is selected |
| Lost response | transport closes after dispatch | observation only | no duplicate URL or query is sent |
| Locale mismatch | non-English UI | direct URL, then selector preflight | direct path may proceed; fallback stops before an unmatched selector |

Record CoreDevice acceptance, whether WDA started, selector lookup outcome, final visible state, and cleanup outcome. Do not record the user's location or full address in benchmark artifacts.

## Completion gates

A Maps task is complete only when:

- the requested query, destination, or route preview is visibly established;
- no turn-by-turn guidance is running;
- no ambiguous suggestion was selected;
- WDA was never started for a successful direct path, or its single fallback burst was torn down;
- a lost response was handled by inspection rather than replay; and
- the report says whether physical verification occurred. For this implementation, it did not.
