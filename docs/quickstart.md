# Quickstart: adopt the harness in a project

One script, then a commit, a push and the forge and runner steps, on a project whose tests and lint are green at HEAD.

## 0. What you need

* A git repository with at least one commit and tests that pass at HEAD (and a committed `uv.lock` for a uv project).
* `git` >= 2.34 and `curl`. `uv` is installed by the script when it is missing (pinned, user-local).
* For CI: a GitLab project and a Maintainer token, or a GitHub repository where you can add a secret.
* A runner host you control, with sudo (section 3).

## 1. Clone and adopt

```bash
git clone https://github.com/ciprianiacobescu/l4.git ~/l4
cd /path/to/your-project
~/l4/scripts/adopt.sh
```

`adopt.sh [--repo DIR] [--ci gitlab|github] [--framework openspec|kiro] [--commit] [--no-install] [--no-gates] [--dry-run]`
prints one line per step, `[ADOPT-nn] STATUS title - detail`:

| Step | What it does |
|---|---|
| ADOPT-01 harness | the checkout the script lives in |
| ADOPT-02 git | git >= 2.34 |
| ADOPT-03 repository | the project, with at least one commit; warns about uncommitted changes (doctor checks HEAD only) |
| ADOPT-04 uv | finds or installs uv (`--no-install` fails instead and prints the installer command) |
| ADOPT-05 harness environment | `uv sync --frozen` of the harness |
| ADOPT-06 CI | `--ci`, else github when `origin` contains github.com, else gitlab; no origin and no `.gitlab-ci.yml` asks for `--ci` |
| ADOPT-07 adopt | `l4 init --vendor` the first time; `l4 upgrade` when `.l4/config.yaml` exists (output passed through) |
| ADOPT-08 check | `.l4/bin/l4 doctor --adoption` (`--no-gates`: config rows only); a red base exits 3 |
| ADOPT-09 commit | only with `--commit`: stages exactly the paths the adoption added or changed (compared with a snapshot taken before ADOPT-07), never `git add -A`; files that were already dirty stay unstaged |

`--dry-run` changes nothing (no sync, no doctor, no commit). The script ends with the remaining steps, filled in for
your project, and `adopt: done (exit N)`; exit 3 means the gate dry run was red: fix what doctor lists and rerun.

A Python project gets its gates proposed from `pyproject.toml`; any other ecosystem gets `# TODO:` gates at the top of
`.l4/config.yaml` for you to fill in. Run from the project's checkout, which has an `origin` on the forge.

### What `l4 init` and `l4 doctor --adoption` do

**`l4 init`** writes `.l4/` (config, the vendored harness, the CI template, the shim), the `.gitlab-ci.yml` include,
and extends `.gitignore`. It reads `pyproject.toml` to propose the gates: a `dev` extra gives
`uv sync --frozen --extra dev`, a `dev` dependency group keeps plain `uv sync --frozen`, ruff in neither leaves
`lint: []`, and every assumption is a `# TODO:` line at the top of `.l4/config.yaml`. It never writes `--all-extras`
(an extra such as `embed` may pull torch) and prints the extras it did **not** install:

```
note: extras not installed by gates.setup: embed, index, otel; a test that needs one fails until you add `--extra <name>` ...
next: run `.l4/bin/l4 doctor --adoption` ...
```

`.gitlab-ci.yml` is **created** with the include and a `test` job when it is absent (tagged with `ci.runner_tags`; its
first line ends the job on a schedule pipeline), gets the include inserted when it has none, and gets one `- local:` item
when it has a block-list `include:`. A form it cannot edit safely (`include: file.yml`, a flow list, a mapping) is
refused with exit 2 and nothing written; add the printed snippet yourself and run `l4 init --no-ci-edit`. A
repository that ignores `.serena/` gets no seed and `memory.enabled: false`, with the `.gitignore` carve-out printed.

**`l4 doctor --adoption`** runs the rows that read only the repository (config, specs, memory, CI tags) and a dry run
of the gates at HEAD, in a detached worktree (`GATE-001`): setup, build, lint, typecheck, then the test command. It runs
no environment, provisioning or sandbox row, so it works on a laptop with no agent CLI. It exits 3 on a red base and says
what to change:

