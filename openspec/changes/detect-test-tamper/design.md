# Detect test tamper: pre-existing tests are compared per test, and audit tests run without the unit's support files

Status: design, 2026-10-17. Harness at release 0.4.14 (`795e97a9`). Markers: **[V]** verified (read in the code at the
cited line, or run), **[I]** inferred (follows from the code, not run end to end).

## 0. The answer in five lines

1. Four confirmed review findings, all still present at 0.4.14 (section 1): a red step can weaken or rebind a
   pre-existing test and nothing notices (implementer-4, verifier-2: a reproduced false PASS on broken code); a deleted
   test is hidden by any same-named test in another changed file (verifier-8); and audit tests run with the unit's own
   `conftest.py` in place, so an autouse fixture can make the audit pass on broken code (verifier-6: reproduced).
2. One pure comparison, `src/l4/implementer/tamper.py`, used by the red step and by step 1: a test is identified by its
   file and qualified name, and compared on the AST as every statement that binds its name plus what it uses in its own
   file (fixtures, helpers, constants, marks, autouse fixtures, module hooks) (D1-D3).
3. Red: after `classify_red` accepts the step, a pre-existing test that the step changed, bound again or deleted fails
   the attempt with `guard.test_tamper{rule: "pre-existing test", action: "rejected"}` and a retry text that says what to
   do; a reopened task's stale tests and a `[test-infra]` task are allowed (D4).
4. Step 1: the same comparison from the base to head, per introducing commit: a harness commit is a blocker unless an
   allowance holds (`tests.superseded`, `[test-infra]`, a `task.unfrozen` of the same task); people's commits are listed,
   never blocked. A second sub-part blocks a red commit that changed a test an earlier step of the unit wrote (D5-D7).
