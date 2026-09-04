---
name: ipad-app-store
description: Open App Store or show one exact App Store product page on the paired iPad through iPad Agent.
---

# App Store on iPad

```python
from ipad_agent import ipadappstore
ipadappstore("open")
ipadappstore("show", 361309726)
ipadappstore("show", "https://apps.apple.com/app/pages/id361309726")
```

`show` accepts a positive 5–20 digit product ID, optional `id` prefix, or one canonical HTTPS `apps.apple.com` app-product URL. URLs may include a lowercase two-letter storefront and slug, but no credentials, port, query, fragment, redirect, collection, search, or arbitrary path.

Stop at the product page. Never press a price, Get, cloud-download, update, subscribe, account, payment, rating, review, or confirmation control without a separate exact user request.

Both `open` and `show` have exact-profile rendered evidence on `iPad17,1` / `J817AP` / build `23G83`. CoreDevice acceptance alone still proves only dispatch, and uncertain delivery is never replayed.

See [`WORKFLOWS.md`](WORKFLOWS.md) for canonical grammar and evidence boundaries.
