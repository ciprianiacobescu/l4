# M1.9 progress (re-verification after the hand-off, and the PR-1 findings)

Build of `docs/plan/m19-plan.md`, branch `m19`, from main `e7de0c6`. `main` has not moved since, so the "merge `main`
before stage C if M1.8 has landed" step did not apply (M1.8 is a parallel branch, `../l4-wt/m18`, not on main). Commits
carry no trailers. "Seen fail" means the test was run before the code and failed (a missing module counts for the new
files). Where a test passed at its first run it says so in the note.

| line | status | commit | note |
|---|---|---|---|
| 1 `vcs/authorship` (L4-ARC-008 d) | done | d932ff1 | `commit_records`, `is_harness`, `HANDOFF_SUBJECT`, `handoff_commit`; `provenance` imports them. Both tests passed at first run (module and test were written together); the suites that use `provenance` are unchanged and green |
| 2 `after_handoff` (2.41) | done | efb7238 | `state/review.py`; seen fail (import error). `--first-parent H..head`, so a human merge of the base is one foreign commit |
| 3 H unless HEAD is H | done | 3c1e726 | `handoff_hook`; `pr.ready{head}`. `test_handoff_reentry.py` seen fail with the old condition swapped back in; its test file was committed with line 7 (`45491a4`/`9805be3`), because it needs the re-entry |
| 4 lifecycle rows | done | 73d0d23 | three edges, `archived` asserted as no source; seen fail (missing trigger) |
| 5 fold `ci_heads`, `ci_failure` | done | 46a4c26 | seen fail |
| 6 snapshot review and plan rows | done | f9050c8 | `UnitSnapshot.review`, `UnitFacts` fields, `_in_review` rows; seen fail |
| 7 `_drive` review branch | done | 9805be3 | `review_trigger` in `state/review.py`; SCN-ARC-16 test seen fail (`nothing to do`) |
| 8 spec route and SCN-ARC-14 | done | 45491a4, f1aee26, 31b9101 | the spec-edit test passed at first run (its code is line 7); the CI test was written after lines 12, 13 and 16 and passed once its assertions matched the real status words. `f1aee26` was committed with a failing assertion; `31b9101` is the same test fixed |
| 9 draft before any push, sticky note | done | 9805be3, 21a1eeb | `_Mirror._draft`, `_Mr.draft`; the tests were written before the code but not run red |
| 10 loop safety | done | 9805be3 | no code; passed at first run, as planned. The "cannot fix" bullet is its own test (`test_a_fix_round_that_cannot_fix_ends_in_escalated_after_max_fix_rounds`) |
| 11 trace lines | done | 78e65e8 | with line 31; seen fail |
| 12 step 0 CI blockers | done | 5f035f8 | `ci_detail`/`ci_blockers` in `preconditions.py`; seen fail |
| 13 forge port, GitLab | done | 27ef3a0 | `JobResult`, `list_pipeline_jobs`, `job_log_tail`, `clip_log`; FakeGitLab routes; seen fail |
| 14 GitHub check runs, LocalForge | done | 5a77f08 | own `{"check_runs"}` reader, log redirect without the token; seen fail |
| 15 `evaluate_ci` | done | b676fe2 | `ci/repo_ci.py`; seen fail (import error) |
| 16 sweep duty | done | 54adaa2 | `Sweeper._ci_duty`; seen fail (`ci=` keyword) |
| 17 redaction of tails | done | 54adaa2 | with line 16; note: the ledger writer redacts too, the explicit redaction is belt and braces |
| 18 CLI surface | done | 54adaa2 | `ci: H <sha10> ...` lines on stderr (stdout stays the plan, `--json` stays JSON); `l4 archive` passes `ci=False` |
| 19 protected paths by human | done | 9b278d3 | `protected_changes_by_human`, `Outcome.human`, `IntegrityReport.human_protected`, report section, step-1 note; `Repo.commit` is the bot, `commit_as_human` added |
| 20 `check_tests` per commit | done | fd42856 | `Outcome.human_tests`, `IntegrityReport.human_tests`, report section; seen fail |
| 21 scope exempts human files | done | 9a81ed3 | `ChangedFile.human`, `scope_evidence` attribution; seen fail. `test_root_files.py` commits as the bot now |
| 22 conventions and header | done | 170244f | `verifier/conventions.py`; seen fail |
| 23 judge rubric and block | done | 802b1b7 | `PROMPT_VERSION = 4`, lock regenerated |
| 24 audit writer | done | 87d6ba6 | `testwriter@2`, AST rejection, one retry, header and conventions blocks; the lock pins `testwriter/audit` and `testwriter/e2e` |
| 25 `register_l4_marker` | done | 3135c64 | `init/pytest_marker.py`; seen fail; the real `pytest --strict-markers` runs in four layouts |
| 26 init and upgrade wiring | done | 819b906 | one field each; `upgrade` docstring amended; seen fail |
| 27 `ForgeUrls`, schema key | done | d7c377f | `forge/urls.py`, `observability.redact_forge_urls`; SPEC 3.2 and L4-OBS-002 edited in the same commit (the schema test reads 3.2) |
| 28 `LedgerWriter` `file_filter` | done | 076c80e | seen fail |
| 29 P5 wiring | done | 0cb9844, 2cbc6e1 | writer in `run_unit_in_worktree`, sweeper `_UnitRun`, `write_round_evidence`, `_ensure_mr`, `_own_mr`, `outcome.json` (orchestrator and planner) and `l4 status`; the `test_hooks.py` assertion is the placeholder form |
| 30 iteration | done | 3509cb7 | `run.started.iteration` = folded count + 1; the first run printed `iteration 0` before |
| 31 zeroed-run gate lines | done | 78e65e8 | `test-zero` and `test-presatisfied` failing say `(expected: zero values must fail)` |
| 32 close-out | done | 5599362, 6cda6bf, adb3ce3, 4dfa00c | SPEC 12.0 note, 12.1 events, 3.2, L4-OBS-002, L4-ARC-002, L4-SEC-004; ticks forge-and-ci 2.2, 2.41, 2.44, sandbox-security 2.10 (pointers rewritten); this file |

