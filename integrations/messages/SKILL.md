---
name: ipad-messages
description: Open a blank Messages compose sheet on the paired iPad; recipient-specific preparation remains exact and send-free.
---

# Messages on iPad

```python
from ipad_agent import ipadmessages
ipadmessages("compose")
```

`compose` opens an empty Messages compose sheet through Apple’s documented `sms:` route. It supplies no recipient, body, or attachment and never sends.

`prepare` recognizes one exact caller-supplied phone number using a leading plus, digits, hyphens, and periods, but remains candidate-gated and non-dispatching until the route has a sealed lab plan and is visibly proven for an explicit user-provided recipient. Never invent a number. `open` is also kept out of ordinary use until a privacy-safe visible check is available.

Do not read message lists, open a thread by guessed identifier, prefill body text, attach files, select contacts, or press Send. A compose sheet may already have opened after an uncertain response; never replay.

See [`WORKFLOWS.md`](WORKFLOWS.md) for grammar and privacy boundaries.
