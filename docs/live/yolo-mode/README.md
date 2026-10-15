# Delivery plans, live on GitLab and GitHub (yolo-mode, task group 9)

**Date:** 2026-10-15.
**Harness:** the two ten-unit scenarios ran on branch `yolo` at `47294b25` (the review-4 fixes, plus the two readiness
fixes and the repository-keyed worktrees that this run found to be needed; see "Defects"). The stop cases ran on the
later integration commits, the last ones on `8388c1a4` (both forges) and `5863fb68` (GitLab, the batch profile).
**Implementer:** `opencode-go/deepseek-v4.1-flash` (OpenCode Go, `OPENCODE_API_KEY`). **Judge:** Claude Code
(`CLAUDE_CODE_OAUTH_TOKEN`); the first GitLab review fell back to `f-longcat`.

| | GitLab | GitHub |
|---|---|---|
| Repository | a self-hosted GitLab, a disposable private project | `ciprianiacobescu/l4-dummy-public`, public, GitHub-hosted runners (free) |
| Harness delivery | vendored (`.l4/vendor/`) | setup action, copied (`--action-copy`), private harness fetched with a temporary read-only deploy key |
| Integration branch | `staging` (default branch `main`) | `l4/main` (also the default branch, so the cron runs its workflow) |
| Artifacts | job artifacts | none (`ci.upload_artifacts: false`: a public repository) |

## The plan

Ten specs (six OpenSpec changes, four Kiro specs) in one plan `valuation`, one batch per wave, unit dependencies,
`merge: auto`, limits 2 attempts per unit, 60 runs, 25 USD. The specs and the plan landed in **one commit**, so the plan
held the units from the first run (`held by plan valuation (new)` for all ten in the first pipeline).

| Wave | Units | Needs |
|---|---|---|
| 1 | A `openspec:add-money-format`, B `kiro:stock-ledger`, C `openspec:add-vat` | — |
| 2 | D `openspec:add-stock-valuation`, E `kiro:invoice-line` | A, B and C each |
| 3 | F `openspec:add-valuation-summary`, G `kiro:invoice-lines` | F needs D; G needs E |
| 4 | H `openspec:add-summary-currency` | F only |
| 5 | I `openspec:add-shelf-label`, J `kiro:units-surplus` | — |

`scripts/validate_plan.py` printed exactly these waves. The plan runs one unit at a time, so I and J (wave 1 by their
dependencies) ran last, in the order of the file.

## Proven

| What | GitLab | GitHub |
|---|---|---|
| Units held from the first run (specs and plan in one commit) | pipeline of 3a9077b: 10 × `held by plan valuation (new)` | first run 38686860263 |
| The readiness review in CI refuses a spec with a gap; the author fixes it; CI reviews again | 3 reviews: NEEDS_REVISION ×2, then all READY | 1 review: all READY (the revised specs) |
| `l4 yolo activate` from a laptop | 03:41:03 | 05:32:10 |
| A named run of a unit whose prerequisites are not integrated is refused, and writes nothing | `l4 run --unit openspec:add-stock-valuation`: exit 13, `waits for openspec:add-money-format (not integrated)`; no ledger event from that run | same command, same exit and reason, no ledger event |
| Every unit dispatched and first run only after all its prerequisites were integrated (C1, C2), one unit at a time (C3), all integrated (C4) | `analyze_enforcement.py`: C1–C4 ok for 10/10 | C1–C4 ok for 10/10 |
| Each MR/PR merged by the guarded fast-forward push, archive MR/PR merged | MRs !2–!17 | PRs #1–#16 |
| `plan.completed`, post-merge check pass for every unit | 06:01:06, at `29bc685` | 06:09:43, at `f5ed57a` |
| The default branch is never promoted | `main` still `01ce1d4` | `main` still `1e943ef` |
| The integrated code works | 57 tests pass on `staging`; the spec examples hold | 60 tests pass on `l4/main`; the spec examples hold |
| A promoted lesson is injected into every implementer prompt (experience graph, L4-KG) | — (no lesson) | `lessons.injected{L-8d816d0e}` in all 10 units; `l4 kg report`: 32 prompts, nothing followed |

The enforcement check (`analyze_enforcement.py`) reads git only, never `l4` code: the plan file on the target, the plan
ledger `refs/l4/plans/valuation`, and every unit ledger in every ref (the first `run.started` of each unit).

Per unit, both forges: one attempt each, no retries; the post-merge check passed for all ten.

