## Why

On 2026-10-20 a consumer unit's diff was about 141000 characters, so the LLM judge saw it in two parts (the cap is
120000 characters a part, L4-VER-041). The code that implements one criterion lay in both parts. Each part saw half of
it and answered `insufficient_evidence`. The merged verdict was `insufficient_evidence`, the criterion was
`needs_human`, and a person was asked a verdict question, although the whole diff satisfied the criterion.

How the code does it (release 0.4.20, da3e7c28):
- Each part prompt says: "A criterion whose code is not in this part: answer insufficient_evidence with the reasoning
  `not in this part`" (`_part_rules`, `src/l4/verifier/judge.py:381-395`). Nothing tells a part what to do with a
  criterion whose code it shows only in part, and nothing judges such a criterion on all of its code.
- The merge takes, per criterion, a `fail` of any part, else a `pass`, else a `not_verifiable`, else
  `insufficient_evidence` (`_ORDER` and `_criteria`, `src/l4/verifier/judge_parts.py:16,25-32`). It never reads the
  reasoning, so it cannot tell "not in this part" from "I saw half and cannot confirm". Two half views give
  `insufficient_evidence`.
- Aggregation makes a covered criterion with a judge `insufficient_evidence` `needs_human` with the reason `the judge
  answered insufficient_evidence` (`src/l4/verifier/aggregate.py:86`). The question's `Why:` line is that reason
  (`src/l4/verifier/verdicts.py:527`). It does not say that the evidence was split, so the person cannot tell this case
  from a criterion that really lacks evidence.

## What Changes

- **A criterion whose evidence is split over parts gets one follow-up judgment of all of it** (L4-VER-056, L4-VER-057).
  After the parts are merged, a criterion is *split* when its merged verdict is `insufficient_evidence`, its tracing
  tests make it `covered` and not held, and its files lie in two or more judged parts. Its files come from the
  harness, not from the judge's words: its tracing tests, the code those tests import, the files of the commits of
  the tasks whose red step added those tests, and the files the parts cited for it. The judge step then makes one
  follow-up call with only those criteria and only those files, whole, from all parts, within one part's characters.
  Its verdict for a criterion replaces the merged `insufficient_evidence`. Several split criteria share a call when
  their files fit together; a round makes at most as many follow-up calls as it judged parts.
- **A follow-up never makes a round worse** (L4-VER-057). A criterion that any part failed, passed or called
  `not_verifiable` is never re-judged. A follow-up whose reply is discarded, or that hits a usage limit or an error,
  keeps the merged verdict and does not discard the round's judge verdict (unlike a part, SCN-VER-166). A criterion
  whose files are all in one part, or whose files are all in a part cut to the cap or in no judged part, gets no
  follow-up: the first is a real `insufficient_evidence`, the second is the `judge_view` hold of L4-VER-043.
- **The part prompt asks a part to name what it saw** (L4-VER-056). A part that shows only some of a criterion's code
  judges it when that is enough, else answers `insufficient_evidence` and cites each file of the part that holds some
  of its code. The template becomes `judge@12`; a diff within one part keeps its prompt text and hash.
- **The verdict and the question say that the evidence was split and what was done** (L4-VER-058). The reason of such
  a criterion ends, for example, `its evidence was split over parts 1 and 2 of the diff: follow-up call 1 judged its 4
  files of those parts together and answered pass`, or says why no follow-up was made. The reason is the question's
  `Why:` line and the criteria table of `verification.md`. `verification.md` lists each follow-up call under the
  judge line; `verdict.json` records `judge_followups` and `judge_split`; `verify.judge` records `followup`,
  `followups` and `criteria`.
- **Docs**: SPEC (L4-VER-056 to L4-VER-058, SCN-VER-190 to SCN-VER-203, the step 9 row of §10.2, L4-VER-018's
  template sentence, L4-VER-041 and L4-VER-042, SCN-VER-161's template, change-table row 59), the runbook's
  verification section, and CHANGELOG `## 0.4.21 (unreleased)`.

## Impact

- Code: `src/l4/verifier/judge_followup.py` (new: the files of a criterion, the split test, the groups, the merge of
  the follow-up replies, the note), `src/l4/verifier/judge.py` (`FollowUpView`, the follow-up diff section and its
  rules, the new part rule, `PROMPT_VERSION = 12`), `src/l4/verifier/ladder.py` (`_judge_step` makes the follow-up
  calls; `_finalize` passes the note to aggregation), `src/l4/verifier/aggregate.py` (`aggregate_criterion(...,
  split="")`), `src/l4/verifier/types.py` (`judge_followups`, `judge_split`), `src/l4/verifier/report.py` (the rows
  and the two keys), `src/l4/verifier/evidence.py` (a resumed round keeps them), `src/l4/templates.lock.json` (the
  judge's version becomes 12; its system text and hash are unchanged, design D6).
- Cost: one more judge call per follow-up group, only in a round that would otherwise ask a person about a split
  criterion; at most as many as the round's parts, each prompt no longer than a part's.
- Ledger and evidence: new optional keys `verify.judge{followup, followups, criteria}` and `verdict.json`
  `judge_followups`, `judge_split`. Older readers ignore them; `l4/verdict@1` stays (keys were added the same way for
  `judge_parts`).
- Behaviour change: a split criterion that the follow-up passes is no longer a person's question. Every other verdict
  path, the part layout, the holds and the merge of L4-VER-042 are unchanged.
- Tests that change: the literal `judge@11` asserts (`tests/unit/verifier/test_prompt.py`, `test_judge_satisfied.py`,
  `test_judge_feedback.py`, `test_judge_step.py`, `test_judge_accepted.py`, `test_judge_sources.py`).
- No configuration key, no new dependency, no template file change, no change of the part cap or the part count.
