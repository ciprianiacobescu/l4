# Changelog

All releases of the L4 harness. Consumers pin a release tag `vX.Y.Z` (or the moving major tag `v0`). The source of a
release is the tag `src-vX.Y.Z` on `amaster`; the release commit on branch `release` holds only the shipped paths.

The harness is before 1.0. Each entry says what was added, what changed in behaviour and what was fixed, so a
consumer can decide when to move its pin (`l4 upgrade --harness-ref vX.Y.Z`).

## 0.4.19 (unreleased)

### Added
- A `kiro-cli` profile can be a judge, a clarifier and a plan-readiness reviewer (`roles.judges`, `roles.clarifier`,
  the `s1_judge` stand-in). It runs a tool-less harness agent (`tools: []`, no MCP server, no resources) from a private
  `KIRO_HOME` with `chat.disableInheritingDefaultResources`, in an empty folder, with the prompt on standard input and
  no trust flag (L4-KJD-001, L4-KJD-002). Its reply is the final text of the stream, sliced to one JSON object and
  validated, with the same repair as any judge (L4-KJD-003). A run that holds a tool call or a `runError`, started any
  part on an engine other than `v2`, or was served a model that contradicts a pinned one is never a verdict. The
  delegate role, when it ships, is not to take a `kiro-cli` profile.
- `auto` by default: a `kiro-cli` profile with no `model` passes `--model auto` in every mode. `auto` is routed: its
  possible vendors are the makers of the Active models of `kiro-cli chat --list-models --format json`, listed once in
  the `auth` step of `l4 probe` and joined with the built-in set (`anthropic`, `minimax`, `zhipu`), which is used alone
  when the listing fails. `l4 probe` names the set and its source. The served model is read from the CLI's session file
  (L4-KJD-012, L4-KJD-013, L4-KJD-015): an `auto` judge whose served model has the implementer's vendor loses its verdict
  as `model_mismatch`, a pinned model that Kiro could not set is a `model_mismatch`, and `routed (unverified)` is a new
  independence status (`kiro-auto routed: anthropic, minimax, zhipu (auto)`). For a pinned model the session file only
  detects a mismatch: it is the CLI's own selection, so a pinned Kiro judge stays `declared`.
- Doctor `CFG-011` (warn, never an error) describes each `kiro-cli` judge or clarifier profile, with the possible
  vendors of an `auto` profile and their source, and warns on `options.agent` and on a `min_version` below `2.32.0`
  (L4-KJD-009). A `vendor:` on an `auto` profile is noted as ignored. On a fresh runner, where doctor runs before any
  probe has recorded a listing, the line says `built-in (no listing recorded yet)`, not `built-in`.
- Judge and clarifier credits: `verify.judge.credits` and `budget.cost{credits, credits_source: kiro.stream, role}` for
  a Kiro call, summed over its calls and never added to dollars (L4-KJD-004).
- The simulation replays a judge's recorded stream through the real kiro-cli adapter (scenario `happy-kiro-judge`), and
  `tests/fixtures/recorded/kiro-cli/2.32.0/` holds the recorded shapes (L4-KJD-010).
- `l4 yolo go PLAN --reason TEXT [--accept-findings | --force] [--yes] [--json] [--no-push] [--local] [--wait DURATION]`
  takes a plan from a committed file to an active plan in one command. It runs preflight, push, check, review,
  findings, accept and activate over the existing commands, with their rules and leases, reads before each step
  whether it holds, and stops at the first step that cannot pass with one stop code (20 to 29, not members of the exit
  table) and one `Next:` line. It pushes the base branch only as a fast-forward and never forces. CI reviews are read
  from the plan ledger every 15 seconds up to `--wait`. `--json` prints one `l4/yolo-go@1` document. It is safe to run
  again, to interrupt and to run twice at once (a lost plan lease is read again, at most three times). A person types
  the plan id before the activation (`--yes` skips it; without a terminal and without `--yes` the run stops with 29);
  an agent's run stops at a person's step (activation, `--force`, a push outside the plan file and its unit folders,
  the cancel of another active plan), and `--json` marks such a next command with `next_by: person`
  (L4-YOLO-080 to L4-YOLO-089).
- The MCP tool `l4_plan_go` runs `l4 yolo go` as an agent, read-mostly: no `--accept-findings`, `--force`, `--yes` or
  `--local`, and `--no-push` always. It may ask CI for a review (judge tokens) and wait; it never pushes, accepts or
  activates (L4-YOLO-090).
- The skill's `operate.md` and `plan.md`, the runbook (12.2) and `docs/yolo-mode.md` teach the one command
  (L4-YOLO-091).
- The GitHub workflow templates record the job's start (`L4_JOB_STARTED_AT`, a first step `job start`), and the
  soft deadline counts from it. Run `l4 upgrade` to get the step; until then the deadline counts from the run's start,
  and the run warns once (L4-IMP-066).
- Before each implementer step and each verification round, a run with a known budget compares the time left
  with the step's estimate. The estimate is the longest step of that kind in this run or among the unit's recorded
  steps, at least 10 minutes and at most one agent time limit plus `gates.timeout` (four gate timeouts for a round). A
  step that does not fit is not started; a resumed green is checked before its baseline. The first step of a run
  always starts. Every step records `step.timed` (L4-IMP-067).
- At the soft deadline, every agent, CLI judge and gate that the unit's run has running gets SIGINT, then SIGKILL
  after 5 s. The step is handed back: `deadline.reached` is recorded, no attempt is counted, the phase does not change,
  the ledger and the unit branch are pushed, `run.finished` has `reason: soft deadline: …`, and the run exits 10. The
  next run continues from the last pushed step, and a stopped replay of a held step is replayed again (L4-IMP-068,
  L4-IMP-069).
- A step stopped at the soft deadline starts again only as the first step of a run, and a second stop halts the
  unit with `deadline_repeated`. The reason names the job timeout to raise and `l4 retry` (L4-IMP-071).
- A GitHub run that the pin guard stops off the base (a scheduled run on a default branch that is not the base, or a
  push to an old unit branch) relays to the base before it reads the configuration, so a configuration key that its
  older harness does not know cannot stop it. `l4 doctor --ci`, `l4 plan --sweep`, `l4 run` and `l4 status` stop there
  and exit 0; the first of the first three dispatches `l4.yml` on the base once per job, when the base may have work
  and no other run of `l4.yml` is queued or running there, and prints what it did (`outcome.json` `relay`). On the
  base itself a configuration error stays exit 2. It works once the default branch's copy pins 0.4.19 or later: copy
  .github/workflows/l4.yml to the default branch once (or promote the base); the base's own run warns while that copy
  is behind, or missing (L4-IMP-072, L4-IMP-074).
- `l4 yolo status` calls an open run "ended without a record" when it is older than its job timeout (recorded on
  `run.started` as `job_timeout_s`) or when the forge says its CI run completed. For an active plan whose open run
  ended without a record, or with nothing running or queued on the base and either idle for two schedule periods or
  with no schedule that can advance it, `Next:` gives the command that starts a run on the base (`gh workflow run
  l4.yml --ref <base>`). `--json` has `open_run.ended_without_record` and `open_run.why` (L4-IMP-073).

### Changed
- `kiro-cli` is a judge adapter: it is in `JUDGE_ADAPTERS` (`l4/config/roles.py`), so a `kiro-cli` profile loads in
  every judge role of that file (`roles.judges`, `roles.verifier_agent`, `roles.clarifier`, `roles.s1_judge`). In
  0.4.18 it was refused there at load (`… cannot judge`, L4-CFG-006); that error now lists `claude-code, codex,
  opencode, kiro-cli, fake`, and `scripts/yolo_preflight.py` checks the same list.
- The vendor of a `kiro-cli` profile with a pinned model is the maker of that model (`claude-` anthropic, `gpt-` and
  `o<digit>` openai, `gemini-` google, `deepseek-` deepseek, `glm-` zhipu, `minimax-` minimax, `qwen` alibaba, `kimi-`
  moonshot). A profile whose `vendor:` contradicts its model no longer loads: `vendor contradicts the model: <model> is
  made by <vendor>`. Fix: delete `vendor:` (for example `vendor: amazon` on a Claude model) or set the maker.
  `vendor: unknown` makes no claim and loads (the maker counts). A model of no known family keeps its declared vendor. The rule is not applied to opencode in this change.
- `auto` is routed, so its `vendor:` is ignored: a profile with no model, or `model: auto`, counts with every vendor Kiro
  may route it to. A Kiro judge on `auto` is not independent of a Claude, GLM or MiniMax implementer (fix: pin a model
  whose maker the implementer does not share, or use a judge of another adapter). Two `auto` sides, or an `auto` judge
  and a profile of no known vendor, are never independent (fix: pin one).
- Under `verifier.independence: different_model`, model ids are compared after folding a `.` between digits to `-`
  (`claude-sonnet-4.5` is `claude-sonnet-4-5`).
- Every `kiro-cli` run names a model. An implementer with `options.agent` and no model now runs `--model auto`, which
  overrides the model in that agent file (fix: name the model in the profile).
- The hello of every `kiro-cli` profile, implementers included, runs the tool-less judge agent in a private `KIRO_HOME`,
  so it does not start the user's MCP servers. That hello passes `--v2` and `--model auto`, measured on kiro-cli
  2.32.0 only: recommend `min_version: 2.32.0` on every `kiro-cli` profile, implementers included. The `auth` step of an `auto` profile lists the models (it passes whatever
  the listing says).
- A continuation is dispatched for a unit handed back or left at the soft deadline even when another unit of the
  run exits 11, 12 or 13. When it is dispatched, the plan's own next-run start of the same run is not sent: one dispatch
  per run. A run in which no step started dispatches nothing and says so. On GitLab the continuation is now a pipeline
  on the base, and none is started while one waits. Each continuation is one more run of a delivery plan, so a plan's
  `limits.runs` is reached sooner (`limit_runs`; `l4 yolo resume --extend-runs N`) (L4-IMP-070).
- Failed attempts of a task count across runs: `implementer.max_task_attempts` and `implementer.escalate_after`
  read the task's `task.attempt_failed` since its last commit, retry, resume or restart, so a run that hands back and
  continues does not give a task fresh attempts. The attempt number continues after the highest attempt of the phase
  (L4-IMP-075).
- In GitHub Actions, on a copy of the workflow that is not the base's, `l4 doctor --ci` stops before the configuration
  and its checks, prints the pin warning and exits 0 (before, it could exit 2 on a configuration key its older harness
  does not know) (L4-IMP-072).
