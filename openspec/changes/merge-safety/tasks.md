Every task follows these rules:
- Write the named tests first and see them fail, then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`. Then `ruff check .`,
  `ruff format --check` on the files that changed, and `python scripts/check_spec.py docs/SPEC.md`.
- Never wait on a process with `while pgrep -f ...`; never run tests in the background. Stage explicit paths only.
- Name a consumer "a consumer repository".
- `<review>` is the reviewer's scratch folder `l4review/`; the orchestrator gives its path. Its reproductions assert
  the bug (they pass on 0.4.14). A port copies the setup, fixes the imports and asserts the intended behaviour as the
  task says. When a file is gone, build the setup from the description in the task.
- The design decisions are in `design.md` (D1..D9). Text in backticks in a test assertion is the exact text.

## 1. The recorded hand-off commit H (L4-ARC-008, design D1, D2)

- [x] 1.1 Tests first.
  - `tests/unit/yolo/test_merge_safety_handoff.py`, ported from
    `<review>/verify-yolo/repo/tests/unit/vy/test_vy1_forged_after_h.py`.
    - Setup: a `CycleWorld` with an active `merge: auto` plan. The unit branch `l4/openspec/a` has a commit, then H made
      as the bot (`docs(a): hand off to review`, trailers `L4-Run`, `L4-Phase: verified`), then a commit that adds
      `evil.py`, then (for SCN-YOLO-101) an empty second hand-off commit as the bot. The branch is pushed, with an open
      PR.
    - Imports: `from .yolo_cycle_world import CycleWorld, ev, unit_id` and `from .yolo_ledger_world import _env, sh`.
    - In `build()`, make the review the way `load_snapshot` will: `after_handoff(world.git,
      f"refs/remotes/origin/{BRANCH}", "a", "openspec/changes/a", recorded=real_h)`. The state gets
      `ready_head=real_h`. Return the `evil.py` commit's sha too.
    - `test_a_bot_identity_commit_after_h_is_not_merged` (SCN-YOLO-100): the `evil.py` commit is made with the
      bot's identity and `L4-Run`. Assert `snap.review.reentry` and `[c.sha for c in snap.review.foreign] == [tip]`.
      After `world.step({"a": snap})`: neither `unit.merge_requested` nor `unit.merged` is in `world.kinds()`,
      `evil_on_main(world)` is False, and `step.allow == frozenset({A})`.
    - `test_a_person_commit_after_h_is_not_merged` (SCN-YOLO-102): the reproduction's control, with the recorded H.
    - `test_a_forged_second_handoff_commit_is_not_h` (SCN-YOLO-101): `r.handoff == real_h`, `not r.at_handoff`,
      `r.reentry`, `[c.sha for c in r.foreign] == [evil, tip]`, and after the step no `unit.merged`.
  - `tests/unit/orchestrator/test_review_reentry.py`, `test_a_bot_identity_commit_after_h_reverifies`
    (SCN-YOLO-100, run side). Commit as `human_commit` does, but with `raw(clone, "-c",
    f"user.name={BOT_IDENTITY.name}", "-c", f"user.email={BOT_IDENTITY.email}", "commit", "-q", "-m",
    "chore: tidy\n\nL4-Run: r-20261014T1000Z-0002")`. After `second = run_l4([JUDGE])`, the last three
    `(from, to, trigger)` of `second.events("phase.changed")` are the three of
    `test_human_code_commit_after_handoff_reverifies_and_hands_off_again`, starting with
    `("in_review", "verifying", "commit_after_handoff")`.
  - `tests/unit/state/test_review.py`, with its `Branch` helper:
    - `test_a_recorded_h_off_the_branch_is_lost` (SCN-YOLO-103): make H, then `git reset --hard H~1` and a person's
      commit. `after_handoff(..., recorded=h)` is `lost` and `reentry`, and `review_trigger(after,
      UnitState(unit="openspec:add-x", phase="in_review"))` is `Trigger.COMMIT_AFTER_HANDOFF` with
      `context["lost"] is True`.
    - `test_without_a_recorded_h_the_identity_rule_stays` (SCN-YOLO-104): H, a strict bot commit `bot`, a person's
      commit `human`. `after_handoff(...)` gives `handoff == h` and `foreign == [human]`.
      `after_handoff(..., recorded=h)` gives `foreign == [bot, human]`.
  - `tests/unit/state/test_fold.py`, `test_pr_ready_folds_into_ready_head`: `pr.ready{head: h1}` then
    `pr.ready{head: h2}` give `ready_head == h2`. A later `pr.ready` without `head`, or with a non-string `head`,
    changes nothing. With no `pr.ready`, `ready_head` is None.
  - `tests/unit/state/test_status_branch.py`, `test_the_snapshot_passes_the_recorded_h_to_the_review`: push a unit
    branch whose ledger (`unit_repo.write_ledger`) ends with `phase.changed` to `in_review` and `pr.ready{head: B}`,
    where B is the branch's first commit. Monkeypatch `l4.state.status.after_handoff` with a wrapper that records its
    keyword arguments and calls the real function. Then `recorded == B` and `snapshot.state.ready_head == B`.
- [x] 1.2 Code.
  - `src/l4/state/fold.py`: `UnitState.ready_head`, `_pr_ready`, `HANDLERS["pr.ready"]`.
  - `src/l4/state/review.py`: `after_handoff(..., *, recorded=None)` as D2, and update the module docstring.
  - `src/l4/state/status.py` `load_snapshot` and `src/l4/orchestrator.py` `_review`: pass `recorded=` the state's
    `ready_head`.
  - Run: the files of 1.1, `tests/unit/state`, `tests/unit/planner/test_review_rows.py`,
    `tests/unit/archive/test_handoff_reentry.py`, `tests/unit/ci/test_sweeper.py`, `tests/unit/orchestrator`,
    `tests/unit/yolo`.

## 2. The merge lands the recorded H (L4-YOLO-040, L4-YOLO-008, L4-YOLO-032, design D3, D9)

- [x] 2.1 Fixtures, then tests first.
  - Fixtures: `CycleWorld.in_review` gets the default `"ready_head": head` in `fields`, which `**state` can override.
    In `tests/unit/yolo/test_yolo_merge_guard.py` and `tests/unit/yolo/test_yolo_merge_squash.py`, every in-review
    `UnitState(...)` gets `ready_head=` the hand-off commit that the snapshot's `AfterHandoff.handoff` names. A test
    whose point is a branch that moved keeps `ready_head` at the old H. Any other test under `tests/unit/yolo` that
    builds an in-review snapshot by hand for a merge gets `ready_head` the same way.
  - `tests/unit/yolo/test_merge_safety_guard.py` uses the `World`, `FakeForge` and `pull` of
    `test_yolo_merge_guard.py` (import them):
    - `test_a_head_that_is_not_the_recorded_h_is_not_merged` (SCN-YOLO-108): H is `world.handoff`. Commit X on the
      unit branch and push it. Snapshot `AfterHandoff(handoff=X, head=X)` with `ready_head=H`. `merge_guarded` is
      `not_ready`, `X[:10]` and `H[:10]` are in the detail, and `world.target()` is unchanged.
    - `test_no_recorded_h_is_not_merged` (SCN-YOLO-109): the snapshot is at H with `ready_head=None`. The result is
      `not_ready`, `l4 retry --unit openspec:x` is in the detail, and the target is unchanged.
    - `test_a_fast_forward_pushes_the_recorded_h` (SCN-YOLO-105): the World's `fast-forward` config and
      `ready_head=H`, which is the tip. The result is `merged`, `out.head == out.landed == H`, and
      `world.target() == H`.
  - `tests/unit/yolo/test_merge_safety_guard.py`, `test_the_squash_merge_is_pinned_to_the_recorded_h` (SCN-YOLO-106):
    a `CycleWorld` with the default squash. After the step, `world.forge.get_pr(1).head_sha == H`, the landed commit's
    tree is H's tree in `world.origin`, and the plan ledger's `unit.merged` has `head == H` and `merge_commit` that
    commit.
- [x] 2.2 Code. In `src/l4/yolo/merge.py`, `_recorded_head` replaces `_unit_head`, and the checks of D3 run in order
  with their exact details. Every use of the head becomes H: the `ls-remote` and PR-head checks, `squash_merge`,
  `guarded_push` and `push_fast_forward`. The re-entry detail is reworded as D3 says. `cycle._merge` already passes
  `out.head` to `_delete_after_merge` and `_integrate`, and that is now H. Run: the files of 2.1 and `tests/unit/yolo`.

## 3. A review edge comes before the merge (L4-YOLO-041, design D4)

- [x] 3.1 Tests first, in `tests/unit/yolo/test_merge_safety_review_edge.py`, ported from
  `<review>/verify-yolo/repo/tests/unit/vy/test_vy2_ci_red.py`.
  - Setup: an active `merge: auto` plan, `unit.dispatched` seeded, `head = world.unit_branch("a")`, an open PR, and
    `world.in_review("a", head, ci_failure=CiFailure(head=head, jobs=[{"name": "unit-tests"}], preexisting=[],
    pipeline=7))`. Imports come from `.yolo_cycle_world`.
  - `test_red_ci_recorded_on_h_is_verified_not_merged` (SCN-YOLO-110): `next_action(facts_of(snap))[0] == "verify"`.
    After the step there is no `unit.merge_requested` or `unit.merged`, `world.landed(head)` is False,
    `step.allow == frozenset({A})`, and one of `step.actions` contains `dispatched openspec:a (in_review)`.
  - `test_without_a_pr_the_unit_is_dispatched_for_verification`: the reproduction's control.
  - `test_the_guarded_merge_refuses_recorded_red_ci_on_h` (SCN-YOLO-111): `merge_guarded(world.app, world.cfg,
    world.git, world.forge, snap, before_push=lambda _: True, sleep=lambda s: None)` is `not_ready`, and its detail
    contains `the repository CI failed on the hand-off commit`, `unit-tests` and `(recorded)`. `world.landed(head)` is
    False.
- [x] 3.2 Code.
  - `src/l4/yolo/cycle.py` `_merge`: `if self._unit_action(snap) in _ACTIONABLE: return None` right after the PASS
    check.
  - `src/l4/yolo/merge.py`: the recorded-red check (D3 step 3).
  - Run: the file of 3.1 and `tests/unit/yolo`.

## 4. A GitHub check run is one job of one workflow (L4-CI-010, L4-CI-011, design D6, D8)

- [x] 4.1 Tests first.
  - `tests/unit/forge/_github_helpers.py` `FakeGitHub`: `add_workflow_run`, `add_check_run(..., app=None)`, the two
    routes and `workflow_runs_status`, as D9 says.
  - `tests/unit/ci/test_check_run_identity.py`, ported from
    `<review>/verify-forge-vcs-ci/copy/tests/unit/ci/test_verify_fvc_ci.py` (`test_fvc1_*`). The world is the
    sweeper's `review`, and `GitLabForge.list_pipeline_jobs` is monkeypatched onto a real `GitHubForge` over an
    `httpx.MockTransport`. Its handler also answers `GET /repos/o/r/actions/runs` by `head_sha`:
    - on H, `tests.yml` is suite 1 and `docs.yml` is suite 2; on the base, suites 3 and 4;
    - every check run has `"app": {"slug": "github-actions"}`;
    - `test_a_failed_job_of_one_workflow_is_not_hidden` (SCN-CI-051): `action.what == "ci_failed"`, and
      `tests.yml / build` is in `action.detail`;
    - keep the control.
  - `tests/unit/forge/test_github_checks.py`:
    - `test_a_rerun_collapses_whether_or_not_it_has_a_new_suite` (SCN-CI-052) is parametrized. Run 900 of `tests.yml` has
      `run_attempt: 2`. Variant A: both check runs `test` are in suite 31. Variant B: attempt 1 is in suite 31, attempt 2
      in suite 32, and the attempts route answers 31 for attempt 1. Each time there is one job, its `key` is
      `tests.yml / test`, and it is `success`.
    - `test_push_and_pull_request_runs_are_two_jobs` (SCN-CI-053): two runs of `tests.yml`, events `push` (suite 41,
      `build` success) and `pull_request` (suite 42, `build` failure). There are two jobs with key `tests.yml / build`, and
      `red_jobs` is the `pull_request` one.
    - `test_a_check_run_of_another_app_is_keyed_by_its_slug` (SCN-CI-054): the keys are
      `{"codecov / build", "tests.yml / build"}`, and `red_jobs` is the `codecov` one.
    - `test_an_unreadable_workflow_listing_keys_actions_runs_by_suite` (SCN-CI-055): `workflow_runs_status = 403` with
      the check runs of SCN-CI-051. The workflows are `{"suite-1", "suite-2"}`, the failure is listed, and caplog has
      one warning with `could not be read`.
    - The existing tests in this file stay as they are and pass: a check run with no `app` still collapses by name.
  - `tests/unit/ci/test_repo_ci.py`, `test_the_base_comparison_matches_workflow_and_job` (SCN-CI-056): a pure
    `evaluate_ci` on `JobResult`s with `workflow`. H has `tests.yml`/`build` failed. With base `docs.yml`/`build` failed,
    the result is `failed`. With base `tests.yml`/`build` failed, it is `preexisting`.
  - `tests/unit/forge/test_gitlab_pipelines.py` (SCN-CI-057): two pipelines of one sha. The older has `test` failed and
    the newer has `test` success. There is one job, with `status == "success"`, `workflow == ""` and `key == "test"`.
    If the file has a test like this already, add the assertions to it.
- [x] 4.2 Code.
  - `src/l4/forge/base.py`: `JobResult.workflow`, `.event`, `.key`.
  - `src/l4/forge/github.py`: `list_pipeline_jobs`, `_workflow_suites`, and `_job` taking the identity, as D6 says.
  - `src/l4/ci/repo_ci.py`: `evaluate_ci` by `key`, and update the module docstring.
  - `src/l4/ci/sweeper.py` `_ci_duty`: record `name: j.key`, plus `workflow` and `event` when `workflow` is set, and
    `ci.preexisting.jobs` as keys; the action details name keys.
  - `src/l4/forge/local.py`: `script_jobs` takes `workflow` and `event`, and the `settled` dedup keys by
    `(workflow, event, name)`.
  - Run: the files of 4.1, `tests/unit/ci`, `tests/unit/forge`, `tests/unit/archive/test_repo_ci.py`.

## 5. A hand-off commit that no job of the project ran on is not_run (L4-CI-012, L4-CI-002, design D5, D7, D8)

- [x] 5.1 Tests first.
  - `tests/unit/ci/test_check_run_identity.py`, the two `test_fvc4_*` ported:
    - `test_only_the_skipped_l4_job_is_not_run` (SCN-CI-058): `action.what == "ci_not_run"`,
      `its only check run is the harness's own l4 job` is in the detail, and `GITHUB_TOKEN` is not;
    - the control (no check run, `ci_not_run`).
  - `tests/unit/ci/test_repo_ci.py`:
    - `test_no_check_run_is_not_run` stays as it is and is the test of SCN-CI-050 (name it in its docstring);
    - replace `test_gitlab_without_a_pipeline_keeps_its_behaviour` with `test_gitlab_without_a_pipeline_job_is_not_run`
      (SCN-CI-059): `["ci_not_run"]`, and `no pipeline of the project has a job on the hand-off commit` is in the
      detail.
  - `tests/unit/ci/test_handoff_ci.py` (new):
    - `test_the_sweep_and_the_merge_read_the_same_verdict` (SCN-CI-060). Five hand-off commits, scripted the way
      `tests/unit/ci/test_sweeper.py` scripts pipelines (read it first): running, green, failed (red on H, green on
      the base), pre-existing (red on both), and none. `read_handoff_ci(...).status` gives `running`, `green`,
      `failed`, `preexisting` and `not_run`, and the sweep's CI duty on the same commits gives `ci_waiting`,
      `ci_green`, `ci_failed`, `ci_preexisting` and `ci_not_run`;
    - `test_the_not_run_reason_names_the_case`: on `github` with no job, the reason is `NO_CHECK_RUN`; on `github`
      with only `l4`, it is `ONLY_HARNESS_JOB`; on `gitlab` with no job, it is `NO_PIPELINE_JOB`.
