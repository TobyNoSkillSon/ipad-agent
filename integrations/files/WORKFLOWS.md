# Files workflows

## Scope

Files support is limited to foregrounding the app and navigating to Recents, Browse, or Search. A caller-supplied search term may remain visible for the user. The integration must not inspect result rows, enumerate storage, open content, or mutate files.

Apple documents Recents, Browse, and Search in the iPad User Guide: <https://support.apple.com/guide/ipad/find-and-view-files-and-folders-ipadb3b759ed/ipados>.

## Instructions

Normal workflows use only the named selector readiness and action calls below. They do not request page source, screenshots, broad hierarchy inspection, coordinates, or item lists.

### Recents

1. Activate Files.
2. Check `recents-selected`. If exactly one control is ready, Recents is already selected; stop.
3. Otherwise require exactly one `recents` control, run `open-recents` once, and require exactly one `recents-selected` control.
4. Stop before any file or folder row. A missing or non-unique readiness/verification match is a hard stop, not permission to retry the tap or broaden the selector.

### Browse

1. Activate Files.
2. Check `browse-selected`. If exactly one control is ready, Browse is already selected; stop.
3. Otherwise require exactly one `browse` control, run `open-browse` once, and require exactly one `browse-selected` control.
4. Do not enter a provider, storage location, tag, folder, or shared location. A missing or non-unique match is a hard stop.

### Search

1. Activate Files and check `search-field`.
2. If exactly one field is already visible, do not tap Search again. Otherwise require exactly one `search` button, run `focus-search` once, and require exactly one `search-field`.
3. If the request includes an exact term, run `enter-search` once against `search-field`, then require that the same field remains uniquely visible.
4. Do not inspect the accessibility hierarchy or query matching rows. Do not return names, counts, metadata, locations, thumbnails, or snippets.
5. Do not open a result. Leave the query in place unless the caller explicitly asks for a separate allowed navigation action.

The More menu, context menus, drag and drop, selection mode, provider/location rows, file rows, and result rows are outside this integration.

## Selector rationale

The supplied private evidence contains two unchanged-state accessibility inspections. In that state, the old label-only Recents recipe admitted an accessible navigation control, its inaccessible duplicate, and a heading. Recents and Browse each also exposed an inaccessible duplicate control. The revised base predicates bind the exact button type and English label, then require both `visible == 1` and `accessible == 1`; selected state is deliberately excluded so the same base selector can resolve before or after selection. In the supplied state, each base destination predicate resolves to one control in both inspections.

`recents-selected` and `browse-selected` add only `selected == 1` for state verification. The supplied state directly supports selected-state verification for Recents and unselected-state readiness for Browse. Browse-after-tap selection is a symmetric workflow expectation, not a compatibility claim; stop if it is absent or non-unique.

The supplied state directly supports one accessible visible Search button after the button type and accessibility constraints are applied. `search-field` is a separate SearchField predicate because typing into the button was incorrect. The supplied state did not include an expanded Search field, so that selector remains a bounded, unverified post-tap expectation and must fail closed.

Selectors are not cached because Files can replace its navigation hierarchy when view state changes. There are deliberately no selectors for providers, locations, tags, folders, files, results, More, Select, or context-menu items.

## State, locale, and version caveats

The evidence supports only the unchanged visible English state supplied for this fix. It does not establish behavior in a hidden sidebar, compact width, Split View, Stage Manager, an active provider, a first-run prompt, another locale, or another Files/iPadOS state. The manifest therefore remains compatibility `unverified`, with no verified app version.

No physical navigation, tap, typing, or focused-search inspection was performed for this change. Static checks plus the supplied evidence can establish current-state selector cardinality, not end-to-end device compatibility. Prompts and any selector mismatch are stop conditions.

## Safety and retry classes

- `activate`: navigate and safe to repeat.
- Recents, Browse, and focus Search: transient UI navigation; preflight current state, dispatch at most once, then verify only the named state selector.
- entering a term: transient UI state; it does not authorize reading results.
- a lost tap or typing response may already have changed state. Use only selector readiness to inspect the destination/search control; never replay automatically.
- file creation, rename, move, copy, share, download, upload, tag, deletion, provider traversal, and item inspection are prohibited.

The manifest permits one attempt. Readiness and verification mean resolving one named control selector, not collecting page source or file data.

## Benchmark scenarios

These scenarios define future bounded checks. No timings or pass rates were collected here.

| Scenario | Start state | Exercise | Pass condition |
|---|---|---|---|
| Recents already selected | Recents selected | state preflight only | one `recents-selected`; no tap |
| Recents navigation | Browse selected | preflight, one Recents tap, verification | one `recents-selected`; no item opens |
| Browse already selected | Browse selected | state preflight only | one `browse-selected`; no tap |
| Browse navigation | Recents selected | preflight, one Browse tap, verification | one `browse-selected`; no provider or folder opens |
| Search already expanded | visible Search field | field preflight only | one `search-field`; no Search-button tap |
| Search focus | supplied-style initial navigation state | one Search-button tap, field verification | one `search-field`; no result is inspected |
| Visible search term | visible Search field | enter a synthetic non-private term | field remains uniquely visible; results are not inspected |
| Selector mismatch | changed or localized state | selector-only preflight | workflow stops without hierarchy, XPath, or coordinate fallback |
| Lost response | transport closes after tap or typing | state-only selector readiness | no second tap or duplicate typing occurs |

Use a synthetic term for future tests. Any private evidence must exclude screenshots and must not retain or report filenames, provider names, location names, result rows, or content.

## Completion gates

A Files task is complete only when:

- the requested Recents or Browse control is uniquely selected, or the Search field is uniquely visible;
- preflight skipped the mutation when that state was already ready;
- no selector broadened beyond the named accessible visible control;
- no file, folder, provider, storage location, or search result was opened or enumerated;
- no file names, result counts, metadata, contents, or locations were returned or retained;
- no More menu, context menu, selection mode, or mutation control was used;
- any WDA burst was torn down; and
- the report distinguishes supplied current-state selector evidence from unperformed end-to-end physical verification. No end-to-end physical workflow was performed for this change.
