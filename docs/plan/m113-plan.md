# M1.13 — wave C harness findings (W-C1..W-C7) and the magnitude result path (planned 2026-10-07)

## Goal

Wave C of sample-consumer left seven harness findings, W-C1..W-C7 (`docs/adoption/sample-consumer/wave-c.md`,
kept outside this repository). The free-resources measurement of magnitude-qwen as implementer (`docs/free-resources.md`
section 11, `docs/live/magnitude/`) left one more, MAG. Harness `main` is at `5aa112b`, which already merged M1.12.
First each W-C item is checked against M1.12; M1.13 builds only what is open. **27 build lines**, test first: each new
test is seen failing for the stated reason before the code is written. A line that passes at once is a pin and is
recorded as `already satisfied`.

Labels: [V] read in code or evidence at `5aa112b`; [I] inferred; [U] not checked (a build line settles it first).

## Covered or open

| Item | Status | Cited |
|---|---|---|
| W-C1 test-only finding on correct code cannot pass red | **open** | M1.12 line 25 and M1.11 W5 handle a rejected *coverage hold* (`H-` id, `is_coverage_hold_finding`) only; the wave-C finding was a judge finding with a criterion, so `plan_fix_unit` made a red/green task (`chore = criterion is None and not scenarios`, `verifier/fixunit.py`) |
| W-C2 an escalated unit cannot be resumed | **open** | `state/resume.py` refuses `escalated` and every `--extend-*`; `lifecycle.py` has the RESUMED edge from `HALTED` only; `ci/sweeper.py::_resume_one` turns the label on an escalated unit into a refusal; `verifier/fixloop.py::decide_fix` reads only `cfg.max_fix_rounds`. SPEC L4-IMP-013, SCN-RES-03 and the 12.0 row already require it |
| W-C3 the question does not say how to unfreeze | **partly covered, rest open** | covered: M1.12 F2 (`implementer/loop.py::_suggest_edits`, `templates/green.md` v3, `tests/unit/implementer/test_suggested_edit.py`) makes the agent's question carry an "Edit `<path>`: ..." option, so `accepted` unfreezes. Open: nothing in the question as a human reads it names the file rule, the `accepted` status or the override trap (`specs/questions.py::_render_section`) |
| W-C4 audit writer tests are weak | **partly covered, rest open** | covered: M1.11 W7 bans *computed* reflection (`verifier/testwriter.py::_reflection`); M1.12 K2 lints audit tests (`verifier/audit.py`, `tests/unit/verifier/test_audit_lint.py`). Open: constant-name `hasattr` cascades pass `_reflection`; a name the code under test does not define is never checked; nothing tells the writer about files the spec excludes |
| W-C5 Codex wrote in-process handler tests | **covered** | M1.12 K3: `agents/codex.py` (loopback never on `implement` without opt-in), `templates/contract.md` v7 (`@codex` sockets sentence), `tests/unit/agents/test_codex_loopback.py`; branch (b) of M1.12 decision 5 landed. The live in-process attempt predates the vendored `8bdaf11` |
| W-C6 designed stop shows as a failed CI job | **covered** | M1.12 K4: `exitcodes.CI_ALLOWED`, the `designed stop, not a failure` line, `tests/unit/cli/test_ci_allowed.py`; diagnosis in `docs/plan/m112-progress.md` (a `failed (allowed)` job). The project still vendors `8bdaf11` |
| W-C6 `idle.py` reads a 502 as busy | **open** | `scripts/dev/mk-gitlab-api.sh` retries a proxy 502 once (M1.11 W11, `tests/unit/forge/test_mk_scripts.py:292`); the owner's `idle.py` is outside the repository and treats any failed call as busy |
| W-C7 free clarifier cannot unfreeze | **covered by design** | `implementer/unfreeze.py`: an `accepted` suggestion unfreezes only a file the *question itself* names (M1.10 C2); M1.12 F2 makes the question name it. The rule is a security boundary and stays. The human-facing words are W-C3 |
| MAG result path | **open** | `implementer/tdd.py::_prompt` gives the host path of `agent-tmp/result.json`; magnitude-qwen rewrote `units/` to `worktrees/` in 3 of 3 attempts |

## Facts this plan rests on

