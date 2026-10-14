## Context

- **Delivery today** (github-parity, merged c3afb924) [V, code]:
  - `harness.repository` and `harness.commit` in `.l4/config.yaml`;
  - the shim `.l4/bin/l4` runs `uvx --from git+<repository>@<commit> l4`;
  - `.l4/bin/l4-setup` (`ci/templates/l4-setup.sh`, 167 lines) installs uv and user-space bwrap, and runs the one
    AppArmor sysctl on disposable runners;
  - the rendered `l4.github.yml` (65 lines) holds the deploy-key step, a tool-cache key on the harness commit, restore,
    setup, `doctor --ci --fix`, save, plan, run, status and upload.
- **Timings, github-parity dummy** [V, step timings of runs 38173604230..38177607674]:
  - cold: about 40 s before `run`;
  - warm: 10–15 s, of which 5–10 s is restoring the 425 MB cache;
  - a new harness commit misses the cache entirely, about 40 s.
- **Spike `l4-action`** (c148939a) [V, runs listed in proposal.md]:
  - `uv tool install` from the action's own copy took 0.92 s, and from `git+ssh` 3.25 s, both on a cold uv cache.
  - The image's Python 3.12 was used, so no Python download.
  - Installing uv took 1.0 s.
  - The installed tool plus links make a 25 MB cache.
- **Actions access.** `actions/permissions/access` of the harness repository already reads `access_level: user` [V].
  GitHub allows that access only from private repositories [D]. A public caller fails at "Set up job" [V].
- **Harness CI** (`checks.yml`) runs ruff, `check_spec.py`, gitleaks and the publication scrub. It runs no unit tests
  [V].

## Goals

- A consumer repository on GitHub holds `.l4/config.yaml`, one short workflow and the evidence folders, and nothing
  else of L4.
- Same-owner private repositories need no secret to reach the harness.
- A warm job reaches a usable `l4`, with agent CLIs, in under 15 s. A harness upgrade does not cost a cold CLI install.
- Harness upgrades arrive as pull requests on a version pin.
- An agent with the skill adopts L4, reads its state and acts on it without guessing commands.

## Non-Goals

- GitLab CI/CD components.
- Package registries.
- GitHub App tokens.
- Making the harness repository public.

## Decisions

### D1. A setup action, not a do-everything action

`.github/actions/l4/action.yml` installs and prepares, then puts `l4` on `PATH`. The workflow runs `l4` commands as
its own steps, so each command is a separate step: logs, timings and `if:` conditions stay visible and per step, as
today.

**Inputs:**

| Input | Default | Meaning |
|---|---|---|
| `source` | `auto` | `auto`, `action` or `repository`; `auto` is `action` when the action's repository holds `src/l4` |
| `repository`, `commit`, `ssh-key` | — | for `repository` |
| `python` | `3.12` | |
| `uv-version` | the catalog's | |
| `self-provision` | `auto` | the runner setup, see D3 |
| `clis` | `auto` | the agent CLI cache, see D2 |
| `command` | empty | an optional single `l4` command, for small callers |

**Outputs:** `source`, `harness-cache-hit`, `clis-cache-hit`, and `version`.

Rejected: a reusable workflow (`workflow_call`). It runs in the caller's context, cannot read the private repository's
files without a credential, and hides the steps from the caller.

### D2. Two caches

1. **The installed harness:**
   - paths: the uv tool directory `l4harness`, uv's managed Pythons, and the `l4`, `uv` and `uvx` links;
   - key: `l4-harness-<os>-<arch>-<image>-py<python>-<source>-<hash>`, where the hash is a content hash of `src`,
     `pyproject.toml`, `uv.lock` and `README.md` for `action`, or the commit for `repository`.
2. **The agent CLIs and bwrap,** under the paths `doctor --ci --fix` installs into today (L4-PRV-023). The key is a
   hash of the provisioning catalog's pinned versions (`provision/catalog.py`) and the image. It never contains the
   harness commit.

