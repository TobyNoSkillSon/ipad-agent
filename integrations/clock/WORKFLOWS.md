# Clock workflows

## Scope

Clock supports tab navigation and one transient stopwatch. World Clock, Alarms, and Timers are view-only destinations. The stopwatch may run for the current task, but the task owns its cleanup and must leave it stopped at zero.

The integration does not add cities, operate alarms, configure timers, or record laps.

## Instructions

### Navigate to a tab

1. Activate Clock.
2. Require exactly one visible accessible button for the requested tab, then choose one of `open-world-clock`, `open-alarms`, `open-stopwatch`, or `open-timer` once.
3. Verify the selected tab and stop. A missing or non-unique button is a hard stop, not permission to broaden the selector or retry the tap.
4. Do not use Add, Edit, alarm switches, timer controls, or list rows.

Each tab has its own manifest scenario, so a request never runs several tab actions merely to declare coverage.

### Run a transient stopwatch

1. Activate Clock and open Stopwatch.
2. Run `inspect-stopwatch-state`. It inspects the stable reading identifier, then uses separate three-second gates for its exact zero value and the unique visible accessible Start button. If either gate fails, stop without a tap; a running or nonzero stopwatch is pre-existing state.
3. Only after those gates succeed, run `start-stopwatch` once. Do not call this action independently or after a failed baseline; its unique Stop button is the three-second transition gate.
4. At the requested end, run `stop-stopwatch` once. Three-second gates require unique visible accessible Start and Reset buttons before cleanup.
5. Run `reset-stopwatch` once. Its Start gate verifies the stopped control after the Reset response; then separately require exactly one `stopwatch_zero` readiness match without another tap.
6. The workflow is incomplete until the post-reset Start gate and direct zero-readiness check establish stopped and zero conditions.

Apple documents that the stopwatch keeps running after another app opens or the iPad sleeps, and that Stop followed by Reset clears it: <https://support.apple.com/guide/ipad/use-the-stopwatch-ipad2f9067d6/ipados>.

## Selector rationale

The supplied private physical evidence contains two unchanged inspections of one selected, reset Stopwatch state. The old label-only Stopwatch recipe admitted both an accessible tab button and its inaccessible duplicate. The revised tab predicates bind the exact button type and the labels exposed by the current UI—`World Clock`, `Alarms`, `Stopwatch`, and `Timers`—then require both `visible == 1` and `accessible == 1`. In the supplied state, each predicate resolves to one control in both inspections.

Start is likewise one accessible visible button in the supplied state; Lap is separately exposed but has no selector or action. Start, Stop, Reset, and `stopped_start` all use exact button predicates. Stop and Reset are state-transition expectations rather than physically observed controls in the reset state, so they fail closed if absent or non-unique.

`stopwatch_reading` binds the stable `stopwatch-time` accessibility identifier. `stopwatch_zero` binds that identifier and its exact observed value, `0 seconds`, while also requiring the accessible visible static-text element. Zero readiness and Start readiness remain separate baseline gates before Start. After Reset, the action gates on Start and the workflow separately requires direct `stopwatch_zero` readiness; no selector tries to infer one control from the other.

Elements are not cached because Start becomes Stop, and Stop becomes Start plus Reset as state changes. There are no selectors for Add, Edit, city rows, alarm switches, Lap, timer presets, or timer controls. XPath, coordinates, index recipes, and broad hierarchy fallbacks are excluded.

## State, locale, and version caveats

Clock preserves stopwatch state across app switches and sleep. A pre-existing nonzero or running stopwatch is user state unless the current task has recorded ownership. The workflow must not commandeer or reset it.

Portrait orientation can switch between digital and analog stopwatch faces by swiping. This integration does not swipe or depend on a face. Split View, Stage Manager, Dynamic Type, and an external keyboard can alter layout.

The manifest schema supports only compatibility `unverified`, so the manifest remains unverified and lists no verified Clock app version. The supplied evidence physically establishes selector cardinality only for one unchanged, selected, reset Stopwatch surface. Its recorded locale is unknown even though the exposed labels and zero value were English; it therefore establishes no locale-wide compatibility claim.

No physical tab tap, Start, Stop, Reset, elapsed-time transition, or end-to-end cleanup was exercised for this repair. The evidence does not cover another tab, running or stopped-nonzero state, another stopwatch face, Split View, Stage Manager, Dynamic Type, an external keyboard, a prompt, or another locale. Any mismatch is a hard stop.

## Safety and retry classes

- tab actions: navigate; repeat only after confirming the requested tab is not selected.
- Start, Stop, and Reset: transient, `inspect_then_decide` after dispatch.
- a lost response after Start can leave the stopwatch running. Inspect immediately; do not tap Start again.
- a lost response after Stop can leave either state. Inspect Start and Stop visibility.
- a lost response after Reset can leave the display at zero. Inspect before any further action.

The manifest permits one attempt per action. Cleanup is a required forward step, not a retry. If cleanup cannot be established, report the live or uncertain stopwatch state rather than claiming completion.

## Benchmark scenarios

The table defines future physical benchmarks. The supplied physical evidence is a repeated unchanged-state selector observation, not a lifecycle benchmark; no timings or state transitions were measured for this repair.

| Scenario | Start state | Exercise | Pass condition |
|---|---|---|---|
| Tab navigation | Clock on an arbitrary tab | one requested tab action | requested tab selected; no list item or control changes |
| Stopwatch lifecycle | stopped at zero | Start, brief wait, Stop, Reset | elapsed reading advanced, then returned to stopped zero |
| Background continuity | task-owned stopwatch running | foreground another app, return to Clock | elapsed time continued; Stop and Reset cleanup succeeds |
| Pre-existing state | stopwatch running or nonzero without task ownership | observation only | workflow refuses Start and Reset and reports the blocker |
| Lost Start response | response closes after tap | state inspection | no second Start; running state is handled once |
| Lost Reset response | response closes after tap | state inspection | zero state is accepted without another Reset |
| Locale mismatch | non-English Clock UI | selector preflight | workflow stops before any guessed tap |

Use a stopwatch duration long enough to observe a changed reading but short enough to clean up immediately. Record selector outcomes, state transitions, and cleanup result. Do not record existing alarms, cities, or timer values.

## Completion gates

A tab-navigation task is complete when the requested tab is visibly selected and no Clock item changed.

A stopwatch task is complete only when:

- the stopwatch was stopped at zero before this task claimed it;
- Start, Stop, and Reset were each dispatched at most once;
- no Lap action occurred;
- the final state is stopped at zero with Start visible;
- a lost response was resolved by state inspection, not replay;
- any WDA burst was torn down; and
- the report limits physical observation to the supplied unchanged selected/reset Stopwatch surface and does not imply end-to-end lifecycle or locale compatibility.