* **MAG** [V, `docs/live/magnitude/`]. The work was right in all three attempts; the result JSON went to
  `<worktree>/agent-tmp/result.json`. The harness reads `wb.agent_tmp / "result.json"`, host path
  `.../units/<fw>/<unit>/agent-tmp/`, bind-mounted rw into the agent sandbox at the same path (`sandbox/bwrap.py`).
  [V] A file at `<worktree>/agent-tmp/result.json` is **inside the worktree**, which `git add -A` stages: accepting a
  result from there would let an agent put arbitrary bytes into the commit, so it is never accepted.
* **MAG, design choice** [I]. Three routes: (1) accept the wrong path: rejected, above. (2) bwrap `--bind` of the step
  dir at `<worktree>/.l4-result`: stronger against an agent that unlinks the alias, but bwrap's argv is mirrored in
  `scripts/runner/sandbox-probe.sh` (`tests/unit/sandbox/test_probe_parity.py`), creates the mount point in the real
  worktree, and does not exist for `sandbox.mode: none`. (3) a **harness-made symlink** `<worktree>/.l4-result ->
  <agent-tmp>` made before each agent step and removed after it. The target is bound at its own host path in the
  sandbox, so the alias resolves under bwrap and under `none`, with no change to the sandbox argv. If the agent replaces
  or removes the alias, its result is not found and the step fails as today (no result, never a smuggled one). **Route 3
  is taken**; the deviation from the "bind mount" example is recorded in the progress file.
* **MAG, what the alias is not** [I]. It is not a second accepted location: acceptance still reads
  `req.result_path` on the host (`agents/base.py::read_result_file`). The alias exists only while the agent runs, is
  excluded from git (`HARNESS_EXCLUDES`), is a protected path, and is removed before any gate runs (gates mount no
  `agent-tmp`, so the link would only dangle).
* **W-C1** [V, wave-c live logs]. The fix unit's task for F-27a2f8dd ("New tests bypass the HTTP server and do not check
  the observable outcomes", criterion C-a9eff2f4, accepted by the owner as satisfied in Q-001..Q-003 and rejected as a
  finding in Q-004) ran red three times and halted: `red attempt n failed: tests not collected individually`
  (`tdd.py::classify_red`: the agent rewrote existing tests, so no new id exists). The code was correct, so no honest
  failing red exists. [V] A `tests` chore (`run_single(kind="tests")`, M1.11 W5) already exists: it keeps new test files,
  puts `L4-TDD: exempt` on the commit, records `task.tests_added`, and the verifier discriminates those tests with
  `discriminate_extra` (zero-value run, then base-code run, `verifier/ladder.py::_extra_proof_step`) when they carry a
  criterion tag. So the missing piece is the **routing** and an **early discrimination** for a chore bound to a criterion.
* **W-C1, classification** [I]. A finding is a test-only finding when: the finding is a judge or human finding (not a
  gate's), it cites a criterion whose round result is `pass` (the criterion is satisfied, by the judge or accepted by a
  human), it has no regression scenario, and its title or detail says it is about tests. Any miss keeps today's red/green
  task, so a code defect on a passing criterion is never turned into "add tests".
* **W-C2** [V]. `escalated` has one source: `verifying` (`VERIFY_FAIL_EXHAUSTED`), so "the phase before" is `verifying`.
  `unit.resumed` resets the breaker counters and the verifier's consecutive-error counter. The label carries no number,
  so it needs a defined amount. **Decision: one label event grants exactly one more fix round**, recorded as
  `budget.extended{fix_rounds: 1, by: member, signal}`; a member who wants more adds the label again after the next
  escalation, or runs `l4 resume --extend-fix-rounds N`. A fresh full budget per label was rejected: it makes one click
  worth three judge calls and three fix units.
* **W-C3** [V]. `unfreeze.names_path` and the digest rule are unchanged. A hint that lists every frozen file would let a
  clarifier suggestion unfreeze a file the agent never named (the hint would count as "the question names it"), so the
  hint **only restates the frozen test files the agent's own question already names** and otherwise says the general rule
  without a path.
* **W-C4** [V]. The audit writer is tool-less; its user prompt carries the changed sources at head
  (`audit.head_sources`) and the existing test file's style. It never sees `design.md`, which in wave C said that only the
  event log may change. [I] A deterministic check on imported names is feasible from the shown sources.
* **W-C6** [V]. `scripts/dev/mk-gitlab-api.sh` retries a proxy 502 once after 2 s. `idle.py` calls it, and any non-zero
  exit counts as busy. [U] how many consecutive 502s a Mintkey vault error gives; three tries with backoff is a guess,
  configurable.

## Decisions

