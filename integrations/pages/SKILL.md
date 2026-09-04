---
name: ipad-pages
description: Open Pages or send/show one supported local document file on the paired iPad through iPad Agent.
---

# Pages on iPad

```python
from ipad_agent import ipadpages
ipadpages("open")
ipadpages("drop", "/absolute/path/file.pages")
ipadpages("show", "/absolute/path/file.pages")
```

Accepted file extensions are `.pages`, `.doc`, `.docx`, `.rtf`, `.txt`. The app-owned gate runs before the shared private AirDrop roots, extension, size, and timeout policy.

The operator selects the iPad in the macOS AirDrop sheet. Never automate recipient choice or replay an uncertain transfer. Sender callback completion does not prove receipt. Launching Pages alone does not prove the exact file opened or imported. A fresh DOCX delivered through `show` has exact-profile screenshot evidence for receipt, import, and opening in Pages; standalone `drop` and other file formats remain unverified.

No collaboration-link command exists because Apple publishes no stable token grammar and no task-owned generated sample is available. Never guess a scheme or construct an opaque collaboration identifier. Creating, editing, exporting, printing, sharing, or deleting remains outside this integration.

`open` is proven on the exact profile for Pages 15.3 on `iPad17,1` / `J817AP` / build `23G83`. A first-run “What’s New” Continue screen may require the user to proceed manually. See [`WORKFLOWS.md`](WORKFLOWS.md).