## Verification

Full suite in five chunks (the machine was under load 17-20, so the chunks ran two or three at a time):

| chunk | directories | result |
|---|---|---|
| 1 | `tests/unit/agents`, `availability`, `llm` | 471 passed, 5 skipped |
| 2 | `tests/unit/verifier`, `implementer`, `gates` | 1080 passed, 3 skipped, 1 xfailed (the strict `test_residual_a_forgery_that_never_names_the_plugin_still_passes`, a documented hole of m16) |
| 3 | `tests/unit/orchestrator`, `archive`, `state`, `vcs`, `specs` | 564 passed, 2 skipped |
| 4 | every other `tests/unit` directory and `tests/unit/test_*.py` | 1607 passed, 5 skipped |
| 5 | `tests/contract`, `scenarios`, `integration`, `live` | 59 passed, 63 skipped (live tests need `L4_LIVE=1`) |

Collected 3860 = 3781 passed + 78 skipped + 1 xfailed (`pytest --collect-only` agrees). The skips are the live and
optional-tool tests (Serena, uv with a network, Playwright, `L4_LIVE`). The chunks ran at `6cda6bf`; two commits came after them (`adb3ce3`, `4dfa00c`: whitespace in two test files and one SPEC sentence; the tests of the first were rerun).


* `uv run ruff check .`: clean.
* `uv run ruff format --check .`: 73 files would be reformatted (74 at the base `e7de0c6` by the same count). The tree is
  not format-clean at the base, so nothing was reformatted wholesale. Files this branch touched that were already
  unformatted at the base were left alone where M1.8 may touch them or the reformat would be large:
  `src/l4/forge/github.py`, `tests/unit/ci/test_sweeper.py`, `tests/unit/conftest.py`,
  `tests/unit/security/test_protected.py`, `tests/unit/state/test_ledger.py`. Three that were unformatted at the base
  and are not shared with M1.8 came out formatted as a side effect of formatting what was edited:
  `src/l4/verifier/integrity.py`, `src/l4/verifier/provenance.py`, `tests/unit/ci/test_sweep_cli.py`. Two test files that
  were clean at the base and were not after an edit were formatted (`adb3ce3`). The M1.8-shared files changed by
  small seams only: `orchestrator.py` +29/-4, `archive.py` +33/-10, `ladder.py` +2/-1, `init/init.py` +28/-1,
  `config/schema.py` +1.