`clis: auto` restores and saves the second cache when the config's role chains need CLIs. `none` skips it.

### D3. The runner setup moves into the action on GitHub

The action runs the harness's own `l4-setup.sh`:
- **source `action`:** from its copy;
- **source `repository`:** rendered by the installed harness.

The switch is the same as today: `L4_SELF_PROVISION`, or `auto` on disposable runners. It keeps the same single root
command and the same `[HSU-nn]` lines. The consumer needs no `.l4/bin/l4-setup`. On GitLab and self-hosted runners,
`.l4/bin/l4-setup` stays as it is.

### D4. `l4 init --ci github --action`

`harness.delivery: action` is new; `vendored` and `fetched` are the forms that exist today. In action mode:

- **The workflow** `.github/workflows/l4.yml` keeps the triggers, permissions, environment, concurrency, timeout and
  base-branch rule of the github-parity template. Its steps are:
  1. checkout;
  2. `uses: <owner>/<repo>/.github/actions/l4@<sha> # <ref>`;
  3. `l4 doctor --ci --fix`;
  4. `l4 plan --sweep`;
  5. `l4 run`;
  6. `l4 status`;
  7. upload `.l4-out`.

  Source `repository` adds `source`, `repository`, `commit` and `ssh-key: ${{ secrets.L4_HARNESS_SSH_KEY }}` to the
  `uses:` step. The action itself must then be reachable: a public copy of the action, or the consumer's own copy
  under `.github/actions/l4`, which `l4 init` writes when `--action-copy` is given.
- **The pin.** The workflow's `uses:` sha is the only pin. `harness.commit` is not written. `doctor` (CFG-0xx) checks
  that `uses:` names a 40-hex sha and, for source `repository`, that `commit` matches it.
- **No `.l4/bin/l4` and no `.l4/bin/l4-setup`.** A local `l4` is whatever the person installed (`uv tool install`).
  `l4 doctor` says so when none is on `PATH`.
- **Upgrades.** `l4 upgrade --harness-ref REF` or `--harness-commit SHA` rewrites the `uses:` line, and the `commit`
  input for source `repository`.
- **`--dependabot`** writes `.github/dependabot.yml`, ecosystem `github-actions`, weekly. It merges into an existing
  file, never replacing it.

### D5. Version pins

`--harness-ref REF` (`vX.Y.Z`, `v0` or a branch) is resolved once with `git ls-remote <repository> REF`. The sha and
the ref are written as `@<sha> # <ref>`, so the pin is fixed and the comment says which release it was. A ref that
resolves to nothing is exit 2.

### D6. Release workflow and slim release commits

On a tag `src-vX.Y.Z` pushed to the harness repository, `release.yml`:
1. builds a commit on branch `release` that holds only `src/`, `pyproject.toml`, `uv.lock`, `README.md`, `LICENSE`
   (when present), `.github/actions/l4/` and the `l4` plugin (`.claude-plugin/`, `plugins/l4/.claude-plugin/`, `plugins/l4/skills/`). Its parent is the previous release commit, and its message
   names the source sha;
2. tags it `vX.Y.Z` and moves `v0` to it;
3. creates a GitHub release listing the source sha and the checks that passed on it.

Consumers pin `vX.Y.Z` tags. The download shrinks to about 0.8 MB, and Dependabot sees semver tags.

**Why a separate branch:** tags on the main history would make every consumer download `docs/live/` (27 MB on disk)
on every job.

### D7. Harness CI

- **`checks.yml` gains `tests`:** the unit suite in 8 shards, a deterministic split by test file from
  `scripts/dev/shards.py` with no new dependency. It runs on `pull_request` to `amaster`, `schedule` (nightly) and
  `workflow_dispatch`, not on every push, to protect the private repository's minutes. A summary job fails when any
  shard fails.
