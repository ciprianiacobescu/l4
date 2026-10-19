## Why

Three reports of the maintainer about accepting a delivery plan (harness 0.4.17):

1. "In the next release of the L4 allow a path to force accept everything in a plan without needing a new llm review -
   I got blocked trying to accept a plan and opencode is not working there." Today every way to activation goes through
   a readiness review made by a model: `l4 yolo activate` refuses a plan with no review, a review for other inputs, or
   an item that is not READY and has no acceptance that holds (L4-YOLO-005), and `l4 yolo accept` refuses BLOCKED, a
   blocking finding, a material finding, fewer than `yolo.review.accept_after_rounds` judged versions, and a plan with
   no review at all (L4-YOLO-027, `src/l4/yolo/accept.py` `check`, `src/l4/yolo/commands.py` `run_accept`). When the
   judge cannot run on the machine (the review is BLOCKED, or there is none), a person has no way on.
2. "Hanging at interactive prompt even if --yes was provided for accept." `run_accept` asks a person for the plan id
   whenever stdin is a terminal and ignores `--yes` (`--yes` counts only for an agent that
   `yolo.review.accept_by_agents` lets accept); `run_waive` does the same. The prompt is written to stdout, so behind a
   pipe or a wrapper that holds stdout it is not seen, and the command waits on stdin.
3. "Seems the review cache used a stale judgement. Something accepted still appears as NEEDS_REVISION." An acceptance
   holds only while the latest review's entry of its subject has the same `material` and `findings_sha`
   (`accept.holds`). A reuse picks the newest recorded entry of a material (`findings.prior_entries`), not the one an
   acceptance is bound to; `l4 yolo findings`, `l4 yolo review --worktree`, `--local` and the CI log print an accepted
   subject as `NEEDS_REVISION` (and `(reused)`) with nothing on that line about the acceptance; and when an acceptance
   stops holding the text says `the material changed` even when only the findings changed. Design D9 says what the
   code shows about each hypothesis.

## What Changes

- **`l4 yolo accept PLAN --all --force --reason TEXT`** (L4-YOLO-057): a person accepts every unit and batch of the
  plan as it stands, without a readiness review: no review, a stale one, BLOCKED, blocking, material and too few rounds
  are all overridden. It calls no model. One event `plan.force_accepted` records the person, the reason, the plan
  digest and per subject its digest(s), what it skipped and the latest review's time.
- **A person only, in a terminal** (L4-YOLO-058): refused for an agent always (`accept_by_agents` does not apply),
  for an MCP caller, and without a terminal.
- **Not overridden** (L4-YOLO-059): a plan file that is not a plan, the admission of `l4 yolo activate` (a cycle, an
  unknown unit, intake, open questions …), a unit with no folder (`unit_missing`) and the plan status rule.
- **Bound to the digests** (L4-YOLO-060): a change of the plan file voids it; a change of a unit's spec voids it for
  that unit and its batch. `--withdraw` removes it.
- **Activation** (L4-YOLO-061): when a holding force acceptance covers every subject, no review is needed;
  `plan.activated` records `review: force_accepted` and each force-accepted subject with `force: true` and no findings.
- **Visible** (L4-YOLO-062): `l4 yolo status`, `l4 yolo findings`, the activation output, the plan report, each unit's
  PR body and the implementer's prompt say `force-accepted without review by <person> (<reason>)`.
- **`--yes` is a person's confirmation too** (L4-YOLO-063): a person's `--yes` replaces the typed plan id in
  `l4 yolo accept` (also with `--force`) and `l4 yolo waive`; every acceptance and waiver records `confirmed`.
- **No prompt waits unseen** (L4-YOLO-064): without a terminal nothing prompts (exit 2 naming `--yes`); the prompt is
  written to stderr, flushed.
- **A reuse keeps the judgement an acceptance is bound to** (L4-YOLO-065), and **an acceptance that does not hold says
  why in one line** (both sides' material, findings and time, reused or new) while an accepted subject is shown as
  accepted where its verdict is printed (L4-YOLO-066).
- **Docs** (L4-YOLO-067): `docs/yolo-mode.md` "When the reviewer is unavailable", the runbook, the skill (agents never
  run `--force`; they print the command for the person), CHANGELOG 0.4.18, SPEC.

## Impact

- Code: `src/l4/yolo/accept.py`, `src/l4/yolo/commands.py` (`run_accept`, `run_activate`, `_review_view`,
  `run_status`, `run_findings`, `run_review --local`, `run_waive`, `_show_and_confirm`), `src/l4/yolo/state.py`,
  `src/l4/yolo/model.py`, `src/l4/yolo/findings.py`, `src/l4/yolo/review_worktree.py`, `src/l4/yolo/cycle.py`
  (`_accepted`, the review step's `prior` and log line), `src/l4/yolo/report.py`, `src/l4/accepted.py`,
  `src/l4/implementer/tdd.py` (`accepted_block`), `src/l4/archive.py` (`render_pr_body`, `_pr_body`), `src/l4/cli.py`.
- Ledger: new events `plan.force_accepted`, `plan.force_acceptance_withdrawn`; new optional keys
  `plan.activated{review}`, `plan.activated{accepted.<subject>.force}`, `plan.accepted{confirmed, judged_at}`,
  `plan.finding_waived{confirmed}`. Older ledgers fold unchanged; older readers ignore the new keys.
- Carrier `.l4/review-accepted.json`: an item may carry `force: true` (only when true, so the bytes of an existing
  carrier do not change).
- Behaviour change: a person's `--yes` no longer prompts (it did); `l4 yolo accept` takes an optional SUBJECT.
- Spec: L4-YOLO-057 to L4-YOLO-067, SCN-YOLO-150 to SCN-YOLO-176, change-table row 53; the text of L4-YOLO-005,
  L4-YOLO-027 and L4-YOLO-031 and the CLI rows of `yolo accept`, `yolo waive` and `yolo activate` name the new rules.
- No configuration key, no runtime dependency, no prompt version change.
