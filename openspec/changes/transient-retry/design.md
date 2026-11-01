## Context

`FallbackSelector.select` walks a role's chain. A profile refused by `serves` or a constraint is skipped without a probe
and its cool-down key is not collected; every other profile's key goes to `walk.keys`. A cooling profile is skipped as
`cooling`; a probed profile that fails is skipped with the failed step, and a failure with a limit records a cool-down.
When nothing is usable in a required chain, `_nothing_usable` raises `WaitingCapacity` with
`retry = cooldowns.earliest_reset(walk.keys, now) or now`.

A failed probe step has a `failure_class` (`ProbeResult.failure_class`): `transient` for a step that timed out
(`StepTimedOut` in the ladder, a hello that timed out in `probes.hello_result` and `agents.command`) and for an OpenCode
hello whose provider was unreachable; `auth`, `other`, `limit` and `unsupported_version` for the rest; None for an
adapter error and for most failures of the binary, auth and quota steps. `_remember` caches no transient failure, so the
next selection probes the profile again.

`state.parks._fix_only` reads the park's `availability.unavailable`: a park is fix-only when no skip is `cooling`,
`quota` or `concurrency`, none has `resets_at`, and `retry_after` is within 2 s of the park. Two consecutive fix-only
parks for the same profiles stop the plan with `capacity_needs_fix` (L4-YOLO-035). A plan step never chains a run for a
parked unit; the planner dispatches it again once `retry_after` has passed.

## Decisions

### D1 A transient skip bounds the wait (L4-AVL-013)

`_Walk` gets `transient: list[str]`, the names of the profiles skipped in this selection for a failure whose
`failure_class` is `transient` and that has no limit. `_probe` appends the name when it records such a skip; `forget`
removes it with the profile's other records. `_nothing_usable` computes

```
reset = cooldowns.earliest_reset(walk.keys, now)
if walk.transient:
    soon = now + default_cooldown
    reset = soon if reset is None else min(reset, soon)
retry = reset or now
```

`availability.default_cooldown` (30 m) is already the wait of a limit with no reset and of a park whose exception names
no time (L4-OPS-009), so no new key is added. A cool-down that ends sooner still wins.

### D2 Only the transient class

A failed login, a refused or wrong hello, a missing binary, an unsupported version, a constraint and `serves` need a
person: today's rule stays for them (`test_mixed_auth_and_cooling_takes_the_cooling_reset`,
`test_auth_failure_parks_due_now_not_after_the_default_cooldown`). Making every non-cooling skip due at once would
dispatch a unit with a 24-hour cool-down and an expired key at every trigger, each run charged, with no
`capacity_needs_fix` stop (the cooling skip makes the park not fix-only). A busy login (`concurrency`) is waited for in
the selection (`login_lock_wait`) and is left as it is.

### D3 A transient park is not fix-only

With `retry_after` 30 minutes after the park, `_fix_only` already returns None (the time is in the future), so two
parks of a chain that only timed out no longer stop the plan with `capacity_needs_fix`, whose fix text (renew a secret,
install a binary) does not fit an outage. The plan waits with `waiting_capacity`, and the trigger after the wait probes
again. `parks.py` is not changed in behaviour; its docstring names the transient case.

## Limits

- A model that hangs on every hello is probed again at each trigger after 30 minutes until the plan's `max_runs` or a
  person stops it; the sticky note names the timeouts.
- The delegate is an optional role: its selection raises `RoleUnavailable` with no `retry_after`, and L4-DLG-013 still
  escalates a question whose delegate hello timed out.
