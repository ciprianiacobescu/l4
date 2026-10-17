## Why

An independent review of 0.4.13 confirmed four findings, with reproductions. They still apply to 0.4.14 with the squash
merge, leased branch deletion and `refs/l4/merged/*` keep refs: each reproduction was run again against this source.
Together they let a `merge: auto` plan land code that nobody verified, or code that the repository's own CI says is red.

- **yolo-1 (major).** The guarded merge lands the branch tip, not the hand-off commit H. It trusts commits after H on
  identity text that anyone can write. In the reproduction, someone pushed a commit that adds `evil.py`, after the
  review, with the bot's name and an `L4-Run` trailer. The next plan step squash-merged it onto the target, deleted the
  branch and integrated the unit. A forged second hand-off commit on top also becomes H, because `handoff_commit` takes
  the newest commit whose subject matches. `pr.ready{head}` already records the real H, but nothing reads it.
- **yolo-2 (major).** The sweep can record a red `ci.failed` on H, and the planner then says `verify`. The plan step
  merges the unit anyway: `_merge` never asks the planner, and the guard reads no CI. More broadly, the plan never waits
  for H's CI: in the usual timing it merges before the CI has finished.
- **forge-vcs-ci-1 (major).** GitHub check runs are merged by name across workflows. A failed `build` of `tests.yml` is
  hidden behind a passing `build` of `docs.yml`, and H is reported green.
- **forge-vcs-ci-4 (minor).** When the only check run on H is the harness's own `l4` job, skipped, H is reported green
  instead of `not_run` (L4-GHP-008).

## What Changes

- **H is a record, not a commit message** (L4-ARC-008). `pr.ready{head}` is folded into `UnitState.ready_head`. The
  review after the hand-off counts from the recorded H. With `archive.mode: post_merge_pr`, the only mode built, the
  harness pushes nothing to the unit branch while the PR is ready, so every commit after the recorded H re-enters review
  whatever its identity. A recorded H that is no longer an ancestor of the branch head is rewritten history.
- **The merge lands the recorded H and nothing else** (L4-YOLO-040, L4-YOLO-008, L4-YOLO-032). There is no merge
  without a recorded H, or when the branch head or PR head is not H. The squash call is pinned to `sha` H, and the
  fast-forward pushes H.
- **A review edge comes before the merge** (L4-YOLO-041). If the planner gives an in-review unit work (red CI recorded
  on H, a commit after H), the plan dispatches the unit and does not merge it.
- **The merge waits for the repository's CI on H** (L4-YOLO-042, L4-YOLO-043, L4-YOLO-013). If that CI is running,
  red, not run or unreadable, the merge is `merge_not_ready` with a detail that says why and what clears it. A job red
  on H and on the base does not block. `yolo.merge.require_ci` (default `true`) lets a repository whose hand-off pushes
  start no CI merge on record. `unit.merged` records what the CI said.
- **A GitHub check run is one job of one workflow** (L4-CI-010, L4-CI-011). Check runs are keyed by workflow file,
  event and job name, found through the commit's workflow runs and every attempt of each. Other apps are keyed by their
  slug. The base comparison matches `<workflow file> / <job>`.
- **No job of the project on H is `not_run`** (L4-CI-012, L4-CI-002). This holds on every forge, and the skipped `l4`
  job does not count. The reason says which case it is. The sweep and the merge read H's CI through one function.
- **GitLab parity.** Jobs are still keyed by name: a commit's pipelines all run the project's one CI configuration. A
  GitLab H with no pipeline job is now `not_run` (it was `ci_green`), and the merge gate is the same on both forges.

## Impact

- Code: `src/l4/state/fold.py` (`ready_head`), `src/l4/state/review.py` (`after_handoff(..., recorded=)`),
  `src/l4/state/status.py`, `src/l4/orchestrator.py` (`_review`), `src/l4/yolo/merge.py`, `src/l4/yolo/cycle.py`,
  `src/l4/yolo/model.py` (`MergeOutcome.ci`), `src/l4/config/schema.py` (`YoloMergeCfg.require_ci`), the new
  `src/l4/ci/handoff_ci.py`, `src/l4/ci/repo_ci.py`, `src/l4/ci/sweeper.py`, `src/l4/forge/base.py` (`JobResult`),
  `src/l4/forge/github.py`, `src/l4/forge/local.py`.
- Tests: the reviewer's reproductions ported under `tests/unit/yolo/` and `tests/unit/ci/`, with their assertions turned
  around. The test worlds now record H and give it a green CI job by default. `FakeGitHub` serves workflow runs.
- Docs: `docs/SPEC.md` (L4-ARC-008, L4-YOLO-008, L4-YOLO-013, L4-YOLO-032, L4-YOLO-040..043, L4-CI-002,
  L4-CI-010..012, SCN-YOLO-100..119, SCN-CI-050..060, §3.2, §12.1, the change row), `docs/runbook.md`,
  `docs/yolo-mode.md`, `CHANGELOG.md`.
- **Behaviour changes on upgrade.** A `merge: auto` plan no longer merges until the repository's CI on H is finished
  and not red. On GitHub, a hand-off pushed with the workflow's `GITHUB_TOKEN` starts no CI, so the plan waits
  (`merge_not_ready`) until the person gives the push a token that starts runs, or sets
  `yolo.merge.require_ci: false`. GitHub job names in `ci.failed` gain their workflow file (`tests.yml / build`).
