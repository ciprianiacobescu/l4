Every task follows these rules:
- Write the named tests first and see them fail, then write the code.
- Run only the named test files and their folder, for example
  `.venv/bin/python -m pytest -q --no-cov tests/unit/implementer`. Then run `ruff check`, `ruff format --check` and
  `mypy` on the files that you changed.
- Never wait on a process with `while pgrep -f …`: it matches itself.
- Stage explicit paths only.
- Every event key, message and file shape is in `design.md`. Do not change one without the orchestrator.
- The env var of the live case is anonymised as `APP_OTEL_ENABLED`. Never use a product name in a test or a doc.

The bench fixtures are `make_bench` and `raw` (`tests/unit/implementer/conftest.py`). The green helpers are in
`tests/unit/implementer/test_test_path_freeze.py` (`green_after_red`, `freeze_events`) and
`test_tdd_green.py` (`answer_naming`). A support file that exists before red is committed before `run_red`, as the
probe of design section 1.1 did.

## 0. Contract (orchestrator, before wave 1)

- [ ] 0.1 Contracts with no behaviour:
  - `ClarifierCfg.answer_by_agents: bool = False` (`config/schema.py`);
  - `FrozenFile.in_red: bool = False` (`implementer/guards.py`);
  - `PlanStep.activated: Mapping[str, str]` (`yolo/cycle.py`, default empty);
  - `Grant.reason` and `Grant.source` (`implementer/unfreeze.py`; `reason` defaults to `"human_answer"`);
  - new modules whose functions raise `NotImplementedError`: `specs/tasks_text.py` (`task_text(data, task, framework)
    -> str`), `implementer/opened.py` (`check_opened(before, after, *, named_by_task, unit_modules) -> str | None`,
    which returns `why`), `actor.py` (`actor`, moved from `yolo/accept.py`, which re-exports it), and
    `specs/questions_cli.py` (`run_questions`, `run_show`, `run_accept`, `run_answer`).

  Tests: the config default loads and rejects a non-boolean; an old ledger with a `task.unfrozen` that has no `reason`
  folds as before; `yolo/accept.actor` is the same object as `l4.actor.actor`.
  [L4-QMD-009] [L4-IMP-014]

## 1. Wave 1: pure functions (four agents, disjoint files)

### Agent A: `specs/tasks_text.py`

- [ ] 1.1 `task_text(data, task, framework)`: the checkbox line of `task` (by `task.line`) and every following line up to
  the next task line (`OPENSPEC_TASK_RE` or `KIRO_TASK_RE`) or a line that starts with `#`. The marker is read as
  `[ ]` with `digest._MARKER`. Line ends are normalised to `\n`, and a BOM is dropped.
  - Test first, in the new file `tests/unit/specs/test_tasks_text.py`: an OpenSpec one-line task; a Kiro task with
    detail bullets and a `_Requirements:_` line (the same span that `_links_below` reads); the last task of a file; a
    ticked task equals its unticked form; CRLF.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/specs`.
  [L4-IMP-014]

### Agent B: `implementer/unfreeze.py`

- [ ] 1.2 `names_path(text, path, *, dot_slash=False)`: with `dot_slash=True`, one leading `./` that starts the token is
  allowed, and the `./` of `../` is not. The answer rule keeps `dot_slash=False`.
  - Test first, in `tests/unit/implementer/test_unfreeze.py`: SCN-IMP-164 at function level (`the conftest`,
    `` `**/conftest.py` ``, `` `../conftest.py` ``, `` `./conftest.py` ``, `tests/conftest.py` against `conftest.py`
    and against `tests/conftest.py`), `conftest.py:12`, `conftest.py.bak`.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/implementer/test_unfreeze.py`.
  [L4-IMP-014]
- [ ] 1.3 `named_by_task(text, manifest, *, source) -> Unfreeze`: the candidates and the `kept` reasons of design D3,
  at most 3 paths in sorted order, and one `Grant(question=None, reason="named_by_task", source=source)`. Needs 1.2.
  - Test first, in `test_unfreeze.py`: each `kept` reason (a red test of this task, the red step changed it, an ignore
    file, not a Python file, a symlink at red, more than 3), and a pre-existing test file outside the manifest is
    neither opened nor listed.
  - Verify: as 1.2.
  [L4-IMP-014] [SCN-IMP-162, SCN-IMP-163, SCN-IMP-165]