- The GitHub Release of each version starts with that version's CHANGELOG section, above the source commit, the
  release commit and the checks. A tag whose version has no dated section (`## X.Y.Z (YYYY-MM-DD)`) is refused before
  anything is pushed (L4-ACT-006).

### Fixed
- A default `kiro-cli` profile passes its probe on a GitHub-hosted runner without configuration. Its `/usage` call (the
  `quota` step) and its model listing (the `auth` step) took 23 to 30 s, over the 20 s `availability.probe_step_timeout`
  (LIVE-001 failed). The adapter now declares a floor of 90 s for those two calls, used as the longer of the step
  timeout and the floor and still capped by `availability.probe_timeout` (default 60 s, so 60 s unless it is raised)
  (L4-AVL-012). Every probe step records `step_ms`; a step of a second or more shows its time in `l4 probe`, in
  `availability.selected` (`probes.<profile>.step_ms`) and in the doctor LIVE-001 line.
- A failed `kiro-cli` hello says why: its reason is `kiro-cli reported runError (<stage>): <message>`, with the message
  redacted (no e-mail, ARN, account, profile, request or session id, no path, no token) and cut to 200 characters. On
  kiro-cli 2.32.0 a pinned model id the account does not have fails the prompt with a `runError` and writes no warning:
  the profile is skipped like any failed hello, and the standard-error check for a model Kiro could not set stays as a
  second guard (L4-KJD-007, L4-KJD-015).
- A Kiro run with an invalid or missing key or login (`bearer token … invalid`, `not logged in`, an exit 1 that asked
  for `kiro-cli login`) is an `auth` failure: the profile cools and the next profile of the chain takes the call. It was
  a failed attempt.
- `/usage` that answers `Invalid token` fails the quota step as `auth`, not as `quota_unrecognised`.
- A run with a known job timeout is no longer killed by the CI timeout in the middle of an agent step, which left
  an open run with no end and no continuation (L4-IMP-012, L4-IMP-068).
- `l4 yolo status` no longer says `nothing: CI advances the plan at each run` for an active plan that nothing will
  advance (L4-IMP-073).

## 0.4.18 (2026-10-20)

### Added
- `scripts/yolo_preflight.py` in the `l4` skill, beside `validate_plan.py`, standard library only. It checks a clean
  tree, HEAD equal to `origin/<base>`, the plan file and the unit folders on origin, the judge roles, the installed
  OpenCode major, `yolo.review.accept_by_agents` and the caller. It asks the harness for the admission and the review
  state, and prints exactly one `Next:` command (`--json` too) (L4-SKL-005).
- The skill's `references/operate.md` starts with "origin is what counts", a numbered runbook from the draft to an
  active plan, and an error table (message, cause, fix). The runbook allows at most two rounds of spec fixes per
  subject, then accepting what this stack cannot fix, and a person activates (L4-SKL-004).
- `plan.reviewed` records `target_rev` and `unit_revs`, the revisions the review read. A stale review's messages name
  the changed files from them (L4-YOLO-068).
- `l4 yolo accept PLAN --all --force --reason TEXT` lets a person accept every unit and batch of a plan with no model
  review, for a plan whose judge cannot run. It records `plan.admitted` (when needed) and `plan.force_accepted`, bound
  to the digests of the plan file and each unit, and calls no model. An agent is refused whatever `accept_by_agents`
  says, and no MCP tool runs it; `--withdraw` removes it. `l4 yolo activate` accepts it in place of a missing or stale review (the findings of a current review on a
  subject it did not override still refuse); the plan fold ignores one whose actor is not a person; status,
  findings, the report, the implementer's prompt and the PR body name it (L4-YOLO-057 to L4-YOLO-062).
- Doctor `SANDBOX-005` warns when a Go project's `gates.setup` has no `go mod download`: `GOMODCACHE` and the checksum cache are read-only in every other gate. The runbook and the adopt skill say to run `go mod download all && go mod verify` in setup and to point tool caches (`GOLANGCI_LINT_CACHE`) at `.l4-out/`.
- `sandbox.tool_paths` (read-only paths for both sandbox kinds, for a tool under the home that the harness does not
  find) and `sandbox.setup_paths` (read-only paths for the sandbox of a `gates.setup` command only, for a registry
  login such as `~/.npmrc`). An entry that is, holds or lies inside a login is a configuration error.
- Doctor `SANDBOX-003` plants canaries in the home, in another unit's step directory and in the lock directory and fails
  (exit 3) when either sandbox kind can read one. Doctor `SANDBOX-004` warns while `sandbox.setup_paths` is set.
- The ledger events `env.rebuilt` and `guard.notice`, and `guard.violation` with rule `environment`.
- `yolo.extend_by_agents` (default `false`) in `.l4/config.yaml` on the base branch lets an agent raise a plan's limits
  with `l4 yolo resume --extend-…`, like `yolo.review.accept_by_agents` does for `l4 yolo accept`. The event
  (`plan.extended`, or `plan.resumed` that extends) records the actor, its marker and whether the key allowed it
  (L4-YOLO-051).
- `l4 yolo status` lists the extensions of a plan (`extended: runs 90 -> 110 by <who> (person): <why>`).
- Kiro steering reaches the implementer as data. The harness reads `.kiro/steering/*.md` on the host and puts each file
  that applies under `# Project conventions` as an `<l4:data>` block, by its Kiro front matter: none or `always`
  (always), `fileMatch` (a pattern matches a path of the task or of the unit branch), `manual` (the task, the
  requirements or the design names it as `#<file>`) and `auto` (after the others, when the budget has room). An
  OpenSpec unit gets the `context` of `openspec/config.yaml` the same way, never its `rules`. The sandbox masks stay,
  and `~/.kiro/steering` is never read. `implementer.include_agents_md: true` adds the repository root's `AGENTS.md`
  as a convention (never `CLAUDE.md`).
- Nothing is cut silently any more. A source that is cut by the budget or not read (over 262,144 bytes, a symbolic link,
  a file that is not regular) is named under `# Not shown in full` with its path, the characters shown and the lines
  left out, and the run records `prompt.truncated`. `prompt.rendered` records `budget_tokens`, `budget_source` and the
  steering decisions.
- `l4 run --dry-run` prints per unit the budget, each steering decision and each cut. `l4 status --unit` prints the
  last `Prompt cut:` and `--json` has `prompt_cut`. Doctor SPEC-004 warns when the next task's prompt would cut a source.
- A profile may set `context_budget_tokens` for its own steps, for a small local model in a fallback chain.
- The step-9 judge gets each done task's whole block (detail bullets included) and is asked whether the diff does what
  each task's text says; `verifier.judge_context_budget_tokens` (48000) bounds its spec text in the implementer's
  priority order, and a spec file it did not see whole is named to it.
- A profile may state its model's window (`context_window`, or an opencode provider's `limit.context`): the whole prompt
  then stays within 60% of it (`budget_source: model_window`), and doctor SPEC-004 warns when a budget exceeds that
  or when the never-cut parts alone exceed it (`prompt.over_window` at run time).
- `docs/control-loop.md`, "How L4 runs: branches, events and the control loop": the one control loop, where each kind of state lives (base branch, unit branch, lock ref, plan ref, keep refs, PR), what starts a run, one run step by step, what a stop keeps, redoes or loses, what each local command writes, a worked recovery of a halted unit in a stopped plan, and swimlane diagrams. Linked from the README, the quickstart, the runbook, the delivery-plans page, the architecture page and the skill's operate reference.
- The skill reference `references/control-loop.md` (at most 900 words, for coding agents: rules, a table of what to run for each state, what a stop keeps, the MCP tools), a rule in `SKILL.md`, and one sentence in the MCP server instructions: continue a unit with `l4_retry` or `l4_plan_resume`, never by a checkout or push of its unit branch.
- `availability.probe_step_timeout` (default `20s`, capped by `probe_timeout`): the timeout of the `binary`, `auth` and
  `quota` steps of a probe. The `hello` keeps `probe_timeout` (L4-AVL-012).

### Fixed
- Every confirmation prompt of `l4 yolo accept` and `l4 yolo waive` goes to stderr and runs only on a terminal, so a
  pipe or a wrapper on stdout no longer hides it; without a terminal the command exits 2 and names `--yes`.
- A review reuses the judgement an acceptance is bound to when the ledger holds two judgements of one material, so the
  acceptance is not lost to a newer one. An acceptance that no longer holds says why in one line (`other material`, or
  `other findings of the same material`), a dry run with `--fresh` no longer says `the material changed` for the same
  material, an accepted subject is shown as accepted where its verdict is printed, and a `reused` verdict shows when it
  was judged (L4-YOLO-065, L4-YOLO-066).
- A replayed step (an accept of a held question) runs the post-step guards of an agent step: the scratch drop, the runner-configuration revert (`guard.violation`) and the environment check. A patch saved by 0.4.17 that loosens `[tool.pytest.ini_options]` no longer reaches the commit.
- The replay guard no longer re-applies the saved patch's version of a frozen test or a test-support file that the freeze (green, single) or the test-chore review put back.
- A step that weakens a pre-existing test is refused before a pre-satisfied hold is taken: a person is never asked to accept it.
- A hold on a spec file the judge could not read whole is bound to the content of that file, and its question names `verifier.judge_context_budget_tokens` and the file instead of the wording of a diff hold.
- A unit whose started run ends with exit 3 (`gates.setup` failed, no usable sandbox) no longer makes the plan dispatch
  a run every minute until `max_runs`: the plan stops with the new reason `setup_failed`, which names the gate and its log
  and ends with `l4 yolo resume`.
- `support_at_base` restores a link original by its real path through the confined helpers (a committed directory link re-pointed during the block no longer makes the harness create an entry outside the work tree), checks each restored link's target, and counts two plan paths that resolve to one file once.
- A test that replaced a source directory with a link to a directory outside the repository made the harness write
  there when it restored files after the test run (the zero-value runs, the run at the red code, the reports). Every file
  operation of the harness after agent code ran now refuses a link on its path, removes the link and writes nothing
  through it. The unit halts with the code `planted_link` and the ledger names each link and where it pointed. A guard
  that used to crash on such a replaced directory (`git rm` without `-r`) can no longer crash a run.
- A step can no longer pass a gate by editing the configuration the gate reads. Before, a green step that added
  `ignore_errors = True` to `mypy.ini`, or a red step that added `ignore = ["ALL"]` to `[tool.ruff]` or `addopts =
  "-p plugin"` to the pytest section of `pyproject.toml`, kept the change and had it committed. `tdd.gate_config_globs`
  now takes effect.
