# Clock maintenance

## Public boundary

Clock is launch-only. `commands.py` exposes `open`, which performs one CoreDevice activation. No current Apple documentation supplies a Clock URL grammar for alarms, timers, stopwatch state, or top-level tabs. Siri/App Intent and Shortcuts actions are not CoreDevice payloads and do not enlarge this integration.

The previous selector-era tab and stopwatch actions were removed. WDA, Appium, labels, coordinates, and lifecycle controls are not part of normal Clock operation.

## Compatibility

[`route-compatibility.json`](route-compatibility.json) binds launch evidence to [`device-profiles/ipad17-1-j817ap-clock-1.1-ipados-26.6.1-23g83.json`](device-profiles/ipad17-1-j817ap-clock-1.1-ipados-26.6.1-23g83.json). The authorized screenshot was inspected, recorded only as metadata, and deleted. It proves Clock was visible on that exact product/hardware/build scope; it proves no tab or clock operation.

## Safety and checks

Dispatch once after unlock. A lost response is uncertain and is never replay authority. Do not inspect or alter alarms, timers, stopwatch state, cities, or protected settings. App-local tests stay offline and verify the one-command adapter, manifest, evidence metadata, and absence of selector-era behavior.
