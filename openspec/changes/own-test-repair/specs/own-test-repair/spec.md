## Purpose

A unit's own new test that fails for a reason other than its checks gets a narrow repair step whose edit a person
accepts, so no fix step bends product code to a broken test, and a plan that waits on the person has the edit and its
evidence ready.

## ADDED Requirements

### Requirement: L4-IMP-091 A repair step proposes an edit of the failing tests only, and only a person's accept applies it
A candidate is a failing test of a round that (all of): sits in a file that matches `tdd.test_globs` and no
`tdd.test_support_globs` glob, is a Python file, is bound once in it, was first added by a harness commit that carries
`L4-TDD: red` of this unit (absent at the unit's base, `unit_base`, which for a fix unit is its parent's) and has not
been changed by a person's commit since (its facts and what it uses in the file, `tamper.facts_of`, are as the red
commit left them; a file taken out and added again is no candidate), failed with a kind other than `assertion` or
`not_implemented` (the round's `failures`), and was raised by the test itself: the round records every repository file
the traceback passes through (`frames`) and the deepest (`location`), and ALL of them SHALL match `tdd.test_globs` or
`tdd.test_support_globs`, so a production file anywhere in the traceback disqualifies it. A record that lacks them, or
whose traceback has a frame with an absolute path that is no library, is no candidate. No production file the unit
added or changed may mention `__tracebackhide__`. A browser test's message SHALL be a usage error (`TypeError`,
`ValueError`, `AttributeError`, `NameError`, "must be a ...", "unexpected keyword argument"); a timeout, a locator that
matched nothing or too much, or a failed connection is no candidate.
A finding SHALL become a `repair` chore only when every test id it fails on is a candidate; otherwise it stays a plain
fix chore. The task SHALL name each test, its kind and the first line of its message, carry the excerpt of the gate log
of the finding, and say that the test may be right and the code wrong. The step SHALL derive the candidates again from
git and the stored round; the marker is never the proof.

