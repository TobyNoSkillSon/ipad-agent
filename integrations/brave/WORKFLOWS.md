# Brave route authority

## Boundary and addon gate

The public wrapper is `ipadbrave`. `website` and `youtube` retain their existing behavior. `search` is now proven and admitted. `private-website` remains candidate-gated. `ipfs` and `ipns` are incompatible on this exact profile after each accepted dispatch visibly left the prior route unchanged.

Brave remains an optional addon. The active configuration must include `brave` in `enabled_addons`. A disabled addon stays index metadata: its manifest and policy are not opened. After enablement, every admitted or maintenance route targets `com.brave.ios.browser` through CoreDevice.

The manifest contains direct activation and URL actions only. `open-url-direct` contains one HTTP(S) delivery and no prelaunch step. Custom-route action declarations bind search, private browsing, IPFS, and IPNS to separate v1 policy actions; no production scenario exposes the gated routes.

## Existing commands

### `website`

```python
from ipad_agent import ipadbrave
ipadbrave("website", "https://example.com/path?mode=compact#result")
```

Supply one absolute HTTP(S) URL with a nonempty authority. The established v1 action accepts paths, queries, fragments, and syntactically valid explicit ports. It rejects credentials, whitespace and controls, backslashes, malformed percent escapes, invalid ports, unsupported schemes, and values above 2,048 UTF-8 bytes.

### `youtube`

```python
from ipad_agent import ipadbrave
ipadbrave("youtube", "https://youtu.be/video-id", at=90)
```

Supply one HTTP(S) URL on `youtube.com`, `m.youtube.com`, `youtu.be`, or `youtube-nocookie.com`, optionally with one leading `www.`. `at` must be a finite non-negative integer or float. The adapter truncates it to whole seconds and writes or replaces `t=<seconds>s` before the unchanged website policy.

## Custom-route grammar

There is no candidate dispatch helper. Production admits `search`, rejects `private-website` before dispatch, and rejects incompatible IPFS/IPNS routes before dispatch. Any future private-route test first requires a sealed lab representation and exact authorization.

### `search`

The input is one raw string containing at least one non-whitespace character. Controls are rejected. Spaces and reserved characters are data, not caller encoding. The builder uses the exact source route with one field:

```text
brave://search?q=<percent-encoded-raw-query>
```

It emits uppercase percent escapes and encodes the raw value once. There are no extra fields, path, port, credentials, or fragment.

### `private-website`

The input is one HTTP(S) URL. The nested URL must have a host and no credentials, port, whitespace, controls, backslash, or malformed percent escape. The builder emits exactly:

```text
brave://open-url?url=<percent-encoded-http(s)-url>&private=true
```

The URL field is encoded once. Field order and the lowercase fixed boolean are mandatory. This candidate is explicit and privacy-sensitive. Compatibility work requires exact authorization for the displayed destination. Delivery may create or retain a private tab; the integration has neither identity-bound ownership nor automatic cleanup authority.

### `ipfs` and `ipns`

Both accept one exact lowercase URI. `ipfs` permits a CIDv0 authority (`Qm` plus 44 base58 characters) or a lowercase base32 CIDv1 authority (`b` plus 20–120 base32 characters). `ipns` permits either supported CID form or a canonical lowercase multi-label DNS name. Empty authorities, credentials, ports, whitespace, controls, backslashes, malformed percent escapes, and values above 2,048 bytes are rejected. Valid paths, queries, and fragments pass unchanged.

IPFS and IPNS are incompatible on this profile: each accepted exact-profile dispatch left the prior Brave route visible. Their source declarations and strict parsers remain fail-closed authority records, not permission to dispatch them again.

## Policy and manifest binding

[`url-policy.json`](url-policy.json) remains v1 and scheme-only. Its actions are intentionally separate:

| Action | Allowed schemes | Adapter-owned binding |
|---|---|---|
| `open-url` | `http`, `https` | Existing website and YouTube validation |
| `open-search` | `brave` | Exact `search` authority, empty path, sole `q` field |
| `open-private-website` | `brave` | Exact `open-url` authority, ordered `url` and fixed `private=true` fields |
| `open-ipfs` | `ipfs` | Strict CID authority and exact URI validation |
| `open-ipns` | `ipns` | Strict CID or DNS authority and exact URI validation |

