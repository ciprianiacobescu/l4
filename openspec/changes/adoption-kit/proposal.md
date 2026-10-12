## Why

Adopting L4 on GitHub still leaves harness machinery in the consuming repository, and the harness repository has no
packaging for people or agents:

- **Files in the consumer.** `l4 init --harness-repo` (github-parity) keeps the harness code out of the consumer. It
  still writes four files:
  - a 65-line rendered workflow;
  - the `.l4/bin/l4` shim;
  - the 167-line `.l4/bin/l4-setup`;
  - a deploy-key secret, needed even for the owner's own private repositories.
- **One cache keyed on the harness commit.** It holds the harness and the agent CLIs, 425 MB [V, `actions/caches` of
  the github-parity dummy]. Every harness upgrade throws all of it away and pays ~40 s cold; a warm job pays 5–10 s to
  restore it.
- **Pins are commits only.** No tag or version can be named, and nothing moves a pin by pull request.
- **The harness repository's CI runs no unit tests.** `checks.yml` runs ruff, the SPEC check, gitleaks and the
  publication scrub. The suite takes 68 minutes on one process.
- **No skill.** An agent asked to "adopt L4", "give feedback on this unit" or "resume the escalated unit" has nothing
  to load.

A spike on 2026-10-12 (branch `l4-action`, dummy `ciprianiacobescu/l4-dummy-action`) measured a composite action
[V, runs 38299270512, 38299395945, 38299475651, 38299563947]:

| Caller | Source | Cold job | Warm job | `l4` start |
|---|---|---|---|---|
| private repository of the same owner | the harness repository's own action (no key) | 11 s | 16 s | 0.43 s |
| public repository | a copy of the action, the harness fetched with a deploy key | 11 s | 7–11 s | 0.28–0.40 s |
| public repository | the harness repository's own action | fails at "Set up job": `Unable to resolve action … not found` | | |

- The cache of the installed harness is 25 MB, restored in 1–2.3 s.
- The private action's repository is downloaded every job, which took 2.5 s once and 9.8 s once (6.7 MB archive).
- These timings cover the harness alone, without the agent CLIs.
- GitHub documents the public-caller limit: a private repository's actions are shared only with private repositories
  of the same owner [D, docs.github.com "Sharing actions and workflows from your private repository"].

The maintainer asked on 2026-10-12 for an installable skill and defined GitHub workflows or actions: "Do it in
parallel… But always validate it."

## What Changes

- **The harness as a setup action**, `.github/actions/l4` in the harness repository, like `setup-python`. It installs
  the harness, makes the runner ready (what `l4-setup` does today), restores both caches, and puts `l4` on `PATH`. The
  workflow then runs `l4 doctor`, `l4 plan` and `l4 run` as plain steps. It has two sources:
  - **`action`:** the action's own downloaded copy. Callers are private repositories of the same owner, and no key is
    needed.
  - **`repository`:** fetched by commit over SSH with a read-only deploy key. Callers are public or other-owner
    repositories.
- **Two caches:**
  - the installed harness, keyed on its source (~25 MB);
  - the agent CLIs, keyed on the provisioning catalog's pinned versions.

  A harness upgrade then restores the CLIs warm.
- **`l4 init --ci github --action`.**
  - It renders a short workflow that `uses:` the action at a pinned sha with a `# vX.Y.Z` comment.
  - It writes no `.l4/bin/` files.
  - `harness.delivery: action` takes the pin from the workflow's `uses:` line alone, so there is one place to change.
  - `--dependabot` adds `.github/dependabot.yml` for `github-actions`, so a new harness release arrives as a pull
    request.
- **Pins by version.**
  - `l4 init` and `l4 upgrade` take `--harness-ref vX.Y.Z` (a tag or branch). It is resolved to its sha once
    (`git ls-remote`), and the sha is written with the ref as a comment.
  - The harness repository gains a release workflow. A `vX.Y.Z` tag builds a slim release commit that holds only what
    the action installs (about 0.8 MB against 6.7 MB), and moves the `v0` tag.
- **Harness CI.**
  - The unit suite runs in shards on pull requests to `amaster`, nightly, and on demand.
  - An action self-test job runs `.github/actions/l4` from the checkout.
  - Dependabot covers the harness repository's own action pins.
- **An installable `l4` skill** in the Agent Skills format: `skills/l4/SKILL.md` with reference files.
  - It is a Claude Code plugin with a marketplace entry in this repository, and Codex can load it from
    `~/.agents/skills/`.
  - It covers adopting L4, reading status, answering questions, giving feedback and resuming.
  - It is written test-first against recorded failures of an agent without it.
- **Live evidence on the dummy repository:** the action in both sources, then a full `doctor`/`plan`/`run` of a seed
  unit, with cold and warm timings.

**Not in this change:**
- A GitLab CI/CD component (the GitLab counterpart of the action).
- Publishing to PyPI or GitHub Packages.
- A GitHub App token step.

## Capabilities

### New Capabilities

- `adoption-kit`: the setup action and its two sources, the split caches, `l4 init --action` and version pins, the
  release workflow and slim release commits, the harness repository's CI, and the installable `l4` skill.

### Modified Capabilities

None as an OpenSpec delta. design.md lists the SPEC lines this change amends: §2.1 (the `init`/`upgrade` rows),
§3.2 (`harness.delivery`), L4-INS-001/004/005, §16.2 (the GitHub template), L4-PRV-020..023 (the runner setup moves
into the action on GitHub) and §21 (delivery row 18).

## Impact

- **Harness repository:** `.github/actions/l4/action.yml`, `.github/workflows/{checks,release,action-selftest}.yml`,
  `.github/dependabot.yml`, `skills/l4/**`, `.claude-plugin/{plugin,marketplace}.json`.
- **Code:**
  - `src/l4/ci/github.py` and `templates/l4.github.yml`: the action form;
  - `src/l4/ci/render.py`;
  - `src/l4/init/init.py` and `upgrade.py` (`--action`, `--harness-ref`, `--dependabot`);
  - `src/l4/config/schema.py` (`harness.delivery`);
  - `src/l4/doctor/` (a check that the `uses:` pin and the config agree).
- **Docs:** `docs/SPEC.md`, `docs/quickstart.md` (GitHub through the action), `docs/live/action/`.
- **Live:** the dummy `ciprianiacobescu/l4-dummy-action`, private or public as each test needs. A temporary read-only
  deploy key is added for the public test and removed afterwards. The maintainer deletes the repository.
