## ADDED Requirements

### Requirement: L4-AVL-013 A transient failure in a chain bounds the capacity wait
When no profile of a required chain is usable and at least one profile was skipped in that selection for a failure of the
`transient` class with no limit (a probe step that timed out, a `hello` that timed out or found its provider
unreachable), `retry_after` SHALL be the earlier of the earliest end of a cool-down in the chain and the time of the park
plus `availability.default_cooldown`. Without such a skip, `retry_after` SHALL stay as L4-AVL-007 says: the earliest
cool-down's end, else the time of the park. A missing binary, a failed login, a `hello` that was refused or answered
wrongly, an unsupported version, a constraint and `serves` SHALL NOT shorten the wait.

#### Scenario: SCN-AVL-33 (+) a timed-out hello next to a long cool-down waits the default, not the cool-down
- **WHEN** the judges' chain is `[slow, spent]`, `slow`'s hello times out (`transient`) and `spent` reports its credits
  used up with a reset 24 hours away
- **THEN** the unit parks in `waiting_capacity` with `retry_after` = the park + 30 minutes

#### Scenario: SCN-AVL-34 (−) a cool-down that ends sooner still sets the time
- **WHEN** `slow`'s hello times out and `spent` cools until 10 minutes after the park
- **THEN** `retry_after` is the end of `spent`'s cool-down

#### Scenario: SCN-AVL-35 (+) a chain that only timed out waits and does not stop the plan
- **WHEN** every profile of the chain times out at its hello, in two parks with no work between them
- **THEN** each park's `retry_after` is the park + 30 minutes, neither is fix-only, and the plan is not stopped with
  `capacity_needs_fix`

#### Scenario: SCN-AVL-36 (−) a failed login keeps the rule of L4-AVL-007
- **WHEN** one profile fails its login and another is cooling; or every profile fails its login or binary
- **THEN** `retry_after` is the cool-down's end; or the time of the park
