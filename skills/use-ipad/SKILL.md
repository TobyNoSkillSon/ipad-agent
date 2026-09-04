---
name: use-ipad
description: Use the paired iPad through iPad Agent for applications, websites, maps, settings, files, media, messages, or other supported destinations.
---

# Use the iPad

Resolve the requested application in [`../../integrations/index.json`](../../integrations/index.json), then read only that application package's `SKILL.md` and follow it. For a multi-application request, read only the skills for the applications actually involved.

Reading an app skill loads it into the current session context; reuse that knowledge for repeated calls instead of copying or editing this gateway.

Run its bare Python call with the repository root as the working directory; installing the Pi skill does not install `ipad_agent` into the system Python environment.

For ordinary use, stop there. For investigation or maintenance, follow the app skill into its `WORKFLOWS.md`; read [`../../SECURITY.md`](../../SECURITY.md) for physical actions or uncertainty, [`../../README.md`](../../README.md) for public semantics, and [`../../docs/integrations/authoring.md`](../../docs/integrations/authoring.md) for integration development.
