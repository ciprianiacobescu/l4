# Unfreeze and answer: a task opens the files it names, and `l4 questions` answers on the unit branch

Status: design draft, 2026-10-16. Harness at 0.4.1 plus the fixes of branch `fix-042` (4ccbe035). Markers: **[V]**
verified (read in the code at the cited line, or run), **[I]** inferred (follows from the code, not run end to end),
**[G]** a chosen number with no measurement behind it.

## 0. The answer in six lines

1. The deadlock is real and has no exit today. Green may not change a tracked test-support file (the red-to-green
   freeze of L4-IMP-002). The `[test-infra]` tag lifts a different freeze. A person's answer never unfreezes a support
   file. A probe on this branch reproduced the live log line in both cases (section 1.1) [V].
2. Decision: a frozen **Python support file that the task's own text names exactly** opens for that task's green
   (`task.unfrozen{reason: "named_by_task"}`). The text must be what a person reviewed: the unit folder has the digest
   that an active plan froze at activation, or the task's text is the same on the base branch (D2, D3).
3. What keeps the guard's purpose: the task's red tests stay frozen, and so does every support file that its red step
   changed. The opened file must keep all its old statements, and it must not rebind a name or patch the unit's code
   (D5, D6).
4. A person's answer can now unfreeze a support file (not an ignore file). The harness note on a blocked green
   question says what an answer can and cannot unfreeze (D7).
5. `l4 questions` reads `questions.md` from the fetched unit branch and writes it with the harness's own parser and
   section-scoped edits. It makes one plain commit as the operator (no `L4-Run:` trailer, no `[skip ci]`, so CI
   starts) and pushes without force. `--no-push` is dry (D8 to D10).
6. Agents: the actor rule of `l4 yolo accept`. An agent may answer the kinds in `clarifier.auto_accept_kinds` when the
   answer names no frozen path. Everything else needs `clarifier.answer_by_agents: true` on the base branch (D11).

## 1. Current state

### 1.1 The deadlock, reproduced

- The green step does this in order (`src/l4/implementer/tdd.py:1016-1033`) [V]:
  1. It computes the answers that unfreeze something (`unfreeze_for`).
  2. It drops their paths from the red manifest.
  3. It runs the agent.
  4. `restore_frozen(manifest)` puts back every file of the manifest that differs from the red commit.
  5. `freeze_test_paths` puts back every other changed path of the test and support globs, unless the task carries
     `[test-infra]`.
- The red manifest holds every test file that red changed or added (`kind: "test"`). It also holds **every tracked
  file** that matches `tdd.test_support_globs` or an ignore-file glob (`kind: "support"`). The support globs are tested
  first (`src/l4/implementer/guards.py:58-74`) [V]. The defaults hold `**/conftest.py` in both the test globs and the
  support globs (`src/l4/config/defaults.py:27-34`), so a root `conftest.py` is a support file [V].
- `restore_frozen` records a changed support file as `guard.violation{path, phase: "green"}`
  (`guards.py:231-249`) [V]. That is the live log line. The test-path freeze writes `guard.test_tamper{rule: "test path
  freeze"}` instead (`guards.py:283-288`) [V].
- `unfrozen()` keeps a named support or ignore file frozen with the reason "a support or ignore file stays frozen"
  (`src/l4/implementer/unfreeze.py:120-124`) [V]. SPEC L4-IMP-002 says the same. When nothing else is unfrozen, the
  green step writes **no** `task.unfrozen`, because `unfreeze.paths` is empty (`tdd.py:1018`), so the `kept` reason
  reaches nobody [V].
- The note that the harness adds to a blocked green question considers only frozen **test** files
  (`src/l4/implementer/loop.py:126-127`, `unfreeze.py:65-88`). The green template promises: "a person who accepts that
  option unfreezes exactly that file" (`templates/green.md:5`). For a support file that promise is false [V].
- **Probe** (a temporary test with the fixtures of `tests/unit/implementer/test_test_path_freeze.py`, run with
  `.venv/bin/python -m pytest` and then deleted; the working tree was clean afterwards) [V]:
  - PROBE1: a root `conftest.py` committed before red, the task titled `... [test-infra]`, a green that appends
    `os.environ.setdefault(...)`. Result: the manifest kind is `support`, green's edit was put back, and the ledger has
    `guard.violation ('conftest.py', 'green')`.
  - PROBE2: the same without the tag, with a technical question that names `` `conftest.py` `` in its context. The
    clarifier suggestion is "Edit `conftest.py`: add the setdefault line", the Status is `accepted`, and
    `question.answered{by: human}` is recorded with the digest. Result: no `task.unfrozen`, the edit was put back, and
    the ledger has `guard.violation ('conftest.py', 'green')`.

