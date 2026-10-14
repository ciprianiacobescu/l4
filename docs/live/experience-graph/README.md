# Experience graph, live on the test repositories' history (tasks 8.3 and 8.4)

**Date:** 2026-10-15.
**Harness:** branch `kg` (`l4 kg` and `l4 lessons promote`), run from a laptop on local clones. Nothing ran in CI,
nothing was fetched or pushed by `l4 kg`, and no model was called.
**GitHub:** `ciprianiacobescu/l4-dummy-action` (private), cloned with `git fetch origin '+refs/l4/*:refs/l4/*'`,
checkout `l4/main` (its `forge.base_branch`). The history is the operator-commands live test
(`docs/live/operator-commands`): 4 units, among them `kiro:pick-priority` with 3 kept attempts and 3 restarts.
**GitLab:** the self-hosted GitLab test repository of yolo-mode, checkout `staging` (its `forge.base_branch`). It had no L4 run yet.

## 8.3: build, report, why

| Step | Result |
|---|---|
| `l4 kg build` (GitHub) | `index built: 134 nodes, 301 edges from 16 refs (n = 16)`, `skipped: none (n = 0)` |
| `l4 kg report --out .l4-out/kg/report.md` (GitHub) | [github-report.md](github-report.md) |
| `l4 kg why kiro:pick-priority` (GitHub) | [github-why-pick-priority.txt](github-why-pick-priority.txt): 4 attempts, every line with its `src` |
| `l4 kg build` and `report` (GitLab) | `index built: 0 nodes, 0 edges from 1 refs (n = 1)`; [gitlab-report.md](gitlab-report.md) says n = 0 everywhere |

The GitLab report is empty because that repository has no L4 history yet. It is run again after the yolo-mode
scenario (`docs/live/yolo-mode`).

### Five numbers checked against `git show` of their sources

[recount.py](recount.py) reads the ledgers and verdicts straight from the git objects of every ref. It deduplicates
by blob and by `(run_id, seq)`, and uses no `l4.kg` code. Its output is [github-recount.txt](github-recount.txt).

| Report line | Report | Recount | |
|---|---|---|---|
| Runs | n = 26 | 26 distinct `run_id` | [V] |
| Rounds | n = 18 | 18 distinct `verdict.json` blobs | [V] |
| `vacuous` | n = 2 units, n = 5 attempts | 5 `task.attempt_failed` with a `vacuous:` reason, units `kiro:add-low-stock-message` and `kiro:pick-priority` | [V] |
| Lesson `L-e7230fe4` | n = 9 prompts | 9 `lessons.injected` events naming it | [V] |
| Run `r-20261013T2113Z-72cb` (`why`) | exit 13, n = 3 failed task attempts | `git show 6029fda4a0:.kiro/specs/pick-priority/.l4/ledger/r-20261013T2113Z-72cb.jsonl`: `run.finished` `exit_code 13`, 3 `task.attempt_failed` (lines 29, 40, 51) | [V] |

The attempt count also agrees: 3 attempt refs plus the current branch for `kiro:pick-priority`, and 1 attempt each
for the other 3 units, give 7.

## 8.4: a recurring failure class

`vacuous` recurs in 2 units, so the success path of design "How the implementer benefits" applies.

1. `l4 kg propose` wrote the draft `L-8d816d0e` (dedupe key `kg-a-vacuous`) and its evidence file to
   `.serena/memories/inbox/kg-2026-10-14/`. The evidence file named the 5 sources:
   - `b14ff415e7:.kiro/specs/add-low-stock-message/.l4/ledger/r-20261013T0043Z-f8c5.jsonl#29`;
   - `6029fda4a0:.kiro/specs/pick-priority/.l4/ledger/r-20261013T2113Z-72cb.jsonl#29` and `#40`;
   - `6029fda4a0:.kiro/specs/pick-priority/.l4/ledger/r-20261013T2120Z-eefa.jsonl#37` and `#48`.
2. The operator replaced the `TODO(person)` line with advice taken from the harness's own rule
   (`implementer/discrimination.py`: a red test must fail **by assertion** when the stub answers its zero value).
3. **Defect found:** `l4 lessons promote L-8d816d0e` refused on `l4/main`. The base branch sits under the unit-branch
   prefix `l4/`, so the command took it for a unit branch. Its message named `l4/main` as the branch to promote on.
   It is fixed on `kg` (`check_checkout` exempts `forge.base_branch`), with the regression test
   `test_a_base_branch_under_the_prefix_is_not_a_unit_branch`.
4. After the fix, the promote wrote the lesson (scope: every task). It made one commit that changes only
   `.serena/memories/harness/lessons.md`, with the person's identity and no `L4-*` trailer: see
   [github-promote.txt](github-promote.txt) and [github-promote-commit.txt](github-promote-commit.txt).

The rest of 8.4 needs later units: their `lessons.injected` events for `L-8d816d0e` and the lesson's line in
`kg report`. Those units are the yolo-mode scenario's units on the same repository. The result is recorded there and
added here.
