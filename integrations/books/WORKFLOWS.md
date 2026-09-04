# Books maintenance

## Boundary

`commands.py` owns four commands: `open`, `item`, `drop`, and `show`. Shared code owns CoreDevice, unlock handling, AirDrop, and result projection. The inert lab manifest is launch-only and cannot reintroduce the removed Reading Now, Library, Store, Search, selector, Appium, or WDA surface.

## Product authority

Apple documents web product links and `ibooks://assetid/<ID>`. The adapter accepts either a 5–20 digit positive asset ID or a canonical HTTPS product URL with exact host `books.apple.com`, lowercase two-letter storefront, `book` or `audiobook`, a bounded lowercase slug, and final `id<ID>`. It rejects credentials, ports, query strings, fragments, alternate hosts, redirects, search links, collections, arbitrary `ibooks://` input, and non-product paths.

An asset ID is converted to exact `ibooks://assetid/<ID>`. A supplied product URL is byte-preserved after complete validation. The full route is revalidated immediately before one CoreDevice dispatch.

Opening a product page is transient navigation, not authority to obtain, sample, download, buy, subscribe, or alter an account. Unknown post-dispatch state is uncertain and is never replayed.

## File authority

[`file-authority.json`](file-authority.json) permits `.epub` and `.pdf` only. The app gate runs before the shared private AirDrop policy; it cannot enlarge allowed roots, extensions, file size, or timeout. AirDrop sender completion and the `show` result alone do not prove that Books imported or displayed the transferred file. Separate exact-profile user-visual evidence establishes that outcome for one EPUB `show` test only.

## Compatibility

[`route-compatibility.json`](route-compatibility.json) binds non-unique product/hardware/build scope. `open` is proven from inspected pixels. `item` is source-backed and proven by an exact-profile screenshot of the requested product page. A valid route can still show an unavailable-item message when its storefront does not match the account region. `drop` remains candidate and `legacy-admitted`. `show` is proven and admitted from the recorded EPUB receipt/import/open result; that evidence does not establish standalone `drop` or PDF handoff.

No screenshots, product URLs, asset IDs, filenames, library contents, device identifiers, or raw responses belong in committed evidence.

## Manual EPUB evidence

A fresh harmless EPUB sent through `show` was selected manually in AirDrop and directly confirmed by the operator as imported and open in Books. This proves the EPUB `show` path only for the recorded profile. Standalone `drop` and PDF handoff remain unverified.
