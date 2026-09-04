---
name: ipad-files
description: Open Files on the paired iPad or transfer/show one explicitly selected local regular file through iPad Agent.
---

# Files on iPad

```python
from ipad_agent import ipadfiles
ipadfiles("open")
ipadfiles("drop", "/absolute/path/file.pdf")
ipadfiles("show", "/absolute/path/file.pdf")
```

`open` foregrounds Files. `drop` offers one path admitted by the shared private AirDrop roots, extension, and size policy. `show` transfers once and then launches Files.

The operator selects the iPad in the macOS AirDrop sheet. Never automate recipient selection or replay an uncertain transfer. Host callback completion alone does not prove receipt. A fresh ZIP delivered through `drop` has exact-profile screenshot evidence for receipt and opening in the system preview. Launching Files still does not prove the exact transferred file is visible or selected.

There is no supported command for Recents, Browse, Search, an arbitrary Files path, provider traversal, SMB credentials, or file enumeration. Do not infer one from `shareddocuments://` or `smb://` bundle registration.

`open` has exact-profile rendered evidence for Files 1.0 on `iPad17,1` / `J817AP` / build `23G83`. The generic ZIP `drop` path is proven on that profile; exact Files ownership/visibility through `show` remains unverified.

See [`WORKFLOWS.md`](WORKFLOWS.md) for route exclusions and evidence boundaries.
