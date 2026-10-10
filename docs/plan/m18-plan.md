# M1.8 — easy adoption (planned 2026-10-05)

## Goal

Setting up L4 from zero on `example-group/sample-consumer` (project 119) on 2026-10-05 took **37 maintainer commands
and 2 file edits**. The goal is "a script or a couple of commands". M1.8 adds `l4 setup gitlab` (the forge side in the
l4 CLI), makes `l4 init` write the CI include, adds `l4 doctor --adoption` (config rows plus a dry run of the gates at
the base), and fixes the six run-behaviour findings of job 5561 (R1–R6). **Target for a new project: 5 commands, 0
file edits on a green base** (section "Target command sequence"). **38 build lines**, test first.

Finding ids: A1–A13 adoption, R1–R6 run behaviour (the task brief of 2026-10-05).

## Coverage: finding → build lines

| Finding | Lines | Finding | Lines |
|---|---|---|---|
| A1 init never writes `.gitlab-ci.yml` | 24, 25 | A10 forge setup is scripts, not the CLI (the headline) | 27–35, 37 |
| A2 default lint fails, setup ignores extras, doctor silent | 18, 20–23 | A11 runner type unchecked, CI-002 not registered | 15, 32 |
| A3 no gate dry run at adoption (no GATE-001) | 16–19, 34 | A12 `mk-gitlab-api.sh` hides HTTP errors | 38 |
| A4 no config-only doctor scope | 12 | A13 no pipeline watcher | 36 |
| A5 `.serena/project.yml` written when ignored | 13, 14 | R1 wrong red advice for an import error | 1 |
| A6 list keys replace defaults | 9, 10 | R2 red and green share one budget | 2 |
| A7 stand-in-only S1 config confusing | 11 | R3 parking writes nothing on the MR | 7 |
| A8 `.l4-out/` committed before init | 26 | R4 auth failure cools down 30 min | 3, 4 |
| A9 no pipeline schedule for the sweep | 31 | R5 no `exit_reason`, no event for the failed judge choice | 5, 6 |
| | | R6 MR title repeats the unit name | 8 |

## Facts this plan rests on