5. Step 4a (and step 5's head run): the unit's added, changed or deleted test-support files are put at their base
   versions for the run and restored byte for byte after; a test that does not run that way runs with them in place only
   when step 1's content scan read them and found nothing, else it is rejected; the record says which (D8-D9).

## 1. Current state and the findings

Re-read in this worktree (0.4.14) and reproduced with the reviewer's own tests, copied into the worktree for the run and
removed again (nothing of them is committed):

| Finding | Status at 0.4.14 | Where | Reproduction output at 0.4.14 |
|---|---|---|---|
| implementer-4 (major) | applies [V] | `tdd.run_red` (`src/l4/implementer/tdd.py:821-1084`) has no comparison of pre-existing tests: `enforce_red_scope` skips test paths (`stubs._exempt`), and `guard.test_tamper` is emitted only by `restore_frozen`, `restore_test_paths` and `review_test_chore` | `[weakened] red: ok ''`, `tampered file committed in red: True`, `guard.test_tamper events: []`; the same for `[rebound]` |
| verifier-2 (blocker) | applies [V] | `integrity.check_tests` (`src/l4/verifier/integrity.py:210-262`) compares only the sets `scan.defined_tests` and the counters `scan.skip_markers`; `classify_red` counts a regression only when a base-passing test fails or is gone (`tdd.py:315-381`) | `WEAKEN True CODE 0 VERDICT PASS`, steps 0-4, 9, 10 `ok`, `TAMPER []`, `TOTAL AT ORIGIN ['    return 0 if not prices else 999.0']` |
| verifier-6 (blocker) | applies [V] | `audit._judge_written` runs `wb.run_gate("audit", …)` in the worktree with the unit's support files in place (`src/l4/verifier/audit.py:219`); nothing in `audit.py`, `generate.py` or `ladder.py` reverts them | `FULL CODE 0 VERDICT PASS HOLDS []`, `FULL AUDIT [('C-d80f494d', 'rejected', "it passes when the project's functions answer their zero value")]`, `FULL IMPL AT ORIGIN ['    return amount']`; the same audit test at head: `conftest=unit: 1 passed`, `conftest=base (none): 1 failed` |
| verifier-8 (minor) | applies [V] | `check_tests` unions bare names of every changed file into `head_defined` (`integrity.py:222-233`) | `WHO=harness SAME_NAME_ELSEWHERE=True -> findings=[] human_listed=[]` (control `False`: the blocker) |

Facts the design builds on [V]:

- `scan._qualified` yields module-level functions and the methods of module-level classes with dotted names
  (`scan.py:148-156`); `defined_tests` keeps a set, so a second `def` of a name disappears into it.
- `guards.appended_only` already rejects rebinding and module-level pytest names for a test chore (`guards.py:200-226`),
  and `guards._bound` / `_MODULE_HOOKS` (`guards.py:113-131`) say which names a top-level statement binds and which names
  pytest reads at module level. They are reused here.
- SPEC 10.2 row 4a already says "Audit and generated tests run with the unit's added or changed support files reverted to
  their base versions where they still collect; otherwise with them, provided the step-1 content scan of those files is
  clean" (`docs/SPEC.md:3058`). The code does not do it.
- `red_code_in_place` and `zero_values_in_place` (`src/l4/implementer/discrimination.py:60-150`) swap files for the
  length of a gate run and restore them with a sha256 check. The new context manager follows them.
- Gate runs take `extra_env`, and `PYTEST_ADDOPTS` values are joined (`workbench.run_gate`, `gates/coverage.merge_pytest_env`).
- pytest stops the whole run at a collection error (`Interrupted: 1 error during collection`) unless
  `--continue-on-collection-errors` is given, also through `PYTEST_ADDOPTS` [V, run with this worktree's pytest on a
  scratch folder: `1 error` without it, `1 passed, 1 error` with it]; the audit's own "deferred" handling
  (`audit.py:222-236`) exists because of it.
- Five existing red tests expect `red broke existing tests: …` or `no new test: existing tests were changed and now fail:
  …` with the failure excerpt when red rewrites a pre-existing test so that it fails (`tests/unit/implementer/
  test_tdd_red.py:117-127, 545-585`, `tests/unit/implementer/test_loop.py:188-215`). The red check therefore runs after
  `classify_red` (D4), so those keep their reason and excerpt.
- SC-03 (`docs/SPEC.md:9782`) names weakened tests in the tampering subset; there is no seeded tampering benchmark in
  code. The eval seed set (`src/l4/eval/seeds.py`) is hashed (`seed_set_sha256`), so adding seeds is the owner's call
  (open question 3). The regression tests of this change are the tampering cases until then.

## 2. Decisions

### D1 One comparison, by file and qualified name (L4-IMP-045)

New pure module `src/l4/implementer/tamper.py` (text in, facts out; Python only; no git). The implementer side owns it
because it reuses `guards._bound` and `guards._MODULE_HOOKS`; `verifier/integrity.py` imports it, as it already imports
`implementer/opened.py`. No public name starts with `test` or `Test` (a test module that imports it must not collect it).

- **Identity.** A test is `(path, qualified name)`: a module-level function whose name starts with `test`, or a method
  whose name starts with `test` of a module-level class (`Class.test_x`), the set `scan._qualified` yields. Never a bare
  name across files.
- **Bindings.** For a scope (the module body, or one module-level class body), each statement in order contributes, for
  every name it binds, one *part*:
  - `def`, `async def`, `class`, `=`, `: … =`, `+=` and the other augmented assignments, `del`: `ast.dump(statement,
    include_attributes=False)` (positions out; decorators, defaults, annotations, parameters and body in);
  - `import a.b`: binds `a`, part `import a`; `import a.b as c`: binds `c`, part `import a.b`; `from .m import x as y`:
    binds `y`, part `from .m import x` (level dots, module, name). A part per alias, so `from pytdd import total` and
    `from pytdd import apply_discount, total` give `total` the same part;
  - a compound top-level statement (`if`, `try`, `with`, `for`, `while`, `match`): every name bound anywhere inside it
    (a `Name` in a store context, a nested `def`/`class` name, an import alias), part `ast.dump` of the whole statement;
  - `from m import *`: binds the pseudo-name `*`, part `from m import *`.
  Identical import parts of one name are kept once (a repeated `import pytest` is no rebinding, as `guards._same_import`
  says today); every other part is kept in order, duplicates included.
- **Definition** of a test = the ordered parts of its own name in its own scope (`parts`), hashed (`definition`,
  sha256 of the parts joined by `\n`). A second `def` (or an assignment, an import or a `del`) of the name adds a part:
  that is how shadowing is caught, also when the original `def` stays in place.
- **Normalisation.** `ast.parse` drops comments and layout, so they and a trailing newline change nothing (SCN-IMP-46
  stays green). A docstring of the test is part of its body and counts as a change (conservative: a docstring can carry a
  criterion id, L4-CRT-002). A file that does not parse yields no facts.
- **Outcome per test of `before`** (`compare(path, before, after)`), in this order:
  - `unparsable`: `after` is given and does not parse. why: `the file does not parse`;
  - `deleted`: the name has no part in its scope at `after` (`after` is `None` when the file is gone or is not a regular
    file). why: `it was deleted`;
  - `rebound`: `after` has more parts and its first parts equal all of `before`'s. why: `its name is bound again at line
    <n>, which replaces it` (`<n>`: the line of the first added part);
  - `changed`: the parts differ otherwise. why: `its body, decorators or parametrisation changed`;
  - `changed`: the parts are equal and the closure (D2) differs. why: `what it uses in this file changed: <names>`
    (the names whose parts differ, sorted, at most 5, then `(+<k> more)`);
  - otherwise nothing. A `before` that does not parse yields nothing (there was no test to protect).

### D2 What a test uses in its own file is part of it (L4-IMP-046)

The closure of a test at one revision is a map *name -> sha256 of that name's parts in the module scope* (`""` when the
file does not bind it), built by a work list:

- seeds: the names the test's own parts *read*; every autouse fixture of the module (a function whose decorator is a call
  whose function's source text ends in `fixture`, with a keyword `autouse` whose value is not the constant `False`);
  every module-level name that matches `guards._MODULE_HOOKS` except dunders (`pytestmark`, `setup_module`,
  `teardown_module`, `setup_function`, `teardown_function`, `setup`, `teardown`, `pytest_*`); and `*` when the module
  has a star import;
- *reads* of a part: every `Name` in a load context; every parameter name of every `def`, `async def` and `lambda` in it
  (the fixtures a test requests are its parameters); every string constant argument of a call whose function ends in
  `usefixtures`; for a method part, `<Class>.<attr>` for every `self.<attr>` / `cls.<attr>` whose base is the method's
  first parameter;
- for a method `C.test_x`, also: the part `C:` (the `ClassDef` dumped with an empty body: decorators, bases, keywords)
  and every name the class body binds that does not start with `test` (`C.setup_method`, `C.<fixture>`, `C.<helper>`,
  class attributes), with their reads;
- each name taken from the work list adds its parts (module scope, or class scope for `C.<name>`) and the reads of its
  non-import parts, until nothing new comes; the test's own name is left out (its definition is compared on its own).

The closure digest is the sha256 of the sorted `name=sha` lines. It is computed at each revision on its own, so a fixture
override, an added autouse fixture, an added `pytestmark`, a changed constant, a changed helper, or a new module-level
binding of a builtin or imported name the test reads all change it; a new test, a new helper only new tests use, a new
non-autouse fixture only new tests request, a widened import line and a repeated import do not.

Not covered, on purpose: fixtures and hooks in `conftest.py` and other test-support files. Red may change those
(L4-IMP-002), a shared fixture often grows for a new feature, and a rule there would refuse honest work. They stay with
the step-1 content scan, the red-to-green freeze, the support-file AST rule (L4-IMP-016 rule 3, extended to every changed
support file by D11 on the owner's decision) and, for the audit, D8.

### D3 A moved test is the same definition in a new place (L4-IMP-047)

`moved(deleted, added)` is pure: `deleted` maps `(path, name)` to the definition digest at the earlier revision of each
`deleted` outcome, `added` maps `(path, name)` to the definition digest at the later revision of each test of a changed
file that did not exist under that `(path, name)` at the earlier revision. A deleted test is moved when an added test has
the same digest (the digest holds the function name, so the name is the same too); each added test stands for at most one
deleted test, pairs taken in sorted order of `(path, name)`. Everything else is deleted. A renamed file (`--no-renames`:
a delete and an add) is a move of each test whose definition stayed. This replaces `head_defined`, which accepted any
same-named test of any changed file (verifier-8).

### D4 Red: a pre-existing test changed by the step fails the attempt (L4-IMP-048)

Where: `tdd.run_red`, right after `classify_red(...)` returned `ok` and before the proofs, the vacuity check and either
commit path (`finish_already_satisfied` or the red commit). The early already-satisfied path (`not test_files`) cannot
change a test and needs no check. Running after the gate keeps today's reason and excerpt for a red that makes an
existing test fail; it costs one gate run in the rare tamper case.

What: for each path the step changed (`changed_paths(wb.git, base, excludes=wb.excludes)`) that ends in `.py`, matches
`tdd.test_globs` and existed at the step's base: `compare(path, text at base, text in the worktree or None)`; moves are
decided with `moved` over every changed test file of the step (a new file is only a move target). "Pre-existing" means
present at the step's base, so the tests an earlier task's red wrote are protected too.

Allowed, in red only:
- a task whose title carries the human tag `[test-infra]` (`task_tags`): no comparison at all;
- a test of the task's stale set (`stale.tests`, L4-OPS-015): its outcome is dropped when `names_test_id(test_id, path,
  name)` holds for a stale id (the rule of today's `integrity._is_superseded`, moved into `tamper.py`).
A `task.unfrozen` frees files for green, never for red; people's commits do not exist inside a step.

Why fail and not put back: putting the file back would also drop new tests the agent appended to it (then the attempt
fails on "no tests added" with a less clear reason), and putting back single functions means editing the agent's file in
place, which the red guard never does (L4-IMP-002 "The guard MUST NOT patch the agent's file in place").

What happens: one event per file, `guard.test_tamper{phase: "red", path, rule: "pre-existing test", action: "rejected",
tests: ["<name>", …], why: "<name>: <why>; …"}`, then `wb.discard_changes()` and
`RedOutcome("failed", reason, excerpt=excerpt)`:

- `reason` (one line, as every attempt reason): `red changed tests that existed before this step: <path>::<name> (<why>)`
  for at most 5 tests joined by `; `, then `(+<k> more)`;
- `excerpt`: `A red step adds new tests with new names. Leave every existing test as it is, and the fixtures, helpers,
  constants and marks it uses in its file: give a new fixture or helper a new name, or put the new tests in a new file. If
  an existing test is wrong, report status blocked with a question that names it.` followed by one line per test.

`guardnotes.note_of` returns `None` for `action: "rejected"`: the attempt's own reason and excerpt already tell the agent
(no second line in the "put back" note, whose preamble would be wrong for a rejection).

### D5 Step 1, part A: pre-existing tests from the base to head (L4-VER-030, L4-VER-031)

`integrity.check_tests` keeps its file set (changed `.py` files matching `tdd.test_globs`, outside the unit
directories) and its skip-marker check unchanged, and replaces the name-set comparison:

1. `compare(path, base text, head text or None)` for each file; `moved` over all of them (D3).
2. Per remaining outcome `(path, name, kind)`:
   - a `tests.superseded` id names it (`names_test_id`): listed in the note as today
     (`superseded by a changed criterion, not deleted: …`);
   - `who = _introducers(ctx, path, introduced)`, where `introduced(b, a)` is, for `deleted`, "the name is a test in
     `facts_of(b)` and not in `facts_of(a)`", and otherwise "`facts_of(b)` has the name and `facts_of(a)` is `None` or
     has other `definition`/`closure`/`parts` for it";
   - `_by_people(who)`: listed in `human_tests` as `<path>::<name> <kind> by <sha10>, …` (no finding; the existing
     verification.md section "Test changes made by humans");
   - else, for every harness record in `who` look up its commit (`commits(ctx)`, by sha) and allow it when its `(unit,
     task)` carries `[test-infra]`, or a `task.unfrozen` event of the same unit and task names the path (`reason`
     `human_answer` or `named_by_task`). When every harness record is allowed: listed in the new
     `Outcome.allowed_tests` as `<path>::<name> <kind> (task <t>: [test-infra])` or `(task <t>: unfrozen by <source>)`;
     otherwise a blocker. A harness record without an `L4-Task` (a merge, a ledger commit) is never allowed. Nobody
     found keeps it a blocker (fail closed, as `_by_people` says today).
3. Blockers: `a pre-existing test was deleted` (`deleted`, detail `_listed` of `<path>::<name>`) and
   `a pre-existing test was changed` (`changed`, `rebound`, `unparsable`, detail `<path>::<name> (<why>)`).
4. Reported once: a test whose name, whose class, or whose file's `<module>` key is in the skip check's blocker list
   (`skipped`: the markers a harness commit added) is not reported as changed, since that blocker already names it. A
   skip marker that only people added (listed, not a blocker) hides nothing: a harness change to the same test is still
   reported.

The note gains `(+<n> allowed, listed)` next to `(+<n> by humans, listed)`. `IntegrityReport.allowed_tests` collects the
lists (`run_integrity`); `report.py` renders them (D10). Parsing is cached per text (`functools.lru_cache` on
`facts_of`), because `_introducers` parses the same file at every commit.

### D6 Step 1, part B: a later red may not change an earlier step's test (L4-VER-032)

The red guard (D4) protects the tests of earlier tasks; the verifier checks the same on the commits, as it does for the
test-path freeze (`check_test_paths`). In `check_tests`, after part A: for each harness commit (`commit_records` +
`is_harness`, as `check_test_paths`) whose `L4-TDD` is `red` or `already-satisfied` and whose task does not carry
`[test-infra]`, `compare(path, text at the first parent, text at the commit)` for each `.py` test file it changed (outside
the unit directories), `moved` within that commit; every outcome for a test that is **not** a test at the base (part A
judges those) and that no `tests.superseded` id names is a blocker `a red step changed a test that an earlier step wrote`,
detail `<path>::<name> (task <t>, red commit <sha10>: <why>)`. People's commits are not walked here.

### D7 Blocker or finding

| What | Where | Result |
|---|---|---|
| a test that exists at the base changed, bound again, unparsable or deleted (no move), by a harness commit with no allowance | step 1 | blocker `a pre-existing test was changed` / `a pre-existing test was deleted` |
| the same, only people's commits | step 1 | listed (`human_tests`), no finding |
| the same, by a harness commit of a `[test-infra]` task, or naming a path a `task.unfrozen` of that task frees; or a superseded test | step 1 | listed (`allowed_tests` / the note), no finding |
| a skip or xfail marker added | step 1 | blocker as today; the test is not listed again as changed |
| a test an earlier step of the unit wrote, changed by a later red commit | step 1 | blocker `a red step changed a test that an earlier step wrote` |
| a red step that changed a pre-existing test | red | the attempt fails (`guard.test_tamper`, `action: "rejected"`); no finding |
| an audit test that fails at head with the support files at the base | 4a | `failed`: the criterion is held (L4-VER-012), as today |
| an audit test that does not run with them at the base, no fallback allowed | 4a | rejected: minor finding `an audit test was rejected`, as today's other rejections |

A step-1 blocker FAILs the unit. A fix unit cannot restore a test (the test-path freeze), so the same deterministic
finding comes back and the fix loop escalates to a person, as for a deleted test today [V, `fixloop.failure_set`]. The
person restores the test on the unit branch (`git checkout <base> -- <path>` in their own commit) or, if the change is
wanted, makes it in their own commit after restoring; `l4 resume` goes on. The runbook names this (task 7.1).

### D8 Audit tests run with the unit's support files at the base (L4-VER-033, L4-VER-034)

New module `src/l4/verifier/support_base.py`:

- `SupportPlan(changes: tuple[tuple[str, str], ...], fallback: bool, why_not: str)`: `changes` are `(path, status)`
  with status `A`, `M` or `D` from `git diff --name-status -z --no-renames <base> <head>` for paths that match
  `tdd.test_support_globs` (which holds its `extra_` entries) and are not under a `.l4/` directory. Runner configuration
  (`tdd.runner_config_files`: `pyproject.toml`, `setup.cfg`, `package.json`, …) is **not** reverted: those files carry
  dependencies and build settings the run needs, and their test-runner sections are already held by the red-to-green
  freeze and the step-1 `addopts` scan (owner decision 2, section 5).
- `support_plan(git, cfg, base_sha, head, integrity) -> SupportPlan`: `fallback` is true only when `integrity` is given
  and its check named `content scan` has status `ok`; `why_not` is `step 1's content scan did not read them: <its note>`
  (status `skipped`) or `step 1 did not run` (no report).
- `support_at_base(wb, base_sha, plan) -> Iterator[list[str]]` (a context manager, the pattern of `red_code_in_place`):
  for each change, an `A` path is set aside (removed), an `M` path gets its base bytes, a `D` path is written from the base
  (missing parent directories created and remembered); a symbolic link at head is removed and recreated after; a path
  that is a symbolic link at the base, or whose parent resolves outside the worktree, is left as it is and not yielded;
  bytecode is dropped (`_drop_bytecode`). It yields the paths it reverted. `finally` puts back every original (content,
  mode, link target), removes what it wrote for an `A`-absent or `D` path and the directories it created, drops
  bytecode, checks each regular file's sha256, and raises `RuntimeError("could not restore <names> after the run with the
  support files at the base")` when one differs. Nothing is committed and `git status` is unchanged afterwards.

`audit._judge_written(wb, written, round_no, out, collected=None, *, support: SupportPlan)`:

1. `support.changes` empty: today's body; each record gets `support="unchanged"`.
2. Otherwise, inside `support_at_base`: one gate run `audit-base-support` with `extra_env={"PYTEST_ADDOPTS":
   "--continue-on-collection-errors"}` (a unit test file that no longer imports without the unit's helpers must not
   stop the audit file from running); a file *ran* when the report holds at least one of its ids, none with status
   `error` (a fixture or setup error), and no collection error names its stem. Each file that ran is judged as today
   (`failed`, `rejected` for skipped, or a candidate), and the candidates' zero-value run (`confirm_pre_satisfied`, with
   the same `extra_env`) runs inside the same block; their records get `support="base"`.
