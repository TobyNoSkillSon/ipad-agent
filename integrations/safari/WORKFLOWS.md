# Safari workflows

## Scope and status

Safari is the built-in core browser and the configured example default. That routing choice is not compatibility evidence. Production scenarios are limited to foregrounding Safari, explicit HTTP(S) URL delivery, the durable Now routes, and bounded toolbar inspection. Compatibility remains `unverified`.

URL delivery may reuse the current normal tab or create persistent tab state. CoreDevice acceptance proves dispatch only; it does not prove which tab received the URL or that the page became visible. The integration has no production task-tab creation or cleanup action. Exact automatic cleanup is unsupported because no exact current-task tab identity and identity-bound close control have been established. Two historical pilot task tabs remain as bounded residue and must not be touched.

Raw evidence, URLs, UI source, identifiers, and tab information remain private under `.runtime/lab/`. Never inspect or publish tab titles, thumbnails, inventory, or counts.

## Explicit URL route

1. Use `show-web-page` only with one caller-supplied absolute HTTP or HTTPS URL.
2. The strict Safari URL-policy manifest allows only `http` and `https`. Planning rejects unsupported schemes, malformed URLs, whitespace/control characters, bad escaping, and URL credentials before execution.
3. `accepted` means CoreDevice accepted dispatch. A visible result requires a separate permitted observation; do not infer it from timing or transport success.
4. A lost response is uncertain. Do not replay the URL, use Back as compensation, create a tab, or claim ownership.
5. URL delivery can leave history, website data, or persistent tab state under Safari's existing settings. There is no automatic cleanup claim.

## Now display and recovery

1. Publish generated and local artifacts through the normal display route, not the generic URL scenario.
2. `display-now-page` first foregrounds Safari without URL delivery so the durable Now page can acknowledge.
3. Only after that readiness attempt fails may the display router use `recover-now-page` once with its fixed private-LAN HTTP Now URL and a fresh revision.
4. `browser-visible-ready` is a Now acknowledgement, not a synonym for CoreDevice acceptance.
5. A locked CoreDevice result is terminal: the outcome fails as locked and no URL, WDA, selector, retry, or later step follows.
6. Stop on Local Network, certificate, connection-privacy, or other interstitials. Never bypass them or close, reload, navigate, or repurpose the durable Now tab.

## Bounded toolbar observation

`inspect-toolbar-bounded` may inspect only the retained unique visible accessible Address, Tabs, and New tab toolbar controls in the observed regular-width state. Address carries dynamic context; do not interpret, bind, or publish it. This scenario must not tap the Tabs or New tab controls. Zero or multiple matches, a prompt, or a changed layout is terminal.

The toolbar observations do not authorize tab overview entry, tab creation, selection, grouping, reordering, closure, or cleanup. Those production scenarios and actions are intentionally absent.

## Safety and retry

- Activation sends no URL and starts no WDA.
- URL delivery is one attempt and may mutate persistent browser state.
- Reverify the exact physical authorization immediately before every step.
- Stop on a locked device, a prompt/interstitial, uncertain dispatch, selector ambiguity, or unclear state.
- Never enter private browsing, inspect unrelated browser data, submit forms, download files, change settings, or perform account, payment, destructive, or protected actions.
- Never use Close All, count/position-based cleanup, generic Close controls, XPath, or coordinates.

The retained evidence boundary is narrow and does not establish public compatibility. `compatibility-v1.json` remains empty and unverified.
