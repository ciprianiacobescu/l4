# M1.10 progress

Plan commit `1116504`. Branch `m110`, not pushed. All 26 build lines are committed, no trailers.

## Commits

| Line | Commit |
|---|---|
| 1 | ecc2892 |
| 2 | 9d88355 |
| 3 | 14b03f1 |
| 4 | 9d206b1 |
| 5 | 7c23aec |
| 6 | c6d5684 |
| 7 | 43e2519 |
| 8 | 81bbac4 |
| 9 | 2a2245f |
| 10 | 3fe0934 |
| 11 | 930aaf3 |
| 12 | 41bd82d |
| 13 | 31d5752 |
| 14 | d4035f1 |
| 15 | 8352919 |
| 16 | b038f81 |
| 17 | 08f4404 |
| 18 | 7b12b64 |
| 19 | e748f10 |
| 20 | 8b0e152 |
| 21 | 1e9cfbe |
| 22 | 4e16da5 |
| 23 and 24 | d8047bc (one commit) |
| 25 | 88754c9 |
| 26 (SPEC, openspec pointer) | be560a0 |

## Full suite (collected = passed + skipped + xfailed)

| Chunk | Collected | Passed | Skipped | Xfailed |
|---|---|---|---|---|
| agents, availability, llm | 481 | 476 | 5 | 0 |
| verifier, implementer, gates | 1152 | 1148 | 3 | 1 |
| orchestrator, archive, state, vcs, specs | 585 | 582 | 2 | 1 |
| every other tests/unit dir and test_*.py | 1863 | 1858 | 5 | 0 |
| contract, scenarios, integration, live | 122 | 59 | 63 | 0 |

The two xfails are the two known strict ones. `ruff check .` passes, `check_spec.py` reports no problem, and
`python -m l4.templatelock --write` leaves no diff (judge v5, implementer/green v2).

## Deviations

* `ruff format --check .` fails: 63 files at the plan commit, 62 now, none introduced by M1.10. Left alone to keep
  the diff to the plan's seams. Files M1.10 touched that were clean were formatted.
* First chunk 1 run had one failure, `tests/unit/agents` `test_interrupt_sends_sigint_then_the_run_ends`, a signal
  timing test that ran while other pytest runs loaded the machine. It passed alone three times and in the rerun of the chunk.
* Test-first: seen failing before the code for lines 1-7, 10, 11, 15, 17-22, 25. For lines 8, 12, 13, 16 tests and code
  landed in the same edit; checked afterwards by running each commit's tests against the parent's code (they fail
  there). Lines 9 and 14 are end-to-end tests over earlier lines and passed at first run.
* Lines 23 and 24 share one commit.
* Line 1: the job-5604 fixture gained a `step_script` section start line, which the real trace has.
* Line 2: the existing sweeper test that forbids the log now patches `GitLabForge.job_log` (the sweep calls it).
* Line 5: a skipped step names no failing step in the detail; a derived one does, first. The detail's summary shrinks
  its log tail so both fit 600 characters. Known edge: a 300-character step with a job URL of about 235 characters
  overflows (69 characters fits).
* Line 9: the CI command in the fixture is `<sys.executable> scripts/check_len.py src`, not `python ...`.
* Line 12: an id is "failing at red" only when the report lists it as failed or error; the function returns the ids that do not.
* Line 14 turns the real verifier on inside the test.
* Line 20: `GET runners/:id` is outside `/projects/`, so one assertion of `test_gitlab_setup_flow` now allows `/runners/`.
* Line 21: `RefreshFailed` (in `gitlab_admin`) carries the reason of a failed refresh.
* Line 22: `src/l4/commands.py` needed no change. `L4_TOKEN_COMMAND` goes through click's `envvar` (the process
  environment); the test covers the `--help` text and the function, not the env var itself.
* Line 23: `project_dirs` also drops a directory nested in another of the list (`src/pkg` under `src`), a rule decision 15 did not state.
* Line 26: SPEC also gained a sentence under L4-VER-001 for the judge diff and Owner changes.

## Review fixes (adversarial review of C1, C2, C3, C8)

| Commit | What |
|---|---|
| 13bda39 | `fails_at_red` fails closed: an id the run at red does not report (a collection error) or a run without a report is not failing there. Before, a vacuous corrected test that imported a module only green added passed decision 7. |
| cfa88b0 | `unrunnable` refuses a shell given a command string (`sh -c`, `bash -lc`, `env sh -c`, `--command`): the quoted argument hid every operator and denied word, and `gates.network` defaults to `allow`. |
| f5a9071 | An `accepted` answer (the clarifier's text) unfreezes only a test the question itself names (title, Context, Options); a human's own `answered` text may still name any test. Two test fixtures now name the path in the question, as the live Q-002 does. |
| f5e0203 | Regression tests: a harness-edited local CI include outside `.gitlab/` is refused; a file a person and the harness both changed is no owner change. |

SPEC L4-IMP-002 and L4-ARC-002 state the two narrowed rules.

Full suite after the review fixes, one background run of `uv run pytest -q`: 4129 passed, 78 skipped, 2 xfailed
(the 4123 passed above plus 6 new tests). `ruff check .` passes, the template lock leaves no diff, `check_spec.py`
reports no problem. `ruff format --check .`, counted by the reviewer on the same ruff: 70 files at `1116504`, 69 now,
none new.
