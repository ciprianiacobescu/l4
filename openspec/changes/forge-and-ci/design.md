## Context

SPEC section 1 (INS), 11 (ARC; RACE-001 is owned by `state-vcs-locks`) and 16 (CI) define how the harness is adopted, how it talks to the forge and
how pipelines drive it. The reference environment is GitLab 17.5.2 CE at gitlab.example.com, project
`example-group/dummy-agentic` (id 118), runner #12 `l4-runner` (shell executor, tags `agentic, ai, opencode`,
`run_untagged: false`, [V] pipeline #2521 ran on runner #8 because its jobs had no tags). `CI_JOB_TOKEN` cannot push
before GitLab 18.4 [V], so every write uses a project access token (scopes `api`, `write_repository`).

Evidence labels follow SPEC section 0: [V] verified, [D] secondary source, [I] design decision, [U] unverified, must be
confirmed by a test or spike before relying on it.

Package: distribution `l4harness`, import package `l4`, console script `l4`.

## Goals

- One command adopts the harness: `uvx --from git+<url>@<sha> l4 init --ci gitlab`, review the diff, commit.
- Generated CI is boring: explicit tags, script files or one-line commands, no inline multi-line shell, no `: ` hazards.
- The forge layer is a small port with one conformance suite run against the fake, local, GitLab and GitHub clients.
- The archive lifecycle is deterministic and idempotent: every forge write is derived from `state.json`, so the
  sweeper can repair anything.
- M1 (walking skeleton) runs live on the dummy repository: GitLab forge, GitLab template, `l4 init`, post-merge
  archive MR.

## Non-Goals

- Auto-merge of code (`merge_policy: auto` is v1.1). The harness merges only its own archive PR, and only when
  `archive.auto_merge_archive_pr: true`.
- PR-comment commands (`/l4 ...`), a web dashboard, Spec Kit execution.
- Provisioning of runners (`runner-provisioning`), the lock protocol and FORGE-005/006 checks (`state-vcs-locks`),
  the orchestrator loop (`implementer-tdd-loop`).
- Changing forge settings (job timeout, protected branches): the harness only reads them and warns.

## Decisions

### D1. A shim `.l4/bin/l4` is the single way CI starts the harness

