# GitHub parity, live (change `github-parity`, L4-GHP-013)

**Dates:** 2026-10-11 and 2026-10-12 · **Repository:** public dummy `ciprianiacobescu/l4-dummy-public` (default branch
`amaster`), created for this test. It was made private on 2026-10-12 and the maintainer deletes it · **Harness:** fetched at run time from the private
`ciprianiacobescu/agent-supervisor` at `4ce89efc` (then `80b9f6de`), never committed to the dummy repository ·
**Runners:** GitHub-hosted `ubuntu-24.04` · **Forge token:** the workflow's own `GITHUB_TOKEN` · **Agents:**
implementer `oc-free` (OpenCode `opencode/mimo-v2.6-flash-free`), judge `claude-judge` (Claude Code, subscription token
as an environment secret; served `claude-sonnet-5-5`). Labels: **[V]** observed here.

## What was set up, and how

1. **Content.** The dummy repository got:
   - the eval seed base project and two seed units as OpenSpec changes (`add-shelf-code`, `add-tip-amount`, no reference
     answers);
   - `l4 init --ci github --harness-repo git@github.com:ciprianiacobescu/agent-supervisor.git --harness-commit 4ce89efc…`.

   The repository's tracked files are only the project, `openspec/`, `.l4/config.yaml`, `.l4/bin/l4`,
   `.l4/bin/l4-setup`, `.serena/project.yml`, `.github/workflows/l4.yml` and `README.md`. **No `.l4/vendor/`** [V].
2. **Deploy key.** A read-only key, id 166118772, was added to the harness repository. Its private half became the
   environment secret `L4_HARNESS_SSH_KEY`.
3. **`l4 setup github`**, run through the Mintkey proxy (`--api-url http://localhost:8000/v1/call/<service>`, a brokered
   token):
   - the first real run created the environment `l4` and its branch policies (`amaster`, `l4/*`, `l4/**/*`), set the
     workflow permissions and sealed the two secrets;
   - then a transient 502 from the proxy stopped it;
   - the second run printed `KEPT` for everything already done, created the variable and the labels, and failed only on
     the dispatch, because the workflow was not pushed yet (`404`).
4. **Push.** Pushing the content started the first run.

## Runs [V]

