# Messages maintenance

## Route authority

Apple documents `sms:` and `sms:<number>`. The number grammar permits digits plus `+`, `-`, and `.`; this adapter tightens it to one optional leading plus and a bounded digit-led value. It never accepts a query, body, attachment, callback, thread ID, `sms://`, `messages://`, or `im:` route.

The public goal is preparation only. `compose` has no recipient or content. `prepare` requires a caller-supplied exact recipient and separate explicit pilot authority. Send and all confirmations remain manual.

## Privacy and evidence

Do not use screenshot observation that reveals conversation rows or recipient history. A blank compose sheet may be inspected only to establish route rendering, with no recipient or message content retained. Public evidence records only route family and non-unique product/hardware/build scope.

CoreDevice acceptance does not prove the compose sheet appeared. Unknown post-dispatch state is uncertain and is never replayed. Default-messaging choice, account setup, and protected prompts remain human-controlled.

## Candidate maintenance boundary

There is no candidate dispatch helper. A maintainer may build the existing candidate `open` activation plan directly with `plan_scenario(...)`; physical execution still requires review, a short-lived `PhysicalAuthorization.for_plan(...)`, and `run_physical_scenario(..., physical=True, authorization=...)`. The recipient-bearing `sms:` shape cannot currently be represented by the sealed v2 lab URL planner, so `prepare` remains production-gated and has no physical route. Add a reviewed sealed planner representation before any future test.