Generated YAML must call script files or one-line `l4 ...` commands. A tiny POSIX `sh` shim named `l4` lives in
`.l4/bin/` and each l4 job puts it first on `PATH` with one `before_script` line, so job scripts read exactly as the
SPEC patterns do (`l4 run --unit X || l4 ci map-exit $?`). The shim reads `harness.commit` from `.l4/config.yaml`
(the one pin, L4-INS-005) with `sed` on the canonical layout `init` writes, then prepends `$HOME/.local/bin` (runner-provisioning's user-local uv location, L4-PRV-004) to `PATH` and `exec uvx --from "git+$URL@$SHA" l4 "$@"`; when `uvx` is still not found it prints the one-time `install.sh` command of runner-provisioning and exits 3;
when `.l4/vendor/` exists it execs `uv run --project .l4/vendor l4 "$@"` instead. `URL` is baked at init time and may be
overridden by the CI variable `L4_HARNESS_URL`.
Alternatives: (a) inline `uvx` in each YAML script line (rejected: version pin duplicated in YAML, quoting hazards);
(b) a pre-installed global `l4` on the runner (rejected: breaks pinning, SCN-INS-08 needs zero-install);
(c) a Python bootstrap that parses YAML (rejected: needs the dependency it is trying to fetch).
This adds `.l4/bin/l4` to the file set of L4-INS-002 (see "SPEC deviations").

### D2. GitLab pipeline shape: include template, `.pre` detect job, dynamic child pipeline

`.l4/ci/l4.gitlab-ci.yml` (rendered by `l4 ci render --platform gitlab`) defines two jobs, both in the built-in stage
`.pre` so the repository's own `stages:` list can never exclude them [I]:
`l4-detect` (rules: skip when `$CI_COMMIT_MESSAGE =~ /\nL4-Run: /`, run on sources `push|web|api|trigger|schedule`;
script `<doctor line> && l4 plan --json $L4_PLAN_FLAGS > plan.json && l4 ci render-child --plan plan.json > child.yml`, where the doctor line is runner-provisioning's `l4.provision.runner.doctor_command(cfg, "gitlab")` (`l4 doctor --ci --fix` when `ci.self_provision` resolves true, else `l4 doctor --ci`), with a `rules: variables: {L4_PLAN_FLAGS: "--sweep"}` entry for the `schedule` source so the sweeper runs on schedules without a second script form; artifacts
`plan.json`, `child.yml`, `.l4-out/`, dotenv report `.l4-out/l4.env`) and `l4-run` (`needs: [l4-detect]`,
`trigger: {include: [{artifact: child.yml, job: l4-detect}], strategy: depend}`). `.gitlab-ci.yml` receives one
`include: - local: '.l4/ci/l4.gitlab-ci.yml'` entry. Child jobs (module `l4.ci.render.render_child`) are named
`l4-run-<fw>-<name>` with `stage: l4`, `tags: <ci.runner_tags literal list>`, `resource_group: l4-<fw>-<name>` (characters
outside `[A-Za-z0-9._-]` mapped to `-`, a short hash appended on collision) [I], `interruptible: false`,
`allow_failure: {exit_codes: [10, 11, 12]}`, `variables: {GIT_DEPTH: "0", L4_UNIT: "<id>"}`, `before_script` PATH line and
`script: [ "l4 run --unit <id> || l4 ci map-exit $?" ]`. Every rendered string is emitted through one YAML quoting helper
and the output is linted by `l4.ci.lint` (parse back with `yaml.safe_load`, assert each `script` item is a `str`, no
bare `: `, no multi-line items, tags present).
Alternatives: dynamic child pipeline without an include template (rejected: SCN-INS-01 requires an include);
`rules: changes` for detect (rejected, [V] always true on new branches); a CI/CD component only (components are GA since
17.0 but availability on 17.5 CE is [I], so the include form is primary and the component is optional, CI-001 part i).

### D3. `ci.runner_tags` rendered as literal lists

SPEC mentions `tags: $L4_RUNNER_TAGS`. GitLab expands variables in `tags` only as whole strings, so a list cannot be
expressed that way. The renderer writes the literal list from `ci.runner_tags` (default `[agentic]`). CI-002 compares the
rendered tags to the runner's tags when readable.

### D4. Forge port

`l4.forge.base` defines dataclasses `PullRequest(number, url, head_branch, base_branch, head_sha, title, draft, state
["open"|"merged"|"closed"], merge_commit_sha, labels: tuple[str,...], mergeable: bool|None, author)`,
`JobResult(name, status, pipeline_id, web_url)`, `Approval(user, head_sha)`, `ForgeCapabilities(...)`, errors
`ForgeError`, `ForgeAuthError`, `ForgeNotFound`, `ForgeRateLimited`, and the `Forge` Protocol:
`whoami`, `token_scopes`, `server_version`, `ensure_labels`, `find_pr(head_branch)`, `get_pr(number)`,
`list_prs(head_prefix, state)`, `create_pr(head, base, title, body, draft=True)`, `update_pr(number, title=None,
body=None, draft=None, state=None)`, `set_managed_labels(number, labels, prefix)`, `upsert_sticky_note(number, body)`,
`set_commit_status(sha, context, state, description, target_url=None)`, `list_pipeline_jobs(sha)`,
`user_can_write(login)`, `approvals(number)`, `dispatch_continuation(unit, ref)`, `merge_pr(number)` (called only by
the archive PR auto-merge path), `delete_branch(name)`. `make_forge(cfg, env, transport=None)` picks the class from
`forge.type` / `ci.platform` / the `origin` URL. Tests inject `httpx.MockTransport`, so no new dependency.
Alternatives: python-gitlab / PyGithub (rejected: NFR-004 limits runtime dependencies); `glab`/`gh` CLIs (rejected:
not guaranteed on the runner, output parsing).

### D5. GitLab REST v4 mapping (httpx, header `PRIVATE-TOKEN`)

| Port method | Request | Evidence |
|---|---|---|
| `whoami` | `GET /user` | [V] |
| `token_scopes` | `GET /personal_access_tokens/self` | [U] returns scopes for project access tokens on 17.5.2 |
| `server_version` | `GET /version` | [V] |
| `ensure_labels` | `GET /projects/:id/labels`, `POST /projects/:id/labels` (`name`, `color`) | [V]; plain `l4:phase` names allowed in CE [U] |
| `create_pr` | `POST /projects/:id/merge_requests` with title `Draft: <title>`, `source_branch`, `target_branch` | [V] draft by title prefix |
| `update_pr` ready | `PUT .../merge_requests/:iid` with title lacking the `Draft: ` prefix | [U] response `draft` flips to false |
| `set_managed_labels` | `PUT .../merge_requests/:iid` with `add_labels` / `remove_labels` | [V] avoids replacing foreign labels |
| `upsert_sticky_note` | `GET/POST/PUT .../merge_requests/:iid/notes` finding the marker `<!-- l4:sticky -->` | [V] |
| `set_commit_status` | `POST /projects/:id/statuses/:sha` (`state`, `name`=`l4/<unit>`, `description`) | [V]; states `pending|success|failed` |
| `list_pipeline_jobs` | `GET /projects/:id/pipelines?sha=:sha`, `GET /projects/:id/pipelines/:id/jobs` | [V] |
| `user_can_write` | `GET /projects/:id/members/all/:user_id` access_level >= 30 | [V] |
| `approvals` | `GET .../merge_requests/:iid/approvals` | [U] available in CE |
| `dispatch_continuation` | `POST /projects/:id/trigger/pipeline` (`token`, `ref`, `variables[L4_UNIT]`) | [V] |
| `merge_pr` | `PUT .../merge_requests/:iid/merge` | [V] |
Pagination follows `X-Next-Page`; 429 and 5xx retry up to 3 times with backoff honouring `Retry-After`; the token is
never logged (redaction list includes the variable named by `forge.token_env`).

### D6. Pushes: credential helper per command, credentials stripped from `origin`

`l4.forge.gitlab.git_auth_args(token_env)` returns the `-c credential.helper=...` arguments for a helper that echoes
`username=oauth2` and the password from the named environment variable at call time, so the secret is never in argv, a
remote URL or `.git/config`. `strip_remote_credentials(repo)` runs at the start of `doctor --ci` and `run` and does
`git remote set-url origin <url-without-credentials>` through the hardened git runner of `state-vcs-locks`. Checkpoint
pushes add `-o ci.skip`; hand-off and archive pushes add nothing. Alternatives: token in remote URL (rejected: SPEC 16.3
and L4-SEC-005); SSH deploy key (rejected: cannot create MRs, adds a second credential).

### D7. GitHub specifics

`GitHubForge` uses REST for PRs, labels, statuses and `workflow_dispatch`; marking a draft ready uses GraphQL
`markPullRequestReadyForReview` because the REST PATCH cannot clear `draft` [D]. The App installation token is minted by
`mint_installation_token(app_id, private_key, installation_id)`: an RS256 JWT signed by `openssl dgst -sha256 -sign`
(key written to a 0600 temp file, removed afterwards) then `POST /app/installations/:id/access_tokens`. No `cryptography`
or `PyJWT` dependency (NFR-004). Alternative: optional extra `[github-app]` with `cryptography` (kept as fallback if
spike [U-6] fails). Hand-off pushes use the minted token; checkpoints use `GITHUB_TOKEN`.

### D8. Continuation and idempotency

`l4.ci.continuation.dispatch(unit, next_iteration)`: (1) read the ledger; if `continuation.dispatched` for
`next_iteration` exists return `dispatched` without a call; (2) append `continuation.requested{iteration}` and commit with
trailer `L4-Iteration: <n>` (checkpoint, `[skip ci]`); (3) call `Forge.dispatch_continuation`; (4) append
`continuation.dispatched`, or `continuation.failed` on error. The result feeds `outcome.json.continuation`. The ref is the
base branch, because configuration is trusted from the base head (L4-CFG-004); the pipeline's `detect` job then plans the
unit like any other (level-triggered), `L4_UNIT` is informational.

### D9. Sweeper

`l4.ci.sweeper.Sweeper` implements simulation-harness's `l4.planner.SweepPort` (`run(plan, *, dry_run) -> list[Duty]`) and is
resolved lazily by `l4 plan --sweep`. Each duty is a separate function returning a `Duty` record with the planner's duty-kind
vocabulary (so `--detailed-exitcode` and dry-run can print them): `resume_waiting_capacity`, `resume_expired_lease`,
`detect_merged_or_closed_pr` (merged/closed/reopened, delegates to `archive.handle_merged` / `archive.handle_closed`; in M1
`handle_merged` is only "record `merged` through `lifecycle.transition` and call `PostMergeArchiver.open_archive_pr`" (tasks
1.33, 1.36), while WIP-branch and lock-ref cleanup and the closed/reopened paths are M2 tasks 2.51 and 2.53),
`refresh_moved_base` (delegates to `archive.refresh_on_base_move`), `honour_resume_label`, `rerun_intake`,
`repair_mirrors` (compares labels/status/body with `archive.render_*` of the folded state and writes only differences).

### D10. Archive module

`src/l4/archive.py` groups: pure renderers `render_pr_title`, `render_pr_body`, `labels_for(state)` (one `l4:<phase>` plus
`l4:needs-answers` / `l4:escalated` when applicable), `status_for(state)`; `PrMirror.sync(forge, state, *, notes=())`, the
single writer of labels, status, body and the one `<!-- l4:sticky -->` note (`notes` are extra sticky sections such as the
clarifier's `ClarifyOutcome.sticky_section`, so no other change writes forge labels or notes); `HandOff.commit(worktree, unit, run)` (collects `verification.md`, evidence index, folded
ledger; runs `SpecProvider.done_gate`; one commit without `[skip ci]`; push; mark ready); `RepoCi.evaluate(forge, head_sha,
base_sha) -> CiVerdict(new_failures, preexisting)`; `MergeDetector.classify(pr, repo) -> MergeOutcome(archived: bool)` using
`git ls-tree <merge_commit_sha> openspec/changes/<name>` (Kiro: ledger fold at that commit); `PostMergeArchiver`
(`pending_units`, `open_archive_pr`, `archive_pr_open()` for serialisation, branch `l4/archive/<fw>/<name>`, commit
`chore(<unit>): archive` with trailers, path allow-list check that only archive paths changed, `auto_merge` gate);
`ApprovalArchiver` (opt-in: `valid_approval(pr, state)`, `archive_on_approval`, `revert_archive`, `refresh_on_base_move`,
tag `l4/<fw>/<name>/verified-<round>-<short-sha>`); orchestrator hooks resolved lazily by implementer-tdd-loop's `HOOKS`:
`forge_hook(cfg, env) -> ForgePush(auth_args, checkpoint_args, handoff_args)` (D6 credential helper, `-o ci.skip` for
checkpoints, `strip_remote_credentials` applied once), `mirror_hook(services, unit, notes)` (= `PrMirror.sync`) and
`handoff_hook(services, unit)` (= `HandOff.commit`); `run_archive` is the `l4 archive` handler; `PushGuard.check(branch, kind)` (rejects pushes not allowed while ready,
L4-ARC-008 part b); `push_with_race_handling` (a thin wrapper that sends archive and hand-off pushes through `l4.vcs.locks.PushCoordinator` and
`l4.vcs.push.recover_from_human_push` of `state-vcs-locks`, which owns L4-RACE-001; it adds only the forge credential
arguments of D6 and returns `PushOutcome.replan_required` to the caller).
The post-merge archive commit is a normal commit (no `[skip ci]`) with an `L4-Run` trailer so l4 jobs skip it while the
repository CI runs on it. If an open archive MR becomes unmergeable it is closed with a note and rebuilt on the latest
base under a numbered branch (`.../<name>-2`); the harness never force-pushes.

### D11. `l4 init` flow

`plan_init(repo, opts) -> InitPlan` is pure (reads the tree, runs `git ls-remote` for the pin, never writes) and returns
`PlannedFile(path, content, mode, action in {create, extend, overwrite})`; `render_diff(plan)` produces unified diffs;
`apply_plan` writes atomically (temp file + rename) and only after every precondition passed, so a refusal leaves no
partial state. Ecosystem detection (`l4.init.ecosystem.detect_gates`) follows L4-GAT-003 markers and returns a
`GateProposal(test, setup, build, lint, typecheck, e2e, todo_keys)`; config is rendered from the bootstrap-core defaults
plus only the keys init sets (`harness`, `spec.frameworks`, `gates`, `forge.type`, `ci.platform`, `ci.runner_tags`) and
re-loaded through `load_config` before writing. The pin comes from `l4.__version__` -> tag `v<version>` ->
`git ls-remote <url> refs/tags/v<ver>^{} refs/tags/v<ver>` (peeled commit wins). `--vendor` fetches the pinned commit into a
temp clone, checks `HEAD == harness.commit`, copies tracked files (no `.git`) to `.l4/vendor/`.
Alternatives for the URL: `harness.url` config key (rejected: not in the SPEC schema; amendment would ripple into
bootstrap-core), so `L4_HARNESS_URL` at init time or the package's `Source` project-URL is baked into the shim.

### D12. Doctor checks

`checks_ci.py`: CI-001 (files present, header comment equals config pin, tag still resolves to commit), CI-002 (rendered
GitLab jobs carry `ci.runner_tags`; if the project's runner info is readable and `run_untagged: false` untagged jobs are an
error, if unreadable a warning that the live check decides), CI-003 (`resource_group` / `concurrency` present and not
cancelling), CI-004 (`GET /projects/:id` `build_timeout` vs `ci.time_budget`). `checks_forge.py`: FORGE-001 (token present,
scopes), FORGE-002 (`git push --dry-run` to `<prefix>doctor-probe`), FORGE-003 (labels, `--fix` creates them), FORGE-004
(server version, feature matrix). All tolerate `ci.platform: local`.

## [U] facts to settle first (test or spike before dependent work)

| # | Fact | Settled by |
|---|---|---|
| U-1 | `trigger:include:artifact` + `strategy: depend` on 17.5.2 CE propagates child `allow_failure: exit_codes` as a passed-with-warnings parent | task 1.18 (CI Lint API) then the live pipeline of `live-validation`; fallback: drop `strategy: depend` |
| U-2 | A trigger job in stage `.pre` with `needs: [l4-detect]` is accepted by 17.5.2 | task 1.18 (CI Lint API) |
| U-3 | `rules: if: '$CI_COMMIT_MESSAGE =~ /\nL4-Run: /'` matches a trailer in the full commit message | live pipeline on a commit with and without the trailer (`live-validation`, SCN-CI-13) |
| U-4 | `resource_group` accepts `l4-openspec-add-greeting` and rejects `:` | task 1.18 (CI Lint API) |
| U-5 | `GET /personal_access_tokens/self` works for project access tokens | task 1.9 (recorded fixture), then live |
| U-6 | `openssl` is present on GitHub-hosted and the reference runners for RS256 signing | task 2.11 and doctor FORGE-001 (GitHub) |
| U-7 | Draft toggling by `Draft: ` title prefix and `add_labels`/`remove_labels` behave on 17.5.2 | recorded fixtures in tasks 1.4-1.6, then live |
| U-8 | Project runner details (`run_untagged`) are readable with a project token | task 2.4; otherwise CI-002 falls back to a warning |
| U-9 | The MR approvals API is available in CE | task 2.5; otherwise `accept_forge_approval` is ignored with a doctor warning |
| U-10 | CI/CD components work on 17.5 CE | task 2.22 (FORGE-004 matrix); the component form is optional |

## Risks / Trade-offs

- The `.gitlab-ci.yml` edit is the only modification of an existing file by `init`; a repo with its own top-level
  `include:` gets a printed snippet and exit 2 rather than a text-level YAML rewrite (loss of comments/anchors is worse).
- Child-pipeline propagation of exit codes is [U-1]; if it fails the fallback is a single `l4-run` job per unit using
  `parallel:matrix` generated by `detect`, losing per-unit `resource_group` in the pipeline graph but keeping it in YAML.
- The shim parses YAML with `sed`; CI-001 verifies that `.l4/config.yaml` keeps the canonical `harness:` block layout.
- GitHub parity depends on a test repository (SPEC Q5 is open); GitHub code paths are covered by `MockTransport` contract
  tests and run live only in `live-validation` M2.
- Archive-on-approval has many paths (revert, refresh, voiding). It is opt-in, M2 and tested first on the fake forge.

## SPEC deviations and ambiguities resolved (to be amended in SPEC.md in this change, section 24.1 item 4)

1. Token variable: the task text names `L4_GITLAB_TOKEN`, SPEC section 3.2 and 16.3 name `L4_FORGE_TOKEN` (`forge.token_env`).
   Choice: follow the SPEC; the GitLab forge reads the variable named by `forge.token_env`.
2. File set: `.l4/bin/l4` and `.l4/ci/l4.gitlab-ci.yml` are CI caller files for L4-INS-002 (SPEC lists only "the CI caller file(s)").
3. `tags: $L4_RUNNER_TAGS` is rendered as literal tags from `ci.runner_tags` (D3).
4. Resource group names replace characters GitLab rejects (D2).
5. FORGE-005/006 and L4-RACE-001 belong to `state-vcs-locks` (implementation map: SPEC areas STA, LCK, RACE, WTR).
   Cross-change review (2026-10-03) removed the duplicate RACE-001 blocks and SCN-RACE-01..04 from this change; the
   equivalent scenarios are SCN-RACE-N1..N4 and SCN-IMP-22 in `state-vcs-locks`, and tasks 2.57/2.58 here only wire the
   archive paths to that implementation.
6. The harness repository URL is not in the SPEC schema (SPEC Q1 open); see D11.
7. The rendered detect line appends `$L4_PLAN_FLAGS`, empty except on the `schedule` source where it is `--sweep`; SPEC's
   line (SCN-CI-11) is exactly what runs on every non-schedule pipeline.