- The folders the sandbox masks (`.hermes`, `.kiro/hooks`, `.kiro/prompts`, and now `.kiro/skills`) are protected paths:
  what a step or a test run wrote there used to be committed.
- Code an agent wrote can no longer read the runner user's files. The agent and gate sandboxes showed the real home, so
  a test written by an agent could read `~/.git-credentials`, `~/.netrc`, `~/.ssh/id_*`, `~/.config/gh/hosts.yml` or
  `~/.docker/config.json` (proved under bubblewrap 0.8.0). Both sandbox kinds now start from an empty home and an
  empty runner cache and see only the tools, the step's own directories and the caches.
- A file written into `.venv` or `node_modules` can no longer decide a verdict. A green step that wrote only a `.pth`
  file into site-packages passed with the production code still a stub, and the verifier ran on that environment too:
  no guard looked there, `git clean` and `uv sync --frozen` kept the file. The harness now rebuilds an environment that
  a step or a gate changed, and gates that do not build it see it read-only.
- Two projects with a unit of the same name on one runner no longer share directories. The step directories, the
  `uv`, `pip` and `npm` caches, the excludes file and the unpublished run files are keyed by the repository key, so one
  project's unpublished run file is never pushed into the other's lock ref.
- A unit's OpenCode provider key file and credential-loader file are no longer readable from another unit's sandbox,
  are created in 0700 directories, and one left by a killed run is removed before the unit runs again.
- The login lock files and the unit lock files are no longer readable inside the sandboxes.
- A package cache can no longer carry a plant into a rebuilt environment. A file an agent step or a gate wrote into the
  unit's `uv` cache (`zz_marker.pth` in `archive-v0/<id>/`) came back in every environment rebuilt from it. The per-unit
  caches are now read-only except for `gates.setup`, every step and gate works in a private scratch cache that is
  discarded, and the verifier builds from caches of its own, emptied at the start of each round.
- A symlink in a `PATH` directory, or a shim into a project's `node_modules`, can no longer expose the files next to its
  target: the sandbox binds the target file or the package, and skips any tool path that is or lies inside a login or
  a known secret location (`~/.config/gh`, `~/.aws`, ...).
- The outcome record a pytest gate keeps could be emptied by a conftest that reached the plugin through `sys.modules`.
  The plugin now opens the record when it is imported and keeps the descriptor out of reach; a pytest report with test
  cases and an empty or missing record fails with `the test report was altered (no outcome record)`; a failed row of a
  phase wins over a later passed one; and the content scan flags references to `l4_trace`, `_OUTCOME`,
  `L4_OUTCOME_FILE`, `xmlpath`, `sys.modules` lookups of `l4` and assignments to `.exitstatus` / `.xmlpath`.
  Only those exact names count (a fixture called `xmlpath` or a constant `_OUTCOMES` is fine), `verifier.test_awareness_allow`
  lists the match instead of blocking it, the record sits outside the gate's temp directory under a random name, and a
  record the plugin created but left empty fails the gate even when a wrapper (`make test`) ran pytest.
- A red step that weakened, rewrote or shadowed a test that already existed (a second `def` of its name, a helper, a
  constant, a fixture or an autouse fixture it uses in its file) used to be committed and judged green. It now fails its
  attempt with `red changed tests that existed before this step: <path>::<name> (<why>)`, nothing is committed, and the
  retry prompt says what to do. A `[test-infra]` task and the stale tests of a reopened task are exempt
  (L4-IMP-045..048).
- Step 1 never saw a weakened pre-existing test: a unit whose test went from `== 3.75` to `is not None` and whose code
  then returned a wrong value passed. It now compares each test that exists at the base per test on the AST, by file and
  qualified name, and a harness commit that changes or deletes one is the blocker `a pre-existing test was changed` or
  `a pre-existing test was deleted`; a later red commit that changes a test an earlier step wrote is a blocker too.
  People's changes and the ones a `[test-infra]` task, a `task.unfrozen` or a `tests.superseded` event allows are listed
  in `verification.md` (L4-VER-030..032).
- A deleted test was hidden when any other changed test file defined a test of the same name, whatever its body, and a
  person's deletion was not listed either. A test now counts as moved only when the same definition appears under a new
  file or name (L4-IMP-047, L4-VER-030, L4-VER-031).
- Audit tests ran with the unit's own `conftest.py` in place, so an autouse fixture could make the audit of broken code
  pass. Audit tests, their zero-value run and a generated UI test's head run now use the unit's test-support files at
  their base versions (the amended entry below widens this to every test file for the audit); the Audit table of
  `verification.md` has a `Support` column, and `verify.audit` and `verify.generated` carry `support`
  (L4-VER-033..036).
- Step 1 now also blocks a test-support file that patches code the unit changed in module-level code or an autouse
  fixture (it used to check only the files a task opened); a fixture a test requests by name is listed (L4-VER-037).
- Step 1 now runs the base's tests on the unit's code: the test gate runs at head with every test and support file the
  unit added or changed at its base version (added ones set aside), and a test that passed at the base must still pass.
  A weakened helper module, a weakened or hooked conftest, a swap through `__code__` or `globals()`, a production module
  that imports only with the unit's conftest, and a weakened Go or TypeScript test (any language with a JUnit report)
  now fail step 1 with `a pre-existing test fails on the unit's code` or `a pre-existing test no longer runs on the
  unit's code`; the integrity table has the row `pre-existing tests still pass`. A test a `tests.superseded` event, a
  `task.unfrozen`, a `[test-infra]` task or only people's commits cover is listed (L4-VER-038).
- The comparison of a pre-existing test now sees statements that are not plain definitions (attribute assignments,
  `globals()`, `setattr`, a class attribute), inherited tests, real locals, normalised docstrings and moves that keep the
  closure; the content scan reads helper modules under the test globs and flags `pytest_pyfunc_call`, a plain
  `pytest_runtest_call` or `pytest_runtest_setup`, and an assignment to `.obj` or `.runtest` (L4-IMP-045..049,
  L4-VER-039).
- The audit runs without any of the unit's test or support files and collects only the audit file; it never falls back
  to them, holds a criterion whose production module does not import, and keeps the writer's collection retry. A
  generated UI test's head run keeps app data the unit added under `fixtures/` and no longer crashes when the server
  does not start without the unit's runner support (L4-VER-033..035).
- Step 1 scans the unit's production diff: a line that names `.l4-out`, a configured report path, an `L4_*` or `PYTEST_*`
  variable is the blocker `production code reacts to the test run` (code that behaves differently while the verifier runs);
  `"pytest" in sys.modules`, importing pytest, `atexit.register` and a `sys.argv` check for pytest are listed for the
  judge in `verification.md`. A support file that only people changed, a `[test-infra]` task changed or a `task.unfrozen`
  frees stays at head for the run of the base's tests, listed (L4-VER-038, L4-VER-039).
- The audit file is written under the directory the test command collects (a command narrowed to `tests/unit` used to
  leave it uncollected and the criterion held); a test command that never collects it is a minor rejection naming the
  command. A generated UI test's head run reverts a helper named like a test module and no longer falls back to the
  unit's support files: a server that does not start without them holds the criterion (L4-VER-033..035).
- New config key `verifier.test_awareness_allow` (list of production path globs, default empty): a match of the test-awareness
  blocker in a file under one of them is listed for the judge with its glob instead of blocking. It is read from the base
  branch's `.l4/config.yaml`, never from the unit, and `l4 doctor` shows it (CFG-010) (L4-VER-039).
- Every pytest gate run is cross-checked: the harness's plugin records what pytest judged for each test outside the
  worktree, and a JUnit report that disagrees (a pass the record does not hold, a failure removed) fails the gate with
  `the test report was altered` and the test ids; a conftest or helper with `atexit.register`, `os._exit`, a
  session-end hook that writes a file, or a name of the report path is a content-scan hit (L4-IMP-006 (8), L4-VER-039).