```
GATE-001  error  fail  HEAD 0123456789; uncommitted changes are not included; gates ran bwrap: lint: fail (...) ...
  fix: lint `ruff check .` fails on style findings; `ruff check --select F,E9 .` passes: use it in gates.lint ...
       tests need modules from optional extras: chromadb (extra index); change gates.setup ... to `uv sync --frozen --extra dev --extra index`
```

Fix what it lists (config edits), run it again, and go on. `--no-gates` runs only the config rows (seconds, no venv).
A laptop cannot see a failure that exists only on the runner's platform (a module missing on Linux): section 4 ends with a
check pipeline on the runner for that reason.

### Test paths

The red-green freeze, the integrity checks and the red manifest all read `tdd.test_globs` (and `tdd.test_support_globs`);
a green step or a fix chore may not change any path they match, whatever the language. The defaults cover Python layouts
and `l4 doctor` does not guess other stacks yet, so for a .NET or JS project add their test folders in `.l4/config.yaml`:

```yaml
tdd:
  extra_test_globs: ["**/*.Tests/**", "**/*.Test/**", "**/*.IntegrationTests/**", "web/tests/**"]
```

What the test command writes must not land in those folders unless git ignores it: a report or coverage file the
test gate leaves in a test folder is committed with the step and counts as a test-path change. Write reports under
`.l4-out/` (the default `gates.test.reports` path, never committed), e.g. `dotnet test --results-directory .l4-out`,
or ignore the folder (`TestResults/` in that project's `.gitignore`).

## 2. Commit and push

Commit exactly what the adoption wrote: `--commit` does it for you (only the paths the adoption added or changed; your own
uncommitted edits stay out), or by hand with the list that `l4 init` prints in its `next:` line (`.l4/`, `.gitignore`, the
CI file, and `conftest.py` and `.serena/project.yml` when it wrote them), then `git commit -m "Adopt the L4 harness"`. On
GitLab push with `-o ci.skip`: the token does not exist yet, so a first pipeline would fail CI-001.

```bash
git push -o ci.skip -u origin main      # GitHub: git push -u origin main
```

If the project is not on the server yet, create it (GitLab's push-to-create makes a private project when your namespace
allows it; otherwise one click or API call) and `git remote add origin <url>` first.

## 3. Prepare the runner

`l4 setup gitlab` fails when no online runner carries `ci.runner_tags`, and its check pipeline runs on the runner, so the
runner comes first. You need a host you control, with sudo. On GitHub you can instead use GitHub's own runners and no
host at all (GitHub-hosted, below).

### Get a runner

**GitLab.** Install `gitlab-runner` from GitLab's official packages
(https://docs.gitlab.com/runner/install/linux-repository/). In the project create a **project** runner (Settings > CI/CD >
Runners > New project runner) with tags = the config's `ci.runner_tags` (default `agentic`) and "Run untagged jobs" off.
Then on the host:

```bash
sudo gitlab-runner register --non-interactive --url https://gitlab.example.com --token <glrt-... runner authentication token> --executor shell
```

A project runner is preferred: `l4 setup gitlab` WARNs on instance runners, because any tagged job of the instance runs
next to the runner's agent logins.

**GitHub.** Register a self-hosted runner (repository Settings > Actions > Runners > New self-hosted runner) with the
labels in `runs-on` of `.github/workflows/l4.yml` (`["self-hosted", <ci.runner_tags>]`), and run `prereqs.sh` below with
`RUNNER_USER=<the user the runner service runs as>`.

**GitHub-hosted (no runner of your own).** Leave `ci.runner_tags` empty, and the generated job runs on `ubuntu-24.04`.
Turn provisioning on with the repository variable `L4_SELF_PROVISION=true` (Settings > Secrets and variables > Actions >
Variables), or with `ci.self_provision: true` in the config. The job then runs:
1. A tool-cache restore.
2. `.l4/bin/l4-setup`. It installs uv and a user-space bubblewrap. On Ubuntu 24.04 it also runs one root command on that
   throwaway VM, `sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`, because the sandbox cannot start
   without it. The repository variable `L4_PROVISION_ROOT=0` forbids that command, and the sandbox check then fails.
3. `l4 doctor --ci --fix`, which installs the agent CLIs your role chains use.
4. A cache save, on the base branch only.

The first job spends about 45 s on installs. A job that restores the cache spends a few seconds [V, spike 06]. There is
no prerequisites script and no login on a host: the agents authenticate from secrets (section 4, GitHub).

### Prerequisites and logins

Self-hosted runners only; a GitHub-hosted job needs neither. As an admin with sudo, from a clone of the harness on the runner host:

```bash
bash scripts/runner/prereqs.sh --check
bash scripts/runner/prereqs.sh --apply        # RUNNER_USER=<user> for a runner user other than gitlab-runner
```

Then log in the agent CLIs AS the runner user (`prereqs.sh` PRQ-15 prints the exact steps). Never copy CLI credentials
between users or machines: a second copy of a refresh token kills the first. The check pipeline of section 4 (GitLab:
`l4 setup gitlab` triggers it; `l4 ci watch --project group/name --ref main` follows it) then verifies the runner.

## 4. Connect the forge

### GitLab

```bash
GITLAB_TOKEN=<maintainer PAT> .l4/bin/l4 setup gitlab --project group/name --watch
```

`l4 setup gitlab` reads the project, then, one row per fact and never a value:

```
OK    config no .l4/config.yaml: schema defaults (...)        # only when run without a config
OK    project group/name (id 119) private, default branch main
WARN  runner #12 (instance_type, online) is an instance runner on a private project: any project of this GitLab whose jobs carry these tags can run on it ...
OK    .gitlab-ci.yml on main includes .l4/ci/l4.gitlab-ci.yml; the project's own jobs: test (they run on every scheduled pipeline too)
NEW   token l4-bot id=63 scopes=api,write_repository level=30 expires=2027-10-05
SET   variable L4_FORGE_TOKEN (environment scope l4, masked, not protected, raw)
OK    new token can read project group/name as the bot user
NEW   schedule l4 sweep (*/30 * * * * UTC on main)
OK    pipeline #1234 triggered on main with L4_ADOPTION_CHECK=1: https://...
... the watcher's lines, then the job's trace if it failed ...
summary: 5 ok, 2 new, 1 set, 0 kept, 1 warn, 0 fail -> exit 0
```

* A `WARN` row names every instance (shared) runner the `l4` job can take, whatever the project's visibility (a
  public or internal project says so in the row): any tagged job of the instance runs next to the runner's agent logins.
