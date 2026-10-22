# Adopting L4 in a repository (GitHub)

The harness lives in its own repository (`OWNER/l4`, private) and is used as a **setup action**. The
adopting repository keeps only:
- `.l4/config.yaml`;
- one workflow, `.github/workflows/l4.yml`;
- `.serena/project.yml`;
- the evidence the harness writes later.

No harness code, no `.l4/bin/`.

## 1. Pick the form

| The harness / the adopting repository | Form | Credential for the harness |
|---|---|---|
| **Public harness** (the published one), any repository | `--action` | **None.** The adopting repository's Actions policy must allow actions from other repositories ("Allow all actions", or an allow-list that names the harness). |
| Private harness, **private adopting repository of the same owner** | `--action` | **None.** In the harness repository: Settings → Actions → General → Access → "Accessible from repositories owned by …". |
| Private harness, **public** or another owner's adopting repository | `--action-copy` (a copy of the action in `.github/actions/l4/`) | A **read-only deploy key**, one per adopting repository: the public half on the harness repository, the private half as the secret `L4_HARNESS_SSH_KEY` in the environment `l4`. |

A public repository can never use a private repository's action: GitHub fails it at "Set up job".

## 2. A local `l4` at the version you adopt

```sh
uv tool install git+https://github.com/OWNER/l4@v0.4.25 && l4 skills install   # or @<sha>
l4 --version
```

`l4 skills install` puts this skill into the skill folder of each coding agent on the machine (add `--project` to
commit it for the team, `--agent NAME` for one agent); run it again after an upgrade.

## 3. Adopt

On the adopting repository's default branch, with a clean tree:

```sh
l4 init --ci github --action --harness-ref v0.4.25 [--dependabot] [--s1 laya|jev|none]
# a private harness, and a public or other-owner repository:
l4 init --ci github --action --action-copy --harness-repo git@github.com:OWNER/l4.git --harness-ref v0.4.25
```

- **`--action-repo OWNER/l4`** is optional. By default it is the repository the running `l4` was installed from
  (section 2). Pass it from a checkout, which has no install origin: `init` then exits 2.
- **System One.** `l4 init` writes a Laya profile (local, no key) as `roles.s1_judge` by default. `--s1 jev` writes a
  Jev profile that reads `TYPESAFE_API_KEY` (pass `--secret TYPESAFE_API_KEY=TYPESAFE_API_KEY` to `l4 setup github`);
  `--s1 none` writes neither, and every implementer question then goes to a person. `l4 doctor --adoption` says which
  is in use.
- **The pin.** `--harness-ref` resolves the tag once and writes `uses: …/.github/actions/l4@<sha> # v0.4.25`; that line
  is the only pin. `--harness-ref` takes a tag or a branch; a commit sha goes to `--harness-commit` (40 hex characters).
- **Upgrades by pull request.** `--dependabot` makes Dependabot propose upgrades. It does not work with
  `--action-copy`.
- **Then edit `.l4/config.yaml`:**
  - **Agents that can log in on a GitHub-hosted runner** (init prints a `todo:` when the default ones cannot):
    - Claude Code takes `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`);
    - kiro-cli takes `KIRO_API_KEY`;
    - OpenCode with `auth: api_key` and an `opencode/` or `opencode-go/` model takes `OPENCODE_API_KEY`;
    - codex needs `auth: api_key` (`CODEX_API_KEY`), since its subscription login is a local file;
    - OpenCode's free models need no key, unless the profile says `auth: api_key`.

    Give the implementer and the judges different vendors. Profiles proven on GitHub-hosted runners:

    ```yaml
    profiles:
      kiro:         {adapter: kiro-cli, auth: api_key, model: glm-5, vendor: zhipu}       # secret KIRO_API_KEY
      oc-free:      {adapter: opencode, model: opencode/mimo-v2.6-flash-free, vendor: xiaomi}  # no secret
      oc-go:        {adapter: opencode, auth: api_key, model: opencode-go/deepseek-v4.1-flash, vendor: deepseek}  # secret OPENCODE_API_KEY
      claude-judge: {adapter: claude-code, auth: subscription, vendor: anthropic}          # secret CLAUDE_CODE_OAUTH_TOKEN
      codex:        {adapter: codex, auth: api_key, vendor: openai}                        # secret CODEX_API_KEY
    roles:
      implementer: [kiro]          # or [oc-free], [codex]; a list is a fallback chain
      judges: [claude-judge]
    ```
  - **`ci.schedule`:** the default is every 30 minutes. On a private repository that is about 1,400 runner-minutes a
    month even when idle; set a slower cron, or `null`.
  - **`ci.upload_artifacts: false`** on a **public** repository. The `l4-out` artifact holds the prompts and agent
    transcripts (secrets masked), and any signed-in user can download it.
  - The test gate and the role chains; `l4 doctor --adoption` checks them. The test gate must write
    `.l4-out/junit.xml` (for example `pytest --junitxml=.l4-out/junit.xml`), or set `gates.test.reports`.
  - **CI jobs the gates do not mirror** (a database job, a chart or image check): `l4 doctor --adoption` lists them.
    Add their commands to `gates`, or accept that L4 will not run them.