| Unit | GitLab MR · merge commit · usage | GitHub PR · merge commit · usage |
|---|---|---|
| A `add-money-format` | !2 · `2cd86b6` · $0.05, 6 runs (5 of them the defect below) | #1 · `f8df4b5` · $0.04, 3 runs (2 refused a PR before `l4 setup github` gave Actions the right) |
| B `stock-ledger` | !4 · `1038b35` · $0.06 | #3 · `8b86507` · $0.06 |
| C `add-vat` | !5 · `40f9d5f` · $0.03 | #4 · `1fca646` · $0.03 |
| D `add-stock-valuation` | !7 · `3aa735b` · $0.05 | #6 · `8027e5a` · $0.05 |
| E `invoice-line` | !9 · `6d6d718` · $0.08 | #8 · `48a5f15` · $0.07 |
| F `add-valuation-summary` | !10 · `63af33b` · $0.04 | #9 · `3cf267b` · $0.06 |
| G `invoice-lines` | !12 · `3a2d050` · $0.07 | #11 · `43accb4` · $0.08 |
| H `add-summary-currency` | !13 · `7d260a8` · $0.04 | #12 · `f9472bb` · $0.04 |
| I `add-shelf-label` | !15 · `0371140` · $0.04 | #14 · `ad6ddf2` · $0.04 |
| J `units-surplus` | !17 · `29bc685` · $0.05 | #16 · `f5ed57a` · $0.04 |
| **Plan** | **$1.47** (reviews $0.96), 15 dispatching runs, 2 h 20 min from activation, of which 1 h 44 min paused for defect 3; 34 min of running after the fix | **$1.00** (review $0.47), 12 dispatching runs, 37 min from activation |

## Checked again from fresh clones

Both repositories were cloned fresh on a laptop after `plan.completed`. On each integrated branch: `uv sync --frozen`,
the test suite, and `smoke.py`. The smoke script imports every module and checks all ten features together with the
specs' own examples, 34 checks; the toy has no entry point (`package = false`), so this is what "starts" means here.
To check that the suites test something, three functions were broken in a throwaway copy, one at a time.

| | GitLab `staging` 29bc685 | GitHub `l4/main` f5ed57a |
|---|---|---|
| Tests | 57 passed | 60 passed |
| `smoke.py` | 34/34, all 10 modules import | 34/34 |
| `main` (untouched) | 15 passed | 15 passed |
| `vat_cents` broken | 18 failed | 20 failed |
| `units_surplus` broken | 4 failed | 3 failed |
| `invoice_lines` broken | 5 failed | 5 failed |

The two forges' implementations differ (57 and 60 tests: two independent runs of the same specs); both meet the specs.

## Stop cases (task 9.3, and 9.4's stop case on GitLab)

Run after the two scenarios, on the integration branch (`cb65669d`, then `9aa4000a`, then `8388c1a4`), with three tiny
OpenSpec changes: `add-percent-off`, `add-discounted-total` (needs `add-percent-off`) and `add-sku-normalize`.