- [ ] 1.4 `unfrozen()` grants a named support file of a human answer (not an ignore file) under the existing
  conditions, with `reason="human_answer"`. The kept reason for an ignore file is `an ignore file`.
  - Test first, in `test_unfreeze.py`: SCN-IMP-168 and SCN-IMP-169 at function level. The existing tests stay green.
  - Verify: as 1.2.
  [L4-IMP-015]

### Agent C: `implementer/opened.py`

- [ ] 1.5 Rules 1 and 2 of design D5: every top-level statement of `before` is in `after`, unchanged (`ast.dump`) and in
  order. No new statement binds a name of `before` or a `_MODULE_HOOKS` name (reuse `_bound` and `_MODULE_HOOKS` of
  `guards.py`). A file that does not parse fails with `why: "does not parse"`.
  - Test first, in the new file `tests/unit/implementer/test_opened.py`: the live case (a new
    `os.environ.setdefault(...)` statement between two old ones, and a new autouse fixture that calls
    `monkeypatch.setenv`) passes; a changed fixture body fails; a second `def client` fails; a removed statement fails;
    a new `pytestmark` fails.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/implementer/test_opened.py`.
  [L4-IMP-016] [SCN-IMP-171]
- [ ] 1.6 Rule 3 of design D5: the patch forms (`monkeypatch.setattr` and `delattr`, `mock.patch`, `patch.object`,
  `mocker.patch`, `setattr`, an attribute assignment) whose target is a dotted string or an imported module object of
  `unit_modules`. `unit_modules(paths, cfg)` derives dotted names from the unit's changed production `.py` files with
  the root rule of `tdd.py:993-999`. A change of the environment and a module that the unit did not change pass.
  - Test first, in `test_opened.py`: SCN-IMP-172 at function level, one test per form, an `import app.otel as o;
    o.enabled = …`, `os.environ[...] = …` passes, `monkeypatch.setattr("time.time", …)` passes.
  - Verify: as 1.5.
  [L4-IMP-016] [SCN-IMP-172]

### Agent D: `implementer/guards.py` and `yolo/cycle.py`

- [ ] 1.7 `build_manifest` sets `FrozenFile.in_red` for every path in its `changed` set. `resume_red` builds its
  manifest the same way (`tdd.py:968`).
  - Test first, in `tests/unit/implementer/test_guards.py`: a support file that red changed has `in_red=True`, and a
    tracked support file that red did not touch has `in_red=False`.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/implementer/test_guards.py`.
  [L4-IMP-014] [SCN-IMP-163]
- [ ] 1.8 The plan step fills `PlanStep.activated` with `state.digests[unit]` for every unit in `allow`, in the CI step
  and in the preview of a named run (`_previewed`). `run_unit_in_worktree` passes it to `Orchestrator(activated=…)`,
  and the services hand it to the `Workbench` (`activated_digest: str | None`, with the plan id).
  - Test first: in `tests/unit/yolo/test_yolo_cycle_run.py`, an allowed unit carries its frozen digest, and a held
    unit does not; in `tests/unit/orchestrator/test_accepted_carrier.py`, the workbench of a planned run has the digest.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/yolo tests/unit/orchestrator`.
  [L4-IMP-014]

## 2. Wave 2: the green step (two agents)

### Agent E: `implementer/tdd.py`, `prompt.py`, `templates/green.md`, `progress.py`

- [ ] 2.1 `task_source(wb, task) -> str | None` returns `None` for a fix unit (`read_fix_marker`) or a follow-up unit
  (`read_follow_up_marker`). It returns `plan:<id>@<digest>` when `unit_digest(wb.git, "HEAD", folder)` equals the
  workbench's activated digest. It returns `base:<sha10>` when `task_text` at HEAD equals `task_text` of the same task
  key in `refs/remotes/origin/<forge.base_branch>:<folder>/tasks.md`. Otherwise it returns `None`. Needs 1.1 and 1.8.
  - Test first, in the new file `tests/unit/implementer/test_named_unfreeze.py`: each source, a unit-branch-only text
    gives `None`, a fix unit gives `None`, and a missing base ref gives `None`.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/implementer/test_named_unfreeze.py`.
  [L4-IMP-014] [SCN-IMP-160, SCN-IMP-161, SCN-IMP-166]