The v1 scheme check cannot establish those host, path, or query constraints. Trusted app code builds and rechecks them before asking the action-specific policy to admit a URL. No function accepts an arbitrary Brave-scheme value.

## Exact-profile compatibility

[`route-compatibility.json`](route-compatibility.json) is bound to [`device-profiles/ipad17-1-j817ap-brave-1.93-136-ipados-26.6.1-23g83.json`](device-profiles/ipad17-1-j817ap-brave-1.93-136-ipados-26.6.1-23g83.json): Brave 1.93 build 136, product `iPad17,1`, hardware `J817AP`, iPadOS 26.6.1, build `23G83`. It contains no unique device identifier.

| Command | Availability | Production status |
|---|---|---|
| `website` | `proven` | `admitted` |
| `youtube` | `candidate` | `legacy-admitted` |
| `search` | `proven` | `admitted` |
| `private-website` | `candidate` | `candidate-gated` |
| `ipfs` | `incompatible` | `candidate-gated` |
| `ipns` | `incompatible` | `candidate-gated` |

Availability comes from evidence. Current upstream source on the `brave/brave-ios` development branch provides syntax authority through `NavigationRouter.swift` and `Info.plist`. Issue 627 and pull request 3582 supplement the search declaration. Source syntax, policy validation, fake execution, and CoreDevice acceptance do not prove rendered behavior.

The `website` observer record is metadata-only: evidence kind, actor, method, result, and non-unique product/hardware/build scope. It retains no screenshot, destination, URL, query, fragment, tab data, device identifier, or evidence-file reference. The screenshot was deleted after adjudication. Search also has exact-scope visible-result evidence. IPFS and IPNS each have exact-scope negative screenshot evidence: Brave remained on the prior search page after accepted delivery. Private website and YouTube have no exact-scope visual evidence.

The manifest's required compatibility marker remains `unverified` because v1 has no per-command status. The strict route authority carries the current distinction.

## Candidate test matrix

Only `private-website` remains candidate-gated. Review its exact value and static build first; never batch or replay a dispatched candidate. Search is already proven and admitted. IPFS and IPNS are incompatible on this profile and are not eligible for another maintenance probe.

| Candidate | Authorization | Pass condition |
|---|---|---|
| `private-website` | Exact destination plus explicit private-opening intent | The destination is visible in private browsing; no cleanup follows |

A lost response is uncertain because Brave may already have received the route. Inspect once with the user. Do not resend, close a tab, or use another route as compensation.

## Excluded routes

Do not expose or probe `open-text`, internal deep links, shortcut handlers, blank-tab routes, bookmarks, history, downloads, playlist, wallet, QR, Brave News, VPN promotion, settings, or arbitrary `brave://` payloads. Upstream registration does not make those routes part of this application boundary.

## Rendering and tab state

CoreDevice acceptance proves URL delivery only. It does not prove foreground state, network completion, content rendering, search results, distributed-content resolution, private mode, media playback, or tab choice. Brave may reuse a normal tab or create another one. A private candidate may leave a private tab.

The integration does not establish task-tab identity. It performs no automatic cleanup and makes no cleanup claim for normal or private tabs. Browser history and website data may persist according to Brave's existing settings.

## Offline maintenance

Static planning may use `activate-direct` without parameters or `open-url-direct` with one HTTP(S) `url`. Custom-route builders must use fakes for configuration, registry, and policy during tests. CI remains offline and must not contact a device.

Upstream references:

- [`NavigationRouter.swift`](https://github.com/brave/brave-ios/blob/development/Sources/Brave/Frontend/Browser/NavigationRouter.swift)
- [`Info.plist`](https://github.com/brave/brave-ios/blob/development/App/iOS/Supporting%20Files/Info.plist)
- [Issue 627](https://github.com/brave/brave-ios/issues/627)
- [Pull request 3582](https://github.com/brave/brave-ios/pull/3582)