| Case | Where, plan | What happened (plan ledger) |
|---|---|---|
| A spec push to the current unit | GitHub, `stops-a` (`merge: auto`) | `add-percent-off` dispatched 07:52:22; a scenario added to its spec on `l4/main` at 07:52:37; the unit's guarded merge was refused (`unit.merge_refused stale`, the target is not in the unit head); the next step stopped the plan: `plan.stopped inputs_changed` "the spec of openspec:add-percent-off changed after the activation" (07:55:52). |
| Recovery after that stop | GitHub, `stops-a` | The verifier asked a verdict question for the new scenario (no test traced it); answered `reject: add a test`. CI reviewed again, a person activated again (09:25:22), the plan resumed when the answer was read, merged both units and completed (09:34:29). `tests/test_discount.py` asserts `percent_off(250, 100) == 250`. |
| `merge: human`: the plan never merges | GitHub, `stops-b` | `add-sku-normalize` dispatched 09:36:14 and handed off (PR #21, verdict PASS); several runs later the PR was still open and unmerged. |
| `l4 yolo cancel` | GitHub, `stops-b` | `plan.cancelled` 09:45:52; the next run: `nothing to do: no unit has a next step`; PR #21 left open for a person. |
| `l4 yolo cancel` while the second unit is current | GitLab, `final-gl` (the final harness, `8388c1a4`) | `add-percent-off` merged and integrated (09:54:02); `add-discounted-total` dispatched 09:54:39; cancelled 09:54:52. Its run finished and opened MR !20; twelve minutes and three pipelines later MR !20 was still open and `staging` had not moved. |

The recovery found two more defects (fixed, see below): the re-review read the harness's ticks in `tasks.md` as a
contradiction, and a review made with an older review prompt stayed current. One operator error is worth noting: an
answer written under a second `### Answer` heading is not read; write it under the template's own heading.

## A batch acceptance profile, an adopted unit, a plan after a plan (task 9.2, GitLab)

Plan `batch-gl` (`merge: auto`): one batch `smoke` with `acceptance_profile: smoke` (`yolo.profiles: {smoke: [test]}`)
over `add-discounted-total`, in review since `final-gl` was cancelled (MR !20), and a new `add-sku-normalize`.

| Step | Plan ledger |
|---|---|
| The review knows what an earlier plan delivered | the first review asked for `add-percent-off` as a dependency (it is archived on the target, so no plan can list it): defect 6; after the fix the judge asked only that the spec state `percent_off`'s rounding (a fair finding, fixed in the spec on the unit branch); then READY |
| The plan adopts a unit that is already in review | `add-discounted-total` dispatched 11:28:53 and merged 11:30:07 (MR !20) |
| The batch check | after both units integrated: `batch.failed`, "test failed (report missing: .l4-out/junit.xml)": defect 7 |
| Recovery: `l4 yolo resume` after the fix | `plan.resumed` 11:47:40, `batch.accepted smoke` 11:48:03, `plan.completed` 11:48:28 |

## Defects this run found, each fixed with tests

1. **A batch without an acceptance profile was refused at random.** The review asked the judge whether "the units
   together deliver the batch outcome", which a plan file cannot state; two batches of the same shape passed, two
   failed. Such a batch now only groups units; a `batch_acceptance` finding on it is kept as an assumption
   (L4-YOLO-004, `3957acfa`).
2. **A batch review did not show its units' prerequisites,** so the judge reported them missing. It now shows them, as
   a unit review does, and both say that a prerequisite is merged before its dependants start (`32321f0a`).
3. **Two projects on one runner collided on a worktree path.** Worktree and lock paths had no repository key; an older
   project on the same runner had a change `add-money-format`. Every run of A stopped with "a checkout of another
   repository" — and the plan step chained the next run anyway: 5 runs in 2 minutes, stopped by a person. Paths are now
   keyed by the normalized `origin` (L4-WTR-001, L4-LCK-001, L4-CFG-005, `cc58912d`); the chaining is fixed on the
   integration branch: a unit that never starts makes the plan wait (`unit_not_started`) instead of chaining runs.
4. **A re-review after a mid-unit stop could never pass.** It showed the judge `tasks.md` from the unit branch, where the
   harness had ticked the done tasks; the judge called that a contradiction. The review now shows the folder exactly
   as the change digest sees it, every task unticked (L4-YOLO-004, `9aa4000a`).
5. **A review made with an older review prompt stayed current,** so a fix to the review could not reach a plan whose
   inputs had not changed. `plan.reviewed` records the prompt version; an older one is stale (L4-YOLO-004, `8388c1a4`).
6. **A plan could not depend on what an earlier plan delivered.** An archived change cannot be a unit of a new plan
   and `external_dependencies` must be empty, but the judge saw neither, so it asked for the dependency. The review
   now lists the units already delivered on the target (L4-YOLO-004, prompt version 3, `afcce3e4`).
7. **A batch profile ran its gates without `gates.setup`** on the fresh worktree, so every check of a project with a
   setup step failed (the documentation's own example too). Setup now runs first, as a prerequisite that never counts
   toward a pass (L4-YOLO-009, `5863fb68`).
8. **The planning guide** said to commit the plan file without its specs (new specs would then run before the plan
   holds them) and to run `l4 yolo check` before the push (it reads the target). Both fixed (L4-YOLO-020).

Smaller findings, not yet fixed: `l4 init --action` cannot infer the action repository from a worktree checkout (pass
`--action-repo`); the activation push error on GitHub names GitLab's token rules; the harness push from a laptop ignores
git's https credential helper (an SSH remote works).

## Not covered here

- The lesson's effect: neither forge produced a `vacuous` red test in this run, with or without the lesson, so the run
  shows the injection, not an effect.
- The loop fix (`run_not_started`) is covered by unit tests with a real `l4 run`, not by a live run: after the
  repository-keyed paths no live unit failed before it started.
- A `merge: human` plan merged by a person: the person's merge was not exercised (PR #21 was cancelled instead).

## Files

- `enforcement-gitlab.txt`, `enforcement-github.txt`: the output of `analyze_enforcement.py`.
- `report-gitlab.md`, `report-github.md`: `l4 yolo report valuation`.
- `events-gitlab.txt`, `events-github.txt`: the plan ledgers at `plan.completed`, one line per event (time, type,
  unit, reason, usage), without URLs or identities.
- `analyze_enforcement.py`: the checker.
- `smoke.py`: the end-to-end check of the ten features.
- `events-stops-a.txt`, `events-stops-b.txt`, `events-final-gl.txt`: the stop cases; `events-batch-gl.txt`: the batch
  profile.
