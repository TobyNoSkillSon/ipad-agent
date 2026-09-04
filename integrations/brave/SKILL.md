---
name: ipad-brave
description: Open an explicit website, search query, or YouTube URL in explicitly enabled Brave on the paired iPad through iPad Agent.
---

# Brave on iPad

Brave remains an addon. The runtime must list `brave` in `enabled_addons`; otherwise resolution fails before the addon manifest or URL policy is loaded.

```python
from ipad_agent import ipadbrave
ipadbrave("website", "https://example.com/path?view=full#section")
ipadbrave("search", "architecture references")
ipadbrave("youtube", "https://youtu.be/video-id")
ipadbrave("youtube", "https://www.youtube.com/watch?v=video-id", at=90)
```

Each admitted example is one call and causes at most one CoreDevice URL dispatch. There is no separate Brave prelaunch step.

## Admitted payloads

- `website` takes exactly one absolute `http://` or `https://` URL with a nonempty authority. Paths, queries, fragments, and valid explicit ports are allowed by the preserved v1 website policy. Credentials, whitespace or controls, backslashes, malformed percent escapes, invalid ports, and values over 2,048 UTF-8 bytes are rejected before dispatch.
- `search` takes one nonblank raw query, rejects controls, percent-encodes it once, and opens the exact `brave://search` route backed by Brave source.
- `youtube` takes one HTTP(S) URL whose host, after removing one leading `www.`, is `youtube.com`, `m.youtube.com`, `youtu.be`, or `youtube-nocookie.com`. Optional `at=` accepts a finite non-negative integer or float, truncates it to whole seconds, and writes or replaces `t=<seconds>s`. Other HTTP(S) destinations use `website`.

On Brave 1.93 build 136 for `iPad17,1` / `J817AP` / build `23G83`, `website` and `search` have exact-profile observer-screenshot-pass evidence and are proven. `youtube` has no separate rendered evidence and remains candidate, but stays public as `legacy-admitted` for backward compatibility.

## Gated and incompatible routes

The wrapper recognizes `private-website`, but production rejects it as a source-backed candidate because it creates persistent private-tab state without identity-bound cleanup.

- `private-website` is designed for one strict HTTP(S) URL without credentials or a port. Its exact route contains only the encoded URL and fixed `private=true`. It is privacy-sensitive, requires exact authorization during compatibility work, and may leave a private tab.
- `ipfs` and `ipns` remain recognized for fail-closed compatibility reporting, but one exact-profile dispatch of each left the prior Brave route visible. They are incompatible on this profile and cannot be probed again through the maintenance gate.

All custom routes share the 2,048-byte ceiling and reject credentials, ports, controls, whitespace, backslashes, and malformed percent escapes.

## Exclusions and caveats

The public surface does not expose arbitrary `brave://` values, `open-text`, internal deep links, shortcuts, blank tabs, bookmarks, history, downloads, playlist, wallet, QR, Brave News, VPN promotion, or settings routes.

Success proves CoreDevice accepted one URL delivery request. It does not prove Brave is foreground, the destination rendered, media played, or a timestamp took effect. Brave may reuse a normal tab or create another one. Candidate private delivery may leave a private tab. The integration establishes no tab ownership and performs no automatic cleanup. After an uncertain response, inspect with the user and do not replay the URL.

See [`WORKFLOWS.md`](WORKFLOWS.md) for source authority, candidate testing, and exact URI grammar.
