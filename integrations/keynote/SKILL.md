---
name: ipad-keynote
description: Open Keynote or send/show one supported local presentation file on the paired iPad through iPad Agent.
---

# Keynote on iPad

```python
from ipad_agent import ipadkeynote
ipadkeynote("open")
ipadkeynote("drop", "/absolute/path/file.key")
ipadkeynote("show", "/absolute/path/file.key")
```

Accepted file extensions are `.key`, `.ppt`, `.pptx`. The app-owned gate runs before the shared private AirDrop roots, extension, size, and timeout policy.

The operator selects the iPad in the macOS AirDrop sheet. Never automate recipient choice or replay an uncertain transfer. Sender callback completion does not prove receipt. Launching Keynote alone does not prove the exact file opened or imported. A fresh PPTX delivered through `show` has exact-profile screenshot evidence for receipt, import, and opening in Keynote; the minimal fixture’s marker text was not visibly rendered. Standalone `drop` and other file formats remain unverified.

No collaboration-link command exists because Apple publishes no stable token grammar and no task-owned generated sample is available. Never guess a scheme or construct an opaque collaboration identifier. Creating, editing, exporting, printing, sharing, or deleting remains outside this integration.

`open` is proven on the exact profile for Keynote 15.3 on `iPad17,1` / `J817AP` / build `23G83`. See [`WORKFLOWS.md`](WORKFLOWS.md).
