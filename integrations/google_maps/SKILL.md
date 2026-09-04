---
name: ipad-google-maps
description: Search, frame, preview directions, inspect Street View, or open a validated Google Maps link on the paired iPad.
---

# Google Maps on iPad

```python
from ipad_agent import ipadgooglemaps
ipadgooglemaps("open")
ipadgooglemaps("search", "Wawel Royal Castle, Kraków")
ipadgooglemaps("map", (48.85837, 2.29448), zoom=16, basemap="satellite")
ipadgooglemaps("directions", "Gdańsk", origin="Warsaw", travelmode="driving")
ipadgooglemaps("street-view", (48.85837, 2.29448), heading=35, pitch=5, fov=75)
ipadgooglemaps("link", "https://www.google.com/maps/search/?query=Colosseum%2C%20Rome&api=1")
```

`show` aliases `search`. Search accepts an optional `query_place_id`. Directions accepts optional `origin`, paired place IDs, up to three ordered `waypoints`, matching `waypoint_place_ids`, `travelmode`, and `avoid`. Map requires a coordinate and accepts zoom 0–21, basemap, and layer. Street View requires a viewpoint coordinate and bounded heading, pitch, and field of view.

All routes use Google’s documented `https://www.google.com/maps` URL grammar, are encoded once, capped at 2,048 bytes, and target the installed Google Maps bundle through one CoreDevice dispatch. `link` accepts only a canonical URL equivalent to one admitted non-navigation command.

Do not use `navigate` unless the user explicitly asks to start guidance for an exact reviewed route; it remains candidate-gated and any physical test must use a short-lived plan-bound sealed-lab authorization. Never infer current location, save places, post reviews, share location, alter an account, or approve prompts.

Success proves dispatch acceptance only. Use separately authorized pixel inspection for visible confirmation, and never replay an uncertain route.

See [`WORKFLOWS.md`](WORKFLOWS.md) for exact grammar and safety.
