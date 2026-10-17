## Purpose

No step can pass a gate by rewriting the configuration that the gate reads. Lint, type-check and scanner settings, and
test-runner settings, are put back after every agent step and every gate run. A task changes them only when a person
said so, through a tag in the task or an answer, and the permission is recorded.

## MODIFIED Requirements

### Requirement: L4-IMP-006 Gate configuration cannot be weakened (part c)
After each agent step and after each gate run, the harness SHALL put back changes to gate configuration and to runner
configuration, as L4-IMP-040 defines both. The exception is a file that L4-IMP-041 opens for the task: through a
human-written `[config]` or `[test-infra]` tag in the task title, or through a person's answer that names the file.
The red-to-green freeze of the runner sections (L4-IMP-002) SHALL NOT be lifted by either.

#### Scenario: SCN-IMP-26 (−) Gate configuration cannot be weakened
- **GIVEN** green sets `"strict": false` in `tsconfig.json` and adds `src/` to `.gitleaksignore`, in a task without a
  `[config]` tag
- **WHEN** the guard runs
- **THEN** both changes are reverted, `guard.violation` logged; the secret scan would ignore the repository's
  `.gitleaksignore` anyway

#### Scenario: SCN-IMP-240 (−) Green's `ignore_errors = True` in `mypy.ini` is put back before the typecheck gate
- **GIVEN** a typecheck gate that fails on the green code unless `mypy.ini` holds `ignore_errors = True`, and a green
  step that writes the implementation and that line, in a task without a tag
- **WHEN** `run_green` runs
- **THEN** `mypy.ini` is back to its content at the red commit before any gate runs, the ledger has
  `guard.violation{phase: green, rule: "gate configuration", path: mypy.ini, action}`, the typecheck gate fails, and the
  green commit is not made

## ADDED Requirements

### Requirement: L4-IMP-040 What gate configuration is (part a)
Gate configuration SHALL be, at any depth, the files matching `tdd.gate_config_globs` or `tdd.extra_gate_config_globs`,
and the lint and type-check sections of manifests: in `pyproject.toml` `[tool.mypy*]`, `[tool.ruff*]`, `[tool.pylint*]`,
`[tool.pyright*]` and the other tools design D6 lists; their `setup.cfg` and `tox.ini` forms; in `package.json`
`eslintConfig`, `eslintIgnore`, `prettier` and `stylelint`.

#### Scenario: SCN-IMP-246 (−) A configuration file in a subdirectory counts
- **GIVEN** a green step that adds `packages/api/ruff.toml` and changes `packages/api/pyproject.toml` `[tool.mypy]`
- **WHEN** the agent-step guard runs
- **THEN** `packages/api/ruff.toml` is removed, `packages/api/pyproject.toml` is back to the red commit, and both
  have violations

### Requirement: L4-IMP-040 A script that a gate command runs belongs to that gate (part b)
The entries that a gate command resolves to (a repository script file it runs, `Makefile`, `justfile`, `tox.ini`,
`[tool.poe]`, or the `package.json` `scripts` entries `X`, `preX`, `postX`) SHALL be gate configuration for the build,
lint, typecheck and extra gates, and runner configuration for the test and e2e gates.

#### Scenario: SCN-IMP-244 (−) A script that a gate command runs is gate configuration
- **GIVEN** `gates.lint: ["npm run lint"]` and `gates.typecheck: ["sh scripts/typecheck.sh"]`, and a green step that
  changes `scripts.lint` in `package.json` to `exit 0` and empties `scripts/typecheck.sh`
- **WHEN** the agent-step guard runs
- **THEN** `package.json` and `scripts/typecheck.sh` are back to the red commit, and each has a `gate configuration`
  violation, with the section `scripts.lint` named for `package.json`

### Requirement: L4-IMP-040 What runner configuration is (part c)
Runner configuration SHALL be, at any depth: the files `pytest.ini`, `.pytest.ini`, `pytest.toml`, `.pytest.toml`,
`.coveragerc` and every `tdd.runner_config_files` entry other than `pyproject.toml`, `setup.cfg`, `tox.ini` and
`package.json`; the runner sections of those four (`[tool.pytest*]`, `[tool.coverage*]`, `[tool:pytest]`, `[pytest]`,
`[coverage:*]`, `jest`, `mocha`, `nyc`, `c8`, `ava`, `scripts.test`); and the entries of part b for the test and e2e
gates.

