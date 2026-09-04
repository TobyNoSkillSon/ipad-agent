# Safari route authority

## Boundary

The public wrapper remains `ipadsafari`, with exactly two commands: `website` and `youtube`. Both are one-call CoreDevice routes to `com.apple.mobilesafari`; neither starts a separate activation or UI-automation phase. The inert [`url-policy.json`](url-policy.json) preserves the v1 scheme boundary: `open-url` accepts only HTTP and HTTPS and caps the URL at 2,048 UTF-8 bytes.

The manifest contains direct `activate` and `open-url` actions for static lab authority. `open-url-direct` contains only the URL action, so it does not imply a prelaunch ceremony. Production commands dispatch the URL exactly once after input, compatibility-authority, registry, and v1-policy validation.

## Command grammar

### `website`

```python
from ipad_agent import ipadsafari
ipadsafari("website", "https://example.com/path?mode=compact#result")
```

Supply one string containing an absolute HTTP(S) URL with a nonempty authority. The established policy accepts paths, queries, fragments, and syntactically valid explicit ports. It rejects credentials, whitespace and control characters, backslashes, malformed percent escapes, invalid ports, unsupported schemes, and values above 2,048 UTF-8 bytes. There are no keyword options.

`website` already covers `music.youtube.com` and every other destination that satisfies this general HTTP(S) policy.

### `youtube`

```python
from ipad_agent import ipadsafari
ipadsafari("youtube", "https://youtu.be/video-id", at=90)
```

Supply one HTTP(S) URL on `youtube.com`, `m.youtube.com`, `youtu.be`, or `youtube-nocookie.com`, optionally with one leading `www.`. `at` is optional; it must be a finite non-negative integer or float, is truncated to whole seconds, and writes or replaces the `t=<seconds>s` query value. No other keyword is accepted. This is a convenience transformation before the same v1 HTTP(S) policy and exactly-once dispatcher; it is not a separate Safari scheme.

## Exact-profile compatibility

[`route-compatibility.json`](route-compatibility.json) is bound to [`device-profiles/ipad17-1-j817ap-safari-26.6.1-ipados-26.6.1-23g83.json`](device-profiles/ipad17-1-j817ap-safari-26.6.1-ipados-26.6.1-23g83.json): Safari 26.6.1, product `iPad17,1`, hardware `J817AP`, iPadOS 26.6.1, build `23G83`. The profile is model/build scoped and contains no unique device identifier.

Availability is derived from evidence:

- `candidate`: Apple documents the source syntax, but no exact-scope rendered result exists for that command.
- `proven`: exact-scope user visual or observer-screenshot evidence shows the expected content, with no conflicting failure.
- `incompatible`: exact-scope failure evidence exists, with no conflicting pass.

Current status:

| Command | Availability | Production status | Reason |
|---|---|---|---|
| `website` | `proven` | `admitted` | An authorized CoreDevice delivery was directly adjudicated from an observer screenshot on the exact profile. |
| `youtube` | `candidate` | `legacy-admitted` | Apple's documentation supports the underlying HTTP(S) payload syntax, but no separate exact screenshot proves the YouTube convenience. It remains public for backward compatibility. |

The public evidence record for the observer pass is metadata-only: fixed evidence kind, actor, method, result, and non-unique product/hardware/build scope. It retains no screenshot, destination, URL, query, fragment, tab data, device identifier, or evidence file reference. The private screenshot was deleted after adjudication. Official documentation, policy validation, fake execution, and CoreDevice acceptance are not rendering proof.

The manifest's required compatibility marker remains `unverified` because that v1 schema has no per-command state. The separate strict authority above carries the truthful route-level distinction and is checked before policy or device dispatch.

## Explicit exclusions

Apple or simulator registration is not sufficient authority for extra routes. Do not add or send:

- `x-web-search` or `x-safari-https`;
- FTP or `webclip`;
- private-tab or extension routes;
- guessed, private, insecure, simulator-only, or redundant schemes.

Use `website` for ordinary HTTP(S) destinations, including `music.youtube.com`. The exclusions prevent redundant or unstable aliases from widening the command surface.

## Rendering, tabs, and retry

An accepted result means CoreDevice accepted the URL delivery request. It does not prove foreground state, network completion, page rendering, media playback, timestamp application, or tab choice. Safari decides whether to reuse the current normal tab or create another one. Delivery may persist history, website data, and tab state.

The integration does not create identifiable task tabs, inspect tab inventory, or own a close control. It therefore performs no automatic tab cleanup and makes no cleanup claim. Never use tab counts, positions, or bulk closure as compensation.

Input and authority failures occur before dispatch. Once dispatch begins, a timeout, nonzero launch result, or lost response is uncertain: the URL may already have arrived. Inspect with the user and never replay automatically. Do not submit forms, download files, alter settings or accounts, make payments, enter private browsing, or handle protected confirmations through this boundary.

## Offline maintenance

Static planning may use `activate-direct` with no parameters or `open-url-direct` with one `url` parameter. Fake plans verify only manifest and harness behavior. CI remains offline and must not contact a device.

Apple source: [URL Scheme Reference — About Apple URL Schemes](https://developer.apple.com/library/archive/featuredarticles/iPhoneURLScheme_Reference/Introduction/Introduction.html). It establishes HTTP(S) source syntax, not exact-profile rendering.