- **Re-render after editing:** `l4 upgrade --harness-ref v0.4.25`. The workflow is always re-rendered from the config,
  so never edit `l4.yml` by hand.

## 4. GitHub setup

1. Commit what init listed, with `[skip ci]` in the message, and push.
2. Put each secret's value in an environment variable without echoing it (`read -rs VAR; export VAR`).
3. Run:

   ```sh
   GH_TOKEN=… l4 setup github --repo OWNER/REPO \
     --secret CLAUDE_CODE_OAUTH_TOKEN=CLAUDE_CODE_OAUTH_TOKEN [--secret KIRO_API_KEY=KIRO_API_KEY] [--secret OPENCODE_API_KEY=OPENCODE_API_KEY] \
     [--secret L4_HARNESS_SSH_KEY=L4_HARNESS_SSH_KEY] --watch
   ```

   It creates the environment `l4` with its branch rules (the default branch too, when it is not the base), seals the secrets, sets the workflow permissions (write, and
   Actions may create pull requests), the variable `L4_SELF_PROVISION` and the labels, and dispatches a first run.
   `--dry-run` reads only.

   GitHub runs `schedule` and `workflow_dispatch` only from the default branch. When the default branch is not the
   base, `setup` checks that it holds `.github/workflows/l4.yml` with the same pin as the base. Without the file the
   row is FAILED and the dispatch is not sent, so run `setup` after the default-branch pull request is merged (4a).
4. Unset the variables afterwards. Never paste a secret into a file or a chat.

The forge token is the workflow's own `GITHUB_TOKEN`. Pushes made with it start no workflow anywhere, so the
repository's own CI does not run on L4's PRs and shows `not_run`. To have it run:
1. Make a fine-grained token with contents and pull-request write, and checks, actions and commit-statuses read, on the repository (the CI read of merge-safety and `yolo.merge.require_ci` needs the reads).
2. Store it as `L4_FORGE_TOKEN` in the environment `l4` (`--secret L4_FORGE_TOKEN=L4_FORGE_TOKEN`).
3. Set `forge.token_env: L4_FORGE_TOKEN` (or init with `--forge-token-env L4_FORGE_TOKEN`) and run `l4 upgrade`.

A push from a laptop uses your own git credentials (https with your credential helper, or ssh). A refused push names
the forge's own token rules.

## 4a. An integration branch, and specs that already exist

When L4 must work on a branch that is not the default one (for example `staging`, promoted to `main` by a person) and
the repository already has specs that L4 must not start:

1. Create the branch from the default branch and push it. Run every `l4` command below with the release you adopt:
   `uv tool run --from git+https://github.com/OWNER/l4@vX.Y.Z l4 …`.
2. On that branch: `l4 init … --hold-existing` as in section 3. It writes the ids of the specs found now as
   `yolo.hold`: none of them runs, no plan and no review are needed. Then set `forge.base_branch: <branch>` (and
   `forge.merge_policy: auto` if delivery plans may merge), mirror the repository's CI commands in `gates`, run
   `l4 upgrade --harness-ref vX.Y.Z` and `l4 doctor --adoption`. Commit what init listed with `[skip ci]`.
3. To release a held spec, remove its id from `yolo.hold` or list it in a plan. `yolo.hold: ["*"]` makes every spec
   opt-in by plan. A spec that no plan lists and `yolo.hold` does not match runs alone, as a pull request into
   `<branch>` that a person merges.
4. Copy form only: create the deploy key (`ssh-keygen -t ed25519 -N "" -f key`), add `key.pub` to the harness
   repository as a read-only deploy key named after the adopting repository, and pass `--secret
   L4_HARNESS_SSH_KEY=…` to `l4 setup github` (section 4). Delete the local private key afterwards.
5. Push the branch. Open a pull request to the default branch with `.github/workflows/l4.yml` **only**, and merge it:
   the cron and `workflow_dispatch` run from the default branch's copy. The job checks out `<branch>` before the action,
   so nothing else is needed there. After every `l4 upgrade`, copy the new workflow there too: a stale copy runs the old
   pin; the run then does no work and prints a warning that names both commits (doctor `CFG-008`).
