## 1. State core (wave 1, agent A: `state/lifecycle.py`, `state/fold.py`, `orchestrator.py`, the capacity row of `planner.py`)

- [ ] 1.1 Lifecycle edges (D2, D9): `halted`/`escalated → implementing` on `spec_edit_since_stop`; `in_review → verifying` on `retry_requested`; `verifying`/`verified → halted` on `breaker_or_budget`; every non-terminal phase `→ abandoned` on `pr_closed`; `abandoned → previous_phase` on `pr_reopened`. The table tests cover each new row. (L4-OPS-001, L4-OPS-003, L4-OPS-009)
- [ ] 1.2 `phase.changed` into `halted` or `escalated` carries `reason` (a code of D5) and `detail`. The fold keeps `halt_reason` (the code) and a new `halt_detail`. Old ledgers without `detail` fold as before. (L4-OPS-005)
- [ ] 1.3 The fold reads `unit.restarted` as a new start (no phase, counters at zero, `restarts` counted) and `unit.retried` like `unit.resumed`. (L4-OPS-001, L4-OPS-004)
- [ ] 1.4 Every halt in `orchestrator.py` records its code and detail: `max_task_attempts`, `unselectable_task`, `baseline_failed`, `secret_in_push`, `fix_records`. The log line is `[l4] run: <unit> halted: <detail>`. (L4-OPS-005)
- [ ] 1.5 The secret halt (D9): discard the unpushed commits with a hard reset of the worktree to `origin/<branch>`, record `breaker.tripped` and the halted edge in any phase, and push the ledger alone. A test shows that the remote branch gets no code commit and the ledger says `halted`. (L4-OPS-009, SCN-OPS-15)
- [ ] 1.6 `waiting_capacity` always records `retry_after`, using `availability.default_cooldown` when the cause gives none. `planner._after_capacity` maps `previous_phase = fixing` to `implement`. (L4-OPS-009, SCN-OPS-02)
- [ ] 1.7 `l4 run --unit` on `halted` or `escalated` exits 13 before the lease, with the detail and `Next: l4 retry --unit U --reason TEXT`. It writes no ledger, pushes nothing and syncs no label. A test checks the head and the labels. (L4-OPS-010, SCN-OPS-17)

## 2. Verifier (wave 1, agent B: `verifier/fixloop.py`, `verifier/verdicts.py`, `verifier/notes.py`, the fix-unit green gate)

- [ ] 2.1 The fix loop puts `(code, detail)` in `ctx.shared["escalation"]` for every escalation cause: `fix_rounds_exhausted` (`fix rounds used n/m`), `no_convertible_finding`, `no_fix_units`, `fix_unit_not_created`, `feedback_rounds_exhausted`. `orchestrator._verify` (shared with agent A: coordinate through this key only) uses it for the edge, the note headline and `exit_reason`. Three verifier errors use `verifier_errors`. No text says "no fix round is left" unless the rounds are used up. (L4-OPS-005, SCN-OPS-10)
- [ ] 2.2 `same_failure` (D7): the failure set of a round comes from the round's gate results and JUnit reports (`.l4/evidence/round-<n>/`). It is compared with the previous round's, and person commits between the rounds are checked with `foreign_tail`. Equal and not empty → escalate with `same_failure` and `round <n> failed the same way as round <n-1>: …`. Tests: SCN-OPS-12 and SCN-OPS-13. (L4-OPS-007)
- [ ] 2.3 A verdict question with Status `dismissed` reads as `open`. The note line and the plan reason say `Q-NNN: a verdict question cannot be dismissed: start the answer with accept or reject`. (L4-OPS-009)
- [ ] 2.4 The green step of a fix-unit task runs its test gate with `gates.coverage.cov_env`, with the output in the step's private folder. Only pass or fail is used. A test shows a coverage-only failure reaching the fixer's retry prompt. (L4-OPS-012, SCN-OPS-19)

## 3. Forge (wave 1, agent C: `forge/base.py`, `forge/github.py`, `forge/gitlab.py`, the label sync in `archive.py`)

- [ ] 3.1 The target from `origin` (D11): GitHub `owner/name` from a github.com `origin`, and GitLab `https://<host>/api/v4` plus the path without `.git`. Configured values win. `forge.type: auto` with a github.com `origin` is GitHub. (L4-OPS-011, SCN-OPS-18)
- [ ] 3.2 `Forge.start_run(ref) -> Literal["started", "already_queued", "refused", "unsupported"]`. GitHub reuses the dispatch of `l4.yml`. GitLab uses `POST /projects/:id/pipeline {ref}`. A 401 or 403 is `refused`, never an exception. The recorded GitLab API exchange goes into a test. (L4-OPS-002)
- [ ] 3.3 `Forge.close_pr(number, comment)`: comment, then close. Also `Forge.pr_state(number) -> open|closed|merged`, if the existing `get_pr` does not already say so. (L4-OPS-004, L4-OPS-009)
- [ ] 3.4 The label sync also ensures `<prefix>retry`, `<prefix>restart` and `<prefix>resume`, once per run. (L4-OPS-008)

