## Why

The first adoption of the harness by a GitLab consumer whose base branch deploys a staging app on every push needed
four manual fixes that the harness should have made or named:

1. **GitLab refused every pipeline the harness started.** The project's own jobs are excluded from schedule, api and
   trigger pipelines (so the harness's runs never redeploy), and the `l4` job is in stage `.post`. GitLab refuses a
   pipeline whose jobs are all in `.pre` or `.post` ("pipeline would have been empty", HTTP 400): the adoption check
   and every scheduled sweep failed before a job ran. `l4 init` adds a job in a normal stage only when it creates
   `.gitlab-ci.yml`, not when it edits an existing one (`src/l4/init/ciedit.py`).
2. **`l4 setup gitlab` said the opposite.** Its row lists the project's own jobs and says "(they run on every scheduled
   pipeline too)" (`src/l4/setup/gitlab.py:308`) without reading their `rules`, `only` or `except`.
3. **The bot could never merge.** With `forge.merge_policy: auto` and a base branch that accepts merges from
   Maintainers only, the Developer-level bot token `l4 setup gitlab` creates (`BOT_LEVEL = 30`) cannot merge a unit.
   GitLab does not let the role of a project access token's bot change; a new token is needed. Nothing said so.
4. The doctor had no check for (1) either.

## What Changes

- **Which project jobs run on a pipeline of a given source** (L4-INS-007): a small three-valued evaluator of `rules`,
  `only`, `except`, job `when` and `workflow: rules` (run / skip / unknown) for the sources the harness starts. Setup's
  row reports the project's jobs on a scheduled pipeline of the base branch from it.
- **An empty pipeline is named before GitLab refuses it** (L4-INS-008): setup warns and doctor check `CI-007` warns
  when, on a schedule or api pipeline of the base branch, no project job runs and none is unknown, and when
  `workflow: rules` creates no such pipeline at all.
- **`l4 init` adds the anchor job when it edits an existing `.gitlab-ci.yml`** (L4-INS-009) whose jobs would all skip
  those pipelines: `l4-pipeline-anchor`, a job in a normal stage that only echoes.
- **The bot's level follows the merge policy and the protection** (L4-INS-010): setup creates the token as a
  Maintainer when `forge.merge_policy` is `auto` and the base branch accepts merges from Maintainers only, says why,
  and warns about a kept Developer token in that case, naming `--rotate --revoke-old`.

## Impact

- Code: `src/l4/ci/gitlab_rules.py` (new), `src/l4/setup/gitlab.py`, `src/l4/doctor/checks_ci.py`,
  `src/l4/init/ciedit.py` and `src/l4/init/init.py`.
- Docs: `docs/SPEC.md` (requirements, scenarios, change row 65), the GitLab section of `docs/runbook.md`.
- No config key. The token's level changes only for `merge_policy: auto` with a Maintainer-only base branch.
