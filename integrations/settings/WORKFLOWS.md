# Settings route maintenance

## Target profile

Ordinary deep-link navigation is proven only for the non-unique model/build profile in [`device-profiles/ipad-pro-11-inch-m5-wifi-ipados-26.6.1-23g83.json`](device-profiles/ipad-pro-11-inch-m5-wifi-ipados-26.6.1-23g83.json): product `iPad17,1`, hardware `J817AP`, OS build `23G83`. The profile contains no unique device identifier. Its model/build fields come from `devicectl`; marketing and hardware capabilities come from Apple’s technical specification.

A compatibility statement applies only when `product_type`, `hardware_model`, and `os_build` all match the evidence `proof_scope`. A different value in any field requires new direct visual evidence and a separate profile/build assessment.

## Evidence and availability

[`route-catalog.json`](route-catalog.json) preserves 251 byte-exact `settings-navigation://` routes. Evidence is structured:

- `runtime-literal`: exact bytes found in the iOS 26.5 simulator runtime (23F77) under Xcode 26.6; this is discovery evidence, not physical compatibility.
- `user-visual-pass`: the user saw the expected target on the bound proof scope.
- `observer-screenshot-pass`: the agent directly inspected an authorized project-owned WDA screenshot and saw the expected target on the bound proof scope; the private screenshot was then deleted.
- `user-visual-fail`: the user saw a different result on the bound proof scope.
- `profile-capability-mismatch`: a route requires a capability absent from the bound profile.

Availability is derived independently from safety policy:

- `proven`: user-visual-pass or observer-screenshot-pass on the exact target scope, without conflicting failure evidence;
- `candidate`: concrete route retained for controlled development testing;
- `incompatible`: negative visual evidence or a profile capability mismatch;
- `template`: dynamic route requiring substituted data.

The current totals are 11 proven, 209 candidate, 10 incompatible, and 21 template. The StandBy routes are incompatible because the profile has `standby=false`. `stand-by-always-on-display-options` also records that Settings launched while the prior Apple Intelligence & Siri page remained visible.

Safety policy remains `normal`, `explicit`, or `blocked`. It does not imply availability. Fragments navigate to rows only. Query actions, dynamic values, payment and account-changing destinations, install/profile/update/reset flows, passcode targets, and other mutation-adjacent routes remain blocked.

## Production boundary

`open` performs ordinary Settings app activation without a page claim. Named shortcuts and `show` dispatch only the exact 11 proven IDs whose evidence scope matches the target profile. Candidate, incompatible, template, blocked, action-kind, unknown, URL, and parameterized inputs fail before CoreDevice. A permitted call uses the shared CoreDevice direct-open primitive once; there is no retry or selector fallback.

CoreDevice acceptance proves dispatch only. It never creates user-visual evidence, and a lost response is not permission to replay the request.

## Controlled candidate testing

Candidates stay outside the app skill and there is no candidate dispatch helper. Physical candidate work requires a separately designed sealed lab plan and exact short-lived authorization; incompatible, template, blocked, action-kind, and dynamic entries remain ineligible.

When a candidate is tested, record the directly inspected visible result, actor, method, and exact proof scope. Promote it only after a user visual pass or an agent-inspected authorized screenshot on this profile/build. Screenshot capture without pixel inspection and CoreDevice acceptance without a visible confirmation both remain insufficient.

## Documentation and checks

Agents start at [`catalogue/README.md`](catalogue/README.md), select one section, and read that folder’s `ROUTES.md`. Section files show availability, scoped evidence, kind, and policy while omitting raw URLs. The JSON catalogue remains the sole URL authority.

Run app-local offline tests and manifest validation after catalogue, profile, adapter, or documentation changes. These checks may parse data, import the adapter, mock direct-open, and verify one-call behavior; they must not contact a device.