The repair step SHALL keep an edit only when the structural rules of a repair hold (the rules of the first design,
unchanged: every changed file is a candidate's file and UTF-8 before and after; the facts of every other name and the
module's statements that bind no name are equal; imports only added, in place, from `re`, `json`, `datetime`, `math`,
`decimal` or `fractions`, binding no name the file or the builtins bind; each repaired test keeps its decorators, its
signature and its number of top-level statements, at most 3 replaced in place with no new `try`, `if`, loop, `with` or
`match`; no check removed or moved into a nested scope or below `and`/`or`, a conditional expression or `:=`; a
replaced statement loads only the names the vocabulary rule allows and none of `os`, `sys`, `pathlib`, `open`,
`inspect`, `functools`, `operator`, `importlib`, `builtins`, `object`, `type`, `getattr`, `setattr`, `delattr`,
`globals`, `vars`, `environ`, `getenv` or a dunder, under any alias; in an `async def` a check counts only when awaited;
no `return`, `yield`, always-true `assert`, constant `and`/`or` operand, skip, `xfail`, `importorskip`, `SkipTest`,
`exit`, write outside its locals, `global`, `nonlocal`, `globals`, `vars`, `setattr`, `delattr`, `__import__`, `exec`,
`eval`, `compile` or `importlib`), the repaired tests pass in the gate they failed in under the test gate's
no-regression rule, and each is proved again (a unit-gate test fails by an assertion when the project's functions
answer their zero value; an e2e test fails by an assertion against the unit base's production code, built). A change
to any other file SHALL be put back and fail the attempt: product code is frozen in a repair. These rules are a filter
that keeps bad proposals from a person, not the boundary (design D1).

A step that passes them SHALL NOT be committed. Its edit SHALL be saved as a held step (L4-IMP-065: the patch and the
result under `<unit>/.l4/held/`, their digests in the raise) and the work tree put back, and one question of kind
`harness` with check `repair` SHALL block the task, with no attempt counted. The question SHALL show each repaired
test (id, kind and first line of the failure, the gate), the gate run that passed them, how each was proved, that the
structural rules held, the changed paths and the diff of each file, and offer `accept: apply this edit` and
`retry: <note>`. Its raise SHALL record `repair_blobs` (each changed path -> its blob before and after, from a
temporary index of the step base with the patch applied). A patch whose expected state cannot be computed, or that
changes a path outside the repaired tests' files or a link, SHALL NOT be offered: the attempt fails. Nor SHALL a patch
whose repaired files' text, before or after it, changes under the question's redaction or holds a character a view
does not show as it is (a C0 or C1 control other than tab, newline and a carriage return before a newline; U+2028,
U+2029; a bidirectional control; a zero-width character or U+FEFF). The agent-field shape of the redactor SHALL NOT
cross a line end, and a test's source view SHALL show the lines Python counts of the function its id names, inside the
class the id names.

An `accept` of a `repair` question SHALL count only when its `question.answered` record has `by: human`; an answer by
an agent (`clarifier.answer_by_agents`) or by the delegate never applies a repair. The delegate SHALL escalate such a
question without a model call ("a repair of a test is a person's decision"), and `l4 questions accept|answer` by an
agent SHALL refuse it, whatever `clarifier.answer_by_agents` says. A recorded accept that does not count SHALL replay
nothing and be recorded once (`held.accept_ignored`); the step runs again as an agent's and its proposal is held by a
question of its own. A person's accept SHALL make the next run replay the saved edit (no agent; the digests and the
stale rule of L4-IMP-065) and run the same checks on it again. Before the commit the replay SHALL compare the changed
test files with the raise's `repair_blobs` (the same paths; each one's blob at the step base and in the work tree are
the recorded pair); a difference fails the attempt. On pass the commit SHALL carry `L4-TDD: exempt` and the ledger
`task.repaired{task, base, files, tests, ids, proved, sha10, question, patch_sha256}`, staged with no line-ending
conversion and with no `notes_for_verifier` or `suppressions` of the saved result, where `proved` maps each test id
to how it was proved and `sha10` ties the proof to the content of its file. A replay that fails a check fails the
attempt and uses the accept up. `retry` drops the saved step and the next step is an agent's, with the note. When the
attempts are used up the task SHALL escalate as a fix chore does, with a note that the test may be right and the
product code wrong.

#### Scenario: SCN-IMP-453 (+) A repair of a broken assertion call is proposed, not committed
- **GIVEN** the unit's own `e2e/test_a.py::test_x` (added by its red commit) fails in the e2e gate with kind `other`
  ("value must be a string or regular expression")
- **WHEN** the repair step replaces `expect(page).to_have_url(lambda url: …)` with `page.wait_for_url(lambda url: …)` and
  the e2e gate then passes `test_x` and the base-code proof holds
- **THEN** nothing is committed: the edit is saved under `.l4/held/`, the work tree is as before the step, one harness
  question of check `repair` blocks the task and shows the diff, the gate run and the proof, its raise records
  `patch_sha256` and `repair_blobs`, and no attempt is counted

#### Scenario: SCN-IMP-454 (−) Another test of the file is not touched
- **WHEN** the step also changes `test_y` of the same file, a helper or fixture `test_x` uses, or adds a module-level call
- **THEN** the change is put back and the attempt fails naming what changed; no question is raised

#### Scenario: SCN-IMP-455 (−) No check may go
- **WHEN** the step removes an `assert` of `test_x`, deletes a statement, wraps statements in a new `try`, changes its
  fixtures, or adds `pytest.skip`, `pytest.mark.xfail` or `importorskip`
- **THEN** the attempt fails naming the rule; no question is raised

#### Scenario: SCN-IMP-456 (−) Product code is frozen in a repair
- **WHEN** the step changes `src/app/page.tsx` as well
- **THEN** the product change is put back and the attempt fails

#### Scenario: SCN-IMP-457 (−) A repaired test must pass where it failed
- **WHEN** after the step `test_x` still fails in the e2e gate
- **THEN** the attempt fails naming `test_x`, no question is raised; after the last attempt the task escalates with the
  note that the test may be right and the code wrong