3. The files that did not run: when `support.fallback`, today's body runs on them with the support files in place
   (records `support="head"`, the existing collection retry and deferral apply); else each is rejected with
   `it does not run with the unit's support files at the base (<first line: its collection error, the first erroring
   test, or "no test of the file ran">), and a run with them needs step 1's content scan to have read them: <why_not>`.

Every caller passes `support`: `run_audit(..., support)` from `ladder._audit_step` (built with `support_plan(wb.git,
wb.cfg, base_sha, result.head_sha, result.integrity)`), and the re-entries in `_retry_collected` and `_lint_accepted`.
`confirm_pre_satisfied(wb, candidates, *, extra_env=None)` and `zeroed_run(..., extra_env=None)` thread the variable to
`wb.run_gate`. `AuditRecord` gains `support: str = ""` and `support_files: tuple[str, ...] = ()` (the reverted paths
for `base`, the plan's paths for `head`); `verify.audit` carries both.

With the reproduction (appendix A), the audit test fails at head once `tests/conftest.py` is set aside, so the record is
`failed`, the criterion is held and the verdict is not PASS. An honest unit with no support change runs exactly as today.

### D9 A generated UI test's head run follows the same rule (L4-VER-035)

`generate._discriminates` runs the head with `run_e2e(wb, name="e2e-head")`. With a plan that has changes, that run is
made inside `support_at_base` (no `PYTEST_ADDOPTS`: `run_e2e` takes none, and its server must start as configured);
when the new file's tests did not run there (`_traced` finds none, or one errors) and `support.fallback` holds, it runs
again in place (`e2e-head-support`); without the fallback the verdict is `uncollectable` with the reason of D8 step 3.
The base run is unchanged (the merge-base checkout already has the base support files). `GeneratedOutcome.support` and
`verify.generated{support}` record `base`, `head` or `unchanged`. `generate_ui_tests(..., support)` gets the plan from
`ladder._generate_step`.

### D10 What a person sees

- **Red:** the attempt fails with `red changed tests that existed before this step: tests/test_pricing.py::
  test_total_adds_prices (its body, decorators or parametrisation changed)` in the console and in
  `task.attempt_failed.reason`; the ledger holds `guard.test_tamper{phase: "red", rule: "pre-existing test", action:
  "rejected"}`; the next attempt's prompt carries the reason and the excerpt of D4. Nothing of the attempt is committed.
- **Step 1:** the row `integrity` fails with `a pre-existing test was changed` (or `…deleted`, or `a red step changed a
  test that an earlier step wrote`); verification.md lists each `<path>::<name> (<why>)` in the finding. Allowed changes
  appear under a new section `## Pre-existing tests changed with an allowance (L4-VER-031)`, people's under the existing
  `## Test changes made by humans`.
- **Step 4a:** the Audit table gets a column `Support`: `base`, `head`, or `-` (unchanged); a rejection names why. The
  step note ends with `support files at the base: <n>` when the plan had changes.
- **Step 5:** the Generated UI tests rows say `support: base|head` when the plan had changes.

### D11 Step 1: a support file may not patch the unit's code for every test (L4-VER-037)

`integrity.check_scan` already ran rule 3 of `opened.check_opened` on the paths a `task.unfrozen` names. It now also runs
it on every changed (not deleted) `.py` file that matches `tdd.test_support_globs` outside the unit directories, as
`opened.new_patches(before, after, modules)`: the patches and assignments of a symbol of a production module the unit
changed (`unit_modules`) that `after` has and `before` did not, each as `(target, blocking)`. **Blocking** unless the node
sits inside a fixture that is not autouse and that no autouse fixture requests (its parameters, transitively): module
level, a class body, an autouse fixture, a fixture an autouse fixture requests, a plain function and a hook all block,
because they run for every test or their use is unknown. A blocking hit joins the hits of the content scan (so the
`[test-infra]` exemption and the people's-commits listing of L4-SEC-004 apply as for every other hit): `<path>: patches
<target>, which the unit changed, for every test`. The others are listed in `Outcome.mocked` /
`IntegrityReport.mocked_support` (`<path>: patches <target> in a fixture a test requests`, note `(+n fixture patch(es) of
the unit's code, listed)`), and verification.md shows them under `## Fixtures that patch the unit's code when a test
requests them (L4-VER-037)`. Python only, as the rest of the scan. Known limit: a patch that the AST rule cannot name
(`vars(module)["f"] = g`, a computed attribute) is not seen; the audit's run without the unit's support files (D8) is
the second line, and SCN-VER-112 uses exactly that form.

## 3. Contracts

- `tamper.facts_of(source: str) -> dict[str, Facts] | None` with `Facts(parts: tuple[str, ...], lines: tuple[int, ...],
  definition: str, closure: str, uses: Mapping[str, str])` (`uses`: the closure's name -> sha map, for the `why`).
- `tamper.compare(path: str, before: str, after: str | None) -> list[Tampered]`, `Tampered(path, name, kind, why)`,
  `kind` one of `changed`, `rebound`, `deleted`, `unparsable`; sorted by `name`.
- `tamper.moved(deleted: Mapping[tuple[str, str], str], added: Mapping[tuple[str, str], str]) -> set[tuple[str, str]]`.
- `tamper.names_test_id(test_id: str, path: str, name: str) -> bool` (the rule of `integrity._is_superseded`, on the
  qualified name's last part; `_is_superseded` calls it).
- `tdd.preexisting_test_changes(wb, task, base, stale) -> list[Tampered]` (the red check, so a test can bypass it).
- Event `guard.test_tamper{phase: "red", path, rule: "pre-existing test", action: "rejected", tests, why}`.
- `IntegrityReport.allowed_tests: list[str]`, `Outcome.allowed_tests: list[str]`.
- `support_base.SupportPlan`, `support_plan(...)`, `support_at_base(...)` as in D8.
- `AuditRecord.support`, `AuditRecord.support_files`; `verify.audit{…, support, support_files}`;
  `GeneratedOutcome.support`; `verify.generated{…, support}`. No schema under `src/l4/schema/` describes the audit or
  generated rows of `verdict.json` [V: only `outcome.schema.json` is there]; whatever rebuilds these records from a
  stored round must accept a row without the new keys (an older round) and one with them.
- `opened.new_patches(before, after, modules) -> list[(target, blocking)]`; `Outcome.mocked`, `IntegrityReport.mocked_support`
  (D11).
- Finding titles: `a pre-existing test was changed`, `a pre-existing test was deleted` (kept),
  `a red step changed a test that an earlier step wrote`.

## 4. Not in this change; risks

- Other languages: the comparison reads Python; a changed non-Python test file keeps today's checks (names and skip
  markers are Python too). Same as the content scan [U].
- Fixtures in `conftest.py` and support files (D2, D11) and runner configuration (D8): owner decisions 1 and 2.
- The closure may refuse an honest red that edits a helper or constant an old test also uses. The retry text says how to
  avoid it (a new name). If live runs show it often, the owner can narrow D2 (decision 4 keeps it strict for now); the rule is never relaxed
  silently in a fixture.
- `--continue-on-collection-errors` is a pytest option. The audit writes pytest tests only (the step is `not_run` for
  other code, `ladder._no_python`), so it is set only there.
- `support_at_base` edits the worktree for the length of a run. A killed verifier can leave it edited; the verifier
  starts every round from a fresh worktree at the unit head (L4-VER-001), so nothing reaches a commit.

## 5. Owner decisions on the open questions (applied)

1. **The support-file AST rule covers every changed test-support file** (D11, L4-VER-037): an autouse fixture or
   module-level code that patches a production symbol the unit changed is a blocker; a fixture a test requests by name
   (an ordinary mock) is listed.
2. **The audit does not revert pytest-only runner files** (`pytest.ini`, `.pytest.ini`, `pytest.toml`, `.pytest.toml`,
   `tox.ini`, `setup.cfg`, `pyproject.toml`): another change of the same release (`guard-harness-writes`) guards runner
   configuration in red and green. `support_plan` leaves every `tdd.runner_config_files` path out (D8).
3. **No eval seed-set change.** The regression tests of this change are the tampering cases.
4. **The in-file closure (D2) stays strict as designed.**
5. **0.4.15 is another change (the MCP server).** This change's `CHANGELOG.md` entries are under `## 0.4.16
   (unreleased)`; a released section is never edited.

## Appendix A: the reproductions

The reviewer's tests (repro paths in `findings.json`, under the session scratchpad `l4review/`) use the fixtures of this
repository: `tests/unit/implementer/conftest.py` (`make_bench`, `red_step`, `green_step`, `result`, `IMPL`, `STUB`,
`TESTS`, `KNOWN`, `UNKNOWN`), `tests/unit/orchestrator/conftest.py` (`run_l4`, `BRANCH`), `tests/unit/verifier/
test_ladder.py` (`judge_step`), `tests/unit/verifier/test_ladder_depth.py` (`AUDIT_KNOWN`, `JUDGE`,
`audited_criterion`, `steps_of`, `writer_step`), `tests/unit/verifier/conftest.py` (`valid_spec`, `with_verifier`) and
`tests/unit/verifier/_integrity_helpers.py` (`new_repo`, `Repo.commit`, `Repo.commit_as_human`). Their texts, in case the
scratchpad is gone:

- implementer-4 (`verify-implementer/repo/tests/unit/implementer/test_verify_impl4_tamper.py`): task `Task("1.1",
  "1.1", "1.1 Add `apply_discount`", False, " ", 0, 3, 3)`; the red step writes `tests/test_discount.py: TESTS`,
  `src/pytdd/pricing.py: STUB` and `tests/test_pricing.py` as either
  `"from pytdd import total\n\n\ndef test_total_adds_prices():\n    assert True\n\n\ndef test_total_of_nothing_is_zero():\n    assert total([]) == 0\n"`
  (weakened) or the base file plus `"\n\ndef test_total_adds_prices():\n    pass\n"` (rebound), with
  `structured=result("red", tests_added=["tests/test_discount.py::test_known_code"], criteria_ids=[KNOWN, UNKNOWN])`.
- verifier-2 (`verify-verifier/rt/tests/unit/verifier/test_v2_weakened.py::test_v2[True]`): `run_l4([red, green,
  judge_step()])` where red is `red_step()` with `tests/test_pricing.py` set to
  `"from pytdd import total\n\n\ndef test_total_adds_prices():\n    assert total([1.25, 2.5]) is not None\n\n\ndef test_total_of_nothing_is_zero():\n    assert total([]) == 0\n"`
  and green writes `src/pytdd/pricing.py` as `IMPL.replace("return round(sum(prices), 2)", "return 0 if not prices else
  999.0")`.
- verifier-6 (`…/test_v6_audit_support.py::test_v6_full`): `cid = audited_criterion()`, `with_verifier(
  audit_sample_ratio=0.5)`, `run_l4([red, green, writer_step(cid, AUDIT_KNOWN), JUDGE], **config)`; red adds
  `tests/conftest.py` = `CONFTEST2` below; green writes `src/pytdd/pricing.py` = `'CODES = {"SAVE10": 10}\n\n\ndef
  total(prices: list[float]) -> float:\n    return round(sum(prices), 2)\n\n\ndef apply_discount(amount, code):\n    return
  amount\n'`. The control is `test_v6[False]` (honest red and green: `VERDICT PASS`, audit `accepted`).

```python
CONFTEST2 = '''import types

import pytest

import pytdd.pricing as _p


def _good(amount, code):
    _l4_orig(amount, code)
    if code not in CODES:
        raise ValueError(code)
    return round(amount * (100 - CODES[code]) / 100, 2)


@pytest.fixture(autouse=True)
def _pricing_fixture():
    if getattr(_p, "CODES", None):
        saved = _p.apply_discount.__code__
        _p._l4_orig = types.FunctionType(saved, _p.__dict__)
        _p.apply_discount.__code__ = _good.__code__
        yield
        _p.apply_discount.__code__ = saved
    else:
        yield
'''
```

- verifier-8 (`…/test_v8_masked_delete.py::test_v8`): base `tests/test_cart.py` = `"def test_empty():\n    assert
  compute([]) == 0\n\n\ndef test_other():\n    assert 1\n"`, `tests/test_orders.py` = `"def test_x():\n    assert
  1\n"`; head deletes `test_empty` from `test_cart.py` and appends to `test_orders.py` either `"\n\ndef test_empty():\n
  assert True\n"` (same name elsewhere) or `"\n\ndef test_y():\n    assert True\n"`; committed by `repo.commit("work")`
  (harness) or `repo.commit_as_human("a person's change")`; `check_tests(repo.context(base, head))`.