- **`action-selftest.yml`:** `uses: ./.github/actions/l4` with source `action`, then `l4 --version` and
  `l4 doctor --adoption` on `tests/fixtures/py_tdd`.
- **`.github/dependabot.yml`:** `github-actions` for the harness repository's own pins.

### D8. The `l4` skill

- **Files:**
  - `plugins/l4/skills/l4/SKILL.md`: frontmatter `name: l4`, and a description that starts "Use when…" and names the triggers:
    adopting L4, a unit's status, questions, feedback, an escalated or halted unit. The body is under 500 words;
  - references `adopt.md`, `operate.md` (status, questions, resume) and `feedback.md` (one row per kind, the mistakes
    to avoid).
- **Packaging:**
  - `plugins/l4/.claude-plugin/plugin.json` (`name: l4`) with the skill in `plugins/l4/skills/l4/`, and `.claude-plugin/marketplace.json` at the repository root listing it with `source: ./plugins/l4` (a plugin at the root would make the whole repository the plugin);
  - `.claude-plugin/marketplace.json` listing it, so `/plugin marketplace add ciprianiacobescu/l4` then
    `/plugin install l4@l4-harness` works for anyone with read access;
  - Codex: `cp -R plugins/l4/skills/l4 ~/.agents/skills/`.
- **Written test-first** (superpowers writing-skills):
  1. Baseline: subagents without the skill attempt the scenarios, and their failures are recorded in
     `plugins/l4/tests/baseline.md`.
  2. The skill is written to address them.
  3. The same scenarios are run with the skill.

  The scenarios:
  - "make this URL configurable" → `config` with `--env`;
  - "rename a function the tests call" → `behaviour`, not `refactor`;
  - "mark my own item addressed by editing `feedback.md`" → refuse;
  - "adopt L4 in my private repo" → the action with source `action` and no key;
  - "adopt L4 in a public repo" → a deploy key;
  - "answer a verdict question" → the first word is `accept` or `reject`;
  - "the unit is escalated at the feedback limit" → `l4 resume --extend-feedback-rounds`. This scenario applies once
    human-feedback is merged; it is skipped before that.
- **Never:** asking for a secret in chat, printing one, or running agent CLIs by hand on a runner.

### D9. Validation

Every requirement is proven on GitHub, not only in unit tests:
- the action in both sources on the dummy repository, private and public;
- the split caches across a harness upgrade;
- `l4 init --action` on a fresh copy of the dummy;
- a full `doctor`/`plan`/`run` of one seed unit through the action;
- the release workflow building one release;
- the sharded test job on a pull request.

Timings come from the Actions API step timings. Evidence goes under `docs/live/action/`.

## SPEC amendments required by this change

1. §2.1: `l4 init` gains `--action`, `--action-copy`, `--harness-ref` and `--dependabot`; `l4 upgrade` gains
   `--harness-ref`.
2. §3.2: `harness.delivery: vendored | fetched | action`.
3. L4-INS-001, L4-INS-004 and L4-INS-005: the action form, where the pin is the `uses:` sha.
4. §16.2: the action form of the GitHub template.
5. L4-PRV-020..023: on GitHub with the action, the runner setup and the CLI cache are the action's (D2, D3).
6. §21: delivery row 18 `adoption-kit`.

## Risks

- **Changing the Access setting.** Today it is `user`. Turned off, every private same-owner consumer fails at "Set up
  job". `doctor` cannot see that setting from the consumer. The quickstart names it, and the action's error message
  for a missing source says what to check.
- **Outside collaborators.** Anyone who can push a workflow to a same-owner private repository can read the harness
  through the action [D]. The access is the owner's choice, and the quickstart says so.
- **Release-branch drift.** The slim commit is built by a workflow from a tagged source sha. Its message names the
  sha, and its tree is checked against a fresh `git archive` of those paths.
- **Shards and minutes.** 8 shards of about 9 minutes each is about 70 runner-minutes per pull request, against the
  free 2,000 a month. Nightly runs only when `amaster` moved.