#### Scenario: SCN-IMP-458 (+) An assertion failure, a pre-existing test or a person's test is no repair
- **WHEN** the unit's own test fails by assertion, or a test that existed at the unit's base fails with any kind, or the
  failing test was first added by a person's commit on the unit branch
- **THEN** the fix unit makes a plain fix chore, as before

#### Scenario: SCN-IMP-459 (+) A non-Python test or a mixed finding is no repair
- **WHEN** the unit's own failing test with kind `other` is a TypeScript test, or the gate finding fails on one candidate
  and one pre-existing test
- **THEN** no repair chore is made; the fix chore and its escalation are as before

#### Scenario: SCN-IMP-460 (+) An added import is allowed
- **WHEN** the repair adds `import re` and uses `re.compile(...)` in one replaced statement of `test_x`
- **THEN** the edit passes the structural rules and is proposed

#### Scenario: SCN-IMP-462 (−) A vacuous repair is refused
- **WHEN** the step turns `assert x == 4` into `assert x == 4 or 1 == 1`, `assert x == ANY`, an early `return`, or a
  call that no longer reaches the product
- **THEN** the attempt fails, naming the rule or, for a test that passes without the product, "the repaired test no
  longer tells a working product from a broken one"

#### Scenario: SCN-IMP-463 (−) Code hidden by an encoding cookie is refused
- **WHEN** the file starts with `# coding: utf-7` before or after the step
- **THEN** the attempt fails naming the encoding

#### Scenario: SCN-IMP-464 (−) A failure raised by product code is no repair
- **WHEN** a unit's own test fails with kind `other` and the deepest repository frame of its traceback is
  `src/app/x.py`, or the traceback is not recorded
- **THEN** no repair chore is made

#### Scenario: SCN-IMP-465 (−) A test a person changed is no repair
- **WHEN** a person's commit on the unit branch changed the failing test, or what it uses in its file, after the red
  commit, or deleted the file and added it again
- **THEN** no repair chore is made

#### Scenario: SCN-IMP-466 (+) A repaired test keeps no old proof and gets its own
- **WHEN** an accepted repair is committed with `proved` and `sha10`
- **THEN** the verifier counts the test as proved by the repair while its file has that content, and by nothing when the
  file changed after it

#### Scenario: SCN-IMP-467 (−) A repaired test cannot tell the proof runs from the real gate or reach other tests
- **WHEN** a replaced statement reads `os.environ` or `os.path.exists`, `sys.modules`, `getattr(m, "__setattr__")`,
  `functools.partial(setattr, m)`, `m.__dict__`, `f.__globals__`, `__builtins__`, an alias of any of them, or a name the
  test never used and the module does not bind once, or sets an attribute of a name that only a comprehension binds
- **THEN** the attempt fails naming `vocabulary` or `side-effect`

#### Scenario: SCN-IMP-468 (−) A dropped await is a removed check
- **WHEN** the step turns `await expect(x).to_have_text("a")` into `expect(x).to_have_text("a")` in an `async def`
- **THEN** the attempt fails naming `check-dropped`

#### Scenario: SCN-IMP-469 (−) The location of a failure cannot be faked
- **WHEN** a unit's own test fails with kind `other` and its traceback passes through `src/app/x.py` before ending in the
  test file, or a production file of the unit mentions `__tracebackhide__`, or a browser test fails with a timeout or
  with a locator that matched nothing
- **THEN** no repair chore is made

#### Scenario: SCN-IMP-470 (−) A unit test that fails only against the base code is not proved
- **WHEN** a repaired unit test passes when the project's functions answer their zero values and fails against the unit
  base's production code
- **THEN** the attempt fails with "the repaired test no longer tells a working product from a broken one"