* `FAIL` rows make the exit code 3: no online runner carries `ci.runner_tags` (the `l4` job would stay pending), only
  instance runners while shared runners are off, a bot token that does not verify, or a red check pipeline.
* A second run with the same arguments sends only reads (and the check pipeline unless `--no-pipeline`); `--dry-run`
  sends only reads and says what it would change.
* `--secret NAME=ENVVAR` (repeatable) copies a secret from your environment into a masked variable of the `l4`
  environment; `--rotate` makes a new token (add `--revoke-old` to revoke the older ones once the new one verified);
  `--cron EXPR`, `--no-schedule` and `--no-pipeline` change or skip the schedule and the check pipeline.
* The check pipeline runs `doctor --ci --fix --adoption` on the runner (the CI template adds `--adoption` when the
  pipeline variable `L4_ADOPTION_CHECK` is non-empty), then `plan`, which says `nothing to do`. `--watch` follows it; so
  does `l4 ci watch --project group/name --ref main [--tail 60]` at any time.
* Exit 1 is an HTTP error (the rows printed before it say what was done): a 403 means the credential is not a
  Maintainer's; a 401 means it was refused.

### GitHub

One command does it, with a token that has admin on the repository (`GH_TOKEN`; its value is never printed):

```bash
l4 setup github --secret CLAUDE_CODE_OAUTH_TOKEN=CLAUDE_CODE_OAUTH_TOKEN --watch
```

It is idempotent: a second run prints `KEPT` rows. It sets up:
- the environment `l4`, which `ci.github_environment` names, with a deployment branch policy for the base branch, the
  unit prefix (`l4/*`, `l4/**/*`) and the default branch when it is not the base (the schedule runs there);
- each `--secret NAME=ENVVAR`, sealed into that environment;
- the variable `L4_SELF_PROVISION=true` for a hosted runner;
- the workflow permissions: write, and Actions may create pull requests;
- the labels.

It then dispatches the `l4` workflow, and `--watch` follows it (`l4 ci watch --repo owner/name` follows any later run).
`--dry-run` only reads.

