# Adoption lessons: design

Date: 2026-10-15. Code read at `95851428` (main = origin/amaster; v0.4.0 source `88c6a503` plus one skill document).
Nothing in the repository was changed. The draft change is in `change/` next to this file.

**Labels.** **[V]** verified in this session: code read at the cited `file:line`, a probe run, or a log read.
**[I]** inferred from code or platform behaviour, not tested here. **[G]** a guess that needs a measurement.
**[P]** proposed, not built.

**Sources of the lessons.**
- The first real consumer: a consumer repository, public, base `staging`, the action copy form, OpenCode
  `opencode-go/deepseek-v4.1-flash` implementer, Claude judge. Its job logs, readiness answers and plan files are in
  the session scratchpad (`mm-first-run.log`, `mm-run-38775716596.log`, `mm-review-1..7.txt`, `mm-plan/`) [V].
- The yolo-mode live run's "smaller findings, not yet fixed" (`docs/live/yolo-mode/README.md:155-157`) [V]: items 3–5
  come from there.
- A read-only doc sweep against the code (item 12), and the coordinator's lessons 13 and 14.

**Out of scope here (owned by the review-resolution change):** overriding or accepting readiness findings, a pre-push
local review, per-finding resolution hints from the judge, and the `tasks.md` checkbox normalisation the judge sees.
Where an item touches them, it says "covered by the review-resolution change".

**Requirement ids.** A fresh prefix, `L4-ADO-001..019` with scenarios `SCN-ADO-01..`, so nothing collides with
`L4-YOLO-021+` (likely taken by the review-resolution change) or the self-hosting proposal's `L4-SELF-*`. `L4-ADO`
and `SCN-ADO` are unused today [V grep over `openspec/`, `docs/`, `plugins/`]. The area of each requirement is named
in the summary.

---

## 0. Summary

| # | Lesson | Verdict | Requirement (area) | Cost |
|---|---|---|---|---|
| 1 | Evidence plugins shadowed under `python -m pytest` | **Accept, different fix.** A gate-start guard, not a new command or `PYTHONSAFEPATH`: both break real layouts [V probe] | ADO-001 (GAT) | S |
| 2 | Default branch missing from the environment's deployment branches | **Accept** | ADO-002 (GHP) | S |
| 3 | `init --action` needs `--action-repo` | **Reject the code change**: it already infers from the install [V probe]; only a checkout needs the flag. Fix the message and docs | ADO-018 (docs) | XS |
| 4 | GitLab wording in a GitHub push error | **Accept** | ADO-004 (CI) | XS |
| 5 | Laptop push ignores the https credential helper | **Accept** | ADO-003 (SEC) | XS |
| 6 | L4's PRs never run the repository's CI | **Accept a warning now; defer the CI-green merge precondition** | ADO-006 (DOC) | M |
| 7 | OpenSpec intake refusals give no way out | **Accept three parts, reject one**: the 500-character rule does not fail `--strict` [V probe] | ADO-007, -008, -009 (OSP, YOLO) | M |
| 8 | Readiness size budgets learnt only after a CI round | **Accept** | ADO-010 (YOLO) | S |
| 9 | Spec-authoring guidance in the skill | **Accept** | ADO-014 (SKL) | S |
| 10 | Existing specs need a hold-only backlog plan | **Accept, generalised** as `yolo.hold` (patterns; `"*"` is the self-hosting `require_plan`) | ADO-011, -012 (YOLO, INS) | M |
| 11 | The backlog plan reads "refused" every run | **Accept**: addressed by 10, plus clearer status and all findings printed | ADO-013 (YOLO) | XS |
| 12 | Docs vs today's behaviour | **Accept**: 14 doc fixes, and one new defect: **pin skew** between the default branch's workflow copy and the base | ADO-005 (GHP), ADO-018 (docs) | S |
| 13 | System One unused on the consumer | **Accept, premise corrected**: S1 off costs a person's attention, not paid calls [V]. Per the user's decision, Laya is the default System One: init enables it, provisioning installs and caches it, and doctor reports the engine and whether it starts. The consumer uses Jev | ADO-015, -016, -019 (S1) | M (019: M–L) |
| 14 | The workflow never passes a System One key | **Accept, must-fix** [V repro] | ADO-017 (CI) | XS |

**19 requirements, 54 scenarios, 33 tasks.** The draft change is `change/adoption-lessons/`: proposal, a short design with the decisions D1–D11, five capability specs and the tasks. It is ADDED-only and has a Purpose per capability. It passes `openspec validate --strict` (1.14.0), each file is under 20,000 characters, and the folder is 57,600 characters [V]. When it is committed, this analysis goes to `docs/plan/adoption-lessons.md` (task 9.1), which the change's design names as its evidence.

---

## 1. The items

### Item 1. Test-gate plugin shadowing — accept, with a guard instead of a command change

**Current state.**
- `l4 init` proposes `.venv/bin/python -m pytest --junitxml=.l4-out/junit.xml` as the test gate
  (`src/l4/init/ecosystem.py:16`, used for every pyproject proposal at `:96`) [V]. The eval cell config
  (`src/l4/eval/cellconfig.py:21`) and the S1 canary (`src/l4/s1/canary.py:47`) use the same `-m` form [V].