#### Scenario: SCN-IMP-471 (+) A person's accept applies exactly the saved edit
- **GIVEN** the question of SCN-IMP-453
- **WHEN** a person answers `accept: apply this edit` and the next run reaches the task
- **THEN** no agent runs: the saved patch is applied (`held.replayed` with its `patch_sha256`), the structural rules,
  the e2e gate and the proof run again and hold, and the commit carries `L4-TDD: exempt` and `task.repaired` with the
  question and the patch digest; the task is done

#### Scenario: SCN-IMP-472 (−) The delegate does not accept a repair
- **GIVEN** the question of SCN-IMP-453 and a delegate whose kinds include `harness`
- **WHEN** the delegate runs
- **THEN** it escalates the question without a model call, with the reason "a repair of a test is a person's decision"

#### Scenario: SCN-IMP-473 (−) An agent's accept never applies a repair
- **GIVEN** the question of SCN-IMP-453 and `clarifier.answer_by_agents: true` on the base branch
- **WHEN** an agent runs `l4 questions accept` on it, or a `question.answered{by: agent}` or `{by: delegate}` of an
  `accept` is on record
- **THEN** the CLI refuses the agent ("a repair of a test is a person's decision"); for a recorded accept the run
  replays nothing, records `held.accept_ignored{question, task, check: repair, by}` once and commits nothing, and the
  next repair step is an agent's whose proposal is held by a new question that only a person's accept applies

#### Scenario: SCN-IMP-474 (+) Retry asks the agent again
- **WHEN** a person answers `retry: keep the lambda, use wait_for_url` on the question of SCN-IMP-453
- **THEN** the saved step is dropped and the next repair step is an agent's, with the note in its prompt

#### Scenario: SCN-IMP-475 (−) A replay that fails its checks is not committed
- **GIVEN** an accepted repair question
- **WHEN** the replayed edit no longer passes the gate (or a structural rule, or its proof)
- **THEN** the attempt fails naming the check, nothing is committed, the accept is used up and the next attempt is an
  agent's

#### Scenario: SCN-IMP-476 (−) A repair of an earlier attempt is not replayed
- **WHEN** the unit was restarted, or the task reopened, after the repair question was raised, and the question was
  accepted
- **THEN** the saved step is dropped and nothing is replayed (an open question is `superseded by restart`)

#### Scenario: SCN-IMP-477 (−) A proposal that cannot be shown exactly is not offered
- **WHEN** the step's saved patch changes a path outside the repaired tests' files, adds a link, or its expected state
  cannot be computed
- **THEN** no question is raised and the attempt fails with "the repair could not be saved for a person to review"

#### Scenario: SCN-IMP-478 (−) A repaired file that changed since the accept is not committed
- **GIVEN** a person accepted the repair question of `e2e/test_a.py` with `repair_blobs` `[b0, b1]`
- **WHEN** another commit changed `e2e/test_a.py` before the replay, so that the saved patch still applies but the file
  at the step base is not `b0` or the replayed file is not `b1`
- **THEN** the attempt fails with "a repaired file changed since a person accepted the edit", nothing is committed and
  the accept is used up


#### Scenario: SCN-IMP-479 (−) A proposal the question would not show as it is is not offered
- **WHEN** the repaired test's new lines hold a comment with `"signature": "` and a later line a double quote, or a
  value of a configured secret, or a form feed, a lone carriage return, U+2028, U+202E or U+200B
- **THEN** no question is raised and the attempt fails with "the repair could not be saved for a person to review",
  naming the file; and a failure line or any other text with an agent-field opener hides no later line of a question

#### Scenario: SCN-IMP-480 (+) The source view shows the method the id names
- **GIVEN** a file with `TestA.test_x` and `TestB.test_x`, and a module comment holding two form feeds
- **WHEN** the question of a repair of `TestB::test_x` is built
- **THEN** its source view shows all of `TestB.test_x`, from its first line to its last

#### Scenario: SCN-IMP-481 (+) The commit is the accepted blob whatever the line-ending settings
- **GIVEN** `core.autocrlf=input` in the repository and a repaired test file with CRLF line ends
- **WHEN** a person's accept is replayed
- **THEN** the committed blob is the recorded `after` and the verifier accepts the commit

