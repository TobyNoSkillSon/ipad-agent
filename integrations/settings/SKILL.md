---
name: ipad-settings
description: Open Settings or an exact-profile visually proven Settings destination on the paired iPad through CoreDevice.
---

# Settings on iPad

Use one semantic call. `open` activates the Settings app without claiming a page:

```python
from ipad_agent import ipadsettings
ipadsettings("open")
```

These shortcuts are proven only for product `iPad17,1`, hardware `J817AP`, OS build `23G83`:

```python
ipadsettings("general")
ipadsettings("about")
ipadsettings("wifi")
ipadsettings("bluetooth")
ipadsettings("battery")
ipadsettings("accessibility")
```

`show` accepts one of these exact, visually proven route IDs:

- `accessibility`
- `accessibility-motion-title`
- `apps-com-apple-mobilesafari`
- `apps-com-apple-mobilesafari-row-private-browsing-uses-normal-browsing-search-engine-selection`
- `battery`
- `bluetooth`
- `general`
- `general-about`
- `general-international`
- `general-keyboard`
- `wi-fi`

```python
ipadsettings("show", "general-keyboard")
```

Each call dispatches at most once. Row destinations only navigate to a row; they never operate its control. Candidate, incompatible, template, blocked, unknown, URL, and parameterized inputs fail before CoreDevice.

For deeper navigation, start at [`catalogue/README.md`](catalogue/README.md), choose the relevant section, and read only that section’s `ROUTES.md`. Those documents distinguish proven routes from development-only candidates and non-dispatchable entries. Apple does not support the private scheme, and CoreDevice acceptance alone does not prove that a destination rendered.
