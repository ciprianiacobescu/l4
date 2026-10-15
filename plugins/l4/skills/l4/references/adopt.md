# Adopting L4 in a repository (GitHub)

The harness lives in its own repository (`OWNER/l4`, private) and is used as a **setup action**. The
adopting repository keeps only:
- `.l4/config.yaml`;
- one workflow, `.github/workflows/l4.yml`;
- `.serena/project.yml`;
- the evidence the harness writes later.

No harness code, no `.l4/bin/`.

## 1. Pick the form

| The adopting repository | Form | Credential for the harness |
|---|---|---|
| **Private, same owner** as the harness | `--action` | **None.** In the harness repository: Settings → Actions → General → Access → "Accessible from repositories owned by …". |
| **Public**, or another owner | `--action-copy` (a copy of the action in `.github/actions/l4/`) | A **read-only deploy key**, one per adopting repository: the public half on the harness repository, the private half as the secret `L4_HARNESS_SSH_KEY` in the environment `l4`. |

A public repository can never use a private repository's action: GitHub fails it at "Set up job".

## 2. A local `l4` at the version you adopt

```sh
uv tool install git+https://github.com/OWNER/l4@v0.4.0   # or @<sha>
l4 --version
```

## 3. Adopt

On the adopting repository's default branch, with a clean tree:

```sh
l4 init --ci github --action --action-repo OWNER/l4 --harness-ref v0.4.0 [--dependabot]
# public or other-owner repository:
l4 init --ci github --action --action-copy --harness-repo git@github.com:OWNER/l4.git --harness-ref v0.4.0
```

- **The pin.** `--harness-ref` resolves the tag once and writes `uses: …/.github/actions/l4@<sha> # v0.4.0`; that line
  is the only pin.
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
  - The test gate and the role chains; `l4 doctor --adoption` checks them.
- **Re-render after editing:** `l4 upgrade --harness-ref v0.4.0`. The workflow is always re-rendered from the config,
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

   It creates the environment `l4` with its branch rules, seals the secrets, sets the workflow permissions (write, and
   Actions may create pull requests), the variable `L4_SELF_PROVISION` and the labels, and dispatches a first run.
   `--dry-run` reads only.
4. Unset the variables afterwards. Never paste a secret into a file or a chat.

The forge token is the workflow's own `GITHUB_TOKEN`. The harness's pushes made with it start no other workflows, so the
repository's own CI shows `not_run` on L4's PRs. To keep that CI, use a fine-grained token as `L4_FORGE_TOKEN` in the
environment `l4` and set `forge.token_env: L4_FORGE_TOKEN`.

## 4a. An integration branch, and specs that already exist

When L4 must work on a branch that is not the default one (for example `staging`, promoted to `main` by a person) and
the repository already has specs that L4 must not start:

1. Create the branch from the default branch and push it. Run every `l4` command below with the release you adopt:
   `uv tool run --from git+https://github.com/OWNER/l4@vX.Y.Z l4 …`.
2. On that branch: `l4 init …` as in section 3, then set `forge.base_branch: <branch>` (and `forge.merge_policy: auto`
   if delivery plans may merge), mirror the repository's CI commands in `gates`, run `l4 upgrade --harness-ref vX.Y.Z`
   and `l4 doctor --adoption`. Commit what init listed with `[skip ci]`.
3. **Hold the existing specs** in the next commit: `l4 yolo draft backlog --target <branch> --merge human`, set its
   `limits` to `{"max_unit_attempts": 1, "max_runs": 1, "max_cost_usd": 0}`, validate, and say in the commit message
   that the plan only holds units and is never activated. A unit listed in any plan that is not completed does not
   run; `exclude` does not hold. Admission may refuse the plan (old specs often fail intake); the hold still applies.
4. Copy form only: create the deploy key (`ssh-keygen -t ed25519 -N "" -f key`), add `key.pub` to the harness
   repository as a read-only deploy key named after the adopting repository, and pass `--secret
   L4_HARNESS_SSH_KEY=…` to `l4 setup github` (section 4). Delete the local private key afterwards.
5. Add the **default branch** to the environment `l4`'s deployment branches (Settings → Environments → l4): the cron
   runs on the default branch, and `l4 setup github` adds only `<branch>` and `l4/*`.
6. Push the branch. The first run must show every existing unit `held by plan backlog` and `nothing to do`.
7. Open a pull request to the default branch with `.github/workflows/l4.yml` **only**: GitHub runs `schedule` and
   `workflow_dispatch` only for workflows on the default branch. The job checks out `<branch>` before the action, so
   nothing else is needed there.

New specs outside every plan then run as single units (a pull request into `<branch>`, merged by a person); a plan
with `merge: auto`, activated by a person, is merged into `<branch>` by L4.

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
