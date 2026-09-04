---
name: ipad-preview
description: Open Preview on the paired iPad or send/show one Preview-compatible local PDF or image through iPad Agent.
---

# Preview on iPad

```python
from ipad_agent import ipadpreview
ipadpreview("open")
ipadpreview("drop", "/absolute/path/document.pdf")
ipadpreview("show", "/absolute/path/image.png")
```

`open` foregrounds Preview. `drop` offers one app-approved PDF or image through the shared one-attempt AirDrop transport. `show` transfers once and then launches Preview.

The app-owned file gate accepts PDF and Preview-declared image formats only; it rejects office documents, archives, movies, EPUBs, and other extensions before AirDrop. The shared private AirDrop configuration must also allow the selected extension and path.

The operator selects the iPad in the macOS AirDrop sheet. Never automate recipient selection or retry an uncertain transfer. Host callback completion proves only that macOS completed its share attempt. `show` returns `pending` after sender completion and Preview launch because those steps alone do not prove receipt or exact opening. Claim either only from separate visible confirmation.

`open` has exact-profile rendered evidence for Preview 1.0 on `iPad17,1` / `J817AP` / build `23G83`. A manually selected PDF delivered through `show` has exact-profile user-visual evidence for receipt and opening in Preview. Standalone `drop`, image receipt, and generic file association remain unverified.

See [`WORKFLOWS.md`](WORKFLOWS.md) for the complete file authority and evidence boundary.