- [ ] 2.2 `unfreeze_for` adds the `named_by_task` grant when `task_source` gives a source. `run_green` drops all opened
  paths from the manifest and keeps them in `freeze_test_paths`. It writes one `task.unfrozen` per reason
  (`reason`, `source`, `kept`, and `question`/`answer_sha256` only for `human_answer`). Needs 1.3, 1.4, 2.1.
  - Test first, in `test_named_unfreeze.py`: SCN-IMP-159 (the probe's setup with a task text that names
    `` `conftest.py` ``, at bench level, under a plan source and under a base source), SCN-IMP-161, SCN-IMP-162,
    SCN-IMP-165, SCN-IMP-166. The tests of `test_test_path_freeze.py` and `test_tdd_green.py` stay green.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/implementer`.
  [L4-IMP-014] [SCN-IMP-159, SCN-IMP-161, SCN-IMP-162, SCN-IMP-165, SCN-IMP-166]
- [ ] 2.3 After the agent step and before `restore_frozen`, `run_green` runs `check_opened` on each opened `.py` path
  (all rules for `named_by_task`, rule 3 for `human_answer`). It also checks with `reject_symlinks` that the path and
  its parents are no symlinks, and that the file was not deleted. A failure puts the file back to the red version and
  records `guard.violation{rule: "opened file", path, phase: "green", why}`. `guardnotes.py` gets the rule's sentence.
  Needs 1.5, 1.6, 2.2.
  - Test first, in `test_named_unfreeze.py`: SCN-IMP-171, SCN-IMP-172, SCN-IMP-173. In
    `tests/unit/implementer/test_guard_notes.py`: the note of the rule.
  - Verify: as 2.2.
  [L4-IMP-016] [SCN-IMP-171, SCN-IMP-172, SCN-IMP-173]
- [ ] 2.4 The green prompt gets the section `# Files this task names` (design D4) in a data block. `templates/green.md`
  allows a change to a listed file and says that an ignore file is never unfrozen. `progress.py` prints
  `task <k> opened by its text (<source>): <paths>` for `named_by_task`, and keeps today's line for a human answer.
  - Test first: `tests/unit/implementer/test_prompt.py` (the section, and that the section is absent with no open);
    `tests/unit/obs/test_progress.py` (both lines).
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/implementer/test_prompt.py tests/unit/obs`.
  [L4-IMP-014]

### Agent F: `implementer/loop.py` and the note

- [ ] 2.5 `_frozen_tests` becomes `_frozen_paths`: test and support files, without ignore files.
  `unfreeze_note(text, frozen, ignore=…, suggested=…, unit=…, qid_hint=True)` says which named files an answer can
  unfreeze, says that an ignore file never unfreezes, and names `l4 questions accept Q-NNN --unit <unit>`. The note
  never offers an edit that the harness refuses. Needs 1.4.
  - Test first, in `tests/unit/implementer/test_unfreeze_note.py`: SCN-IMP-170; a question that names `.gitignore`;
    a question that names nothing. In `tests/unit/implementer/test_loop.py`: a blocked green with `conftest.py` in
    option 1 gets the new note.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/implementer/test_unfreeze_note.py
    tests/unit/implementer/test_loop.py`.
  [L4-IMP-015] [SCN-IMP-170]

## 3. Wave 2: the verifier (one agent)

### Agent G: `verifier/integrity.py`

