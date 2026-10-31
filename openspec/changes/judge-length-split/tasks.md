## 1. The signal (D1)

- [x] 1.1 Write the tests first (tests/unit/agents: grep `without a final stop` and the opencode v1/v2 stream fixtures;
  tests/unit/llm or the agent_judge tests: grep `complete_structured`; tests/unit/verifier: grep `def test_.*run_judge`).
  Then implement design D1: `RunResult.length_stop`, set by `agents/opencode.py` and `agents/opencode_v2.py` when the
  stream's last reason is `length` and the run gave no result; `StructuredResult.length_stop` on the `error` path of
  `complete_structured`; `JudgeRun.length_stop` from the last call in `run_judge`. Status and detail unchanged.
  Cases: SCN-VER-268.
  Result: `RunResult.length_stop` (default False). `OpenCodeAdapter.parse` sets it in the branch that writes `the stream
  ended without a final stop` when the stream's last reason is `length`; `OpenCodeV2Adapter.parse` sets it in the two
  branches that give no result without a named cause (an export whose outcome is not `succeeded`, and no export with no
  final stop), not in the step-bound, denial, error, exit-code, timeout or cancel branches. `StructuredResult.length_stop`
  is copied from the run on the `error` return of `complete_structured` only; `run_judge` sets `JudgeRun.length_stop`
  from the last call. Status and detail are unchanged. Tests: tests/unit/agents/test_opencode_length_stop.py (v1 and v2:
  marked on `length`, unmarked on `tool-calls`, `other`, no `step_finish`, `stop`, a timeout and a succeeded export),
  tests/unit/llm/test_agent_judge_length_stop.py, two tests in tests/unit/verifier/test_judge_run.py.

## 2. The split (D2, D3, D4, D5)

- [x] 2.1 Write the tests first (tests/unit/verifier: grep `_ask_judges`, `judge_parts`, `judge_followups` and the
  stub judge backends of test_ladder*.py / test_judge*.py). Use a stub backend that returns a length stop for any prompt
  with more than K criteria and a valid reply otherwise. Then implement D2 to D5: `VerifierCfg.judge_length_splits`
  (default 2, 0..4); `BatchView` and the batch section in `build_judge_prompt` (exclusive with `followup`, composes with
  `part`; a prompt without it is byte-identical); `_ask_judges(criteria=, rebuild=)` with the per-call bookkeeping in one
  helper used by whole and batch calls; the merge into one `JudgeRun` per prompt; `judge_body` passes `criteria` and
  `rebuild` (and appends batch prompt hashes); `_follow_ups` passes neither; the records (`judge.length_split`,
  `verify.judge.batch_criteria`/`batch_depth`, `VerifyResult.judge_batches` in `verdict_json` and
  `evidence.restore_round`, `judge_parts[].batches`, `prompt_sha256`). Run `tests/unit/test_template_lock.py` after the
  prompt change and say in the result whether the judge prompt version had to change.
  Cases: SCN-VER-265, SCN-VER-266, SCN-VER-267, SCN-VER-269; a usage limit in a batch moves to the next judge with the
  whole prompt; a `schema_invalid` batch holds the round; the served-model independence check runs for a batch call.
  Result: `VerifierCfg.judge_length_splits` (0..4, default 2). `judge.BatchView(shown, total)` and `build_judge_prompt(
  batch=)`: the criteria section begins with the D3 sentence, `batch` composes with `part` and raises `ValueError` with
  `followup`; a prompt without it is byte-identical (the judge system text is unchanged, so the template lock needed no
  version bump: `judge@13` stays). `ladder._judge_call` is the one place a judge call is made and booked (independence
  check, calls, cost, `verify.judge` with `batch_criteria` and `batch_depth`, `judge.reply_repaired`, `budget.cost`);
  `_ask_batches` cuts the criteria in halves (the first has `ceil(n/2)`), records `judge.length_split`, asks the same
  judge for each half, cuts a half that stops again while its depth is below the setting, and merges the batches with
  `merge_part_verdicts` into one `JudgeRun` (calls and cost include the calls that stopped at the limit); a batch that
  ends `error` (named `batch of K criteria at depth D: ...`) or `model_mismatch` discards the judge and the next judge
  gets the whole prompt, a `schema_invalid` or `timeout` batch is returned as it ended, a `RoleLimit` moves to the next
  judge. `_ask_judges(criteria=, rebuild=)` starts it; `_follow_ups` passes neither. `judge_body` passes `rebuild`
  (non-first batches drop the feedback, accepted, satisfied and done-task blocks), appends every batch prompt's hash to
  the round's, and writes `judge_parts[].batches`, `VerifyResult.judge_batches` (one row per batch call, a batch that
  stopped again included), `verdict_json` and `evidence.restore_round` keep it. Tests: tests/unit/verifier/
  test_judge_length_split.py (20: SCN-VER-265..267 and -269, the limit, schema and served-model cases in a batch, the
  prompt and the configuration); with the split switched off 12 of them fail, and a part that contributes its batches
  to the parts' merge one by one fails the assumptions test.

## 3. Checks

- [ ] 3.1 SPEC.md (L4-VER-071, the scenarios, the `judge.length_split` event, `verifier.judge_length_splits` in the
  configuration reference, row 110), CHANGELOG 0.4.48, runbook (waiting for capacity after a length stop); the unit
  suites of agents, llm and verifier, ruff, `openspec validate judge-length-split --strict`.