## 4. Commands (wave 2, agent D: `state/retry.py`, `state/restart.py`, `state/resume.py`, `cli.py`, and the resume path of `orchestrator.py`)

- [ ] 4.1 `l4 retry` with D2's table: the refusals with their exact messages, `--rounds N`, `unit.retried{reason, by, signal}`, and the commit `chore(<name>): retry [skip ci]`. `in_review` takes `retry_requested`. A merged unit clears `archive.failed` with `archive.retried`. Tests for each row. (L4-OPS-001, SCN-OPS-01..03)
- [ ] 4.2 `spec_edit_since_stop`: the person's commits after the stop commit, restricted to the unit folder outside harness files. Tests SCN-OPS-06 and SCN-OPS-07. (L4-OPS-003)
- [ ] 4.3 The start of a run after the push: `start_run(base)`, the output line for each result, and `--no-run`. Tests SCN-OPS-04 and SCN-OPS-05 with a fake forge. (L4-OPS-002)
- [ ] 4.4 `l4 resume` becomes `retry` restricted to `halted` and `escalated`, with its flags and refusals unchanged (`tests/unit/state/test_resume.py` stays green). (L4-OPS-001)
- [ ] 4.5 `l4 restart` with the seven steps of D4: the attempts refs, the folder rules, the new branch and its ledger file, the push with a lease, `close_pr`, and `start_run`. Tests: SCN-OPS-08, SCN-OPS-09, a restart of an `abandoned` unit, and a restart after the branch was deleted. (L4-OPS-004)

## 5. Sweep and labels (wave 2, agent E: `ci/sweeper.py`, `ci/resume_label.py`, `forge/pushfail.py`)

- [ ] 5.1 The sweep reads `<prefix>retry` and `<prefix>resume` (both mean retry) and `<prefix>restart` with the member rule. One action per label event. `restart` is also read on the closed merge request of an `abandoned` unit. The refusal text names the command. (L4-OPS-008, SCN-OPS-14)
- [ ] 5.2 A merge request closed without a merge gives `pr.closed` and `abandoned`, with the note `### Abandoned: the merge request was closed without a merge`. A reopened merge request gives `pr_reopened`. (L4-OPS-009, SCN-OPS-16)
- [ ] 5.3 The deleted-branch message (`forge/pushfail.py`) names `l4 restart --unit <unit> --reason TEXT`. (L4-OPS-009)

## 6. Status and plan (wave 2, agent F: `state/status.py`, the reason rows of `planner.py`)

- [ ] 6.1 The `REASON` column, cut to 60 characters, with D6's content for each phase. The table tests and the golden outputs are updated. (L4-OPS-006, SCN-OPS-11)
- [ ] 6.2 `l4 status --unit U` prints the detail block with `Next: <command>`. `--json` carries `reason` and `next`. (L4-OPS-006)
- [ ] 6.3 `l4 plan` uses `halt_detail` for `halted` and `escalated`, and the dismissed-verdict reason from 2.3. (L4-OPS-006)

## 7. Docs and SPEC (wave 3)

- [ ] 7.1 SPEC: the L4-OPS-001..013 requirement texts in the operations section, delivery row 19, and the new lifecycle rows in 12.0. `scripts/check_spec.py` reports nothing uncovered or undefined.
- [ ] 7.2 `docs/runbook.md`: each stuck situation gets one command and one label. Section 11 drops the limits this change removes. The text stays in ASD-STE100.
- [ ] 7.3 `docs/state-diagram.md`: the new edges.
- [ ] 7.4 The skill's `references/operate.md`: `l4 retry` and `l4 restart`. Re-run its operate scenarios (S3, S6, S7 of `plugins/l4/tests/with-skill.md`) with the skill, and record the result.

## 8. Review and live validation

- [ ] 8.1 An independent review of the whole change on the session model. Fix every confirmed finding.
- [ ] 8.2 The full suite is green on the 8 CI shards.
- [ ] 8.3 Live validation on the GitHub dummy, with evidence in `docs/live/operator-commands/`:
  - a halted unit, `l4 retry` by command, and the started run;
  - an escalated unit, `l4:retry` by label;
  - `l4 restart` by command, and `l4:restart` by label;
  - a closed merge request made `abandoned`, then restarted;
  - the `REASON` column in the CI `l4 status` step.

  (L4-OPS-013)
- [ ] 8.4 The GitLab pipeline start: a recorded API exchange in a test. A live call follows if a GitLab test project is available. (L4-OPS-013)