- [x] 5.2 Code.
  - `src/l4/ci/handoff_ci.py` (new): `HandoffCi`, `read_handoff_ci`, and the three reasons, as D5 and D7 say.
  - `src/l4/ci/sweeper.py` `_ci_duty`: call it, map its statuses to today's action words, and import `NO_CHECK_RUN`
    from it (the name stays importable from `sweeper`).
  - Run: the files of 5.1, `tests/unit/ci`, `tests/unit/archive/test_repo_ci.py`.

## 6. The merge waits for the repository's CI on H (L4-YOLO-042, L4-YOLO-043, L4-YOLO-013, design D5, D9)

- [x] 6.1 Fixtures, then tests first.
  - `tests/unit/config/test_schema_yolo_merge.py`: `yolo.merge.require_ci` defaults to `False`, `true` is accepted,
    and `"maybe"` is refused with the loader's message.
  - Fixtures:
    - `LocalForge.script_jobs(..., replace=False)`: with `replace=True` it drops the jobs already scripted for that
      sha.
    - `CycleWorld.in_review(..., ci=(("test", "success"),))`: unless `ci is None`, it scripts `ci` on `head` with
      `replace=True`.
    - The `FakeForge` of `test_yolo_merge_guard.py` and the fakes of `test_yolo_merge_squash.py` get
      `list_pipeline_jobs(self, sha, *, settled=False)`, which returns `[JobResult("test", "", "success", False, 1, 1,
      "")]`. So does any other fake forge that a test under `tests/unit/yolo` gives to `merge_guarded`.
  - `tests/unit/yolo/test_merge_safety_ci_gate.py` uses `CycleWorld`. The base head is
    `world.git.rev_parse("refs/remotes/origin/main")`, and the waits are read from `world.events()`:
    - `test_running_ci_on_h_holds_the_merge` (SCN-YOLO-112): `ci=(("test", "running"),)`. There is no
      `unit.merge_requested`. The last `plan.waiting` has reason `merge_not_ready`, and its detail contains
      `the repository CI is still running on the hand-off commit` and `head[:10]`.
    - `test_a_ci_wait_is_recorded_once_and_chains_no_run` (SCN-YOLO-107): two more steps while the job still runs.
      The count of `plan.waiting` events is unchanged, and `step.start_next_run is False` each time.
    - `test_the_wait_ends_when_h_is_green` (SCN-YOLO-113): then `script_jobs(head, [("test", "success")],
      replace=True)` and a step. `unit.merged` is written with `ci == "green"`.
    - `test_red_ci_on_h_not_yet_recorded_is_not_merged` (SCN-YOLO-114): `ci=(("test", "failed"),)` and
      `("test", "success")` on the base head. There is no `unit.merged`, and the wait detail contains `test` and
      `the next sweep records it`.
    - `test_a_job_red_on_h_and_on_the_base_does_not_hold_the_merge` (SCN-YOLO-115): `("lint", "failed")` on H and on
      the base head. The unit is merged with `ci == "preexisting"` and `ci_jobs == ["lint"]`, and one of
      `step.actions` contains `red as on the base: lint`.
    - `test_require_ci_true_waits_for_a_ci_and_names_the_fix` (SCN-YOLO-116): `yolo.merge.require_ci: true` (the
      `make_cfg` form of SCN-YOLO-118 below) and `ci=None`. There is no `unit.merged`, and the detail contains
      `no CI of the repository ran on the hand-off commit` and `yolo.merge.require_ci: false`.
    - `test_red_ci_on_h_blocks_even_when_no_ci_is_required` (SCN-YOLO-120): `require_ci: false` and `("test",
      "failed")` on H, `("test", "success")` on the base head. There is no `unit.merged`.
    - `test_a_preexisting_record_now_red_on_h_alone_names_the_retry` (SCN-YOLO-119):
      `world.in_review("a", head, ci_heads={head: "preexisting"}, ci=(("lint", "failed"),))` and
      `("lint", "success")` on the base head. There is no `unit.merged`, and the detail contains `lint` and
      `l4 retry --unit openspec:a`.
    - `test_unreadable_ci_is_not_green` (SCN-YOLO-117): `world.step(..., forge=...)` with a `LocalForge` subclass
      whose `list_pipeline_jobs` raises `ForgeError("HTTP 502", status=502)`. There is no `unit.merged`, and the
      detail contains `could not be read`.
    - `test_no_ci_on_h_merges_on_record_by_default` (SCN-YOLO-118): the default configuration and `ci=None`. The unit
      is merged with `ci == "not_run"` (and no `ci_jobs`), and one of `step.actions` contains `head[:10]` and
      `yolo.merge.require_ci`.
    - `test_a_fast_forward_merge_records_h_and_green_ci` (SCN-YOLO-105, plan side): `fast-forward` set as
      `test_yolo_cycle_squash.py::test_scn_yolo_78_fast_forward_stays_an_option` sets it. `unit.merged` has `head == merge_commit == H` and `ci == "green"`, and
      `world.tip() == H`.
    - In `test_the_squash_merge_is_pinned_to_the_recorded_h` (SCN-YOLO-106, task 2.1), add that `unit.merged` has
      `ci == "green"`.
