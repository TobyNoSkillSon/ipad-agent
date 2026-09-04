---
name: ipad-clock
description: Open the Clock application on the paired iPad through the existing iPad Agent Clock command.
---

# Clock on iPad

```python
from ipad_agent import ipadclock
ipadclock("open")
```

`open` is the complete public surface. It accepts no arguments and performs one unlock-gated CoreDevice activation. On product `iPad17,1`, hardware `J817AP`, build `23G83`, an authorized screenshot showed Clock visible.

No supported Clock URL payload exists. Alarm, timer, stopwatch, World Clock, App Intent, selector, and Shortcuts operations are not exposed. A successful call means launch acceptance; do not replay an uncertain launch.
