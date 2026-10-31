## 1. A passing repair is held as a proposal (D2, D3, D5)

- [x] 1.1 Write the tests first (tests/unit/implementer/test_repair_step.py, over the real bench it uses). Then
  implement: `held.Check` gains `"repair"`, `held_patch.CHECKS["single"] = ("tests", "repair")`, `_LABEL["repair"]`;
  `held_question` for check `repair` (title, per-test lines, evidence, the accept and person-only lines of D3; the other
  checks byte-identical); `_raise_held` records `repair_blobs` (from `expected_state` of the saved patch: path ->
  `[blob before, blob after]`); `_run_repair`: an agent step that passes every check is captured and held
  (`GreenOutcome("held")`), a replayed step that passes is committed with `task.repaired{..., question,
  patch_sha256}`, a replayed step never holds again; a patch outside the repaired files, with a link, or whose expected
  state is empty, fails the attempt (D3 last paragraph). Cases: SCN-IMP-453, SCN-IMP-471, SCN-IMP-474, SCN-IMP-475,
  SCN-IMP-476, SCN-IMP-477, and the tests of the first design that asserted a commit after an agent step now assert the
  hold (then a replay for the commit).
  Result: `held.Check` gains `repair` (label `repair proposal`; its subjects are the repaired test ids, so
  `_TEST_SUBJECTS` lists it and `accepted_overrides` finds a repair accept by test id), `held.RepairedTest` and two
  defaulted `HeldCheck` fields (`repaired`, `blobs`) carry what the question shows and the blob pair; `held_question`
  routes `repair` to `_repair_question` (title, a line per repaired test with the kind, gate and first line of its
  failure, the runs, how each was proved, the structural-rules sentence, the diffs and patch path through
  `_source_lines`, options `accept: apply this edit` and `retry: <note>`, the person-only line), the four other checks
  go through the code they had. `held_patch.CHECKS["single"] = ("tests", "repair")`; `held_patch.repair_blobs` gives
  (path, blob before, blob after) from `expected_state` and the base tree. `tdd._run_repair` ends an agent step that
  passed every check with `_repair_proposal` (`capture`, the blobs, `wb.discard_changes()`, `GreenOutcome("held")`); a
  replayed step (`wb.replay_question`) is committed as before and `task.repaired` gains `question` and
  `patch_sha256`; `loop._raise_held` records `repair_blobs` (path -> `[before, after]`) for check `repair`.
  tests/unit/implementer/test_repair_step.py (41 tests, 31 before): the three commit tests now assert the hold and then
  the replay's commit, SCN-IMP-453 (nothing committed, work tree as before, the raise's digests and blobs checked
  against git, the question's text), SCN-IMP-471 (no agent, `held.replayed`, same checks run again, the commit's blobs
  are the recorded pair), SCN-IMP-474 (retry drops the step; the note reaches the next agent), SCN-IMP-475 (a replay
  that fails its gate: nothing committed, accept used up), SCN-IMP-476 (restart, reopened task: parametrized),
  SCN-IMP-477 (five cases of an unoffered proposal), and two loop tests (blocked with no attempt counted; accept then
  done with no agent). Choices the design left open: the digest of the replay travels in a new `Workbench` field
  (`replay_patch_sha256`, set by `replay_step`, cleared by `step_or_replay`); the blobs are computed and checked at
  hold time (so a proposal that cannot be shown fails the attempt before any question) and stored on the `HeldCheck`,
  `_raise_held` only emits them and only when the step was saved; `repair_blobs` also refuses a deleted or added file
  and a changed file mode (stricter than "outside or a link"); `runs` names the gate runs by their run names (`test`,
  `e2e-chore`, `test-extra-zero`, `e2e-repair-base`); a repair hold that cannot be replayed (`Refused`) is shown by the
  same question with the unsaved line and only `retry`.

## 2. Only a person applies it (D4)

