---
name: ipad-apple-maps
description: Open Apple Maps or use proven map, search, place, Look Around, directions, guides, and link routes on the paired iPad.
---

# Apple Maps on iPad

Use ordinary app activation when the user asks to open Maps:

```python
from ipad_agent import ipadmaps
ipadmaps("open")
```

On product `iPad17,1`, hardware `J817AP`, build `23G83`, the ordinary proven route families are `frame`; `search` and its `show` alias; `place`; `look-around`; `directions` preview; `guides`; and validated full `link`.

`navigate` and `report-a-problem` remain candidates and require an explicit request plus a reviewed, plan-bound sealed-lab test. Production and the private planning helper reject direct dispatch. `navigate` may start guidance; `report-a-problem` stops at the sheet and never authorizes submission. A lost dispatch response is uncertain and must not be replayed.

Read [`WORKFLOWS.md`](WORKFLOWS.md) for command grammar, exact-profile evidence, safety boundaries, and candidate testing.