Labels: [V] read in code, files, a log, the GitLab API or a probe at `8f604a5`; [I] inferred; [U] not checked.
The job 5561 evidence (log, ledger, `outcome.json`, MR JSON) is local only (`docs/adoption/sample-consumer/live/`
is git-ignored: it holds the private project's source text). Nothing from it is quoted below except harness lines.

* **Job 5561, run behaviour** [V log, ledger, outcome.json]:
  * red attempts 1 and 2 failed with `ModuleNotFoundError: import of xattr halted`, and the retry text
    (`tdd.py:172–175`) told the agent about a guarded stub and a `TypeError`. Attempt 3 passed. Green then had one
    attempt left: `failures` counts red and green together (`loop.py:88, 96, 129`).
  * the judge `claude-code` failed the **auth** probe; the unit parked with `retry_after` = park time + 30 min
    (`fallback.py:412–422` falls back to `availability.default_cooldown` when no cool-down is recorded;
    `orchestrator.py:342–344` does the same for a bare `RoleUnavailable`). Until then `plan` says `none`.
  * the ledger holds one `availability.selected` (the implementer's) and nothing for the failed judge choice;
    `outcome.json` has `"exit_reason": null` (`_park` never sets `_exit_reason`).
  * the MR stayed silent: `_park` sets no `_notes`, so the sticky note was not touched.
  * MR title `[l4] build-without-extra-modules: build-without-extra-modules`: `proposal_title` strips `Proposal:` from
    the heading `# Proposal: <name>` and returns the name (`archive.py:56–80`).
  * `gate baseline fail (192 tests: 188 passed, 4 failed)`: failures at the base, on the runner, before any agent.
* **Auth failures are re-probed on every run** [V `fallback.py:381–394` `_remember`]: only a success or a failed
  `hello` is cached. So "re-probe on the next run" needs no cache change, only a `retry_after` that is already due.
* **Scratch probe at `8f604a5`** [V, a fresh repo with `.serena/` in `.gitignore`, run from this worktree]:
  * `l4 init --ci gitlab --vendor` wrote `.serena/project.yml` into the ignored directory, wrote no `.gitlab-ci.yml`,
    printed the include snippet (A1, A5);
  * `l4 doctor` on this Mac exits **3** only because ENV-004 fails (`codex not found`), a runner-only row (A4);
  * `l4 plan` in a repo without `.gitignore` leaves `.l4-out/outcome.json` and `.l4-out/l4.env` untracked (A8).
* **GitLab, read-only, 2026-10-05** [V through `mk-gitlab-api.sh`, `/tmp/l4gl.env` removed after]:
  * project 119: `visibility: private`, `default_branch: main`, `shared_runners_enabled: true`;
  * `GET projects/119/runners` lists #8 `docker-runner` and #12 `l4-runner`, **both `instance_type`**, online;
    with `?tag_list=agentic` only #12. So the endpoint includes instance runners, and the tag filter works;
  * `GET projects/119/pipeline_schedules` is `[]` (A9).
  * Not checked [I]: that a plain Maintainer token (not the proxy's credential) may list runners and create schedules;
    that a schedule runs as its owner, who must be allowed to run pipelines on the protected default branch.
* **The verifier blocks on base failures** [V `verifier/gates.py`]: step 2 stops at the first failing setup, build,
  lint or typecheck command (a blocker), and step 3 (`_judged`) fails on any failing test. The implementer tolerates
  both at the base (`tdd.py` `static_baseline`, `baseline`). So a base that fails lint or a test makes every unit FAIL.
* **A Mac cannot see the sample-consumer base failures** [V analysis 3.1: all four are
  `ModuleNotFoundError: xattr` on Linux; I: macOS has `xattr`]. A local dry run is platform-dependent; the runner is the
  truth. This is why setup ends with a check pipeline (decision 7).
* **CI template** [V `ci/templates/l4.gitlab-ci.yml`]: the one job `l4` is in stage `.post`, `tags: [agentic]` is
  written literally (`ci.runner_tags` exists in the schema, default `[agentic]`, and the template ignores it), the
  rules already start it for `schedule|web|api|trigger` pipelines, and line 39 is
  `.l4/bin/l4 doctor --ci --fix || .l4/bin/l4 ci map-exit $?`.
* **A pipeline whose only jobs are in `.pre`/`.post` is not created** [V analysis EDIT B; I GitLab docs]. An
  include-only `.gitlab-ci.yml` therefore runs nothing.
* **Pushing before setup makes the first pipeline red** [V `checks_ci.py` CI-001, job 5561 doctor table]: runner #12
  rewrites origin URLs, and CI-001 then fails (error) while `L4_FORGE_TOKEN` is unset.
* **The scripts being ported** [V `scripts/forge/`]: `gitlab_bot_token.py` (stdlib, `--api-base`, `--auth-env`,
  `--auth-scheme private-token|bearer`, `--verify-base`, `--rotate`, variable masked/raw/not protected, environment
  scope `l4`, warns about an unscoped twin, never prints the value); `gitlab_ci_var_from_mintkey.py` (same for one
  Mintkey secret); `mk-gitlab-bot-token.sh` (brokered JWT into the environment, then `exec` with the proxy form).
  `tests/unit/forge/test_ci_variable_scripts.py` pins them.
* **`mk-gitlab-api.sh`** [V]: `curl -s` without `-f` on all three calls; the cache path `/tmp/l4gl.env` is hard-coded.
* **A new command needs a SPEC row** [V `tests/unit/cli/test_dispatch.py`]: `HANDLERS` must equal the set of SPEC
  §2.1 commands written in the test, plus `s1`. A new requirement needs a scenario, or `scripts/check_spec.py` fails
  [V `check_spec.py`].
* **SCN-INS-12** [V `openspec/changes/forge-and-ci/specs/install-init/spec.md:49`] says an existing top-level
  `include:` makes `l4 init` exit 2. M1.8 narrows it (decision 4).
* **List keys** [V `schema.py:91–103`]: `tdd.test_support_globs`, `tdd.test_globs`, `odd.forbidden_paths` are plain
  lists with defaults; setting one replaces the defaults.
* **Step 8** [V `ladder.py:721–745, 1019`; `s1_step.py:69–72`]: wired whenever `roles.s1_judge` is non-empty; an
  adapter profile there makes `open_s1_backend` raise, so step 8 is `unavailable` on every round.
  `preflight.py:34–37` requires a non-empty `roles.s1_judge` for `clarifier.s1_standin: llm_boolean`.
* **Mirror** [V `archive.py:175–182`]: `sync` does nothing before the branch is pushed, and replaces the sticky note
  only when given notes (`()` writes "Nothing is waiting for a human answer.").

## Target command sequence (a new project)

`H` = a clean harness checkout. Run from the project's checkout, which has a committed `uv.lock` and an `origin` on the
GitLab server.

```bash
1  uv run --frozen --project "$H" l4 init --ci gitlab --vendor     # config, vendor, CI include + tagged test job, .gitignore
2  .l4/bin/l4 doctor --adoption                                    # config rows + gates at HEAD (setup, lint, test)
3  git add .l4 .gitignore .gitlab-ci.yml && git commit -m "Adopt the L4 harness"
4  git push -o ci.skip -u origin main                              # no pipeline yet: the token does not exist
5  GITLAB_TOKEN=<maintainer PAT> .l4/bin/l4 setup gitlab --project group/name --watch
   # the maintainer's Mintkey form of step 5:
   #   "$H"/scripts/forge/mk-l4-setup-gitlab.sh --project group/name --watch
```

**Count: 5 commands, 0 file edits** when the base is green (37 + 2 on 2026-10-05). Conditional extras:
* `git remote add origin <url>` when the repository was never on the server (+1);
* config edits that `doctor --adoption` (step 2) or the check pipeline (step 5) asks for, when the base is not green;
* creating the project: GitLab's push-to-create makes step 4 create a private project in a namespace where the pusher
  may create projects [I, checked in the live protocol]; otherwise one click or API call before step 4 (+1).

What step 5 does, in order (each a line of output, never a value): reads the project; lists online runners with the
configured tags and reports their type; reads `.gitlab-ci.yml` on the default branch; ensures the bot token and the
masked `L4_FORGE_TOKEN` scoped to environment `l4` (rotates only on `--rotate`); sets each `--secret NAME=ENV`;
ensures the `l4 sweep` schedule (`*/30 * * * *`, SPEC L4-CI-001); triggers one pipeline on the default branch with
`L4_ADOPTION_CHECK=1` (the runner-side gate check, decision 7) and, with `--watch`, follows it to the end.

## Decisions

1. **`l4 setup gitlab`** (new command, `src/l4/setup/gitlab.py`; HTTP in `src/l4/forge/gitlab_admin.py`):
   * options: `--project <id|group/path>` (required; a `%2F`-encoded path is decoded once, then encoded once),
     `--api-base` (default `forge.gitlab.api_url`, else derived from `origin`: `https://<host>/api/v4`),
     `--auth-env` (default `GITLAB_TOKEN`), `--auth-scheme private-token|bearer` (default `private-token`),
     `--verify-base` (where the new bot token is verified; default `--api-base` for `private-token`, and
     `forge.gitlab.api_url` or the `origin`-derived base for `bearer`, because a proxy injects its own credential),
     `--rotate`, `--revoke-old` (only with `--rotate`), `--secret NAME=ENV` (repeatable), `--cron EXPR`,
     `--no-schedule`, `--no-pipeline`, `--watch`, `--dry-run`;
   * constants as in the script: token `l4-bot`, Developer, scopes `api,write_repository`, 365 days, variable
     `forge.token_env`, environment scope `l4` (the template's environment);
   * it reads `.l4/config.yaml` of `--repo` (default: the current directory) when present, for `forge.gitlab.api_url`,
     `forge.token_env`, `ci.runner_tags` and `forge.base_branch`; without one it uses the schema defaults
     (`L4_FORGE_TOKEN`, `[agentic]`) and says so in a row, so it also runs from the harness checkout. A config that
     exists and does not validate is exit 2, as for every command;
   * the client: https, or plain http to a loopback host (the Mintkey proxy), no redirects, `x-next-page` paging,
     30 s timeout. An HTTP error is `AdminError(method, path, status, body[:300])` with every credential cut out.
     Request headers and `variables` response bodies are never logged;
   * output rows `OK | NEW | SET | KEPT | WARN | FAIL <subject> <detail>`, then a summary. Every byte goes through a
     `Redactor` seeded with the maintainer credential, the bot token and every secret value;
   * exit 0 (no FAIL row), 3 (a FAIL row: no usable runner, a token that fails verification), 2 (usage: empty
     `--auth-env`, an empty `--secret` source, a bad project), 1 (an HTTP error: the rows printed so far say what
     was done). `--dry-run` sends only GETs and prints what it would change.
2. **Idempotence.** A second run with the same arguments sends only GETs (plus the check pipeline unless
   `--no-pipeline`). The token is kept while an active `l4-bot` token **and** the scoped variable exist. A missing
   variable creates a new token (the old value cannot be read back) and warns that the old token is still active.
   `--rotate` creates, sets, verifies; `--revoke-old` then revokes the older active `l4-bot` tokens. A `--secret` is
   compared in memory: equal → KEPT, different → SET, missing → NEW. An unscoped twin (`*`) is reported, never deleted.
3. **Runners** (`GET projects/:id/runners?tag_list=<ci.runner_tags>`): no online runner → FAIL ("the l4 job would
   stay pending"); only instance runners while `shared_runners_enabled` is false → FAIL; an `instance_type` runner on
   a private project → WARN ("any project of this GitLab whose jobs carry these tags can run on runner #N, next to
   this project's checkout and the runner's agent logins"); group or project runner → OK. The type is printed.
4. **`l4 init` edits `.gitlab-ci.yml`** (`src/l4/init/ciedit.py`, forge-and-ci 1.22, SCN-INS-12 narrowed):
   * absent: write the include **and** a `test` job in stage `test` with `tags: <ci.runner_tags>`, the setup commands
     and the test command of the proposed gates, and a first script line that exits 0 on a `schedule` pipeline (the
     job keeps the sweep's pipeline alive — a `.post`-only pipeline is not created — at a cost of seconds);
   * present without a top-level `include:`: insert the snippet after the leading comment block, bytes otherwise
     unchanged;
   * present with a block-list `include:`: insert one `- local: .l4/ci/l4.gitlab-ci.yml` item with the list's
     indentation;
   * already included: nothing;
   * any other `include:` form (a scalar, a flow list, a mapping): exit 2 and print the snippet, nothing written;
   * the edit never reorders or removes a job: the parsed document after the edit equals the one before, with the
     include list extended, and the job keys keep their order (the property every `ciedit` test asserts);
   * CRLF files stay CRLF; `--no-ci-edit` prints the snippet as today; a file whose jobs are all in `.pre`/`.post` gets
     a warning.
5. **`l4 doctor --adoption`.** A new scope `config` marks the rows that depend only on the repository (CFG-*, SPEC-*,
   MEM-*, CI-002); `adoption` marks GATE-001. `--adoption` runs `{config, adoption}`, so ENV-*, PRV-*, SANDBOX-*,
   COV-001 and LIVE-* do not run on a laptop. `--adoption --no-gates` runs only `config` (seconds, no venv: the
   config-only check A4 asked for). `--ci --adoption` runs `{ci, config, adoption}`. Plain `doctor` is unchanged
   (`config` rows also carry `ci` and `local`).
6. **GATE-001** (error, scope `adoption`): `gates.setup` (network on), `build`, `lint`, `typecheck`, then
   `gates.test.command` with its report, in a detached worktree of HEAD under `$L4_CACHE/adoption/<sha12>` (removed
   after). It reports per gate pass/fail, the failing test ids (10 at most, then a count) and the first lint lines,
   and says "HEAD <sha10>; uncommitted changes are not included". Sandbox: bwrap when it is usable; otherwise, outside
   CI only, the gates run unsandboxed (it is the maintainer's own committed code) and the row says so; in CI without a
   usable sandbox the row fails. Suggestions in the fix column (`src/l4/gates/suggest.py`):
   * a test failing with `ModuleNotFoundError: X` where a pyproject extra lists a distribution named X (normalised
     `-`/`_`, lower case) → "add `--extra <extra>` to gates.setup";
   * a failing `ruff check` command → the same command with `--select F,E9`, run once; suggested when it passes, else
     `lint: []`;
   * failing tests at the base → "every verification FAILs step 3 until they pass; fix them first, or deselect them
     in gates.test.command (`--deselect <id>`)".
7. **Runner-side check.** The template's doctor line becomes
   `.l4/bin/l4 doctor --ci --fix ${L4_ADOPTION_CHECK:+--adoption} || .l4/bin/l4 ci map-exit $?`. The variable's value
   is never expanded into the command line, only tested for being non-empty, so a pipeline variable cannot inject
   flags. `l4 setup gitlab` (unless `--no-pipeline`) triggers `POST projects/:id/pipeline` on the default branch with
   `L4_ADOPTION_CHECK=1`: GATE-001 then runs on the runner, in the gate sandbox, with the runner's platform. A failing
   GATE-001 makes the `l4` job exit 3, so `plan` and `run` do not start. Step 4 pushes with `-o ci.skip` because the
   token does not exist yet (Facts).
8. **`l4 init` reads `pyproject.toml`** (`src/l4/init/ecosystem.py`, forge-and-ci 1.19 reduced to uv/pytest/ruff,
   L4-GAT-003): `dev` as an extra → `uv sync --frozen --extra dev`; `dev` as a dependency group → `uv sync --frozen`;
   other extras are listed as not installed, and `--all-extras` is never written (a heavy extra such as `embed`
   pulls torch); no `uv.lock` → keep `--frozen` and say "run `uv lock` and commit it"; no ruff → `lint: []`; no pytest
   or no coverage → a note. Every assumption becomes a `# TODO:` line at the top of `.l4/config.yaml`.
9. **CI-002** (`checks_ci.py`, scopes `ci, local, config`, forge-and-ci 2.19): jobs come from `.gitlab-ci.yml` and its
   `include: local:` files (one level; remote, project and template includes are listed as "not checked"). A job's
   tags, or `default: tags` when it has none, must contain every tag of `ci.runner_tags`; a `$VARIABLE` tag is "not
   checked". The `l4` job missing a tag is a **fail at error** (SCN-CI-06), so is a template whose tags differ from
   `ci.runner_tags`. A repository job missing a tag is a **fail at warn**, naming the jobs ("runs on any runner of the
   instance: your code leaves the tagged runner"). Reason: sample-consumer's `test` job is untagged on purpose
   (owner decision O8, runner #8 with a container image); an error would turn its every `l4` job red on upgrade.
10. **R4.** `_nothing_usable` takes `retry_after` from the earliest cool-down of the chain; when no profile of the
    chain is cooling, every failure was binary, auth, hello, a constraint or `serves`, so `retry_after` = now: the
    next run (any pipeline) probes again. `WaitingCapacity` gains `unready: tuple[Unready, ...]`
    (`profile, adapter, auth, step, reason`) for those failures. `_park` adds the default cool-down only for a bare
    `RoleUnavailable` (as today).
11. **R3.** `_park` sets the sticky section "Waiting for capacity" before the phase change, built from the
    exception: per unready profile the step and reason, plus `provision.readiness.steps_for(adapter, auth)` for an auth
    failure ("then run a pipeline on `<base>`, or wait for the `l4 sweep` schedule"); for a cool-down, the time it
    ends and "the scheduled sweep resumes the unit after that; without a schedule, run a pipeline after <time>".
    `CAPACITY_RESTORED` sets `_notes = ()`, which clears it (as M1.7 clears the base-conflict note). Before the branch
    is pushed there is no MR, so only `exit_reason` and the log carry it.
12. **R5.** `_nothing_usable` appends `availability.unavailable{role, required, skipped: [Skipped.to_event()...],
    retry_after}` before raising (also for an optional role); `_park` sets `_exit_reason` to
    `waiting_capacity: <reason>` (300 characters). `fold` ignores unknown events [V `fold.py:3`], so no fold change.
13. **R2.** Each phase (`red`, `green`, `single`) has its own `max_task_attempts`. `task.attempt_failed.attempt` and
    the log line count per phase; `breaker.tripped` gains `phase`; the halt reason names the phase.
14. **R1.** The "neither an assertion nor NotImplementedError" reason keeps its first sentence; the advice depends on
    the exception names of the wrong tests: `ImportError`/`ModuleNotFoundError`/`SystemExit` → "the test blocks an
    import on purpose and the code under test raised it: catch `ImportError` (and `SystemExit`) in the test and call
    `pytest.fail(...)` with what should have happened"; `TypeError` → the guarded-stub text as today; anything else →
    "make the test fail by assertion: catch the error and call `pytest.fail`, or stub the missing symbol with
    `raise NotImplementedError`". Several kinds → each advice once.
15. **R6.** A heading equal to the unit name (case, `-`, `_` and spaces ignored) is not a title: the Why line is used,
    else the title is `[l4] <name>`.
16. **A6.** `odd.extra_forbidden_paths`, `tdd.extra_test_support_globs` and `tdd.extra_test_globs` are appended
    (deduplicated) to the base list after validation, so every reader sees the merged list. CFG-005 (warn,
    `config` scope) names the defaults that an explicitly set base list drops and points to the `extra_` key.
17. **A7.** Step 8 is wired only when `roles.s1_judge` holds a `backend: system-one` profile. Otherwise step 8 is
    `not_run` "no System One profile on roles.s1_judge (an adapter profile there serves only the clarifier's
    llm_boolean stand-in)". The preflight message for `llm_boolean` says the same.
18. **A5.** `init` asks `git check-ignore` about `.serena/project.yml`; when ignored it writes no seed, writes
    `memory: {enabled: false}`, and prints the carve-out. MEM-002 (warn) reports memory on with ignored harness paths,
    with the same carve-out. The carve-out is tested with real `git check-ignore`, not assumed.
19. **A8.** Whoever creates `.l4-out/` creates `.l4-out/.gitignore` (`*`), so the directory ignores itself before
    `init` has touched `.gitignore`. The CLI seals it before dispatch (best effort, an `OSError` is ignored).
20. **A13.** `l4 ci watch --project P [--pipeline ID | --ref REF]` with the auth options of decision 1,
    `--interval` (15 s), `--timeout` (90 min), `--tail N` (last N trace lines of each failed job, ANSI stripped; 0 by
    default). One line per job status change (`job <id> <name> (<stage>) <status> — runner #<id> <description>`), a
    final table, "failed (allowed)" for an allowed failure; exit 0 for a successful pipeline, 1 for failed, canceled
    or timed out. `setup --watch` uses it with `--tail 60`.
21. **Mintkey stays outside the harness.** `scripts/forge/mk-l4-setup-gitlab.sh` gets the brokered JWT into the
    environment (never argv, never disk), maps `--mk-secret NAME=<mintkey secret>` to an exported variable plus
    `--secret NAME=<that variable>`, and `exec`s `${L4_BIN:-.l4/bin/l4} setup gitlab` with the proxy form. The old
    scripts stay, with a docstring line pointing to `l4 setup gitlab`; their removal is deferred.

## Deviations from the brief

* **CI-002 warns, not errors, for repository jobs** without the runner tags (decision 9); the `l4` job missing them
  is an error. An error would turn every `l4` job of sample-consumer red (its `test` job is untagged by O8).
* **The adoption push uses `-o ci.skip`, and `l4 setup gitlab` triggers one pipeline by default** (decision 7), with
  `L4_ADOPTION_CHECK=1`. Without it the first pipeline is red (CI-001, no token yet), and the runner-side gate check
  would not exist. `--no-pipeline` turns it off.
* **`--revoke-old`** is added (opt-in, only with `--rotate`), so a rotation can finish without a hand revoke.
* **`init` writes a tagged `test` job** when it creates `.gitlab-ci.yml` (not only the include): an include-only file
  runs no pipeline.
* **`--no-gates`** on `doctor --adoption` gives the config-only check of A4 without running the suite.

## Build lines

Line format: `n. task — what · test (write it first, see it fail) · code · verify`. Stage A touches only run-behaviour
files and can go first or in parallel with B. Stage C needs line 15's job reader (line 24 asserts CI-002 on init's
output). Stage D needs lines 15 and 21. Verify commands never pipe into `tail`; the full suite runs in the tool's
background mode.

**Stage A — run behaviour (R1–R6)**

1. L4-IMP-002 (R1) — red retry advice by exception kind (decision 14) ·
   `tests/unit/implementer/test_tdd_red.py::test_import_error_red_advises_catching_it_and_pytest_fail`,
   `::test_type_error_red_keeps_the_guarded_stub_advice`, `::test_mixed_kinds_give_each_advice_once` ·
   `src/l4/implementer/tdd.py` (`classify_red`) · `uv run pytest tests/unit/implementer/test_tdd_red.py
   tests/unit/implementer/test_guard_notes.py -q`
2. L4-IMP-008 (R2) — per-phase budget (decision 13): red fails twice then passes, green fails twice then passes →
   `done`; three red failures halt naming `red` ·
   `tests/unit/implementer/test_loop.py::test_green_has_its_own_attempt_budget_after_a_late_red`,
   `::test_red_budget_exhausted_halts_with_phase_red`, `::test_single_phase_budget_unchanged` ·
   `src/l4/implementer/loop.py` (`run_task`), `src/l4/progress.py` if the attempt line changes ·
   `uv run pytest tests/unit/implementer/test_loop.py tests/unit/obs -q`
3. L4-AVL-007 (R4) — no cool-down in the chain → `retry_after` = now, `unready` filled; a limit keeps its reset ·
   `tests/unit/availability/test_fallback.py::test_auth_failure_parks_due_now_not_after_the_default_cooldown`,
   `::test_limit_failure_keeps_the_cooldown_reset`, `::test_mixed_auth_and_cooling_takes_the_cooling_reset` ·
   `src/l4/availability/fallback.py` (`_nothing_usable`), `src/l4/availability/errors.py` (`WaitingCapacity.unready`),
   `src/l4/verifier/selection.py` (`no_independent_verifier` keeps `unready`) ·
   `uv run pytest tests/unit/availability tests/unit/verifier/test_selection.py -q`
4. R4 end to end — a unit parked on an auth failure is due on the next run: `plan` gives `verify` at once; the
   re-probe on a fixed login resumes it ·
   `tests/unit/orchestrator/test_run_unit.py::test_auth_park_is_due_on_the_next_run`,
   `tests/unit/planner/test_capacity_row.py::test_retry_after_equal_to_now_is_due` · `src/l4/orchestrator.py` (`_park`)
   · `uv run pytest tests/unit/orchestrator tests/unit/planner -q`
5. L4-AVL-008 (R5) — `availability.unavailable{role, required, skipped, retry_after}` on a failed selection ·
   `tests/unit/availability/test_fallback.py::test_nothing_usable_emits_availability_unavailable`,
   `tests/unit/verifier/test_selection.py::test_failed_judge_choice_is_in_the_ledger` · `src/l4/availability/fallback.py`
   · line 3's command
6. L4-AVL-007 (R5) — `_park` sets `exit_reason`; `outcome.json` carries it and `retry_after` ·
   `tests/unit/orchestrator/test_run_unit.py::test_park_writes_exit_reason_to_outcome` · `src/l4/orchestrator.py` ·
   `uv run pytest tests/unit/orchestrator tests/unit/cli/test_outcome.py -q`
7. L4-ARC-002 (R3) — the "Waiting for capacity" sticky section on park, refreshed on a re-park, cleared on
   `CAPACITY_RESTORED` (decision 11) ·
   `tests/unit/orchestrator/test_run_unit.py::test_auth_park_writes_sticky_with_login_steps`,
   `::test_quota_park_names_retry_after_and_the_sweep`, `::test_capacity_restored_clears_the_capacity_note` (fake
   GitLab, as M1.7 line 12) · `src/l4/orchestrator.py` (`capacity_section` next to `base_conflict_section`, `_park`,
   `_drive`) · `uv run pytest tests/unit/orchestrator -q`
8. L4-ARC-002 (R6) — title dedupe (decision 15) ·
   `tests/unit/archive/test_render.py::test_heading_repeating_the_unit_name_falls_back_to_why`,
   `::test_heading_repeating_the_name_without_why_gives_the_bare_title` · `src/l4/archive.py` (`proposal_title` takes the
   name) · `uv run pytest tests/unit/archive -q`

**Stage B — config and doctor (A3, A4, A5, A6, A7, A11)**

9. L4-CFG-001 (A6) — `extra_` keys appended after validation, deduplicated, base list untouched when set explicitly ·
   `tests/unit/config/test_schema.py::test_extra_keys_append_to_the_defaults`,
   `::test_explicit_list_plus_extra_keeps_both_once` · `src/l4/config/schema.py` · `uv run pytest tests/unit/config -q`
10. A6 — CFG-005 (warn; scopes `ci, local, config`): an explicitly set `odd.forbidden_paths` or
    `tdd.test_support_globs` that drops a default names the dropped entries and the `extra_` key (`model_fields_set`) ·
    `tests/unit/doctor/test_checks_config.py::test_cfg005_names_dropped_defaults` (new file),
    `::test_cfg005_passes_with_extra_keys` · `src/l4/doctor/checks_config.py` · `uv run pytest tests/unit/doctor -q`
11. L4-VER-002 step 8, L4-CLR-002 rule 5 (A7) — step 8 `not_run` without a System One profile; the preflight text ·
    `tests/unit/verifier/test_ladder.py::test_step8_not_run_when_s1_judge_holds_only_adapter_profiles`,
    `tests/unit/config/test_preflight_m18.py::test_llm_boolean_message_names_the_role_and_step8` (new file) ·
    `src/l4/verifier/ladder.py` (wiring at line 1019, `_s1_step` reason), `src/l4/config/preflight.py` ·
    `uv run pytest tests/unit/verifier/test_ladder.py tests/unit/config -q`
12. L4-DOC-001 (A4) — scope `config` on CFG-*, SPEC-*, MEM-*, CI-002; scope `adoption`; `--adoption` and
    `--no-gates` flags (decision 5) · `tests/unit/doctor/test_scopes.py::test_adoption_runs_config_and_adoption_scopes_only`,
    `::test_no_gates_runs_the_config_scope_only`,
    `tests/unit/doctor/test_doctor_cli.py::test_adoption_without_agent_clis_exits_0` (a `which` that finds no codex:
    ENV-004 does not run) · `src/l4/doctor/registry.py`, `src/l4/doctor/run.py`, the check modules' scopes,
    `src/l4/cli.py` (doctor flag) · `uv run pytest tests/unit/doctor tests/unit/cli -q`
13. L4-INS-002 (A5) — init: ignored `.serena/` → no seed, `memory.enabled: false`, carve-out printed ·
    `tests/unit/init/test_serena_seed.py::test_ignored_serena_dir_writes_no_seed_and_turns_memory_off` (real git
    repo) · `src/l4/init/init.py` · `uv run pytest tests/unit/init -q`
14. L4-MEM-004 (A5) — MEM-002 (warn; `ci, local, config`): memory on and `.serena/project.yml` or
    `.serena/memories/harness/lessons.md` ignored → the carve-out. The test applies the printed carve-out to the
    `.gitignore` and asserts `git check-ignore` no longer matches either path ·
    `tests/unit/doctor/test_checks_memory.py::test_mem002_carve_out_unignores_the_harness_paths` ·
    `src/l4/doctor/checks_memory.py` · `uv run pytest tests/unit/doctor/test_checks_memory.py -q`
15. CI-002, forge-and-ci 2.19 (A11) — `gitlab_jobs(repo) -> list[CiJob]` (local includes, `default: tags`) and the
    check (decision 9) · `tests/unit/doctor/test_checks_ci.py::test_ci002_fails_for_an_untagged_l4_job` (SCN-CI-06),
    `::test_ci002_warns_for_an_untagged_repo_job_and_names_it`, `::test_ci002_default_tags_satisfy_it`,
    `::test_ci002_template_tags_differing_from_runner_tags_is_an_error`, `::test_ci002_shipped_template_passes` ·
    `src/l4/ci/gitlab_jobs.py`, `src/l4/doctor/checks_ci.py` · `uv run pytest tests/unit/doctor/test_checks_ci.py -q`
16. GATE-001 infrastructure — `dry_run_gates(cfg, repo, environ, *, in_ci) -> GateDryRun` (decision 6): detached
    worktree at HEAD, `run_gate` per command, worktree removed in `finally` ·
    `tests/unit/gates/test_dryrun.py::test_failing_tests_at_head_are_reported_and_no_worktree_is_left` (`tdd_repo`),
    `::test_uncommitted_changes_are_not_in_the_dry_run`, `::test_in_ci_without_a_sandbox_it_fails_instead_of_running`
    · `src/l4/gates/dryrun.py` · `uv run pytest tests/unit/gates/test_dryrun.py -q`
17. A3 — GATE-001 (error, scope `adoption`) over line 16 · `tests/unit/doctor/test_checks_gates.py::
    test_gate001_lists_preexisting_failures_and_exits_3`, `::test_gate001_passes_on_a_green_base`,
    `::test_gate001_names_the_head_and_the_sandbox_state` · `src/l4/doctor/checks_gates.py` (in `CHECK_MODULES`) ·
    `uv run pytest tests/unit/doctor -q`
18. A2, A3 — suggestions (decision 6) · `tests/unit/gates/test_suggest.py::test_missing_module_suggests_the_extra`,
    `::test_failing_ruff_suggests_select_f_e9_when_it_passes`, `::test_failing_narrow_ruff_suggests_empty_lint`,
    `::test_failing_base_tests_suggest_fix_or_deselect` · `src/l4/gates/suggest.py` · `uv run pytest tests/unit/gates -q`
19. L4-CI-001 (A3) — the template's doctor line (decision 7). The test runs the script line with `sh -c` and a stub
    `.l4/bin/l4` that prints its argv: without the variable, with `L4_ADOPTION_CHECK=1`, and with the value
    `1 --live; touch pwned` (argv is exactly `doctor --ci --fix --adoption`, no file created) ·
    `tests/unit/ci/test_template.py::test_doctor_line_adds_adoption_only_from_a_non_empty_variable` ·
    `src/l4/ci/templates/l4.gitlab-ci.yml` · `uv run pytest tests/unit/ci -q`

**Stage C — `l4 init` (A1, A2, A8)**

20. forge-and-ci 1.19, L4-GAT-003 (A2) — `detect_python(repo)` and `propose_gates(eco)` (decision 8) ·
    `tests/unit/init/test_ecosystem.py::test_dev_extra_adds_extra_dev_to_setup`, `::test_dev_group_keeps_plain_sync`,
    `::test_other_extras_are_listed_never_all_extras`, `::test_no_ruff_leaves_lint_empty_with_a_note`,
    `::test_no_lock_says_uv_lock`, `::test_no_pyproject_keeps_the_m0_gates_with_a_todo` ·
    `src/l4/init/ecosystem.py` · `uv run pytest tests/unit/init/test_ecosystem.py -q`
21. L4-INS-003 (A2) — `render_config` takes the proposed gates; `# TODO:` lines name each assumption; the config still
    loads · `tests/unit/init/test_plan_init.py::test_gates_follow_pyproject_and_todos_name_the_assumptions` ·
    `src/l4/init/init.py` · `uv run pytest tests/unit/init -q`
22. A2 — init prints the extras it did not install and "run `l4 doctor --adoption` next" ·
    `tests/unit/init/test_init_cli.py::test_init_names_uninstalled_extras_and_the_next_command` ·
    `src/l4/init/init.py` · same as 21
23. A2 — the sample-consumer shape end to end, offline: a fixture pyproject with extras `dev, otel, index, embed`,
    ruff in `dev`, a test needing the `index` extra; `init` then `doctor --adoption` → setup `--extra dev`, GATE-001
    fails naming the test and suggesting `--extra index`, never `embed` ·
    `tests/unit/init/test_adoption_flow.py::test_extras_project_init_then_doctor_adoption_suggests_the_missing_extra`
    · whatever lines 16–22 missed · `uv run pytest tests/unit/init tests/unit/doctor -q`
24. forge-and-ci 1.22, L4-INS-002 (A1) — `merge_include(text | None, runner_tags, gates) -> CiEdit` (decision 4) ·
    `tests/unit/init/test_ciedit.py::test_absent_file_gets_include_and_a_tagged_test_job`,
    `::test_no_include_is_prepended_and_bytes_are_kept`, `::test_block_list_include_gets_one_item`,
    `::test_already_included_is_a_noop`, `::test_scalar_flow_or_mapping_include_refuses_with_the_snippet`,
    `::test_crlf_stays_crlf`, `::test_only_post_jobs_warns`, `::test_created_file_passes_ci002` (line 15), each asserting
    the parsed-document property of decision 4 · `src/l4/init/ciedit.py` · `uv run pytest tests/unit/init/test_ciedit.py
    -q`
25. A1 — wiring: the edit is part of `InitPlan` (written by `apply_plan`, so a refusal writes nothing), `--no-ci-edit`
    · `tests/unit/init/test_init_cli.py::test_gitlab_init_writes_the_ci_file`,
    `::test_no_ci_edit_prints_the_snippet_and_leaves_the_file`, `::test_refused_ci_edit_writes_nothing` ·
    `src/l4/init/init.py`, `src/l4/cli.py` · `uv run pytest tests/unit/init tests/unit/cli -q`
26. L4-INS-002 (A8) — `seal_out_dir(path)` (decision 19) in the CLI callback and in `write_outcome`/`write_ci_outputs`
    · `tests/unit/cli/test_outcome.py::test_plan_before_init_leaves_git_status_clean` (real git repo,
    `git status --porcelain --untracked-files=all` empty) · `src/l4/fsutil.py`, `src/l4/cli.py`, `src/l4/outcome.py` ·
    `uv run pytest tests/unit/cli -q`

**Stage D — `l4 setup gitlab`, `l4 ci watch`, scripts (A9–A13)**

27. A10 — `AdminApi` (decision 1) · `tests/unit/forge/test_gitlab_admin.py::test_private_token_and_bearer_headers`,
    `::test_http_error_names_the_status_never_the_credential`, `::test_redirect_is_not_followed`,
    `::test_pagination_follows_x_next_page`, `::test_plain_http_only_to_loopback` (httpx `MockTransport`, as
    `test_gitlab_http.py`) · `src/l4/forge/gitlab_admin.py` · `uv run pytest tests/unit/forge/test_gitlab_admin.py -q`
28. A10 — project argument and API base: id, raw path, `%2F` path → one encoding; base derived from `origin` ·
    `tests/unit/setup/test_gitlab_setup.py::test_project_path_is_encoded_exactly_once`,
    `::test_api_base_is_derived_from_origin` · `src/l4/setup/gitlab.py` ·
    `uv run pytest tests/unit/setup -q`
29. A10 — bot token and `L4_FORGE_TOKEN` (port of `gitlab_bot_token.py`; decision 2) · `::test_fresh_project_creates_
    token_and_scoped_masked_variable`, `::test_second_run_sends_only_gets`,
    `::test_missing_variable_creates_a_token_and_warns_the_old_one_is_active`, `::test_rotate_creates_sets_verifies`,
    `::test_revoke_old_revokes_only_after_verification`, `::test_verification_goes_to_verify_base_with_the_bot_token`,
    `::test_unscoped_twin_is_reported_not_deleted` · same file · same command
30. A10 — `--secret NAME=ENV` (port of `gitlab_ci_var_from_mintkey.py`) · `::test_secret_created_then_kept_then_updated`,
    `::test_empty_source_env_refuses_before_any_write`, `::test_bad_variable_name_is_a_usage_error` · same
31. L4-CI-001, L4-CI-004 (A9) — the `l4 sweep` schedule · `::test_schedule_created_once_then_kept`,
    `::test_schedule_with_another_cron_or_ref_is_updated`, `::test_inactive_schedule_is_reactivated`,
    `::test_no_schedule_skips_it` · same
32. A11 — runners and the include on the default branch (decisions 3, 9) ·
    `::test_no_online_tagged_runner_fails_with_exit_3`, `::test_instance_runner_on_a_private_project_warns`,
    `::test_project_runner_is_ok_and_its_type_printed`, `::test_only_instance_runners_with_shared_runners_off_fails`,
    `::test_missing_include_on_the_default_branch_warns` · same, plus line 15's `gitlab_jobs` on the fetched file
33. A10 — the command: `run_setup_gitlab`, summary, exit codes, `--dry-run`, redaction; the CLI group `setup`; SPEC
    §2.1 row, a new requirement L4-INS-006 with scenarios SCN-INS-15 (fresh project), SCN-INS-16 (second run sends only
    GETs), SCN-INS-17 (no runner: exit 3) · `::test_output_and_logs_never_contain_a_secret_value` (capsys and caplog,
    the fake token, PAT and secret values), `::test_dry_run_sends_only_gets`, `::test_exit_codes`,
    `::test_without_a_config_the_schema_defaults_are_used_and_named`;
    `tests/unit/cli/test_dispatch.py` (`SECTION_2_1` and `ARGV` gain `setup gitlab`) · `src/l4/setup/gitlab.py`,
    `src/l4/cli.py`, `src/l4/commands.py`, `docs/SPEC.md` · `uv run pytest tests/unit/setup tests/unit/cli -q` and
    `uv run python scripts/check_spec.py docs/SPEC.md`
34. decision 7 — the check pipeline: one `POST projects/:id/pipeline` with `L4_ADOPTION_CHECK=1` after the token
    exists, URL printed; `--no-pipeline` skips; `--dry-run` never triggers · `::test_pipeline_triggered_once_with_the_
    adoption_variable`, `::test_no_pipeline_and_dry_run_trigger_nothing` · same
35. A10 — a fake-server end to end: empty project → first run creates token, variable, secret, schedule, triggers a
    pipeline; second run sends only GETs and one pipeline POST; output equals the documented rows ·
    `tests/unit/setup/test_gitlab_setup_flow.py::test_first_and_second_run` · whatever lines 27–34 missed · same
36. A13 — `l4 ci watch` (decision 20), injected clock and sleep · `tests/unit/ci/test_watch.py::
    test_one_line_per_status_change`, `::test_allowed_failure_is_success`, `::test_timeout_exits_1`,
    `::test_tail_prints_the_failed_jobs_trace_tail_only` · `src/l4/ci/watch.py`, `src/l4/cli.py`, `src/l4/commands.py`,
    SPEC §2.1 row, `test_dispatch.py` · `uv run pytest tests/unit/ci tests/unit/cli -q`; then `setup --watch` uses it:
    `tests/unit/setup/test_gitlab_setup.py::test_watch_follows_the_triggered_pipeline`
37. A10 — `scripts/forge/mk-l4-setup-gitlab.sh` (decision 21); deprecation line in the two old scripts · `tests/unit/
    forge/test_mk_scripts.py::test_setup_wrapper_passes_the_proxy_form_and_no_jwt_in_argv` (fake `curl` and fake
    `L4_BIN` on PATH, a temp HOME with a fake `.claude.json`; the fake l4 records argv and environment names) · the
    script · `uv run pytest tests/unit/forge/test_mk_scripts.py -q`
38. A12 — `mk-gitlab-api.sh`: first `ENVF=${L4GL_ENV:-/tmp/l4gl.env}` (so the test never touches the maintainer's
    cache), then `-fsS` on the two Mintkey calls, the upstream body to a temp file with `%{http_code}`, body printed,
    exit 22 with `HTTP <code> <METHOD> <path>` on stderr for a status ≥ 400 ·
    `tests/unit/forge/test_mk_scripts.py::test_mk_gitlab_api_exits_22_on_404_and_prints_the_body`,
    `::test_cache_path_is_overridable` · `scripts/dev/mk-gitlab-api.sh` · same command

**Stage E — close-out** (no number: it adds no behaviour)

* `docs/quickstart.md`: the target sequence, the Mintkey form, what each step prints, the expected check pipeline,
  the conditional extras (H10 of the analysis).
* `uv run pytest -q` in the tool's background mode; `uv run ruff check .`; `uv run python scripts/check_spec.py
  docs/SPEC.md`; `uv run l4 simulate --all` (identical to `main`).
* Tick forge-and-ci 1.19 (reduced), 1.22 (as narrowed), 2.19; write `docs/plan/m18-progress.md`; owe the SPEC edits
  below that line 33 did not make.

## Deferred (not in M1.8)

* **Creating the GitLab project** (`setup gitlab --create`): push-to-create or one click covers it; checked live.
* **GitHub `l4 setup github`** (App, secrets, schedule).
* **Recording the runner type in the ledger** (`run.started.runner.type`): needs a Maintainer API call at run time;
  setup reports it instead.
* **Rendering the template's tags from `ci.runner_tags`**: CI-002 catches a mismatch; the template stays static.
* **Schedule pipelines skipping repository jobs**: only init's own `test` job exits early on a schedule; existing
  jobs are the maintainer's.
* **Backoff for repeated auth parks** (see Risks): re-probe every run, as asked.
* **Removing the old forge scripts** and `mk-gitlab-bot-token.sh`; `--token-name`, `--token-days` options.
* **Ecosystems other than uv/pytest/ruff** (L4-GAT-003 npm, go, cargo): `init` keeps a `TODO`.
* **Analysis H-items not in the brief** (H1 `--type change`, H4 docs-only tasks, H7, H11–H20).

## Doc changes owed (not made by the build lines, except line 33's SPEC rows)

* §2.1: `l4 doctor [--adoption]`, `l4 init [--no-ci-edit]`, `l4 setup gitlab …`, `l4 ci watch …` (rows for the two
  new commands are made by lines 33 and 36).
* §15 doctor table: CI-002 (error for the l4 job, warn for repository jobs), GATE-001, MEM-002, CFG-005; the scopes
  `config` and `adoption` in L4-DOC-001.
* L4-IMP-008: `max_task_attempts` per phase. L4-AVL-007: a chain with no cool-down is due at once. L4-AVL-008 and
  12.1: `availability.unavailable`. L4-INS-002: `.gitlab-ci.yml` edit, `.l4-out/.gitignore`, the ignored-`.serena`
  rule. SCN-INS-12 narrowed to the include forms decision 4 refuses. 16.3: the `L4_ADOPTION_CHECK` doctor line.
* L4-NFR-001: the `< 30 s` bound of `doctor --ci` excludes `--adoption` (GATE-001 runs the suite), like `--live`.
* `docs/runner/README.md`: `setup gitlab` replaces the bot-token script section.

## Live protocol

The runner's Claude login is dead and stays so until the maintainer logs in again; nothing here touches it. Logs
(ANSI stripped) go to `docs/live/m18/`. A new private scratch project `example-group/l4-adopt-smoke` (a small uv/pytest
fixture with ruff in `dev`, one deliberate ruff error, and an optional extra that one test needs) proves the sequence;
sample-consumer (119) is touched only by step 6. Its config sets `roles.judges: [claude-code]` only, so the dead
login parks the unit (R3–R5 can be seen now; the rest of the unit waits for a login).

| Step | Action | Expected |
|---|---|---|
| 0 local | full suite at the M1.8 head; `l4 simulate --all` | green; identical |
| 1 | in a clone of the smoke repo: commands 1–2 of the sequence | init writes `.gitlab-ci.yml` (include + tagged `test` job), setup `--extra dev`; doctor `--adoption` exits 3: GATE-001 names the ruff error (suggests `--select F,E9`) and the test needing the extra (suggests `--extra <it>`); no ENV/PRV/SANDBOX rows |
| 2 | apply the two suggestions (2 config edits), re-run doctor `--adoption` (1 command) | exit 0 |
| 3 | commands 3–4 (`git push -o ci.skip`) | no pipeline; the project exists (push-to-create) [I] — if not, create it in the UI, count +1, push again |
| 4 | command 5 with the Mintkey wrapper and `--watch` | rows: project private; runner #12 `instance_type` WARN; include on `main` OK; NEW token, SET `L4_FORGE_TOKEN` (scope `l4`), NEW schedule `*/30 * * * *`; pipeline with `L4_ADOPTION_CHECK=1`: `l4` job doctor shows GATE-001 pass on the runner, then `nothing to do`; watcher exit 0. No value anywhere in the output or the job log |
| 5 | command 5 again (`--no-pipeline`) | only GETs (API audit by count), every row KEPT/OK, exit 0 |
| 6 | `--dry-run`, then a real run against `example-group/sample-consumer` with `--no-pipeline --no-schedule` | dry run: "would create schedule"; real: token and variable KEPT, schedule skipped, #12 instance WARN on a private project. **The schedule on 119 is the maintainer's decision, not part of this protocol**: every 30 min it runs 119's untagged `test` job (~90 s on runner #8) and the `l4` job on runner #12 (`concurrent = 1`, shared with dummy-agentic), and under 119's current vendored harness the parked unit re-parks with a ledger commit whenever its 30-min `retry_after` lapses. Suggest `--cron '0 * * * *'` if wanted |
| 7 | seed one unit in the smoke project (one task); push to `main` | red → green; `verifying`; judge `claude-code` fails auth → `waiting_capacity`, exit 12: `outcome.json` `exit_reason` set, `retry_after` = park time (not +30 min); ledger `availability.unavailable{role: judges}`; MR sticky "Waiting for capacity" with the `claude setup-token` steps; MR title has no repeated name |
| 8 | `l4 ci watch --ref main` while the next scheduled pipeline runs (≤ 30 min) | the unit is re-run (not `none`), re-parks, the note is refreshed, not duplicated |
| after re-login (maintainer) | run a pipeline | the unit resumes at once, verifies; `CAPACITY_RESTORED` clears the note |

Count to report: commands and edits of steps 1–4 (expected 5 commands, plus 1 doctor re-run and 2 config edits caused
by the deliberately red base).
Spend: Codex 2 agent steps; no Claude.

## Risks

* **The check pipeline is the only runner-truth.** A laptop dry run passed the very failures that motivated A3
  (Facts). If a maintainer skips step 5's pipeline (`--no-pipeline`), base failures reach the first unit again.
* **A dead login now re-parks on every run.** With the 30-minute schedule that is one `chore(<unit>): ledger
  [skip ci]` commit per sweep on the unit branch while the login stays dead (the 30-minute cool-down gave the same
  cadence, but the run then exited before any commit). Cheap, noisy; backoff deferred.
* **The schedule runs the repository's jobs too.** Init's own `test` job exits early on a schedule; other jobs run
  every 30 minutes on whatever runner takes them. Setup prints the job names; `--cron` makes it sparser.
* **Permissions not verified** [I]: listing runners and creating schedules with a plain Maintainer PAT; the schedule
  owner must be able to run pipelines on the protected default branch. The live protocol uses the proxy credential,
  so a direct-PAT user may hit a 403 that the error row must explain.
* **Textual YAML edits.** The parsed-document property is the guard; anything outside the recognised forms is refused,
  not guessed.
* **R2 raises the worst case** of agent steps per task from 3 to 6 (3 red + 3 green). `max_task_attempts` still caps
  each phase.
* **`--revoke-old` while a job runs** with the old token: that job's next push fails with an explained 401/403 and
  the next run uses the new token. It is opt-in.
