# M1.7 — the base merge of verifier step 0 (planned 2026-10-05)

## Goal

Step 0 of the ladder merges the base branch into the unit branch instead of stopping (SPEC 12.3 L4-WTR-001, 10.2
L4-VER-002 step 0 "branch contains base head (else merge first)", L4-VER-011 "the round restarts … base merge in step
0"). Today `src/l4/verifier/preconditions.py:45` exits 1 with "the unit branch does not contain the base head …; merge
it in first (M1)", and on the live add-vat run a human had to merge `main` by hand (`b16c9fd`, docs/live/README.md).
M1.7 builds the merge (state-vcs-locks 1.27, 1.28), the harness-owned conflict rules for `questions.md` and `tasks.md`
(4.4–4.6) and the M1 form of a source conflict (verifier 1.6: exit 1, no verdict). **17 build lines**, test first.

## Facts this plan rests on

Labels: [V] read in code or files, [I] inferred, [U] not checked.

* **Order inside `verify_hook`** [V, ladder.py:593–664]: `consume_verdicts` (reads `questions.md`), then
  `_resumable` (computes `subject_sha` on HEAD), then judge selection, then `verify_unit`, which computes `head` and
  `subject` before step 0 runs. A merge inside `check_preconditions` would come after the reuse decision.
* **`subject_sha` skips `L4-Phase: verifying|lessons`** [V, evidence.py:44,57–68]; it walks `--first-parent` and reads
  each commit's first-parent diff. A merge commit tagged `verifying` would be invisible to it, and a NEEDS_HUMAN round
  would be reused on code it never saw.
* **Integrity after a merge** [V, integrity.py:75–82, 255–265; preconditions.py:48]: `base_sha` is
  `merge-base(base head, head)`, which is the base head once it is merged. So `diff base..head` holds only the unit's
  changes plus conflict resolutions, and `commits()` (`base..head`, only commits with `L4-Task`) ignores the merge
  commit. The red-green freeze compares the historical red and green commits, which the merge does not touch.
* **Push path** [V, orchestrator.py:173–192, vcs/git.py:166–180]: `ctx.push` is `Orchestrator.push`. It pushes
  `HEAD:refs/heads/<branch>` fast-forward only (`+` and `--force` are refused before git runs), with the forge's
  `push_config`, then `forge.after_push` and the mirror sync. `Git.commit` and `Git.push` call `on_commit`/`on_push`.
  These print `commit <sha10> <subject>` and `pushed <branch> <old10>..<new10> <compare url>` in the job log
  (progress.py:112–123). M1 has no lease: the run holds the local flock, and fenced lock refs are M2 (state-vcs-locks §2).
* **The base ref** [V, vcs/worktree.py:50–76]: `WorktreeManager.ensure` fetches `+refs/heads/<base>` with `--prune`
  before every worktree, so `refs/remotes/origin/<base>` is the run's base snapshot.
* **CI** [V, ci/templates/l4.gitlab-ci.yml]:
  * `allow_failure.exit_codes: [10, 11, 12]`: an exit 1 makes the `l4` job red;
  * the job runs the harness and the config from the base checkout, also for a push to `l4/**`;
  * a push whose head message has `L4-Run` starts no `l4` job, and `[skip ci]` skips the whole pipeline.
* **No `in_review → *` edge** [V, state/lifecycle.py:95–121; planner.py:45 "in_review: waiting for merge"]. The open
  MRs !4, !8, !10, !12, !13, !15 (all `l4:in_review`, 1–15 commits behind `main` @ `bb5f3477` [V, GitLab API
  2026-10-05]) cannot be re-triggered by an answer, so the live protocol seeds new units.
* **Runner git is 2.34.1** [V, docs/runner/README.md:66]: no `merge-tree --write-tree` (needs 2.38). Everything below
  uses `merge --no-commit`, `ls-files -u` and `show :N:path`.
* **`state.json` is not written** [V, state/fold.py:1–4]: the ledger is folded on read, so the "re-fold `state.json`"
  rule has nothing to act on yet.
* **Clarifier lever** [V, config/schema.py:286–288; orchestrator.py docstring]:
  * `clarifier.enabled: false` sends blocking questions straight to `awaiting_human` (exit 11);
  * the default `auto_accept_kinds` is `[technical]`.
* **Conflicting appends** [V, docs/live/m14/s5-not-run-merge-conflicts.txt]: in trial merges, two branches that each
  append a method to `Cart` conflict in `src/pricing/cart.py`.

## Decisions

1. **Where.** `bring_in_base(ctx)` is the first statement of `verify_hook`, before `consume_verdicts`, `_resumable`
   and `bench()`. It folds the ledger itself for the round number of its `verify.step` event (the same
   `last_verdict.round + 1` that `verify_hook` computes later). It lives in a new `src/l4/verifier/basemerge.py`, so `ladder.py`, which M1.5 and M1.6 also edit,
   changes by one call. `check_preconditions` keeps its ancestor check as a guard that should never fire, with the
   message "bug: the base merge of step 0 did not run".
2. **How.** The merge runs as `git -c rerere.enabled=false -c merge.autoStash=false merge --no-ff --no-commit
   <base sha>` in the unit worktree (`HARDENING` scrubs the environment, not the runner user's `~/.gitconfig`),
   then `Git.commit` with the bot identity. There is never a fast-forward, rebase, amend or forced push. The merge is
   pushed at once through `ctx.push()`, before any gate, so a crash after it does not merge twice. If the push is
   refused, `explain_push_failure` applies as for every harness push.
3. **No re-fetch.** The base is the `ensure` snapshot of this run. A base that moves during the run is merged by the
   next run.
4. **Message and trailers.**
   * Subject: `chore(<unit-name>): merge <base>@<sha10> into the unit branch [skip ci]` (`clip_subject` keeps the
     `[skip ci]`).
   * Trailers: `L4-Unit`, `L4-Run`, `L4-Iteration`, `L4-Phase: verifying` (the unit's phase: an internal step does
     not change it, SPEC 12.0).
   * No `L4-Task`, `L4-TDD` or `L4-Step`, because reconcile parses `L4-Step` and integrity keys on `L4-Task`.

   The commit starts no pipeline. The hand-off commit H (no `[skip ci]`) runs the project's CI on the merged tree.
5. **Subject.** `subject_sha` never skips a commit with two or more parents because of its phase; its first-parent
   diff still decides. A merge that brings code is a new subject, so the round restarts at step 0 (L4-VER-011). A merge
   whose first-parent diff is empty or touches only harness-owned files is not a new subject, so reuse stays correct.
6. **No-op.** When the base head is already an ancestor of HEAD: no `git merge`, no commit, no push, no event. The
   step-0 note reads `base <base>@<sha10> contained`.
7. **Frozen red tests.** The merge is never an integrity matter (see Facts). Files from `task.red_ok.frozen` that the
   merge changed are recorded in `base.merged.frozen_touched` and shown in the step-0 note. Step 3 re-runs every test,
   red tests included, on the merged tree. A base that breaks the unit is a FAIL and goes to the normal fix loop.
8. **Harness-owned conflicts** are resolved before anything is aborted:
   * **`<unit>/questions.md`**, merged per question id, `base` may be absent (add/add: the harness creates the file on
     the branch). Rules, applied in order:
     1. byte-identical sections are kept;
     2. a section that only one side changed against the base takes that side;
     3. if exactly one side carries a human answer (`answered_by == "human"` and `is_answered`), that side wins;
     4. otherwise the side whose last commit touching the file is newer (`%ct`) wins, and a tie goes to the unit branch.

     A question on one side only is kept, and the index is refreshed. When the unit branch wins every question and
     the base adds none, the result is the unit branch's bytes unchanged. The same id holding a different question
     (title or asked text) escalates.
   * **`<unit>/tasks.md`**: both sides are compared with every marker blanked. If they are byte-identical, the result
     is the unit branch's bytes, with a task marked done when either side has it done (a byte splice as in
     `specs/markers.py`). Any other difference escalates.
   * **Ledger paths** (`<unit>/.l4/ledger/*`) cannot conflict (one file per run). A conflict there is refused as a
     harness bug.
   * **`state.json`** is not written by the harness (see Facts), so there is no rule.
   * **Archive**: if `base..HEAD` holds an `L4-Phase: archived` commit, the merge is refused with "archive revert before
     a base merge (L4-ARC-006, state-vcs-locks 4.7) is not built". With the default `post_merge_pr` mode a unit branch
     never has one.
   * **`lessons.md`**: M1.5 is not on `main`. Its merge owes a lesson-id union resolver (contract note for m15).
9. **Source conflicts (the M1 form of verifier 1.6):**
   * The merge is aborted with `merge --abort`: nothing is committed or pushed.
   * Events: `base.conflict{base, base_sha, files, resolved}` and `verify.step{round, step: "0", status: "error",
     reason: "base-merge-conflict"}`.
   * `BaseMergeConflict(L4Exit)`, exit 1, defined in `l4.vcs.merge` (the orchestrator must not import a verifier
     module: `ladder.py` imports the orchestrator). The phase stays `verifying`, the job is red, there is no verdict.
   * `Orchestrator._verify` catches it, sets the sticky section "Base merge needed: merging `<base>`@`<sha10>` into
     `<branch>` conflicts in <files>. Merge `<base>` into the branch by hand, resolve, push; the next run verifies
     again. Every run until then exits 1." It then calls `_sync_mirror()` and re-raises.
   * Clearing the note: `MirrorHook.sync` replaces the sticky only when it is given notes (archive.py:175–182), so a
     stale section would survive a later success. When step 0 finds the branch containing the base (merged now or by
     a human), and the last `base.*` event in the folded ledger is `base.conflict`, `bring_in_base` sets
     `ctx.shared["notes"] = ()`, which clears the note. A NEEDS_HUMAN in the same hook still overrides it
     (`_ask_verdicts`).
   * The 3-strike escalation of L4-VER-010 has no code [V, grep], so the run exits 1 on every pipeline until the
     merge is done.
   * **Deferred: the conflict task (state-vcs-locks 4.8, 4.9; verifier 5.12, SCN-VER-22).** All three tasks sit in M2
     sections, and verifier 1.6 itself scopes M1 to exit 1. Building them needs:
     * a conflict-resolution prompt, and a TDD-exempt commit kind outside `tasks.md`, which integrity's TDD history
       must accept;
     * attempt accounting, and a new `verifying → escalated` trigger.

     The sim scenario `base-branch-moved-conflict` (owner forge-and-ci) stays `pending`.
10. **Answers and verdicts.** The merge runs before `consume_verdicts` and `_resumable`. So a run triggered by answers
    on a branch behind its base merges first, and its round is judged afresh (new subject). The human verdicts carry
    over by criterion text hash and `carry_rejects` (SCN-VER-48, live-fix `69ef5b4`). A run triggered by answers that
    implements first merges at step 0 of the verification that follows in the same run.
11. **Dry run.** In `l4 run --dry-run`, a unit whose remote branch lacks the base head gets this line:
    `  base moved: step 0 merges <base>@<sha12> (<n> commits behind; changed on both sides: <files>|none)`. The
    overlap is `diff --name-only mb..base ∩ mb..branch`, read-only and valid on git 2.34. `l4 verify --dry-run`
    still raises USAGE_ERROR. `l4 plan` reasons are left alone, because `tests/live` parses those rows.
12. **Not merged:** `in_review` and `archived` units. With `post_merge_pr` the harness pushes nothing to a ready MR
    (L4-ARC-007), and L4-ARC-004/006 are not built. The forge shows the human that the MR is behind or conflicting.
    **Known limit:** a base that adds an unchecked task to this unit's `tasks.md` fails step 0's done-gate (FAIL),
    because the `verified → implementing` edge is not built.

## Build lines

Line format: `n. task — what · test (write it first, see it fail) · code · verify`. Stage A edits only new files.
Merge `main` before line 9 (`ladder.py` is shared with m15 and m16).

**Stage A — `l4.vcs.merge` (new)**
1. state-vcs-locks 1.27 — `merge_base_into(git, base_sha, *, message, trailers, resolvers) -> MergeResult` (clean:
   two-parent commit, old head and base head as parents, pushed SHAs unchanged) · `tests/unit/vcs/test_merge.py::
   test_base_merged_pushed_history_untouched` · `src/l4/vcs/merge.py` · `uv run pytest tests/unit/vcs/test_merge.py -q`
2. state-vcs-locks 1.28 — `Git.history` of a merge plus push holds no `rebase`, `--amend`, `+` refspec or `--force`
   · `::test_update_never_rewrites_pushed_history` · same · same
3. no-op — the base head is an ancestor: `MergeResult(kind="noop")`, and no `merge` argv in `Git.history` ·
   `::test_branch_containing_base_is_a_noop` · same · same
4. safety — a dirty worktree is refused before `merge`, and after an abort the run's unstaged ledger lines are still
   on disk (`reset --merge` semantics, tested here, not assumed) · `::test_dirty_worktree_refused_before_merge`,
   `::test_conflict_abort_keeps_unstaged_ledger_lines` · same · same
5. classification — `ls-files -u` and `run_bytes("show", ":1|2|3:<path>")` (byte-exact, base stage optional) feed a
   resolver table. An unresolved file aborts and returns `MergeResult(kind="conflict", files, resolved)`. A ledger
   path or an `L4-Phase: archived` commit is refused · `::test_source_conflict_aborts_and_names_files`,
   `::test_ledger_path_conflict_is_refused`, `::test_archived_commit_on_branch_refuses_merge` · same · same

**Stage B — harness-owned resolvers (new files)**

6. state-vcs-locks 4.6 — `merge_questions(base | None, ours, theirs, ours_newer) -> bytes` (rules of decision 8) ·
   `tests/unit/vcs/test_merge.py::test_questions_merged_per_id_newer_human_answer`;
   `tests/unit/specs/test_questions_merge.py::test_add_add_without_base`, `::test_unit_side_winning_all_is_byte_identical`,
   `::test_one_sided_question_kept_and_index_refreshed`, `::test_same_id_different_question_escalates` ·
   `src/l4/specs/questions_merge.py` · `uv run pytest tests/unit/specs/test_questions_merge.py tests/unit/vcs/test_merge.py -q`
7. state-vcs-locks 4.4, 4.5 — `merge_task_markers(ours, theirs, framework)`: union of done markers when the bytes with
   markers blanked are identical, else `Escalate` (OpenSpec and Kiro marker forms) ·
   `test_merge.py::test_tasks_md_union_of_done_markers`, `::test_differing_task_text_escalates` ·
   `src/l4/specs/tasks_merge.py` · same

**Stage C — step 0, lifecycle surface, trace**

8. verifier 1.6 (merge part) — `bring_in_base(ctx) -> BaseMerge`:
   * base `refs/remotes/origin/<forge.base_branch>`;
   * message and trailers of decision 4;
   * `ctx.push()`;
   * `base.merged{base, base_sha, merge_sha, behind, resolved, frozen_touched}`;
   * on conflict: `base.conflict`, `verify.step{…status error, reason base-merge-conflict}`, `BaseMergeConflict`,
     nothing pushed.

   Tests: `tests/unit/verifier/test_preconditions.py::test_base_merged_before_gates_and_conflict_is_error_in_m1` (the
   task's name: parents, trailers, `[skip ci]`, pushed head, event; the conflict half), plus
   `::test_frozen_file_changed_by_merge_is_recorded_not_a_finding`. Code: `src/l4/verifier/basemerge.py`. Verify:
   `uv run pytest tests/unit/verifier/test_preconditions.py -q`.
9. ladder seam — `bring_in_base(ctx)` is the first statement of `verify_hook` (it folds for its own round number), and
   the step-0 note carries the merge.
   Test: `tests/unit/verifier/test_ladder.py::test_base_merge_runs_before_the_reuse_decision` (round 1 NEEDS_HUMAN, the
   base moves, the verdicts are answered; the judge is called and no step is `reused`). Code:
   `src/l4/verifier/ladder.py`. Verify: `uv run pytest tests/unit/verifier/test_ladder.py tests/unit/verifier/test_resume.py -q`.
10. subject — a commit with two or more parents is never skipped for its phase ·
    `tests/unit/verifier/test_resume.py::test_base_merge_commit_is_a_new_subject`,
    `::test_merge_with_empty_first_parent_diff_is_not_a_subject` · `src/l4/verifier/evidence.py` · same as 9
11. guard text — the ancestor check stays, with the message "bug: the base merge of step 0 did not run". Change the
    assertion of the existing `test_preconditions.py::test_a_branch_that_lacks_the_base_head_is_an_error_not_a_verdict`
    (it calls `check_preconditions` directly, so it still raises) · `src/l4/verifier/preconditions.py` · line 8's
    command
12. MR note — `_verify` catches `BaseMergeConflict`, sets the sticky section of decision 9, syncs and re-raises.
    `bring_in_base` clears the note on the next success after a `base.conflict` ·
    `tests/unit/orchestrator/test_run_unit.py::test_base_conflict_sets_sticky_note_and_exits_1`,
    `::test_next_successful_merge_clears_the_conflict_note` ·
    `src/l4/orchestrator.py` · `uv run pytest tests/unit/orchestrator -q`
13. trace — `base.merged` → INFO `base merged: <base>@<sha10> into <branch> as <merge10> (<n> commits[; resolved
    <files>])`. `base.conflict` → WARNING `base merge conflict with <base>@<sha10>: <files>; merge it by hand and push
    (exit 1)` · `tests/unit/obs/test_progress.py::test_base_merge_lines` · `src/l4/progress.py` ·
    `uv run pytest tests/unit/obs -q`
14. integrity — a clean merge that changes code under test and a pre-existing test file that the unit also extended
    adds no integrity finding, and `commits()` ignores the merge ·
    `tests/unit/verifier/test_integrity.py::test_clean_base_merge_adds_no_integrity_finding` · no code expected (a
    failure here is a bug to fix in `integrity.py`) · `uv run pytest tests/unit/verifier/test_integrity.py -q`
15. dry run — the line of decision 11 · `tests/unit/sim/test_dryrun.py::test_base_moved_line_names_overlap` ·
    `src/l4/sim/dryrun.py`, plus `base_moved(git, base, branch)` in `src/l4/vcs/merge.py` ·
    `uv run pytest tests/unit/sim/test_dryrun.py -q`
16. end to end (`run_l4` + `tdd_repo` + `raw`):
    * `tests/unit/verifier/test_verdict_reentry.py::test_answer_on_a_branch_behind_base_merges_then_hands_off`:
      round 1 NEEDS_HUMAN, `main` moves, verdicts answered; then the merge commit, a full round, PASS, and H with the
      merge on its first-parent chain;
    * `::test_conflict_exits_1_with_note_and_pushes_no_merge`;
    * `::test_questions_md_on_both_sides_is_resolved_by_the_harness`.

    Code: whatever the earlier lines missed. Verify: `uv run pytest tests/unit/verifier -q`.
17. close-out:
    * run `uv run pytest -q` in the tool's background mode, then `uv run ruff check .`;
    * tick state-vcs-locks 1.27, 1.28, 4.4, 4.5, 4.6 and verifier 1.6 (1.6 noting "conflict task: 5.12");
    * write `docs/plan/m17-progress.md`;
    * owe the SPEC edits below.

**Doc changes owed (not made here):**
* SPEC 12.1 event list gains `base.merged` and `base.conflict`.
* L4-VER-011 says that a merge commit is a subject whatever its `L4-Phase`.
* 12.3 notes the M1 exit-1 form, until 5.12 lands.

## Live protocol on `example-group/dummy-agentic` (runner `l4-runner`)

The operator acts as human and maintainer. Save every job log (ANSI stripped) under `docs/live/m17/`. Two new units:
**A `add-item-count`** (`Cart.item_count()`, the sum of quantities) and **B `add-cart-clear`** (`Cart.clear()` drops
every item and the applied discount code). Both are modelled on `add-is-empty`: proposal, one task, a spec with two
scenarios, and a `design.md` `## Open questions` item labelled `(product)`.

| Step | Action | Expected (checked against the job log, the ledger and the GitLab API) |
|---|---|---|
| 0 local | `uv run pytest -q` at the M1.7 head. Local `l4 run --dry-run` on a fresh clone of the dummy with `l4/*` and `refs/l4/locks/*` fetched | suite green; no `base moved` line for the `in_review` units (their next action is `none`, so the dry run does not list them) |
| 1 | one push to `main`: `l4 upgrade` to the M1.7 commit, `clarifier.enabled: false` (the lever), seeds A and B | one `l4` job, exit 11 (allowed): Q-001 raised for A and for B, `awaiting_human`, two draft MRs `l4:awaiting_human`. Both branches hold only harness commits |
| 2 | push `M2` to `main`: a docstring under `class LineItem:` in `src/pricing/cart.py` (a file A's tests import, far from the end of `Cart`) | `l4` job `nothing to do`, exit 0 |
| 3 (clean merge, answer path) | answer A's Q-001 on A's branch (`answered`) | One job, exit 0 (judge-dependent [I]: 10 or 11 also show the merge). Expected, in order: `answers submitted: Q-001`, red → green, `phase implemented → verifying`, then the merge lines in the job log: `commit <m10> chore(add-item-count): merge main@<M2:10> into the unit branch [skip ci]`, `pushed l4/openspec/add-item-count <old10>..<m10> …/-/compare/…`, `base merged: main@<M2:10> into l4/openspec/add-item-count as <m10> (1 commit)`. Then the full ladder 0–10 (no `reused`), and H with `pushed` |
| 3 checks | API and a clone | merge commit `parent_ids == [pre-merge head, M2]`; trailers `L4-Unit/L4-Run/L4-Iteration/L4-Phase: verifying`; its pipeline is `skipped`. `git merge-base --is-ancestor M2 H` holds; H's pipeline ran `test` on the merged tree. MR with `include_diverged_commits_count=true` → `diverged_commits_count: 0`. Ledger `base.merged{behind: 1, resolved: [], frozen_touched: []}`; verification.md step-0 note names the merge |
| 4 | push `M3a` to `main`: append `line_count()` at the end of `Cart` and a one-line helper method after `Cart.add`. Push `M3b`: `openspec/changes/add-cart-clear/questions.md` = B's branch file with Q-001 `answered` "yes (main copy, older)" | `nothing to do` ×2. Local (a local run refreshes no refs: first `git fetch origin main '+refs/heads/l4/*:refs/remotes/origin/l4/*'`) `l4 run --dry-run --unit openspec:add-cart-clear` (B is not actionable, so it must be named) shows `base moved: step 0 merges main@<M3b:12> (3 commits behind; changed on both sides: openspec/changes/add-cart-clear/questions.md)` (B's branch has no code yet) |
| 5 (source conflict) | answer B's Q-001 on B's branch, `answered` "yes: clear() also forgets the code (branch, newer)" | red → green. Step 0 then gives `base merge conflict with main@<M3b:10>: src/pricing/cart.py; merge it by hand and push (exit 1)`, **job red, exit 1**. Ledger: `base.conflict{files: [src/pricing/cart.py], resolved: [openspec/changes/add-cart-clear/questions.md]}` and `verify.step{step 0, status error, reason base-merge-conflict}`; no `verify.verdict`. Branch head = the final ledger commit, with no merge commit (`main` is not an ancestor). MR sticky "Base merge needed …"; phase `verifying` |
| 6 (harness-owned conflict) | push `M4` to `main`: `git revert M3a` only | One `l4` job (B `verifying`, plan `verify`). A local dry run (fetch as in step 4, then `--unit`) taken right after the push, before the job pushes the merge, shows `4 commits behind; changed on both sides: openspec/changes/add-cart-clear/questions.md, src/pricing/cart.py`. Main's net change to cart.py is now only M2's docstring, so cart.py merges clean [I: different hunks], and questions.md is an add/add **resolved by the harness**. Lines `commit <m10> chore(add-cart-clear): merge main@<M4:10> …`, `pushed …`, `base merged: … (4 commits; resolved openspec/changes/add-cart-clear/questions.md)`. The merged `questions.md` is **byte-identical to B's branch file** (the branch answer is newer). Then the full ladder and H (exit 0, or 10/11 judge-dependent). The MR sticky no longer contains "Base merge needed" |
| 7 (optional, verdict path) | if A or B ended NEEDS_HUMAN, push one more unrelated commit to `main`, then answer the verdict question on the unit branch | the merge happens before the round, and the round is judged afresh: `verify.judge` present, no step `reused` |
| cleanup | restore `clarifier.enabled` (delete the line), push | `nothing to do`. MRs A and B stay open for the maintainer |

Retry rules:
* **Step 5 merges clean** [I]: the conflict depends on where Codex puts `clear()`; M3a covers the end of `Cart` and the
  spot after `add`. If B's merge is clean, record a second clean merge. Then seed **C `add-cart-remove`** like B,
  run steps 4 and 5 for it with M3a' editing the exact lines of B's green diff, and run step 6 for C.
* **Step 1 raises no question for a unit**: reset that unit (close its MR, delete its branch) and push the seed again.

Spend: Codex 4 agent steps, or 6 with C. Claude: 2 judge calls (≈ $0.35 [I, M1.3 rates]). The clarifier is off.

## Risks

* `subject_sha` (line 10) is the one change that alters existing behaviour. If it is wrong, a stale NEEDS_HUMAN round
  is reused on merged code, or a merge that should not be a subject triggers a needless full round. Lines 9 and 16
  test both directions.
* `merge --abort` must keep the unstaged run ledger [I from git docs]. Line 4 proves it before anything relies on it.
* Exit 1 on every run until a human merges is noisy (a red job each time), but this is the documented M1 form. The
  conflict task (5.12) is the fix.
* A merged base can carry a newer vendored harness onto the unit branch. That is harmless: CI runs the harness from
  the base checkout [V template].