- The language packs (`src/l4/lang/`) exist only on the unmerged branch an unmerged trial branch. They cover brace languages
  (C#, ECMAScript) and generate no Python test command [V `git ls-tree`, `git grep`].
- `build_gate_env` sets no `PYTHONSAFEPATH` (`src/l4/sandbox/env.py:41-49`) [V]. The plugins are loaded through
  `PYTEST_ADDOPTS=-p l4_trace` / `-p l4_cov` and a `PYTHONPATH` entry (`src/l4/gates/trace.py:17-20`,
  `src/l4/gates/coverage.py` `cov_env`) [V].
- Under `python -m`, the working directory is `sys.path[0]`, ahead of `PYTHONPATH`, so a root `l4_trace.py` replaces
  the pinned plugin (reproduced in `docs/plan/proposal-l4-self-hosting.md`, appendix) [V there]. pytest imports `-p`
  plugins at pre-parse, before any ini `pythonpath` or conftest insertion, so `sys.path[0]` is the only way in [I
  pytest internals].
- `trace.py:1-4` claims "a repository cannot shadow it". That is false under `-m` [V].
- The verifier blocks a **new** module named `l4_trace`/`l4_cov` at any depth (`src/l4/verifier/scan.py:86-109`) [V].
  So today the shadow is caught at verification. It is not prevented during the red/green steps, and a file already
  on the base is not caught at all [I].

**Probe (this session, the repository's `.venv`, Python 3.12) [V]:**

| Command | Result |
|---|---|
| `python scripts/main.py`, which imports a sibling `scripts/sib.py` | ok |
| the same with `PYTHONSAFEPATH=1` | `ModuleNotFoundError: No module named 'sib'` |
| `python -m pytest tests` in a flat, uninstalled layout (`flatpkg.py` at the root) | 1 passed |
| the same with `PYTHONSAFEPATH=1` | 1 failed |
| `.venv/bin/pytest tests`, same layout | 1 failed |

**Decision.**
- **Reject `PYTHONSAFEPATH=1` in `build_gate_env`.** It applies to every gate command, so it breaks lint or check
  scripts that import siblings and flat-layout test suites. Consumers would see it as a silent break on a harness
  upgrade. This supersedes the self-hosting proposal's L4-SELF-015.
- **Reject switching `l4 init` to `.venv/bin/pytest`.** It breaks the same flat layout. It also adds no protection that
  the guard below does not give.
- **Accept a deterministic guard (ADO-001).** Before a test-gate run that loads an evidence plugin, the harness checks
  the gate's working directory for an importable `l4_trace` or `l4_cov`: a module file of any importable suffix, or a
  package `__init__`. It reuses `scan.plugin_module`'s rules. If one is there, the gate does not run: the run records a
  gate error naming the file. The red, green and verification steps are covered, and so is a file already on the base.
  This fails closed and changes no `sys.path` semantics.
  - `coverage` is left out of the guard. A root `coverage.py` can be a legitimate script, and the scan already reports
    a new one.
- Fix the false docstrings (`trace.py:1-4`; the `-m` remark in `scan.py:95` and `l4_cov.py:85` stays true).

**Worth it now?** Yes. About 40 lines plus tests, and no consumer can be broken by it.

### Item 2. The default branch in the environment's deployment branches — accept

**Current state.**
- `l4 setup github` creates the environment with custom branch policies and adds exactly `forge.base_branch`,
  `<prefix>*` and `<prefix>**/*` (`src/l4/setup/github.py:235`) [V].
- GitHub runs `schedule` on the default branch, and a run from the Actions page defaults to it [I platform]. The job's
  ref is then the default branch, which the environment refuses. the consumer needed `main` added by hand [V memory
  record of the adoption]; `adopt.md:109-110` documents the manual step [V].
- The dispatch at the end of setup targets the base (`github.py:296-301`). It answers 404 until the workflow file is on
  the default branch (`docs/live/action/README.md:34-35`, per the doc sweep) [V by the reader].
- `admin()` already reads `GET /repos/{repo}` (`github.py:~199`), whose body carries `default_branch` [I API].

**Decision (ADO-002).** When the default branch differs from `forge.base_branch`:
- add a branch policy for the default branch, as `CREATED` or `KEPT`;
- read `.github/workflows/l4.yml` on the default branch. If it is missing, print a `FAILED` row that says schedule and
  dispatch need it there, and skip the dispatch. If it differs from the base's copy, print a `FAILED` row naming both
  pins (item 12, ADO-005).

**Worth it now?** Yes. It removes a manual step every integration-branch adoption hits. Cost: about 30 lines and fakes
for two more API calls.

### Item 3. `init --action` and `--action-repo` — reject the code change, fix the message and docs

**Current state.**
- `_action_pin` already infers the repository: `--action-repo`, else the slug of `--harness-repo`, else
  `harness_origin()` (`src/l4/init/init.py:462-481`) [V].
- `harness_origin()` reads the install's `direct_url.json` (`src/l4/buildinfo.py:52-61`) [V].
- **Probe [V]:** under `uv tool run --isolated --from git+https://github.com/OWNER/l4@<v0.4.0 sha>`,
  `harness_origin()` returned `OWNER/l4` and `harness_commit()` the release sha.
- The failure in this session's transcript came from an `l4` wrapper over a **checkout**. the consumer's init passed
  `--action-repo` pre-emptively, because `adopt.md:33` shows it [V transcript].
- `docs/live/yolo-mode/README.md:155-156` says "from a worktree checkout" [V].

**Decision.** No inference from a checkout's git remote: a checkout pins its own HEAD, which may be unpushed or
unreleased. Instead:
- the error names the cause ("the running l4 is a checkout or an editable install, which has no install origin; run
  the released l4 (`uv tool run --from git+https://github.com/OWNER/l4@vX.Y.Z l4 …`) or pass `--action-repo
  OWNER/REPO`");
- `adopt.md:33` makes `--action-repo` optional and says when it is needed (ADO-018).

**Worth it now?** Yes, as a docs and message fix only.

### Item 4. GitLab wording in a GitHub push error — accept

**Current state.** For a credential refusal, `explain_push_failure` always says "`{token_env}` must be a project
access token with the write_repository (and api) scopes and the Developer role or higher"
(`src/l4/forge/pushfail.py:80-84`) [V]. The "not set" addition is made only under `GITLAB_CI` (`:85-88`) [V]. The
function takes no platform. Its callers are the plan store, the orchestrator, the archive, follow-ups, post-merge and
restart [V grep].

**Decision (ADO-004).** `explain_push_failure` takes the platform (`forge_platform`):
- **GitHub:** "`{token_env}` needs Contents: write (and Pull requests: write) on the repository; the workflow's
  GITHUB_TOKEN has it when the workflow grants `contents: write`".
- **GitLab:** keeps today's text.
- **Any platform:** if the variable is empty, the hint adds "`{token_env}` is not set". Outside CI it adds the
  ADO-003 note.

**Worth it now?** Yes. A few lines, and one test per platform.

### Item 5. A laptop push ignores the keychain helper — accept

**Current state.** `push_auth_config` always returns `git_auth_config(...)` (`src/l4/forge/gitlab.py:499-507`). That
resets `credential.helper` to empty and installs a helper that prints `$token_env` (`:487-496`), even when the variable
is empty [V]. `fetch_auth_config` returns `()` when the variable is empty (`src/l4/forge/base.py:300-310`) [V]. So a
laptop fetch over https uses the person's keychain, but the push in the same command fails. An SSH remote works,
because helpers do not apply to it [V docs/live/yolo-mode/README.md:157].

**Decision (ADO-003).** `push_auth_config` mirrors `fetch_auth_config`:
- **Outside CI, with the token variable empty:** no helper pairs. The person's own git credentials apply, and nothing
  is written to `.git/config`. The GitLab `pushurl` workaround is still added when CI rewrites the URL.
- **In CI:** unchanged. The token must be there (`require_token_in_ci`).

**Worth it now?** Yes. A few lines. Every laptop operator command that pushes is affected: `l4 yolo activate`,
`cancel`, `resume`, `l4 restart`.

### Item 6. L4's PRs never run the repository's CI — accept a warning now, defer the merge precondition

**Current state.**
- With the workflow `GITHUB_TOKEN`, L4's pushes and PRs start no other workflows (`docs/SPEC.md:3736-3740`, cited by
  the self-hosting proposal) [V there].
- `adopt.md:88-90` already documents `L4_FORGE_TOKEN` and `forge.token_env` [V]. But init's own note says "the forge
  token is the workflow's own GITHUB_TOKEN … so there is none to set" (`src/l4/init/init.py:504-520`) [V], and
  `quickstart.md:213-217` leaves out the `forge.token_env` and `l4 upgrade` steps (doc sweep) [V by the reader].
- The plan merge's preconditions name no CI state (`src/l4/yolo/merge.py:1-16`) [V].
- A repository-CI duty already exists at the hand-off: the sweep reads the project's CI on the hand-off commit, and
  turns red jobs that are new against the base into a fix round. With `GITHUB_TOKEN` it records `ci_not_run` with
  the reason "pushes made with GITHUB_TOKEN start no runs" (`src/l4/ci/repo_ci.py:1-9`, L4-ARC-002 (d), L4-GHP-008;
  `tests/unit/ci/test_repo_ci.py`) [V]. So with a token whose pushes start CI (`L4_FORGE_TOKEN`), the unmirrored
  jobs do run, and the harness acts on them. What stays open is only that a `merge: auto` plan does not wait for that
  verdict [I: not traced through the plan step].
- No doctor row compares the repository's CI with `gates` [V: the registry modules and their ids].
- the consumer's `ci.yml` had a Postgres conformance job and helm/docker validation that the gates do not mirror (lesson
  statement; the readiness review's `feasibility` finding on deployment-hardening agrees, `mm-review-2.txt`) [V].

**Decision (ADO-006).** `l4 doctor --adoption` gets a warning row that:
- parses `.github/workflows/*.yml` other than `l4.yml` (and `.gitlab-ci.yml` through the existing `parse_gitlab_ci`);
- lists each job that runs on `push` or `pull_request` and is not mirrored by the gates. A job counts as mirrored when
  every `run:` command of it, normalised (`uv run `, `.venv/bin/`, `python -m ` stripped), appears in a gate command, a
  gate setup command or a `yolo.profiles` gate. A job with `services:` or a `container:` is reported with that fact;
- when `forge.token_env` is `GITHUB_TOKEN` and `forge.merge_policy` is `auto`, also says: "L4's pushes start no CI,
  so a `merge: auto` plan merges on the gates alone"; the fix hint names `L4_FORGE_TOKEN` + `forge.token_env` +
  `l4 upgrade`.

The match is a heuristic, so the row is a warning that lists what it found and never fails a run.

**Deferred.** A merge precondition "the repository's CI is green on the head" (the self-hosting proposal's
L4-YOLO-0xx, phase 3). It needs a token whose pushes start CI, and a CI-status reader per forge. Cost M–L; worth doing
only together with an App or PAT token story.

**Worth it now?** The warning, yes: a day of work, and it makes an invisible gap visible at adoption time.

### Item 7. OpenSpec intake refusals — accept three parts, reject one

**Current state.**
- Plan admission runs the provider's strict validation per unit (`src/l4/yolo/plans.py:131-149`). It joins every
  ERROR and **cuts the text at 300 characters** (`:140`) [V]. The plan step's line prints only the **first** finding
  (`src/l4/yolo/cycle.py:797`); `l4 yolo check` prints all of them (`src/l4/yolo/commands.py:500-529`) [V].
  the consumer's first run showed 1 of 8 findings [V log].
- An `Archive would refuse this delta:` INFO is promoted to ERROR (`src/l4/specs/openspec.py:47,472-478`, L4-OSP-006)
  [V].
- **A single unit outside any plan gets no OpenSpec strict validation at intake.** `_lint_scenarios` validates only
  Kiro (`src/l4/orchestrator.py:541-550`), and `_discover` checks only tasks and the test command (`:707-721`) [V]. The
  first strict validation is at verification (`src/l4/verifier/preconditions.py:218-223`), **after** the implementer
  has been paid [V]. The plan path and the single-unit path disagree, although `plans.intake`'s docstring says it is
  "the intake checks of a unit's first run" [V].
- **L4-OSP-007 (the Purpose of a new capability) is specified but not built for a consumer's change**
  (`docs/SPEC.md:926-929`). Only fix units use `_purpose` (`openspec.py:353-372`) [V grep].
- **OpenSpec probes (1.13.2 local, 1.14.0, the runner's pin) [V]:**

| Delta | `validate --strict` |
|---|---|
| MODIFIED on a capability with no `openspec/specs/<cap>/spec.md` | valid, with INFO `Archive would refuse this delta: dreaming: target spec does not exist; only ADDED requirements are allowed for new specs. MODIFIED and RENAMED operations require an existing spec.` |
| MODIFIED that drops one of the base requirement's scenarios | ERROR `MODIFIED "Fusion" omits scenario(s) the current spec still has: "One list empty" … Copy the omitted scenarios into the MODIFIED block …` (299 characters: the hint is past the 300-character cut once the path is prepended) |
| ADDED requirement of 594 characters | valid, no issue. Archived fine. After the archive, `openspec validate <spec> --strict` reports the long requirement as INFO and the placeholder Purpose as a WARNING (which fails strict) |

**Decision.**
- **Reject the "requirements over 500 characters fail `--strict`" lesson.** On 1.14.0 it is an INFO on main specs only
  [V]. The skill keeps one line of advice on it (short requirement statements), because the judge reads them.
- **Accept ADO-007:** a single OpenSpec unit is strictly validated at intake, like Kiro. An ERROR rejects it (exit
  14, `unit.rejected`, the reasons in full) before any agent runs. The same check builds L4-OSP-007's Purpose rule for
  a capability new to `openspec/specs/`.
- **Accept ADO-008:** findings are shown in full.
  - The 300-character cut becomes a per-issue bound of 600 characters, for every issue.
  - The plan step prints one line per finding, up to 10, then "… and N more: `l4 yolo check <plan>`".
  - A harness hint follows OpenSpec's text for the archive refusal only, since OpenSpec's own scenario ERROR already
    carries one: "`openspec/specs/<cap>/spec.md` is not on `<target>`. Either archive the change that creates
    `<cap>` first, or write this delta as `## ADDED Requirements`. A unit cannot MODIFY what another unit of the same
    plan only adds: fold the change into that unit."
- **Accept ADO-009:** `validate_plan.py` (standard library) pre-checks two things on the working tree.
  - MODIFIED/RENAMED/REMOVED on a capability with no baseline.
  - The Purpose rule.
  - This catches the commonest refusal before the push. The scenario-name rule is left to OpenSpec, so the script does
    not re-implement OpenSpec's parser.
- **Rejected for now:** deferring intake inside a plan until a dependency's archive creates the capability. It needs
  structured intake results, dispatch-time re-validation and a wait on the archive PR. Cost L, for a rare plan shape.
  The hint says what to do instead.

**Worth it now?** ADO-007 yes: it saves an implementer's spend per malformed unit. ADO-008 and ADO-009 are small.

### Item 8. Readiness size budgets — accept a pre-check that matches the harness exactly

**Current state.**
- `MAX_FILE_CHARS = 20_000`, `MAX_FOLDER_CHARS = 80_000`, `MAX_DEPENDENCY_CHARS = 20_000`
  (`src/l4/yolo/readiness.py:64-66`) [V].
- `read_folder` (`:140-170`) works like this [V]:
  - it walks the folder's files sorted by path;
  - it skips `digest.is_excluded` paths (any `.l4` directory above the file, `verification.md`, `questions.md`,
    `feedback.md`) and binary files;
  - it normalises `tasks.md` markers;
  - each file shows at most `min(20,000, left)` characters, and the folder budget is consumed by the characters shown;
  - a file reached with no budget left is "omitted".
- A unit's review reads its own folder at 80,000, and each direct `depends_on` folder at 20,000. A batch review reads
  its units at 80,000 and its out-of-batch prerequisites at 20,000 (`:486-535`) [V].
- Any cut adds a blocking `material_cut` finding, so the verdict can never be READY (`:353-373`) [V].
- At the consumer, `add-telemetry-runtime`'s `tasks.md` lost 7,148 characters **as a dependency**. That made three
  dependent units NEEDS_REVISION (`mm-review-1.txt`) [V].
- `validate_plan.py` has no size check [V grep]. The script and its skill copy are held byte-identical
  (`tests/unit/yolo/test_yolo_validate_plan.py:87`) [V].

**Decision (ADO-010).**
- The script computes, for every planned unit, the cut and omitted lists exactly as `read_folder` would. It does this
  for the unit's own folder at 80,000 and, for each unit that appears in any `depends_on` or as an out-of-batch
  prerequisite, at 20,000.
- It reports `material_over_budget: <unit>: <path>: N characters cut (as a dependency of <x>)`.
- Exit 1, like every other problem, because the cut makes READY impossible.
- The constants and the reading rules are held to the harness by a test: equal constants, and the same cut and
  omitted lists as `read_folder` on a git fixture.
- `l4 yolo check` prints the same lines after admission, from the real `read_folder`. It does not refuse admission,
  so a person can still accept a cut (covered by the review-resolution change).

Not proposed: changing what the review shows of a dependency (for example, specs first and `tasks.md` last). The
judge's `interfaces` findings at the consumer came from reading a dependency's tasks [V `mm-review-4.txt`]. Any change
there is a review-prompt decision (covered by the review-resolution change, if at all).

**Worth it now?** Yes. A day, mostly the parity test. It removes whole CI rounds.

### Item 9. Spec-authoring guidance — accept as a short skill reference

**Current state.**
- The skill has four references (`plugins/l4/skills/l4/SKILL.md:50-58`). None of them is about writing a spec [V].
- the consumer needed 8 review rounds for one plan [V `mm-plan` git log: "answer the eighth readiness review"]. The
  judge's findings fall into a few kinds:
  - `contradiction` (proposal or design against spec, two capabilities disagreeing);
  - `testability` (a SHALL with no scenario, an undecidable scenario, a "can run only if" test);
  - `failure_cases` (what happens when a stage does not run or raises);
  - `missing_dependency` (two units editing one function; a doc unit describing what a later unit creates);
  - `interfaces` (a helper one unit must expose to another);
  - `feasibility` (tools the runner lacks);
  - `material_cut` [V `mm-review-1..7.txt`].

**Decision (ADO-014).** A new `references/spec.md` of at most 450 words. It is a checklist keyed to those kinds, with
one line each:
- a scenario for every SHALL, including failure and "no work" cases;
- no line-number anchors;
- name the reusable helpers a unit exposes, with signatures;
- state delivered sections in prose;
- keep a dependency folder under 20,000 characters (move background to `docs/`);
- ADDED-only for a capability with no baseline, with a `## Purpose` of at least 50 characters;
- keep every scenario name in a MODIFIED block;
- `depends_on` when two units edit one function;
- no hidden dependency through docs;
- tools the runner has;
- short requirement statements;
- run `openspec validate <change> --strict` and `validate_plan.py` before the push.

`SKILL.md` gets one line under "Where to look next", and its description gains "writing a spec for L4". `plan.md`
links to it. The skill test files (`plugins/l4/tests/*.md`) get one scenario.

**Worth it now?** Yes. Hours of work, and it is the cheapest lever on review rounds.

### Item 10. Holding existing specs — accept, generalised as `yolo.hold`

**Current state.**
- A unit listed in a non-final plan is held (`src/l4/yolo/cycle.py:148-182`). An `exclude` entry does not hold, and a
  refused or invalid plan still holds (`src/l4/yolo/plans.py:233-257`) [V].
- With no plan file, the plan step returns `allow=None` and nothing is held (`cycle.py:350-355`), and
  `with_plan_holds` returns early (`src/l4/planner.py:236-238`) [V].
- So adopting a repository with existing specs needs a hold-only "backlog" plan (`adopt.md:102-105`) [V].
- That pattern fails open in two ways [V/I]:
  - **New specs.** Every new spec must be appended to the backlog.
  - **Cost.** If admission ever accepts the backlog (the consumer's shrank to 2 units after the archive), it is reviewed
    by the judge at a cost. `max_cost_usd: 0` is not checked before the review (`cycle.py:754-757,799-813`, per the
    doc sweep and the self-hosting proposal) [V by the reader].
- The self-hosting proposal adds a boolean `yolo.require_plan` (L4-SELF-014).

**Decision (ADO-011, ADO-012).** One config key, `yolo.hold: list[str]` (default `[]`): exact unit ids or `fnmatch`
patterns (`openspec:add-image-*`, `"*"`).
- A unit that matches and is listed in **no plan file** gets no agent work of any kind (implement, verify,
  continuation, bootstrap). `l4 status`, `l4 plan` and `l4 run --dry-run` show it as `held by yolo.hold`.
- A unit listed in a plan file follows the plan's rules, so listing a held spec in a plan releases it to that plan.
- `held_by_other_plan` and admission are unchanged. The key has no ledger, no review and no cost.
- `"*"` is the self-hosting proposal's `require_plan: true`, so L4-SELF-014 becomes "set `yolo.hold: ["*"]`".
- A unit already started (has a phase) that later matches the hold is held the same way as a plan hold holds it. Merged
  and archived units are never held (as `with_plan_holds` does).
- `l4 init --hold-existing` writes the ids of every unit found at init, sorted, into `yolo.hold` (ADO-012).
- `adopt.md` section 4a uses it in place of the backlog plan. `validate_plan.py` counts a held unit as covered.

**Order of adoption.** The schema is strict (an unknown key exits 2), so the order is: release, pin move, then the
config edit [V schema strictness per the self-hosting proposal].

**Worth it now?** Yes. It is the real consumer's need. It replaces a pattern that fails open, and it serves
self-hosting at the same time. Cost M: about 120 lines plus tests over planner, cycle, dry-run, schema and the
validator.

### Item 11. "refused" every run — accept, mostly through item 10

**Current state.**
- The refusal log line is not repeated while the findings are unchanged (`cycle.py:791-795`) [V].
- But `l4 status` prints `plan backlog: refused, 0/26 integrated, $0.00/$0.00` on every run, and the table prints
  `held by plan backlog (refused)` [V logs].
- The first run printed the refusal twice: `[l4] yolo.cycle:` and `[l4] run:` [V log].

**Decision (ADO-013).**
- With `yolo.hold`, the backlog plan is not needed (item 10).
- For plans that do hold units while not active, the status line adds what that means: `plan backlog: refused
  (holds 26 units; none of them runs until the plan is fixed, completed or its file removed)`.
- The plan step's refusal line lists all findings (ADO-008).

**Worth it now?** Yes. Small.

### Item 12. Docs and runbook vs today's behaviour — accept, with one new defect

**New defect: pin skew between the default branch's workflow copy and the base (ADO-005).**
- With an integration base, `.github/workflows/l4.yml` also lives on the default branch (`runbook.md` 7.15,
  `adopt.md:112-114`) [V].
- Scheduled and Actions-page runs use the default branch's file. Its pin is the `uses:` sha, or in the copy form the
  `commit:` input [I platform]. The base checkout runs before the action step (`src/l4/ci/templates/l4.github-action.yml:42-54`),
  so in the copy form the action file comes from the base while the `commit:` comes from the default branch's copy [V
  template order].
- After `l4 upgrade` on the base, every cron run executes the old harness against the new config, until a person also
  updates the default branch's copy. Nothing reports it. Today the consumer is not skewed: both copies are at
  `996b00b1` [V].
- **Decision:**
  - In CI with `harness.delivery: action`, `l4 doctor --ci` fails a new row when the running commit
    (`L4_HARNESS_COMMIT`, exported in both forms [V log]) differs from the pin read from the base's workflow (the
    existing `read_pin`, `checks_config.py:103-149`).
  - The row names both shas and the fix ("update `.github/workflows/l4.yml` on `<default branch>` to the base's copy").
  - `l4 upgrade` prints that reminder when the base is not the default branch, and `l4 setup github` reports a skewed
    copy (ADO-002).
  - Self-healing (dispatch on the base and exit 0) stays with the self-hosting proposal's L4-SELF-010. This
    requirement is the detection half of its L4-SELF-001.

**Doc fixes (ADO-018), from the sweep [V by the reader at the cited lines; spot-checked: runbook 7.15, `adopt.md`]:**
1. `README.md:10-11`: forge setup is "manual". Wrong since `l4 setup github`.
2. `runbook.md:1121-1145`: no step for the default branch's deployment policy. Say the cron runs the default
   branch's pin.
3. `runbook.md:444-445`: "a private harness needs the ssh form". https with the person's credentials works.
4. Template comments (`l4.github-action.yml:7-8`, `l4.github.yml:5-6`): "starts nothing, except on the base branch".
   With `GITHUB_TOKEN`, no harness push starts a run anywhere.
5. `adopt.md:116` vs `plan.md:7-8`: new specs "run as single units" vs "every spec must be in a plan or exclude". Make
   them agree: a spec meant to run alone goes in `exclude` with that reason; a held spec counts as covered.
6. `quickstart.md:203-204`, `runbook.md:514`, `quickstart.md:265`: say that the schedule runs on the default branch.
7. adopt.md section 4a: the order of `l4 setup github` against the default-branch PR (the dispatch answers 404 until
   then).
8. `quickstart.md:246`: `--action-repo` is needed only from a checkout (item 3).
9. `runbook.md:466-471`, `operate.md:54`, `quickstart.md:280-282`: a laptop push uses the person's credentials after
   ADO-003. Until then, use SSH.
10. `runbook.md:977-978,998`: the push-refusal hint per forge (ADO-004).
11. `adopt.md:67,100`: the test gate must write `.l4-out/junit.xml` (or set `gates.test.reports`).
12. `quickstart.md:213-217`: `L4_FORGE_TOKEN` needs `forge.token_env` and `l4 upgrade` too; CI runs on no L4 PR.
13. `yolo-mode.md:179-181`, `runbook.md:1380-1382`: state the review limits.
14. `adopt.md:102-111`: replace the backlog plan with `yolo.hold`. Until 0.4.x+1, warn that an admitted hold plan
    costs a review.

Also seen, not proposed:
- YOLO-001 warns on every run while `merge_policy: auto` waits for a plan (`checks_yolo.py:15-30`, the consumer log). It
  is by design (SCN-YOLO-17).
- ENV-008's fix hint names `prereqs.sh`, which a hosted runner never runs (log). This is cosmetic; it is noted in
  ADO-015's row text.

### Item 13. System One unused on the consumer — accept, with the premise corrected

**Current state.**
- **(a) init.** `l4 init` writes two profiles (codex, claude-code) and two roles (implementer, judges)
  (`src/l4/init/init.py:60-64,114-127`) [V].
  - It writes no `roles.s1_judge` (default `[]`, `src/l4/config/schema.py:463`) and no `backend: system-one`
    profile [V].
  - `verifier.s1.enabled` defaults to true (`schema.py:533`) and `clarifier.s1_standin` to `none` (`schema.py:500`)
    [V].
- **What S1 off costs (the premise was partly wrong).**
  - `build_s1_judge` returns `NoS1` when no system-one profile opens and the stand-in is `none`
    (`src/l4/clarifier/router.py:417-451`) [V].
  - The router turns `S1Unavailable` into `decision(False, "unavailable")` (`router.py:549-551`) [V]. **The
    clarifier's answer is not auto-accepted, and the question goes to a person.** No paid call is made for routing.
  - The verifier's step 8 is record-only: "Nothing here reads `p` to decide anything" (`src/l4/verifier/s1_step.py:1-6`;
    `ladder.py:905-928`) [V]. So S1 off costs human attention on every implementer question that the clarifier could
    have answered, plus the calibration rows. It costs no model spend.
  - Paid calls happen only under `s1_standin: llm_boolean` [V `router.py:450-451`].
- **(b) hosted setup.**
  - The hosted setup script runs HSU-00..05 (switch, facts, uv, PATH, bwrap, root step) and installs no Laya and no
    Serena (`src/l4/ci/templates/l4-setup.sh`, 0 matches) [V].
  - `doctor --ci --fix` installs uv, node, OpenSpec and the agent CLIs of the role chains only
    (`src/l4/provision/catalog.py:122-141`) [V].
  - Laya is installed only by `scripts/runner/prereqs.sh` PRQ-18 on a self-hosted runner (`:192-204`) [V].
  - A `laya-local` profile on a hosted runner therefore probes "laya-serve is not on PATH" (`system_one.py:639-642`)
    and S1 is silently off, with ENV-006 a skipped or failed warning [V].
- **(c) Jev through OpenCode Zen.**
  - **Probes, 2026-10-15 [V]:** `POST https://opencode.ai/zen/v1/systemone` with model `jev-1.13-free`, **no key**:
    HTTP 200, `noul 0.96`, 1.3 s. With an invalid bearer: HTTP 401 "Invalid credential".
  - The `jev` engine refuses to start without a key (`system_one.py:653-656`) [V].
  - **Is an OpenCode Go key also a Zen key? [I, not verified].** The harness treats both `opencode/` and
    `opencode-go/` as OpenCode's own providers reading `OPENCODE_API_KEY` (`src/l4/agents/credentials.py:40`). That
    is about the opencode adapter, not about Zen's `/v1/systemone`.
  - The coordinator reports Jev paid (`api.typesafe.ai`, `jev-1.13.0`) answered live today with the TypeSafe key [V
    by the coordinator]. `docs/free-resources.md:311` still says "untested end to end".
  - Keyless Jev when `base_url` is set is already listed as a candidate (`free-resources.md:328`, item 4); keyless is
    undocumented by Zen.
- **(d) Laya on a hosted runner.**
  - Measured on the self-hosted VM: ready in 5.5 s (14.1 s cold), p50 864 ms per `noul` call, peak RSS 2.48 GB
    (`docs/runner/README.md:91`) [V there].
  - Download: CPU torch plus the `typed-decisions` checkpoint of a 421M-parameter ModernBERT-large, about 1.5–2 GB
    [G: parameters from `docs/research/03-eval-verification.md:75`, size not measured].
  - The CLI cache is already about 240 MB (`Sent 240235984`, the consumer log) [V]. Adding Laya to it would make every
    CLI-cache save about 2 GB [G]. A separate cache keyed on the Laya pin avoids that.
  - The state budget is capped at 300 approx-tokens for Laya (`config/defaults.py:20`, `S1Cfg.laya_budget`) [V]. The
    same cap on Jev measurably cost accuracy (`docs/eval-framework.md` 6.2) [V there]. Laya's own window is 463
    tokens.
- **LAN-only engines.** `remote` (Laya on the maintainer's Mac) and `ollama` (tev1) cannot be reached from a
  GitHub-hosted runner [I network].
- **Licence.** TypeSafe MCA 2.3(b): Jev output is never a training label. The S1 log already tags each line with its
  engine (`system_one.py:1-20`) [V]. Nothing here trains on it.

**User decision (2026-10-15, through the coordinator):** "By default Laya should be the enabled system one. For
the consumer use jev."

**Laya install size, measured without installing [V, this session]:**
- `uv pip compile 'laya[serve]==0.3.24' --python-platform x86_64-manylinux_2_28 --python-version 3.12 --torch-backend
  cpu` resolves 44 packages, with torch `2.14.1+cpu` and transformers `5.20.0`.
- The wheel sizes come from PyPI and the PyTorch CPU index: about **253 MB** in total, of which torch is 196 MB.
- The `typed-decisions` checkpoint is **846 MB**: `model.safetensors` is 842.6 MB, and the tokenizer 3.6 MB (Hugging
  Face API).
- So a cold hosted job downloads about **1.1 GB**. The cache would be about 1.2 GB, and it restores in about 10–20 s
  [G].
- Ready in 5.5–14 s and 2.48 GB peak RSS, as measured on the self-hosted VM [V there].
- GitHub's standard hosted runner has 16 GB for public repositories and 7 GB for private ones [I, GitHub runner
  documentation, not checked here]. `laya-serve` runs only around the S1 work, never beside an agent
  (`system_one.py:9-11`) [V docstring].

**Decision.**
- **ADO-016, init (S).**
  - `l4 init` writes `profiles.laya: {backend: system-one, engine: laya-local}` and `roles.s1_judge: [laya]` by
    default.
  - `--s1 jev` writes the TypeSafe Jev profile instead (`api_key_env: TYPESAFE_API_KEY`, model `jev-1.13.0`), as
    the consumer uses it. `--s1 none` writes none.
  - The language packs (unmerged) write no config, so nothing changes there.
- **ADO-019, provisioning (M–L).**
  - Laya becomes a tool of `required_tools` whenever a `laya-local` profile is in `roles.s1_judge` or
    `verifier.s1.shadow`. So `l4 doctor --ci --fix` installs it on both forges: a persistent GitLab runner once, a
    hosted GitHub runner from the cache.
  - The install goes outside the harness's uv tool directory, which belongs to the harness cache.
  - On GitHub the action keeps Laya in its own cache, keyed on the pin and the checkpoint. The CLI cache key is
    unchanged.
  - The pin moves from `prereqs.sh` into the catalog.
- **ADO-015, doctor (S).**
  - One S1 row names the profile that would serve, with its engine and model. For `laya-local` it starts
    `laya-serve` once, stops it, and gives the seconds to ready, as the user asked.
  - When nothing serves, it warns with the reason, the consequence ("the clarifier auto-accepts no answer, so every
    implementer question goes to a person") and the profile lines.
  - It reports `remote`/`ollama` as unreachable on a GitHub-hosted runner.
- **ADO-017 (item 14)** passes `TYPESAFE_API_KEY` to the consumer's job.
- **Not proposed:** keyless Jev, and Jev through OpenCode Zen.
  - Zen answered keyless today, but that is undocumented.
  - Whether a Go key is a Zen key stays [I]. With Laya as the default and the consumer on TypeSafe's own key, it no
    longer matters.

**Worth it now?** Yes. ADO-016 without ADO-019 would leave hosted runners with a profile that never opens, so they
ship together. The cost of the default is about 1.1 GB on the first hosted job of a repository and about 2.5 GB of
memory during step 8. `--s1 none` is the way out.

### Item 14. The workflow never names a System One key — accept, must-fix

**Current state.**
- `credential_secrets` (`src/l4/ci/github.py:84-99`) iterates `adapters_in_use(cfg)`, which keeps only profiles whose
  `adapter` is a known CLI (`src/l4/provision/catalog.py:109-119`) [V].
- A `backend: system-one` profile has no adapter, so its `api_key_env` never reaches the job's `env`.
- **Repro [V]:** a config with a claude-code implementer and judge and `s1_judge: [jev]` (`api_key_env:
  TYPESAFE_API_KEY`) renders `['CLAUDE_CODE_OAUTH_TOKEN']` only. `l4 upgrade` then has nothing to change ("up to
  date", per the coordinator) [V the render; I the upgrade message].
- On GitLab, CI/CD variables scoped to the environment reach the job without rendering (template comment,
  `l4.gitlab-ci.yml:18`) [I]. So only GitHub's renderer needs the fix.

**Decision (ADO-017).** `credential_secrets` also names the `api_key_env` of every `backend: system-one` profile in
`roles.s1_judge` or `verifier.s1.shadow`. A test covers both lists. The docs say `l4 setup github --secret
TYPESAFE_API_KEY=TYPESAFE_API_KEY`, and `free-resources.md:311` is updated after an end-to-end run (task).

**Worth it now?** Yes. Ten lines.

---

## 2. How the pieces fit

- **Ordering.**
  1. ADO-003, -004, -017 and -001 first: small, and independent of each other.
  2. ADO-008 before ADO-013: both touch the plan step's lines.
  3. ADO-011 before ADO-012 and the `adopt.md` rewrite.
  4. ADO-009 and ADO-010 change `scripts/validate_plan.py` and its skill copy together.
  5. ADO-017 before ADO-016; ADO-019 together with ADO-016 (the default needs the install).
- **Shared files.**
  - `src/l4/yolo/cycle.py`: ADO-008, -011, -013.
  - `src/l4/planner.py`: ADO-011.
  - `scripts/validate_plan.py` and `plugins/l4/skills/l4/scripts/validate_plan.py`: ADO-009, -010, -011.
  - `src/l4/setup/github.py`: ADO-002, -005.
  - `src/l4/doctor/`: ADO-005, -006, -015.
  - Tasks touching the same file are ordered in `tasks.md`.
- **The self-hosting proposal** (untracked, `docs/plan/proposal-l4-self-hosting.md`):
  - L4-SELF-014 becomes `yolo.hold: ["*"]` (ADO-011).
  - L4-SELF-015 is rejected (item 1 probe).
  - ADO-005 is the detection half of L4-SELF-001.
- **The review-resolution change:**
  - ADO-010 reports budget overruns but does not refuse admission, so that change can let a person accept a cut.
  - ADO-008's hints are the harness's own intake hints, not judge-finding hints.

## 3. Open questions

1. **`yolo.hold` vs `yolo.require_plan`.** One pattern list (proposed) or the self-hosting boolean? The list covers
   both uses with one key.
2. **ADO-010's exit code.** A budget overrun is exit 1 in `validate_plan.py`. Should it be a warning, if the
   review-resolution change lets a person accept a `material_cut`?
3. **Laya's start check in every CI job.** It adds 5–14 s per job (the user asked for it). Keep it in `--ci`, or
   only in `--adoption`?
4. **Laya on private repositories.** The standard runner there has 7 GB [I]. Laya peaks at 2.5 GB, but only around
   the S1 work. Is the default still Laya for a private repository, or does `l4 init` pick `--s1 none` there and say
   so? the consumer is public and uses Jev, so this matters for the next adopter.
5. **ADO-005's failure mode.** A red cron job every 30 minutes until the default branch's copy is updated. Is that
   acceptable until L4-SELF-010's self-healing dispatch exists?
6. **The scenario prefix.** `L4-ADO`/`SCN-ADO` are new; the review-resolution change must not use them.