### 1.2 What `[test-infra]` does

- The tag is read by `task_tags(title)` (`src/l4/verifier/scan.py:236`) [V]. It is used in five places, and none of
  them is the red-to-green freeze [V, `grep -rn "test-infra" src/l4`]:
  - `freeze_test_paths` returns early (`tdd.py:1065`), after `restore_frozen` already ran at `tdd.py:1032`;
  - the verifier's test-path check skips the task's commits (`src/l4/verifier/integrity.py:409, 416`);
  - the verifier's content scan does not scan the files that the task's commits touched (`integrity.py:483-489, 505`);
  - the verifier's TDD history skips the task, because `test-infra` is a TDD-exempt kind
    (`integrity.py:665-666`, `defaults.py:26`);
  - L4-IMP-006 (3) does not revert a gate-config change of a task with the tag (SPEC text).
- The verifier's red-to-green check `check_freeze` has no tag exception (`integrity.py:343-378`). A support file that
  changed between the red commit and the green commit is a blocker unless a `task.unfrozen` of that red commit names
  it (`integrity.py:330-340, 357-358`) [V].
- `run_task` does not run a tagged task in one phase: only `chore_findings` (a fix unit's chore) selects the single
  phase (`src/l4/implementer/loop.py:183-186`). The TDD exemption of L4-IMP-003 is M1 (`tdd.py:9`) [V]. PROBE1 ran
  red and then green with the tag.
- So the code does what SPEC says. L4-IMP-006 (7) names the tag as an exception of the **test-path** freeze. L4-IMP-002
  green and the §10.2 row "red→green freeze held" have no tag exception. The tag was not designed for this case. It
  cannot cover the case unless L4-IMP-002 changes.

### 1.3 Questions today

- The `questions` handler is a stub that exits 2 (`src/l4/specs/questions.py:190-192`). The CLI row takes free
  `words`, `--unit` and `--text` (`src/l4/cli.py:135-137`). `OWNING_CHANGE` names `spec-providers`
  (`src/l4/commands.py:72`). SPEC §2.1 calls it a "Local helper for humans" that "edits `questions.md`"
  (`docs/SPEC.md:424`) [V].
- The parser and the writers exist. `QuestionsFile.parse` never raises on content. `set_status` changes the Status
  value and that question's index row (`questions.py:456-461`). `set_suggestion` (`:480-496`) and the splice
  (`:609-619`) keep every other byte. There is no writer for the `### Answer` body [V].
- An answer counts when the run that follows reads it. `Clarifier.reenter` records `question.answered{by: human,
  answer_sha256}` at the start of the unit's next run (`src/l4/orchestrator.py:362-370`). `answered_by` returns `human`
  for every Status but `answered-by-clarifier` (`questions.py:559-560`) [V].
- A verdict answer must start with `accept` or `reject`: `_DECISION` (`src/l4/verifier/verdicts.py:49`) [V].
- CI starts on a push to a unit branch. GitHub: `on.push.branches: [base, prefix]` (`src/l4/ci/templates/l4.github.yml:10-12`).
  GitLab: the rule on the unit-branch prefix (`l4.gitlab-ci.yml:35`). A push whose message has an `L4-Run: ` trailer
  starts nothing off the base branch (`l4.gitlab-ci.yml:32`; the GitHub template's header, lines 5-7) [V].
- Outside CI with the `forge.token_env` variable empty, a push uses the person's own git credentials
  (`src/l4/forge/gitlab.py:499-513`) [V].
- A fix unit's questions are in `<unit folder>-fix-<n>/questions.md` on the parent's branch (`docs/runbook.md:558`;
  `tdd.py:1174-1175` reads a fix unit's own ledger beside the parent's). The parent stays `fixing` while they are open,
  and the planner says `fixing: fix unit questions open: …` (`src/l4/planner.py:160-162`) [V].

## 2. Decisions

### D1. Why not the `[test-infra]` tag

The alternative that was proposed: use the tag. Under it, the readiness review, `validate_plan.py` and the skill flag a
task that names a test-infrastructure path without the tag, and the blocked question tells the person to add the
tag. That does not work, for two reasons:

1. **It does not unblock.** The tag does not lift the red-to-green freeze, in the implementer (`tdd.py:1032` before
   `:1065`) or in the verifier (`check_freeze`, no tag test). PROBE1 shows the live line with the tag present [V].
   Telling a person to add the tag would send them to a second dead end.
2. **Making the tag work would open too much.** The tag is a TDD exemption. To make it lift the red-to-green freeze,
   L4-IMP-002 must change, and the task would then also get every other effect of the tag (section 1.2): all its test
   paths free in green, no content scan of its files, no TDD history, no gate-config revert. The live task had a real
   red test that was worth keeping. The tag would throw away the checks that matter most when a support file changes.

Chosen: a narrow rule that opens only the named Python support file, only for that task's green, and keeps the
content scan, the TDD history and the red tests (D3 to D6). From that alternative this design keeps:
- (b) as the true note on a blocked question (D7);
- the skill's spec-writing advice to name such a file exactly (task 5.3).

The tag stays as it is. Task 6.2 adds one SPEC sentence that says that the tag does not lift the red-to-green freeze,
so that nobody makes the same mistake again.

### D2. Where the task text comes from, and why it is a person's text

The text is read from the unit's `tasks.md` at the green step's base (the work tree at HEAD). These rules make it a
person's text:

- **No agent can write it during a run.** The spec root (`openspec/**`, `.kiro/specs/**`) is a protected path that the
  harness puts back after every agent step (L4-SEC-004, L4-IMP-006 (1)). The harness's own writes to `tasks.md` are
  check marks only. Those are normalised (`src/l4/yolo/digest.py:31, 62-65`) [V].
- **It must be the reviewed text.** One of these must hold, or nothing opens:
  - **(a) An active plan's frozen digest.** The plan step lets a planned unit run only while the unit folder's digest
    equals the digest frozen at activation. A changed folder stops the plan with `inputs_changed`
    (`src/l4/yolo/cycle.py:1038-1051, 575-578`) [V]. The digest covers every file of the folder except `.l4/`,
    `questions.md`, `verification.md` and `feedback.md`, and reads every check mark as `[ ]`
    (`digest.py:68-99`) [V]. A person activated the plan after its readiness review (L4-YOLO-005). The plan step
    already carries per-unit data into the unit run: `PlanStep.accepted` reaches `Orchestrator(accepted=…)`
    (`cycle.py:113-120`, `orchestrator.py:235, 1506`) [V]. This design adds `PlanStep.activated: unit id → digest`
    beside it. The workbench gets the digest. At each green step it computes `unit_digest(git, HEAD, folder)`, and
    when the two are equal the source is `plan:<plan id>@<digest>`.
  - **(b) The base branch.** The task's text block (D3) at HEAD equals, after check-mark normalisation, the block of
    the task with the same key in the unit folder on `refs/remotes/origin/<forge.base_branch>` as the run fetched it.
    Text on the base branch went through the project's own merge. The source is `base:<sha of that ref, 10
    characters>`.
- **Which units can use it.** A fix unit (`.l4/fix.json`) and a follow-up unit (`.l4/followup.json`) never open
  anything by task text. The harness writes their `tasks.md` from findings or feedback, so the text is not a reviewed
  spec. A unit whose text is in neither source opens nothing. Its green behaves as today.

Rejected: trusting the text on the unit branch alone. A person, or an agent that acts with a person's push rights,
could push a task text that names `conftest.py` and so open it. Source (a) or (b) means that a person reviewed the
text before it took effect.

### D3. What the task text is, and how a path is named

- **The text block.** The text block of a task is its checkbox line plus every following line, up to the next task
  line (the provider's own task regex: `OPENSPEC_TASK_RE`, `KIRO_TASK_RE`) or a Markdown heading. This is the span that
  Kiro's `_links_below` reads (`src/l4/specs/kiro.py:119-128`) [V]. The marker is read as `[ ]`. A new helper
  `task_text(data, task, framework)` in `src/l4/specs/tasks_text.py` returns it. `Task` has only the title
  (`src/l4/specs/base.py:125-139`) [V], so the helper reads the file.
- **Ancestors do not count.** Only the task's own block counts. A parent task's text does not, because a parent may
  span tasks with different needs.
- **Candidates.** A candidate is a path of the red manifest whose kind is `support` and that meets all of these
  conditions. Paths come from the manifest, not from the text, so a path outside the repository, a `..` segment or a
  glob can never be a candidate:
  - it ends in `.py`;
  - it is not an ignore file (`IGNORE_FILE_GLOBS`, `guards.py:27`);
  - it was a regular file at the red commit (`FrozenFile.sha256 is not None`; `None` means a symlink or an unreadable
    file, `guards.py:30-33, 51-55`);
  - the red commit did not add or change it.
  The manifest gains `FrozenFile.in_red: bool`, the `changed` set of `build_manifest` (`guards.py:63`).
- **Named.** The rule of `names_path(text, path)` (`unfreeze.py:55-59`) [V], with the `./` allowance below, holds for
  the text block and the path. The allowance is a keyword argument of `names_path`, and the answer rule of D7 does not
  use it.
  - A path is a token: `conftest.py` does not name `tests/conftest.py`, and `tests/conftest.py` does not name
    `conftest.py`. A longer path, such as `conftest.py.bak` or `dir/conftest.py`, is another token.
  - A path may be followed by `:<line>`, by sentence punctuation, or by a closing backtick.
  - Normalisation: the text is read as UTF-8 NFC. One leading `./` before a path token is allowed when the `./`
    itself starts the token, so `./conftest.py` names `conftest.py` and `../conftest.py` does not. `verdicts._names_path`
    (`verdicts.py:104-106`) accepts any `./` before the path, so it would accept `../conftest.py`. It is not reused.
    Nothing else is normalised: no case folding, no backslashes, no globs.
- **At most three paths.** At most 3 paths per task open ([G], the same bound as `MAX_PATHS_PER_QUESTION`,
  `unfreeze.py:24`), in sorted order. The others are `kept` with the reason.
- **Kept paths.** A named manifest path that does not open is listed in the event's `kept` with one reason:
  - `a red test of this task`;
  - `the red step of this task changed it`;
  - `an ignore file`;
  - `not a Python file: a person decides`;
  - `a symlink at the red commit`;
  - `more than 3 paths named`.
  A named test file outside the manifest (a pre-existing test of another task) is not a candidate either: tests are
  red's to write. It is not listed, because the event lists only manifest paths.

### D4. What opens, and for how long

- **The green step.** `unfreeze_for` returns the human grants as today and a new `named` grant. In `run_green`, the
  green step drops the opened paths from the manifest and adds them to `keep` of `freeze_test_paths`. That is the
  existing path of a human grant (`tdd.py:1018-1019, 1033`) [V].
- **The event.** For each green attempt, before the agent step, the step writes
  `task.unfrozen{task, paths, reason: "named_by_task", source, red_sha, kept}`. The event has no `question` and no
  `answer_sha256`. A human grant keeps its event and gains `reason: "human_answer"`. When both kinds of grant exist,
  there are two events.
- **The prompt.** The green prompt gains a section `# Files this task names` with the paths. It says: "you may change
  them as the task says; keep every existing statement; do not patch the unit's code from them; every other test and
  support file stays frozen". The section is in a `<l4:data>` block (`prompt.py:227-232` is the model).
- **`templates/green.md`.** The template allows a change of a file that the prompt lists under that section.
- **Progress line.** `progress.py:223-225` prints `task 2.1 opened by its text (plan p1@…): conftest.py`.
- **Duration.** The open holds for that task's green attempts only. Every later step freezes the file again, and so
  does a fix chore. The test-path freeze and the verifier's test-path check already accept every `task.unfrozen` of
  the same unit and task (`integrity.py:390-398`) [V].

### D5. What an opened file may become

The checks run in green after the agent step and before `restore_frozen`, in `src/l4/implementer/opened.py`, on the
red version and the new version of each opened file. All three rules must hold:

1. **Statements kept.** Every top-level statement of the red version is still there, unchanged (`ast.dump`) and in
   order. New statements may come between them. This is `appended_only` (`guards.py:182-208`) without the
   "only at the end" rule and without the "definitions only" rule. An autouse fixture and an `os.environ` call are
   allowed.
2. **No rebinding.** No new statement binds a name that the red version binds, or a name that pytest reads at module
   level (`_bound`, `_MODULE_HOOKS`, `guards.py:95-112`). A shadowing fixture is the same as editing the old one.
3. **No patch of the unit's code.** No new code patches or assigns a symbol of a production module that the unit
   changed between its base and the step's work tree. These forms count:
   - `monkeypatch.setattr`, `monkeypatch.delattr`;
   - `mock.patch`, `mock.patch.object`, `patch(...)`, `mocker.patch...`;
   - `setattr(...)`;
   - an assignment to an attribute.
   The target can be a dotted string or a module object imported in the file. The production modules are the `.py`
   files of the unit's diff that are not test or support paths, as dotted names under `verifier.evidence.module_roots`
   (`file_kind` and the root rule of `tdd.py:993-999`). Patching the environment (`monkeypatch.setenv`, `os.environ`),
   clocks and modules that the unit did not change stays allowed. This is the rule of §10.2 step 1, "support files
   never replace the code under test". `src/l4/verifier/scan.py` does not build it today. Its functions are
   `result_hooks`, `plugin_module`, `coverage_refs` and `addopts_added`, and none is a patch rule [V]. This change
   builds it for opened files only.

A file that breaks a rule, or that does not parse, is put back to the red version like any frozen file. The harness
records `guard.violation{rule: "opened file", path, phase: "green", why}`, and the retry note carries `why`. A file
that green deleted, or whose path or parent directory is a symlink after the step, is put back with the same event
(`reject_symlinks` on the path's parts). The attempt then runs its gate as usual.

The verifier repeats the work:
- `check_freeze` lists each opened path as `<path> (task <k>, opened by its text, <source>)` in `unfrozen`, and the
  note counts `(+n opened by task text)`;
- `check_scan` runs rule 3 on the files that a `task.unfrozen{reason: "named_by_task"}` names. A hit is a blocker;
- the content scan of result hooks already runs on every changed support file of a task without `[test-infra]`
  (`integrity.py:479-514`) [V].

### D6. Why the guard keeps its purpose

The freeze exists so that green cannot make the red proof pass by changing the proof instead of the code. With this
design:

- **The proof stays frozen.** The red tests of the task stay frozen, and so does every support file that the task's red
  step changed. The named-file rule never opens a `kind: test` path, a path that red changed, or a path of another
  task's red.
- **Only infrastructure opens.** What opens is a file that the reviewed spec already declares as part of the
  deliverable. In the live case the behaviour under test is the default in `conftest.py`. The red test checks that
  edit, and only that edit can satisfy it.
- **The old content stays.** Rule 1 and rule 2 stop green from changing or shadowing a fixture that the red tests use.
  Rule 3 stops a new autouse fixture from replacing the unit's code. The content scan stops result hooks.
- **Nothing else changes.** The rest of the work tree is frozen as before. The verifier checks the commits again, and
  the opened file and its source are listed in `verification.md`, where the reviewer sees them.

Residual risk [I]: rule 3 is syntactic. A fixture that patches through an alias that the AST cannot resolve (`getattr`
on a computed name, `importlib` with a computed name) escapes it. The judge sees the diff, and the opened file is
listed for the reviewer. The same gap exists today for every support file that red writes.

The discrimination check of a corrected red test (`_undiscriminating`, `tdd.py:1153-1165`) does not apply to an opened
support file. In the live case the red test passes at the red commit's code with the new `conftest.py`, because that
file is the deliverable. The check would refuse exactly the edit that the task asks for. Rules 1 to 3 replace it.

L4-IMP-002 green (a) runs the red tests "and test-support files as committed in the red commit" from a scratch copy.
That copy is M1 (`tdd.py:9-10`). Task 6.1 adds "except the paths of a `task.unfrozen` of the task", so that the copy
does not undo an open when it is built.

### D7. A person's answer and support files; the true note

- **`unfrozen()`.** Today a named support file of an answer stays `kept` (`unfreeze.py:122-124`). New rule: a support
  file that a human answer names is granted, under the same conditions as a test file:
  - the Status is `answered`, or `accepted` with the question naming the file;
  - the recorded digest equals the digest of the answer;
  - the question is not a verdict question, and it holds the task;
  - at most 3 files per question.
  Ignore files stay `kept`. The person decides, so a support file that red changed may open too, and so may a file
  that is not Python. A `.py` file still gets rule 3 of D5; rules 1 and 2 apply only to an open by task text. Rule 3
  is also the SPEC's general rule for support files.
- **`unfreeze_note`.** It considers the frozen test and support files (`_frozen_tests` becomes `_frozen_paths`,
  `loop.py:126-127`) and says three things:
  - which named files an answer can unfreeze;
  - that an ignore file never unfreezes;
  - how to answer: set **Status** to `accepted` or `answered`, or run `l4 questions accept Q-NNN --unit <unit>`, then
    the push resumes the run.
  It never offers an edit that the harness would refuse. The question in the live run would have read: "To let the
  next green change `conftest.py`, set **Status** to `accepted` …".
- **The `green.md` sentence.** "a person who accepts that option unfreezes exactly that file" becomes true for support
  files. The template adds: "an ignore file (`.gitignore`) is never unfrozen".

### D8. `l4 questions` and `l4 questions show`: read only

- **Forms.**
  - `l4 questions [--unit U] [--json]` lists the open questions. `l4 questions list …` is an alias, for SPEC §2.1's
    form.
  - `l4 questions show Q-NNN --unit U [--json]` shows one question.
- **Where it reads.**
  1. It fetches the base branch and the unit refs (`fetch_unit_refs`, `src/l4/state/retry.py:145-155`). When the fetch
     fails, it reads the tracking refs that exist and prints `warning: not fetched (<error>): the questions may be
     old`.
  2. It reads `questions.md` at `refs/remotes/origin/<unit branch>`, never in the local checkout: the answer that
     matters is the one on the branch. It uses `git cat-file` and a limit of `MAX_QUESTIONS_BYTES`. A tree entry that
     is a symlink (mode `120000`) is not read: it is reported as `questions.md is a symlink on <branch>`.
- **Units.**
  - With `--unit`, the command reads the unit and each fix unit folder `<unit folder>-fix-<n>` on the same branch.
  - `--unit` also takes a fix unit's own id (`<fw>:<name>-fix-<n>`), and then reads its parent's branch.
  - With no `--unit`, it reads every unit that has a branch on `origin`.
- **List.** One line per question whose Status is `open`: `UNIT  ID  KIND  BLOCKING  TITLE`. A question with an
  unsubmitted draft (`unsubmitted_answer`) shows `draft` in place of the kind. An `unreadable_section` is one warning
  line. The last line is `Next: l4 questions show <id> --unit <unit>`, or `no open question`. Exit 0.
- **Show.** Show prints:
  - the section's fields and blocks as the file has them;
  - the effect of `accept` (the suggestion text, or `no clarifier suggestion: answer it with --text`);
  - the frozen paths that the suggestion names and whether an accepted suggestion would unfreeze each one (D7, from
    the latest `task.red_ok.frozen` of each task that the question holds, in the unit's ledger on the branch);
  - whether this caller may write it (D11);
  - `Next:` lines with the exact commands.
  For a verdict question, show prints `answer with: l4 questions answer Q-NNN --unit U --text "accept <reason>"` (or
  `reject`).
- **JSON.** The JSON uses the schema `l4/questions@1`, with the same facts.

### D9. `accept` and `answer`: the write

`l4 questions accept Q-NNN --unit U [--no-push]` and `l4 questions answer Q-NNN --unit U --text TEXT [--no-push]`
(`--text -` reads standard input, as `l4 feedback add` does):

1. **Fetch.** Fetch as in D8. `H` is the unit branch's head. `H` must exist (refusal R2 of D10).
2. **Read and check.** Read `questions.md` at `H` as in D8. Parse it and check the refusals of D10.
3. **Edit.** Edit only spans of the question, as the harness's own writers do (L4-QMD-003):
   - `answer` writes the `### Answer` body with a new `QuestionsFile.set_answer(qid, text)`. The new body is the
     existing comment line `<!-- write below this line -->` (kept when it is there), then the text, then one line end.
     When the section has no `### Answer` block, the method adds one at the end of the section. Then `set_status(qid,
     ANSWERED)`.
   - `accept` only does `set_status(qid, ACCEPTED)`.
   - `set_status` also rewrites that question's index row (`questions.py:456-461`). The run would otherwise rewrite
     that row in a commit of its own (`refresh_index`). No other byte changes. The file's line endings and BOM are
     kept.
4. **Round trip.** Parse the new bytes:
   - the question's Status must be the new one;
   - for `answer`, `answer_text` must equal the given text, stripped;
   - every other question must have the same id, Status, blocking tasks and effective answer as before;
   - the parse must have no new issue.
   Otherwise the command refuses (R10). This is the check that "the same parser and rules" hold.
5. **Commit.** Make one commit with git plumbing, as `yolo/worktree.py:28-58` does: a private index file in the
   harness cache (`GIT_INDEX_FILE`), `read-tree H`, `update-index --cacheinfo <mode of the old entry>,<new
   blob>,<path>`, `write-tree`, `commit-tree -p H`. No branch is checked out and no work tree is touched, so a branch
   that the operator has checked out is not disturbed. Author and committer are git's own identity of the operator.
   The message:
   ```
   answer Q-002 (<unit name>): <question title, at most 60 characters>

   Status: answered
   By: <git author name> (person)          # or (agent: CLAUDECODE)
   Via: l4 questions
   ```
   For `accept`, the subject starts with `accept` and the Status line is `accepted`. The message has no `L4-` trailer
   and no `[skip ci]`, so the push starts CI on both forges (section 1.3). The commit is a person's commit under the
   author rule (`src/l4/vcs/authorship.py:28-32`).
6. **Push.** Push `<commit>:refs/heads/<branch>` to `origin` without force. The push uses the auth of
   `push_auth_config`, which is the person's own credentials outside CI.
   - A push that is rejected as not a fast-forward is refusal R12. Nothing changes.
   - Any other push failure exits 1 with `explain_push_failure`'s text.
   - On success, the tracking ref moves to the commit and the command prints
     `pushed <sha10> to <branch>: the push starts a run`, `Next: l4 status --unit <unit>`. When the operator has the
     branch checked out, it also prints `your checkout of <branch> is behind: git pull`.
7. **No ledger write.** The command writes no ledger event. The run that the push starts records
   `question.answered{by: human}` as it does for a hand edit (section 1.3). An unfreeze then follows from that record
   as today.

**`--no-push`.** The command does steps 1 to 4, then prints a unified diff of `questions.md` (3 lines of context) and
the commit message, then `nothing written (--no-push)`. It exits 0, and it makes no commit object, no ref change and no
file change. "Dry" is the word of the request. A local edit, as `l4 feedback add` does it, would need the unit branch
checked out, and it could not be checked against the fetched head that the push would use.

### D10. Refusals

Every refusal exits 2, writes and pushes nothing, and prints two lines: `questions: <cause>` and `Fix: <what clears
it>`.

| | Cause | Fix |
|---|---|---|
| R1 | `no unit <U>` (the providers do not detect it) | `l4 status lists the units` |
| R2 | `<U> has no branch on origin: no question was asked yet` | `the next run creates it` |
| R3 | `<U> has no questions.md on <branch>` or `no Q-NNN in <path>` (or its section is unreadable) | `l4 questions --unit <U>` |
| R4 | `Q-NNN is <status>` (answered, accepted, answered-by-clarifier, dismissed) | `to change an answer, edit its section on <branch> by hand; an answer a run already used becomes a fix unit "apply clarification Q-NNN" (L4-QMD-006)` |
| R4b | `Q-NNN is superseded by Q-MMM` | `answer Q-MMM: l4 questions show Q-MMM --unit <U>` |
| R5 | `Q-NNN has a draft answer under Status open` | `submit it on <branch> (set Status to answered) or remove it, then run the command again` |
| R6 | `<U> does not wait for an answer: it is <phase>` (`merged`, `archived`, `abandoned`), or `a run is working on <U> (run <id>)` | for a finished unit `an answer changes nothing`; for a live run `try again when it ends: l4 ci watch` |
| R7 | `Q-NNN has no clarifier suggestion to accept` | `l4 questions answer Q-NNN --unit <U> --text TEXT` |
| R8 | `Q-NNN is a verdict question: accept is not an answer to it` | `l4 questions answer Q-NNN --unit <U> --text "accept <reason>"` (or `reject`) |
| R9 | `a verdict answer starts with accept or reject` (`_DECISION` does not match) | the same command with the first word fixed |
| R10 | the text is empty, longer than 20,000 characters [G], has a line that the file reads as structure (a heading, `---`, a table row, a field line such as `- **Status:**`, a code fence), holds an HTML comment, holds a value that the redactor changes (`a secret-like value (<kind>)`), or fails the round trip | `remove or indent line <n>` / `remove the secret; rotate it if it was real` / the round-trip difference |
| R11 | the agent rule (D11) | `a person runs the command, or set clarifier.answer_by_agents: true in .l4/config.yaml on <base> (a pushed change a person can see)` |
| R12 | `<branch> moved since the fetch (now <sha10>)` | `run the command again: it fetches first` |
| R13 | `questions.md is a symlink on <branch>`, or larger than 2 MiB | `fix the file on <branch> by hand` |

**R6 and open questions.** A question may be open while the unit runs other tasks (SCN-IMP-23). So "does not wait"
means one of two things: the unit is finished, or a run is live now. A run is live when the lock ref's pending ledger
has a `run.started` with no `run.finished`, the rule of `l4 restart`
(`src/l4/state/restart.py:259-268`) [V]. In every other phase the answer is taken by the next run. The usual case is
`awaiting_human`, or `fixing` with the fix unit's questions open.

### D11. Agents

- **Who is an agent.** The command uses the actor rule of `l4 yolo accept` (`src/l4/yolo/accept.py:20-41`): one of
  the markers `CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT`, `AI_AGENT`, `CODEX_SANDBOX`, `L4_RESULT_PATH` makes the caller
  an agent, and so does a standard input that is not a terminal. The function moves to `src/l4/actor.py`, and both
  commands import it.
- **What an agent may write without the key.** An agent may run `accept` or `answer` when all of these hold:
  - the question's kind is in `clarifier.auto_accept_kinds` (default `[technical]`);
  - the kind is not `verdict`;
  - the effective answer (the text for `answer`, the suggestion for `accept`) names no path, by `names_path`, of the
    latest `task.red_ok.frozen` of any task that the question holds.
- **The key.** Any other write by an agent needs `clarifier.answer_by_agents: true`. Both keys are read from
  `.l4/config.yaml` on `refs/remotes/origin/<base>`, with the loader as `target_config` does it
  (`accept.py:44-62`). An agent cannot set them on the unit branch.
- **Why this split.**
  - The clarifier is already an agent that answers the kinds of `auto_accept_kinds` on its own
    (`src/l4/config/schema.py:510-513`). An operator agent that answers the same kinds adds no new trust.
  - A product or ambiguous question was routed to a person on purpose.
  - A verdict answer is a human verdict (L4-VER-013): an `accept` waives a criterion, a finding or a hold.
  - An answer that names a frozen path unfreezes it for green (D7). That weakens the anti-reward-hacking guard, the
    same kind of decision as `yolo.review.accept_by_agents` guards. The key is in `clarifier`, beside
    `auto_accept_kinds`, because both say who may answer a question. `yolo.review.*` is about plan reviews.
- **The limit.** The harness cannot know who types a command, and an agent with push rights can still edit the file by
  hand (D7.2 of review-resolution). The rule keeps honest agents from deciding for a person. It is not a security
  boundary. The skill changes with it: `operate.md` tells an agent to give a question outside the rule to a person,
  unless the key is set. It no longer teaches the hand edit for those questions (task 5.2).
- **Record.** The commit body names the actor (`person`, or `agent: <marker>`). The ledger keeps `by: human`, because
  the file has no field for the actor. Recording the actor in the ledger is not in this change.

### D12. Help text, SPEC, runbook, skill

- `l4 --help`: `questions` reads "List and show open questions; accept or answer one on the unit branch (commits and
  pushes)". `OWNING_CHANGE["questions"]` becomes `unfreeze-and-answer`.
- SPEC §2.1 row 424 gains the forms and "commits and pushes to the unit branch; `--no-push` shows the change".
- Runbook:
  - 7.1 puts the command first and keeps the hand edit as the other way;
  - the NOTE at line 614 is removed;
  - 10.4 gains the row;
  - line 1283 no longer lists `l4 questions`;
  - 10.5 says that a person can also use `l4 questions` for `questions.md`;
  - 11 states the agent rule.
- Skill `operate.md`: the command, the agent rule, and when to relay a question to a person. Skill `spec.md`: a task
  that must change a test-support file names it exactly (`conftest.py`, not "the conftest"). Only a Python support
  file that red does not change opens, and only for that task's green.

## 3. Failure cases of the named-file rule

| Case | Result |
|---|---|
| The task names `tests/test_otel.py`, a red test of this task | stays frozen, `kept: a red test of this task` |
| The task names `tests/conftest.py`, which red changed | stays frozen, `kept: the red step of this task changed it` |
| The task says "the conftest" or `**/conftest.py` | nothing named, nothing opens |
| The task names `conftest.py`; the repository has `tests/conftest.py` only | nothing named (`conftest.py` is not that path) |
| The task names `../other/conftest.py` or `/etc/conftest.py` | not a manifest path, nothing opens |
| The task names `../conftest.py`, and the repository has a root `conftest.py` | nothing named (the `./` of `../` does not start a token) |
| `conftest.py` is a symlink at the red commit | stays frozen, `kept: a symlink at the red commit` |
| Green replaces the opened file, or its directory, with a symlink | put back, `guard.violation{rule: "opened file", why: "a symlink"}` |
| The task names `.gitignore` or `tests/fixtures/data.json` | stays frozen (`an ignore file`, `not a Python file: a person decides`) |
| Neither source holds: no active plan's digest is carried, and the task text differs from the base branch | nothing opens; green as today |
| A fix unit's task names `conftest.py` | nothing opens (harness-written text) |
| Green rewrites a fixture of the opened file, or adds `monkeypatch.setattr("pkg.mod.fn", …)` for a module the unit changed | file put back, `guard.violation{rule: "opened file", why}`, retry note |
| Green adds `os.environ.setdefault(...)` and a new autouse fixture that sets an env var | kept |

## 4. Risks

- **The task text is prose.** A spec author who names `conftest.py` for a reason that is not an edit opens it. Rules 1
  to 3 limit what green can do there, and the skill teaches to name a file only for an edit [I].
- **Python only.** The open is limited to `.py` support files, because the harness can check them. A JavaScript
  `test-setup.ts` that a task names stays frozen and still needs a person (D7).
- **The agent rule is a speed bump** (D11).
- **R6 and the live-run check** read the lock ref's pending ledger. A stale `run.started` of a dead runner blocks the
  command, as it blocks `l4 restart` today. The fix is the same.

## 5. Not verified

- The GitHub push trigger for a commit that an operator pushes with a GitHub App token in `forge.token_env` [I: the
  template triggers on every push to the prefix; GitHub's "no workflow from `GITHUB_TOKEN` pushes" rule does not
  apply to an App or a PAT token].
- Which step raised the live run's question. A question with the frozen list comes only from `_raise_blocked`: a green
  attempt that reports `blocked`, or a frozen test that hangs (`loop.py:219-228`). When `max_task_attempts` (default
  3, `config/schema.py:504`) runs out, the breaker halts the unit without a question (`loop.py:236-241`). So the live
  question was most likely the third green attempt, which reported `blocked` [I]. The note fix of D7 covers both
  `_raise_blocked` paths.
- `task_text` on a Kiro task with sub-bullets that are task lines without a checkbox: the rule stops at the next task
  line or heading, as `_links_below` does [I].