#### Scenario: SCN-IMP-242 (−) Red cannot plant a pytest plugin through `addopts`
- **GIVEN** a red step that adds `addopts = "-p l4hooks"` to `[tool.pytest.ini_options]` and a root module `l4hooks.py`
  that holds only a stub, and a green step that fills `l4hooks.py` with a hook that turns failures into passes and
  leaves `pricing.py` as the stub
- **WHEN** red and then green run
- **THEN** `pyproject.toml` is back to the base after red with a `runner configuration` violation that names
  `tool.pytest`, and green fails because the red tests still fail against the stub

### Requirement: L4-IMP-040 Sections are compared parsed, and dependencies stay free (part d)
Every other section of a manifest (dependencies, project metadata) and the lock files SHALL stay free. Guarded sections
SHALL be compared parsed (TOML, INI, JSON), so a comment or whitespace edit is no change, and a file that parses at one
end only SHALL count as changed in every guarded section.

#### Scenario: SCN-IMP-245 (+) Red's new test dependency stays
- **GIVEN** a red step that adds `pytest-mock` to `[dependency-groups] dev` in `pyproject.toml` and updates `uv.lock`,
  and touches no guarded section
- **WHEN** the agent-step guard and the red scope run
- **THEN** both changes stay, and no `gate configuration` or `runner configuration` violation is recorded

#### Scenario: SCN-IMP-247 (+) A comment-only edit of a guarded section is no change
- **GIVEN** a green step that only adds a comment line inside `[tool.ruff]` of `pyproject.toml` and reorders two of its
  keys
- **WHEN** the agent-step guard runs
- **THEN** the file keeps the step's edit and no violation is recorded

### Requirement: L4-IMP-040 Configuration is put back after every agent step (part e)
After every agent step (red, green, single), a change in a guarded file or section against the step base that L4-IMP-041
does not allow SHALL put the whole file back to the step base, and a new file SHALL be removed, recorded as
`guard.violation{phase, rule: "gate configuration" | "runner configuration", path, sections, action, task, attempt}` and
carried to the next attempt's prompt. In green, runner configuration SHALL always be put back.

#### Scenario: SCN-IMP-241 (−) Red's `[tool.ruff.lint] ignore = ["ALL"]` puts `pyproject.toml` back to the base
- **GIVEN** a red step, in a task without a tag, that adds a test, a stub, and `[tool.ruff.lint] ignore = ["ALL"]` to
  `pyproject.toml`, and a lint gate that fails on the red test unless that ignore is there
- **WHEN** `run_red` runs
- **THEN** `pyproject.toml` equals the base before any gate runs, `guard.violation{phase: red, rule: "gate
  configuration", path: pyproject.toml, sections: ["tool.ruff"]}` is recorded, the lint gate fails, and no red commit
  carries the ignore

#### Scenario: SCN-IMP-248 (−) Green's runner change is put back even with `[test-infra]`
- **GIVEN** a task titled `1.2 [test-infra] Register the slow marker` whose green step adds `markers` to
  `[tool.pytest.ini_options]`
- **WHEN** the agent-step guard runs in green
- **THEN** `pyproject.toml` is back to the red commit with a `runner configuration` violation, because the red-to-green
  freeze holds for every task

### Requirement: L4-IMP-040 Configuration is put back after every gate run (part f)
After every gate run, in the implementer and in the verifier, any gate or runner configuration that differs from its
content just before the gate SHALL be put back to that content and recorded with `phase: gate` and `where: <gate>`. No
tag or answer SHALL lift this.

#### Scenario: SCN-IMP-243 (−) A test that rewrites `ruff.toml` while the test gate runs does not loosen the lint gate
- **GIVEN** a red test that, when the test gate runs it, appends `ignore = ["ALL"]` to `ruff.toml`
- **WHEN** the test gate finishes and the static gates run
- **THEN** `ruff.toml` holds its bytes from before the test gate, `guard.violation{phase: gate, rule: "gate
  configuration", path: ruff.toml, where: test}` is recorded, and the lint gate judges the original settings

