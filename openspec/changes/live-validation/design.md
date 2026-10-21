## Context

SPEC 20.4: "Live - opt-in pipeline against the reference environment: the dummy GitLab repository
`example-group/dummy-agentic` on runner `l4-runner` (tags `agentic`), plus a GitHub test repository; seeds a small app
with an OpenSpec change and a Kiro spec". SPEC 24.2.3 requires the live test to pass on the reference GitLab and on a
GitHub repository before `v1.0.0`. The implementation map fixes the M1 exit criterion as five observable steps.

Reference environment [V, architecture section 15, 2026-10-03]: project id 118, default branch `main`, merge method
`merge`, `build_timeout` 3600 s (maintainer decision: raise to 180 min), runner #12 `l4-runner` (v19.4.1, shell
executor, tags `agentic, ai, opencode`, `run_untagged: false`), runner #8 `docker-runner` takes untagged jobs
(pipeline #2521). `CI_JOB_TOKEN` cannot push; the harness uses a project access token `l4-bot` (`api`,
`write_repository`, Developer) in the masked CI variable named by `forge.token_env` (`L4_FORGE_TOKEN`).

## Goals

- Every live assertion is made against an oracle that is independent of the code under test.
- A live run is reproducible: reset script, seeded fixture, recorded evidence (pipeline ids, MR iid, labels, ledger lines).
- NFR requirements are executable benchmarks with a failing counterpart proving the benchmark can fail.

## Non-Goals

- Provisioning the runner or logging agents in (human steps, `runner-provisioning` prints them).
- Changing GitLab project settings (job timeout, schedules are created by a human; the harness never changes forge settings).
- Measuring SC-03..SC-17 benchmarks of SPEC section 25 (separate benchmark effort; this change provides the harness for
  them only for SC-10 timing hooks).

## Decisions

### D1. Raw-API oracle, separate from the harness's forge client

`tests/live/gitlab_oracle.py::LiveGitLab` is a ~100-line httpx wrapper (`pipeline(id)`, `jobs(pipeline_id)`,
`mr(iid)`, `mr_by_branch(name)`, `labels(iid)`, `commit_status(sha)`, `commits(ref)`, `file(path, ref)`,
`play_schedule(id)`) that shares no code with `l4.forge.gitlab`. This follows the rule that a system's own output is
never its own oracle. Credentials: `L4_LIVE_TOKEN` (read/inspect, may be the Mintkey-brokered `example-gitlab` service
whose identity is an instance admin - acceptable for read-only inspection only) and `L4_LIVE_HUMAN_TOKEN` (a maintainer
personal token used solely to play the human: merge the MR, commit the answer). The harness itself only ever uses the
project access token in the CI variable.
Alternatives: use `GitLabForge` in the tests (rejected: circular); scrape the web UI (rejected: brittle).

### D2. Gating

Live tests carry `@pytest.mark.live` and skip unless `L4_LIVE=1`. Offline unit tests cover the helper code with
`httpx.MockTransport` so `uv run pytest -q` stays green in normal CI. Each live test prints its evidence and appends it to
`.l4-out/live/<run-id>/evidence.json` (pipeline id, job ids, runner id, MR iid, head SHA, label set, ledger events seen).

### D3. Seeded fixture

