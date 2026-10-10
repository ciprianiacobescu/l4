# M1.7 progress (base merge of verifier step 0)

Build of `docs/plan/m17-plan.md`, branch `m17`, from main `cce44f0`. Commits carry no trailers. "Seen fail" means the
test was run before the code and failed (a missing module counts for the new files); lines 14 and 16 are the plan's
"no code expected / whatever the earlier lines missed" lines, so their tests passed at first run on the code of the
earlier lines (line 16 was shown to fail with the line-9 seam disabled).

| line | status | commit | note |
|---|---|---|---|
| 1 `merge_base_into` (1.27) | done | 73ccbcc | `src/l4/vcs/merge.py`; merge commit has parents [old head, base], pushed history untouched |
| 2 never rewrites history (1.28) | done | 73ccbcc | asserts no `rebase`, `--amend`, `+` refspec, `--force`, `reset --hard` in `Git.history` |
| 3 no-op | done | 73ccbcc | an ancestor base: no `merge` argv, no commit |
| 4 dirty tree, abort keeps ledger | done | 73ccbcc | `keep_dirty` for the run's ledger; `merge --abort` keeps its unstaged lines (tested) |
| 5 conflict classification | done | 73ccbcc | `ls-files -u` + `show :N:`; ledger path conflict and `L4-Phase: archived` refused (`MergeRefused`, exit 1) |
| 6 `questions.md` merge (4.6) | done | 6424dad | `src/l4/specs/questions_merge.py`; table in `src/l4/specs/harness_merge.py` |
| 7 `tasks.md` markers (4.4, 4.5) | done | 6424dad | `src/l4/specs/tasks_merge.py`; `Escalate` is defined in `l4.vcs.merge` |
| 8 `bring_in_base` (1.6) | done | 54e5175 | `src/l4/verifier/basemerge.py`; `base.merged`, `base.conflict`, `verify.step` error, `BaseMergeConflict` |
| 9 ladder seam | done | 61c47bb | first statement of `verify_hook`; `VerifyContext.base_note` feeds the step-0 note |
| 10 `subject_sha` | done | 2d8141b | a commit with 2+ parents is never skipped for its phase; first-parent diff via `git diff <sha>^1 <sha>` |
| 11 guard text | done | 54e5175 | "bug: the base merge of step 0 did not run" |
| 12 MR note | done | 8e674fb | `_verify` catches `BaseMergeConflict`, sticky "Base merge needed", syncs, re-raises; cleared by `ctx.shared["notes"] = ()` |
| 13 trace lines | done | 8b33511, b3a0937 | INFO `base merged: ...`, WARNING `base merge conflict ...` |
| 14 integrity | done | a458346 | no code change was needed |
| 15 dry run | done | b6bc46b | `base_moved()` in `l4.vcs.merge`; line printed under the unit header |
| 16 end to end | done | 4864eca | three tests in `test_verdict_reentry.py` (fake GitLab for H and the sticky note) |
| 17 close-out | done | cd16b48 | full suite 2801 passed, 50 skipped (EXIT 0, 23m25s); `ruff check .` clean; `check_spec.py docs/SPEC.md` clean; tasks ticked; SPEC edits owed, not made |

## Deviations from the plan

* `harness_resolvers` and `Escalate`: the resolver table lives in `src/l4/specs/harness_merge.py` (new) and `Escalate`
  in `l4.vcs.merge`, so the git layer does not import spec code. Plan 8 named only `questions_merge.py`/`tasks_merge.py`.
* The conflict check runs on the merge that git leaves in the index: resolvers run first in memory; the merge is
  aborted untouched when any file stays unresolved, so `resolved` on `base.conflict` is "would have been settled".
* Dry-run wording uses "1 commit behind" for a single commit (the plan's text is the plural form).
* `Git.commit(..., allow_empty=True)` is used for the merge commit, so a merge with an unchanged tree still commits.
* The dirty check in `merge_base_into` uses the unit's harness ignore file (`core.excludesFile`), written by
  `bring_in_base` when it is missing (a run that resumes at `verifying` has built no Workbench yet).
* `tests/unit/verifier/conftest.py` re-exports the archive fixtures (`forge_env`, `use_fake_gitlab`, `gitlab`).
* Review fix: `Orchestrator._verify` returns exit 1 for `BaseMergeConflict` instead of re-raising it (plan decision 9
  said re-raise). Raised, it ended the whole `l4 run`, so every unit sorted after a conflicting one never ran, on every
  run until a human merged (SPEC 2: several units give the most severe code). Test:
  `test_verdict_reentry.py::test_a_base_conflict_ends_its_unit_with_exit_1_and_the_units_after_it_still_run`.
* The tick also edited the task text (`code:` paths and a `conflict task: 5.12` note) of state-vcs-locks 1.27, 4.4, 4.5, 4.6 and verifier 1.6, not only the checkbox.
* Not built (as planned): conflict task (state-vcs-locks 4.8, 4.9, verifier 5.12), archive revert, `lessons.md` union
  resolver (M1.5 is not on main), 3-strike escalation of L4-VER-010.

## SPEC edits owed (not made)

* 12.1 event list gains `base.merged` and `base.conflict`.
* L4-VER-011: a merge commit is a subject whatever its `L4-Phase`.
* 12.3: the M1 exit-1 form of a source conflict, until verifier 5.12 lands.

## Open limits

* Live protocol on `example-group/dummy-agentic` is not run (needs a runner, tokens and Codex spend).
* A unit with a source conflict exits 1 on every run until a human merges the base.
