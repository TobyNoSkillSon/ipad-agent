# Brave addon workflows

## Scope

Brave is an optional addon. The registry excludes it until `brave` appears in `enabled_addons`. Core operation must continue to work with Safari or another configured browser when Brave is absent or disabled.

The addon can foreground Brave, deliver one explicit HTTP or HTTPS URL, use Back or Reload on a task page, and open the tab overview without reading it. It has no close-tab, new-tab, menu, share, download, history, private-mode, or settings action.

## Instructions

### Durable Now behavior

The Now page is durable shared display state. It is not owned by an individual URL task.

1. Generated text, reports, tables, code, and local-display assets go through the standard Now display route, not `brave.open-url`.
2. The display route foregrounds Brave without a URL first. This gives an existing Now page time to acknowledge the new revision while preserving the selected tab.
3. Only the display router may deliver the fixed Now URL when acknowledgement fails. Do not type that URL into the address field or use the addon action to simulate recovery.
4. Never use Back, Reload, tab selection, or cleanup against the Now page.
5. After an external URL task, restore Now only by publishing the next artifact through the standard display route. Let its readiness acknowledgement determine whether URL recovery is needed.

This workflow matches the existing router contract. It does not promise that Brave keeps a particular tab selected or that CoreDevice URL delivery always creates a new tab.

### Task URL and cleanup

1. Confirm that the URL is explicit and uses `http` or `https`.
2. Run `activate` first. If the request is only to show a Now artifact, stop and use the display route instead.
3. Dispatch `open-url` once. Brave decides whether to reuse, create, or select a tab according to app state and settings.
4. Do not infer tab ownership from a successful dispatch, foreground change, matching URL, or recent creation time.
5. Use Back or Reload only when the visible non-Now page and its navigation history belong to the current task. Never reload a transaction or submitted form automatically.
6. `show-tabs` may establish that the overview is open, but the workflow must not read titles or thumbnails and must not select or close anything.
7. No automated cleanup follows ordinary CoreDevice URL delivery because this addon cannot prove which tab was created or reused.

A tab is task-owned only when a separate workflow records a before-state, performs the exact create-tab action, and confirms the corresponding new tab without inspecting unrelated tabs. This addon has no create-tab action, so it cannot establish that evidence. If another authorized workflow does establish ownership, it may close only that tab under exact cleanup authority. It must still preserve Now and every pre-existing tab.

Brave documents that tab-bar visibility, automatic inactive-tab closing, and private-tab retention are user settings: <https://support.brave.com/hc/en-us/articles/35938403203853-How-do-I-manage-my-tab-settings-on-iOS>. The addon does not inspect or change them.

## Selector rationale

The address predicate is retained for bounded identity and compatibility checks; no manifest action types into it. Brave has exposed app-owned accessibility IDs for Back, stop/reload, and Show Tabs. The Reload recipe combines the stop/reload identifier with the visible `Reload` label; the other controls use direct IDs. These avoid coordinates across portrait, landscape, and optional tab-bar layouts.

The stop/reload control can change meaning while a page loads. `reload-page` first runs a bounded three-second wait against the Reload-only predicate and taps only if it resolves. A visible Stop control therefore fails the action before mutation. Selectors are not cached because toolbar controls and tab overview elements can be rebuilt after navigation.

There are no selectors for Close, New Tab, Private, Menu, Share, Downloads, History, Shields, Sync, Wallet, or settings. XPath and coordinate fallbacks are prohibited.

## State, locale, and version caveats

Brave version, orientation, toolbar placement, tab-bar preference, private browsing, a loading page, and iPad window size can change the accessibility tree. CoreDevice URL delivery does not provide a durable contract for tab creation versus tab reuse. Browser history and website data can persist even when no tab is closed.

The manifest targets English selectors and iPadOS 17 or later, but compatibility is explicitly `unverified` and lists no verified Brave app version. Accessibility IDs are app implementation details and can change independently of iPadOS. A private window, biometric gate, first-run screen, crash restore, sync prompt, download prompt, or browser update prompt is a stop condition.

These selectors and workflows have not been exercised on a physical iPad in this change. Static tests prove addon gating and manifest structure only. They do not prove current Brave UI compatibility or tab behavior.

## Safety and retry classes

- `activate`: navigate and tab-preserving by intent; safe repeat only when Brave is not foreground.
- `open-url`: the executable step is `transient` and `inspect_then_decide`; the integration-level persistent-tab-state profile records that history, website data, and tab selection may outlive the action.
- Back and Reload: transient page navigation; `inspect_then_decide` after dispatch.
- tab overview: navigate; inspection is limited to overview-open state.
- lost response: assume URL or navigation may have occurred. Never resend, go Back to compensate, or close a tab.

The addon allows one attempt. Payments, forms, account changes, downloads, protected confirmations, private-state inspection, and browser-setting changes remain prohibited.

## Benchmark scenarios

These are future physical checks, not reported measurements.

| Scenario | Start state | Exercise | Pass condition |
|---|---|---|---|
| Addon disabled | Brave installed but not enabled | registry resolution | Brave remains unavailable; core registry loads |
| Existing Now acknowledgement | Now page already visible | publish through display route | Brave foregrounds without URL delivery and the same page acknowledges |
| Now recovery | Now page absent or stale | display-router recovery | fixed Now URL delivered at most once; fresh revision acknowledges |
| External task URL | ordinary Brave state | activate, one CoreDevice URL | requested page visible; no claim about tab creation or ownership |
| Tab overview boundary | task page visible | show Tabs | overview opens; no titles, thumbnails, selection, or close action captured |
| Lost URL response | transport closes after dispatch | visible-page inspection | no duplicate URL, Back compensation, or tab cleanup |
| Version mismatch | changed Brave toolbar | selector preflight | toolbar action stops without XPath or coordinates |

Record addon enablement, Brave version when available without account access, URL-dispatch phase, Now acknowledgement, selector lookup result, and whether WDA was torn down. Do not record URLs containing secrets, page content, tab inventory, history, or private state.

## Completion gates

A Brave task is complete only when:

- addon enablement was explicit;
- Now content used the display route and a visible readiness acknowledgement;
- an external URL was dispatched at most once;
- no tab ownership was inferred from URL delivery;
- no Now, unowned, pre-existing, or private tab was closed, selected, reordered, or grouped;
- any cleanup affected only a separately proven task-owned tab under exact authority;
- no browser settings, private data, forms, downloads, accounts, payments, or protected controls were touched;
- any WDA burst was torn down; and
- the report states that this implementation had no physical iPad or Brave verification.