6. Run `l4 setup github` (section 4). It adds the default branch to the environment's deployment branches and checks
   the workflow there. The first run must show every existing unit `held by yolo.hold` and `nothing to do`.

With `merge: auto` in an activated plan, L4 merges into `<branch>`; otherwise a person merges.

**On 0.4.0, which has no `yolo.hold`:** hold the existing specs with a plan instead. Run `l4 yolo draft backlog --target
<branch> --merge human`, set its `limits` to `{"max_unit_attempts": 1, "max_runs": 1, "max_cost_usd": 0}`, validate, and
say in the commit message that the plan only holds units and is never activated. A unit listed in a plan that is not
completed does not run; `exclude` does not hold. Admission may refuse the plan, and the hold still applies. The plan
fails open for every new spec, and a judge review is charged if admission ever accepts it. Move to `yolo.hold` once the
pin is on a release that has it: the schema is strict, so release, pin move, then the config edit.

## 4b. A cheap-first implementer chain

A chain in `roles.implementer` moves a failing task to the next profile. Put the cheap profiles first and an optional
stronger profile last. Two models of one provider are two steps, because the move goes by profile:

```yaml
profiles:
  deepseek:      {adapter: opencode, auth: api_key, model: opencode-go/deepseek-v4.1-flash, vendor: deepseek}  # OPENCODE_API_KEY
  glm:           {adapter: opencode, auth: api_key, model: opencode-go/glm-5.3-flash, vendor: zhipu}           # the same key
  claude-sonnet: {adapter: claude-code, auth: subscription, vendor: anthropic}                                # optional, last
  claude-judge:  {adapter: claude-code, auth: subscription, vendor: anthropic}
  codex-judge:   {adapter: codex, auth: api_key, vendor: openai}                                              # CODEX_API_KEY
roles:
  implementer: [deepseek, glm, claude-sonnet]   # cheap first; a task moves after escalate_after failures
  judges: [claude-judge, codex-judge]           # a judge must not share a vendor with an implementer that ran
implementer:
  escalate_after: 2                             # 0: never move
  max_task_attempts: 3                          # the last profile's attempts
```

- Escalation moves by profile, cheap first. After `escalate_after` failed attempts of one phase, the next usable profile
  takes the phase and reads the reasons of the earlier failures. The last profile gets `max_task_attempts`. The next
  task starts on the first profile again.
- Without `claude-sonnet` the chain needs no subscription.
- A judge of every implementer vendor is vetoed. The harness does not move a task to a profile when no judge of another
  vendor is left (the independence rule). With the judge `claude-judge` alone, a move to `claude-sonnet` is skipped.
  Keep one judge of another vendor, here `codex-judge`.
- `escalate_after: 0` turns escalation off. `l4 doctor` (CFG-009) warns when `escalate_after` is not below
  `max_task_attempts`, or when two profiles run the same model.
- The key `implementer.escalate_after` needs harness 0.4.4. Move the pin (`l4 upgrade --harness-ref v0.4.25`) before you
  edit the config: the schema is strict.

## 4c. A polyglot repository

The L4 job installs Python, uv and the agent CLIs, nothing else. For Go or TypeScript gates set `ci.toolchains`
(`l4 init` proposes it from `go.work`/`go.mod`, `.nvmrc`/`engines.node` and `packageManager: pnpm@X`), then run
`l4 upgrade`, which puts pinned `actions/setup-go`, `actions/setup-node` and `pnpm/action-setup` steps before L4:

```yaml
ci:
  toolchains: {go: {version_file: go.work}, node: {version: "22"}, pnpm: {version: "11"}}
```

Then write the gates for those languages (`go test ./...`, `pnpm test`). With `go` set, gates run with
`GOTOOLCHAIN=local` and `GOFLAGS=-mod=readonly`; the Go and pnpm caches are per unit. A Go project's `gates.setup` must run `go mod download all && go mod verify` (the module and checksum caches are read-only in the other gates; doctor SANDBOX-005 warns without it), and a tool with its own cache (golangci-lint: `GOLANGCI_LINT_CACHE`; anything under `~/.cache`) must point it at `.l4-out/` in the gate script. `l4 doctor --adoption` (TOOL-001)
names a gate command whose tool is not on the PATH. On GitLab the runner image must provide the toolchains.

## 4d. A Kiro judge

