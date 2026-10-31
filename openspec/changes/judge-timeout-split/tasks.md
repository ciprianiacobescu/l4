## 1. Timeout split (D1, D2)

- [ ] 1.1 Write the tests first (tests/unit/verifier/test_judge_length_split.py and test_judge_run.py: their stub judge
  backends; add a stub that returns `timeout` for prompts with more than K criteria). Then implement D1 and D2:
  `run_judge(retry_timeout=)`, `_judge_call` passes it, `_ask_judges` and `_ask_batches` split on `timeout` as on a length
  stop while the prompt can be split, `judge.length_split.cause`. Cases: SCN-VER-270, SCN-VER-271, SCN-VER-272; the 0.4.48
  length-stop tests stay green (their events gain `cause: length`).

## 2. Checks

- [ ] 2.1 SPEC.md (L4-VER-071 amended, SCN-VER-270..272, row 111), CHANGELOG 0.4.49; the verifier suite, ruff,
  `openspec validate judge-timeout-split --strict`.
