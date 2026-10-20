## Why

A unit of a consumer repository passed L4 verification on 2026-10-20 and was handed off. The repository's own GitHub CI
then failed on the hand-off commit (pytest: 1 failed, 2277 passed). L4 recorded `ci.failed`, sent the unit back to
`verifying` and made a fix unit for the blocker `repository CI failed: ci.yml / lint · types · tests`. Two things went
wrong.

1. **The evidence missed the error.** The finding's detail said `job … failed on the hand-off commit … Log ends:
   ...##(warning)Node.js 20 is deprecated. The following actions target Node.js 20 but are being forced to run on
   Node.js 24: actions/checkout@v4, astral-sh/setup-uv`. The `FAILED` test line, the assertion and `##[error]Process
   completed with exit code 1.` never reached the implementer.
   - `GitHubForge.job_log_tail` (`src/l4/forge/github.py:729-747`) returns `clip_log(text, 40)`: the last 40 lines of
     the whole job log. A GitHub job log ends with the post steps (`Post job cleanup.`, the git cleanup of
     `actions/checkout`, the cache of `setup-uv`), `Cleaning up orphan processes` and the runner's deprecation warnings.
     A log of this repository's own dummy shows the same shape: its failing step's `exit code 128` is line 176 of 223,
     outside the last 40 (`docs/live/feedback/runs/38329266005-job-115075028141.log`).
   - `clip_log` (`src/l4/forge/base.py:165-171`) removes ANSI codes but not the runner's per-line timestamp
     (`2026-10-13T00:51:07.5246531Z `, 29 characters a line) or the byte-order mark of the first line, so about a
     third of the 3,000-character budget holds timestamps.
   - `ci_detail` (`src/l4/verifier/preconditions.py:76-88`) then keeps the end of that tail, and the fix unit's spec
     flattens it (`_plain`, `_line`), which turns `##[warning]` into `##(warning)`.
   - No failing step was named. `GitHubForge.job_log` returns `step=None` by design (`github.py:598-600`), and
     `derive_ci_steps` reads only `.gitlab-ci.yml` (`preconditions.py:134-160`), so a GitHub job's `ci.step` says `no
     failing step in the log`. The jobs API knows the failing step's name and conclusion; nothing reads it.
   - GitLab has the same class of problem in a smaller form: `_read_trace` drops the runner's upload and cleanup
     sections (`src/l4/forge/gitlab.py:72-75`) but keeps `after_script`, whose output comes after the job's error
     (`docs/runner/live-m0-2026-10-04-job-5420.txt:88-106`: an `l4 status` table between the traceback and `ERROR: Job
     failed`). A long `after_script` pushes the error out of the 40 lines.
2. **The gates hid behaviour that only CI has.** The failing test asserted on `--help` text. Typer forces a terminal,
   so rich writes ANSI codes, when `GITHUB_ACTIONS`, `FORCE_COLOR` or `PY_COLORS` is set (`typer/rich_utils.py:78-84`,
   typer 0.26.8 and 0.27.1). The repository's CI sets `GITHUB_ACTIONS=true`; L4's gate environment is built from an
   allow-list (`src/l4/sandbox/env.py:10-13`: locale, `TERM`, proxies) that drops `CI`, `GITHUB_ACTIONS`, `GITLAB_CI`
   and every colour variable. So the unit's gates passed, the repository's CI failed, and a fix unit's gates could not
   reproduce the failure either.

## What Changes

- **The excerpt of a red GitHub job is the failing step's** (L4-VER-061). The forge reads the job's steps
  (`GET actions/jobs/:id`), finds the first `##[error]` line of the log (at or after the start of the step the API
  names as failed), and takes that step's section: its `Run …` header, then the last 40 lines up to the next step, the
  post-job lines or the end of the log. Timestamps and the byte-order mark go; `##[error]` and `##[warning]` read
  `Error:` and `Warning:` as on GitHub's page. `ci.failed.jobs[]` records `failed_step`, the step's name. A log
  without `##[error]` keeps today's tail (without timestamps); no log keeps today's empty tail.
- **The excerpt of a red GitLab job ends with the job's script** (L4-VER-062): the `step_script` section's last 40
  lines and the closing `ERROR: Job failed: …` line; `after_script` and the cache upload are left out. A trace without
  a `step_script` section keeps today's tail.