* `uv run python -m l4.templatelock --write` leaves no diff.
* `python3 scripts/check_spec.py docs/SPEC.md`: clean (exit 0, with PyYAML: `config keys not in §3.2: []`).

## Deviations from the plan

* `review_note` (the sticky section) lives in `state/review.py`, not in `orchestrator._notes`; `_review_noted` clears it at
  the next hand-off. The edge context also carries `lost`.
* `_Mr.pushed` is initialised from the existence of the unit's branch on the remote, so the mirror can draft and label
  before this run's first push. That is a behaviour change for every resumed run (a unit parked in `waiting_capacity`
  with a branch now gets its labels synced before it pushes), not only for the re-entry.
* `SweepAction` gained `ci_green` (the plan names three kinds); `sweep(..., ci=)` is a new keyword and `l4 archive` passes
  `ci=False`. "No pipeline yet" is reported as `green`. A CI record is published twice per sweep (the event, then
  `close()`), the same pattern as the merge duty.
* `Redactor.forge_urls` and `scrub_for_commit`, `forge/urls.app_forge_urls` and `origin_url`, and a reset in
  `load_app_config` carry P5 to every sink that already held the redactor; the plan did not name this plumbing.
* Extra public surface: `AfterHandoff.head/reentry/at_handoff`, `ForeignCommit`, `ReviewTrigger`, `UnitFacts.handoff_sha`,
  `ci_detail`, `ci_blockers`, `clip_log`, `UNFINISHED`, `TEMPLATE_VERSION`, `Outcome.human_tests`,
  `IntegrityReport.human_tests`, `ChangedFile.human`, `MarkerEdit.created`.
* A lost H (history rewritten) re-verifies like a foreign commit, with a plan row of its own
  (`in_review: the hand-off commit is not on the branch`).
* `check_tests` and the scope check attribute per file by `git log` history simplification, one `git show` per commit
  and path; a path nobody can be named for stays a blocker.
* GitHub `job_log_tail` makes its own two `httpx` GETs (no retry loop) so the second one can go without the token; a
  downgrade to http, a non-redirect and a 404 give no tail.
* The step-0 round is told apart from later ones by "no `verify.verdict` after the `repository_ci_failed` edge", read
  from the run's own ledger, as planned; the detail opens with the stage, H, the URL and the end of the log (the first 600
  characters are what a fix unit's proposal keeps), then the whole tail.
* The trace shows the newest of several foreign commits.
* New test fixtures: `tests/unit/ci/review_world.py`, `TddRepo.config(observability=)`, `commit_as_human`.
* Seen-fail gaps, listed in the table: lines 1, 8, 9 and 10.
* Commit hygiene: `f1aee26` and `31b9101` share a message (the first had a failing assertion); `2cbc6e1` is a lint fix
  in `m1.9:` form, not `m1.9(fix):`.

## Not built (as planned)

* P1(b), doctor comparing `gates.setup` with the project job's install line (M1.8's `doctor --adoption`).
* forge-and-ci 2.9 except its check-run part (statuses, collaborator permission, review approvals), the approval half of
  2.41, and everything of `on_approval` (the archive revert, a voided approval).
* The live protocol on `example-group/dummy-agentic` (needs the runner, tokens and Codex spend).
* An ignore list for red jobs that no fix can change (M2).

## Open limits

* A fix round for a job that code cannot fix (infrastructure, a flaky job) burns one round per H until `escalated`.
* Authorship is trusted: with `sandbox.mode: none` an agent could commit as a "human" (no agent-commit guard yet).
* A closed MR plus a human commit re-verifies and opens a new MR (`abandoned` is not built).
* Each recorded CI result is a sweep run with a `run.started`, so the fold's iteration goes up by one, as for `PR_MERGED`.