1. **MAG: alias by symlink, acceptance unchanged** (above). New module `l4/implementer/resultalias.py`:
   `RESULT_ALIAS = ".l4-result"`, `RESULT_ALIAS_PATH = ".l4-result/result.json"`, `link(worktree, step_dir)`, `drop(worktree)`.
   `agent_step` links before `impl.run` and drops in its `finally`, before the protected revert. The implementer prompt of
   a prompt-contract adapter says `.l4-result/result.json` (relative to the working directory). The env
   `L4_RESULT_PATH` and the `command` adapter keep the host path (the tool, not a model, writes there).
2. **W-C1: route, then discriminate early.** `plan_fix_unit` marks the test-only finding `chore=True, tests=True` and keeps
   its criterion on the task. `run_single(kind="tests")`, for a task whose title cites a criterion, runs
   `discriminate_extra` on the added tests and needs at least one accepted (fails by assertion on zero values or on the
   base code), with the ids recorded in `task.tests_added.discriminating`. `single_tests.md` v3 says to tag the tests with the
   cited criterion and to exercise the interface the design names. Coverage-hold chores (no criterion) are unchanged.
3. **W-C2: resume an escalated unit with an extension** per SPEC (`--extend-fix-rounds`, label = 1 round). The fold adds
   `budget.extended` to the fix-round limit; `decide_fix` uses the sum. `l4 resume` of an escalated unit whose fix rounds
   are used up and with no extension is refused naming the budget (SCN-RES-02 style); an escalated unit that has rounds left
   (three verifier errors, a fix unit that could not be created) resumes without one. `--extend-iterations` and
   `--extend-cost` stay refused ("not yet implemented"): out of scope.
4. **W-C3: a harness note in the question.** For a technical question of a task in green, `loop._questions` appends a
   harness-written note to the context (never to the options, never listing a file the agent did not name).
5. **W-C4: three checks and one rule set.** `testwriter/audit` v4: rules for names, reading the sources, and files the spec
   excludes. A reply that calls `hasattr` is rejected with a reason (a probe for a name the writer could read). A reply that
   imports a name from a shown source module that does not define it is rejected with the names it does define. The
   unit's `design.md` and `proposal.md` (bounded) are passed as sources so the exclusions are visible.
6. **W-C6: retry in the helpers.** The proxy's 502 is retried `L4GL_RETRIES` times (default 3, backoff `L4GL_RETRY_WAIT`
   times the try number). A repository helper `scripts/dev/l4_idle.py` is the tested form of `idle.py`: a 502 that survives
   the retries is "unknown", exit 2, never "busy"; busy is exit 1; idle is exit 0. The owner's scratch copy is replaced by
   a call to it.

## Build lines (test first)

**MAG: a short result path inside the sandbox** (SPEC 8.1 prompt contract, L4-SEC-004, L4-SEC-005; new `implementer/resultalias.py`, `tdd.py`, `prompt.py`, `workbench.py`)

1. Test: `link(worktree, step_dir)` makes `<worktree>/.l4-result` a symlink to `step_dir`; a file written through
   `.l4-result/result.json` is `step_dir/result.json`; calling it again replaces a leftover symlink, a real directory and
   a regular file; `drop` removes the symlink and not what it points to, removes a real directory with its files without
   following a symlink inside it, and is a no-op when nothing is there. Fails: no module.
2. Test: in a real git repository with the harness excludes, `.l4-result` as a symlink and as a directory is not shown by
   `git status` and not staged by `git add -A` with `exclude_config`, and `git clean -fdx` with the harness keeps survive it.
   Pins the pattern: `.l4-result/` with a slash would not match a symlink. Fails: shown as untracked.
3. Test: `.l4-result/**` is a contract-protected path: a tracked `.l4-result/x` changed by an agent step is reported and put
   back. Fails: not in `CONTRACT_PROTECTED_GLOBS`.
4. Test (agent step, fake adapter): during the step `<worktree>/.l4-result` exists and resolves to the unit's `agent-tmp`;
   an adapter that writes its result only through the alias is accepted; after the step, also after an exception in the
   adapter, no `.l4-result` is left in the worktree. Fails: no alias.
5. Test: the rendered implementer prompt of a prompt-contract adapter says `.l4-result/result.json` and contains no host
   `agent-tmp` path; a native adapter's prompt is unchanged. Fails: the host path is in the prompt.
