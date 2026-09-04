---
name: ipad-photos
description: Open Photos or send/show one supported local photo or video file on the paired iPad through iPad Agent.
---

# Photos on iPad

```python
from ipad_agent import ipadphotos
ipadphotos("open")
ipadphotos("drop", "/absolute/path/file.heif")
ipadphotos("show", "/absolute/path/file.heif")
```

Accepted file extensions are `.heif`, `.heic`, `.jpg`, `.jpeg`, `.png`, `.gif`, `.tif`, `.tiff`, `.mp4`. The app-owned gate runs before the shared private AirDrop roots, extension, size, and timeout policy.

The operator selects the iPad in the macOS AirDrop sheet. Never automate recipient choice or replay an uncertain transfer. Sender callback completion alone does not prove receipt. A fresh PNG delivered through standalone `drop` has exact-profile screenshot evidence for receipt, persistent import, and opening in Photos; the generated fixture’s marker text was not visibly rendered. Launching Photos after transfer still does not prove the exact file opened.

No collaboration-link command exists because Apple publishes no stable token grammar and no task-owned generated sample is available. Never guess a scheme or construct an opaque collaboration identifier. Creating, editing, exporting, printing, sharing, or deleting remains outside this integration.

`open` is proven on the exact profile for Photos on `iPad17,1` / `J817AP` / build `23G83`. See [`WORKFLOWS.md`](WORKFLOWS.md).