A `kiro-cli` profile can be a judge or a clarifier (harness 0.4.20, kiro-cli 2.32.0, the harness's pin; a Kiro CLI 3 is refused; secret `KIRO_API_KEY`).
Move the pin before you edit the config. With no model it runs Kiro's `auto`; pinned, it runs one model:

```yaml
profiles:
  deepseek:     {adapter: opencode, auth: api_key, model: opencode-go/deepseek-v4.1-flash, vendor: deepseek}  # OPENCODE_API_KEY
  kiro-auto:    {adapter: kiro-cli, auth: api_key, min_version: "2.32.0"}                    # no model: auto
  kiro-sonnet:  {adapter: kiro-cli, auth: api_key, model: claude-sonnet-5.5, vendor: anthropic, min_version: "2.32.0"}
roles:
  implementer: [deepseek]
  judges: [kiro-auto]            # or [kiro-sonnet]
```

- **A Kiro judge's vendor is its model's maker.** `claude-` is `anthropic`, `gpt-` `openai`, `gemini-` `google`,
  `deepseek-` `deepseek`, `glm-` `zhipu`, `minimax-` `minimax`, `qwen` `alibaba`, `kimi-` `moonshot`. A `vendor:` that
  contradicts the model does not load (`vendor contradicts the model: …`): delete it or set the maker.
- **On `auto`, the vendor is every maker Kiro may route it to** (`anthropic`, `minimax`, `zhipu` and what `kiro-cli chat
  --list-models` adds; `l4 probe` shows the set). A `vendor:` there is ignored. So `kiro-auto` judges a DeepSeek,
  OpenAI or Google implementer, but is vetoed for a Claude, GLM or MiniMax one, and two `auto` profiles are never
  independent. Pin a model to make the served model checkable, and pin one whose maker the implementer does not share.
- `l4 doctor` (CFG-011) warns on `options.agent` (ignored by a judge) and on a missing `min_version: "2.32.0"`. A key
  Kiro rejects moves to the next judge; keep a second judge of another vendor in `roles.judges`.
- Kiro meters plan credits: `verify.judge.credits` and `budget.cost{credits}`, never dollars.

## 4e. Agent CLI pins

A GitHub-hosted runner installs every agent CLI at the harness pin (`kiro-cli 2.32.0` from its versioned archive), and
no CLI updates itself. To hold one at another version of the same major, set `ci.cli_versions`, for example
`ci: {cli_versions: {kiro-cli: "2.28.0"}}`. Move the pin before you add the key: an older harness refuses it. A Kiro
version works only when the harness holds its digests. The key changes the CLI cache key; `l4 doctor` ENV-015 names the
override, and notes one that equals the pin (remove it). A major other than the pin's (Kiro CLI 3) does not load.

## 4f. The delegate (optional)

A model can answer a unit's questions in CI, so a plan does not wait on a person for a technical question. It is off.
`l4 init` writes it as a commented-out block at the end of `.l4/config.yaml`, with a model pinned on `codex` and
`claude-code` (the default `delegate.independence: model` compares models) and `delegate-sonnet` (`claude-sonnet-5`) as
the delegate. To turn it on, on the base branch, remove the leading `# ` of the lines that begin with a single `#`
(`delegate.enabled: true` and `roles.delegate`):

```yaml
roles:
  delegate: [delegate-sonnet]
delegate:
  enabled: true
  scope: yolo
```

Four adapters serve it (`claude-code`, `codex`, `opencode`, `kiro-cli`), each read-only. A free-tier model (an OpenCode
Zen id `opencode/…` or an id that ends in `:free`) answers technical and harness questions only: put it last in
`roles.delegate`. A `kiro-cli` profile on `model: auto` vetoes every delegate. `l4 doctor` checks the chain (`DLG-001`).
Turning it on is the person's decision; see `references/operate.md`.

## 5. Upgrades

```sh
uv tool install --force git+https://github.com/OWNER/l4@v0.5.0
l4 upgrade --harness-ref v0.5.0
```

Run it with the `l4` of the target version. It re-renders the workflow (and refreshes the copied action in copy mode)
and prints the diff. Then commit and push.

## Self-hosted runners and GitLab

- **A self-hosted GitHub runner:** `l4 init --ci github --action --runner-tag TAG`. It gets no tool cache.
- **GitLab:** `l4 init --ci gitlab` (the vendored or fetched form; there is no action). Read the harness's
  `docs/quickstart.md` if you have access to it.
- **An `l4 run` that stops at once with `the job API says token refused`:** a CI/CD variable named `CI_JOB_TOKEN`
  (project, group or instance) replaces the job token. Rename it; `l4 setup gitlab` names it, and 0.4.24 falls back
  to the token in `CI_REPOSITORY_URL`.
