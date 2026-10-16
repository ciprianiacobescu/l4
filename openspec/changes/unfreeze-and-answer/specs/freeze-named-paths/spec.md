## Purpose

The green step of a task may change a frozen Python test-support file that the task's own reviewed text names, and
nothing else that is frozen. A person's answer can unfreeze a support file too. The red proof of the task stays frozen,
and an opened file is checked so that it cannot replace the code under test.

## ADDED Requirements

### Requirement: L4-IMP-014 A task's own reviewed text opens the support files it names
In the green step of a task, the harness SHALL open each path of the red manifest that meets all of these conditions:
- its kind is `support`;
- its name ends in `.py`;
- it is not an ignore file;
- it was a regular file at the red commit;
- the red commit did not add or change it;
- the task's text block or one of its enclosing headings names it.

To open a path means: the path is dropped from the frozen set of that green attempt and kept by the test-path freeze.
The text block is the task's checkbox line and the lines after it, up to the next task line or heading. Its check
marker is read as `[ ]`. The text that names a file is the task's text block and its enclosing headings: the closest
`#` to `####` heading line above the task in the same `tasks.md`, and each parent heading above that, up to the top (a
heading of another section does not count; a `#` line inside a code fence is no heading). A heading is part of the
same reviewed file as the task line, so (a) and (b) below apply to the headings and the text block together.

A path is named when it is a whole token of that text: a repository-relative path, which may be followed by
`:<line>`, sentence punctuation or a backtick. One leading `./` is allowed when it starts the token. There is no case
folding and no glob. A longer or shorter path is another token. A text block that names more than 3 candidates opens
the first 3 in sorted order.

The text block MUST come from a spec that a person reviewed:
- (a) the unit folder at the step's base has the digest that an active delivery plan froze for the unit at activation
  (the plan step carries it into the run); or
- (b) the same task key on the base branch, as the run fetched it, has the same text block after check-mark
  normalisation.

When neither holds, nothing MUST open. A fix unit or a follow-up unit MUST NOT open anything by task text.

Before the agent step, the harness MUST record
`task.unfrozen{task, paths, reason: "named_by_task", source, red_sha, kept}`. `source` is `plan:<plan id>@<digest>` or
`base:<sha>`. `kept` lists each named manifest path that stays frozen, with its reason:
- `a red test of this task`;
- `the red step of this task changed it`;
- `an ignore file`;
- `not a Python file: a person decides`;
- `a symlink at the red commit`;
- `more than 3 paths named`.

The open MUST hold for that task's green attempts only. Every later step MUST freeze the path again. The green prompt
SHALL list the opened paths under `# Files this task names`. The verifier SHALL accept a change of an opened path
between that red commit and its green commit, list it in `verification.md` with its source, and count it as
`(+n opened by task text)`.

#### Scenario: SCN-IMP-159 (+) The task of an activated plan opens the root conftest.py
- **GIVEN** an active plan whose unit has the frozen digest, and task 2.1 "Add `os.environ.setdefault("APP_OTEL_ENABLED", "false")` beside the existing line in the root `conftest.py`, and an autouse fixture"
- **AND** a red commit whose new test asserts the default, and a root `conftest.py` that red did not change
- **WHEN** green adds the line and a new autouse fixture to `conftest.py`
- **THEN** `task.unfrozen{task: "2.1", paths: ["conftest.py"], reason: "named_by_task", source: "plan:<id>@<digest>"}` is recorded before the agent step, the edit is kept, there is no `guard.violation` for `conftest.py`, and the red test passes

#### Scenario: SCN-IMP-160 (+) Outside a plan, the base branch's text is the source
- **GIVEN** a unit that no plan lists, whose task 2.1 has the same text block on the base branch and at the step's base
- **WHEN** green edits the `conftest.py` that the task names
- **THEN** the edit is kept, and the event's `source` is `base:<sha>`

#### Scenario: SCN-IMP-161 (−) Text pushed only to the unit branch opens nothing
- **GIVEN** a unit that no plan lists, and a person's commit on the unit branch that adds "edit `conftest.py`" to task 2.1, which the base branch does not have
- **WHEN** green edits `conftest.py`
- **THEN** no `task.unfrozen` is recorded, the file is put back, and `guard.violation{path: "conftest.py", phase: "green"}` is recorded as today

#### Scenario: SCN-IMP-162 (−) The task's own red test stays frozen
- **GIVEN** a task whose text names `tests/test_otel.py`, a test file that its red step added
- **WHEN** green changes `tests/test_otel.py`
- **THEN** the file is put back with `guard.test_tamper`, and the `task.unfrozen` event (if any path opened) lists `tests/test_otel.py` in `kept` with `a red test of this task`

#### Scenario: SCN-IMP-163 (−) A support file that red changed stays frozen
- **GIVEN** a task whose text names `tests/conftest.py`, and a red commit that added a fixture to `tests/conftest.py`
- **WHEN** green changes `tests/conftest.py`
- **THEN** the file is put back, and it is kept with `the red step of this task changed it`

#### Scenario: SCN-IMP-164 (−) Only an exact path token names a file
- **GIVEN** a repository with a root `conftest.py` and `tests/conftest.py`, neither changed by red
- **WHEN** the task text says, in turn, "the conftest", "`**/conftest.py`", "`../conftest.py`" and "`tests/conftest.py`"
- **THEN** the first three open nothing, and the fourth opens `tests/conftest.py` and not `conftest.py`

