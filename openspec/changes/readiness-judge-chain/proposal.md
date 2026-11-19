## Why

A consumer's delivery plan of ten units lost three readiness reviews in 40 minutes. The first judge of `roles.judges`
failed its hello, so the selection took the next one. That judge stopped at its output limit on the batch subject, a
batch the size of the whole plan. The review raised `JudgeFailed`. The plan step caught it as `RoleUnavailable`, recorded
nothing and threw away the verdicts of the units already answered in that review. The later judges of the chain were
never asked. Nothing marked the judge that failed, so every later run picked the same judge and failed the same way.
With another single judge, the same batch subject stopped at the output limit too.

What the 0.4.58 source does (read for this change):

- `l4.yolo.readiness.review_plan_costed` selects one judge, `factory.for_role("judges", ...)`, the first whose probes
  pass, and asks it every subject.
- `_Calls.ask` raises `JudgeFailed`, a `RoleUnavailable`, on `error` and on `timeout`. An `error` with a length stop is
  included: the opencode adapters set `length_stop`, and readiness never splits.
- `_Calls.ask` raises `RoleLimit` on a usage limit and cools nothing down.
- After two schema breaks a subject is BLOCKED with `schema_invalid`.
- The three callers catch the exception and record nothing: `cycle.py` (the CI step), `commands.py` (`--local`) and
  `review_worktree.py` (`--worktree`). The cost already spent is never charged to the plan.
- `l4 yolo status` shows nothing about a failed review; only the run log has a line.
- The review uses `roles.judges`, the chain of unit verification. To put another judge first for plan reviews, a
  consumer must also reorder the judges of its running units.
- Every call is bounded by `DEFAULT_TIMEOUT_S = 900`. No caller passes `timeout_s`, and no key sets it. A large batch
  subject ran a judge past 900 s and nothing was recorded. No profile has a timeout of its own, and the verifier's judge
  uses a constant too (`JUDGE_TIMEOUT_S = 600`).
- The plan step runs before `l4 run` arms its soft deadline, so nothing stops a long review before the CI job's own
  timeout.

Unit verification already handles these cases:

- L4-VER-071: a length-stopped judge call is split into parts for the same judge.
- L4-VER-075: a schema break moves to the next judge, and a timeout holds the round.

## What Changes

- **`roles.plan_judges`** (optional, default empty). When it is not empty it is the review's chain, in place of
  `roles.judges`. Unit verification never reads it. It is a judge role for the load check (L4-CFG-006), CFG-002,
  CFG-011, ENV-004, `l4 doctor --live`, `l4 probe --role` and the skill's preflight script.
