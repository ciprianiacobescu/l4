## 1. The signal (D1)

- [ ] 1.1 Write the tests first (tests/unit/agents: grep `without a final stop` and the opencode v1/v2 stream fixtures;
  tests/unit/llm or the agent_judge tests: grep `complete_structured`; tests/unit/verifier: grep `def test_.*run_judge`).
  Then implement design D1: `RunResult.length_stop`, set by `agents/opencode.py` and `agents/opencode_v2.py` when the
  stream's last reason is `length` and the run gave no result; `StructuredResult.length_stop` on the `error` path of
  `complete_structured`; `JudgeRun.length_stop` from the last call in `run_judge`. Status and detail unchanged.
  Cases: SCN-VER-268.

## 2. The split (D2, D3, D4, D5)

- [ ] 2.1 Write the tests first (tests/unit/verifier: grep `_ask_judges`, `judge_parts`, `judge_followups` and the
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

## 3. Checks

- [ ] 3.1 SPEC.md (L4-VER-071, the scenarios, the `judge.length_split` event, `verifier.judge_length_splits` in the
  configuration reference, row 110), CHANGELOG 0.4.48, runbook (waiting for capacity after a length stop); the unit
  suites of agents, llm and verifier, ruff, `openspec validate judge-length-split --strict`.
