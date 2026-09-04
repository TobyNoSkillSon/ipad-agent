---
name: ipad-numbers
description: Open Numbers or send/show one supported local spreadsheet file on the paired iPad through iPad Agent.
---

# Numbers on iPad

```python
from ipad_agent import ipadnumbers
ipadnumbers("open")
ipadnumbers("drop", "/absolute/path/file.numbers")
ipadnumbers("show", "/absolute/path/file.numbers")
```

Accepted file extensions are `.numbers`, `.xls`, `.xlsx`, `.csv`, `.tsv`. The app-owned gate runs before the shared private AirDrop roots, extension, size, and timeout policy.

The operator selects the iPad in the macOS AirDrop sheet. Never automate recipient choice or replay an uncertain transfer. Sender callback completion does not prove receipt. Launching Numbers alone does not prove the exact file opened or imported. A fresh XLSX delivered through `show` has exact-profile screenshot evidence for receipt, import, and opening in Numbers; standalone `drop` and other file formats remain unverified.

No collaboration-link command exists because Apple publishes no stable token grammar and no task-owned generated sample is available. Never guess a scheme or construct an opaque collaboration identifier. Creating, editing, exporting, printing, sharing, or deleting remains outside this integration.

`open` is proven on the exact profile for Numbers 15.3 on `iPad17,1` / `J817AP` / build `23G83`. See [`WORKFLOWS.md`](WORKFLOWS.md).