6. Adversarial test (the damage line): a fake adapter writes a valid result to `<worktree>/agent-tmp/result.json` (the
   magnitude path) and nothing to the alias: the step is `result missing`, and nothing of that file is committed or
   survives the discard. A second adapter replaces the alias with a real directory holding the result: also missing, and the
   directory is gone before the gates run. Pin: no second accepted location (passes at once; recorded `already satisfied`).
7. Test: `config_content` for `implement` still allows the step dir under `external_directory` and denies other
   directories (pin: the alias target is that directory); a gate run after the step cannot read the result file (the gate
   sandbox spec mounts no `agent-tmp`). SPEC 8.1 and `docs/free-resources.md` section 11 say what the alias is. Pin plus
   doc test.

**W-C1: a fix task for a test-only finding on correct code** (SPEC L4-VER-006, L4-IMP-002, L4-VER-009; `verifier/fixunit.py`, `specs/openspec.py`, `implementer/tdd.py`, `templates/single_tests.md`)

8. Test (reproduction, the cbsg shape): a FAIL round with a judge finding "New tests bypass the HTTP server and do not
   check the observable outcomes" on criterion C-1 whose round result is `pass` (accepted by a human), rejected by a human
   with a reason: `plan_fix_unit` returns one group with `chore` and `tests` True and `criteria == (C-1,)`, and the decision
   text first in `detail`. Fails: `chore` is False, so the task goes to red.