- [x] 6.2 Code.
  - `src/l4/config/schema.py`: `YoloMergeCfg.require_ci`.
  - `src/l4/yolo/model.py`: `MergeOutcome.ci` and `.ci_jobs`.
  - `src/l4/yolo/merge.py`: `_ci_gate` with the details of D5's table, called at D3 step 5, and the outcome set with
    `dataclasses.replace`.
  - `src/l4/yolo/cycle.py` `_merge`: `unit.merged` gets `ci` (always) and `ci_jobs` (only when not empty), plus the
    warning lines of D5 (for `not_run` also a best-effort note on the merged PR or MR, `upsert_sticky_note`). The tests that compare a whole `unit.merged` (for example
    `test_yolo_cycle_squash.py::test_scn_yolo_78_fast_forward_stays_an_option`) gain `"ci": "green"`.
  - `src/l4/forge/local.py`: `script_jobs(replace=)`.
  - Run: the files of 6.1, `tests/unit/yolo`, `tests/unit/config/test_schema_yolo_merge.py`, `tests/unit/ci`,
    `tests/unit/orchestrator/test_accepted_carrier.py`.

## 7. Docs

- [ ] 7.1 `docs/SPEC.md`.
  - **L4-ARC-008 (§11).**
    - After "and marks the PR ready.", add: "It records the sha of H as `pr.ready{head}` on the unit's lock ref
      (L4-STA-004), and that record is H from then on (`UnitState.ready_head`)."
    - Replace "Any commit after H that the harness did not make (a commit is the harness's only when ... is a
      person's) **voids the approval**" with: "Any commit after the recorded H that the harness did not make **voids
      the approval**. With `archive.mode: post_merge_pr`, where the harness pushes nothing to the unit branch while
      the PR is ready (L4-ARC-007), that is every commit after the recorded H, whatever its author, committer or
      trailers, and a recorded H that is not an ancestor of the branch head is rewritten history. Only a unit with no
      recorded H keeps the identity rule: a commit is the harness's only when its author **and** its committer are
      the harness bot identity **and** it carries an `L4-Run` trailer, so an amended, rebased or cherry-picked H is a
      person's."
  - **L4-YOLO-008.**
    - "no person's commit after the hand-off" becomes "no commit after the recorded hand-off commit H and no other
      review edge to take (L4-YOLO-041)".
    - "the head to push equals the tip of the unit branch on `origin` and the head of the PR" becomes "the recorded H
      (L4-YOLO-040) equals the tip of the unit branch on `origin` and the head of the PR, and the repository's CI on H
      allows the merge (L4-YOLO-042)".
    - "pinned to the unit head" becomes "pinned to H", and "pushing the unit head" becomes "pushing H".
  - **L4-YOLO-013.** The parenthetical "(no open PR, a PR aimed at another branch, a PR head that is not the branch
    tip)" gains ", no recorded H, a branch head that is not H, or the repository's CI on H running, red and not yet
    recorded, not run, or unreadable (L4-YOLO-042)".
  - **L4-YOLO-032.**
    - "pinned to the verified head" becomes "pinned to the recorded hand-off commit H (L4-YOLO-040), never a branch
      tip it read".
    - "its tree with the head's tree" becomes "its tree with H's tree".
    - `unit.merged{head, merge_commit, method, raced}` becomes `unit.merged{head, merge_commit, method, raced, ci,
      ci_jobs}`.
  - **New paragraphs.** L4-YOLO-040..043 go after L4-YOLO-035, as bold-id paragraphs with the delta's text. L4-CI-010,
    L4-CI-011 and L4-CI-012 go after the L4-CI-005 paragraph.
  - **L4-CI-002.** In the bullet on hand-off pushes with `GITHUB_TOKEN`, "With no check run at the hand-off commit"
    becomes "With no check run at the hand-off commit, or none but the harness's own `l4` job", and the bullet cites
    L4-CI-012.
  - **§3.2.** Under `yolo.merge`, add `require_ci: false` with the comment `# true: a hand-off commit no CI ran on waits for one;
    false: it is merged, recorded as ci: not_run (L4-YOLO-043)`.
  - **§12.1.** The `pr.ready` entry says that `head` is folded as `ready_head` (L4-ARC-008). The `ci.failed` entry
    says that a GitHub job is named `<workflow file> / <job>` (L4-CI-011).
  - **Scenarios.** SCN-YOLO-100..120 go after SCN-YOLO-92 in §23.20, and SCN-CI-050..060 go after SCN-CI-16 in §23.13.
    Use SPEC form: `#### SCN-… (±) Title · L4-…`, `- **Given**`, `- **When**`, `- **Then**`, with the delta's text and
    the requirement each belongs to. SCN-YOLO-100 also cites L4-YOLO-041.
  - **§3.2 and rule 3 of `scripts/check_spec.py`.** Every config key in backticks must be in §3.2, so add
    `yolo.merge.require_ci` before you cite it. A backticked word that starts with a top-level config key and a dot
    (`ci.`, `yolo.`, `forge.` and so on) is read as a key. So the examples use `tests.yml`, never a lone `ci.yml`.
    `ci.failed` and `ci.preexisting` pass because §12.1 lists them.
  - **Rule 4 of `scripts/check_spec.py`.** The new SPEC text must not contain the retired term "at the tip".
  - **The change table of §21.** Add a row after the last row present. At 0.4.14 the last row is 39, so this one is 40
    unless another change added a row: `merge-safety`, what it does in
    one sentence with the ids, `openspec/changes/merge-safety/`, and the live check "a consumer repository's
    `merge: auto` plan after the upgrade: a hand-off push that starts no CI is now merged on
    record (`ci: not_run`) with a warning; give the push a token that starts runs and set `yolo.merge.require_ci: true`
    to make the CI gate the merge".