- [ ] 3.1 `_unfrozen_paths` returns the reason and the source. `check_freeze` lists
  `<path> (task <k>, opened by its text, <source>)` for `named_by_task`, and counts `(+n opened by task text)` apart
  from `(+n unfrozen by human answers)`. `check_test_paths` stays as it is: it already reads `paths`.
  - Test first, in `tests/unit/verifier/test_integrity.py`: SCN-IMP-167; and a `named_by_task` event of another red
    commit does not allow the change.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/verifier`.
  [L4-IMP-014] [SCN-IMP-167]
- [ ] 3.2 `check_scan` runs rule 3 (`opened.check_opened` with only rule 3) on each changed `.py` path that a
  `task.unfrozen` of the unit names. A hit is a blocker `an opened support file patches the unit's code`. Needs 1.6.
  - Test first, in `test_integrity.py`: a green commit that adds `monkeypatch.setattr("app.otel.enabled", …)` to an
    opened `conftest.py` is a blocker, and `monkeypatch.setenv` is not.
  - Verify: as 3.1.
  [L4-IMP-016] [SCN-IMP-172]

## 4. Wave 3: `l4 questions` (two agents, after waves 1 and 2)

### Agent H: `specs/questions.py` and `specs/questions_cli.py` (read side, edit)

- [ ] 4.1 `QuestionsFile.set_answer(qid, text)`: it replaces the body of the `### Answer` block with the comment line
  (kept when present), the text and one line end, or it adds the block at the end of the section. It works on spans
  only and keeps the line endings.
  - Test first, in `tests/unit/specs/test_questions.py`: LF and CRLF files; a section without an Answer block; a BOM;
    bytes outside the spans unchanged.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/specs/test_questions.py`.
  [L4-QMD-008]
- [ ] 4.2 Reading. Fetch with `fetch_unit_refs` (a failure is a warning). Then:
  - read `questions.md` at a ref with `cat-file`: a symlink entry is refused, and so is a file over
    `MAX_QUESTIONS_BYTES`;
  - list the folders: a unit, its fix units on its branch, or a fix unit by id on its parent's branch;
  - `run_questions` lists open questions, drafts and unreadable sections, with the `Next:` line and `--json`
    (`l4/questions@1`).

  A test world in the new file `tests/unit/specs/questions_world.py`: a bare origin, two unit branches and a fix unit
  folder (model: `tests/unit/yolo/yolo_cmd_world.py`).
  - Test first, in the new file `tests/unit/specs/test_questions_cli.py`: SCN-QMD-12, SCN-QMD-14, a failed fetch, and
    a symlinked `questions.md`.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/specs`.
  [L4-QMD-007] [SCN-QMD-12, SCN-QMD-14]