- [x] 2.1 Write the tests first (tests/unit/implementer, tests/unit/delegate, tests/unit/specs/test_questions_cli.py).
  Then implement: `accepted_overrides` counts an accept of check `repair` only with `by: human`; `find_replay` records
  `held.accept_ignored{question, task, check, by}` once for an accept that does not count; `DelegatePass._without_a_call`
  escalates a harness question whose raise has `check: repair`; `l4 questions accept|answer` by an agent refuses it
  whatever `clarifier.answer_by_agents` says (the raise read from the unit's ledger at the folder's head). Cases:
  SCN-IMP-472, SCN-IMP-473; the other harness checks keep their rule (a test each).
  Result: `held.accepted_overrides` skips an `accept` of check `repair` unless the ledger records it `by: human` (for
  `repair` the events read are those of the workbench's fix unit, because a fix unit numbers its questions from Q-001 in
  its own file; the other checks read what they read); `held.ignored_accept` names the actor of a recorded `agent` or
  `delegate` accept of a repair question; `held_patch.find_replay` then emits `held.accept_ignored{question, task, check,
  by}` once per question (the `saved: false` branch already did it without `by`), leaves the saved step in place
  (`_queue_removal` is not called) and returns None. `delegate.run._Pass._without_a_call` (the class the task text
  calls `DelegatePass`) returns "a repair of a test is a person's decision" for a harness question whose raise has
  `check: repair`, before any call. `questions_cli.agent_reason` / `check_agent` take a keyword `raise_check`;
  `raised_check` reads the newest `question.raised` of the question from the unit's ledger at the folder's head (the
  fix unit's own raise for a fix unit); `agent_refusal` and `run_show` pass it; for `repair` the refusal precedes the
  `answer_by_agents` shortcut and its Fix line says that no setting helps. tests: tests/unit/implementer/
  test_repair_person_only.py (19: the override by actor, the ignored accept recorded once and nothing replayed or
  removed, a later person's accept replays, the four other checks count an accept whoever gave it),
  tests/unit/implementer/test_held_question_unchanged.py (9: title, options and the digest of the Context of the four
  other checks, with and without a saved step, equal what `held_question` built before this change; the repair
  question has its own head), tests/unit/delegate/test_repair_escalation.py (7), tests/unit/specs/test_questions_cli.py
  (+2: the pure agent rule) and tests/unit/specs/test_questions_agents.py (+7: through the CLI with a ledger raise,
  `answer_by_agents: true` on the base branch changes nothing for a repair, a person answers, a fix unit's raise is not
  the unit's, other checks keep their rule, no readable raise keeps today's rule). Choice the design left open: an
  `accept` by an agent or the delegate (which only a forged or hand-made record can produce, because the CLI refuses an
  agent and the delegate escalates) does not block the task on the same question: as the existing `saved: false` case,
  the run records that the accept was ignored and the step runs again as an agent's, whose proposal is held by a question
  of its own that only a person's accept applies; nothing is committed in between.

## 3. The verifier accepts only the accepted edit (D6)

- [x] 3.1 Write the tests first (tests/unit/verifier/test_repair_integrity.py). Then implement `_repair_acceptance` in
  `l4.verifier.integrity` and call it from `check_test_paths` for every file a `task.repaired` allows in an exempt
  commit: the five conditions of D6, each failing alone in its own test, and the blocker text. The tests of the first
  design gain the question chain (raise, human answer, replay) so they keep testing what they tested. Cases:
  SCN-VER-278, SCN-VER-280, SCN-VER-281, SCN-VER-282.
  Result: `integrity._repair_acceptance` (with `_accepted_why` and `_oid`) returns, for each file a `task.repaired` of the
  commit's task names and the exempt commit changed, `path (task, commit: first failed condition)`; a file passes when
  one `task.repaired` that names it passes all five conditions of D6, judged on the events of the commit's unit
  (`_unit_of`), with the answer after the raise by position in the ledger; `check_test_paths` adds the blocker "a
  repaired test differs from the edit a person accepted" after the existing ones and keeps `_repair_problems`.
  tests/unit/verifier/test_repair_integrity.py (40 tests, 9 before): the helper builds the question chain for the commit
  it makes (raise with the commit's real blob ids, a person's answer, the replay, `task.repaired`), so the tests of the
  first design keep testing what they tested; each condition fails alone in its own test (no question, no digest; eleven
  raise variants; an answer by agent, delegate or clarifier, none, before the raise, of another question or fix unit;
  no replay, a replay of another digest, question or fix unit; a parent blob or a blob that differs; a file edited after
  the replay), and 29 of the 40 fail without the implementation. Choices the design left open: the verifier takes an
  answer as a person's when `question.answered` of the question has `by: human` after the raise, without looking at its
  `answer_sha256` or whether it was `accept` (a `retry` is followed by a new raise and a new question, so no later
  commit can use the old chain); `held.replayed` is not required to follow the answer, only to carry the same digest.

- [x] 3.2 Review fixes. Write the tests first. (a) Before a replayed repair is committed, `_run_repair` compares the
  changed test files with the `repair_blobs` of the replayed question's raise: the same set of paths, and for each the
  blob at the step base (`HEAD`) is the recorded `before` and the blob of the work-tree file the recorded `after`; a
  difference fails the attempt with "a repaired file changed since a person accepted the edit", commits nothing and
  uses the accept up (design D5, SCN-IMP-478: another commit changed the file before the replay and the patch still
  applies). (b) `integrity._accepted_why` requires the `held.replayed` to come after the person's answer (design D6
  condition 4, SCN-VER-281). (c) The tests of SCN-IMP-473 assert what the scenario now says: the recorded accept is
  ignored once, nothing is committed and the next step is an agent's whose proposal is held by a new question.
  Result: (a) `tdd._repair_drift` runs on the replay path of `_run_repair`, after every other check and right before
  `task.repaired` is emitted: `held.recorded_repair_blobs(wb, task, question)` reads the newest `question.raised` of the
  replayed question (kind harness, check `repair`, this task, the events of the workbench's fix unit through
  `_ledger_events`) and returns path -> (before, after); the changed test files (`kept`) must be exactly those paths,
  the blob of each at the step base (`ls-tree` of `base`, the same call `repair_blobs` makes) must be the recorded
  `before` and `git hash-object` of the work-tree file, run with `core.autocrlf=false` and `core.safecrlf=false` as
  `capture` runs `git add`, the recorded `after`. A difference, a raise with no usable blobs, a link or a git error
  returns "a repaired file changed since a person accepted the edit: <path>" (the first differing path); the step
  discards its changes and fails the attempt, commits nothing and emits no `task.repaired`. The accept is used up by the
  `held.replayed` that `replay_step` already wrote (the next `find_replay` sees `_used` and queues the saved step's
  removal), so no second mechanism was added. tests/unit/implementer/test_repair_step.py (49 tests, 41 before): SCN-IMP-478
  over the real bench (hold, a separate commit that changes `test_y` of the repaired file so the saved patch still
  applies, a person's accept: the replay fails with that reason, the head and work tree are as before, no agent ran, one
  `held.replayed`, the next attempt runs an agent), a normal accepted replay still commits with the recorded blobs, five
  cases of the comparison (the after blob, the before blob, another recorded path, the file not recorded, nothing
  recorded) and a CRLF file under `core.autocrlf=true` that is no difference (it fails when `hash-object` runs without
  the two settings). (b) `integrity._accepted_why` takes the position of the first answer by a person after the raise
  and requires the `held.replayed` with the digest in the events after it; the blocker text says that no `held.replayed`
  with this patch_sha256 follows the answer of a person. tests/unit/verifier/test_repair_integrity.py (42 tests, 40
  before): the only replay before the answer is a blocker (fails without the change), an earlier replay beside a later
  one after the answer passes. (c) The tests of SCN-IMP-473 in tests/unit/implementer/test_repair_person_only.py already
  asserted the recorded accept ignored once with `{question, task, check, by}`, nothing replayed or committed and an
  agent run for each next step; one assertion was added to the test whose agent proposal is raised as a new question:
  it is another question than the ignored one, `held.accept_ignored` names only the first, and a person's accept of
  the new one replays. Choices the design left open: the comparison lives in `_repair_drift` with its reader
  `recorded_repair_blobs` in `held.py` beside `_ledger_events`; a raise with no usable blobs fails the replay (the
  comparison cannot be made) with the same reason followed by "the question records no blobs ..."; the verifier takes
  the first answer by a person after the raise and a replay anywhere after it, so a replay between a person's answer and
  a later one counts.

## 4. Checks and documents

- [ ] 4.1 docs/SPEC.md: L4-IMP-091, L4-VER-073, the D11 amendment, SCN-IMP-453..478 and SCN-VER-278..282, the events
  (`question.raised.repair_blobs`, `task.repaired` fields, `held.accept_ignored` for `repair`), change-table row 113;
  CHANGELOG (Unreleased); the runbook and the l4 skill's questions page (a repair question is a person's: read the
  diff, then `accept` or `retry`). Then: the implementer, verifier, delegate and specs suites, ruff, the docs tests,
  `openspec validate own-test-repair --strict`.