- **The excerpt keeps the failure's summary lines** (L4-VER-063). Lines of the failing step that come before the last
  40 and match a short list (pytest's `FAILED` and `ERROR` lines and its first `E` lines, a count such as `1 failed`,
  jest, vitest and go `FAIL` lines, GitHub `Error:` annotations) are kept between the header and the tail, within the
  3,000 characters.
- **The blocker's detail names the step and leads with the failure** (L4-VER-064). `job … failed in step `<name>` on
  the hand-off commit …`, then `Failed: <summary lines>` when they are not already in the end of the log it quotes, then
  `Log ends: …`, within the 600 characters every fix spec keeps. A GitHub job's `ci.step` is skipped with its own
  reason: a GitHub step is named, not re-run.
- **Gates see the CI's identity and colour variables** (L4-SEC-040). When the harness runs in CI (`in_ci`: `CI`,
  `GITHUB_ACTIONS` or `GITLAB_CI` is `true`), every gate process (setup, build, lint, typecheck, test, e2e, a
  `repository-ci:` step) also gets `CI`, `GITHUB_ACTIONS`, `GITLAB_CI`, `FORCE_COLOR`, `NO_COLOR`, `PY_COLORS`,
  `CLICOLOR`, `CLICOLOR_FORCE` and `TTY_COMPATIBLE` as the job has them, each only when its value is a short word
  (at most 16 letters, digits, `.`, `_`, `-`). Agent processes do not. No path or token variable of the CI is passed.
  Outside CI nothing changes; `CI=true l4 run` opts in. `run.started` records the names (`gate_env_ci`), and a refused
  value is named once as a WARNING, never shown.
- **The implementer is told** (L4-IMP-080). When the gates carry those variables, the gate section of the red, green
  and single prompts names them and says that a test of a command's help or output must not depend on colour.
- **Docs**: SPEC (L4-VER-061 to L4-VER-064, L4-SEC-040, L4-IMP-080, SCN-VER-215 to SCN-VER-229, SCN-SEC-100 to
  SCN-SEC-103, SCN-IMP-396; L4-ARC-002, L4-SEC-001 and §12.1 name them; change-table row 62), the runbook's "Your own
  CI is red" paragraph, the skill's operate reference, and CHANGELOG `## 0.4.21 (unreleased)`.

## Impact

- Code: `src/l4/forge/logexcerpt.py` (new, pure: the GitHub sections, the summary lines, the composition),
  `src/l4/forge/base.py` (`JobLog.failed_step`), `src/l4/forge/github.py` (`job_log` reads the steps and composes;
  `job_log_tail` is its tail), `src/l4/forge/gitlab.py` (`_read_trace` keeps the script section and the closing line),
  `src/l4/forge/local.py` (scripted `failed_steps`), `src/l4/ci/sweeper.py` (`_log` redacts `failed_step`; the entry
  records it), `src/l4/verifier/preconditions.py` (`ci_detail`, `ci_blockers`, `derive_ci_steps`),
  `src/l4/sandbox/env.py` (`gate_ci_env`, `refused_ci_env`, `build_gate_env`), `scripts/runner/ci-probe-m15.sh`
  (`m0_gate_env`, the shell twin), `src/l4/orchestrator.py` (`_job_facts`, the WARNING in `run_command`),
  `src/l4/implementer/prompt.py` and `src/l4/implementer/tdd.py` (`PromptContext.gate_env_ci`).
- Ledger: new optional keys `ci.failed.jobs[].failed_step` and `run.started.gate_env_ci`. Older ledgers and readers
  are unaffected: a missing `failed_step` gives today's text.
- Behaviour change: in CI, the gates run with `CI=true` and the forge's own flag. Tools behave as in the repository's
  CI: pytest stops truncating assertion messages, jest and vitest do not write a new snapshot, pnpm installs with a
  frozen lock file, typer and rich colour their output. A test that only the repository's CI failed now fails in the
  unit's own gates, before the hand-off. `l4 ci watch --tail N` prints the last lines of the failing step on GitHub.
  One more read per red GitHub job (`actions/jobs/:id`, at most `MAX_TAILS` = 3 per sweep).
- No configuration key, no runtime dependency, no prompt template file or template version change (the gate section is
  built in code), no doctor check.
- Spec: L4-VER-061 to L4-VER-064, L4-SEC-040, L4-IMP-080, SCN-VER-215 to SCN-VER-229, SCN-SEC-100 to SCN-SEC-103,
  SCN-IMP-396, change-table row 62 (rows 59 to 61 are the parallel drafts `verifier-cap`, `judge-parts` and
  `reject-reason`, which all wrote 59 on their own branches).
