# App Store maintenance

## Public adapter

`commands.py` owns exactly `open` and `show`. `show` converts a positive product ID to `https://apps.apple.com/app/id<ID>` or byte-preserves one fully validated canonical product URL. The complete route is revalidated immediately before a single CoreDevice dispatch.

Accepted URL paths are `/app/id<ID>`, `/app/<slug>/id<ID>`, and the same forms under a lowercase two-letter storefront. The host and scheme are exact; credentials, ports, queries, fragments, non-app media, collections, searches, and redirects are rejected.

The lab manifest is launch-only. Historical Today, Games, Apps, Arcade, Search, selector, Appium, and WDA actions are removed because the semantic adapter never exposed them.

## Safety and evidence

Product-page navigation is transient. It does not authorize Get, price, cloud download, update, subscription, account, payment, rating, review, or confirmation actions. A nonzero or lost post-launch response may already have delivered the route; inspect and do not replay.

Exact-profile observer evidence proves App Store visibility and one requested app product page. It does not prove availability, compatibility, ownership, installation state, price, acquisition, or completion. Committed evidence contains no product ID, URL, screenshot, device identifier, account state, or raw response.