- [ ] 7.2 The other docs.
  - `docs/runbook.md`, the `merge_not_ready` row: list the new details (no recorded H, a head that is not H, CI
    running, red, unreadable, and not run when `yolo.merge.require_ci` is true) and their fixes (wait for the CI; `l4
    retry --unit`; give the hand-off push a token that starts runs or set `yolo.merge.require_ci: false`; check the
    token's `checks: read` and `actions: read`).
  - `docs/yolo-mode.md`: the merge paragraph (about line 164) says that the merge lands the recorded H after the
    repository's CI on it, and the waits paragraph (about line 286) lists the new causes.
  - `CHANGELOG.md`: under `## 0.4.16 (unreleased)` at the top. Create the heading above the newest section unless it
    is already there.
    - `### Fixed`: the four findings in a consumer's words.
    - `### Changed`:
      - a plan merge waits for the repository's CI on H (running, red, unreadable); `yolo.merge.require_ci` (default
        `false`) decides whether a hand-off commit that no CI ran on waits too, and the `GITHUB_TOKEN` consequence:
        by default it is merged on record (`ci: not_run`) with a warning;
      - GitHub job names in `ci.failed` are `<workflow file> / <job>`;
      - a GitLab H with no pipeline job is `ci_not_run`.
  - Run: `python scripts/check_spec.py docs/SPEC.md`, the docs tests under `tests/unit` that read SPEC.md, the runbook
    or the CHANGELOG (`grep -rl "CHANGELOG\|runbook.md\|SPEC.md" tests/unit`), and
    `npx --yes @fission-ai/openspec@1.14.1 validate merge-safety --strict`.
