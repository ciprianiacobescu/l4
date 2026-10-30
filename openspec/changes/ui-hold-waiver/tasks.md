## 1. A stable hold and the waiver (L4-VER-067)

- [x] 1.1 Write the tests first (tests/unit/verifier/test_ui_step.py `crit`/`event`, test_hold_verdicts.py,
  test_verdicts.py; flows in test_ui_flow.py with `web_repo` and `edit_questions_on_origin`). Then implement design D1
  to D3. Cases: SCN-VER-247 to SCN-VER-252; `unclosed_holds` skips `waived`; amend test_ui_step.py's text test (no
  status) and test_ui_flow.py's `(UNKNOWN, "accepted")` regeneration case, which becomes `waived` when only a
  non-tracing file changed; a flow: round 1 hold accepted, round 2 records `waived`, raises no question and exits 0.

  Result: D1 to D3 built as designed. `ui_step` gets `ui_hold_text` (no status), `ui_hold_binding`, `ui_hold_views` and
  `ui_waivers`; `unclosed_holds` skips `waived`; `_generate_step` takes `events`, records `verify.generated{waived, by,
  attempts: 0}` for each waived gap, keeps the minor gap finding ("waived by Q-…") and calls the writer only for the
  rest (when none is left it records the step `ok` without calling `generate_ui_tests`). `question.raised` of a UI hold
  carries `criterion` and `criterion_sha256`; its accept is bound by the `hold_views` sha, which `judge_body` now merges
  into instead of replacing. `GenStatus` has `waived` and `GeneratedOutcome` has `by`. Closest-correct choices: `by` is the
  answered question (Q-…); a hold accept written before this change has no binding, so it waives until a reject, a void
  or a failing tracing test; an accept of the criterion itself is bound to its text only (as today), so a tracing-file
  change ends the waiver of a hold's accept, not of a criterion verdict's; the binding leaves out the audit and generated
  tests (a round writes them after the accept); `fixunit` treats a waived gap as closed so `fix_minor` spawns no fix unit
  for it. Tests: test_ui_step.py 29, test_hold_verdicts.py 57, test_verdicts.py 30 (unchanged), test_ui_flow.py 9,
  test_fixunit.py 41, all passing.

- [x] 1.2 Review fixes

  Result: (1) `_test_blobs` maps a test id to its file with `file_of_test`, else `test_locate.file_of_id` over
  `worktree_files(wb)` (listed once, only when an id is not a Python module) with the unit's changed files preferred; a
  test against a real temp git repository with a `.ts` tracing test (both id forms) accepts, edits the file and sees the
  waiver end. (2) The hold's question now gives step 5's status and reason (`raise_verdict_questions(generated=…)`, not
  hashed) and says an accept lasts until the criterion's text or its tracing tests change; the delegate's material for a
  UI hold carries the criterion's generated-tests row. (3) Reworded: an accept of the criterion itself is bound to its
  text only, an accept of a UI hold to the text and the tracing files (L4-VER-067, D2). (4) A reject after the accept
  ends the waiver over the raw `human.verdict` events, also one a fix unit consumed. (5) Any hold target that is not the
  stable id is treated as an older hold (compared with the hash of its id). (6) and (7) Wording: a failing test
  suspends, and an accept written before this change survives a text change (proposal, design D2, SCN-VER-250/251).
  (8) A criterion whose own verdict in force is a reject is not waived by a later hold accept. Tests (one run of the five files, 155 passed): test_ui_step.py 34, test_hold_verdicts.py 58, test_prompt.py 24, test_ui_flow.py 9, test_verdicts.py 30; ruff clean. Not done: nothing.

## 2. Checks

- [x] 2.1 Run only the test files you changed or added, once each (the machine is loaded; CI runs the full suite),
  then ruff check and ruff format on the changed files. Report the counts.

  Result: the five files (test_ui_step.py, test_hold_verdicts.py, test_verdicts.py, test_ui_flow.py, test_fixunit.py)
  ran once each in the last run, 166 passed (29, 57, 30, 9, 41); during the test-first work they ran more than once.
  ruff format and ruff check are clean on the changed files. No schema enumerates the `GenStatus` strings, so none
  needed `waived`. Deviations from the design, all in 1.1's Result except these: test_verdicts.py gained no test
  (`effective_verdicts` is unchanged, the waiver logic lives in `ui_step`); test_fixunit.py was added to the list for the
  waived-is-closed rule; the binding resolves a test to its file with the Python-only `file_of_test`, so for a test id
  it cannot map (another language) the binding hashes the id and a tracing-file change does not end the waiver; a failing
  tracing test suspends the waiver for that round (D2's wording) and emits no `human.void` for a hold's accept.