9. Adversarial tests for the classification (each must keep today's task): the criterion result is `fail`; the finding has
   a regression scenario (a reject with WHEN/THEN); the title does not speak of tests ("Edge case of an empty cart is not
   handled"); the source is `deterministic`; the finding cites no criterion (stays a `fix` chore). Pins; they pass at
   once and are recorded as such.
10. Test: `create_fix_unit` for that group writes a marker whose `chores` and `test_chores` hold the id, the task line cites
    the id and the criterion, `chore_kind` is `tests`, and `run_task` takes the single phase (no red). Fails: red.
11. Test (`run_single`, fake adapter): a criterion-bound tests chore whose added tests all pass against the zero values and
    the base code is a failed attempt naming them ("pass against the zero values and on the base"); one that adds a test
    that fails by assertion on the zero values is done, `task.tests_added` lists `discriminating`. Fails: both accepted.
12. Test: a coverage-hold chore (no criterion) is not discriminated early (pin of M1.11/M1.12 behaviour, passes at once).
13. Test: `single_tests.md` is v3 and tells the agent to tag every test with the cited criterion and to test through the
    interface the design names; the rendered prompt carries it; `contract@7+single_tests@3`. `templatelock --write`. Fails:
    sentence absent.

**W-C2: resume an escalated unit** (SPEC L4-IMP-013, L4-CI-004, SCN-RES-02/03, 12.0; `state/fold.py`, `state/lifecycle.py`, `state/resume.py`, `verifier/fixloop.py`, `ci/sweeper.py`, `ci/resume_label.py`, `orchestrator.py`)

14. Test: the fold of `budget.extended{fix_rounds: n}` events adds up in `UnitState.fix_rounds_extra`; `unit.resumed` does not
    reset it; unknown keys are ignored. Fails: no field.
15. Test: `decide_fix` with `used == max_fix_rounds` and one extra round on a FAIL spawns fix unit `used + 1`; with none it
    escalates, and the reason reads `fix rounds used 3/3` (and `3/4` once extended, a unit of 3 with 1 extra that used
    4). Fails: always escalates.
16. Test: `Phase.ESCALATED --RESUMED--> verifying` is an edge; the 12.0 table row and `all_edges` agree; a halted unit still
    returns to its previous phase. Fails: no edge.
17. Test: `l4 resume --unit U --reason R` on an escalated unit with all fix rounds used and no extension is refused (exit 2)
    naming `max_fix_rounds`; with `--extend-fix-rounds 1` it records `budget.extended` and `unit.resumed` and the phase is
    `verifying`; on an escalated unit that has rounds left it resumes without one; `--extend-fix-rounds` on a halted unit
    is refused (nothing to extend); `--extend-iterations`/`--extend-cost` still refused. Fails: all refused.
18. Test (sweep): a member's `l4:resume` label on an escalated unit resumes it with `budget.extended{fix_rounds: 1, by,
    signal}`, once per label event; a non-member, the bot and an already-used event are refused as for a halted unit; the
    refusal text for escalated is gone. Fails: refused as "waits for fix rounds".
19. Test: `halted_section("escalated", ...)` says the label (or `l4 resume --extend-fix-rounds N`) gives one more fix round;
    the orchestrator's `escalated: M0 has no l4 resume` text and the module docstrings are updated; SPEC L4-CI-004, L4-IMP-013
    and SCN-RES-03 say it (doc test: the sentences exist). Fails: old text.
20. End to end on the fake adapter (the risky line): an escalated unit resumed with one round runs verification again, the
    FAIL spawns the one allowed fix unit, a second FAIL escalates again with `fix rounds used 4/4`, and a second label event
    gives exactly one more. Fails: stays escalated.

**W-C3: the question says how to unfreeze** (SPEC L4-QMD-005/006; `implementer/unfreeze.py`, `implementer/loop.py`)

21. Test: for a green-phase technical question whose title, context or options name frozen test files, `loop._questions`
    appends a harness note that names exactly those files, says that the answer (or `accepted` of the suggestion) must
    name the path, that `accepted` takes option 1, and that an answer edited after a run used it counts as an override and
    unfreezes nothing. A file the agent did not name is never in the note, whatever the manifest holds (adversarial: the
    manifest has three test files, the question names one). Fails: no note.
22. Test: a question that names no frozen file gets the general sentence without any path; a question raised in red or for a
    non-technical kind gets none; the note is redacted with the rest. Fails: no note.
23. Test: the unfreeze decision is unchanged: the note's file does not make a different `accepted` question unfreeze it
    (the question text used by `names_path(asked, path)` is the agent's text, as before). Pin of M1.10 C2, passes at once.

**W-C4: audit writer tests** (SPEC L4-VER-002a; `verifier/testwriter.py`, `verifier/audit.py`, `templates.lock.json`)

24. Test: `hasattr(...)` with a constant name in an audit reply is rejected with a reason that names it, `getattr` with a
    constant name stays allowed (pin), and the retry gets the reason. Test: `from pkg.mod import Missing` where `pkg.mod` is a
    shown source file that does not define `Missing` is rejected with the names it defines; an imported name it defines, a
    submodule and a module that is not among the shown sources pass (adversarial). Fails: both accepted.
25. Test: `testwriter/audit` rules v4 say: use only names the shown sources define, read the sources before writing, never
    snapshot or compare a whole folder or a log the criterion or design excludes, assert on what the criterion names; the
    version is 4 and the lock is regenerated. Fails: sentence absent.
26. Test: the audit writer's data blocks carry the unit's `design.md` and `proposal.md` (bounded to 8000 characters, at
    head), after the code sources; a unit without them has none. Fails: blocks hold code only.

**W-C6: helpers retry the proxy's 502** (`scripts/dev/mk-gitlab-api.sh`, new `scripts/dev/l4_idle.py`)

27. Test (`FAKE_PROXY_CODES`, as `test_mk_scripts.py`): `502,502,200` succeeds with the default 3 tries; `502,502,502,502`
    exits 22 with `HTTP 502`; `L4GL_RETRIES=0` keeps one try. Test (`l4_idle`): busy jobs listed -> exit 1; none and the last
    main commit older than 15 min -> 0; the API failing with 502 on every try -> exit 2 and the word `unknown`, never busy; a
    502 then success -> decided by the second answer. Fails: one retry only; no helper.

## Order, size and risk

* Order: MAG 1-7, then W-C2 (14-20, the largest), W-C1 (8-13), W-C3, W-C4, W-C6, docs. Each commit carries its tests;
  changed templates (`single_tests.md`, the audit rules) are version-bumped and `uv run python -m l4.templatelock --write`
  is run in the same commit. SPEC lines are edited with the line they describe, and `scripts/check_spec.py` runs at the end.
* Highest damage if wrong: **line 6** (a result accepted from a worktree path is a way into the commit), **line 20 / 17**
  (a resume of an escalated unit must not loop: one label event is one round, and an exhausted budget without an extension
  is refused), **line 9** (a code defect on a passing criterion must never be turned into "add tests"), **line 21** (the
  hint must not widen what an `accepted` suggestion unfreezes). Each gets an adversarial test beside the line.
* Out of scope: bind-mounting the alias (reason above); `--extend-iterations` and `--extend-cost`; changing the
  unfreeze rule; a judge field that says "this finding is about tests" (the classification is conservative instead);
  moving the owner's `docs/adoption` records.
* [U] settled in the build: whether opencode's `write` tool follows the alias without an `external_directory` prompt
  (the allow rule already covers the step dir, line 7 pins the config; a live run with magnitude-qwen is the only real
  answer and is not part of this change).
