## Why

Three lessons from a delivery plan on a consumer repository (harness 0.4.11 to 0.4.14).

1. **A hold on the judge's diff came back every round, and a person's answer to it made a fix unit that could not fix
   it.** A unit's verification held with `Hold H-…: the diff is longer than 120000 characters: the judge saw only the
   start` in every round. The raw `git diff <base>...<unit branch>` was 2.2 MB; about 202 kB of it was code and tests,
   the rest the harness's own files (`.l4/ledger/*.jsonl`, the unit folder's `verification.md` and `questions.md`,
   `.l4/review-accepted.json`). The person rejected the hold with a `WHEN … THEN …` reason, as the hold's question asks
   for one ("end the reason with a sentence WHEN ... THEN ... so that a fix unit can be made", `_hold_question` in
   `src/l4/verifier/verdicts.py`; the runbook §7.1 gives this very hold as its example). `_hold_finding` made it a
   deterministic finding and the fix unit got the task "Rejected hold: the diff is longer than 120000 characters…". A
   fix unit cannot shrink a diff, so the hold came back on the next round and needed a person again.

   What the code shows [V]: the judge's diff (`_git_diff` in `src/l4/verifier/ladder.py`) has left out
   `:(glob,exclude)**/.l4/**` and the `verification.md` of every unit of the family since the first public commit, so
   the ledgers, `review-accepted.json` and `verification.md` never reached the judge or the 120000-character check
   (checked with `git diff --name-only` on a scratch repository: the pathspecs drop all three). What did reach it: the
   family's `questions.md` and `feedback.md`, and the code and tests, which are about 202 kB, longer than the cap by
   themselves. Leaving out the bookkeeping alone would not have removed the hold; judging the diff in parts does.

2. **A run limit can be raised only after the plan stops.** `l4 yolo resume PLAN --extend-runs N` on an active plan
   refuses ("only a stopped or waiting plan resumes"). A person who sees the plan run out (82 of 90 runs used, three
   units left) must wait for the stop and then resume. A `plan.resumed` on an active plan would also be ignored by the
   fold (`fold_plan` applies `plan.resumed` only from `stopped` or `waiting`), so the extension needs its own event.

3. **The hint after an answer leads to a refusal.** After `l4 questions answer Q --unit U`, `l4 yolo status` said
   `Next: answer the questions of U (l4 questions --unit U), then l4 yolo resume PLAN --reason TEXT`. `l4 yolo resume`
   then refused with "U is still awaiting_human: answer its questions first" until a CI run had read the answer: its
   check (`resume_blocker` in `src/l4/yolo/commands.py`) reads only the unit's phase, while the plan step wakes the plan
   on the unit's next action (`_cause_gone` and `_live` in `src/l4/yolo/cycle.py`, `next_action` returns `implement`
   or `verify` for an `awaiting_human` unit whose answers are pushed). The plan then continued by itself, as a waiting
   plan does. The hint named a step that was refused, and was not needed.

## What Changes

- **The judge's diff leaves out the harness's bookkeeping, named once** (L4-VER-040): one list
  (`l4.verifier.diffparts.bookkeeping_pathspecs`) for the judge, the S1 step and the length check: `**/.l4/**`,
  `.serena/memories/harness/**`, and `verification.md`, `questions.md` and `feedback.md` in each unit folder of the
  family. The names come from the unit folder's channel list that `l4.state.review` already holds.
- **A diff longer than one prompt is judged in parts** (L4-VER-041, L4-VER-042): whole files, ordered so that a test
  sits next to the code it is named after, packed into parts of at most 120000 characters, at most 8 parts. Each part
  is one judge call with the round's prompt, the part's diff, a `part K of N` heading, the list of every file and the
  rules of a part. The replies are merged into one verdict with fixed rules (a `fail` beats a `pass`, a `pass` beats a
  part that could not see the code). A diff within the cap gets the same prompt as before. Template `judge@10`.
- **Lock files are one line** (L4-VER-045): `uv.lock`, `poetry.lock`, `Pipfile.lock`, `package-lock.json`,
  `pnpm-lock.yaml`, `yarn.lock`, `go.sum`, `Cargo.lock`, `composer.lock` and `Gemfile.lock` are shown to the judge as one
  line each (path, old and new size, lines added and removed), never diffed, and never cause a hold.
- **A hold on the judge's view is a person's decision, never a fix unit** (L4-VER-043, L4-VER-044): only a single
  file longer than one part, or a diff that needs more than 8 parts, still holds, with a `judge view: …` text that
  names the files. Its question says what `accept` and `reject` mean and asks for no scenario. A reject is a human
  finding no fix task is derived from; the unit escalates with `judge_view_rejected`, and `l4 status`, the refusal of
  `l4 run --unit` and the sticky note name the way out (split the change and restart, or replace the answer with
  `accept` and retry). The 0.4.14 hold text is of the same kind.
- **A limit of an active plan is raised without waiting for the stop** (L4-YOLO-050): `l4 yolo resume PLAN --reason
  TEXT --extend-…` on an active plan records `plan.extended{by, actor, reason, extend, limits_before, limits_after}`
  and nothing else: no resume, no run. Without an `--extend-…` the refusal names the four options; an extension that
  changes no limit is refused. `l4 yolo status` lists the extensions.
- **Raising a limit is a person's decision** (L4-YOLO-051): every `--extend-…` of `l4 yolo resume`, on any plan, is
  refused for an agent (`l4.actor.actor`), with the command a person runs. Today this rule is only written in the docs.
- **After an answer, the hints say what happens, and the resume does not refuse it** (L4-YOLO-052, L4-YOLO-053):
  `l4 yolo resume` and `l4 yolo status` decide with the plan step's own predicate (`still_waits`), so a waiting plan
  whose answers are pushed resumes; the refusal for an open question says the plan continues by itself after the
  answer; the `Next:` line says how to answer, or that the next run reads the answer and how to start it.
- **Docs.** `docs/SPEC.md` (the ten requirements, their scenarios, §2.1, §10.2, L4-VER-018, L4-OPS-022,
  L4-YOLO-013/014, the change row), `docs/runbook.md` (§7.1, §7.3, §12.3, §12.4), `docs/yolo-mode.md`, the skill's
  `references/operate.md`, `CHANGELOG.md` under `## 0.4.16 (unreleased)`.

Not in this change:
- a configuration key for the part size or the number of parts (both are constants, as the cap is today);
- special handling of generated files other than the lock files named in D2 (a large one is a `judge_view` hold that a
  person accepts);
- the hold `the judge's reply was discarded (…)`, whose question still asks for a `WHEN … THEN …` (open question);
- the `waiting_capacity` refusal of `l4 yolo resume` (unchanged).

## Capabilities

### New Capabilities

- `judge-diff`: what the judge's diff holds, judging it in parts, merging the parts, and the holds on the judge's
  view (L4-VER-040 to L4-VER-045).
- `plan-limit-extension`: raising a limit of an active plan, audited, by a person (L4-YOLO-050, L4-YOLO-051).
- `plan-answer-hints`: the resume and the hints of a plan that waits for an answer (L4-YOLO-052, L4-YOLO-053).

### Modified Capabilities

None as an OpenSpec delta: `openspec/specs/` holds no baseline. `tasks.md` group 9 holds the `docs/SPEC.md` work,
including the sentences of L4-VER-018, L4-OPS-022, L4-YOLO-013 and L4-YOLO-014 that change.

## Impact

- `src/l4/verifier/diffparts.py` (new: the bookkeeping list, the listing and packing of parts),
  `src/l4/verifier/judge_parts.py` (new: the merge of the part replies), `src/l4/verifier/ladder.py` (`_git_diff`,
  `_judge_step`, `_ask_judges`), `src/l4/verifier/judge.py` (`build_judge_prompt`, `PROMPT_VERSION`),
  `src/l4/verifier/types.py` (`VerifyResult.judge_parts`), `src/l4/verifier/report.py`, `src/l4/verifier/verdicts.py`
  (`hold_kind`, `_hold_question`, `_hold_finding`), `src/l4/verifier/fixunit.py` (`_candidates`),
  `src/l4/verifier/fixloop.py` (`decide_fix`), `src/l4/state/review.py` (a public name for the channel list),
  `src/l4/state/next_step.py`, `src/l4/orchestrator.py`, `src/l4/ci/resume_label.py`.
- `src/l4/yolo/state.py` (`plan.extended` in the fold), `src/l4/yolo/commands.py` (`run_resume`, `resume_blocker`,
  `_read_units`, `_next_line`, `_describe`, `_render`), `src/l4/yolo/cycle.py` (`still_waits`, a refactor with no
  change of behaviour), `src/l4/cli.py` (help text of `yolo resume`).
- Tests under `tests/unit/verifier/`, `tests/unit/state/`, `tests/unit/ci/`, `tests/unit/yolo/`.
- Cost: a unit whose diff is over the cap now costs one judge call per part (at most 8) instead of one call and a
  person's answer.
