One implementer group (1) and one docs group (2), run in order in one worktree. Rules for both:
- Read `proposal.md`, `design.md` and `specs/judge-answers/spec.md` first. The base is the 0.4.27 tree.
- Write the named tests first. Run them and see them fail for the reason the task names. Then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`, then
  `.venv/bin/ruff check <changed files>` and `.venv/bin/ruff format --check <changed files>`.
- Stage explicit paths only (never `git add -A` or a bare directory). Commit messages: `judge-answers <n>: …`, with no
  trailer and no local path.
- Never write a `while pgrep …` loop or any loop that waits on a process name. No test calls a real agent CLI.
- Name no consumer repository.

## 1. The answers block, the rule and the record (L4-VER-065, L4-VER-066)

- [ ] 1.1 Tests first, new `tests/unit/verifier/test_judge_answers.py`:
  - SCN-VER-232: a `questions.md` (write it with the helpers the existing questions tests use) holding Q-001
    `technical` answered by a person. The rendered block is `<l4:data kind="answer" id="Q-001" by="human">` with the
    three lines of design D2. `build_judge_prompt(..., answers=...)` puts it after the gate report and before the
    implementer's hint.
  - SCN-VER-233: `verdict`, `harness`, dismissed and open questions give no block. `accepted` and
    `answered-by-clarifier` give a block with the clarifier suggestion as the answer and `by="clarifier"` for the
    latter.
  - SCN-VER-234: a fix unit's answered Q-001 is `u-fix-1/Q-001`, and its actor is computed with `fix_unit` set.
  - SCN-VER-235: the caps of D2 and D3. The secret case: a redactor token shape across the 4,000th character is
    redacted before the cut (use the project's test redactor). The `(+N answers not shown: …)` line names each
    question left out.
  - An unreadable `questions.md` (a symlink in its place) gives one line naming the unit, and the prompt is still
    built.
  - SCN-VER-236: `prompt_for` (through `_judge_step` with a fake judge that captures prompts, as the existing
    judge-parts tests do) gives the same block to a whole-diff prompt, a part prompt and a follow-up prompt.
  - D3: the block's length is part of `plan_context`'s `fixed_chars`. Assert with a budget that cuts the spec text
    when the block is present and does not cut it when it is absent.
  - SCN-VER-237: `PROMPT_VERSION == 13`, the prompt's version is `judge@13`, `SYSTEM` holds the rule of design D5
    word for word, and `l4.templatelock` yields version 13 and the new hash. Update the committed template lock the
    way its own test says to.
  - SCN-VER-238: the `verify.judge` event holds `answers` as `[[id, sha256], …]`; `[]` without answers.

  Code: `src/l4/verifier/judge.py` (`AnswerRef`, its renderer, `build_judge_prompt(answers=…)`, the rule in `SYSTEM`,
  `PROMPT_VERSION`), `src/l4/verifier/ladder.py` (`_judge_step`: read the family's questions files, the actor, the
  budget, `prompt_for`, the `verify.judge` field), and `src/l4/templates.lock.json`.
- [ ] 1.2 Update the tests that pin version 12: `git grep -n "judge@12\|PROMPT_VERSION == 12"` lists them. A docs test
  that reads a released requirement's text keeps its `judge@12` only if that text stays (it changes in 2.1).
- [ ] 1.3 Run `pytest tests/unit/verifier tests/unit/llm tests/unit/test_template_lock.py tests/unit/eval` (and any file 1.2 touched)
  and the ruff checks. Commit.

## 2. Docs

- [ ] 2.1 `docs/SPEC.md`: add L4-VER-065 and L4-VER-066 (the spec's texts) after L4-VER-064, and SCN-VER-232 to
  SCN-VER-238 in Part II in the `#### SCN-VER-232 (+) <title> · L4-VER-065` form with **Given**, **When**,
  **Then**. In L4-VER-001's paragraph on what the judge's prompt lists, add the answered questions (L4-VER-065). Where
  the SPEC names the judge prompt version `judge@12`, say `judge@13`. Change table: a new row 69 after row 68 (or after
  the last row if 68 is not there yet): `| 69 | \`judge-answers\` | every judge prompt carries the family's answered
  technical, product and ambiguous questions (the implementer's question text marked unverified, the answer redacted
  and bounded, 24,000 characters at most, charged before the spec text), and the judge judges a criterion as an answer
  narrowed it, names the answer's id, never passes without evidence or over a failing gate, and raises no spec_gap for
  an input an answer settles; judge@13; \`verify.judge\` lists the answers shown (L4-VER-065, L4-VER-066;
  \`openspec/changes/judge-answers/\`) | a unit whose technical answer narrows a criterion passes the judge without a
  verdict question |`. Run `.venv/bin/python scripts/check_spec.py docs/SPEC.md`, which must exit 0.
- [ ] 2.2 `CHANGELOG.md` `## 0.4.28 (unreleased)` (create it above `## 0.4.27` if missing): under `### Changed`, one
  line: the judge sees the unit's answered questions (L4-VER-065, L4-VER-066, judge@13).
- [ ] 2.3 Run `.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit/docs`, `scripts/check_spec.py
  docs/SPEC.md` and `npx --yes @fission-ai/openspec@1.14.1 validate judge-answers --strict` (only warnings allowed).
  Commit.