### Requirement: L4-IMP-040 The verifier checks configuration on the commits (part g)
The verifier's step 1 SHALL make a blocker of a harness commit between base and head that changed a guarded file or
section, unless L4-IMP-041 allowed it for that unit, task and phase: a tag, or a `task.config_opened` that names the
file, and runner configuration never in a green commit. A change that only people's commits made SHALL be listed in
`verification.md` under "Gate and runner configuration changed by humans".

#### Scenario: SCN-IMP-249 (−) The verifier blocks a harness commit that loosened `[tool.mypy]`, and lists a person's change
- **GIVEN** a unit branch on which a harness green commit of a task without a tag changed `[tool.mypy]` of
  `pyproject.toml`, and a person's commit changed `ruff.toml`
- **WHEN** the verifier's step 1 runs
- **THEN** the `gate configuration` sub-check fails with a blocker that names `pyproject.toml (tool.mypy)` and the
  commit, and `verification.md` lists `ruff.toml` under "Gate and runner configuration changed by humans"

### Requirement: L4-IMP-041 A tag or a person's answer opens configuration for one task (part a)
Gate configuration SHALL be allowed to change in a step of a task whose title carries a human-written `[config]` or
`[test-infra]` tag, or for which a person's answer opens the file. Runner configuration SHALL be allowed to change in
red and in a fix chore when the task carries `[test-infra]` or an answer opens the file, and never in green. The red
scope (L4-IMP-002) still decides what red may change: a tag lifts this guard only.

#### Scenario: SCN-IMP-250 (+) A `[config]` task may change `ruff.toml` in green
- **GIVEN** a task titled `2.1 [config] Raise the line length to 120` whose green step changes `line-length` in
  `ruff.toml`
- **WHEN** the agent-step guard runs and the verifier checks the commits
- **THEN** the change stays, no violation is recorded, and the verifier's `gate configuration` sub-check passes

### Requirement: L4-IMP-041 An answer opens a file under the rules of L4-IMP-015 (part b)
An answer SHALL open a configuration file that exists at the step base when: its Status is `answered` or `accepted` by
a human (never `answered-by-clarifier`); the ledger records it with the digest of its text as it is now; its question is
not a verdict question and blocks the task or an ancestor; it names the file (an `accepted` suggestion only a file the
question names too); and at most three files open per question.

#### Scenario: SCN-IMP-251 (+) A person's answer that names `pyproject.toml` opens it for the task's red step
- **GIVEN** a red step that asked `Q-003` (technical, blocking task 1.1): "the async tests need `asyncio_mode = "auto"`
  in pyproject.toml", and a person's answer `yes, add it to pyproject.toml`, recorded with its digest
- **WHEN** the task's next red attempt adds `asyncio_mode = "auto"` to `[tool.pytest.ini_options]`
- **THEN** `task.config_opened{task: "1.1", phase: red, paths: ["pyproject.toml"], question: "Q-003"}` is recorded
  before the agent step, the change stays, and the verifier accepts the red commit

#### Scenario: SCN-IMP-252 (−) A clarifier's answer, an answer for another task and an edited answer open nothing
- **GIVEN** three answers that name `mypy.ini`: one `answered-by-clarifier`, one to a question that blocks task 2.1
  only, and one whose text a person edited after the ledger recorded its digest
- **WHEN** green of task 1.1 changes `mypy.ini`
- **THEN** no `task.config_opened` is recorded and `mypy.ini` is put back with a `gate configuration` violation

### Requirement: L4-IMP-041 What an answer opened is recorded (part c)
The harness SHALL record `task.config_opened{task, phase, paths, question, answer_sha256, kept}` before the agent step
it applies to, and the verifier SHALL accept a change that it or a tag allowed. In green, a manifest an answer names
SHALL open for its gate sections only, and a runner-only file SHALL be listed in `kept` with the reason.

#### Scenario: SCN-IMP-253 (−) An answer cannot open runner configuration for green
- **GIVEN** a person's answer to a green question of task 1.1 that names `pytest.ini`
- **WHEN** green runs
- **THEN** `task.config_opened` lists `pytest.ini` under `kept` with `the runner sections are frozen from red to green
  (L4-IMP-002)`, and a green change to `pytest.ini` is put back
