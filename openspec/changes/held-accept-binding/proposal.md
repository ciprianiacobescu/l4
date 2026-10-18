## Why

On a consumer repository (harness 0.4.16) a task was held with a `harness` question (L4-IMP-063) on one criterion, a
test that pins a dependency's version. A person answered `accept: <why>`. The next run did not take the accept:

1. a hold discards the step's changes (`discard_changes`), so the test the person looked at no longer exists, and
2. an accept covers a criterion only while its candidate tests are among the test ids the question named
   (`Override.covers`).

The next red step's agent wrote the test again from scratch, under another name
(`test_verified_fastmcp_version_is_installed` became `test_fastmcp_version_is_the_verified_one`), the accept did not
cover it, and a new question about the same criterion was raised. Every accept starts the same loop; the person can
never get past the hold.

## What Changes

- **A hold keeps what it held** (L4-IMP-065, D1). When a step is held with a harness question (`pre_satisfied`,
  `vacuity`, `at_red`, `tests`), the step's changes are saved before they are discarded, as a binary-safe patch at
  `<unit folder>/.l4/held/<task>-<check>.patch` (with the agent's result beside it), committed with the questions
  commit. `question.raised` records the patch's `patch_sha256` and the test ids. The question's Context shows the
  source of each named test, redacted before it is cut to 40 lines.
- **An accept replays the held step** (D2). When the next run reaches the step and an accept of that question is
  recorded, no agent runs: the harness verifies the patch's digest, applies it, and runs on it exactly what an agent
  step's changes get (every guard, the gates and the same checks). The override covers the tests of the patch.
  `held.replayed` is recorded. A missing patch, a digest that differs or a patch that does not apply is no override: a
  new harness question says why.
- **Retry, replay and reopening clean up** (D3). `retry` deletes the patch in a commit; a replay deletes it in the
  step's own commit; a restarted unit or a task reopened by a changed criterion drops it.
- **A later agent step is told** (D4). When an agent step runs for a task with an accepted override, its prompt carries
  a data block `accepted tests`: the ids and their source, with the rule to keep them unchanged.
- **The path is the harness's** (D5). An agent's write to `.l4/held/` is refused like any `.l4/` path.
- **Docs** (D6): L4-IMP-065, the text of L4-IMP-063, the runbook and skill lines about answering, and the line that
  `l4 questions answer` starts a run only when the forge token is set.

## Impact

- Capability `held-checks`. Code: `src/l4/implementer/held.py`, `held_patch.py` (new), `tdd.py`, `loop.py`,
  `workbench.py`. No new config key, no new runtime dependency.
- A question raised by 0.4.16 has no `patch_sha256`: its accept behaves as before (the agent step runs).