**The forge token.** With `forge.token_env: GITHUB_TOKEN`, the workflow's own token is enough: the harness opens and
labels pull requests as `github-actions[bot]`. Its one limit is that GitHub starts no workflow run for its pushes, so the
repository's other CI does not run on any L4 pull request. The harness reports that as `not_run`. To have that CI run:
1. Put a fine-grained token, or a GitHub App's, in the environment as the secret `L4_FORGE_TOKEN`, with contents, pull
   requests, commit statuses and actions write (`--secret L4_FORGE_TOKEN=L4_FORGE_TOKEN`).
2. Set `forge.token_env: L4_FORGE_TOKEN` in `.l4/config.yaml` (or init with `--forge-token-env L4_FORGE_TOKEN`).
3. Run `l4 upgrade`, which re-renders the workflow so that the job reads the secret.

**Agent secrets.** Add the one for each agent your role chains use. The generated job passes exactly these to the
harness:
- `CLAUDE_CODE_OAUTH_TOKEN`, from `claude setup-token`, for a claude-code `auth: subscription` profile;
- `ANTHROPIC_API_KEY` for a claude-code `auth: api_key` profile;
- `CODEX_API_KEY` for a codex `auth: api_key` profile;
- `KIRO_API_KEY` for a kiro-cli profile;
- `OPENCODE_API_KEY` for an opencode `auth: api_key` profile whose model starts with `opencode/` or `opencode-go/` (OpenCode Go or Zen);
- an opencode provider's `api_key_env`.

OpenCode's free models without `auth: api_key` need none. `l4 doctor` row PRV-001 names any variable that is missing.

**The harness through the setup action (recommended).** The harness repository is itself a GitHub action. Your
repository then holds only `.l4/config.yaml`, `.github/workflows/l4.yml` and the evidence folders: no `.l4/bin/`, no
vendored code, no `harness.commit`. The `uses:` line of the workflow is the only pin. Pick the form that fits the
repository:

- **A private repository of the same owner as the harness: no key.**
  1. In the harness repository, open Settings > Actions > Access and choose "Accessible from repositories owned by …".
     Anyone who can push a workflow to a private repository of that owner can then read the harness through the
     action, so this is the owner's choice. If the setting is later turned off, every such consumer fails at "Set up
     job".
  2. Adopt with a version pin:
     ```bash
     l4 init --ci github --action --harness-ref v0.4.9
     ```
     `--harness-ref` (a `vX.Y.Z` tag, `v0` or a branch) is resolved once with `git ls-remote`. The workflow gets
     `uses: <owner>/<harness>/.github/actions/l4@<sha> # v0.4.9`. A ref that resolves to nothing is exit 2. Use
     `--action-repo OWNER/REPO` only when `l4` runs from a checkout or was not installed from the harness repository:
     a checkout has no install origin, and `init` then exits 2.
- **A public repository, or one of another owner: a copy of the action and a deploy key.** GitHub never lets a public
  repository use a private action.
  1. Adopt with the copy:
     ```bash
     l4 init --ci github --action --action-copy --harness-ref v0.4.9
     ```
     This writes the action under `.github/actions/l4` (the copy your `l4` ships, so no checkout of the harness is
     needed) and a workflow that uses it with the harness's SSH URL. `l4 upgrade` refreshes that copy too.
  2. Add a read-only deploy key to the harness repository (Settings > Deploy keys), and store its private half as the
     environment secret `L4_HARNESS_SSH_KEY` in the environment `l4`. Use one key per consumer, so that a key can be
     removed on its own.

