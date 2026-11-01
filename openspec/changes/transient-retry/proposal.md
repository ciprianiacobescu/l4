## Why

A consumer's unit reached verification during a provider outage of about 25 minutes. The first judge was refused by
independence (same vendor as the implementer that finished the task), the hello of three free judges timed out at 60 s,
one judge reported that its credits were used up (a 24-hour cool-down), and the last had no key. Nothing was usable, so
the unit parked in `waiting_capacity` with `retry_after` 24 hours later. Ten minutes after the park the free judges'
hellos answered again, but no run would look before the next day; a person had to run `l4 retry` and `l4 yolo resume`.

`retry_after` is the earliest end of a cool-down in the chain (L4-AVL-007). A timed-out hello records no cool-down and is
not remembered (L4-AVL-005: the next run asks again), so it never sets the time: with one cooling profile in the chain,
the unit waits for that profile even when others failed for a cause that ends by itself in minutes.

## What Changes

- When a required chain has nothing usable and at least one profile was skipped for a transient failure (a probe step
  that timed out, a hello that timed out or found its provider unreachable: `failure_class` `transient`), `retry_after`
  is the earlier of the earliest cool-down's end and the park plus `availability.default_cooldown` (30 m).
- A chain whose only failures are transient waits `default_cooldown` too, in place of being due at once. Its park is no
  longer fix-only, so two such parks in a row no longer stop the plan with `capacity_needs_fix` and advice to renew a
  secret; the plan waits and the next trigger after the wait probes again.
- A missing binary, a failed login, a hello that was refused or answered wrongly, an unsupported version, a constraint
  and `serves` keep today's rule: with nothing cooling the unit is due at once (and two identical parks stop the plan),
  and next to a cooling profile the cool-down's end is the time, since a person fixes those.

## Impact

- Code: `l4.availability.fallback` (`_Walk.transient`, recorded in `_probe`, read by `_nothing_usable`), the docstring
  of `l4.state.parks`.
- Spec: L4-AVL-013 (new); the fix-only lists of L4-AVL-007 and L4-YOLO-035; SCN-AVL-33..36; change-table row 115.
- Cost: a chain that keeps timing out (a model that hangs) is probed again at each trigger after 30 minutes, up to the
  plan's `max_runs`, in place of a `capacity_needs_fix` stop after the second park.
- Not changed: the delegate (an optional role) defers or escalates as L4-DLG-013 says; a timed-out delegate hello still
  escalates the question.