#### Scenario: SCN-IMP-482 (−) The agent's notes do not travel with a repair
- **GIVEN** a saved repair result with `notes_for_verifier` and `suppressions`
- **WHEN** a person's accept is replayed and committed
- **THEN** the task's done record and the next round's judge carry neither

### Requirement: L4-VER-073 The verifier accepts only the edit a person accepted, re-checks it, and the judge sees it
`check_test_paths` and the check that red's tests are unchanged after red SHALL accept, for an `L4-TDD: exempt` commit,
the files a `task.repaired` of the same unit and task names, and nothing else, and only when, per file: the event names
a `question` and a `patch_sha256`; the unit's ledger has a `question.raised{kind: harness, check: repair}` of that
question and task with the same `patch_sha256` and `repair_blobs` naming the file; a `question.answered` of it with
`by: human` follows the raise; a `held.replayed` of it with the same `patch_sha256` follows that answer; and the
commit's parent blob and
blob of the file are the `repair_blobs` pair. A file that fails any of these SHALL be a blocker "a repaired test differs
from the edit a person accepted" that names the file, the task, the commit and the first condition that failed. For each
accepted file the structural rules of a repair (the encoding rule included) SHALL run again on the file before and after
the commit, with the tests the event names; a file that breaks them, was added or deleted by the commit, or is named
with no test, is a blocker. A test a `task.repaired` lists SHALL keep no red proof by its id: its proof is the one the
event records (`proved`), valid only while the file still has the content `sha10` names. The judge's material for the
next round SHALL show each repaired test's lines before and after the repair (as for a named test that red changed,
L4-VER-068).

#### Scenario: SCN-VER-278 (−) A repair commit that also changed another test is a blocker
- **GIVEN** an exempt commit of a repair task whose `task.repaired` names `e2e/test_a.py`
- **WHEN** the commit also changed `e2e/test_b.py`
- **THEN** `check_test_paths` reports `e2e/test_b.py`; `e2e/test_a.py` is accepted

#### Scenario: SCN-VER-279 (+) The judge sees the repair
- **WHEN** the next round's judge runs
- **THEN** its prompt has the repaired test's lines before and after the repair, as bounded data

#### Scenario: SCN-VER-280 (−) A repair commit that breaks the rules is a blocker
- **GIVEN** an exempt commit whose `task.repaired` names `e2e/test_a.py`
- **WHEN** the commit removed an assert of the repaired test, declared another encoding, or added another test
- **THEN** `check_test_paths` reports a blocker naming the file and the rule

#### Scenario: SCN-VER-281 (−) A commit that differs from the accepted edit is a blocker
- **GIVEN** a person accepted the repair question of `e2e/test_a.py` with `repair_blobs` `[b0, b1]`
- **WHEN** the exempt commit's blob of `e2e/test_a.py` is not `b1`, or its parent's is not `b0`, or `held.replayed`
  names another `patch_sha256`, or the only `held.replayed` of the question comes before the person's answer
- **THEN** `check_test_paths` reports "a repaired test differs from the edit a person accepted" naming the file and the
  condition

#### Scenario: SCN-VER-282 (−) A repair no person accepted is a blocker
- **WHEN** the `task.repaired` names no question, or its question's only `accept` is `by: agent` or `by: delegate`, or
  the raise of its question is not of check `repair`
- **THEN** `check_test_paths` reports the same blocker, naming the condition

## MODIFIED Requirements

### Requirement: ci-evidence D11 (amendment, the one exception)
A fix chore SHALL NOT change a test file, with one exception: a `repair` chore (L4-IMP-091) may commit the definitions of
the unit's own new failing tests as a person accepted them, under the structural check, and nothing else.

#### Scenario: SCN-IMP-461 (+) A plain fix chore still may not change tests
- **WHEN** a plain fix chore (kind `fix`) edits the same test
- **THEN** the edit is put back as before