- **The chain is walked per call.** A call is a subject or a part of a batch. It is asked of the first judge, in chain
  order, that is usable and not discarded for it. Rules after a call:
  - an `error` discards the judge for the rest of the review;
  - a length stop or a schema break discards it for that call only;
  - a usage limit cools the profile down and discards it;
  - a judge that is not usable (its probes, or its sandbox here) is skipped and named;
  - with no judge left, a call that a judge answered off the schema is BLOCKED (today's verdict for one judge); a call
    with no reply is unanswered.
- **What was answered stays.** A later judge answers only what is left. A review that finishes is one `plan.reviewed`,
  with `judge` on each entry and `judges` and `failures` on the event.
- **`yolo.review.timeout`** (default `15m`, at least `1m`) bounds each call:
  - a whole batch that times out is split;
  - any other timeout ends the review for this run, without the next judge (as L4-VER-075);
  - in a CI job a call starts only when the job has that much time left before its soft deadline;
  - CFG-012 warns when the timeout does not fit `ci.time_budget`.
- **A batch reviewed in parts.** A batch subject with two or more units is reviewed in parts when:
  - its material is longer than `yolo.review.max_batch_chars` (default 160,000; `0`: no split before a call);
  - an incomplete review kept a part of it since the latest finished review;
  - or its whole call stops at the output limit or times out.

  The parts are one per unit, that unit in full with the others read within 6,000 characters, and one summary part. The
  parts' verdicts are merged into one batch verdict under the batch's own material key, with `parts` rows. An unsplit
  subject keeps its prompt byte for byte, and its key, and the prompt version stays 4.
- **`plan.review_incomplete`.** A review that does not finish (reasons `no_judge`, `timeout`, `job_time`) records this
  event instead of `plan.reviewed`. It holds the entries answered in this run, the calls left, each judge's failure and
  the cost.
  - The fold ignores it, so status, review, acceptances and activation are unchanged.
  - The cost is charged as `plan:review`.
  - A later review reuses its entries by material key, so the next run asks only the rest.
  - A judge that failed a material is asked it after the others in the next run.
  - A repeat of the same failures with nothing new is not written.
  - `l4 yolo status` and the run log show the reason, each judge and its failure, and a fix.
  - `--local` and `--worktree --record` record it. A `--worktree` dry run keeps the answers in its local cache.

Non-goals:

- splitting a unit subject;
- splitting a part again;
- asking the next judge after a timeout in the same run;
- a per-profile timeout;
- changing unit verification;
- `l4 yolo go` ending its wait for CI early on a `plan.review_incomplete` (an open question).

## Capabilities

### New Capabilities

- `readiness-judge-chain`: L4-YOLO-095 (the review's own chain), L4-YOLO-096 (the walk), L4-YOLO-097 (the timeout and
  the job's time), L4-YOLO-098 (a batch in parts), L4-YOLO-099 (an unfinished review is kept and shown), L4-YOLO-100
  (documentation).

### Modified Capabilities

These are amended in `docs/SPEC.md`:

- L4-YOLO-004: no `plan.reviewed` for a judge that fails, but the chain and `plan.review_incomplete`.
- L4-YOLO-022: reuse also from `plan.review_incomplete` and from a batch's parts.
- L4-CFG-006: `roles.plan_judges` is a judge role.
- L4-AVL-010: `plan_judges` is optional.
- SCN-YOLO-220: "no `plan.reviewed` is recorded".

## Impact

- Code:
  - `src/l4/yolo/readiness.py`: the walk, the parts, `ReviewIncomplete`, `timeout_s`, `time_left`, `failed_before`.
  - `src/l4/yolo/model.py`: `Verdict.judge`, `Verdict.parts`, `JudgeFailure`, `ReviewResult.failures`.
  - `src/l4/yolo/cycle.py`: the incomplete record, its dedupe, the charge and the log lines.
  - `src/l4/yolo/commands.py`: `--local` and the status block.
  - `src/l4/yolo/review_worktree.py`: the cache, `--record` and the per-entry judge.
  - `src/l4/yolo/findings.py`: `prior_entries`, `history`, `failed_before`, `latest_incomplete`.
  - `src/l4/agents/factory.py`: `for_profile`.
  - `src/l4/agents/fake.py`: `Step.length_stop`, for tests.
  - `src/l4/config/schema.py` and `src/l4/config/roles.py`.
  - `src/l4/doctor/checks_config.py` (CFG-011, CFG-012) and `src/l4/doctor/checks_agents.py` (LIVE-001).
  - `plugins/l4/skills/l4/scripts/yolo_preflight.py`.
- Docs:
  - `docs/SPEC.md`: L4-YOLO-095..100, the amendments, §3.2, SCN-YOLO-261..282 and change-table row 132.
  - `docs/runbook.md`, `docs/yolo-mode.md`, the skill references and `CHANGELOG.md`.
- Configuration: three new keys (`roles.plan_judges`, `yolo.review.timeout`, `yolo.review.max_batch_chars`). They have
  defaults, so an old configuration loads and reviews as before, except that a batch longer than 160,000 characters is
  now reviewed in parts.
- Ledger: one new plan event (`plan.review_incomplete`) and optional fields on `plan.reviewed`. An older harness ignores
  both.
