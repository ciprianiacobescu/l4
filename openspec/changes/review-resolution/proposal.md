## Why

A delivery plan can be activated only when every unit and batch of its readiness review is READY, and there is no
override (`src/l4/yolo/commands.py:799-808`). On 2026-10-15 the ten-unit plan `telemetry-and-fixes` on a real consumer
repository (`merge: auto`) was reviewed seven times in 45 minutes and nine times by the evening, never READY. The
ledger shows why (design section 2):

- every round re-judged every unit and batch: 46% of the unit reviews were of material that had not changed, and
  $7.36 of the plan's $30 limit was spent before activation;
- a person saw one finding per item (possibly a minor one), no "how to resolve", and no comparison with the last
  round, so the same four concerns of one unit came back reworded seven times and were half-fixed each time;
- a prerequisite folder over 20,000 characters blocked its dependents, and the author cut spec text to fit;
- the judge saw every task unticked although the implementer skips ticked tasks;
- the only local review (`--local`) reads `origin`, records like CI, and stops with exit 3 on macOS (no bwrap).

The maintainer's words: "I really want it to be robust and generally working. User (or agent) should have clear path
to resolution or manual mechanism to trigger it anyways under certain conditions."

## What Changes

- **`l4 yolo findings PLAN`**: every blocking and major finding in full, with an id, a `Resolve:` line, the change since
  the previous judgement and the criteria that persist. The one-line views show the most severe finding.
- **Incremental review**: a subject whose material (its folder, its prerequisites as shown, its plan entry, the prompt
  version) was already judged keeps that verdict at no cost.
- **Verdict rules**: minor-only NEEDS_REVISION is READY; a NEEDS_REVISION without a finding gets one; `batch_acceptance`
  on a unit is an assumption.
- **Budgets**: a prerequisite's cut no longer blocks (it is listed in `missing`); prerequisites are shown spec first
  and `tasks.md` last; the budgets are configuration; a cut of the subject says the size, the budget and the fix.
- **Check marks** reach the judge as they are; the digest still ignores them (prompt version 4).
- **`l4 yolo review PLAN --worktree`**: the same review on the working tree before the push, dry by default with a local
  cache, `--record` for a committed tree so CI does not review again; on macOS a tool-less judge runs unsandboxed
  outside CI and says so.
- **`l4 yolo accept PLAN SUBJECT --reason TEXT`**: a person accepts a subject's remaining major findings after two
  judged versions, bound to the material; never BLOCKED, blocking or a cut of the subject; agents only when the
  target's committed configuration allows it. Activation lists every acceptance.
- **Accepted findings travel**: `.l4/review-accepted.json` in the unit folder, a block in the implementer's prompt, a
  structured answer from the verifier's judge, and with `merge: auto` a wait `accepted_finding_open` instead of a merge
  when one is not addressed.
- Not added: an automatic "after N rounds" filter, and a System One pre-screen (measured: it does not discriminate
  uncalibrated). Design D10 and D11 say why.

## Impact

- Code: `yolo/readiness.py`, `yolo/commands.py`, `yolo/cycle.py`, `yolo/state.py`, `yolo/model.py`, new
  `yolo/findings.py`, `yolo/accept.py`, `yolo/worktree.py`, `yolo/judge_sandbox.py`, `yolo/review_worktree.py`,
  `config/schema.py`, `cli.py`, `orchestrator.py`, `implementer/tdd.py`, `verifier/judge.py` and its schema,
  `state/fold.py`, `yolo/report.py`.
- Spec: L4-YOLO-021..029 added, L4-YOLO-004 and -005 modified, SCN-YOLO-43..70.
- Migration: prompt version 3 → 4 makes CI review once more every plan not yet activated or stopped with
  `inputs_changed` (charged). The rounds condition of `l4 yolo accept` counts versions of a subject's text over every
  prompt version, so the live plan's nine earlier rounds still count: one version-4 review, then a person can accept. Old
  ledgers fold unchanged; entries without `material` are never reused. The verifier's judge prompt version 7 → 8.
- Docs: runbook 12.2a and 12.4, `docs/yolo-mode.md`, `docs/SPEC.md` §12.5, the skill's `plan.md` and `operate.md`.
