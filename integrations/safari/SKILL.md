---
name: ipad-safari
description: Open an explicit website or YouTube URL in Safari on the paired iPad through the existing iPad Agent Safari command.
---

# Safari on iPad

```python
from ipad_agent import ipadsafari
ipadsafari("website", "https://example.com/path?view=full#section")
ipadsafari("youtube", "https://youtu.be/video-id")
ipadsafari("youtube", "https://www.youtube.com/watch?v=video-id", at=90)
```

Each example is one call and causes at most one CoreDevice URL dispatch. There is no separate Safari prelaunch step.

## Supported payloads

- `website` takes exactly one absolute `http://` or `https://` URL with a nonempty authority. Paths, queries, fragments, and valid explicit ports are allowed by the preserved v1 policy. Credentials, whitespace or controls, backslashes, malformed percent escapes, invalid ports, and URLs over 2,048 UTF-8 bytes are rejected before dispatch.
- `youtube` takes exactly one HTTP(S) URL whose host, after removing one leading `www.`, is `youtube.com`, `m.youtube.com`, `youtu.be`, or `youtube-nocookie.com`. Optional `at=` accepts a finite non-negative integer or float, truncates it to whole seconds, and writes or replaces the `t=<seconds>s` query value. `music.youtube.com` and every other ordinary HTTP(S) destination remain available through `website`; they are not added to the narrower YouTube convenience allowlist.

Apple's public URL documentation establishes HTTP(S) browser payload syntax, not visible rendering. On Safari 26.6.1 for `iPad17,1` / `J817AP` / build `23G83`, the `website` route has exact-profile observer-screenshot-pass evidence and is `proven`. The `youtube` convenience has no separate exact rendered evidence and remains `candidate`, but stays public as `legacy-admitted` to preserve the existing API. Candidate here means “not separately visually proven,” not “blocked.” See [`WORKFLOWS.md`](WORKFLOWS.md) for the authority and evidence boundary.

## Exclusions and caveats

Registered or observed names `x-web-search`, `x-safari-https`, FTP, and `webclip` are explicitly excluded. Private-tab routes, extension routes, guessed schemes, and simulator-only registrations are also excluded; only HTTP and HTTPS cross the v1 policy.

Success proves CoreDevice accepted one URL delivery request. It does not prove Safari is foreground, the destination rendered, or which normal tab received it. Safari may reuse the current normal tab or create another one and may retain history or website data. The command establishes no tab ownership and makes no tab-cleanup claim. After an uncertain response, inspect with the user and do not replay the URL.