| run | event | what happened | duration |
|---|---|---|---|
| 38173604230 | push `amaster` | cold, described in detail below; one unit left for a continuation | 209 s |
| 38173836160 | `workflow_dispatch` (the continuation) | warm cache; `add-tip-amount` → PR #2 `in_review` (green took 1330 s on the free model) | 1444 s |
| 38175544040 | push `amaster` (PR #1 merged by the maintainer) | `sweeper: … MR !1 merged`, then `archive MR !3 opened` | 40 s |
| 38175559320 | push `amaster` (new spec `accept-whole-amounts`) | red → PR #4; green: the model asked Q-001 instead of guessing → `awaiting_human`, `l4:needs-answers`, exit 11 | 1252 s |
| 38177286893 | push `l4/openspec/accept-whole-amounts` (the person's answer) | `l4: base checkout 57f64298…`; `Q-001 answered by human` → green → PASS → PR #4 `in_review` | 158 s |
| 38177607674 | push `amaster` (`l4 upgrade --harness-commit 80b9f6de…`) | cache miss on the new key, `Built l4harness …@80b9f6de…`; the sweep prints `ci: H … no workflow ran on the hand-off commit; pushes made with GITHUB_TOKEN start no runs` for PRs #2 and #4; `nothing to do` | — |

**The cold run, 38173604230:**
- Deploy key and setup:
  - the deploy-key step set `GIT_SSH_COMMAND`;
  - `l4-setup` installed uv user-locally, extracted bwrap 0.9.0, ran the one sysctl and passed the self-test.
- Doctor:
  - `doctor --ci --fix` printed `Built l4harness @ git+ssh://git@github.com/ciprianiacobescu/agent-supervisor.git@4ce89efc…`;
  - it installed OpenSpec, Claude Code and OpenCode;
  - `ENV-001 Python 3.12.3` and `PRV-001 claude-judge claude-code ready; oc-free opencode ready`.
- Unit `add-shelf-code`:
  - red was done by OpenCode in 65.8 s, and the push opened draft PR #1 as `github-actions[bot]` with the label
    `l4:implementing`;
  - green took 36.9 s;
  - the judge gave `PASS (round 1, 2/2 criteria pass)` with `claude-sonnet-5-5` for $0.03;
  - the hand-off was pushed, the PR marked ready, label `l4:in_review`, unit time 156 s.
- Continuation:
  - `soft deadline: 1 unit(s) left for the next run`;
  - `continuation: dispatched (l4.yml on amaster)`;
  - `::notice::l4 exit 10 (continue)`.

**The continuation run, 38173836160:**
- `Cache restored from key: l4-tools-Linux-X64-ubuntu24-harness-4ce89efc…`.
- The harness was not rebuilt: no `Built l4harness` line, uv's cache held it.
- The cached bwrap failed on the fresh VM and was not downloaded again. The sysctl ran, then the bwrap passed.

## Requirement by requirement

| requirement | evidence |
|---|---|
| L4-GHP-001 the workflow token knows itself | PR #4's sticky note was written by `github-actions[bot]` (id 41898282) with the marker. After the answer the bot updated that same comment in place: "Nothing is waiting for a human answer." [V] |
| L4-GHP-002 a refused PR names the setting | not triggered: `l4 setup github` allowed Actions to create PRs first. Unit test only. |
| L4-GHP-003 soft deadline | `L4_JOB_TIMEOUT_MINUTES: "180"` in the job env. With `time_budget: 21m` and a 20 m margin, the second unit waited [V] |
| L4-GHP-004 continuation | `continuation: dispatched (l4.yml on amaster)`. Run 38173836160 is the `workflow_dispatch` it started [V] |
| L4-GHP-005 base checkout | `l4: base checkout 57f64298…` in the unit-branch run [V] |
| L4-GHP-006 skip rule | the rendered `if:` exempts `amaster`. No `L4-Run:` push to the base occurred in the test. |
| L4-GHP-007 resume by label | Live API conformance, called through the forge: `label_events(2)` returned the bot's own `l4:*` changes (actor 41898282) and a person's label (actor 62260271); `member_access(owner)` = 50; the bot → None. The full halted → label → resumed loop was not run live (no unit halted); the sweeper logic is unit-tested. |
| L4-GHP-008 no check run is not green | found live: the duty was silent in `plan --sweep`. Fixed in `80b9f6de` (`ci_not_run`). Run 38177607674 printed `openspec:add-tip-amount: ci: H cb0ef12b25: no workflow ran on the hand-off commit; pushes made with GITHUB_TOKEN start no runs (use a token that does, or a GitHub App)` [V] |
| L4-GHP-009 links and wording | Found live: the sticky note's "Answer in" link used GitLab's `/-/blob/`. Fixed in `a3f770d7` with one `blob_url` for the PR body and the note. PRV-001 wording: unit tests. |
| L4-GHP-010 fetched harness | `Built l4harness @ git+ssh://…@4ce89efc…` cold, cached when warm. `l4 upgrade --harness-commit 80b9f6de…` changed only `harness.commit` and the cache key [V] |
| L4-GHP-011 `l4 setup github` | as above. The second run printed `KEPT` for every step already applied [V] |
| L4-GHP-012 `l4 ci watch` | `l4 ci watch --repo ciprianiacobescu/l4-dummy-public --ref amaster --api-url <Mintkey proxy>` printed `run #38177607674 completed … l4 success`, then exit 0 [V] |
| L4-PRV-027 environment secrets | both secrets were environment secrets of `l4`, and the dummy repository had no repository secret. The job on the unit branch `l4/openspec/accept-whole-amounts` received them, so the branch policies match nested unit branches [V] |

## Findings

1. **The sticky note's questions link was GitLab's form on GitHub.** Fixed: `forge.urls.blob_url`, used by both
   renderers (`a3f770d7`).
2. **The `ci_not_run` duty was invisible.** `plan --sweep` prints only `ci_*` actions. Fixed: the action is
   `ci_not_run` (`80b9f6de`).
3. **The continuation log line had a doubled `[l4]` prefix.** Fixed (`00bdffa5`).
4. **`l4 init`'s closing note said "add the repository secret L4_FORGE_TOKEN" on GitHub.** Fixed: it now names
   `l4 setup github` and the environment `l4` (`57286886`).
5. **The free model is slow and variable.** Green took 37 s, then 1330 s, then 70 s on similar units.
   `ci.time_budget` and the job timeout must allow for that.
6. **The seed project has no coverage.py,** so COV-001 records diff coverage `not_run`. This is expected for the toy
   project.
7. **The free model asked a precise question instead of breaking a frozen test.** Q-001 named the contradicting line
   and offered three options. The person's answer (option 1, which removes the old test) unblocked it in one run.

## Evidence files

`runs/<run id>.txt` keeps each job's `[l4]`, setup, doctor, cache and harness-build lines, cut from the job log before
the repository was deleted. The full logs went with the repository.

## Clean-up

Done on 2026-10-12:
- deploy key 166118772 removed from the harness repository;
- the dummy repository's two environment secrets deleted;
- the repository made private;
- its Actions disabled, so the 30-minute schedule no longer bills runs on a private repository.

Still to do: delete the repository. The Mintkey token used for the setup cannot delete repositories (no `delete_repo` scope), so the maintainer
deletes the repository.