#### Scenario: SCN-IMP-165 (−) A symlink, an ignore file and a data file stay frozen
- **GIVEN** a task whose text names `conftest.py` (a symlink at the red commit), `.gitignore` and `tests/fixtures/expected.json`
- **WHEN** green changes all three
- **THEN** all three are put back, and the event's `kept` holds `a symlink at the red commit`, `an ignore file` and `not a Python file: a person decides`

#### Scenario: SCN-IMP-166 (−) A fix unit's task opens nothing
- **GIVEN** a fix unit whose harness-written task names `conftest.py`
- **WHEN** its step changes `conftest.py`
- **THEN** no `task.unfrozen` with `reason: "named_by_task"` is recorded, and the file is put back

#### Scenario: SCN-IMP-167 (+) The verifier accepts and lists an opened file
- **GIVEN** a green commit that changed `conftest.py`, and a `task.unfrozen{reason: "named_by_task"}` of the same unit, task and red commit
- **WHEN** the integrity step runs
- **THEN** there is no freeze or test-path finding for `conftest.py`, and `verification.md` lists `conftest.py (task 2.1, opened by its text, plan:<id>@<digest>)`

### Requirement: L4-IMP-015 A person's answer can unfreeze a support file, and the note says how
A human answer that unfreezes a frozen test file (L4-IMP-002) SHALL also unfreeze a frozen test-support file that it
names, under the same conditions:
- Status `answered`, or `accepted` when the question also names the file;
- the recorded answer digest equals the digest of the answer;
- the question is not a verdict question, and it holds the task;
- at most 3 files per question.

An ignore file MUST stay frozen. The event MUST carry `reason: "human_answer"`. An event without `reason` SHALL read as
`human_answer`.

The note that the harness adds to a technical question of a blocked green step SHALL consider the frozen test and
support files that the question names. It SHALL say:
- which of them an answer can unfreeze;
- that an ignore file is never unfrozen;
- how to answer: Status `accepted` or `answered`, or `l4 questions accept Q-NNN --unit <unit>`.

The note MUST NOT offer an edit that the harness would refuse.

#### Scenario: SCN-IMP-168 (+) An accepted suggestion unfreezes conftest.py
- **GIVEN** a technical question on task 1.1 whose context names `` `conftest.py` ``, the clarifier suggestion "Edit `conftest.py`: add the setdefault line", Status `accepted`, and `question.answered{by: human}` with the digest of the suggestion
- **WHEN** the next green of task 1.1 changes `conftest.py`
- **THEN** `task.unfrozen{paths: ["conftest.py"], reason: "human_answer", question: "Q-001"}` is recorded and the edit is kept

#### Scenario: SCN-IMP-169 (−) An answer that names an ignore file unfreezes nothing
- **GIVEN** an answered question that names `.gitignore`
- **WHEN** the next green changes `.gitignore`
- **THEN** the file is put back, and `.gitignore` is kept with `an ignore file`

#### Scenario: SCN-IMP-170 (+) The note on a blocked green says how to unfreeze a support file
- **GIVEN** a green step that reports `blocked` with a technical question whose first option is "Edit `conftest.py`: add the line"
- **WHEN** the harness writes the question
- **THEN** the note names `conftest.py`, says that `accepted` takes option 1 and unfreezes it for the next green, and names `l4 questions accept Q-NNN --unit <unit>`

### Requirement: L4-IMP-016 An opened support file cannot replace the code under test
After the green agent step, and before the frozen files are put back, the harness SHALL check each `.py` file that is
open in that attempt. For a file opened by task text (L4-IMP-014) all three rules MUST hold. For a file unfrozen by a
person's answer (L4-IMP-015) rule 3 MUST hold.
1. Every top-level statement of the red version is still in the file, unchanged and in the same order. New statements
   may come between them.
2. No new statement binds a name that the red version binds, or a name that pytest reads at module level.
3. No new code patches, deletes or assigns a symbol of a production module that the unit changed. The forms are
   `monkeypatch.setattr` or `delattr`, `mock.patch` and `patch.object`, `mocker.patch`, `setattr`, and an assignment
   to an attribute. The target can be a dotted string or an imported module object. A change of the environment and
   a patch of a module that the unit did not change are allowed.

A file that breaks a rule, does not parse, was deleted, or is (or lies under) a symlink after the step MUST be put back
to its red version. The harness MUST record `guard.violation{rule: "opened file", path, phase: "green", why}`, and the
next attempt's prompt carries `why`. The verifier SHALL check rule 3 again on every path that a `task.unfrozen`
names. A hit SHALL be a blocker.

#### Scenario: SCN-IMP-171 (−) Green rewrites a fixture of the opened file
- **GIVEN** an opened `conftest.py` whose red version defines the fixture `client`
- **WHEN** green changes the body of `client`, or adds a second `def client`
- **THEN** `conftest.py` is put back, and `guard.violation{rule: "opened file", why: "changes an existing statement"}` (or `"rebinds client"`) is recorded

#### Scenario: SCN-IMP-172 (−) Green patches the unit's code from the opened file
- **GIVEN** an opened `conftest.py`, and a unit that changed `src/app/otel.py`
- **WHEN** green adds an autouse fixture with `monkeypatch.setattr("app.otel.enabled", lambda: False)`
- **THEN** `conftest.py` is put back with `why: "patches app.otel.enabled, which the unit changed"`, and an autouse fixture with `monkeypatch.setenv("APP_OTEL_ENABLED", "false")` would be kept

#### Scenario: SCN-IMP-173 (−) Green replaces the opened file with a symlink
- **GIVEN** an opened `conftest.py`
- **WHEN** green replaces it with a symlink to a file outside the repository
- **THEN** the link is removed, the red version is checked out, and `guard.violation{rule: "opened file", why: "a symlink"}` is recorded