`l4 init --action` writes a config for a GitHub-hosted runner: `ci.runner_tags: []` and `forge.token_env: GITHUB_TOKEN`
(the workflow's own token, so there is no forge secret to create). Pass `--runner-tag TAG` (repeatable) for a self-hosted
runner and `--forge-token-env NAME` to use a token of your own. A hosted runner has no stored login: `codex` on a
subscription cannot log in there, so init prints a `todo:` line naming the profile; give it `auth: api_key` and the
secret `CODEX_API_KEY`, or name another profile in the role (`claude-code` takes `CLAUDE_CODE_OAUTH_TOKEN`).

The workflow also runs on a schedule, every 30 minutes by default. GitHub runs a schedule only from the workflow file
on the **default branch**. When your base branch is another branch, that file must be on the default branch too, with
the same pin (`l4 setup github` checks it). On a private repository that costs about 1,400
runner-minutes a month even when idle: set `ci.schedule` in `.l4/config.yaml` to a slower cron (for example
`"0 * * * *"`) or to `null` for no schedule, then run `l4 upgrade`, which re-renders the workflow.

On a **public** repository, set `ci.upload_artifacts: false` in `.l4/config.yaml`, and run
`l4 upgrade`: the `l4-out` artifact (prompts and agent transcripts, secrets masked) is downloadable by any signed-in
user, and with the key false the workflow has no upload step.

Then, for both forms:
- `l4 setup github` (above) creates the environment, the secrets and the labels, and dispatches the workflow.
- `--dependabot` (on `l4 init`) adds `.github/dependabot.yml` for the ecosystem `github-actions`, weekly, so a new
  release arrives as a pull request on the `uses:` line. It merges into an existing file. It does not combine with `--action-copy` (exit 2): in copy mode the pin is the `commit:` input, which Dependabot cannot move; use `l4 upgrade --harness-ref`.
- `l4 upgrade --harness-ref v0.5.0` (or `--harness-commit <sha>`) moves the pin by hand: it re-renders the whole
  workflow from the config with the template of the harness that runs it, so run it with the target version, for
  example `uvx --from git+https://github.com/<owner>/<repo>@<sha> l4 upgrade --harness-commit <sha>`. `l4 doctor` (CFG-006) checks that the `uses:` line is a 40-hex sha.
- There is no `.l4/bin/l4` in this form. To run `l4` on your machine, install it:
  `uv tool install git+ssh://git@github.com/<owner>/<harness>.git@<sha>` (`l4 doctor` row CFG-007 prints the hint
  when none is on `PATH`).

On a GitHub-hosted runner the action also installs uv and a user-space bwrap (the runner setup of the next sections
runs inside it) and keeps two caches: the installed harness, and the agent CLIs, which a harness upgrade does not
discard. A warm job reaches `l4` in about 7 s [V: docs/live/action/README.md].

**The harness without the action.** The two older forms stay available: vendored (`l4 init --vendor`, section 1, for air-gapped runners) and fetched (below).

**The harness without committing it (fetched).** `l4 init --ci github --harness-repo git@github.com:<owner>/<harness>.git
--harness-commit <sha>` writes no `.l4/vendor/`. The job fetches that commit with uv and caches it.

A private harness needs a read-only deploy key:
1. Add its public half to the harness repository (Settings > Deploy keys, read-only).
2. Store its private half as the environment secret `L4_HARNESS_SSH_KEY` (`--secret L4_HARNESS_SSH_KEY=...`).

`l4 upgrade --harness-commit <sha>` moves the pin.

## 5. First run

The `l4` job starts on a merge to the base branch, on a push to a unit branch, on the schedule and by hand. It runs
`doctor`, `plan --sweep` and `run`; with no unfinished spec task it says `nothing to do`. Add a spec (OpenSpec change or
Kiro spec) with unchecked tasks and push it: the job implements them test-first on a unit branch and opens an MR/PR.
Questions for you appear in `questions.md` next to the spec: answer in the file and push. `.l4/bin/l4 status` (also the
last step of the job) lists each unit with its state and what it waits for.
To ask for changes to a unit's code once its MR/PR is open (a refactor, a hard-coded value that should be an
environment variable, a missing test), run `.l4/bin/l4 feedback add`, then commit and push. [docs/feedback.md](feedback.md)
has one worked example for each kind and says what happens after the push.

When a unit stops or does not move, use the [operations runbook](runbook.md).

## Conditional extras

| When | Extra step |
|---|---|
| the repository was never on the server | `git remote add origin <url>` before the push of section 2 |
| ADOPT-08 (`doctor --adoption`) or the check pipeline is red | the config edits its fix column names (an extra, `lint: []`, a deselect) |
| GitLab does not create the project on push | create it first (one click or API call) |
| the schedule on a project with its own jobs | those jobs also run every 30 minutes: `--cron '0 * * * *'`, or `--no-schedule` |

A parked unit whose agent login is dead is probed again on every run, so while the login stays dead each sweep leaves one
`chore(<unit>): ledger [skip ci]` commit on the unit branch and refreshes the "Waiting for capacity" note on the MR
(it names the login steps); a backoff is deferred.