- [ ] 4.3 `run_show`: the section, the `accept takes:` line, the frozen paths that the suggestion names (from the latest
  `task.red_ok.frozen` of each held task in the unit's ledger at the ref) with "would unfreeze" per D7, the agent
  verdict of D11, and the `Next:` lines. A verdict question gets the `accept`/`reject` hint. Needs 4.2 and 1.4.
  - Test first, in `test_questions_cli.py`: SCN-QMD-13, and a verdict question.
  - Verify: as 4.2.
  [L4-QMD-007] [SCN-QMD-13]
- [ ] 4.4 The edit and its checks, as pure functions:
  - `edit_accept` and `edit_answer` (set_status and set_answer);
  - the round trip of design D9 step 4;
  - the text checks of R10: empty, more than 20,000 characters, a structural line (`_STRUCTURAL`, `_FIELD`,
    `_SUBHEADING`, a fence) named by its line number, an HTML comment, a redactor hit named by its kind;
  - the question checks R3 to R5 and R7 to R9 (`verdicts._DECISION`).
  Needs 4.1.
  - Test first, in `test_questions_cli.py`: SCN-QMD-18, SCN-QMD-21, SCN-QMD-22, R4b (superseded), R5 (draft), R7.
  - Verify: as 4.2.
  [L4-QMD-008] [SCN-QMD-18, SCN-QMD-21, SCN-QMD-22]

### Agent I: the write, the agent rule and the CLI

- [ ] 4.5 The write: a private index (`GIT_INDEX_FILE` under the harness cache), `read-tree H`, `update-index
  --cacheinfo` with the old mode, `write-tree`, `commit-tree -p H` with the message of design D9. Then a push of
  `<sha>:refs/heads/<branch>` without force, with `push_auth_config`.
  - A not-fast-forward rejection is R12.
  - Any other failure exits 1 with `explain_push_failure`.
  - On success, the tracking ref moves, and a `git pull` hint is printed when the branch is checked out.
  - `--no-push` prints the unified diff and the message, and creates no object.

  Needs 4.4.
  - Test first, in `test_questions_cli.py` with the world of 4.2: SCN-QMD-15 (up to the push; the message has no `L4-`
    line and no `[skip ci]`; author = the test's git identity), SCN-QMD-16, SCN-QMD-17, SCN-QMD-19 (a second clone
    pushes between the fetch and the push).
  - Verify: as 4.2.
  [L4-QMD-008] [SCN-QMD-15, SCN-QMD-16, SCN-QMD-17, SCN-QMD-19]
- [ ] 4.6 R1, R2, R6 and R13: an unknown unit, no branch, a finished phase (from the folded state at the ref with the
  pending ledger), and a live run. Move `_refuse_live_run`'s rule of `state/restart.py:259-268` to a shared function
  and use it in both commands.
  - Test first, in `test_questions_cli.py`: SCN-QMD-20, a `merged` unit, an unknown unit. `tests/unit/state/
    test_restart.py` stays green.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/specs tests/unit/state`.
  [L4-QMD-008] [SCN-QMD-20]
- [ ] 4.7 The agent rule of design D11 uses `l4.actor.actor`. It reads `clarifier.auto_accept_kinds` and
  `clarifier.answer_by_agents` from `.l4/config.yaml` at `refs/remotes/origin/<base>` (generalise
  `yolo/accept.target_config` to return the whole config, and keep the `yolo.review` accessor). The commit body says
  `By: <name> (person)` or `(agent: <marker>)`. Needs 4.3 and 0.1.
  - Test first, in the new file `tests/unit/specs/test_questions_agents.py`: SCN-QMD-23, SCN-QMD-24 (base key, and
    unit-branch-only key), SCN-QMD-25, a verdict question by an agent, and a person with no terminal on stdin is an
    agent. `tests/unit/yolo/test_yolo_accept_rules.py` stays green.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/specs tests/unit/yolo/test_yolo_accept_rules.py`.
  [L4-QMD-009] [SCN-QMD-23, SCN-QMD-24, SCN-QMD-25]
- [ ] 4.8 The CLI:
  - `l4 questions` with the forms `[list]`, `show Q`, `accept Q`, `answer Q --text T`, plus `--unit`, `--json`,
    `--no-push`;
  - the help text of L4-OPS-017;
  - `commands.HANDLERS["questions"]` names `l4.specs.questions_cli:run_questions`, which dispatches the forms;
  - `OWNING_CHANGE["questions"] = "unfreeze-and-answer"`;
  - remove the stub of `questions.py:190-192`.
  Update `tests/unit/cli/test_dispatch.py`: `questions` is no longer "not yet implemented" (lines 92-95 keep `unlock`
  and `ci render`), and the argument row of line 36.
  - Test first: in `tests/unit/cli/test_dispatch.py`, `l4 --help` has the new text, and `l4 questions --help` lists
    the four forms.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/cli tests/unit/specs`.
  [L4-QMD-007] [L4-QMD-008] [L4-OPS-017]

## 5. Docs and skill (one agent, after wave 3)

- [ ] 5.1 Runbook:
  - 7.1: the command first (`show`, then `accept` or `answer`), then the hand edit as the other way, and the agent
    rule in one NOTE;
  - remove the NOTE of line 614;
  - 10.4: add the row;
  - line 1283: remove `l4 questions`;
  - 10.5: the `questions.md` row names the command;
  - 11: the agent rule and the `--no-push` dry run;
  - 7.2: a short note that a green question about a support file can be answered with `accept`.
  - Test first, in the new file `tests/unit/docs/test_unfreeze_and_answer_docs.py`: SCN-OPS-27 (runbook part).
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/docs`.
  [L4-OPS-017] [SCN-OPS-27]
- [ ] 5.2 Skill `references/operate.md`:
  - "Answering `questions.md`" starts with the command;
  - it states the agent rule;
  - it tells an agent to give a product, ambiguous or verdict question, or an answer that names a frozen path, to a
    person unless `clarifier.answer_by_agents` is `true`;
  - it keeps the hand edit as the fallback.
  `SKILL.md`'s line about `operate.md` names the command.
  - Test first, in `test_unfreeze_and_answer_docs.py`: SCN-OPS-27 (skill part).
  - Verify: as 5.1.
  [L4-OPS-017] [SCN-OPS-27]
- [ ] 5.3 Skill `references/spec.md`: a task that must change a test-support file names it exactly (`` `conftest.py` ``,
  not "the conftest"). Only a Python support file that the task's red step does not change opens, only for that
  task's green, and only from a reviewed text (an active plan, or the base branch). A data fixture or an ignore file
  needs a person's answer. `[test-infra]` does not open a support file in green.
  - Test first, in `test_unfreeze_and_answer_docs.py`: the needles.
  - Verify: as 5.1.
  [L4-IMP-014]

## 6. `docs/SPEC.md` (orchestrator)

- [ ] 6.1 §7.2 L4-IMP-002, green:
  - an answer may also unfreeze a support file, but never an ignore file (replace "a support or ignore file stays
    frozen");
  - green (a) runs the red tests "except the paths of a `task.unfrozen` of the task";
  - point to L4-IMP-014..016.

  Add L4-IMP-014 and L4-IMP-015 after L4-IMP-002, and L4-IMP-016 in §7.5 after L4-IMP-006, with the text of
  `specs/freeze-named-paths/spec.md`. Add SCN-IMP-159..173 to §23.7.
  - Verify: `.venv/bin/python scripts/check_spec.py docs/SPEC.md`.
  [L4-IMP-014] [L4-IMP-015] [L4-IMP-016]
- [ ] 6.2 §7.5 L4-IMP-006 (7): the first exception says "a human answer freed them (L4-IMP-002), or the task's own
  reviewed text named them (L4-IMP-014)". Add one sentence: "The `[test-infra]` tag lifts this freeze only; it does
  not lift the red-to-green freeze of L4-IMP-002."

  §10.2 step-1 row:
  - opened files are listed with their source and counted `(+n opened by task text)`;
  - the "support files never replace the code under test" rule is checked for opened files (L4-IMP-016) and stays [U]
    for other support changes.

  §12.1: `task.unfrozen{task, paths, reason, source, question, answer_sha256, red_sha, kept}`.
  - Verify: as 6.1.
  [L4-IMP-014] [L4-IMP-016]
- [ ] 6.3 §6.2: add L4-QMD-007..009 after L4-QMD-006. §2.1 row 424: the four forms, "commits and pushes to the unit
  branch; `--no-push` shows the change". §3.2 `clarifier`: `answer_by_agents: false` with its comment. §23.8: add
  SCN-QMD-12..25.
  - Verify: as 6.1.
  [L4-QMD-007] [L4-QMD-008] [L4-QMD-009]
- [ ] 6.4 §23.19: add L4-OPS-017's scenario SCN-OPS-27, and the requirement text in the operator-commands section. §21:
  add row 20 `unfreeze-and-answer` with its requirement ranges.
  - Verify: as 6.1.
  [L4-OPS-017]

## 7. Orchestrator: integration, review, live check

- [ ] 7.1 Merge the waves. Run the full suite, `ruff check`, `ruff format --check` and `mypy src`. Run `openspec
  validate unfreeze-and-answer --strict`.
- [ ] 7.2 Adversarial review on the session model, not by the implementers. Try to open a proof path:
  - a named red test, a support file that red changed, `../conftest.py`, a symlinked `conftest.py` or parent folder;
  - a text that only the unit branch has, and a fix unit's task;
  - a patch through an alias, and a shadowing fixture.
  Try to answer as an agent without the key, and with the key only on the unit branch. Check that every refusal
  changes nothing on `origin`. Record the results in `docs/live/unfreeze-and-answer/review.md`.
- [ ] 7.3 Live check on a dummy repository (the public GitHub dummy or the GitLab dummy):
  1. Make a plan whose unit's task names the root `conftest.py` (the anonymised live case). Activate it, and see
     `task.unfrozen{reason: "named_by_task"}` and a green commit.
  2. Raise a product question, answer it with `l4 questions answer`, and see the pushed commit start CI and the unit
     leave `awaiting_human`.
  Keep the evidence under `docs/live/unfreeze-and-answer/`. Leave the dummies for the user to delete.
