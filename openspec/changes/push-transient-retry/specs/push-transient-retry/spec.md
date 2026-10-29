## Purpose

A push that fails on the forge's side is tried again before the run gives up, and a failure that remains is reported as
the forge's error, not as a refusal.

## ADDED Requirements

### Requirement: L4-LCK-001 A transient push failure is retried
Every harness push SHALL be tried up to 3 times when git's message is a server or network error (a transient failure),
waiting 5 s and then 15 s, and no try SHALL start more than 60 s after the first. A failure that holds a credential or
permission marker, a hook's or a rule's refusal, and a ref that moved on MUST NOT be retried. Before each new try the
harness SHALL ask the remote whether every ref of the push already holds the value pushed, and SHALL treat the push as
done when it does. A transient failure that remains SHALL exit 1 with the server's message and a hint that the forge
failed on its side; it MUST NOT be reported as a refusal by the forge.

#### Scenario: SCN-LCK-10 (−) a push refused by the forge itself is not retried
- **WHEN** the server's hook refuses a push of the unit branch with a push rule's message
- **THEN** git runs once, and the run exits 1 with the server's message as a refusal by the forge

#### Scenario: SCN-LCK-11 (+) a server error is tried again
- **WHEN** the first push of the unit branch fails with `remote: fatal error in commit_refs_rules` and
  `! [remote rejected]`, and the second succeeds
- **THEN** the branch holds the pushed commit, one warning names the retry, and the step is not lost

#### Scenario: SCN-LCK-12 (+) a push that landed is not pushed twice
- **WHEN** git reports a server error but the remote ref already holds the pushed commit
- **THEN** the push returns as done after one `ls-remote`, with no second push and no lease refusal

#### Scenario: SCN-LCK-13 (−) a server error that remains is the forge's, not a refusal
- **WHEN** every try fails with `remote: Internal Server Error`
- **THEN** the run exits 1 with `push failed on the forge's side`, the error is not `refused`, and no try started more
  than 60 s after the first
