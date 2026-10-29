## Purpose

A server error that OpenCode reports only in its message is a transient failure: it is not cached, the hello is tried
once more, and an in-run call is retried as L4-AVL-006 says.

## MODIFIED Requirements

### Requirement: L4-AVL-002 (amendment)
A status that the CLI gives only in its message, as `[NNN]` at the start, SHALL be read as the structured status.

### Requirement: L4-AVL-005 (amendment)
An error with no status SHALL be classed by its words: a 5xx, "unavailable", "overloaded", a timeout or a reset
connection is `transient`, and is not cached.

### Requirement: L4-AVL-006 (amendment)
The one more `hello` after 20 s SHALL apply to every adapter whose hello reads an error event (claude, OpenCode 1.x and
2.x): only for an error event of the transient class, with the deadline checked before and after the wait. A limit,
an auth failure, a wrong answer, an unsupported version and a hello that timed out SHALL NOT be tried again. OpenCode's
run path SHALL mark an error of the transient class as transient, so judge, verifier-agent and clarifier calls retry it
in the run.

#### Scenario: SCN-AVL-28 (+) a 503 named only in the message is transient
- **WHEN** an OpenCode 1.x hello's error event has no `statusCode` and the message `[503] … Service temporarily
  overloaded`
- **THEN** the hello's class is `transient`, its reason names status 503, and nothing is cached for the profile

#### Scenario: SCN-AVL-29 (+) a transient hello is tried once more
- **WHEN** the first hello of an OpenCode profile gets that error and the second answers
- **THEN** the probe passes after one wait of 20 s, and `availability.selected` shows `hello_retry_wait_s: 20`

#### Scenario: SCN-AVL-30 (−) a second transient error is final
- **WHEN** both hellos get the error
- **THEN** the profile is skipped as transient after two hellos, with no third, and is asked again at the next
  selection

#### Scenario: SCN-AVL-31 (−) what is not tried again
- **WHEN** the hello's error is a 401, out of credits, a 429 in the message, a 400, or the hello times out
- **THEN** there is one hello and no wait, and the classes are auth, limit, limit, other and transient as before

#### Scenario: SCN-AVL-32 (+) an OpenCode judge call is retried in the run
- **WHEN** an OpenCode judge call ends with an error event `[502] Bad Gateway` and the next call answers
- **THEN** `availability.transient{role: judge, status, attempt: 1, wait_s: 20}` is recorded and the verdict is used
