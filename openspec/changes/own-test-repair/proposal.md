# A unit's own new test that fails before it checks anything gets a repair a person accepts

## Why

On a consumer (2026-10-30, harness 0.4.43) a unit's red step wrote an end-to-end test that raised an error from its
test library before any check (an argument type that the library version does not accept). Red and green run only
`gates.test`, so no phase that may write tests ever ran it [V]. Verification failed it; every fix chore may not change
test files (ci-evidence D11), so the guard put back the agent's correct one-line edit of the test, and an unattended
plan waited on the owner's commit. Worse, another fix chore bent correct product code to suit a second broken test of
the same unit [V]. fix-chore-e2e (0.4.45) makes such a chore fail honestly; it still cannot repair the test.

A first design (branch f445-repair) let a narrow step commit the repair under a structural check of the test's syntax
tree and two proofs (the repaired test fails when the product answers its zero values, or against the unit's base
code). Three adversarial reviews each found a full bypass chain (an encoding cookie, vacuous checks, builtins shadowed
through an import, module attributes patched, a forged location of the failure). The lesson: static rules and proofs
show that a test depends on the product, not that it checks the criterion. A check of that kind can keep obviously bad
edits away from a person; it cannot stand in for one.

## What changes

- The repair step of the first design stays (candidates, scope, structural check, gate, proofs), and its result is a
  proposal, not a commit: the edit is saved with the held-step machinery (L4-IMP-065), the work tree is put back, and
  one `harness` question of check `repair` blocks the task. It shows each failing test, the edit of each file, the gate
  run that passed the repaired tests and how each was proved. Options: `accept` (apply this edit) and `retry`.
- Only a person's `accept` applies it: an agent's or the delegate's answer never does, whatever
  `clarifier.answer_by_agents` says; the delegate escalates such a question without a call, and `l4 questions` refuses
  it to an agent.
- The next run replays the saved edit (no agent, the digest the question recorded), runs the same checks again and
  commits it with `L4-TDD: exempt` and `task.repaired`, which names the question and the patch digest.
- The verifier accepts the change of a test file in such a commit only when it is exactly the edit a person accepted:
  the question's raise recorded the blob of each file before and after, a person's answer is on record, and the
  replay used the same patch. The structural rules run again as before. The judge sees each repaired test's lines
  before and after.

## Impact

- Code: `l4.implementer.held` (`Check` `repair`, its question), `l4.implementer.held_patch` (`CHECKS["single"]`, the
  person-only accept, the blobs of the proposal), `l4.implementer.tdd._run_repair` (hold, then commit on replay),
  `l4.implementer.loop` (the raise records the blobs), `l4.delegate.run` (escalates without a call),
  `l4.specs.questions_cli` (refuses an agent), `l4.verifier.integrity` (the accepted edit), and what f445-repair added.
- Spec: L4-IMP-091 and L4-VER-073 added; ci-evidence D11 amended (one exception: a repair a person accepted);
  SCN-IMP-453 to SCN-IMP-484 and SCN-VER-278 to SCN-VER-282 added; change-table row 113.
- Not in this change: non-Python tests (no structural check; they go to a person as today); tests that existed at the
  unit's base; a failure by assertion (a finding about the code).
- Cost: an unattended plan still waits for a person on such a test, now with the edit and its evidence ready, and one
  answer applies it. Residual: a person who accepts without reading; an agent that hides from the CLI's agent detection
  answers as a person, as for every person-only answer.
