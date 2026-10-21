# M1.11 progress

Plan commit `1e37fd8`. Branch `m111`, not pushed. All 30 build lines are committed, no trailers, author and committer
CiprianSpot (`maintainer@example.invalid`). The live protocol of the plan was not part of this run.

## Commits

| Line | Commit |
|---|---|
| 1 | 12d900e |
| 2 | f3d3ea4 |
| 3 and 4 | e8253d6 (one commit) |
| 5 | 33e715b |
| 6 | 143fd15 |
| 7 | f9afe04 |
| 8 | c10f4dd (also holds the sweep half of line 10) |
| 9 | 107e880 |
| 10 | 503989c (the planner reason; the sweep's pointer is in c10f4dd) |
| 11 | fef7315 |
| 12 | f94df86 |
| 13 | 0cd0eec |
| 14 | b03f29f |
| 15 | 2cd9854 |
| 16 | 59e06ff |
| 17 | 178a178 |
| 18 | 03d6a6d |
| 19 | 3772217, and 06b3a7e (the loop test's `run_single` stub takes `kind`) |
| 20 | 334c5e1 |
| 21 | 7d12c6b |
| 22 | 4884f71 |
| 23 and 24 | d0775fd (one commit) |
| 25 | 290af4f |
| 26 | 47af051 |
| 27 | 8c7bd05 |
| 28 | f481727, f01aabd (wrapped lines) and 3c90198 (the runner probe mirrors `UV_LINK_MODE`) |
| 29 | 06ba3e7 |
| 30 (SPEC) | ff98753 |
| 30 (this file) | the commit after 3c90198 |

Also 0739310: `ruff format` on three files that were clean before and that the milestone touched.

## Full suite (collected = passed + skipped + xfailed)

| Chunk | Collected | Passed | Skipped | Xfailed |
|---|---|---|---|---|
| agents, availability, llm | 489 | 484 | 5 | 0 |
| verifier, implementer, gates | 1234 | 1230 | 3 | 1 |
| orchestrator, archive, state, vcs, specs | 595 | 593 | 2 | 0 |
| every other tests/unit dir and test_*.py | 1897 | 1892 | 5 | 0 |
| contract, scenarios, integration, live | 122 | 59 | 63 | 0 |

The five chunks add up to 4337 = `pytest tests --collect-only`. The skips are the live tests and two tool-dependent ones. The xfail is the strict `test_ladder_evidence_gaming` one; the
plan commit has that one `xfail` marker only (M1.10's table counted a second xfail in the orchestrator chunk, which this
base no longer has).

Three chunks had one failure in their first run. None was left:

* agents: `test_interrupt_sends_sigint_then_the_run_ends`, the signal-timing test M1.10 also met (load average 40 to 150
  on this machine). It passed in three runs of its file alone.
* verifier/implementer: `test_single_phase_budget_unchanged`, a regression of mine: its `run_single` stub did not take the
  new `kind` keyword. The stub takes it now (06b3a7e); `test_loop.py` passes (17).
* other dirs: `tests/unit/runner/test_probe_m15_parity.py::test_the_gate_environment_is_build_gate_env`. The bash probe
  `scripts/runner/ci-probe-m15.sh` mirrors `build_gate_env`, and a regression of mine (`UV_LINK_MODE=copy`) had not been
  mirrored there. It is now (3c90198); `tests/unit/runner` passes (13).

The three chunks were not rerun whole after those fixes: the fixed files and directories were rerun alone.
`ruff check .` passes. `python3 scripts/check_spec.py docs/SPEC.md` reports no problem. `python -m l4.templatelock --write`
leaves no diff (`implementer/single_tests` v1, `testwriter/audit` and `testwriter/e2e` v3, `judge` v6).
`ruff format --check .`: 68 files would be reformatted (69 at the plan commit), none of them new, none that was clean before.

## Test-first

Each new test was meant to be seen failing before its code. What was seen live, in the session: lines 1, 2 (the module
did not exist), 3, 4 (against the code stashed), 5, 6 and 29. For the others the test and the code were first run
together. So that this is not a claim without a check, `redcheck.py` (a throwaway script outside the repository) ran the
new tests of each line's commit against the code of the commit before it. Every line has at least one test that fails
or errors there, except the three end-to-end lines the plan calls "whatever the earlier lines missed":

| Line | New tests | Red at the parent | Green at the parent, and why |
|---|---|---|---|
| 1 | 2 | 2 | |
| 2 | 9 | 9 | |
| 3 and 4 | 5 | 5 | |
| 5 | 3 | 2 | `test_run_still_fails_closed_without_bwrap`: it pins behaviour that must not change |
| 6 | 4 | 4 | |
| 7 | 5 | 5 | |
| 8 | 7 | 7 | |
| 9 | 1 | 0 | the end-to-end test over lines 5 to 8 |
| 10 | 1 | 1 | |
| 11 | 3 | 3 | |
| 12 | 4 | 4 | |
| 13 | 1 | 1 | |
| 14 | 1 | 0 | the end-to-end test over lines 11 to 13 |
| 15 | 4 | 4 | |
| 16 | 3 | 3 | |
| 17 | 3 | 3 | |
| 18 | 1 | 1 | |
| 19 | 9 | 9 | |
| 20 | 1 | 0 | the end-to-end test over lines 17 to 19 (run by hand: the script counted a name inside a string) |
| 21 | 6 | 6 | |
| 22 | 6 | 5 | `test_the_matrix_shows_human_and_chore_proofs`: the matrix already prints whatever proof string it gets |
| 23 and 24 | 8 | 6 | `test_a_hex_digest_literal_is_not_secret_shaped` and `test_the_e2e_kind_does_not_take_the_audit_rules`: they pin what stays allowed |
| 25 | 2 | 1 | `test_needs_answers_stays_while_another_question_is_open`: the label stays today too |
| 26 | 1 | 1 | |
| 27 | 4 | 4 | |
| 28 | 6 | 5 | `test_no_uv_lock_or_a_non_uv_setup_runs_no_seed`: it pins what does not happen |
| 29 | 5 | 4 | `test_the_jwt_is_never_printed`: it pins what does not happen |

## Deviations

* **SPEC in one commit** (ff98753) at the end, not per line.
* **Commits that join lines:** 3 and 4; 23 and 24 (the template lock holds both, so they cannot be apart); line 8's commit
  carries the sweep half of line 10 (`resume.hint`), line 10's own commit has the planner reason. Extra commits: the loop
  stub (06b3a7e), the probe parity (3c90198), the wrapped lines (f01aabd) and the three formatted files (0739310).
* **Line 25's tests** are in `tests/unit/verifier/test_ladder_hold_fix.py`, not `test_reentry.py`: the orchestrator
  conftest switches the verifier off for every test of its directory, and a fix unit needs it. Line 20's end-to-end test is
  in the same file for the same reason (the plan named `test_review_reentry.py`).
* **`AbsentSandbox`** (in `sandbox/none.py`) is the refusing sandbox of `l4 resume`, not the plan's `NoSandbox(reason)`:
  `NoSandbox` already exists and means `sandbox.mode: none`.
* **`red_proofs` is unchanged.** The human and chore proofs are read by `extra_proofs`, which also checks that the file
  still has the content that was run; `trace_criteria` takes them as `extra=` and the reasons of rejected tests as
  `reasons=`.
* **A rejection is not cached.** The plan keyed it by (file sha, H); a round at the same head is reused as a whole
  (`reusable`), so there is no fresh round to save a run in, and a rejected test is decided again in every fresh round.
* **The W6 base run** sets `PYTEST_ADDOPTS=--continue-on-collection-errors`. Without it the unit's own tests of a module
  that does not exist at the base abort the whole run at the first collection error and no candidate is decided (seen live in
  the line 22 test). A candidate whose own module does not import is still no proof.
* **`resume.hint{head}`** is a new event (line 8/10): the sweep's "a person pushed after the halt" line is said once per
  head, and that needs a record. It is in SPEC 12.1.
* **`UnitState`** gains `resumed_signals`, `refused_signals`, `hinted_heads` and `halt_reason` (the reason of the edge into
  `halted` or `escalated`, which the sweep needs to rewrite the sticky note around a refusal).
* **A coverage hold's finding** is recognised by its text (`verdicts.COVERAGE_FIX`, a sentence the harness writes, which
  the human's reason follows) and not by `result.holds`: the holds are empty once the reject has settled them.
* **The W10 code** is in `implementer/uvseed.py` (the fill and the copy) and `sandbox/seed.py`; `sandbox/caches.py` is
  unchanged. `Workbench.run_gate_spec` and `gate_spec` take `caches=` for the fill only.
* **`test_guards.py`** was in the pre-existing ruff-format set and was formatted whole in the line 19 commit.
* **Left as they are:** `openspec/changes/bootstrap-core/design.md` and the `forge-and-ci` change still say
  `SEVERITY_ORDER = (1, 2, 3, 13, 14, ...)` and `exit_codes: [10, 11, 12]`. They are the history of those changes; the plan
  expected no openspec ticks, and the SPEC is what changed.
* **Not built, as planned:** GitHub label events (the label is never honoured there), `--extend-*` for `l4 resume`, a
  config knob to keep 13 red.

## Adversarial review (after cfe0749)

Five `m1.11(fix)` commits, each test first (the new tests were run red at cfe0749, then green):

* 054ed27 (W5): `appended_only` accepted any appended def, class, import or assignment that bound a new name. An
  autouse fixture, a fixture override (def, alias or import of a name the file's tests request), `pytestmark`,
  `setup_module`/`setup_function`, `pytest_generate_tests`, or a call made at import (assignment value, decorator,
  default, class body, walrus) kept the frozen proof tests passing whatever the code does. An added statement must now
  only define (tests, test classes, imports, constants; pytest marks are the only calls), and the guard note says so.
* d1d7655 (W6): the extra proof's base run takes a failure **by assertion** only, like the zero-value run. Before, a test
  that only imported the unit's new module in its body failed at the base with an error and became a proof. This
  narrows decision 8 ("fail or error there").
* 90d4b4c (W1): the excerpt redacts each body before its lines are cut (a private key lost its END marker to the
  six-`E`-line bound and went out unredacted).
* 7e28225 (W1/W4): the halted and escalated sticky-note section is redacted (the halt reason quotes a test's first error
  line; the ledger and console redacted it, the note did not).
* f5bc391: SPEC L4-VER-006, L4-VER-009 step 4 and L4-CI-004 (a forge without label events refuses nothing; the text
  promised a refusal the code never made).

Suite at cfe0749: 4258 passed, 78 skipped, 1 xfailed (4337). At f5bc391, in two parts: 4283 passed, 78 skipped,
1 xfailed (4362 = 4337 + 25 new). `ruff check .` clean, `ruff format --check .` 68 (none new), `check_spec.py` clean,
`templatelock --write` no diff.

Left open (not defects of this milestone's lines, or by design): a new test file (in green, a fix chore or a test chore)
can still patch production code at import or in a test body; `own_user_id` failing transiently records a permanent
refusal of that label event; a `secret_in_push` block outside `implementing`/`fixing` exits 13 (now a CI warning) with no
label or note on the MR; the seed fill's TMPDIR is the unit's `gate-tmp`.
