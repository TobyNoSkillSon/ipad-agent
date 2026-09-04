---
name: ipad-books
description: Open Books, show an exact Apple Books product page, or send/show one local EPUB or PDF on the paired iPad.
---

# Books on iPad

```python
from ipad_agent import ipadbooks
ipadbooks("open")
ipadbooks("item", "https://books.apple.com/pl/book/foundation/id419950945")
ipadbooks("item", "419950945")
ipadbooks("drop", "/absolute/path/book.epub")
ipadbooks("show", "/absolute/path/document.pdf")
```

`item` accepts either a positive Apple Books asset ID or one canonical `https://books.apple.com/<country>/book|audiobook/<slug>/id<ID>` URL. It opens only the product page. Never obtain, sample, download, buy, or operate account/payment controls without a separate exact user request.

`drop` and `show` accept EPUB or PDF only. The operator selects the iPad in the macOS AirDrop sheet. Never automate recipient choice or replay an uncertain transfer. Sender callback completion does not prove receipt; launching Books does not prove import or exact opening.

`open` has exact-profile rendered evidence for Books 12.5 on `iPad17,1` / `J817AP` / build `23G83`. The item route is also proven on that profile; product availability still depends on the selected storefront and account region. A manually selected EPUB delivered through `show` has exact-profile user-visual evidence for receipt, import, and opening in Books. Standalone `drop` and PDF handoff remain unverified.

See [`WORKFLOWS.md`](WORKFLOWS.md) for grammar, evidence, and maintenance rules.