`tests/fixtures/dummy-agentic/` is a Python stdlib-only app (`unittest`, no third-party tooling) with
`pyproject.toml`, `tests/`, `openspec/config.yaml`, change `add-greeting` (two small tasks, two scenarios), change
`add-ambiguous` (a requirement that deliberately leaves a product decision open so the implementer raises a question)
and, for M2, change `add-gap` (tasks cover only the happy path while a scenario requires empty-input handling) together
with the human-owned gate `scripts/live/gap_gate.sh`, listed in `gates.extra` of the live config, which fails until the
empty-input behaviour exists - a deterministic way to force the verifier failure -> fix unit -> PASS path.
The live configuration is the `l4 init` output plus the runbook's documented edits; the edited result is kept as
`tests/fixtures/dummy-agentic/l4-config.live.yaml` (written to `.l4/config.yaml` by the seed script after `l4 init`, and loaded
through `load_config` in an offline test). It fixes what the other changes' M1 slices assume: `ci.runner_tags: [agentic]`; `ci.self_provision:
auto`; an implementer chain of `claude-code` (subscription) and `opencode` profiles; a judge and `s1_judge` chain of `openai-chat`
profiles on OpenRouter whose `vendor` differs from every implementer vendor (verifier D4); a clarifier profile;
`clarifier.s1_standin: llm_boolean` (clarification-loop D5, opt-in, so the M1 clarifier can auto-answer without System-One); low
`budgets.max_cost_usd_per_unit`; and `sandbox.mode: auto` (bubblewrap on the runner, SPEC Q6). Until the maintainer installs
bubblewrap, SANDBOX-001 fails closed and step 1 cannot pass; the only alternative is the explicit accepted risk `sandbox.mode: none`
plus `sandbox.allow_none: true`, which the evidence file must record (`sandbox.risk_accepted`).
`scripts/live/seed_dummy.sh` (human-run) pushes the fixture and the output of `l4 init` to `main`;
`scripts/live/reset_dummy.sh` closes MRs and deletes `l4/*`, `l4-wip/*` branches and `refs/l4/locks/*` between runs.

### D4. Expected observables per M1 step (the contract the tests assert)

| Step | Observable (raw API unless noted) |
|---|---|
| 1 doctor | pipeline on `main` finishes `success`; job `l4-detect` has `runner.id == 12`; its log contains the doctor table with zero failed `error` rows; artifact `plan.json` lists `openspec:add-greeting` |
| 2 red/green | branch `l4/openspec/add-greeting` exists; commit list shows a commit with trailer `L4-Phase: red` older than the commit with `L4-Phase: green` for task 1.1; ledger file `openspec/changes/add-greeting/.l4/ledger/<run>.jsonl` contains `availability.selected`, `task.red_ok`, `task.done` |
| 3 verify | `openspec/changes/add-greeting/verification.md` on the branch; ledger has `gate.result` events all passed and exactly one `verify.verdict` with verdict PASS from a judge whose vendor differs from the implementer's |
| 4 MR + archive | MR for the branch is not a draft, label `l4:in_review`, commit status `l4/openspec/add-greeting` = `success` on the head, head commit has trailer `L4-Run` and no `[skip ci]`; the repository's own pipeline for the head exists and the l4 jobs are skipped; after the human merge and one played schedule an MR from `l4/archive/openspec/add-greeting` into `main` exists whose changed paths are only under `openspec/specs/` and `openspec/changes/` |
| 5 clarification | branch `l4/openspec/add-ambiguous` has `openspec/changes/add-ambiguous/questions.md` with `## Q-001`; labels `l4:awaiting_human` and `l4:needs-answers`; the run job ended exit 11 shown as an allowed failure; ledger has `question.raised` and `clarifier.result`; after the human commit sets the answer, a new pipeline starts and the ledger gains `question.answered` and the label becomes `l4:implementing` |

### D5. NFR benchmarks

- NFR-001: a generator builds 200 OpenSpec change folders in a tmp dir; the benchmark times `l4 doctor --ci` and
  `l4 plan --json` via `subprocess` wall clock with a 30 s assertion; a negative test patches the planner to sleep 31 s and
  asserts the benchmark fails.
- NFR-002: `l4 simulate` with zero-latency fakes, 20 steps; harness time = wall time minus time inside fake adapters and
  gates (the fakes expose their own accumulated time); a negative test adds a 6 s harness-side sleep.
- NFR-003: run `plan --json` and `simulate happy-openspec --json` twice with different `PYTHONHASHSEED`, strip `ts`,
  `run_id`, `duration`, compare bytes; the negative test injects set-ordered iteration.
- NFR-004: `scripts/check_wheel_deps.py` builds the wheel, reads `Requires-Dist` from METADATA, ignores `extra ==`
  markers, compares to the approved set, fails on `litellm`.
- NFR-005: assert the harness's own CI definition has Linux (full suite + simulation) and macOS (unit tests) jobs; doctor
  SANDBOX-001 severity tests for `ci.platform: local` (warning) versus `gitlab` (error) on macOS.
- NFR-006: `scripts/check_ga.py` reads the adapter registry's `[U]` facts and the contract-test/LIVE-check mapping in
  `tests/contract/ga_facts.yaml`; exits non-zero naming unmapped facts.
- Release check: `scripts/check_release.py` requires evidence JSON of a passing GitLab live run and a passing GitHub
  live run before it allows the `v1.0.0` tag.

### D6. Section 20.4 is not an L4 requirement ID

SPEC section 20.4 has no `L4-` ID, so the three requirement blocks are headed `§20.4 (part a|b|c)`. The block text is the
normative reading of 20.4 plus 24.2.3. Recommendation: a SPEC amendment assigns an L4 ID to section 20.4 so tasks can cite it in the `[L4-XXX-NNN]` form; until then every live task also cites the L4 requirement it exercises.

## Risks / Trade-offs

- Real agent output is nondeterministic; the live assertions check structure (ordering of phases, presence of events),
  never exact code. A flaky live step is retried once and both attempts are recorded; a second failure is a finding.
- Live runs spend subscription quota and API money; the runbook requires provider-side spend limits and the live config
  sets `budgets.max_cost_usd_per_unit` low.
- The human steps (project access token, masked variable, schedule, agent logins, bubblewrap on the runner) cannot be
  automated; the runbook states the exact commands and the failure signatures (`.bash_logout` running `clear_console`
  fails jobs in "prepare environment"; untagged jobs run on runner #8; `: ` inside a plain `script:` item).
- A GitHub test repository is an open decision (SPEC Q5); M2 steps for GitHub are blocked until a human provides one.
- The 3600 s `build_timeout` limits M1 jobs to roughly 40 minutes of work (the soft deadline applies); the 180 min
  setting is the maintainer's to make, doctor CI-004 reports the current value.