- The audit file is written next to the unit's own test files (an option value such as `--ignore tests/legacy` or `--tb
  short` no longer picks the directory), confirmed by a `--collect-only` run when the unit has no test file there
  (L4-VER-033).
- A `[test-infra]` or `[config]` tag in a fix unit's or follow-up unit's task exempts nothing, and brackets in
  model-written finding text become parentheses before they reach a task (L4-IMP-006).
- The test-awareness blocker reads Python with the AST: comments and docstrings are ignored, only reads of `L4_*` or
  `PYTEST_*` variables and names of `.l4-out` or the report path (with word boundaries) block (L4-VER-039).
- A delivery plan with `merge: auto` no longer merges a unit commit that nobody verified. The merge lands the hand-off
  commit H that the hand-off recorded (`pr.ready{head}`), pinned to its sha, and never the branch tip. Any commit after
  H sends the unit back to verification, whatever author, committer or `L4-Run` trailer it claims: before, a commit that
  copied the bot's identity and trailer after the review was squash-merged unseen, and a forged second hand-off commit
  became H (L4-ARC-008, L4-YOLO-040). The archive merge has the same rule: it lands only the archive head that
  `archive.opened{head}` recorded (the harness's own push); a branch head that is not the recorded one, or an archive
  with no recorded head, is not merged and `archive.failed` names the reason (a person merges the archive PR).
- A plan no longer merges a unit whose repository CI is red. A red CI that the sweep recorded on H is dispatched for
  verification before any merge, and the merge itself waits while the CI on H is running, is red and not yet recorded,
  or cannot be read, with a `merge_not_ready` detail that says why (L4-YOLO-041, L4-YOLO-042).
- On GitHub, a failed job is no longer hidden behind a passing job of the same name in another workflow. A check run is
  one job of one workflow (and event), a re-run replaces its earlier attempt, and a job red on H is pre-existing only
  when the same workflow's job is red on the base (L4-CI-010, L4-CI-011).
- A hand-off commit whose only check run is the harness's own skipped `l4` job is reported `not_run`, not green
  (L4-CI-012).
- A merge no longer treats CI that is not there yet, or a job that did not pass, as green. A cancelled job, an
  `action_required` check (a person must act) and a stale run, a failed commit status, a workflow run still queued or in
  progress, an unfinished GitLab pipeline and a required check that H has not reported are all read: cancelled or held
  jobs block the merge with "re-run it" and open no fix round (a cancelled push run whose pull_request twin finished
  does not block), a required check that never reports blocks it whatever `yolo.merge.require_ci` says, and the
  others are red or running. "No CI" is final only ten minutes after the hand-off, unless the repository has no
  workflow but `l4.yml`, requires no check and shows no status on H (L4-CI-013, L4-CI-014, L4-CI-015). Only the
  harness's own job (`l4` of `l4.yml`) is ignored, no job named `l4` in general. A CI read of a hand-off commit with one
  workflow makes about 7 API calls, three workflows that run on both `push` and `pull_request` about 17, and more when the
  base head is read too (not the hundred or more of before): the jobs of `l4.yml` runs and the base head are read only
  when needed.
- The recorded hand-off commit H is read from the unit's lock ref only, never from a `pr.ready` in the branch tree.
  Anyone who can push the lock ref can still forge `pr.ready{head}`: that residual is accepted, and closing it needs
  signed harness commits or a ref only the harness can write.
- A PR that a person merged at another head while the plan held H is recorded with the head that was merged.
- A diff over 120000 characters no longer holds the unit every round. The judge now reads it in parts: whole files,
  ordered so that a test sits next to the code it is named after, at most 8 parts of at most 120000 characters, one judge
  call each, and the replies are merged into one verdict (a `fail` of any part wins, then a `pass`). A diff within the
  cap keeps its one prompt. The prompt template is `judge@11` (`judge@10` added the parts); `verdict.json` lists `judge_parts` and `verification.md`
  says `judged in N parts` (L4-VER-041, L4-VER-042).
- The judge's diff leaves out the harness's bookkeeping, named once: every `.l4/` file, `.serena/memories/harness/**`, and
  the `verification.md`, `questions.md` and `feedback.md` of each unit folder of the family (L4-VER-040). Lock files
  (`uv.lock`, `poetry.lock`, `Pipfile.lock`, `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `go.sum`, `Cargo.lock`,
  `composer.lock`, `Gemfile.lock`) are shown as one line each (path, old and new size, lines added and removed) and never
  hold the unit (L4-VER-045).
- What the judge still cannot see (one file longer than one part, a diff that needs more than 8 parts) is a hold
  `judge view: …` of its own kind. Its question says what `accept` and `reject` mean and asks for no `WHEN … THEN …`. A
  rejected one is a human finding no fix task is derived from: the unit escalates with `judge_view_rejected`, and
  `l4 status`, the refusal of `l4 run --unit`, the sticky note and a plan stopped on the unit name the way out (split the
  change and `l4 restart`, or `--replace` with an accept and `l4 retry`). Before, a reject with a `WHEN … THEN …` made a
  fix unit that could not shrink the diff, and the same hold came back every round (L4-VER-043, L4-VER-044,
  L4-YOLO-055).
- After `l4 questions answer`, `l4 yolo resume` no longer refuses a plan whose answer is pushed and not yet read, and
  `l4 yolo status` says what happens: while a question is open, how to answer and that the plan continues by itself at
  the run that reads the answer; once the answer is pushed, that the next run reads it and how to start it now. The
  wait line shows the live reason, not the stale `open: Q-…` detail. The plan step, the resume and the status decide with
  one rule (L4-YOLO-052, L4-YOLO-053, L4-YOLO-054).
- Requirements and the criteria text no longer disappear behind a long `design.md` (a Kiro unit whose design was 125,492
  characters lost its `requirements.md` to the budget).
- A spec file over 262,144 bytes was dropped from the implementer's and the judge's prompt without a word; it is now read
  up to the limit and named, and the judge holds the round.
- A Kiro leaf's cited criteria were not required in red: a red step that tested one of `_Requirements: 1.1, 1.2_` passed,
  and the no-new-test path ticked such a leaf without proving the other. Red now fails with a reason that names the
  criterion and the line; a criterion that an earlier red already proved needs no copy (review finding implementer-5).
- Red no longer counts a criterion as proved by an earlier test that was merely re-tagged (the proof is per criterion
  and test, in a file only appended to), accepts new tests and fixtures in an existing test file (a constant computed by a call at import is refused; compute it in the test or use a new file), and accepts a step that
  reports every cited id. Hostile steering (deep YAML, huge or complex patterns, forged names) and unsafe capability directory names
  are named and left out; `l4 status` shows the latest prompt's cut; the clarifier charges its line numbers.
- A fix unit's `_Requirements:_` links resolved against the whole family, so the parent's own `Req 2.1` and the fix
  item `2.1` both counted; they resolve against the fix unit's own items.
- PRQ-11 accepted `opencode v2.0.32` as at least 1.18.34 (`sort -V` ranks the digit first); it now needs major 1.
- A hello that OpenCode 2 rejected (`Unrecognized flag: --pure` or `--dir`, exit 1) was classed `transient`, so the
  profile looked unavailable with no named cause. It is now `unsupported_version`, is never cached, and a run that ends
  the same way has a detail beginning `unsupported_version:` (L4-OCG-003).
- `l4 doctor --fix` kept an OpenCode 2 `opencode` that met the profile's `min_version`.
- A probe no longer hangs on a helper that holds its output. `run_process` reads until the child has exited plus a
  2 s grace, then kills the group, and never waits on a pipe that a process outside the group holds (an OpenCode v2
  daemon started by `auth list` did this) (L4-AVL-012).
- A probe step that times out names the CLI, the seconds, the step, the likely cause and `l4 doctor`, as `transient`:
  `opencode did not answer within 20 s (auth step); an OpenCode v2 daemon or a login prompt can cause this: run l4
  doctor`. The hello that timed out no longer says only `timeout`. `l4 doctor` readiness shows the text.
- An agent run ends when an escaped helper holds its output: `ProcRunner` joins its readers with a bound and logs that
  the raw events end there.

### Changed
- `l4 yolo review PLAN --worktree --record` fetches and records only when HEAD is `origin/<base>`: commit, push, then
  `--record`. HEAD ahead, behind or diverged is refused before any judge call, with both short shas, the counts, the
  paths and the command (`git push origin HEAD:<base>` or the pull). A unit whose branch on origin holds another spec is
  refused too. The last line names `l4 yolo findings` or the person's `l4 yolo activate` (L4-YOLO-069).
- A stale review names what differs: `activate: the review of <plan> is stale against origin/<base> (<sha>):`, one line
  per cause and a `Fix:` line. The causes are the review prompt, the plan file's digests, each changed unit's digests
  (where it is read, and its changed files), a subject not judged, and unpushed commits. `l4 yolo status` shows the
  same lines (`--json`: `review.stale`), and `l4 yolo review` prints them before it asks CI. A plan file that is only
  in HEAD is named with the push. The `inputs_changed` stop details name the frozen and the current digests
  (L4-YOLO-068).
- `l4 yolo review PLAN` and `--local` print a `warning:` when HEAD is ahead of `origin/<base>` and the unpushed commits
  change the plan file or a unit folder: CI reviews origin, not your commits (L4-YOLO-070).
- **Breaking:** an adapter profile that cannot judge in `roles.judges`, `roles.verifier_agent`, `roles.clarifier` or
  `roles.s1_judge` is a configuration error at load. An adapter that can judge is `claude-code`, `codex`, `opencode` or
  `fake`; one that cannot is, for example, `kiro-cli`. The error says the profile `cannot judge`, names the role and the
  allowlist. Before, such a profile was skipped at selection. Remove it from the role: kiro-cli becomes a judge in
  0.4.19. Backend profiles are not affected (L4-CFG-006).
- A person's `--yes` replaces the typed plan id in `l4 yolo accept`, `l4 yolo accept --all --force` and
  `l4 yolo waive`; the findings are still printed, and `plan.accepted`, `plan.finding_waived` and `plan.force_accepted`
  record `confirmed: typed` or `confirmed: --yes` (L4-YOLO-063).
- Upgrade note: reading the CI of a hand-off commit (merge-safety, `yolo.merge.require_ci`) needs more of the forge token
  than the pushes did. On GitHub a fine-grained token needs checks, actions and commit statuses READ on top of contents
  and pull requests write (the workflow's own `GITHUB_TOKEN` gets them from the generated `permissions`). Without them the
  read fails closed and the merge waits with a `merge_not_ready` detail. Add them before `l4 upgrade --harness-ref v0.4.18`.
- A hold about a spec file the judge did not see or saw only in part (`the spec file …: the judge saw only …`) is a hold on the judge's view like the ones about the diff: rejecting it stops the unit with `judge_view_rejected` and never makes a fix unit.
- Gate configuration and runner configuration now have exact definitions (the gate files at any depth, the gate and runner
  sections of `pyproject.toml`, `setup.cfg`, `tox.ini` and `package.json`, and the scripts the gate commands run). After
  every agent step, and after every gate run, a change to them is put back to the step's base unless the task has a
  `[config]` or `[test-infra]` tag or a person's answer names the file (`task.config_opened`). The whole file goes back, so
  a dependency added in the same file must be written again. A red or green step may still add a pytest marker. Runner
  configuration is never changed in green. The verifier's step 1 checks the same rule on the commits.
- A step that leaves a symbolic link which points outside the worktree (an absolute target or a `..` escape) fails its
  attempt before the commit, in red, green and fix chores, unless the base held the same link.
- New default gate globs: `pyrightconfig.json`, `pylintrc`, `.eslintignore`, `.prettierrc*`, `.prettierignore`,
  `biome.json`, `biome.jsonc`; `.coveragerc` is runner configuration. The new key `tdd.extra_gate_config_globs` adds
  globs without restating the defaults.
- Per-unit directories under `$L4_CACHE` carry the repository key (`units/<key>/<fw>/<name>`). Caches start empty once
  after the upgrade (a new `uv` cache gets the project's seed copy); the old `units/<fw>/<name>` directories can be
  deleted by hand. A run file of the earlier `pending-unpublished` layout is published by the repository it records (its key, or the
  project path of its CI link); any other, a local run included, is kept and named in one warning.
- A project environment (`.venv`, `node_modules`) that an agent step or a gate changed is removed and built again by the
  next `gates.setup`; the verifier builds its own. A project without `gates.setup` therefore builds its environment in
  every gate: set `gates.setup`. A test gate that writes into `node_modules` other than `.cache` and `.vite` fails
  read-only: move that command to `gates.setup`. Every agent step and every gate but `gates.setup` starts from an empty
  package cache (read-only shared cache plus a scratch), so a test gate that needs a download setup did not make fails
  under `gates.network: none`: move the download to `gates.setup`. The verifier downloads once per round. A dependency upgrade without a lock-file change is a notice, not a
  violation, when a dependency manifest changed in the same step.
- A plan merge waits for the repository's CI on H when it is running, red or unreadable. The new key
  `yolo.merge.require_ci` (default `false`) decides only whether a hand-off commit that no CI ran on waits too. With
  the default it is merged, after waiting up to ten minutes for a CI that may still be created (at once in a
  repository that can start none), and `unit.merged` records `ci: not_run`; a warning goes to the plan report and to a
  note on the merged PR or MR. A PR a person merged at another head records `ci: unknown`. A GitHub repository whose hand-off is pushed with the workflow's `GITHUB_TOKEN`
  (which starts no runs) that wants its CI to gate the merge gives the push a token that starts runs, such as a GitHub
  App, and sets `yolo.merge.require_ci: true`. A job red on H and on the base does not block: `unit.merged` records
  `ci: preexisting` and the job names.
- GitHub job names in `ci.failed` and `ci.preexisting` are `<workflow file> / <job>` (`tests.yml / build`).
- On GitLab, a hand-off commit with no pipeline job is `ci_not_run`; it was `ci_green`.
- A person's accept of a `judge view:` hold is bound to the head content of every file the hold covers and to the full list of
  files the judge did not see (the hold's text names five): it is void, and the hold asked again, when that content changes. The
  question lists every unseen file (L4-VER-046). The file list of a part prompt is capped at 200 files (then
  `+K more files: see verification.md`, which lists them all) and the diff is read with one `git diff` (L4-VER-047). A test is
  packed with the code it imports, a part that shows the code judges its criterion, and a part that cannot see a test cannot
  call it inadequate. A lock file is a lock file only when its old and new names both are, and its line shows the changed lines
  that touch a source field and the hosts they name (L4-VER-045).
- The key `yolo.extend_by_agents` (and `yolo.review.accept_by_agents`) is read from the plan's own target branch, and only when the plan file there is the one the plan recorded; an agent that names
  another base branch in its configuration has no key. `--extend-cost` must be finite. `l4 yolo status` lists the extensions the plan's
  fold applied, follows the unit's answer step for an invalid, dismissed or draft answer, and describes a unit as answered only when an
  answer is recorded (L4-YOLO-056). A rejected judge-view hold beside another unconvertible reject names both ways out.
- `l4 yolo resume PLAN --reason TEXT --extend-…` on an **active** plan raises the limit and records `plan.extended`; it
  resumes nothing and starts no run. Before, it was refused until the plan stopped. Without an `--extend-…` the refusal
  names the four options, and an extension that changes no limit is refused (L4-YOLO-050).
- Every `--extend-…` of `l4 yolo resume` is a person's decision: an agent is refused, with the command a person runs,
  unless `yolo.extend_by_agents` is true on the base branch. Before, the rule was only written in the docs
  (L4-YOLO-051).
- Every implementer prompt carries each criterion's full text and the task's whole block from `tasks.md` (the enclosing
  headings, the parent tasks' lines, the detail bullets and the `_Requirements:_` line), never cut. The rest of the
  budget is filled in a fixed order by whole sections: conventions (at most half), the requirements narrative, the
  design and the proposal, the sections the task names first.
- `implementer.context_budget_tokens` rises from 24000 to 32000.
- The clarifier's documents are chosen by the same builder, order and cut list (`clarifier@5`).
- Step 1's declared scope reads a Kiro unit's `requirements.md` and `bugfix.md`.
- Templates `contract@12` (conventions, the cut list), `red@11` (every listed criterion needs a new test or an earlier
  proof) and `judge@11` (the cut-list rule, the done-tasks block; it also holds the diff in parts of `judge@10`).
- An `opencode` whose `--version` is not major 1 is refused by name where the harness reads a version, whether or not
  the profile sets `min_version`: the probe's `binary` step, doctor `ENV-004`, doctor `LIVE-005` (now an error, never
  the `unrecorded version` warning) and `prereqs.sh` PRQ-11. The reason reads `opencode 2.0.32 is OpenCode v2; this
  profile runs v1 (opencode-ai 1.x): install opencode-ai@1.18.34 (l4 doctor --fix installs it user-locally); OpenCode 2 support comes in a later L4 release`. The supported major follows the pinned `OPENCODE_VERSION` (L4-OCG-001, -002).
- `l4 doctor --fix` treats an `opencode` of another major as not satisfied and installs the pinned `opencode-ai` into
  the harness npm prefix, linked as `~/.local/bin/opencode`. It never replaces a regular file at that path (the action
  fails and names the path and the manual command), and it fails when the `opencode` the harness path resolves is still
  the wrong major. The Node, `laya-serve` and codex links are unchanged (L4-OCG-004).
- `prereqs.sh` PRQ-15 runs `opencode models` only when PRQ-11 passes, because OpenCode 2's `models` starts a shared
  daemon that outlives the call.

## 0.4.17 (2026-10-19)

### Fixed
- An `accept` of a held check now binds to the step the person looked at (L4-IMP-065). On 0.4.16 a task held with a `harness`
  question discarded the step's changes, and an accept covered a criterion only while its candidate tests were among the test
  ids the question named, so the next agent wrote the test again under another name and a new question was raised for the same
  criterion, without end. Now the held step is saved first, as `.l4/held/<task>-<check>.patch` in the unit folder (binary-safe,
  with the agent's result beside it), committed with the questions commit, and `question.raised` records `patch_sha256`. The
  question's Context shows the source of each named test, redacted and cut to 40 lines. The next run after an `accept` starts no
  agent for that step: it checks the digest, applies the patch, runs the guards, gates and checks an agent's changes get, records
  `held.replayed` and counts the criteria for those tests. A missing patch, a different digest or a patch that does not apply gives
  a new question that says why, never a pass. `retry` deletes the patch and runs an agent with the note; a replay deletes it in the
  step's commit; a restarted unit or a reopened task drops it. The question lists every changed path and shows the redacted diff of every changed path; a cut says that the cut lines are replayed
  too and names the patch path. The accept takes effect only through the replay of exactly that saved step: once the replay is used up
  (it failed a gate or the check refuted a criterion; a failed replay counts as an attempt), it covers nothing, and a later step
  that meets the same inconclusive check is held again with a new question. A reopened task drops every earlier accept. Every question of this release records `saved: true|false`; only a question without it (0.4.16) keeps the old rule by test id. A step is always saved whole, whatever its size; a question is bounded (400 characters a line, 48 KB a Context and less as `questions.md` fills, then the path list and the patch path). A replay commits exactly its saved patch: the tree is snapshotted before its first gate and every non-ignored path is put back to it after each gate run (`held.replay_restored`); links are never followed (every read, unlink, rmdir, mkdir and file creation goes through the file descriptor of the path's folder, reached with `O_NOFOLLOW`, checked again right before each action), a link is trusted only where the saved patch creates it, modes are restored, and a link planted by the setup or by a gate fails the step (`held.replay_unsafe`). The set of trusted links comes from a temporary git index, not from patch text, and a link is trusted with the target the patch gives it (a re-pointed link fails the step); the expected state is the step base plus the saved patch (from a temporary index), not the tree after setup, so a tracked file that setup or a gate changed is put back and a build hook of the patch cannot add content to the commit; the commit of a replay stages only the expected paths (not `git add -A`), and the guard lists untracked files by the base's and the work tree's ignore rules together; files are compared by size and a chunked blob hash and streamed in from git, so a large fixture of the patch replays and no file is read whole; the work tree folder is checked to be the same folder before every restore and git call; a gate-written huge file is no longer read to be removed; a folder a gate made unreadable fails the step cleanly; a cache mount at or above `<cache>/worktrees` is refused. `Next:` offers only `retry` for a question whose step was not saved. A refused replay (patch missing, digest differs, does not apply) raises a question that offers only `retry`. A replay that finds a path outside its saved patch after the gates fails as an attempt. A later agent
  attempt gets a notice (data block `accepted tests`) that the earlier accept was for the earlier step only. All four held checks (`pre_satisfied`, `vacuity`, `at_red`, `tests`) do this. A
  question raised by 0.4.16 has no patch and keeps the old behaviour.
- The runbook and the skill no longer say that `l4 questions answer`, `accept`, `l4 retry` and `l4 restart` always start a run:
  they do when the forge token is set, and otherwise print `start a run with: …`.

## 0.4.16 (2026-10-18)

### Fixed
- `yolo.hold` holds a unit that a delivery plan only excludes: listing a held unit in a plan's `exclude` released it, so after
  a plan review the held units ran. Only the units a plan plans (a batch's units) follow the plan; an excluded unit that
  `yolo.hold` matches stays `held by yolo.hold`, and `l4 plan` / `l4 yolo status` say so. The coverage check still counts a held
  unit as covered (L4-ADO-011).
- Review of the zero-value work (L4-IMP-060..062): a missing test is the agent's (no proof) when the innermost frame of
  its own files is not an import of other code (also a `conftest.py` the unit added that stops pytest);
  the keep loop reads module-level calls of pre-existing test-support modules, and a test that failed by assertion in any
  pass counts as a proof.
- The GitHub setup action installs the harness again with `source: action` (the default for a published
  harness): since 0.4.14 the build reads the l4 skill from `plugins/l4/skills/l4` (L4-SKL-003), which the action's
  build copy and cache key left out, so every run failed with "Forced include not found". The copy and the key now
  hold the skill, and a test keeps them in step with every `force-include` of pyproject.toml.
- A check that could not run no longer fails the agent. The pre-satisfied zero-value run, the base run, run (b), the
  `test-at-red` run, the verifier's audit and the extra-proof runs are judged against the real run, per test: a test
  that failed by assertion is a proof, one that passed or failed another way is no proof, and one the run did not run
  (no report, no test collected, its module failed to import only there, skipped only there) is inconclusive. In 0.4.14
  and 0.4.15 a decorator factory zeroed to `None` broke the import of the modules that apply it, pytest stopped with
  45 collection errors and ran 0 tests, and the message said "its tests still pass"; the unit halted after nine red
  attempts on four profiles (L4-IMP-060).
- Zeroing keeps what imports need: a public function annotated to return a callable or a class keeps its body when a
  module of the varied set applies it at import time (a decorator or decorator factory, or a module-level or
  class-level call), and when a run leaves a candidate inconclusive the functions its tracebacks call, and those called
  by the module-level statements of the production module whose import failed, are kept real and the run is made again,
  at most twice (`zero.kept` records them). Every variant run goes on past collection errors
  (`--continue-on-collection-errors`), so the base run of a unit that adds a module no longer stops at the first test
  file that imports it (L4-IMP-061).
- In a zero-value run a test the unit's own files made unrunnable (it skips itself on the zero answer, its test or
  support file raises at collection, a `parametrize` over a production answer loses its id) is no proof, so the
  attempt fails as on 0.4.15; only a production module that failed to import leaves a criterion inconclusive and holds
  the task. An agent can no longer turn "not discriminating" into a held task, and an `accept` covers only the tests
  the question named.
- Every excerpt in the committed ledger, `questions.md` and the console is redacted before it is cut, so no prefix of a
  secret survives.
- A failing assertion in the setup of a fixture counts as a failure on the zero values when the fixture is in a test
  or support file the unit added or changed; in a file that was there before it is inconclusive (L4-IMP-002).
- The verifier no longer rejects an audit test, or ignores a person's or a chore's test, because a zero-value run
  could not run it: the audit records it `inconclusive` (no finding, listed in `verification.md`), and an extra test
  says why it has no proof (L4-VER-050).
- The console no longer says `(expected: zero values must fail)` for a zero-value run that ran no test, and the
  artefacts line says `not uploaded` when `ci.upload_artifacts` is false in GitHub Actions (L4-IMP-064).

### Changed
- An inconclusive check holds the task: no attempt is used, no profile escalates, the step's changes are discarded,
  one question of the new kind `harness` is raised and the unit waits in `awaiting_human` (exit 11); a delivery plan
  waits without chaining runs. A person answers `accept: <why>` (the next run counts those criteria on the evidence of
  the real run when the check is inconclusive again; audited as `via: human_override`) or `retry: <note>` (the check
  runs again, for example after an L4 upgrade). A criterion a run shows to be not discriminating still fails the
  attempt, and the message lists the inconclusive ones apart. The discrimination check of a test chore that cannot
  decide holds the chore the same way. An agent may answer only where
  `clarifier.answer_by_agents` is true on the base branch; its answer is recorded `by: agent` and labelled
  `agent_override`, never as a person's (L4-IMP-063, L4-IMP-017, L4-QMD-004, L4-QMD-009).
- A criterion whose every test imports no project module and reads a dependency's version (a version pin) is no longer
  passed: it is inconclusive ("its tests import no project module: the zero-value check cannot judge them"), the task is
  held with a `harness` question, and nothing is recorded `via: not_applicable` any more (old ledgers are still read). A
  person's `accept` counts it (L4-IMP-062).
- `gate.finished` and `task.attempt_failed` carry an `excerpt` of at most 600 characters (the `E` lines and the deepest
  repository location, redacted) in the committed ledger, for a repository that uploads no job artifacts
  (L4-IMP-064).
- `l4 status --unit`, `l4 plan` and the waiting detail of a plan name a harness question: `Cause:` quotes the check's
  reason, `Next:` the two answers, and the plan says `harness check inconclusive: Q-NNN` (L4-OPS-006).

## 0.4.15 (2026-10-18)

### Added
- `l4 mcp serve [--repo PATH]...` makes L4 an MCP server over stdio (newline-delimited JSON-RPC 2.0, protocol revision
  2025-11-25; no new runtime dependency). Its tools manage delivery plans and debug units: `l4_status`, `l4_doctor`,
  `l4_plan_status`, `l4_plan_check`, `l4_plan_findings`, `l4_plan_report`, `l4_questions`, `l4_question`,
  `l4_unit_events`, `l4_verification` (read) and `l4_plan_draft`, `l4_plan_review`, `l4_question_answer`, `l4_retry`,
  `l4_plan_resume` (write). Each tool runs the `l4` command it names in a repository the instance was started for, as an
  agent (`AI_AGENT=l4-mcp`), so every CLI rule for agents holds; `l4 yolo activate`, `cancel` and `l4 run` are not
  tools. Several `--repo` give every tool a required `repo` argument; a repository that was not named is refused.
- `l4 mcp install --client claude-code|cursor|vscode|kiro|codex|opencode [--project] [--repo PATH] [--name NAME]
  [--dry-run]` writes the client's documented MCP configuration (one entry per repository, other servers kept, atomic,
  an unparseable file refused).
- `l4 status --unit U --events [--type T] [--last N] [--json]` and `--verification` read a unit's ledger events and
  `verification.md`. The tool `l4_plan_check` runs 0.4.14's `l4 yolo check PLAN --worktree` before the push.

### Fixed
- `l4 resume` and `l4 yolo resume` refuse `--extend-cost` of `nan` or `inf` with a usage error (exit 2); the MCP tools
  refuse a non-finite number the same way.
- `l4 mcp serve`: a timed-out or cancelled call now kills its whole process group after the grace period, also when
  the command itself exited and a descendant ignored SIGTERM; the protocol is read and written as UTF-8 under any
  locale (a non-UTF-8 locale used to kill the server on `tools/list`); progress notifications carry a rising
  `progress` value; `initialize` and each tool name the served repositories, so a client with several instances can
  tell them apart.
- `l4 mcp install --client claude-code` prints the `claude mcp add` line shell-quoted, so a path with a space works.
- `l4 mcp serve`: the tool commands run with `python -P`, so a file of the served repository named `yaml.py`,
  `click.py` or an `l4` package can no longer run in place of a dependency; a stopped call's process group keeps its
  grace period after the command exited, so a descendant can clean up before it is killed; no progress notification
  follows the response of its call.
- `l4 mcp install --project` writes what each client can use: Cursor `--repo ${workspaceFolder}` (Cursor documents no
  working directory for servers), VS Code, OpenCode, Codex and Claude Code `l4 mcp serve` (they start in the project
  or set `CLAUDE_PROJECT_DIR`); Kiro, which documents neither, is refused with a hint to use the user scope. A Codex
  entry lists `forge.token_env` of `.l4/config.yaml` (else the default `L4_FORGE_TOKEN`) under `env_vars`, because Codex
  starts a server with an allowlisted environment. An existing user-scope entry whose `--repo` is a client variable is
  refused like another repository's entry instead of being rewritten. The quickstart says a project file serves a
  worktree only for a session started inside it (Claude Code desktop worktree sessions use the main checkout's file).

## 0.4.14 (2026-10-17)

### Added
- `l4 yolo check <plan> --worktree` checks a delivery plan before the push, with the installed `l4`. It reads the plan
  files and the units from the working tree, runs the admission of `l4 yolo check`, and adds the checks across all plan
  files that only `scripts/validate_plan.py` ran (`uncovered`, `covered_twice`). It prints the findings, the order and the
  budget warnings, writes nothing, and exits 0 or 2. `l4 yolo draft` and `l4 yolo review --worktree` name it in their
  hints. The script stays for an agent or a CI step without the harness, and a parity test holds the two together.
- `l4 skills install` puts the `l4` skill into the skill folder of every coding agent, with no network and no clone:
  the skill now ships inside the wheel and the sdist. User scope writes `~/.claude/skills/l4`, `~/.agents/skills/l4`
  (and `~/.codex/skills/l4` when that folder exists), `~/.config/opencode/skills/l4` and `~/.kiro/skills/l4`;
  `--project` writes `.claude/`, `.agents/`, `.opencode/` and `.kiro/` `skills/l4` in the repository. `--agent auto`
  (the default) takes the agents whose home folder or CLI (`claude`, `codex`, `opencode`, `kiro-cli`) is present. Each
  copy has a manifest `.l4-skill.json`; a rerun updates an untouched copy, refuses an edited one (exit 2) unless
  `--force`, and never follows a symbolic link. `--dry-run` prints the plan. `l4 skills status` lists the copies with
  version, `current` or `old`, and edited files. Doctor row SKL-003 warns about an installed skill older than `l4`, and
  `l4 init` names the command (L4-SKL-003).

### Fixed
- A delivery plan no longer starts a run every minute for a unit that waits for capacity. A plan step that dispatches a
  unit in `waiting_capacity` starts no next run, and a unit that parks twice for the same profiles with none cooling
  (an expired provider key, a missing binary) stops the plan with `capacity_needs_fix`; the stop names the profiles,
  their failures and the fix, and `l4 yolo resume` goes on after it (L4-YOLO-035). A park with a cooling profile still
  waits for its reset.

## 0.4.13 (2026-10-17)

### Added
- `ci.toolchains` provides the toolchains a polyglot repository's gates need. The generated GitHub workflow (action,
  copy and plain forms) sets up Go, Node and pnpm before L4 with `actions/setup-go`, `actions/setup-node` and
  `pnpm/action-setup`, pinned by commit sha and with their own dependency caches off; each entry takes exactly one of
  `version` and `version_file` (pnpm: `version`). Without it the workflow is unchanged. New default caches `gobuild`
  (`GOCACHE`) and `pnpm` (the store directory); with a `go` entry the gates run with `GOTOOLCHAIN=local` and
  `GOFLAGS=-mod=readonly`. Doctor row TOOL-001 names a gate command whose first word is not on the gate PATH (a warning
  in `l4 doctor --adoption`, an error in a CI run), and `l4 init` proposes `ci.toolchains` from `go.work`/`go.mod`,
  `.nvmrc`/`engines.node` and `packageManager: pnpm@X`.

### Fixed
- A repository that adopts L4 with finished Kiro specs is no longer stopped by them. Doctor's SPEC-002 was an error and
  intake rejected the unit for history L4 never runs: a done leaf without a `_Requirements:_` line, or with a
  reference no criterion has, a `## Task Dependency Graph` whose block is a mermaid diagram, a whole-requirement
  reference such as `_Requirements: 1_`, `## Requirement N` with `### Acceptance Criteria` (one heading level higher
  than `### Requirement N` with `#### Acceptance Criteria`), and a number inside a word such as `ADR-0014.8` or
  `AC3`. Now a done leaf's missing or unresolvable link and a graph block that is not JSON are warnings (the tasks run
  in document order); a pending leaf keeps its rule, and a JSON graph that is wrong stays an error. A reference `N`
  resolves when requirement `N` has criteria, both heading levels are read, and a number counts as a reference only
  when it stands alone. SPEC-004 lists the pending leaves only.

## 0.4.12 (2026-10-17)

### Changed
- A delivery plan with `merge: auto` now squash-merges each verified unit by default, and deletes the merged branches.
  Behaviour change on upgrade: the harness used to push the unit head to the target as a fast-forward and never deleted a
  branch. Now it calls the forge's merge, pinned to the verified head, so the target gets one commit (the PR title and
  ` (#<pr>)`, with the trailers `L4-Unit`, `L4-Verified-Head` and `L4-Run`; `unit.merged` records `merge_commit`,
  `method` and `raced`), and, once the forge shows the PR merged, it keeps the verified head at
  `refs/l4/merged/<framework>/<name>` and deletes the unit branch under a lease (and the archive branch after the archive
  merge). A branch a person pushed to after the merge stays (`unit.branch_kept`); a plan step also cleans up to five
  branches of earlier merges. The lock ref is not deleted. The forge's token must be allowed to merge PRs; a forge that
  refuses a squash stops the plan with `merge_refused`. To keep the old behaviour set `yolo.merge.method: fast-forward`
  and `yolo.merge.delete_branches: false`. The evidence link in a PR body now names the head commit, not the branch
  (L4-YOLO-008, L4-YOLO-032, L4-YOLO-033).
- The archive step no longer builds a worktree for a merged unit whose folder is already archived on the base.
- The hand-off refreshes the PR body's evidence link only while the body is still the harness's own; a body a person
  edited stays.

## 0.4.11 (2026-10-17)

### Fixed
- A test of a context manager can prove its criterion. The zero-value run rewrote a `@contextmanager` function (or its
  red stub) to `return None`, so every `with` raised a `TypeError` before the test body ran, and no test could fail by
  assertion: on a consumer repository a unit halted after five red attempts on `search_phase`. Now a context manager's
  zero value enters and yields the zero value of what it yields, a generator yields nothing, and a function annotated
  to return a context manager or an iterator returns a null one. The `vacuous` message says how to test a context
  manager.
- A test gate reads every report it lists. With several reports in `gates.test.reports`, the harness read only the
  first one that existed, so the tests of the other suites were invisible to red, green and the verifier (on a
  consumer repository with three Python projects, the 423 tests of two suites). Now every listed report must exist (else
  `report missing: <report>`), and the reports are merged; a test in two reports keeps its worse result.

- Doctor's CI-003 no longer lists a job that a `typecheck` or `build` gate mirrors: verification runs those gates in
  every round, but the row counted them only when a `yolo.profiles` entry named them. It also ignores `uv run`'s
  `--directory`, `--project`, `--package`, `--frozen`, `--locked` and `--no-sync` options when it compares commands.

### Changed
- The adoption docs and the `l4 init` note name the public harness first: the plain `--action` form needs no deploy
  key for any repository. The copy form and the deploy key are for a private harness.

## 0.4.10 (2026-10-17)

### Fixed
- A finding a person rejects with a `WHEN … THEN …` becomes a fix task even when it cites no criterion and the parent
  has several requirements. The fix-unit planner put a scenario under the cited criterion's requirement, else the
  parent's only one, and dropped it otherwise, so the unit escalated with `no finding of this round can be converted
  into a fix task`. That is the path the 0.4.8 runbook gives for `task <key> is ticked as already satisfied, but its
  text is not done`: on a consumer repository, the reject of that finding stopped the delivery plan. Now the scenario
  goes under an ADDED requirement of its own, `<finding title> — finding <id>`, in the parent's first capability by
  name, as a feedback item's does. A judge's spec-gap suggestion that no person asked for is unchanged.

## 0.4.9 (2026-10-17)

### Fixed
- The zero-value run finds the modules a test imports in a workspace layout. It looked each import up under the
  repository root and `src/` only, so in a uv workspace, where each member keeps its code under
  `packages/<name>/src/<namespace>/<name>/`, it found no module to vary and refused every test of existing behaviour
  with `no project source module is imported by those tests`. On a consumer repository, four of six units lost a red
  attempt to it, and one unit then proved a scenario that pins existing behaviour with tests of the new path. Now an
  import is also looked up under every directory named `src` and every directory with a `pyproject.toml`,
  `setup.py` or `setup.cfg` (and its `src`), from git's tracked and not-ignored files. The head stubs of run (b),
  the verifier's audit sampling and the proof of tests people wrote use the same lookup.

## 0.4.8 (2026-10-17)

### Fixed
- A task that an earlier task already did no longer writes a copy of tests that exist. A red step had to add new test
  functions even when an earlier task of the unit had written and proved the tests of every criterion it cites, so
  each such task added a near-copy of them (on a consumer repository, four classes that assert one contract, and about
  4,400 test lines across four units). Now a red step may add no test and report `criteria_ids` and
  `tdd_exemption: {reason: "already_satisfied by <task>"}`. The passing tests that already trace those criteria are
  then its proof, confirmed as new tests are (the earlier red, the zero-value run, the base run), and the task is
  committed `already satisfied` with no test change.
- A test fixture shaped like a token no longer halts the unit. A red step wrote a redaction test whose fixture spells
  a token whole, as the file's existing tests do; the push scan refused the push and the unit halted with `secret in
  the outgoing commits`, and the plan stopped. Now each implementer step's changes are read for secrets before any
  gate or commit: a hit discards the attempt and tells the agent to build such a value from parts at run time
  (`"mk_" + "agent_" + "A" * 24`), and the next attempt gets that advice. The contract template says the same up
  front. The push scan stays as the last net.
- The confirmation by an earlier red holds for tests in a class. It turned `pkg.tests.test_x.TestY::test_z` into the
  path `pkg/tests/test_x/TestY.py`, found no file, and confirmed nothing, so every such criterion took the zero-value
  run and the base run.

### Added
- The judge checks each task ticked as already satisfied against its own text. The prompt lists those tasks with the
  criteria and tests that proved them, and the reply answers `satisfied: [{task, holds, evidence}]`. A `holds: false`
  is a major finding (`task <key> is ticked as already satisfied, but its text is not done`) that goes to a person.
  Before, a task whose criteria an earlier step satisfied was ticked although its own work (a README line) was never
  done, and the round passed. The judge prompt is `judge@9`.
- The red prompt says when to add no test, and that `already_satisfied` needs the task's own text to be true. The
  skill's `spec.md` has a **tasks** rule: put a behaviour's tests in the task that implements it, write no gate-only
  task, and give a document edit a check that a red step can test.

## 0.4.7 (2026-10-17)

### Fixed
- A unit whose verification passed because a person accepted a hold is merged again by a `merge: auto` plan. The hold
  (for example `the diff is longer than 120000 characters`) was accepted, and the next round reused the judged steps
  without calling the judge. That round did not carry the judge's answers to the plan's accepted review findings, so
  the merge guard found none and the plan waited with `accepted_finding_open`, every finding `no answer recorded`. A
  resumed round now records the answers of the round it reuses again, with `reused_from`.
- A judge reply that leaves out an accepted finding or a feedback item it was asked about is asked once more. The
  second call names the missing ids. A valid second reply is the verdict (`reply: retried`). A broken second reply
  keeps the first verdict. Before, the reply counted as valid, the finding was `not answered`, and a feedback item
  counted as not addressed.

### Added
- `l4 yolo waive PLAN F-id --reason TEXT [--withdraw] [--yes] [--no-run]`: a person (or an agent, when
  `yolo.review.accept_by_agents` is true on the base branch) waives an accepted finding of an active plan on record.
  The merge guard counts it as answered and the harness merges the unit itself, through its guarded merge. The
  report and `l4 yolo status` show the waiver.
- For a plan that waits with `accepted_finding_open`, `l4 yolo status` names the ways out in its `Next:` line:
  `l4 retry` when the verifier gave no answer, `l4 feedback add` when the code must change, `l4 yolo waive` when the
  finding needs no handling.

## 0.4.6 (2026-10-17)

### Fixed
- A unit no longer loops on a rejected verification hold after the fix was given as feedback. The round raised a hold
  (for example `the diff is longer than 120000 characters`), a person rejected it in prose with no `WHEN … THEN …`, and
  the round escalated with `no finding of this round can be converted into a fix task`. The person then gave the fix
  with `l4 feedback`, the feedback fix unit finished and round 4 judged every item fixed, but the old reject stayed in
  force: the same hold came back, the verdict was FAIL, and a retry repeated it. Now a feedback-only fix unit consumes
  the rejects its round could not convert: the verifier drops a reject recorded before a `fix.spawned` with
  `feedback_only: true` (so a ledger written by 0.4.5 and older needs no repair), and new ledgers list those
  questions in `fix.spawned.consumed` and mark the event `lists_unconverted: true`, so that only the listed rejects end.
  A hold that is raised again is asked as a new question on the fixed code.
- The escalation `no_convertible_finding` now names its way out. `l4 status --unit`, `l4 status --json`, the refusal of
  `l4 run --unit` and the note on the merge request say that a retry alone repeats the same verdict, and to give the fix
  as feedback (`l4 feedback add --unit U --kind behaviour --when … --then … --text …`, then the git lines) before
  `l4 retry`. Other causes keep their text. The runbook has the procedure (7.3.1).
- `l4 questions answer Q-NNN --unit U --text TEXT --replace` replaces the answer of an answered verdict question on
  purpose. Before, the command refused it and the only way was a hand edit that nothing explained. The new answer is
  recorded as a new verdict (the latest per target wins); the previous answer stays in a comment under it, and the
  commit says `(answer replaced)`. Without `--replace` the refusal stays and its `Fix:` line names the flag. A
  clarification answer is still changed by hand (L4-QMD-006).
- `l4 yolo status` no longer shows a dependency where there is none. A plan runs one unit at a time, and a unit with no
  prerequisite left said `waits for <unit> (not integrated)`, the same words as a real dependency. It now says
  `waits for its turn: <unit> runs first (one unit at a time)`.

## 0.4.5 (2026-10-16)

### Added
- A heartbeat line while an agent step runs: `task <k> <phase> attempt <n>: <profile> working 6m, 14 tool calls, last
  activity 20s ago`, with `, <m> tool calls open for <t>` while a tool call is open. The key `implementer.heartbeat`
  sets the interval (default `2m`, minimum `30s`, `0` turns it off). The line holds counts and times only, and no text
  of the agent.
- `implementer.idle_timeout` (default `10m`, minimum `1m`, `0` turns it off) and the ledger event `agent.idle`: an agent
  that prints nothing for that time and has no open tool call is stopped, and the attempt fails with a reason that names
  the key.
- `l4 status` has the column `LAST`. `l4 status --unit` has the lines `Last activity:` and `Open run:` (with the CI link
  of the run), and `--json` has `last_activity` and `open_run`. `l4 yolo status` shows `last activity` and `open run`
  of the current unit. The event `run.started` records the CI link, as `run.started.ci_url`.
- The red gate line `red: <n> new tests fail, as intended`, and `gate.finished.red_new_failing`.
- The job summary of GitHub Actions lists each finished task.
- The runbook procedure 4.6 `Is the job stuck?`.

### Changed
- An idle agent gets SIGINT and 5 seconds before the kill, and is not stopped while a claude-code, codex or kiro-cli
  tool call is open.
- The failure reasons of an idle stop and of the step time limit (30 minutes) name the cause.
- The step start line is at INFO.
- The new keys need the 0.4.5 pin before the config edit (the schema is strict).

### Fixed
- A person's answer can now open a pre-existing test that the task must change. Before, the test path freeze put such
  a test back in every green attempt, even after a person accepted the harness's own question that named the file and
  the edit (the unit halted on `green broke existing tests`, and no `task.unfrozen` was recorded). Now an answer
  (`accepted` or `answered`, on the same conditions as for a red test or a support file) that names a tracked test file
  that the red step did not touch opens it for that task's green. It is recorded in `task.unfrozen`, listed in the green
  prompt, accepted by the verifier, and `l4 questions show` says that an accept unfreezes the pre-existing test. The
  red tests of the task and the ignore files stay frozen.
- A rejected verification hold of a kind the harness cannot derive a task from (for example `the diff is longer than
  120000 characters`) whose reason ends with a sentence `WHEN … THEN …` is now a behaviour finding with a fix task, not
  an escalation (`no finding of this round can be converted into a fix task`). Without the scenario the unit still
  escalates, and the question of such a hold no longer promises a fix unit: it asks the reason to end with the scenario.
  Scope and coverage holds are unchanged.
- `l4 feedback add --unit U` no longer needs the unit's own branch checked out: a detached HEAD, or a local branch of
  another name, at the head of `origin/<unit branch>` is accepted (L4's worktree cache may hold the branch). The command
  says which branch the feedback goes to and prints `git push origin HEAD:<unit branch>`. From any other commit the
  refusal says how to get there, including `git switch --detach origin/<unit branch>` and `git worktree list`.

## 0.4.4 (2026-10-16)

### Added
- Escalation along `roles.implementer`: `implementer.escalate_after` (default 2, `0` turns it off). After that many
  failed attempts of one task phase on one profile, the next usable profile of the chain takes the phase, in a fresh
  session, with the reasons of the earlier failures. The harness records `implementer.escalated` or
  `implementer.escalation_skipped`. A move never parks a unit and never takes a profile that would leave no independent
  judge. `task.attempt_failed` and `breaker.tripped` name the profiles; the halt detail lists them.
- The retry note: the `--reason` of `l4 retry` and `l4 resume` on a unit halted on `max_task_attempts` reaches the
  implementer of that task, as a capped and redacted data block, until the task is done. `prompt.rendered` records
  `retry_note`. `l4 status --unit` prints a `Retry note:` line.
- Doctor check CFG-009 (warn): an escalation that cannot act (`escalate_after` not below `max_task_attempts`, or two
  profiles with the same adapter and model).
- New progress lines for the escalation, the failed attempt with its profile, the halt with its profiles and the retry
  note.
- The runbook and the skill (`adopt.md`, `operate.md`) teach the cheap-first chain and the note.
- `agent.finished` records `context_peak_tokens` (OpenCode, Claude Code: the largest input of one call, cache
  included) or `context_peak_percent` (Kiro CLI), and the progress line ends with `, context peak <n>k tokens` or
  `, context peak <p>%`. Codex and a command give none. `RunResult` has the new fields `last_message` and
  `result_problem`.
- The ledger event `result.normalized{task, phase, attempt, source, fixes}` and its progress line
  `L4 repaired the result (…)`. The event holds no text of the agent.

### Changed
- A chain of two or more profiles moves a failing task phase to the next profile by default. Each profile has its own
  attempts; the last one has `max_task_attempts`. Set `implementer.escalate_after: 0` for the old behaviour. The tasks
  of a fix unit do not move.
- The config key needs the 0.4.4 pin before the config edit (the schema is strict).
- The `# Output` section of a prompt-contract step (OpenCode, Kiro CLI, command) is the locked template `output@1`
  (`template_version` ends with `+output@1`). It asks for `status` and `summary` first, names `criteria_ids`,
  `suppressions` and `notes_for_verifier` as optional, shows a smaller schema and no longer asks for the fields that the
  harness derives (`phase`, `task_ids`, `files_changed`, `tests_added`). The prompt of Codex and Claude Code does not
  change.
- The harness repairs the result object of a step before it validates it (`result.normalized`): a missing `summary`, a
  `status` that is not allowed, a text over its limit, a malformed question, suppression or criterion id, and the
  fields that the harness derives. The harness never adds a question, never changes `blocked` and never adds a
  suppression. It can take the object from the last JSON object in the agent's final message, never from a file of the
  worktree.
- An attempt fails for its result only when the agent delivered no result object
  (`the agent's result is invalid: no result was delivered`). A `blocked` result with no question is not a failed
  attempt: it keeps raising one question made from its summary.
- The red check no longer reads the `tests_added` list of the agent. It uses the tests that the JUnit diff finds.

## 0.4.3 (2026-10-16)

### Fixed
- `l4 questions accept` and `answer` pushed the answer to the unit branch and relied on that push to start a run.
  GitHub runs a push with the workflow file of the pushed branch, which still pinned the old harness after the base had
  moved its pin: the pin guard (CFG-008) did no work and the unit did not resume. The push also started the
  repository's own CI on a unit that was in the middle of TDD, and its red tests left a misleading red check on the
  pull request. The commit now carries `[skip ci]` and the command starts a run on the base branch, as `l4 retry` does
  (`--no-run` skips it; a refused start prints how to start one by hand and exits 0).
- `l4 upgrade` now names the open unit branches on origin (from the remote-tracking refs it has, no network) whose own
  workflow copy pins another harness than the new one, and says that a push to one of them does no work and that runs
  start on the base.
- The runbook (7.1) and the skill say to start a run on the base after a hand-edited answer is pushed.
- A Python support file named in the heading of a task's section in `tasks.md` (for example `## 1. Root conftest.py`) now opens in green like one named in the task line, under the same trust check (an active plan or the base branch); a heading of another section, a glob or `../` opens nothing.

## 0.4.2 (2026-10-16)

### Added
- `l4 questions`: list the open questions of a unit, `show` one, `accept` the clarifier's suggestion or `answer` it
  with a text. The command edits `questions.md` on the unit branch, commits and pushes, which resumes the unit in CI.
  `--no-push` shows the change and writes nothing. An agent follows the same rule as `l4 yolo accept`
  (`clarifier.answer_by_agents`). Before, the command was listed in `l4 --help` but stopped with exit 2.
- A test-support file that the task's own reviewed text names (for example `` `conftest.py` ``) can be changed in the
  green step of that task. The file must keep its old statements, must not redefine a name and must not patch the
  code of the unit. The red tests of the task stay frozen. The run records `task.unfrozen{reason: "named_by_task"}`.
- A person's answer can unfreeze a named test-support file (never an ignore file).
- `l4 yolo findings --json` gives `accept_refusal {why, fix}` for a subject that cannot be accepted, and the text view
  prints `accept: not available: <why> (<fix>)`.

### Changed
- The green prompt template is version 5: it names the files of "Files this task names" and says how to change them.
- Every command and option that is not implemented says `(not yet implemented)` in `l4 --help` (`l4 unlock`,
  `l4 status --rebuild`, `l4 resume --extend-iterations`, `--extend-cost`, `l4 run --time-budget`,
  `l4 verify --dry-run`). Each one still exits 2. The runbook lists the same set.
- The `cache.seeded` ledger event records its digest as `digest` (it was `key`, which default secret scanners report
  as an API key in a consumer repository's archived ledgers). Readers accept both.
- The note of a blocked green question never offers an edit that the harness refuses.
- The text of a unit pull request and of an archive pull request says who merges it: a person, or the harness when the
  unit is in an active delivery plan with `merge: auto` (it said the harness never merges it).

### Fixed
- `validate_plan.py` read a comment after a key with a nested block (`hold:   # note`) as the key's value, so it
  ignored `yolo.hold` and reported the held units as uncovered.

## 0.4.1 (2026-10-16)

Review resolution and the lessons of the first adoption on a real consumer repository. This release added features
and changed the readiness review.

### Added
- `l4 yolo findings`: the findings of the latest review with a `Resolve:` line per criterion, and the criteria that come
  back (`persistent`).
- `l4 yolo review --worktree`: review the working tree before a push (dry by default; `--record` writes the review to
  the ledger and judges again everything the ledger does not hold).
- `l4 yolo accept` with conditions (two judged versions of the text, no blocking finding) and a reason that the
  implementer and the verifier receive; the merge guard keeps an accepted finding open until the verifier answers it.
- `yolo.review` budgets (`max_file_chars`, `max_folder_chars`, `max_dependency_chars`), `accept_after_rounds`,
  `accept_by_agents`; `yolo.hold` and `l4 init --hold-existing`.
- System One keys rendered into the workflow; Laya as the default System One (`l4 init --s1 laya|jev|none`).
- The pin guard: a run whose harness pin differs from the base branch's workflow does no work and warns.
- Doctor adoption checks; `validate_plan.py` uses the review's budgets and file set.

### Changed
- The readiness review judges only material it has not judged (the material key covers the text, the templates and
  the schema); minor-only findings count as READY; dependency material is shown spec first.
- The judge prompt is version 8. No `l4 eval --compare` baseline was made for it.
- Every material key changed, so each subject is judged once more after the upgrade.

## 0.4.0 (2026-10-15)

### Added
- Delivery plans (`l4 yolo`): plans of OpenSpec and Kiro units with dependencies, a readiness review by the judge in
  CI, activation by a person, a guarded fast-forward merge into an integration branch, `l4 yolo draft`, the plan
  validator and the plan skill reference.
- `OPENCODE_API_KEY` for OpenCode's own providers.
- The experience graph (manual `l4 kg` and `l4 lessons promote`).

### Changed
- Worktrees and unit locks are keyed by repository.

## 0.3.0 (2026-10-14)

### Added
- Operator commands: `l4 retry`, `l4 restart`, the causes shown in `l4 status`, `same_failure`, a spec push that
  re-enters the unit, Kiro reopen.
- The GitLab base branch; `l4 upgrade --action-repo`.

### Changed
- The repository is `OWNER/l4`.

## 0.2.1 (2026-10-13)

### Fixed
- Coverage survives a test that replaces `sqlite3.connect`.
- The GitHub workflow uploads `.l4-out`.
- Corrections in the runbook.

## 0.2.0 (2026-10-13)

### Added
- Human feedback (`l4 feedback`).
- The adoption kit: the harness as a GitHub setup action.
- The `l4` skill.
