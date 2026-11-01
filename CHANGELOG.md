# Changelog

All releases of the L4 harness. Consumers pin a release tag `vX.Y.Z` (or the moving major tag `v0`). The source of a
release is the tag `src-vX.Y.Z` on `amaster`; the release commit on branch `release` holds only the shipped paths.

The harness is before 1.0. Each entry says what was added, what changed in behaviour and what was fixed, so a
consumer can decide when to move its pin (`l4 upgrade --harness-ref vX.Y.Z`).

## Unreleased

### Added
- `delegate.batch_size` (default 5; 1 asks one question per call as before): the verdict questions of one round that have the same askers are asked in one delegate call, up to that many. A consumer's unit spent $43.83 of its $50 delegate cap on 30 verdict questions of one round, about $1.46 each, and escalated the other 21 on the cap; every call paid again for the same rules, specification and reading of the same head. Now the shared material is sent once (`delegate-batch@1`) and the reply holds one result per question (`l4/delegate-batch@1`); each result is checked against its own question and citations, and answered, deferred or escalated on its own (L4-DLG-028).

### Changed
- A batch of N questions needs N answers' cost left in the unit's cap and the plan's share, and Claude Code's budget for the call is N times `delegate.max_cost_usd_per_answer`, so no batch may spend more than its questions could one by one; its cost is recorded once, with a share on each question's result. A batch call that reports no cost counts at N answers' cost; one that hit a usage limit and reported no cost counts once, at one answer's cost, and the next profile is asked a batch shortened to the money then left (L4-DLG-009, L4-DLG-028).
- A batch call that times out, fails or returns a reply that is not a batch document costs each of its questions an attempt, and each is then asked alone; a missing or doubled result is that question's failed attempt. `delegate.max_questions_per_run` still counts questions, and `delegate.pass` records `calls` (L4-DLG-003, L4-DLG-028).

## 0.4.52 (2026-11-01)

### Fixed
- A unit no longer waits a day for capacity because one judge's credits ran out while the others only timed out. When nothing in a required chain was usable, the wait was the earliest end of a cool-down, and a hello that timed out records none: a consumer's unit parked for 24 hours during an outage of about 25 minutes, though its free judges answered again ten minutes later. Now a skip of the `transient` class (a probe step or hello that timed out, an unreachable provider) bounds the wait to `availability.default_cooldown` (30 m), or to a cool-down that ends sooner (L4-AVL-013).

### Changed
- A chain whose only failures are transient waits `availability.default_cooldown` before the next run probes it, in place of being due at once. Two such parks in a row no longer stop the plan with `capacity_needs_fix` and advice to renew a secret; the plan waits and probes again at the next trigger after the wait. A failed login, a refused or wrong hello and a missing binary keep the old rule (L4-AVL-013, L4-YOLO-035).

## 0.4.51 (2026-11-01)

### Fixed
- A judge's reply that lists more than three riskiest assumptions is kept. Before, the schema's limit of three discarded the whole reply after the repair prompt got the same list back; a consumer's round lost its judge on part 1 of 2 this way and all 25 criteria became verdict questions, though the field changes no verdict. Now the deterministic repair keeps the first two items and joins the rest, by newlines, into the third, so no text is lost; the reply counts as `repaired` with one call. A list with an item that is not text, a short list and every list of objects are left as they are (L4-VER-074).
- A judge whose reply still breaks the schema after the repair and the retry gives way to the next independent judge, as the failure precedence table already said. Before, the round was held at the first judge: the other parts of a diff were not asked, and neither was any other judge of the chain. Now the next independent judge is asked the same prompt (a part's, or the whole prompt of a split one), and the discarded judge is skipped for the rest of the round without a cool-down. When no independent judge is left, the round holds the discarded reply as before and its criteria are asked of a person; the unit does not wait for capacity. A follow-up keeps its rule, and a timeout left after the splits still holds the round, which L4-VER-015 now says (L4-VER-075).

## 0.4.50 (2026-10-31)

### Added
- A unit's own new test that fails with an error of its own is repaired by an edit that a person accepts. Before, such a unit's fix chore could not touch the test (a fix chore may not change one), so its attempts changed correct product code to suit the broken test or ran out and escalated; a consumer's unit had a new browser test that raised an error before any check. Now a failing test of a round becomes a candidate only when this unit's red commit added it, no person's commit changed it, it failed with an error other than an assertion or a missing implementation, and every repository file of its traceback is a test file; a finding whose every failing test is a candidate gets a `repair` chore. The step may change those tests' definitions and add a few imports, under structural rules (no check removed, no skip, no other test, helper or product file), and the repaired tests must pass in the gate they failed in and be proved again. A step that passes is not committed: it is saved as a held step and one harness question of check `repair` blocks the task (no attempt is counted) with the diff of every file, the gate run, how each test was proved and the options `accept: apply this edit` and `retry: <note>`. Only a person's `accept` applies it: an answer by an agent (`clarifier.answer_by_agents`) or by the delegate never does (the delegate escalates the question without a call, `l4 questions` refuses an agent, and a recorded accept of another actor is ignored once as `held.accept_ignored`). The next run replays exactly the saved edit with no agent, runs every check on it again, compares the changed files with the blobs recorded in the question (another commit that changed the file since fails the attempt and uses the accept up) and commits it with `L4-TDD: exempt` and `task.repaired{question, patch_sha256}`. The verifier accepts a repaired test only as the edit a person accepted (the raise with the blobs, a person's answer, the replay after it with the same digest, the commit's two blobs) and the judge sees the test before and after (L4-IMP-091, L4-VER-073).

### Changed
- The agent-field redaction (`"signature": "` and the like) no longer crosses a line end, in every question and in the judge's prompt: a source comment that opened the shape used to hide the lines up to the next double quote. A repair question shows what the accept applies: a proposal whose files hold text the question would redact, or a character a view does not show as it is (named by Unicode class: controls, format characters such as a soft hyphen, variation selectors, tag characters, fillers and every space but U+0020), or whose question would show a redaction mark, is not offered; every line of a held question spells such characters as escapes, so a lone carriage return cannot move the rest of a line out of its code block; a held step is committed byte for byte whatever `core.autocrlf` says, so its digest holds after a fresh checkout; and a repair keeps the suppressions its result declares (the question shows each) so that an accepted `# noqa` is not reported as undeclared (L4-IMP-091).

## 0.4.49 (2026-10-31)

### Fixed
- A step-9 judge call that times out is split like one whose reply stopped at its output limit. Before, a part whose call ran out of `verifier.judge_timeout_s` was retried once with the same prompt, and a second timeout discarded the reply and held the round; a consumer's round lost its judge this way after two timeouts of 600 s on a part the same judge had answered in an earlier round. Now a prompt of two or more criteria that can still be split is not retried: the same judge is asked for each half of its criteria, at most `verifier.judge_length_splits` halvings, and only a batch that cannot be split again keeps the one retry and holds the round on its timeout. `judge.length_split` names its `cause` (`length` or `timeout`). A part whose every call times out costs at most 4 timeouts with the default, where it cost 2 (L4-VER-071).
- A round whose judge gave no verdict keeps the earlier judge's pass of each criterion that nothing it rests on changed. Before, every criterion of such a round became a verdict question ("the judge gave no verdict for this criterion"); a consumer's round asked all 29 again after a fix unit had added only one test file, though an earlier round had passed them on the same production code. Now, when step 9 ran and failed, a criterion takes the `pass` of the newest earlier round with a judge verdict when its source file is unchanged, only spec directories and plain test files changed between the two heads, no changed test file holds a test that traces it, no new test traces it and its tests pass; the earlier adequacy entries come with it, and its reason says `(carried)`. The round keeps the hold of the discarded reply, so it cannot PASS until that hold is answered, and findings are not carried. The ledger records `verify.carried` or `verify.not_carried`, and `verdict.json` keeps `judge_carried`, so a resumed round keeps the carried passes (L4-VER-072).

## 0.4.48 (2026-10-31)

### Fixed
- A step-9 judge whose reply does not fit its output limit is asked again with fewer criteria before it is discarded. Each part of a diff asks the judge for a verdict on every criterion of the unit, so a unit with many criteria can need a longer reply than the model may write; the opencode adapter reported that stop (`last reason: length`) as an error like any other, the judge was discarded for the round and the next judge got the same prompt. A consumer's unit of 29 criteria lost both of its working judges this way on part 1 of 4 and waited for capacity. Now an opencode run (v1 or v2) that stopped at the output limit is marked (`length_stop`; the status stays `error`), and the harness asks the same judge again with the prompt's criteria in two halves, splitting a half again when its reply also stops, at most `verifier.judge_length_splits` times (default 2: at most 4 batches and 7 calls for one part; 0 turns it off). The batch replies of a part are merged into one reply, so parts and follow-ups work as before; only the first batch carries the feedback, accepted and satisfied items. A judge whose smallest batch still stops at the limit is discarded as before, and the next judge gets the whole prompt. The ledger records `judge.length_split`, and `verdict.json` the batches (`judge_batches`). A reasoning model whose thinking alone fills its limit is not helped: give it a reasoning cap through `options.provider`, or add a judge with a larger output limit. Claude Code, Codex, Kiro and Copilot judges report no such stop and behave as before (L4-VER-071).

## 0.4.47 (2026-10-31)

### Fixed
- Red may change a named test of another language through its file's shared lines. A consumer's later unit had to make an earlier unit's merged TypeScript registry test expect 22 codes instead of 16; the reviewed task text named the test as `path::name` and told red to extend `EXPECTED_CODES`, the module-level constant the test compares with. Red did exactly that on two models and five attempts, and each attempt failed with `red broke existing tests: <the named id>`, so the unit halted on `max_task_attempts`: a named test of another language counted as changed only when its own lines (the `test(...)` call to its closing line) differed, and the constant sits above the call. Now a named test whose own lines are the same also counts as changed when it fails at red and its file's lines outside every test differ (`test_locate.outside_tests`: the lines in no test's window, the base report's tests at the base and the red report's at red, blank lines dropped), a constant, fixture or helper of that file; it is excused like one whose own lines changed, so it must fail by an assertion or `NotImplementedError` and green must make it pass. One whose own lines are the same and that still passes is unchanged: nothing is excused, recorded or failed, so a red step that only adds tests or imports to the file is not affected. A named test that fails at red while red changed neither its lines nor its file's shared lines is still `red broke existing tests`, and the reason now adds `the task names <id>, but red changed neither its lines nor the lines of its file outside the tests: change the test, or a constant or helper of its own file that it reads`. The red prompt says which changes count, `named_tests.found{task, tests, source}` records the tests the reviewed text named before each red agent step (before, a red step that failed on a named test left no sign that it had been named), and the judge's block of changed named tests gives the file's diff for a test changed through its shared lines instead of two equal copies of its lines. Not changed: a Python named test (L4-IMP-046's closure already reaches the module's definitions), green opens no pre-existing test file, a test whose expected value is in another file still needs a change of the test or its own file, and the file's other tests are protected by the regression check and by step 1 only, as before (L4-IMP-089, L4-VER-068).
- An agent step can no longer change `.gitattributes`. Git attributes decide what a diff shows: a `.gitattributes` with `*.py -diff` made the judge's diff and the verifier's step-1 scans read `Binary files a/x.py and b/x.py differ` for every Python change, an added `# noqa` included, and a `diff=` driver or `working-tree-encoding` changes the bytes they read too. Now `.gitattributes` at any depth is a protected path (any case), like the CI files and the agent configuration: what a step or a gate writes there is put back and recorded as `guard.violation`, and the root file is found even behind an edited `.gitignore`. A person's `.gitattributes` is the owner's choice and is listed as a protected path changed by a human, as before for the other protected paths (L4-SEC-004).
- A person's reject keeps its `WHEN … THEN …` when the reason is long. The question asks to end a reject's reason with the sentence that becomes the fix unit's check, but `human.verdict` kept only the first 1,000 characters of the reason, so a consumer's delegate's two rejects of 1,207 and 1,264 characters gave the fix unit the scenarios `THEN a` and `THEN a test asserts that [...DEFAULT_ROLES].sort() deep-equals [`. Now the recorded reason keeps up to 4,000 characters, and a longer one that has a `WHEN … THEN …` keeps that sentence whole, from its last `WHEN`, after the start of the text and ` … `; a longer reason without one, or whose sentence alone is longer than 3,800 characters, keeps its first 4,000 characters. The answer's digest is still of the whole answer (L4-VER-059).
- A fix unit's task, heading and proposal line keep the code brackets of the finding's text. To keep model-written text from carrying a `[tag]` that exempts a rule, every `[` and `]` became a parenthesis, so `[...DEFAULT_ROLES].sort() deep-equals ["approver", …]` reached the implementer as `(...DEFAULT_ROLES).sort() deep-equals (…)`. Now only a pair that could be a tag (letters, digits, `_`, `-` and spaces only, such as `[test-infra]` or `[ ]`) and a bracket without a partner become parentheses; any other pair stays, and no tag can be formed from what is left. A human tag still exempts nothing in a fix or follow-up unit (L4-IMP-006).

## 0.4.46 (2026-10-31)

### Changed
- `l4 restart` also supersedes the old attempt's verdict questions. Step 3 sets every open question and every verdict question, answered, consumed or open, to `superseded by restart` (a verdict judged the old attempt's code and evidence, and the new attempt's ledgers name no question of it); a verdict question already superseded stays as it is. Answered technical questions stay, because they are decisions the new attempt keeps. `unit.restarted{superseded_questions}` lists both kinds. The command cannot tell a consumed verdict question from an answered one in `questions.md` (the consumption is in the dropped ledger), so it acts on the kind alone (L4-OPS-004, L4-VER-070).
- `l4 questions list` shows a stale verdict question, whatever its Status (an answered one too), as `<unit> Q-001 stale <blocking> <title>` with the line `stale: raised by an earlier attempt; the next round asks again` under it; the `Next:` line names the first row that is not stale, and the delegate hint leaves stale questions out. `--json` rows carry `status`, `stale` and, for a stale one, `note`. `l4 questions show` says `Q-001 is stale: ...`, `l4 questions answer` on a stale question prints one info line, `Q-001 is stale: raised by an earlier attempt; the next round asks its criterion again`, and the MCP tools `l4_questions` and `l4_question` say that stale questions are listed or marked. The warning for a ledger that cannot be read names the unit once and what is not shown (`no question is marked stale`, `no frozen path or stale mark is shown`), and a question is never called stale for want of a ledger (L4-QMD-007, L4-VER-070).

### Fixed
- A unit that was restarted no longer verifies again on every run because of verdict answers from the old attempt. On a consumer (0.4.45) `l4 restart` started a unit over while its `questions.md` held three verdict questions answered `accept: ...` in the old attempt. A restart kept `questions.md` and superseded only the questions that were still open, and it dropped the old attempt's ledgers. From then on every run of the new attempt looped: the readers of verdict questions (`verdict_status`, which the orchestrator, the planner, the delegate and the sticky note use) counted the three carried-over answers as `ready`, so the run took `VERDICTS_ANSWERED` and the unit verified again (about $0.72 of judge per round), while `consume_verdicts` skipped each answer because no `question.raised` of the new attempt named it (`a question the harness never raised`), so the answers were never consumed. The round ended NEEDS_HUMAN on the same three criteria, and `raise_verdict_questions` asked nothing new because it treated a `ready` question as still waiting for its target. Three rounds ran before a person noticed; only the plan's run and cost limits would have ended it. The readers disagreed on what a verdict question is: `consume_verdicts` required that the attempt's ledger raised it, the others read `questions.md` alone. Now a verdict question counts (open, ready, invalid, dismissed, waiting for its target) only when a `question.raised{kind: verdict}` of the unit's current ledgers names it, the branch's files and the lock ref's pending files; every reader applies that rule (`verdict_status` takes the raised ids as a required argument, `UnitState.verdicts_raised`). A verdict question that none names, carried over by a restart or written by hand, is `stale`: it is not ready, not waiting, not consumed, not offered to the delegate and not in the sticky note, and the round's targets are asked again by the normal rules, or by the legacy path for a round that raised none (the plan says `legacy round N: NEEDS_HUMAN, and its verdict questions were raised by an earlier attempt (Q-001, ...), the run raises them again`; no judge call). When a round asks a target that a stale question names, that question becomes `superseded by Q-NNN`, so it is not listed as asked again for ever; its answer stays in the file. The evidence commit of a round now holds the run's ledger, so the `question.raised` of the round's questions reaches origin with its `questions.md`, or the question would read as stale on another machine and a run killed in that window would lose the event. A unit that already loops stops at its next run on 0.4.46, with no edit by a person: after `l4 upgrade --harness-ref v0.4.46` its next run raises a verdict question for each disputed criterion and waits for the answer. Known limits: the legacy check is `verdict_status(...).any is False`, so a live question for target A with stale ones for B and C (rounds run on 0.4.45 left them) asks B and C one round later, once A is answered and consumed, and the unit is never stuck; `delegate/run.py` `_Pass._events` and the `before` read of `consume_verdicts` read the branch ledger only, not the lock ref's pending ledger, which is unreachable today (the orchestrator folds both, and the evidence commit carries the run's ledger) and no regression; verdict questions of a fix unit raised by its parent are not covered (they are in the fix unit's own ledger by the existing rules) (L4-VER-070, L4-VER-013).
- A file name that is not UTF-8 can no longer make the ledger write raise. On Linux a name that is not valid UTF-8 reaches Python as a str with lone surrogates (`os.fsdecode`), and `Ledger.append` encoded the line as UTF-8 and raised `UnicodeEncodeError`. 0.4.45 fixed that for the one event of the Python encoding guard, which now names the file in a display form; every other event that carries a path (the protected-path guard, the test-path freeze, the gate configuration guard, the planted-link refusal, a scan finding) could still crash a step, or a run, on such a name. Now `Ledger.append` writes every str of an event (keys and values, nested, and the envelope) that holds a lone surrogate in a display form: a byte 0x80..0xFF that `os.fsdecode` escaped as `\xNN`, any other lone surrogate as `\uXXXX` text, each character alone. The line is always valid UTF-8; the returned event, the observers and the JSONL mirror get the same values; text without a surrogate is written byte for byte as before and pays one scan. The redaction still runs first. A name that is not UTF-8 therefore reads back from the ledger as `\xNN` text. Known limit: the display of such names in a merge request comment or a job summary is not changed (they read the ledger's values, which no longer hold surrogates) (L4-OBS-006).

## 0.4.45 (2026-10-30)

### Added
- `--no-fetch` on `l4 status`, `l4 plan`, `l4 resume`, `l4 run` (also `--unit` and `--dry-run`) and `l4 archive`: the command fetches nothing for the state and reads the local refs, as these commands did on a person's computer before. The help says `Read the local refs for the state; a run's worktree still fetches the unit.`: the flag does not reach the worktree of `l4 run`, `l4 resume` and `l4 archive`, which still fetches the base branch and the unit refs before it cuts the branch it works on, so these three still need the forge. A CI job cannot use it: exit 2, `--no-fetch is for a person's computer: a CI job must not read stale refs (L4-CLI-003)` (L4-CLI-005).
- The verdict of a verification round records why each test failed and in which gate. A new `failures` map in `verdict.json` holds, for every test id that failed or errored in step 3, the gate (`test` or `e2e`), the failure kind the JUnit reader gives (`assertion`, `not_implemented`, `error`, `other`, …) and the first line of its message, redacted and at most 200 characters; a module that did not collect has a record of kind `collection`. The `test` side holds the first 200 ids in order and `failures_dropped` counts the rest, the `e2e` side is whole, and `e2e_tests` lists the ids of the e2e report, which tells a browser test from a unit test in `tests`. The `tests` map keeps its form and a reused round keeps the three keys. Before this nothing in a round said whether a failing test came from the unit gate or the browser gate, or whether it failed by assertion or by an error before any check, so a broken test and broken code looked the same (L4-VER-069).

### Changed
- `l4 status`, `l4 plan`, `l4 resume`, `l4 run` and `l4 archive` fetch the unit branches, the lock refs and the plan refs on a person's computer too, before they read anything. They fetched only in a CI job; on a computer they read whatever the last `git fetch` left, so a spec edit pushed from another computer, a run's ledger, a merged or deleted branch or the plan's progress could be missing, and the runbook told people to use `l4 retry`, which fetched, instead. Now the fetch (with `--prune`, once per process, with the token of `forge.token_env` when that variable is set and otherwise your own git credentials) comes first, and a checkout without an `origin` remote is not fetched. `l4 retry` and `l4 restart` bring the plan refs in their fetch too. The sandbox preflight of a local `l4 run` still comes before the fetch. When the fetch fails outside a CI job, `l4 status` warns once (`could not refresh from the forge (<reason>); showing local refs`), shows the local refs whatever git said (a laptop may be offline) and gives up on the fetch after 15 seconds; every other command stops before it folds anything, exit 1 (exit 3 when the forge refused the credential, which also names `forge.token_env` when it is set, because git then uses it instead of your credential helper), with the reason and a hint of its own: `plan` and `run --dry-run` say `pass --no-fetch to read the local refs`, and `run`, `resume` and `archive` say that they need the forge (their worktree fetches) and name `l4 status --no-fetch` to read the local state. In a CI job nothing changes (L4-CLI-005, L4-CLI-003, L4-CLI-004, L4-OPS-014). Known limit: the worktree of `run`, `resume` and `archive` builds its fetch credential without the URL of `origin`, so with `forge.type: auto` and a github.com `origin` it names GitLab's user name for the token.
- A fix chore for a browser-test finding runs the build and the browser tests. The unit's test gate cannot see them, so a fix task for a failed e2e gate was checked against nothing. Now a fix chore whose task holds `e2e gate failed`, or a `new tests failed` or `new tests errored` finding that names tests the parent round recorded under the e2e gate, runs `gates.build` (when configured) and then the e2e gate after the test gate. For `e2e gate failed` the gate must pass, judged whole as step 3 judges it; the tests of the finding must be in the report and pass; and no browser test that passed in the parent round may fail, error or be missing now. A build that fails or a server that is not ready fails the attempt with its reason (`the e2e server was not ready (see <log>)`, with the end of the log), not the run. What the build and the browser run write into the tree (output, `test-results/`, a snapshot baseline, a lock file) is not committed, and a symbolic link a gate plants is removed and halts the unit like any planted link (L4-IMP-090, L4-SEC-021).
- One failure is one fix task. A `new tests failed` or `new tests errored` finding whose test ids are all among the failing ids of a `test gate failed` or `e2e gate failed` finding of the same round now joins that finding's task, which names both, instead of making a second task for the same failure. A list the finding cut (`and <n> more`), ids of two gates, or a verdict without the `failures` map keep two tasks (L4-VER-006).

### Fixed
- A fix task is no longer ticked done when the guard put back its only edit. On a consumer (0.4.43) a new end-to-end test raised an error before any check; step 3 failed two tests and made two findings for the same failures, and each became a fix chore. The agent's edit of the broken test was put back by the guard (a fix task may not change tests), nothing else changed, the test gate had no regression, and the task was ticked done with a commit of `tasks.md` and the ledger alone. Now a fix chore in which a guard put back every edit and no other file changed fails the attempt with `nothing changed: the guard put back every edit (<paths>)`; any guard counts (the test-path freeze, a protected path, a runner configuration), a chore for a CI job keeps its rule (it commits the put-back chore, and `ci_not_fixed` reads it) and a retake keeps `already-done` (L4-IMP-017).
- A fix task no longer changes correct product code to suit a broken browser test unchecked. On the same consumer the second fix task changed an HTTP status code that the design fixes so that the second broken test would pass, and nothing ran the browser tests on it. Now such a task is checked against the e2e gate (see above), so a unit whose own browser test is broken fails its fix attempts honestly and escalates to a person, instead of bending the code to the test (L4-IMP-090).
- A Python file with a coding cookie that names another encoding can no longer hide code from the harness and the judge. An adversarial review (2026-10-30) proved, with the harness's own functions, that a red step could add `# coding: utf-7` as line 1 of a pre-existing test and `  # +AAo-    return` to a line of it: Python honours the cookie and reads a newline and a `return`, while the tamper check, the skip-marker scan and the judge read the file as UTF-8 and see a comment, so the test passed against a broken product and red's own new test still failed by assertion, as red requires. The same trick hides code in any Python file, product code included. Now, after every agent step (red, green, every chore, a refactor and a replayed held step), a `.py` or `.pyi` file the step added or changed whose declared encoding (`tokenize.detect_encoding`) is not `utf-8`, `utf-8-sig` or `ascii` is put back (a new file is removed), recorded as `guard.violation` with `rule: "python encoding"`, and the attempt fails with the advice `Python files must stay UTF-8: do not add a coding cookie that names another encoding. …`; a file that already declared another encoding is put back too, whoever wrote the cookie, and so is a file the guard cannot open (it is `unreadable`). The verifier's integrity checks have a new row, `python encoding`, that makes one blocker `a Python file declares a non-UTF-8 encoding: <path>: <encoding>` listing every such file in base..head (five, then `(+N more)`), whoever committed it, a person included. The verifier's test writer refuses audit and e2e code that declares another encoding (`the test declares the encoding <encoding>; write UTF-8 without a coding cookie`), and `write_test_file` refuses to write it. A Python-named symbolic link is followed inside the tree (chains and linked directories, at most 40 links): when the link or the file it ends at changed, the file at the end is checked and the changed paths of the chain are put back; the guard matches the target by file identity, so a file system that ignores case gives no way round it, and the verifier by folded name. The verifier blocks a touched link that it cannot check (`<link>: link that cannot be checked`): one that ends at no regular file, whose target was deleted or renamed (case only too), that has several folded matches, or of which only a link in the chain changed; a dangling, directory or loop link is not followed, because Python cannot import it as a file. Names that are not UTF-8 stay distinct and are shown as `\xNN`. No file is read whole or skipped by size: at most 64 KiB + 1 bytes decide, and a comment or blank line 1 or 2 longer than that, behind which a cookie may sit, is `unreadable` and a violation like any other encoding; a long line of code is fine. A file with no cookie, a `utf-8` or `ascii` cookie or a byte-order mark is unaffected, and so is a file that is not Python. Not changed, known limits: a file that a gate run writes is checked only by the verifier row, before merge, not after the gates; `.gitattributes` is not frozen; extensionless scripts with a Python shebang, `.pyw`, files loaded through `runpy` and tracked `.pyc` files are not checked; a blob read has no timeout (only the wait for git to exit has one); the verifier's link walk costs one git call per hop for every Python-named link (about 11 s for 1,500 links); the verifier does not follow a link whose directory components differ in case from git's names; and a pre-existing Python file that declares another encoding must be converted to UTF-8 on the base branch before a unit can change it (L4-SEC-042).

## 0.4.44 (2026-10-30)

### Added
- `l4 doctor` says on your own computer when `l4 run` and `l4 verify` will refuse there: a new row LOCAL-001. Since 0.4.43 a local run without a usable sandbox refuses up front (exit 3, nothing recorded), but the doctor said nothing about it on such a computer (the bubblewrap row PRV-002 is skipped off Linux, and SANDBOX-002 and -003 skip when `bwrap` is absent), so a person learned it only when the run refused. Now the row (severity warn, scope `local` only) asks the same preflight the two commands ask and fails with `l4 run/l4 verify will refuse on this computer: <reason>`, the reason being the preflight's (on macOS the ways out: a Linux machine or VM with bubblewrap, letting CI run it with `l4 ci start` or `l4 retry`, `sandbox.mode: container` once it exists). `sandbox.mode: user` and `container` are not built; the row fails naming the mode (`sandbox.mode: user is not built yet`) instead of crashing. It passes naming the sandbox a run would use (`bwrap`, or `none` with `allow_none: true`). `l4 doctor --ci` and `--adoption` never run it, so it cannot change a CI job's exit code, and as a warning it leaves the exit code of `l4 doctor` as the other rows make it. SANDBOX-001, which docs/SPEC.md listed as a warning on macOS (SCN-NFR-05), is not registered: its row is the full credential and isolation probe of L4-SEC-005, which is a separate change, and a row with that id that did less would mislead; the table now says so and SCN-NFR-05 names LOCAL-001 (L4-DOC-001, L4-SEC-041).
- A task that delivers documentation which a test glob covers is warned about before any run: the intake warning `test_path`. On a consumer a task delivered JSON client fixtures under `docs/client/fixtures/*.json`; the default `tdd.test_globs` and `tdd.test_support_globs` include `**/fixtures/**`, so green's write was restored twice as a test-path change and the unit escalated, and the agent's hint said "Tests belong in the red step", which is wrong advice for documentation. Every input is known before the first run, so now a pending required task without the `[test-infra]` tag that names a path (a file, a directory or a glob token such as `docs/x/fixtures/*.json`, which counts as a file directly in its directory) that a test or support glob of the effective config matches and that a scope-exempt glob (`verifier.evidence.scope_exempt`: `docs/**`, `**/*.md`, `CHANGELOG*` by default) also matches gets `warning: test_path: <unit>: task 2.1 names docs/client/fixtures/, which the test glob **/fixtures/** matches …` from `l4 yolo check`, `check --worktree` and `l4 yolo go`, in the CI review's log and at the unit start (a log line, no `unit.rejected`, exit codes unchanged). The message names every glob that matches and the two fixes: a person tags the task `[test-infra]`, or the base branch's `tdd.test_globs` and `tdd.test_support_globs` leave the glob out. The match is the freeze's own, so intake and freeze cannot disagree. A line that says not to touch the path, a ticked task, a path with a source-code extension (test code under `docs/` is red's work) and an ordinary test path such as `tests/fixtures/users.json` give nothing. Not changed: the default globs (narrowing them would stop freezing root-level and `src/**/fixtures` test data for every consumer), the freeze and the skill's offline plan validator (L4-YOLO-094).
- `l4 questions answer` and `accept` say when a run works on the unit. A person (or an agent) can answer while a run works, and nothing showed whether that run would take the answer. Now, right after the `pushed … to <branch>` line, the output has `[l4] questions: run <id> works on <unit> (started <n> min ago): it takes this answer at its next push, or the next run does` when the unit branch's ledger (with the lock ref's pending ledger) shows a run that started and has no end, and the same liveness rule as `l4 yolo status` does not call it ended: with a CI link, older than its job timeout plus 5 minutes, or a CI run the forge says completed (asked only when the age does not decide; a run held for approval has not ended; when the forge cannot be asked, the age decides); a run without a CI link (a local run) counts as ended once it is older than its job timeout (180 minutes when the ledger names none) plus 5 minutes, so that a local run that died is not named for ever. Information only: the write, the exit code and every refusal are as before, `--no-push` prints no line, and a ledger or forge that cannot be read gives none. There is no `l4 questions dismiss` in this tree; the line sits in the one write that `answer` and `accept` share (L4-QMD-011).

### Changed
- A run that only answers questions now answers every question that is due. A consumer's verification round raised 30 and 33 verdict questions at once (one per held criterion); the delegate asked at most `delegate.max_questions_per_run` (default 5) per run and the unit verifies again only when every verdict is settled, so each further run was a delegate-only pass of 5 (3.3 minutes), and the units used 9 and 6 of the plan's 60 runs. Now a pass in a run in which no step of the unit ran before it (the run exists for the delegate) is not bound by that cap: it asks until nothing is due, the first deferral for lack of time (the soft deadline) ends it and the rest wait for the run that deferral asks for, or a cost limit escalates the rest. The pass at the end of a run that did unit work keeps the cap, and the unit still does not continue in the same run. The ledger records `delegate.pass{bound, delegate_only}` at the end of a pass (`bound`: `cap`, `none_due`, `deadline` or `cost`). The cost cap is the owner's setting and is not changed: the delegate's cost over a unit and its fix units is `delegate.max_cost_usd_per_unit` (default $15; a call needs `delegate.max_cost_usd_per_answer`, default $3, left) and the plan's share is `delegate.plan_cost_share` (0.25) of the plan's `limits.max_cost_usd`, so with the defaults a flood still reaches a person after about 12 calls; the saving is about one run per flood of verdicts, not most of them. Raise `delegate.max_cost_usd_per_unit` to let the delegate go on, lower `delegate.max_questions_per_run` to bound the tail of a working run (L4-DLG-003, L4-DLG-009, L4-DLG-013).

### Fixed
- A short quote in the delegate's reply is refused by name, and the prompt states the minimum. Five replies of one consumer unit (about $5.40 of its $15) were thrown away because a `checked` quote was shorter than 12 characters (a quote such as `c: {},`); the refusal said `does not resolve` and the prompt never stated the minimum, so the retry made the same mistake. Now the refusal reads `checked <ref>: the quote of <ref> is shorter than 12 characters` (retryable, whitespace folded, checked before resolution), a long quote that is not on the line keeps `does not resolve`, and the prompt says a quote is at least 12 characters, copied word for word (L4-DLG-005).
- The retry hint after green wrote a documentation path that a test glob covers no longer says "Tests belong in the red step". For a put-back (the test-path freeze, or the removal of a new support path) of a path that a scope-exempt glob and a test or support glob both match, the hint now says that a test glob covers the path, that no agent step after red may write it, to report the task blocked naming the path, and that a person must tag the task `[test-infra]` or leave the glob out of the `tdd` globs on the base branch. A put-back of an ordinary test path, of source code under `docs/` or of a fix chore keeps its text (L4-IMP-006, L4-YOLO-094).
- The artefacts line of a local run no longer says `(CI: job artifacts)`. It names the agent and gate directories only; in a GitHub Actions or GitLab CI job the suffix (or the `not uploaded` note) is as before (L4-IMP-064).
- A person's answer pushed while a run works no longer breaks that run's next push. On a consumer (0.4.40) an agent answered 29 questions with `l4 questions answer`, about one every 4 seconds, while a run worked on the unit; the run made 25 commits of its own and pushed: the forge refused the push (`! [rejected] … (stale info)`), the run ended with exit 1 and advice to `l4 restart`, its 25 commits and its final ledger never reached the forge, and the ledger on the branch kept a `run.started` with no end, so the run looked open for ever. The merge of a person's push that L4-RACE-001 had always promised was never built. Now a refused push is classified with `git ls-remote` against the head the run last saw: the branch is gone, it moved forward, or it was rewritten. When it moved forward and every commit only adds or changes, as a regular file, the `questions.md` of the unit's folder or of one of its fix-unit folders that the branch holds, the run fetches the remote head, merges it into its own HEAD with a harness merge commit (never a rebase), scans the outgoing commits again, and pushes; it makes up to 3 pushes, 5 s and then 15 s apart, then exits 1 `the unit branch keeps moving on the forge` (the answers stay on the forge and the next run takes them). The next step reads the merged `questions.md`, the ledger records `push.merged{remote, commits, paths}`, and a question that both sides changed keeps the person's answer: a delegate's accept, answer or escalation (a `questions.md` section with the harness's `Answered by:` or `Escalated by:` line) no longer beats it, whichever is newer, in a base merge too. The delegate re-reads a question from the worktree before it asks and skips one that was answered meanwhile. What still ends a run: a person's push of any other path (the run exits 1 and names the paths and that the next run starts from the forge's branch, without the `l4 restart` advice that was wrong for a branch that only moved forward), a rewritten or deleted branch (a person's decision: restore it, or `l4 restart`), a push the harness would have to make on top of the unit's hand-off commit, and answers faster than the three pushes. A run whose push of the unit branch fails now still ends on the forge: it publishes a reduced copy of its ledger to the lock ref (the lines the branch already has, every `budget.cost` and `lock.released`, and `run.finished` with `the push of the unit branch failed: <why>`, the forge host scrubbed), so the run has its end and its costs count, and the events about lost commits (a delegate's answer to a question that is still open on the branch, a task done) are not published as facts. The run's commits stay on the runner. Two risks are named: a delegate call that reported no cost is not counted by `delegate_cost` after such a failure, and the atomic push that also advances the lock ref (L4-LCK-001's fencing) is still not built; the SPEC says so (L4-RACE-001, L4-RACE-002, L4-LCK-001, L4-QMD-011).

## 0.4.43 (2026-10-30)

### Added
- `l4 ci start [--if-idle DURATION]` starts the harness's CI run on the base branch only when the harness is idle. People who drive a plan from a laptop wrote their own dispatchers (`gh workflow run` in a loop) that started a run while another was queued or running, or right after one ended, and the queue then held two runs for one job. Now the command asks the forge first: it starts a run (GitHub: a `workflow_dispatch` of `l4.yml`; GitLab: `POST /pipeline` with the forge token) only when no run of the harness is queued or running on any branch, because the job holds one concurrency group for the repository (GitHub counts the newest 100 runs of `l4.yml`, a run held for approval included; GitLab counts the newest 100 pipelines on the base, on the default branch and on the unit-branch prefix), and, with `--if-idle`, when the last run ended at least DURATION ago (`12m`, `90s`). It prints what it did or why it did not. Exit 0 when a run was started or the forge said busy or recent, so a loop goes on; 3 when the token is missing, the forge refuses or it cannot tell (a failed listing, an answer that is not JSON, a finished run with no readable end time, the local forge), so a loop notices; 2 for a bad duration. The listing of the continuation, the relay and `start_run` is not changed. Two risks are named: GitHub's run listing lags right after a dispatch, so two callers seconds apart can both start one, and the idle time is measured with this machine's clock against the forge's timestamps, so a skewed clock shifts it by the skew. `l4 yolo drive` is not part of this change (L4-OPS-024).

### Changed
- Red may change an existing test of any language in place when the task names it as `path::name`. Only a Python test could be changed by red (`path.py::name`, L4-IMP-082), so a later unit that had to change an earlier unit's merged TypeScript test (a registry test asserting "exactly 16 codes", where the task adds six) failed at red with `red broke existing tests`, and green may not open a pre-existing test file at all, so the task cost a question round and a run. Now a backticked `` `src/api/codes.test.ts::the registry holds exactly the codes` `` in the task's reviewed text, where the path is a tracked regular non-Python file of `tdd.test_globs`, names one test when exactly one id of the base report belongs to that file and its name is equal to the given one or ends with it after ` > `. Red may then change that test's own lines; the changed test must fail at red like a new red test (by an assertion or `NotImplementedError`, never by a hang), a changed test that passes, that fails otherwise, or that red deleted or renamed fails the attempt, a changed named test does not count as a new test (the criteria still need one), and a task whose red changed one never ends as already satisfied. The harness records `tests.superseded{reason: named_by_task, language}`, step 1 of the verifier still runs every other test of the file at its base version and folds a recorded id at `[` only for Python ids, and the judge's prompt gets a block that lists each changed named test with its lines at the base and at head. A name that matches no test or several, a test a `.each` generates and a Go test (whose id maps to no file) name nothing: each is recorded as `named_tests.kept{task, token, reason}` and listed in the red prompt. Green stays closed to pre-existing test files in every language, L4-IMP-014's kept reasons and L4-IMP-016's rules are unchanged, and a test whose expected value lives outside its own lines (a shared fixture) is not changed by an edit of those lines alone (L4-IMP-089, L4-VER-068, L4-IMP-082, L4-IMP-048, L4-IMP-014).
- One rule says whether the harness runs in a CI job, and a forge's token is required in any CI job. Three rules were in use: `GITLAB_CI`, `GITHUB_ACTIONS` or `CI` in one helper, inline checks of the first two elsewhere, and a check bound to the forge's own platform, so `CI=true` on a laptop armed the plan step's job budget while the forge code treated the machine as local. Now a CI job is `GITLAB_CI` or `GITHUB_ACTIONS` set to `true` (`in_ci_job`), and the refresh of refs, the plan step's fetch and budget, the continuation, the GitLab push credential helper and the forge token requirement use it. `CI` alone (`ci_like`) stays only where it is an opt-in: the gate environment of L4-SEC-040, the judges' fail-closed sandbox fallback and the severity of the doctor's tool and gate checks. The token requirement follows the rule: `forge.type: gitlab` under `GITHUB_ACTIONS` (or the reverse) without a token now exits 3 before the lease, with a message that names the forge, which the old per-platform check did not require. A contract test lists every comparison of the two variables outside `ci/detect.py` against an allowlist of the sites that ask which CI runs, so a new one fails the suite (L4-CLI-004).

### Fixed
- An accepted UI criterion is no longer held again in every later round. A UI criterion served by a unit-level end-to-end helper raised a hold in round 1 (`fails_at_head`), a person accepted it with a verdict question, and rounds 3 and 5 raised a new hold each (`not_testable`, `uncollectable`), each a new question for a person and a run: the hold's id is a hash of its text, the text named the generator's status, and step 5 never read the verdicts. Now a UI hold's text names no status (`UI criterion C-… has no end-to-end test; see the generated UI tests table`), so its id is the same in every round; the status and the writer's reason stay in the table, in `verify.generated`, in the hold's question and in the delegate's material. Before step 5 calls the writer, a UI criterion is waived when an accept of the criterion is in force, or the latest accept of any UI hold of it is in force: `verify.generated{status: waived, by}` is recorded, no writer is called, no hold is raised, the minor gap finding stays (`waived by …`) and no fix unit is made for it. A hold's accept is bound to the hold's text, the criterion's text and the files of its tracing tests (a test of any language); an accept of the criterion itself is bound to its text only. A waiver ends when the criterion's text or, for a hold's accept, its tracing tests change, on a void, and on a later reject, also one a fix unit consumed; a failing tracing test suspends it for that round, and a criterion whose own verdict in force is a reject is not waived. An accept written before this change has no binding and survives a text change until a reject, a void or a failing tracing test. A rejected hold keeps its path. One risk is named: an accept given on `fails_at_head` survives later UI rework that does not touch the tracing tests (L4-VER-067, L4-VER-013, L4-VER-014).
- A local run on a host without a sandbox no longer stops the plan for everyone. `l4 run --unit <the plan's current unit>` on a laptop without bubblewrap (macOS, for example) took the lease, made the worktree and the ledger, and only then failed to select a sandbox (exit 3); the run recorded `unit.setup_failed`, the next plan step stopped the plan, and the message was the Linux-only bubblewrap hint. Now `l4 run` (also `--unit`) and `l4 verify` check outside a CI job, before refreshing refs, running follow-ups, taking a plan step, a lease or a worktree, that a sandbox can be selected, and exit 3 with nothing recorded when none can: no ledger line, no lease, no worktree, no plan event, and the plan is not stopped. On macOS the message names the ways out and the refused command: a Linux machine or VM with bubblewrap, letting CI run it (`l4 ci start`, or `l4 retry` for a halted or escalated unit), or `sandbox.mode: container` once it exists. `sandbox.mode: none` with `allow_none`, `--dry-run`, `l4 retry`, `l4 resume` and `l4 simulate` are not checked, and in a CI job the check stays in the run: a runner without a sandbox still records `unit.setup_failed` and the plan stops, which the SPEC now says (L4-SEC-041, L4-YOLO-093).

## 0.4.42 (2026-10-30)

### Changed
- An agent that goes silent without doing anything is a limit of its profile, not a failed attempt. A reachable profile whose hello passed could end every step with no tool call, no output and no error: the idle watchdog stopped each step after `implementer.idle_timeout` (10 minutes), the stop counted as a failed attempt, a task moved to the next profile only after `implementer.escalate_after` such stops (20 minutes), and the next task began on the silent profile again, because the run's selected profile never changed and the passed hello stayed cached. Now an implementer step stopped by the idle watchdog before its stream reader saw any tool call, while `roles.implementer` lists more than one profile, is a *silent stop* and is handled as a limit: `availability.limit{kind: silent}`, the profile cools for `availability.default_cooldown`, its cached hello is cleared, `availability.fallback{reason: silent}`, the run's profile moves when it was the silent one, the step's uncommitted work is discarded, and the task goes on on the next usable profile with a note that the profile went silent. It counts for nothing: no `task.attempt_failed`, nothing toward `implementer.escalate_after` or `implementer.max_task_attempts`. `agent.idle` has `silent: true|false`, and the `agent.idle` log line says it is a limit of the profile and not a failed attempt. A task's second silent stop counts as a failed attempt (`reason: silent: already once for this task`), so a chain whose profiles all go silent halts on `max_task_attempts` and does not park run after run. A second limit in one fix task now also cools its profile before the unit parks. An idle stop after a tool call, a step that reaches its time limit, `implementer.idle_timeout: 0`, the deadline's cancel and every idle stop of a chain with one profile count as before, and token counts are not used to decide. One cost is named: an agent whose first tool call runs, or which thinks, longer than `implementer.idle_timeout` with nothing printed reads as silent. OpenCode reports a tool call only when it ends, so there a first call longer than the idle time costs one cool-down of that profile and a move, at most once per task; raise `implementer.idle_timeout` for such a project (L4-IMP-087, L4-IMP-024, L4-IMP-017, L4-AVL-003, L4-AVL-005, L4-AVL-006).
- A task's baseline reuses the green test run of the same code, which saves about a minute for each task after the first of a job. Each task measures a baseline of the full test gate before its red step, and the baseline of every task after the first ran right after the previous task's green gate had run the same suite on the same code (about 65 s each; 8 to 9 minutes in a unit of 9 tasks), because the cache of baselines is keyed by commit and the next base is the green commit, which the harness makes after the gate. Now the harness takes the tree the green gate tests before it runs, and keeps that tree, the gate's digest (command, reports, format, timeouts, network, sandbox mode) and the report after an accepted green. The next baseline of the job takes the report when the digest is the same and the base's tree differs from the kept tree only in the unit's ledger, its `tasks.md` and its held files, records `gate.reused{name: baseline, from: test, task, source_sha, tree}`, prints `gate baseline reused (the green run of <sha>)`, and runs neither setup nor the gate. The first baseline of a job is always measured, and a green gate that ran with a fix unit's coverage environment, after a guard restore (a replayed held step included) or an environment rebuild, or that wrote a tracked file is not reused; an agent step, a discard, a rebuilt workbench or a new job ends the reuse. `resume_red`, the static-gate baselines, the step keys and the verifier's own measurement of its base do not change. A residual risk is named: the tree compared is what git sees, so ignored and excluded files and a version derived from git (setuptools-scm, `git describe`) are outside it, and a test that depends on them could see a different result at the next base than the reused report says (L4-IMP-088, L4-IMP-002).

## 0.4.41 (2026-10-29)

### Fixed
- A red test that uses subtests no longer fails green whatever the code does. unittest-xml-reporting writes a testcase for each failing subtest (`test_rejects (value='')`) and, when every subtest passes, one testcase for the method only. Red recorded the failing subtests as the new tests, so after a green step that made the whole suite pass those ids were missing, the step failed with `red tests still failing` on every attempt and on every profile, and the unit halted on `max_task_attempts`. A subtest's testcase is now read into its test's id with the worse result of the test and its subtests (of two equal failures, the worse kind), and its message names the subtest; a test one of whose subtests fails by assertion under the zero values still counts as discriminating. Test ids that a unit's ledger holds in the subtest form, from a red step before this release, name their test too, so a halted unit can be retried after the upgrade. pytest parameter ids and the display names of other languages keep their ids (L4-GAT-006).

## 0.4.40 (2026-10-29)

### Fixed
- A `merge: auto` plan waits out the hand-off window inside the run, so it no longer idles until someone wakes it. For ten minutes after a unit's hand-off, "no CI on the hand-off commit yet" counts as running, because a repository's CI may not have started. A plan whose current unit was in that window recorded `merge_not_ready`, started no next run, and stayed asleep after the window closed until the next scheduled run, a person's command or a person's resume woke it: on a repository whose pull requests to the target run no CI, that cost one manual resume per unit. Now the plan step of a CI run with a known job budget sleeps for the rest of the window plus 15 s in slices of at most 60 s, reads the hand-off commit's CI after each slice, and asks the merge guard again from the start, which merges the unit as on any wake. CI that appears during the wait ends it, and the normal path records it (a running job, a red job). The wait is bounded by the job's remaining time less a reserve for the merge, its confirmation and the integration; when the budget ends it before the window closes, the wait is recorded as before and the run starts the next run once, which waits out the rest on the same rule. The job's log says `no CI on H yet; waiting up to <N> s for the hand-off window`, and a person's run queues behind that job for at most about ten minutes. Nothing changes for a local run, a job with an unknown budget, `l4 run --unit`, a read-only step, `yolo.merge.require_ci: true` or a base branch that requires a check the hand-off commit has not reported: they record the wait and start no run, as before. A repository whose CI is merely slow still waits for it as before (L4-YOLO-012, L4-YOLO-013, L4-CI-014).
- A server error that OpenCode reports only in words is transient, is not remembered as a wrong answer, and is tried again. A provider's HTTP 503 reached OpenCode 1.x as `[503] … Service temporarily overloaded` in the message, with no `statusCode`, so the hello classed it `other` and cached it for `availability.cache_ttl` (15 minutes): the free profile was skipped for the whole run with `opencode reported an error`, and the in-run retry of judge, verifier-agent and clarifier calls never ran for OpenCode, because its run path never marked an error transient. Both hellos (OpenCode 1.x and 2.x) now read the status as an integer when there is one (`statusCode`, `error.status`, or a `[NNN]` in the message that no word character precedes, so `messages[503]` is no status) and otherwise class the error by server-side words only: unavailable, overloaded, a timeout, a connection reset, refused or closed are `transient`, anything else `other`; a bracketed 429 is a rate limit. A transient error event is tried once more after 20 s (the deadline checked before and after the wait), and `availability.selected` shows `hello_retry_wait_s`; Claude's hello, which already retried, moved onto the same helper and now also checks the deadline around its wait. A limit, a login failure, a wrong answer, an unsupported version, a hello that timed out, an exit with no error event and an unreachable custom provider are not tried again, and a second transient answer is final. OpenCode's run path marks an error of the transient class as transient, so judge, verifier-agent and clarifier calls retry it (3 tries, 20 s then 60 s). Credits and quota stay limits, and no cache time changes (L4-AVL-002, L4-AVL-005, L4-AVL-006).
- A task that names a file the harness will never let an agent write is refused before any run, and the notes after such a removal name the right fix. `odd.forbidden_paths` (by default `.github/workflows/**`, `.gitlab-ci.yml`, `**/migrations/**` and `infra/**`) is removed by the write guard after every step, but a unit's `tasks.md` could still tell the implementer to create `app/migrations/0001_initial.py`: the file was removed after each attempt, the retry hint was the generic one, and after about an hour and 7 attempts the unit raised a question whose note explained how to unfreeze a test, which cannot help. Now the intake (`l4 yolo check`, `review`, `activate`, `go`, the CI review and the start of a unit before it implements, OpenSpec and Kiro) refuses a pending required task whose own text names a missing file that a glob of `odd.forbidden_paths` matches, with the blocker `forbidden_path` naming the task, the path, the glob and the fixes: an explicit `odd.forbidden_paths` list on the base branch without that glob, a person's commit of the file on the base branch first, or rewording the task (not offered as a config fix for the workflow files). A file the revision already tracks, a directory, a nested file, a mention in the design or the spec deltas, a ticked task, a line that says not to touch the file and a line that says a person delivers it are not blockers; the first four print a `warning:` line, and a unit already implementing gets a warning and not a refusal. The agent's retry hint after such a removal now says that no step may write the path and no answer lifts that, and the harness note on a question raised after it, or naming a missing forbidden path, names the path, the glob and the two fixes instead of the unfreeze note; a question that only mentions an existing forbidden file keeps the unfreeze note. The guard is unchanged, and the skill's offline plan validator does not run the rule (L4-YOLO-092, L4-YOLO-002, L4-IMP-006, L4-IMP-015).

### Changed
- The tasks of a fix unit, and a chore task of any unit, move along `roles.implementer` after `implementer.escalate_after` failed attempts, as red and green do. The rule "the tasks of a fix unit do not move" is gone: a fix chore that the cheap first profile could not do halted the unit after `max_task_attempts` on that profile while a stronger profile was configured and idle, and a chore of a follow-up unit never moved either. Now the fix loop asks the same selection as the unit's own loop (the next usable profile with the same checks, including the independence rule for the judges), runs the task on it in a fresh session with the previous-attempt block, and the next task of the fix unit starts on the run's selected profile again; failures of an earlier run move a follow-up unit's chore before its first attempt. `implementer.escalated` records `phase: single` for a chore. The run's selected profile and the profile the fix loop reads do not change, a limit on the moved profile cools that profile only, and a held check, a `blocked` result and a limit still count for nothing. `implementer.escalate_after: 0` turns it off for fix units too. A fix unit that escalates adds a profile to the unit's implementer profiles, which can narrow the judges that pass the independence rule in a later round (L4-IMP-017).

## 0.4.39 (2026-10-29)

### Fixed
- A suggested edit of a frozen test is taken when the agent wrote its path without backticks. A blocked green step's technical question carries option 1 "Edit `<path>`: <change>" as its suggested answer, so that one `accept` unfreezes exactly that file. An option written "Edit src/x.test.ts: …" got no suggestion: `l4 questions accept` had nothing to take, and the delegate's answer that named the path was refused, so the question waited for a person or for another implementer round. Option 1 is now read in both forms (the bare path is one token with a `/` or a `.`), and the suggestion and the harness note use the backticked form. A question raised before this release that has no suggestion block takes its option 1 too: `l4 questions show` names it (`accept.from: "option 1"` in JSON), and `l4 questions accept` and the delegate's `accept` write the block before they set Status `accepted`. A block that exists is never replaced, and nothing opens that did not before: the question must name the file, and the delegate's accept opens test files only and nothing in a fix task. The delegate's prompt (`delegate@6`) now says that a frozen test file opens only through `accept` of the suggestion. When option 1 holds a value the redactor hides, `show` and `accept` say so and ask for an answer with `--text` instead of failing half way (L4-IMP-004, L4-QMD-008, L4-DLG-014).
- A push that fails on the forge's side is tried again instead of losing the step. A single `remote: fatal error in commit_refs_rules` with `! [remote rejected]` from GitHub failed a run that had worked for over twelve minutes, and the unit's line said `push refused by the forge`. Every harness push now tries a server or network error (HTTP 5xx, `RPC failed`, a dropped connection) up to 3 times, 5 s and then 15 s apart, and starts no try more than 60 s after the first. Before each new try it asks the remote whether the push landed after all, so a branch lease is never refused by the harness's own earlier push. A credential or permission failure, an HTTP 4xx answer other than a timeout or a rate limit (a push too large, a bad request), a hook's or a rule's refusal and a moved branch are not retried, as before. The plan ledger's push is retried the same way; `l4 yolo go`'s push of your own commits is not. A server error that remains says `push failed on the forge's side`, is no refusal, and the sweeper tries the archive push again at its next pass (L4-LCK-001).

## 0.4.38 (2026-10-29)

### Fixed
- A test in a file of another language is no longer rejected in a project that also has Python files. In 0.4.37 a TypeScript test chore was held only when neither check run could be made. When the unit changed a Python production file (for example `deploy/seed.py`) the runs were made, but they vary Python files only, so a test such as `src/pricing/total.test.ts` passed both and was rejected with `none of the tests you added looks at the answer`, whatever it asserted, until the unit halted on `max_task_attempts`. Such a test that no run accepted and that no run reached by an error is now inconclusive (`the zero-value run and the base run vary Python files only, and <file> is not a Python file`), and its chore is held with a harness question. A test chore is also held, not failed, when the zero-value scope has files but no function in them can be varied and the unit changed no Python production file (`no run could be made: …`), and its question's `Runs:` line names the runs that were made (it named both when only the zero-value run was made). A chore of rejected and inconclusive tests fails, and its reason lists the inconclusive tests apart from the rejected ones. A held question now finds the file of a test from a JavaScript or TypeScript id (`src.pricing.total.test.ts::…`) and shows the test's own lines, not the first 40 lines of the file, which held no assertion: it read `(the source of this test was not found)` before. A file that is not Python is redacted whole before the test's lines are taken (L4-VER-050, L4-IMP-065).
- The guarded merge no longer logs `the open pull request … is not the unit's <forge>/…` on every merge. The ledger keeps a unit's pull request link with `<forge>` in place of the host (L4-OBS-002), and the merge compared it with the forge's link as plain text. It now compares both in the same form, as the sweeper does, so the line is logged only when the links differ. No merge decision changes (L4-OBS-002).
- Red reads the failures of JUnit 5, JUnit 4, Truth and Swift Testing as it reads those of pytest, Vitest and .NET. Before, a new test that failed with `org.opentest4j.AssertionFailedError` (JUnit 5), `org.junit.ComparisonFailure` (JUnit 4), a Truth fact (`expected: 2` / `but was : 3`) or `Expectation failed:` (Swift Testing) had a wrong or no failure kind, so a red step in such a project could not pass. These are now assertions. `UnsupportedOperationException`, the stub form that red's prompt names for Java and Kotlin, is the stub's not-implemented error, and a Swift Testing message that starts with `Caught error:` is another error. XCTest results from `swift test --xunit-output` carry no failure text, so red still cannot read their kind (runbook, section 11). The kinds of pytest, Vitest and .NET reports do not change (L4-IMP-002).

## 0.4.37 (2026-10-28)

### Fixed
- A test chore whose tests cite a criterion no longer fails every attempt in a project whose code is not Python. Both runs that check such tests (the zero-value run and the base run) vary Python files only, so in a TypeScript project neither was made and every added test was rejected with `none of the tests you added looks at the answer`, whatever the agent wrote, until the unit halted on `max_task_attempts`. When neither run can be made, the tests are now inconclusive with that reason: the chore is held with a harness question (`accept` replays it, `retry` runs the check again), and the verifier's minor finding for such a Python test says `inconclusive:` instead of that it passes against the zero values and on the base; the verifier's check takes only tests whose file is a Python file, so a TypeScript test keeps its `no proof` finding (L4-VER-050).

## 0.4.36 (2026-10-27)

### Fixed
- In step 1 of the verifier, a test module whose last change is a person's commit now runs at head, not at its base version, so a test the unit did not change that runs it (a wrapper around the package's test runner) no longer fails on the content the person replaced; it is listed as a person's line naming every commit that changed it. A support file (conftest, fixture, helper) a person changed last is still put back (L4-VER-038).

## 0.4.35 (2026-10-27)

### Added
- `l4 doctor --fix` and `--ci --fix` install the Chromium of the pinned Playwright into the shared browser cache when the e2e gate uses Playwright (ENV-007 now has a fix), so a repository needs no Chromium step of its own in the rendered workflow, which `l4 upgrade` would drop (L4-ADO-020).

### Fixed
- The delegate may cite a repository's own `.l4/` files (`config.yaml`, `gates/`, `plans/`): only a unit folder's `.l4/`, `.l4/vendor/`, `.l4/ci/`, `.l4/bin/`, `.l4-out/`, `questions.md` and `verification.md` are harness-written and discarded as `cites a harness-written file`. A plan had stopped for a person because two right answers cited the repository's gate scripts (`.l4/gates/test.sh:44`). The prompt is `delegate@5` and says which `.l4/` files are evidence (L4-DLG-005).

## 0.4.34 (2026-10-26)

### Fixed
- A delegate's `checked` reference resolves as a person reads it: a `path:line` quote of a sentence that wraps over lines now resolves when its quote, whitespace folded, starts within three lines of the named line, and a `spec:` reference by a bare file name (when one tracked file of the unit folder has it) or by the repository path the prompt shows (`openspec/changes/<unit>/design.md`) now resolves. A discarded reply's `delegate.result` records its entries' `ref` and `quote`, redacted, so the next discard can be read.

### Changed
- A delegate reply discarded only because a `checked` entry does not resolve is asked again once, within `delegate.max_attempts_per_question`, instead of escalating at once: `delegate.result{status: deferred, discarded}` and the next prompt (`delegate@4`) says why the previous reply was discarded and how a reference is written. Any other discard, and a second one, escalates as before.

## 0.4.33 (2026-10-26)

### Fixed
- A person's commit to a test file on the unit branch, the way L4-IMP-081 names for a test a fix chore may not change, now clears the verifier's `a pre-existing test fails on the unit's code` blocker even when a harness step changed the file before: step 1 reads the last commit of `base..head` that changed the file, and when it is a person's the test is a person's line, not a blocker. The line names every commit that changed the file, the harness's included, and a harness commit after the person's keeps the blocker (L4-VER-038). Step 1 also finds the file of a Go test (the `*_test.go` file of its package that declares the function, the package found from the `module` line of its `go.mod`), so this and the `task.unfrozen` and `[test-infra]` allowances work for Go tests.

## 0.4.32 (2026-10-25)

### Fixed
- The post-merge check of a delivery plan and the gate dry run of `l4 yolo check` empty the tool caches before each gate, so a Vite 5 / Vitest 5 project's test gate loads its config and writes its report there too (a plan had stopped `postcheck_failed` with `report missing`): both runners built their gate sandbox without the reset that the implementer's and the verifier's gates already had, so after a fresh `pnpm install` `node_modules` was read-only with no writable `.vite-temp` and no `.vitest-cache`. They also pass the tracked environment paths, so a `node_modules` that git tracks is source there as well (L4-SEC-035, L4-YOLO-009).

## 0.4.31 (2026-10-25)

### Fixed
- A Vitest 5 test gate no longer fails one test file per run, and the agent steps no longer report Vitest's cache as a violation: `node_modules/.vitest-cache`, Vitest 5's module cache (on by default, read back in later runs), is emptied before every gate and writable like `.vite` (a tmpfs under bwrap), so its `mkdir` under a read-only `node_modules` no longer fails a file at file level and drops it from the baseline; the environment manifest leaves it out, so an agent step that runs Vitest causes no `guard.violation` (rule `environment`) and no rebuild of `node_modules` (L4-SEC-035).

## 0.4.30 (2026-10-25)

### Fixed
- A scratch cache that Go made read-only no longer stops the next agent step: Go extracts every module it downloads into `GOMODCACHE` with read-only directories, which the removal of the step's scratch left behind without a word, and the next step then failed with `FileExistsError` on the scratch directory. One helper, `remove_tree`, makes the read-only directories writable first (and a directory a test suite left unreadable, mode 0o000, readable), only inside the removed tree and never through a symlink, and now empties the agent's temp directory and scratch caches, a gate's scratch caches, the verifier's caches and the result alias; a removal that still fails stops the run at the start of a step, naming the path, and is a warning at the end (L4-SEC-039).
- `l4 retry` names the stopped plan that holds the unit and starts no wasted run: after a retry it looks up the plans that list the unit, as `l4 yolo status` does, and when one is `stopped` it prints `plan <id> is stopped (<reason>): the unit runs again after: l4 yolo resume <id> --reason TEXT` instead of starting a run that would find the unit held, end with `nothing to do` and count against the plan's `max_runs`. The exit code stays 0; a plan in another status, or plans that cannot be read, change nothing (L4-OPS-002).

### Changed
- The skill warns spec authors about scenarios the zero-value check cannot prove: `references/spec.md` gains the rule **unchanged behaviour** (a scenario that already holds at the base is proven only when zeroing the public functions its tests import makes one fail by assertion, so test a public module-level function, leave code nested in a factory such as `create_app()` to existing tests and the design's failure cases, and keep the logic a test checks in a project module), and its word cap goes from 450 to 530 (L4-ADO-014, L4-IMP-002).

## 0.4.29 (2026-10-24)

### Fixed
- A test gate can load a Vite configuration again: `node_modules/.vite-temp`, where Vite 5 and later bundle a TypeScript config and tolerate only `EACCES`, is emptied before every gate and writable like `.vite` (a tmpfs under bwrap), and the environment manifest leaves it out (L4-SEC-035).

## 0.4.28 (2026-10-24)

### Added
- **OpenCode 2 as an opt-in adapter (experimental, not yet checked against a live run)** (L4-OCV-001, L4-OCV-003 to L4-OCV-011). An `opencode` profile with `options.cli_major: 2` runs `opencode2` (`@opencode/cli`); the default is 1 and the harness never switches by itself. Every v2 call carries `--standalone`, gets a private state directory and sees EOF on stdin. The configuration is the native v2 shape with the same effective rules, and the status comes from the exit code, the `error` event, the step bound and the outcome of `opencode2 session export`, not from a final `step_finish`. v2 errors, limits, denials and `auth list --format json` are read from their v2 shapes, and a leaked leading `</think>` is stripped from a reply. Every v2 fact that no run with a real key has seen sits on a named, conservative fallback (L4-OCV-013), and no live run has checked the adapter yet (design E8), so it is announced as `agent.experimental`. Every v2 call reads only a configuration the harness made, and the export never lowers the usage the stream reported. A v2 profile does not serve the delegate: it is a load error in `roles.delegate` (L4-OCV-014). Runbook 10.9 says how to try it; use a runner user that no v1 profile shares.
- **`opencode2` provisioning** (L4-OCV-002). The catalog pins `@opencode/cli 2.0.32`; `l4 doctor --fix` and `l4 doctor --ci --fix` install it, only when a `cli_major: 2` profile is in a role chain, into its own prefix `$L4_HOME/npm-opencode2` and link only `opencode2`, so `opencode` stays v1. A v1 binary at `opencode2` is refused by name.
- **`ci.cli_versions: opencode2` and PRQ-20.** `ci.cli_versions` accepts the key `opencode2` with a version of major 2 only, and the exact pin and doctor ENV-015 apply to it. `prereqs.sh` PRQ-20 installs the pinned OpenCode 2 for the runner user (`--with-opencode2`, off by default).
- **Step bounds for OpenCode 2** (L4-OCV-006). `options.steps.judge` (default 3, allowed 2 to 20) and `options.steps.implement` (default 200, allowed 10 to 2000) set `agents.build.steps`. A run that reaches its bound is never `ok`. `options.steps` on a `cli_major: 1` profile is a load error.

### Changed
- **The judge sees the unit's answered questions** (L4-VER-065, L4-VER-066, `judge@13`). Every judge prompt (the whole diff, each part, each follow-up) carries one `<l4:data kind="answer">` block per answered `technical`, `product` or `ambiguous` question of the unit and its fix units: the implementer's title and options marked unverified, and the answer, redacted and cut, at most 12,000 characters together and charged to the judge's context budget before the spec text. The judge judges a criterion as an answer narrowed it and names the answer's id, and an input an answer settles is no `spec_gap`; an answer never passes a criterion without evidence or outweighs a failing gate. The `verify.judge` event lists the answers shown as `answers: [[id, answer_sha256], ...]`.
- The agent-CLI cache key moves once: the catalog gains `agent:opencode2` and `npm:opencode2`, so the first run after the upgrade installs the agent CLIs again.
- The reason a v1 profile gives for an OpenCode 2 binary now ends `or set options.cli_major: 2 to run OpenCode 2 (experimental)`, where it ended `OpenCode 2 support comes in a later L4 release` (L4-OCG-002). The probe, doctor ENV-004 and LIVE-005 check a profile's own binary and major, and LIVE-005 compares a version only with the recorded versions of the same major (L4-OCV-012).

### Fixed
- `l4 probe`'s OpenCode `auth` step runs `opencode auth list` with an empty config directory and the disable switches, so a config or plugin an agent run wrote under `~/.config/opencode` is never loaded outside the sandbox.

## 0.4.27 (2026-10-23)

### Added
- **GitHub Copilot CLI as an agent (experimental)** (L4-FAC-013 to L4-FAC-022). The adapter `copilot-cli` (binary `copilot`) has four modes: implementer, tool-less judge (also the clarifier and the plan-readiness review), read-only delegate, and the hello of `l4 probe`. Each run starts from a private `COPILOT_HOME` with repository instructions, built-in MCP servers, hooks and memory off; the one credential is `COPILOT_GITHUB_TOKEN`, a fine-grained PAT of a person with Copilot Requests, billed to that person's plan (runbook 10.8). It is in no default role chain and no `l4 init` output names it. The harness stops a run at the first HTTP 429 (`rate_limited`) and after 20 denied tool calls in a row (`permission_blocked`), and records tokens and AI credits, never dollars. A profile with no model runs `--model auto` and is routed. One GitHub-routed live recording on a Copilot Free account backs it (L4-FAC-022, `docs/live/copilot-cli`): on that plan only `auto` runs, and a pinned model that the account does not offer ends as `error` with `model_mismatch: copilot-cli could not set <id> (the account does not offer it: pin a model it offers, or use auto)` (L4-FAC-017), so a judge chain moves on to the next independent judge.
- **The Copilot CLI pin and install** (L4-PRV-047, L4-OCG-006). The catalog pins `copilot 1.0.102`; `l4 doctor --fix` and `l4 doctor --ci --fix` install it from the release tarball after a check of the sha256 digest the harness holds, then warm the package cache; a Copilot CLI of another major is refused. The simulation scenario `happy-copilot-judge` replays a Copilot judge through the real adapter.
- **`prereqs.sh` PRQ-22** installs the pinned Copilot CLI for the runner user (`--with-copilot`, off by default).

### Changed
- The agent-CLI cache key moves once: the catalog gains `agent:copilot-cli`, so the first run after the upgrade installs the agent CLIs again.
- Every rule that treated a profile as routed because its adapter was `kiro-cli` (the vendor of a profile, the config validator, the judge seat, the delegate's independence rules) now reads the routed adapters (`kiro-cli` and `copilot-cli`). Nothing changes for a Kiro profile.

## 0.4.26 (2026-10-22)

### Fixed
- The replay guard of a held step could write outside the work tree on Linux (L4-IMP-086). When a path that is not part of the saved patch had to go back to the step base, the guard ran `git checkout <base> -- <path>`; git resolves that path by name, so a process that swapped a folder of the path for a link at that moment made git write the base file through the link. The guard now writes the base entry through the folder's file descriptor, as it writes the patch's own paths (a regular file streamed from the base blob with its executable bit, a link with its target), and sets the index entry with `git update-index --cacheinfo`; it runs no git command that writes the work tree by path. A base entry that is neither a file nor a link (a submodule) fails the step as an attempt. The security test that races a folder against a link failed about one run in six on Linux before, and passes 30 runs in a row after.
- Test-only: the yolo test helper commits with a fixed git identity, and a plan-check test is skipped where the pinned OpenSpec is not installed, so the nightly CI's environment failures are gone.

## 0.4.25 (2026-10-22)

### Added
- **Existing tests the reviewed text names** (L4-IMP-082). A red step may change in place an existing Python test that the task's reviewed text names, by `path::name` (or `path::Class::name`) or by a test name that exactly one test file defines, or that the text of a criterion the task cites on its `_Requirements:_` line names (only from an activated plan or a unit folder that is the same on the base branch). At most 5 per task. Red still may not delete, rebind or break one, and still writes the new tests the criteria need. The red prompt lists them under `# Existing tests this task changes in place` (red template 13). The harness records them as `tests.superseded{reason: "named_by_task", source}` (the stale-test event now carries `reason: "stale"`), and the verifier lists them as `<id> (named by the task text, <source>)`. Before, red could not change such a test and the task waited for a person's answer.
- **A helper module the task line names** (L4-IMP-083). A Python helper that red adds, that defines no test and that the task line names by path is opened for that task's green step, which fills it in: its module-level names and signatures stay, it gains no test and it does not patch the unit's modules (`drops <name>`, `changes the signature of <name>`, `adds a test <name>`).
- **GitLab: which project jobs run on the harness's pipelines** (L4-INS-007 to L4-INS-009, L4-INS-011). `l4 setup gitlab` evaluates the project's `rules`, `only`, `except`, `when` and `workflow: rules` for the harness's schedule and api pipelines on the base branch and the push pipeline of a unit branch; its `.gitlab-ci.yml` row lists the jobs that run, skip or cannot be decided. It warns when GitLab would refuse such a pipeline as empty (`WARN pipeline`, `WARN workflow:rules`: the l4 job is in `.post`, and a pipeline with only `.pre`/`.post` jobs is refused) and when a project job that deploys would start by itself on one (`WARN deploy jobs`). `l4 doctor` has the same checks as CI-007 and CI-008 (warn). `l4 init --ci gitlab` adds the echo-only job `l4-pipeline-anchor` when the file it edits would give an empty pipeline.
- **GitLab: the bot's level follows the merge policy** (L4-INS-010). With `forge.merge_policy: auto` and a base branch that accepts merges from Maintainers only, `l4 setup gitlab` creates the bot token as a Maintainer (an `INFO` row says so) and warns about a kept token whose level cannot merge (`l4 setup gitlab --rotate --revoke-old`: GitLab does not change a bot's role). A base branch that accepts merges from no one is a `WARN`.

### Changed
- The clarifier reads a function's signature before it suggests a call, and never suggests deleting, skipping or renaming what the specification keeps; it gets the definition lines of up to three functions the question calls (L4-CLR-007, clarifier prompt version 6).

### Fixed
- The zero-value run zeroes the stubs that HEAD already holds (an earlier task's) together with the stubs red added (L4-IMP-084). Before, a criterion whose tests reached an earlier task's stub could be rejected as vacuous.
- A vacuous criterion whose tests only error in the zero-value run is told what to stub (L4-IMP-085): a module the tests cannot import, a `NotImplementedError` at `<path>:<line>` that is not a plain stub, or a missing attribute.

## 0.4.24 (2026-10-22)

### Fixed
- A CI/CD variable named `CI_JOB_TOKEN` (of the project, its group or the instance) made every `l4 run` cancel itself on GitLab (L4-CLI-003). Release 0.4.23 handled a session leader that is gone at the start; on the runner that showed the symptom, the actual cause was a group CI/CD variable named `CI_JOB_TOKEN`: it overrides the predefined variable, the job API answered 401 to its value, and the watchdog read "token refused" as "the job is over" about 0.3 s after the start. Now the job API is asked with the job token in `CI_REPOSITORY_URL` when that differs from `CI_JOB_TOKEN` (one WARNING, no token value anywhere), a first "token refused" while the job's session runs is not a cancel (one WARNING; only the session check watches, and a later refusal still stops the run), and the token in `CI_REPOSITORY_URL` is redacted like `CI_JOB_TOKEN`.
- `l4 doctor` has two new warn rows: CI-005 (inside GitLab CI, `CI_JOB_TOKEN` is overridden by a CI/CD variable) and CI-006 (the rendered `.l4/ci/l4.gitlab-ci.yml` names another `L4_BASE_BRANCH` than `forge.base_branch`: run `l4 upgrade`).
- `l4 setup gitlab` warns, in one `variables` row each, for a variable of the project, of any ancestor group or of the instance named `CI_JOB_TOKEN`, `CI_API_V4_URL`, `CI_REPOSITORY_URL`, `CI_JOB_ID` or `CI_SERVER_URL` (names and scopes, never values). A re-run still reactivates a schedule the owner paused, but pauses it again when the `--watch`ed check pipeline fails, and the FAIL row says so.
- `l4 upgrade --harness-ref vX.Y.Z` on a fetched adoption also writes `harness.version: X.Y.Z` (it left the old version next to the new commit); any other ref, or `--harness-commit`, leaves the version alone.

## 0.4.23 (2026-10-21)

### Fixed
- `l4 run` cancelled itself at once on a GitLab shell runner whose job session leader exits at the start (L4-CLI-003): the watchdog found the leader gone and stopped the run one second after it began, although the job API said the job was running. A leader that is already gone at the start is now dropped from the watch for that run (one WARNING says so; the job API stays, and `cancel.check()` no longer asks the leader), while a leader that exists at the start and disappears later still stops the run. The start line says `no job session check: its leader was gone at the start`, and the stop message names the check that fired (`the job API says <status or token refused>` or `its session leader <sid> is gone`).

## 0.4.22 (2026-10-21)

### Added
- **The delegate** (L4-DLG-001 to L4-DLG-027). A strong model that the project configures answers the questions of units
  in scope inside the harness's own run. It is off unless the base branch says `delegate.enabled: true`, and `delegate:`
  and `roles.delegate` are read from the base branch only. To turn it on, set `delegate.enabled: true` and name
  profiles in `roles.delegate`; `l4 init` writes the block commented out, with the reference profiles. With
  `delegate.scope: yolo` (default) a unit is in scope when it is the current unit of an active or waiting plan, or its
  fix unit; `scope: all` adds units in no plan file while no plan is active. It runs after the clarifier at the end of
  the run that parks the unit, and in a later run through the planner action `delegate`; it asks once per question,
  oldest first, in the kinds of `delegate.kinds`. The reference configuration has the profiles `delegate-opus`
  (`claude-opus-5-5`), `delegate-sol` (`gpt-6.1-sol`, `reasoning_effort: high`), `delegate-sonnet` (`claude-sonnet-5`;
  a verdict question needs a model that is neither the judges' nor the implementers'), `delegate-oc` (opencode) and
  `delegate-kiro` (kiro-cli), and `roles.delegate` is optional (L4-AVL-010).
- Four adapters serve the delegate: `claude-code`, `codex`, `opencode` and `kiro-cli` (L4-DLG-015 to L4-DLG-017). Each
  runs read-only, with no tool server and no forge or CI token, in a detached worktree of the pushed unit head that the
  sandbox mounts read-only (`SandboxSpec.worktree_read_only`). Claude Code uses `--permission-mode plan` with
  `Read,Grep,Glob`, Codex `-s read-only --ephemeral`; opencode gets a read-only mode L4 builds from an allow-list (read,
  glob and grep in the worktree, nested instruction files removed from the checkout, `options.tools` ignored); kiro-cli
  gets a harness agent with read, glob and grep. opencode and kiro-cli reply in their last message.
- Free models answer only what a later step checks. `profiles.<p>.options.delegate_kinds` narrows the question kinds a
  delegate profile answers (it never widens `delegate.kinds`; doctor `DLG-001` fails on an unknown kind), and a
  free-tier model (an OpenCode Zen id `opencode/...` or an id ending `:free`) answers `technical` and `harness`
  questions only (L4-DLG-019).
- The option can be found while it is off. `l4 questions`, `l4 status --unit`, `l4 yolo status` and the sticky note of a
  waiting unit in scope print one `Hint:` line (the first three print none for a question the delegate has already
  escalated for its current raise), `l4 init` writes the delegate as a commented-out block, and `DLG-001`
  names how to turn it on (L4-DLG-021, L4-DLG-022).
- The prompt `delegate@3` holds the question and its evidence as `<l4:data>` blocks, redacted before any cut. The reply
  is one `l4/delegate-result@1`; the harness keeps it only when the decision fits the kind, every `checked` claim
  resolves at the unit head, and the text passes the checks of `l4 questions answer`. A reply is also discarded with
  more than 20 `checked` entries or a `ref` over 300, `quote` or `claim` over 600 characters, or when it cites
  `questions.md`, `verification.md` or `.l4/` (no evidence); a discarded reply records the decision it would have made
  (not its text) and says on the `Escalated by:` line that it was discarded and why, and an `escalate` reply records
  only its redacted refs. A decided question stays decided: a newer harness does not ask it again, only a new raise
  does.
- A kept answer is written by the edit core of `l4 questions` with the field line `Answered by: the delegate (<model>
  via <cli>)`, committed with `By: delegate (...)`, `Via: l4 delegate` and `[skip ci]`, pushed, and followed by one run
  on the base branch that reads it, in a plan and outside one. What it cannot check, it escalates: `Escalated by:`, the
  label `l4:needs-person`, a sticky section `Needs a person (the delegate escalated)`, and a plan that waits with
  `unit_awaiting_human` and starts no run.
- `delegate.independence` (`model` by default: the delegate is not a model or profile that asked or judged the question;
  `profile` vetoes the name only; for a verdict question the implementer profiles and their models are askers too, so
  the model that wrote the code never overturns the judge's dispute of it, and the reference configuration needs a
  third model in `roles.delegate` or its verdict questions escalate; the models the implementer's steps reported count
  as askers' too, so an alias such as `opus` cannot hide the served model, and `DLG-002` warns about an alias),
  `delegate.unfreeze` (default `false`: an answer that would unfreeze a frozen test file escalates; `true` lets the
  delegate accept the clarifier's suggestion for it), and the bounds `max_attempts_per_question` (2),
  `max_answers_per_task` (3), `max_questions_per_run` (5), `max_cost_usd_per_answer` (3.0), `max_cost_usd_per_unit`
  (15.0), `plan_cost_share` (0.25) and `timeout` (15m). The ledger events `delegate.asked` and `delegate.result`; the
  asker (`profile`, `model`, `judges`) on `question.raised`.
- Doctor `DLG-001` (error: the chain, `delegate.kinds`, `options.delegate_kinds`, the limits, an independent delegate
  profile for every implementer and judge profile, and, for each kind of `delegate.kinds`, at least one profile that is
  allowed the kind and independent of every asker of it)
  and `DLG-002` (warn: a delegate profile is usable now; which profiles would answer verdict questions, an `opencode`
  one flagged), both silent while the delegate is off but for the line that names how to turn it on; the delegate chain
  is part of `LIVE-002`.
- `l4 status --unit` prints a `Delegate:` line per decided question; `l4 status` gives the REASON `Q-NNN needs a person
  (the delegate escalated)`; `l4 yolo status` prints `delegate: <n> answered, <m> escalated` and the delegate's cost
  against its share of the plan's cost. All have `--json` fields. `verification.md`, the judge's view, the PR note and
  `l4 yolo report` label the delegate's decisions `delegate_override`.
- Docs: SPEC 3.2, 9.1 and 23.25, the runbook's procedure "The delegate answered or escalated" (with "To turn the
  delegate on"), a section "The delegate" in the delivery-plans and yolo-mode pages, and the delegate in the quickstart,
  the control-loop page and the skill's adopt, operate and plan references.

### Changed
- The delegate follows the rules of 0.4.21. A reject of a finding that cites no criterion needs a `WHEN ... THEN ...`
  that states the behaviour the fix must give, never the judge's suggested fix; a reject of a judge-view hold is
  discarded; an accept of a cap-only criterion cites the test's lines; split and cap-only questions follow the same
  rules (L4-DLG-023, L4-DLG-024).
- `delegate.unfreeze` opens frozen test files only: never a test-support file, and nothing in a fix task. A fix chore's
  answer that changes a test or support file, and a CI failure, go to a person (L4-DLG-014, L4-DLG-025). A run whose
  pass answered a question starts one next run even where the continuation rule starts none (L4-DLG-026).
- The label `l4:needs-person` (created by `l4 setup github`) marks a PR whose open question the delegate escalated; it
  goes when no escalated question of the unit is open.
- The status lines name the delegate's answers and escalations (`l4 status`, `l4 status --unit`, `l4 yolo status`).
  `verification.md` titles the verdict answers `## Answers to verdict questions`, and the PR body names the delegate's
  answers (L4-DLG-027).
- A plan that waits with `unit_awaiting_human` names the escalated questions in its detail. A run in which the delegate
  wrote an answer for a unit of the plan starts the next run once, also when the plan step waited.
- The planner may name a new action, `delegate`, for a unit in scope whose open question the delegate has not decided.
  No lifecycle edge is new: the unit moves in the run that reads the answer.
- `l4 upgrade --harness-ref` with a commit sha says to use `--harness-commit`. The line count of the re-render note
  counts a removed line too (a replaced line counts once), so a re-render that only removed a line no longer says
  `0 lines changed`.

### Fixed
- Every answer in `questions.md` now has its real actor, of every kind. Before, a verdict answer an agent gave was
  recorded `by: human`, and only a harness question could be an agent's. `question.answered` and `human.verdict` carry
  `by: human | agent | clarifier | delegate` (with `marker`, `profile` and `model`), the implementer's answer blocks carry
  the same `by`, and a `By: delegate` line that no ledger record backs counts as an agent's. A verdict that is not a
  person's is no S1 calibration label (`human:verdict` is made only from `by: human`). A fix unit's answers carry their
  real actor too: the delegate's reaches the fix unit's implementer as `by="delegate"`.
- Idle plan runs are free. A run of the dispatched unit that made no agent call, ran no gate and changed no phase but into
  `awaiting_human` or `clarifying` is recorded `plan.run_idle`, does not count against `max_runs` and starts no next run,
  so a plan with a waiting unit no longer spends its runs (`l4 yolo status` shows `runs: 3 of 10 (9 idle, not counted)`).
  A paid clarifier or System One call (`budget.cost`) is work, so a run that made one is not idle; so is a clarifier call
  that was made.
- The delegate's deferrals are bounded: a deferral for lack of time (`reason: soft_deadline`) made no call and counts
  as no attempt, so time-budget pressure never escalates a question as `delegate attempts used`; a question deferred
  that way three times in a row stops asking for the next run and waits for the next scheduled or pushed run, so
  deferrals never chain runs without bound. `DLG-001` fails when `ci.time_budget` is known and `delegate.timeout` plus
  `ci.soft_deadline_margin` does not fit in it.
- Independence fails safe: under `delegate.independence: model` a delegate profile with no `model`, a kiro-cli `auto`
  profile, or an asker whose model is unknown vetoes; models are compared after their provider prefix
  (`openrouter/anthropic/claude-opus-5-5` is `claude-opus-5-5`), and the model that actually served the call is checked
  against the askers too (L4-DLG-018).
- A `checked` entry of the delegate cannot cite `questions.md`, `verification.md` or `.l4/`, and its quote needs 12
  characters. The cost of a delegate call that hit a limit is recorded, a Kiro delegate call's credits are recorded
  (L4-DLG-020), and a pass killed mid-call no longer leaves a registered worktree that stops the next one. The
  `Escalated by:` line neutralises HTML comments. A person's `--replace` of the delegate's answer drops the
  `Answered by:` line. `delegate.unfreeze` is read from the base branch where a green step decides. An agent's answer
  under `clarifier.answer_by_agents` still unfreezes a frozen test or opens gate configuration, as on 0.4.18 (the
  delegate's never does, except an accepted suggestion under `delegate.unfreeze: true`).

## 0.4.21 (2026-10-21)

### Added
- The implementer's contract states `verifier.max_criteria_per_test` with its value (L4-VER-052): a test that traces
  more than that many of the unit's criteria counts for none of them, so give each test one behaviour and at most that
  many ids, and put a criterion that many tests touch only on the tests that assert it directly (`contract@13`). The red
  phase adds that a task line citing K criteria needs at least ⌈K/N⌉ tests (`red@12`).
- A passing test over the cap that has a proof for a criterion counts for it when the judge passed the criterion and
  has a `test_adequacy` entry that marks the test adequate for it, and the test traces at most `min(M // 2, 3 × cap)` of
  the unit's M criteria (L4-VER-054). The judge's matrix lists such tests and asks for the entry (`judge@12`); a `test`
  evidence item in the pass is not enough, and a part of a diff that never saw the test names nothing.
  `verification.md` labels a counted one `over the per-test cap: traces N criteria, named by the judge`. A test that
  traces everything is still no evidence.

### Changed
- A red step whose new test traces more than `verifier.max_criteria_per_test` of the unit's criteria fails its attempt
  before the discrimination runs, with `too many criteria on one test: <test> traces N of this unit's criteria (…),
  more than verifier.max_criteria_per_test (3), so the verifier counts it for none of them: split it into tests that
  each assert one behaviour and carry at most 3 ids, …` (L4-VER-052). A test chore's added test is checked the same
  way. Before, such a test was written, frozen, and ignored at verification, so its criteria became questions for a
  person. Tests that existed before the step are not checked.
- The zero-answer advice of the red phase proposes a test only when it has room under the cap, shows its whole id list
  in the gate's own form, and otherwise says to write a new test (L4-VER-053).
- A diff judged in parts no longer asks a person about a criterion only because its code lay in two parts
  (L4-VER-056, L4-VER-057). When the parts' merged verdict for a covered criterion is `insufficient_evidence` and its
  files (its tracing tests, the code they import, the files of its tasks' commits and the files the parts cited) lie
  in two or more parts, the judge step makes a follow-up call that shows those files together, whole, within one
  part's characters, and its verdict replaces `insufficient_evidence`. Split criteria share a call when their files
  fit together; a round makes at most as many follow-up calls as parts. A criterion any part failed, passed or
  called `not_verifiable` is never judged again, and a follow-up with no usable answer keeps the parts' verdict.
- Each part prompt asks a part that shows only some of a criterion's code to cite the files it holds. The judge
  template is `judge@12`.
- A rejected spec-gap finding whose criterion the unit does not have, answered without a `WHEN … THEN …`, is listed as
  not converted (`answer again with a scenario`) instead of becoming a task from the judge's suggested fix
  (L4-VER-059). When no other finding converts, the unit escalates with `no finding of this round can be converted into
  a fix task`; replace the answer with one that ends with a scenario (`l4 questions answer … --replace`), or give the
  fix as a behaviour feedback item, then `l4 retry`.
- Verdict questions say how to set the check a fix must pass: end the reason with `WHEN … THEN …`; without one the fix
  is checked against the criterion as it is written; for a spec gap, the suggested fix describes what the code does now
  and a reject does not use it (L4-VER-060).
- `l4 questions answer` refuses a `reject` with no reason on a spec gap's question (exit 2): add a reason, or a `WHEN …
  THEN …` (L4-VER-060). A reason alone is accepted: the fix is checked against the cited criterion and the red step
  writes a failing test for the reason, and the gap may be asked again, since no scenario is added. A bare reject of a
  spec gap that reached the file by hand is not converted either (`rejected with no reason`, L4-VER-059).
- A reason's scenario is its last `WHEN … THEN …`: a reason may quote the criterion's and then give its own.
- In CI, the gates run with the CI's identity variables (L4-SEC-040). When `CI`, `GITHUB_ACTIONS` or `GITLAB_CI` is
  `true`, every gate (setup, build, lint, typecheck, test, e2e, a `repository-ci:` step) also gets `CI`,
  `GITHUB_ACTIONS` and `GITLAB_CI` as the job has them, when the whole value is a short word. Agents do not, and no
  colour variable is passed. Tools now behave in the gates as in your CI: typer and rich colour their output, pytest
  stops truncating assertions, jest and vitest write no new snapshot, pnpm installs with a frozen lock file. A test
  that only your CI failed now fails before the hand-off. `run.started` records `gate_env_ci`. Outside CI nothing
  changes; `CI=true l4 run` opts in and logs one INFO line.
- When the gates get those variables, the implementer's prompt names them, gives the command to reproduce a CI-only
  failure, and says that a test of a command's help or output must not depend on colour (L4-IMP-080).
- A CI job that fails again on a later hand-off, with no commit since its earlier failure that changed a project file,
  no longer gets another fix unit (L4-OPS-023). Before, a fix unit whose only task changed nothing (the gates could
  not show the failure, and a fix task may not change the unit's tests) passed its round and was handed off with the
  same failure, until `max_fix_rounds`. Now the round escalates with the new reason `ci_not_fixed`: `l4 status` and the
  sticky note show the CI excerpt and the way on (your own commit, or `l4 feedback add`, then `l4 retry`; `l4 retry`
  alone hands the unit off as it is). A round with a feedback item to take, or a person's reject that converts into a
  fix task, still makes its fix unit. A CI blocker of a job that failed before starts with `again:`.
- A fix task that answers a red CI job is told that the gates may not show the failure and to say so in
  `notes_for_verifier` (L4-IMP-081). A test or test-support file that a fix step changed is put back as before, and the
  note and the step's question now say that a person must commit that change, instead of asking to unfreeze it.

### Fixed
- A criterion that the judge passed and that only the per-test cap left uncovered says so: its reason reads
  `uncovered: the judge passed it, and only the per-test cap left it uncovered: <test> traces N criteria, …`, and its
  question names the fix (`accept` if the test checks it, or `reject: give it its own test of at most N ids`, which
  fails the criterion and spends a fix round) (L4-VER-055). Before, it read
  `uncovered: no adequate discriminating test traces it`.
- A round resumed at aggregation keeps its tests' labels (`not applicable: no project code`, `accepted by Q-NNN: …`):
  the stored trace's `note` was dropped when it was read back.
- The question about a criterion whose evidence was split over parts of a long diff says what happened (L4-VER-058): its
  `Why:` line and `verification.md` end with `its evidence was split over parts 1 and 2 of the diff: …` and what the
  follow-up call answered, or why none was made; so does the reason of a split criterion that only the per-test cap
  left uncovered. Before, the reason was only `the judge answered insufficient_evidence`, the same as for a criterion
  with no evidence. `verification.md` lists each follow-up call; `verdict.json` records `judge_followups` and `judge_split`.
- A fix task no longer pins the judge's suggested fix when a person rejected the finding without a `WHEN … THEN …` of
  their own (L4-VER-059). For a spec gap the judge writes its suggestion as the behaviour the code shows now, so a reject
  such as "the criterion requires exit 1; the code exits 2" made a fix unit whose added scenario said exit 2 next to
  the criterion that says exit 1, and the task could not pass both. The task now cites the criterion and is checked
  against its scenarios; only a person's `WHEN … THEN …` adds a scenario. A spec gap that no person rejected (a minor
  with `verifier.fix_minor_findings`) still pins the suggestion.
- A fix task quotes every reject it consumes. When a person rejected both a finding and its criterion, the criterion's
  reason and its `WHEN … THEN …` were consumed but appeared nowhere in the fix unit (L4-VER-059).
- The red and green prompts carry the rule the single prompt already had: when a task begins with a decision by a
  human (`Decided by … in Q-…`), the decision is binding, so red's tests assert what it describes and green's change
  does it (L4-VER-059). Templates `red@12` (no second bump in this release) and `green@6`.
- The evidence of a red project job is the failing step's output (L4-VER-061, L4-VER-062, L4-VER-063). On GitHub it
  was the last 40 lines of the job log, which end with the post steps (`Post job cleanup.`, cache and checkout
  cleanup, the runner's Node.js warnings), so a fix unit could be given none of the failure. Now the forge reads the
  job's steps, takes the section of the first `##[error]` line (its `Run …` header, its last 40 lines, its `FAILED`
  lines, assertion lines and counts before them), drops the runner's timestamps, and records the step's name as
  `ci.failed.jobs[].failed_step`. On GitLab the excerpt ends with the job's script and the `ERROR: Job failed` line:
  `after_script` and the cache upload no longer push the error out.
- The `repository CI failed` blocker names the failing step (``job `ci.yml / tests` failed in step `tests` …``) and
  puts the failing tests in its first 600 characters (`Failed: …`, the failing tests first, then the counts) before
  `Log ends: …` (L4-VER-064). `##[error]` reads `Error:` (the excerpt ends with `Error: Process completed with exit code 1.`), so a fix spec no longer shows `##(error)`. A GitHub job's
  `ci.step` says that its step is named, not re-run, instead of `no failing step in the log`.
- `l4 questions show` and `accept` with `--unit <fix unit>` find the fix unit's questions on its parent's branch
  instead of failing with `has no branch on origin`.


## 0.4.20 (2026-10-20)

### Added
- Kiro CLI is pinned: `kiro-cli 2.32.0`. On Linux the harness installs it from the versioned archive
  (`https://prod.download.cli.kiro.dev/stable/2.32.0/…`, gnu or musl as Kiro's installer chooses), checks its sha256
  against a table in the harness, and puts `kiro-cli`, `kiro-cli-chat` and `kiro-cli-term` into `~/.local/bin`. It
  never installs `latest` and runs no installer script. On macOS it installs nothing: `l4 doctor` names the pinned
  disk image and its sha256 (L4-PRV-042).
- `ci.cli_versions` holds an agent CLI at another version of the same major, for example `{kiro-cli: "2.28.0"}`.
  Provisioning, the probe and doctor use it, and it changes the agent-CLI cache key. A Kiro version is installed only
  when the harness holds its digests (2.27.1, 2.28.0, 2.32.0). Move your harness pin to 0.4.20 before you add the key
  (L4-PRV-045).
- Doctor `ENV-015` (warn) reports each agent CLI's version against its pin, and names an override. The probe's
  `binary` step records `pin` and `pin_source`; its line reads `binary 2.33.0 (pinned 2.32.0)` on a drift, and
  `availability.selected` records `binary_pinned` then (L4-PRV-046).
- `prereqs.sh` PRQ-21 turns the background update off for the runner user's Claude Code (`DISABLE_AUTOUPDATER` in
  `~/.claude/settings.json`) and Kiro (`app.disableAutoupdates` in `~/.kiro/settings/cli.json`), merging one key into
  each file with `jq` and running no agent CLI (L4-PRV-044).
- Doctor `CFG-012` checks the soft deadline against the step floor (L4-IMP-076, L4-IMP-077). It is an error when a set
  `ci.time_budget` minus `ci.soft_deadline_margin` leaves less than 10 minutes, the smallest estimate of a step:
  `ci.time_budget 21m minus soft_deadline_margin 20m leaves 1 min, less than one step (10 min): set
  ci.time_budget: auto (the job timeout) or raise it`. It is a warning when a set `ci.time_budget` is shorter than the job's timeout
  (`CI_JOB_TIMEOUT`, `L4_JOB_TIMEOUT_MINUTES`, else the `timeout-minutes` of `.github/workflows/l4.yml`) by more than
  the margin.
- `run.started` records `job_budget_source`: `ci.time_budget`, `CI_JOB_TIMEOUT` or `L4_JOB_TIMEOUT_MINUTES`
  (L4-IMP-078).

### Changed
- In CI (`l4 doctor --ci --fix`) an agent CLI of another version than its pin is replaced by the pin, and the install
  must then report exactly the pin; before, a CLI at least the profile's `min_version` was kept. `l4 doctor --fix` on
  your own machine works as before: a CLI that meets `min_version` is kept (`ENV-015` now names both versions and the
  command), and one below it is installed at the pin. A Kiro CLI 3 on your machine is left alone, with the fix named
  (L4-PRV-043).
- A `kiro-cli` of another major than 2 is refused at the probe's `binary` step, by `ENV-004` and `LIVE-005` (an
  error), by `l4 doctor --fix` and by `prereqs.sh` PRQ-12: `kiro-cli 3.0.0 is Kiro CLI 3; L4 runs Kiro CLI 2: install
  kiro-cli 2.32.0 …` (L4-OCG-005).
- No agent CLI that L4 starts updates itself: Claude Code runs and probes get `DISABLE_AUTOUPDATER=1` and
  `DISABLE_UPDATES=1` (installers `DISABLE_AUTOUPDATER=1` only), every `codex exec` gets `-c
  check_for_update_on_startup=false`, and the implementer's private `KIRO_HOME` holds `app.disableAutoupdates`
  (L4-PRV-044).
- `prereqs.sh` PRQ-12 installs the pinned Kiro archive with the same digest check and no longer runs
  `kiro-cli update`. `KIRO_VERSION` is exact, not a floor (L4-PRV-043).
- Every agent-CLI cache key changes once with this release (the catalog now pins Kiro), and every cached probe
  result is probed again once (its identity now holds the pin).
- `l4 run` refuses a set `ci.time_budget` that leaves less than 10 minutes after the margin: it prints the text above
  and exits 2 before the plan step and any unit (L4-IMP-076). Since 0.4.19 checks the deadline inside a unit, such a
  budget started each run's first step with seconds left and halted the unit with `deadline_repeated` after two runs.
  In the generated workflows `l4 doctor --ci` fails first, so the job is red at the doctor step. Fix:
  `ci.time_budget: auto`, the job's own timeout. The configuration still loads, so `l4 status` and `l4 upgrade` work on it.
- `l4 run` logs one warning when a set `ci.time_budget` shortens the job by more than the margin (L4-IMP-077).
- `l4 upgrade` prints `error: …` and `warning: …` lines for these two cases after the files it changes, and still exits
  0 (L4-IMP-079).

### Fixed
- The `deadline_repeated` halt reason and the "no step fitted" warning name the fix of the budget's real source:
  `raise ci.time_budget (or set it to auto)` when the budget is `ci.time_budget`, `raise the job's timeout
  (CI_JOB_TIMEOUT)` on GitLab, and `raise timeout-minutes and L4_JOB_TIMEOUT_MINUTES` on GitHub. Before, the halt always named
  `timeout-minutes`, and the warning named both (L4-IMP-078).

## 0.4.19 (2026-10-20)

### Added
- A `kiro-cli` profile can be a judge, a clarifier and a plan-readiness reviewer (`roles.judges`, `roles.clarifier`,
  the `s1_judge` stand-in). It runs a tool-less harness agent (`tools: []`, no MCP server, no resources) from a private
  `KIRO_HOME` with `chat.disableInheritingDefaultResources`, in an empty folder, with the prompt on standard input and
  no trust flag (L4-KJD-001, L4-KJD-002). Its reply is the final text of the stream, sliced to one JSON object and
  validated, with the same repair as any judge (L4-KJD-003). A run that holds a tool call or a `runError`, started any
  part on an engine other than `v2`, or was served a model that contradicts a pinned one is never a verdict. The
  delegate role, when it ships, is not to take a `kiro-cli` profile.
- `auto` by default: a `kiro-cli` profile with no `model` passes `--model auto` in every mode. `auto` is routed: its
  possible vendors are the makers of the Active models of `kiro-cli chat --list-models --format json`, listed once in
  the `auth` step of `l4 probe` and joined with the built-in set (`anthropic`, `minimax`, `zhipu`), which is used
  alone when the listing fails. `l4 probe` names the set and its source. The served model is read from the CLI's
  session file (L4-KJD-012, L4-KJD-013, L4-KJD-015): an `auto` judge whose served model has the implementer's vendor
  loses its verdict as `model_mismatch`, a pinned model that Kiro could not set is a `model_mismatch`, and `routed
  (unverified)` is a new independence status (`kiro-auto routed: anthropic, minimax, zhipu (auto)`). For a pinned
  model the session file only detects a mismatch: it is the CLI's own selection, so a pinned Kiro judge stays
  `declared`.
- Doctor `CFG-011` (warn, never an error) describes each `kiro-cli` judge or clarifier profile, with the possible
  vendors of an `auto` profile and their source, and warns on `options.agent` and on a `min_version` below `2.32.0`
  (L4-KJD-009). A `vendor:` on an `auto` profile is noted as ignored. On a fresh runner, where doctor runs before any
  probe has recorded a listing, the line says `built-in (no listing recorded yet)`, not `built-in`.
- Judge and clarifier credits: `verify.judge.credits` and `budget.cost{credits, credits_source: kiro.stream, role}` for
  a Kiro call, summed over its calls and never added to dollars (L4-KJD-004).
- The simulation replays a judge's recorded stream through the real kiro-cli adapter (scenario `happy-kiro-judge`), and
  `tests/fixtures/recorded/kiro-cli/2.32.0/` holds the recorded shapes (L4-KJD-010).
- `l4 yolo go PLAN --reason TEXT [--accept-findings | --force] [--yes] [--json] [--no-push] [--local] [--wait DURATION]`
  takes a plan from a committed file to an active plan in one command. It runs preflight, push, check, review,
  findings, accept and activate over the existing commands, with their rules and leases, reads before each step
  whether it holds, and stops at the first step that cannot pass with one stop code (20 to 29, not members of the exit
  table) and one `Next:` line. It pushes the base branch only as a fast-forward and never forces. CI reviews are read
  from the plan ledger every 15 seconds up to `--wait`. `--json` prints one `l4/yolo-go@1` document. It is safe to run
  again, to interrupt and to run twice at once (a lost plan lease is read again, at most three times). A person types
  the plan id before the activation (`--yes` skips it; without a terminal and without `--yes` the run stops with 29);
  an agent's run stops at a person's step (activation, `--force`, a push outside the plan file and its unit folders,
  the cancel of another active plan), and `--json` marks such a next command with `next_by: person`
  (L4-YOLO-080 to L4-YOLO-089, L4-CLI-001).
- The MCP tool `l4_plan_go` runs `l4 yolo go` as an agent, read-mostly: no `--accept-findings`, `--force`, `--yes` or
  `--local`, and `--no-push` always. It may ask CI for a review (judge tokens) and wait; it never pushes, accepts or
  activates (L4-YOLO-090, L4-MCP-003).
- The skill's `operate.md` and `plan.md`, the runbook (12.2) and `docs/yolo-mode.md` teach the one command
  (L4-YOLO-091).
- The GitHub workflow templates record the job's start (`L4_JOB_STARTED_AT`, a first step `job start`), and the
  soft deadline counts from it. Run `l4 upgrade` to get the step; until then the deadline counts from the run's start,
  and the run warns once (L4-IMP-066).
- Before each implementer step and each verification round, a run with a known budget compares the time left
  with the step's estimate. The estimate is the longest step of that kind in this run or among the unit's recorded
  steps, at least 10 minutes and at most one agent time limit plus `gates.timeout` (four gate timeouts for a round). A
  step that does not fit is not started; a resumed green is checked before its baseline. The first step of a run
  always starts. Every step records `step.timed` (L4-IMP-067).
- At the soft deadline, every agent, CLI judge and gate that the unit's run has running gets SIGINT, then SIGKILL
  after 5 s. The step is handed back: `deadline.reached` is recorded, no attempt is counted, the phase does not change,
  the ledger and the unit branch are pushed, `run.finished` has `reason: soft deadline: …`, and the run exits 10. The
  next run continues from the last pushed step, and a stopped replay of a held step is replayed again (L4-IMP-068,
  L4-IMP-069).
- A step stopped at the soft deadline starts again only as the first step of a run, and a second stop halts the
  unit with `deadline_repeated`. The reason names the job timeout to raise and `l4 retry` (L4-IMP-071).
- A GitHub run that the pin guard stops off the base (a scheduled run on a default branch that is not the base, or a
  push to an old unit branch) relays to the base before it reads the configuration, so a configuration key that its
  older harness does not know cannot stop it. `l4 doctor --ci`, `l4 plan --sweep`, `l4 run` and `l4 status` stop there
  and exit 0; the first of the first three dispatches `l4.yml` on the base once per job, when the base may have work
  and no other run of `l4.yml` is queued or running there, and prints what it did (`outcome.json` `relay`). On the
  base itself a configuration error stays exit 2. It works once the default branch's copy pins 0.4.19 or later: copy
  .github/workflows/l4.yml to the default branch once (or promote the base); the base's own run warns while that copy
  is behind, or missing (L4-IMP-072, L4-IMP-074, L4-ADO-005).
- `l4 yolo status` calls an open run "ended without a record" when it is older than its job timeout (recorded on
  `run.started` as `job_timeout_s`) or when the forge says its CI run completed. For an active plan whose open run
  ended without a record, or with nothing running or queued on the base and either idle for two schedule periods or
  with no schedule that can advance it, `Next:` gives the command that starts a run on the base (`gh workflow run
  l4.yml --ref <base>`). `--json` has `open_run.ended_without_record` and `open_run.why`. A CI run held for approval is
  shown as waiting for approval, with its address, not as ended (L4-IMP-073, L4-YOLO-030).

### Changed
- `kiro-cli` is a judge adapter: it is in `JUDGE_ADAPTERS` (`l4/config/roles.py`), so a `kiro-cli` profile loads in
  every judge role of that file (`roles.judges`, `roles.verifier_agent`, `roles.clarifier`, `roles.s1_judge`). In
  0.4.18 it was refused there at load (`… cannot judge`, L4-CFG-006, L4-KJD-008); that error now lists `claude-code,
  codex, opencode, kiro-cli, fake`, and `scripts/yolo_preflight.py` checks the same list.
- The vendor of a `kiro-cli` profile with a pinned model is the maker of that model (`claude-` anthropic, `gpt-` and
  `o<digit>` openai, `gemini-` google, `deepseek-` deepseek, `glm-` zhipu, `minimax-` minimax, `qwen` alibaba, `kimi-`
  moonshot) (L4-KJD-005). A profile whose `vendor:` contradicts its model no longer loads: `vendor contradicts the
  model: <model> is made by <vendor>`. Fix: delete `vendor:` (for example `vendor: amazon` on a Claude model) or set the
  maker. `vendor: unknown` makes no claim and loads (the maker counts). A model of no known family keeps its declared
  vendor. The rule is not applied to opencode in this change.
- `auto` is routed (L4-KJD-014), so its `vendor:` is ignored: a profile with no model, or `model: auto`, counts with
  every vendor Kiro may route it to. A Kiro judge on `auto` is not independent of a Claude, GLM or MiniMax implementer
  (fix: pin a model whose maker the implementer does not share, or use a judge of another adapter). Two `auto` sides, or
  an `auto` judge and a profile of no known vendor, are never independent (fix: pin one).
- Under `verifier.independence: different_model`, model ids are compared after folding a `.` between digits to `-`
  (`claude-sonnet-4.5` is `claude-sonnet-4-5`).
- Every `kiro-cli` run names a model. An implementer with `options.agent` and no model now runs `--model auto`, which
  overrides the model in that agent file (fix: name the model in the profile).
- The hello of every `kiro-cli` profile, implementers included, runs the tool-less judge agent in a private
  `KIRO_HOME`, so it does not start the user's MCP servers. That hello passes `--v2` and `--model auto`, measured on
  kiro-cli 2.32.0 only: recommend `min_version: 2.32.0` on every `kiro-cli` profile, implementers included. The `auth`
  step of an `auto` profile lists the models (it passes whatever the listing says).
- A continuation is dispatched for a unit handed back or left at the soft deadline even when another unit of the
  run exits 11, 12 or 13. When it is dispatched, the plan's own next-run start of the same run is not sent: one dispatch
  per run. A run in which no step started dispatches nothing and says so. On GitLab the continuation is now a pipeline
  on the base, and none is started while one waits. Each continuation is one more run of a delivery plan, so a plan's
  `limits.max_runs` is reached sooner (`limit_runs`; `l4 yolo resume --extend-runs N`) (L4-IMP-070, L4-CI-004).
- Failed attempts of a task count across runs: `implementer.max_task_attempts` and `implementer.escalate_after`
  read the task's `task.attempt_failed` since its last commit, retry, resume or restart, so a run that hands back and
  continues does not give a task fresh attempts. The attempt number continues after the highest attempt of the phase
  (L4-IMP-075).
- In GitHub Actions, on a copy of the workflow that is not the base's, `l4 doctor --ci` stops before the configuration
  and its checks, prints the pin warning and exits 0 (before, it could exit 2 on a configuration key its older harness
  does not know) (L4-IMP-072, L4-ADO-005).
- The GitHub Release of each version starts with that version's CHANGELOG section, above the source commit, the
  release commit and the checks. A tag whose version has no dated section (`## X.Y.Z (YYYY-MM-DD)`) is refused before
  anything is pushed (L4-ACT-006).

### Fixed
- A default `kiro-cli` profile passes its probe on a GitHub-hosted runner without configuration. Its `/usage` call (the
  `quota` step) and its model listing (the `auth` step) took 23 to 30 s, over the 20 s `availability.probe_step_timeout`
  (LIVE-001 failed). The adapter now declares a floor of 90 s for those two calls, used as the longer of the step
  timeout and the floor and still capped by `availability.probe_timeout` (default 60 s, so 60 s unless it is raised)
  (L4-AVL-012). Every probe step records `step_ms`; a step of a second or more shows its time in `l4 probe`, in
  `availability.selected` (`probes.<profile>.step_ms`) and in the doctor LIVE-001 line.
- A failed `kiro-cli` hello says why: its reason is `kiro-cli reported runError (<stage>): <message>`, with the message
  redacted (no e-mail, ARN, account, profile, request or session id, no path, no token) and cut to 200 characters. On
  kiro-cli 2.32.0 a pinned model id the account does not have fails the prompt with a `runError` and writes no warning:
  the profile is skipped like any failed hello, and the standard-error check for a model Kiro could not set stays as a
  second guard (L4-KJD-007, L4-KJD-015).
- A Kiro run with an invalid or missing key or login (`bearer token … invalid`, `not logged in`, an exit 1 that asked
  for `kiro-cli login`) is an `auth` failure: the profile cools and the next profile of the chain takes the call. It was
  a failed attempt (L4-KJD-006).
- `/usage` that answers `Invalid token` fails the quota step as `auth`, not as `quota_unrecognised` (L4-KJD-006).
- A run with a known job timeout is no longer killed by the CI timeout in the middle of an agent step, which left
  an open run with no end and no continuation (L4-IMP-012, L4-IMP-068).
- `l4 yolo status` no longer says `nothing: CI advances the plan at each run` for an active plan that nothing will
  advance (L4-IMP-073).

## 0.4.18 (2026-10-20)

### Added
- `scripts/yolo_preflight.py` in the `l4` skill, beside `validate_plan.py`, standard library only. It checks a clean
  tree, HEAD equal to `origin/<base>`, the plan file and the unit folders on origin, the judge roles, the installed
  OpenCode major, `yolo.review.accept_by_agents` and the caller. It asks the harness for the admission and the review
  state, and prints exactly one `Next:` command (`--json` too) (L4-SKL-005).
- The skill's `references/operate.md` starts with "origin is what counts", a numbered runbook from the draft to an
  active plan, and an error table (message, cause, fix). The runbook allows at most two rounds of spec fixes per
  subject, then accepting what this stack cannot fix, and a person activates (L4-SKL-004).
- `plan.reviewed` records `target_rev` and `unit_revs`, the revisions the review read. A stale review's messages name
  the changed files from them (L4-YOLO-068).
- `l4 yolo accept PLAN --all --force --reason TEXT` lets a person accept every unit and batch of a plan with no model
  review, for a plan whose judge cannot run. It records `plan.admitted` (when needed) and `plan.force_accepted`, bound
  to the digests of the plan file and each unit, and calls no model. An agent is refused whatever `accept_by_agents`
  says, and no MCP tool runs it; `--withdraw` removes it. `l4 yolo activate` accepts it in place of a missing or stale review (the findings of a current review on a
  subject it did not override still refuse); the plan fold ignores one whose actor is not a person; status,
  findings, the report, the implementer's prompt and the PR body name it (L4-YOLO-057 to L4-YOLO-062).
- Doctor `SANDBOX-005` warns when a Go project's `gates.setup` has no `go mod download`: `GOMODCACHE` and the checksum cache are read-only in every other gate. The runbook and the adopt skill say to run `go mod download all && go mod verify` in setup and to point tool caches (`GOLANGCI_LINT_CACHE`) at `.l4-out/`.
- `sandbox.tool_paths` (read-only paths for both sandbox kinds, for a tool under the home that the harness does not
  find) and `sandbox.setup_paths` (read-only paths for the sandbox of a `gates.setup` command only, for a registry
  login such as `~/.npmrc`). An entry that is, holds or lies inside a login is a configuration error.
- Doctor `SANDBOX-003` plants canaries in the home, in another unit's step directory and in the lock directory and fails
  (exit 3) when either sandbox kind can read one. Doctor `SANDBOX-004` warns while `sandbox.setup_paths` is set.
- The ledger events `env.rebuilt` and `guard.notice`, and `guard.violation` with rule `environment`.
- `yolo.extend_by_agents` (default `false`) in `.l4/config.yaml` on the base branch lets an agent raise a plan's limits
  with `l4 yolo resume --extend-…`, like `yolo.review.accept_by_agents` does for `l4 yolo accept`. The event
  (`plan.extended`, or `plan.resumed` that extends) records the actor, its marker and whether the key allowed it
  (L4-YOLO-051).
- `l4 yolo status` lists the extensions of a plan (`extended: runs 90 -> 110 by <who> (person): <why>`).
- Kiro steering reaches the implementer as data. The harness reads `.kiro/steering/*.md` on the host and puts each file
  that applies under `# Project conventions` as an `<l4:data>` block, by its Kiro front matter: none or `always`
  (always), `fileMatch` (a pattern matches a path of the task or of the unit branch), `manual` (the task, the
  requirements or the design names it as `#<file>`) and `auto` (after the others, when the budget has room). An
  OpenSpec unit gets the `context` of `openspec/config.yaml` the same way, never its `rules`. The sandbox masks stay,
  and `~/.kiro/steering` is never read. `implementer.include_agents_md: true` adds the repository root's `AGENTS.md`
  as a convention (never `CLAUDE.md`).
- Nothing is cut silently any more. A source that is cut by the budget or not read (over 262,144 bytes, a symbolic link,
  a file that is not regular) is named under `# Not shown in full` with its path, the characters shown and the lines
  left out, and the run records `prompt.truncated`. `prompt.rendered` records `budget_tokens`, `budget_source` and the
  steering decisions.
- `l4 run --dry-run` prints per unit the budget, each steering decision and each cut. `l4 status --unit` prints the
  last `Prompt cut:` and `--json` has `prompt_cut`. Doctor SPEC-004 warns when the next task's prompt would cut a source.
- A profile may set `context_budget_tokens` for its own steps, for a small local model in a fallback chain.
- The step-9 judge gets each done task's whole block (detail bullets included) and is asked whether the diff does what
  each task's text says; `verifier.judge_context_budget_tokens` (48000) bounds its spec text in the implementer's
  priority order, and a spec file it did not see whole is named to it.
- A profile may state its model's window (`context_window`, or an opencode provider's `limit.context`): the whole prompt
  then stays within 60% of it (`budget_source: model_window`), and doctor SPEC-004 warns when a budget exceeds that
  or when the never-cut parts alone exceed it (`prompt.over_window` at run time).
- `docs/control-loop.md`, "How L4 runs: branches, events and the control loop": the one control loop, where each kind of state lives (base branch, unit branch, lock ref, plan ref, keep refs, PR), what starts a run, one run step by step, what a stop keeps, redoes or loses, what each local command writes, a worked recovery of a halted unit in a stopped plan, and swimlane diagrams. Linked from the README, the quickstart, the runbook, the delivery-plans page, the architecture page and the skill's operate reference.
- The skill reference `references/control-loop.md` (at most 900 words, for coding agents: rules, a table of what to run for each state, what a stop keeps, the MCP tools), a rule in `SKILL.md`, and one sentence in the MCP server instructions: continue a unit with `l4_retry` or `l4_plan_resume`, never by a checkout or push of its unit branch.
- `availability.probe_step_timeout` (default `20s`, capped by `probe_timeout`): the timeout of the `binary`, `auth` and
  `quota` steps of a probe. The `hello` keeps `probe_timeout` (L4-AVL-012).

### Fixed
- Every confirmation prompt of `l4 yolo accept` and `l4 yolo waive` goes to stderr and runs only on a terminal, so a
  pipe or a wrapper on stdout no longer hides it; without a terminal the command exits 2 and names `--yes`.
- A review reuses the judgement an acceptance is bound to when the ledger holds two judgements of one material, so the
  acceptance is not lost to a newer one. An acceptance that no longer holds says why in one line (`other material`, or
  `other findings of the same material`), a dry run with `--fresh` no longer says `the material changed` for the same
  material, an accepted subject is shown as accepted where its verdict is printed, and a `reused` verdict shows when it
  was judged (L4-YOLO-065, L4-YOLO-066).
- A replayed step (an accept of a held question) runs the post-step guards of an agent step: the scratch drop, the runner-configuration revert (`guard.violation`) and the environment check. A patch saved by 0.4.17 that loosens `[tool.pytest.ini_options]` no longer reaches the commit.
- The replay guard no longer re-applies the saved patch's version of a frozen test or a test-support file that the freeze (green, single) or the test-chore review put back.
- A step that weakens a pre-existing test is refused before a pre-satisfied hold is taken: a person is never asked to accept it.
- A hold on a spec file the judge could not read whole is bound to the content of that file, and its question names `verifier.judge_context_budget_tokens` and the file instead of the wording of a diff hold.
- A unit whose started run ends with exit 3 (`gates.setup` failed, no usable sandbox) no longer makes the plan dispatch
  a run every minute until `max_runs`: the plan stops with the new reason `setup_failed`, which names the gate and its log
  and ends with `l4 yolo resume`.
- `support_at_base` restores a link original by its real path through the confined helpers (a committed directory link re-pointed during the block no longer makes the harness create an entry outside the work tree), checks each restored link's target, and counts two plan paths that resolve to one file once.
- A test that replaced a source directory with a link to a directory outside the repository made the harness write
  there when it restored files after the test run (the zero-value runs, the run at the red code, the reports). Every file
  operation of the harness after agent code ran now refuses a link on its path, removes the link and writes nothing
  through it. The unit halts with the code `planted_link` and the ledger names each link and where it pointed. A guard
  that used to crash on such a replaced directory (`git rm` without `-r`) can no longer crash a run.
- A step can no longer pass a gate by editing the configuration the gate reads. Before, a green step that added
  `ignore_errors = True` to `mypy.ini`, or a red step that added `ignore = ["ALL"]` to `[tool.ruff]` or `addopts =
  "-p plugin"` to the pytest section of `pyproject.toml`, kept the change and had it committed. `tdd.gate_config_globs`
  now takes effect.
- The folders the sandbox masks (`.hermes`, `.kiro/hooks`, `.kiro/prompts`, and now `.kiro/skills`) are protected paths:
  what a step or a test run wrote there used to be committed.
- Code an agent wrote can no longer read the runner user's files. The agent and gate sandboxes showed the real home, so
  a test written by an agent could read `~/.git-credentials`, `~/.netrc`, `~/.ssh/id_*`, `~/.config/gh/hosts.yml` or
  `~/.docker/config.json` (proved under bubblewrap 0.8.0). Both sandbox kinds now start from an empty home and an
  empty runner cache and see only the tools, the step's own directories and the caches.
- A file written into `.venv` or `node_modules` can no longer decide a verdict. A green step that wrote only a `.pth`
  file into site-packages passed with the production code still a stub, and the verifier ran on that environment too:
  no guard looked there, `git clean` and `uv sync --frozen` kept the file. The harness now rebuilds an environment that
  a step or a gate changed, and gates that do not build it see it read-only.
- Two projects with a unit of the same name on one runner no longer share directories. The step directories, the
  `uv`, `pip` and `npm` caches, the excludes file and the unpublished run files are keyed by the repository key, so one
  project's unpublished run file is never pushed into the other's lock ref.
- A unit's OpenCode provider key file and credential-loader file are no longer readable from another unit's sandbox,
  are created in 0700 directories, and one left by a killed run is removed before the unit runs again.
- The login lock files and the unit lock files are no longer readable inside the sandboxes.
- A package cache can no longer carry a plant into a rebuilt environment. A file an agent step or a gate wrote into the
  unit's `uv` cache (`zz_marker.pth` in `archive-v0/<id>/`) came back in every environment rebuilt from it. The per-unit
  caches are now read-only except for `gates.setup`, every step and gate works in a private scratch cache that is
  discarded, and the verifier builds from caches of its own, emptied at the start of each round.
- A symlink in a `PATH` directory, or a shim into a project's `node_modules`, can no longer expose the files next to its
  target: the sandbox binds the target file or the package, and skips any tool path that is or lies inside a login or
  a known secret location (`~/.config/gh`, `~/.aws`, ...).
- The outcome record a pytest gate keeps could be emptied by a conftest that reached the plugin through `sys.modules`.
  The plugin now opens the record when it is imported and keeps the descriptor out of reach; a pytest report with test
  cases and an empty or missing record fails with `the test report was altered (no outcome record)`; a failed row of a
  phase wins over a later passed one; and the content scan flags references to `l4_trace`, `_OUTCOME`,
  `L4_OUTCOME_FILE`, `xmlpath`, `sys.modules` lookups of `l4` and assignments to `.exitstatus` / `.xmlpath`.
  Only those exact names count (a fixture called `xmlpath` or a constant `_OUTCOMES` is fine), `verifier.test_awareness_allow`
  lists the match instead of blocking it, the record sits outside the gate's temp directory under a random name, and a
  record the plugin created but left empty fails the gate even when a wrapper (`make test`) ran pytest.
- A red step that weakened, rewrote or shadowed a test that already existed (a second `def` of its name, a helper, a
  constant, a fixture or an autouse fixture it uses in its file) used to be committed and judged green. It now fails its
  attempt with `red changed tests that existed before this step: <path>::<name> (<why>)`, nothing is committed, and the
  retry prompt says what to do. A `[test-infra]` task and the stale tests of a reopened task are exempt
  (L4-IMP-045..048).
- Step 1 never saw a weakened pre-existing test: a unit whose test went from `== 3.75` to `is not None` and whose code
  then returned a wrong value passed. It now compares each test that exists at the base per test on the AST, by file and
  qualified name, and a harness commit that changes or deletes one is the blocker `a pre-existing test was changed` or
  `a pre-existing test was deleted`; a later red commit that changes a test an earlier step wrote is a blocker too.
  People's changes and the ones a `[test-infra]` task, a `task.unfrozen` or a `tests.superseded` event allows are listed
  in `verification.md` (L4-VER-030..032).
- A deleted test was hidden when any other changed test file defined a test of the same name, whatever its body, and a
  person's deletion was not listed either. A test now counts as moved only when the same definition appears under a new
  file or name (L4-IMP-047, L4-VER-030, L4-VER-031).
- Audit tests ran with the unit's own `conftest.py` in place, so an autouse fixture could make the audit of broken code
  pass. Audit tests, their zero-value run and a generated UI test's head run now use the unit's test-support files at
  their base versions (the amended entry below widens this to every test file for the audit); the Audit table of
  `verification.md` has a `Support` column, and `verify.audit` and `verify.generated` carry `support`
  (L4-VER-033..036).
- Step 1 now also blocks a test-support file that patches code the unit changed in module-level code or an autouse
  fixture (it used to check only the files a task opened); a fixture a test requests by name is listed (L4-VER-037).
- Step 1 now runs the base's tests on the unit's code: the test gate runs at head with every test and support file the
  unit added or changed at its base version (added ones set aside), and a test that passed at the base must still pass.
  A weakened helper module, a weakened or hooked conftest, a swap through `__code__` or `globals()`, a production module
  that imports only with the unit's conftest, and a weakened Go or TypeScript test (any language with a JUnit report)
  now fail step 1 with `a pre-existing test fails on the unit's code` or `a pre-existing test no longer runs on the
  unit's code`; the integrity table has the row `pre-existing tests still pass`. A test a `tests.superseded` event, a
  `task.unfrozen`, a `[test-infra]` task or only people's commits cover is listed (L4-VER-038).
- The comparison of a pre-existing test now sees statements that are not plain definitions (attribute assignments,
  `globals()`, `setattr`, a class attribute), inherited tests, real locals, normalised docstrings and moves that keep the
  closure; the content scan reads helper modules under the test globs and flags `pytest_pyfunc_call`, a plain
  `pytest_runtest_call` or `pytest_runtest_setup`, and an assignment to `.obj` or `.runtest` (L4-IMP-045..049,
  L4-VER-039).
- The audit runs without any of the unit's test or support files and collects only the audit file; it never falls back
  to them, holds a criterion whose production module does not import, and keeps the writer's collection retry. A
  generated UI test's head run keeps app data the unit added under `fixtures/` and no longer crashes when the server
  does not start without the unit's runner support (L4-VER-033..035).
- Step 1 scans the unit's production diff: a line that names `.l4-out`, a configured report path, an `L4_*` or `PYTEST_*`
  variable is the blocker `production code reacts to the test run` (code that behaves differently while the verifier runs);
  `"pytest" in sys.modules`, importing pytest, `atexit.register` and a `sys.argv` check for pytest are listed for the
  judge in `verification.md`. A support file that only people changed, a `[test-infra]` task changed or a `task.unfrozen`
  frees stays at head for the run of the base's tests, listed (L4-VER-038, L4-VER-039).
- The audit file is written under the directory the test command collects (a command narrowed to `tests/unit` used to
  leave it uncollected and the criterion held); a test command that never collects it is a minor rejection naming the
  command. A generated UI test's head run reverts a helper named like a test module and no longer falls back to the
  unit's support files: a server that does not start without them holds the criterion (L4-VER-033..035).
- New config key `verifier.test_awareness_allow` (list of production path globs, default empty): a match of the test-awareness
  blocker in a file under one of them is listed for the judge with its glob instead of blocking. It is read from the base
  branch's `.l4/config.yaml`, never from the unit, and `l4 doctor` shows it (CFG-010) (L4-VER-039).
- Every pytest gate run is cross-checked: the harness's plugin records what pytest judged for each test outside the
  worktree, and a JUnit report that disagrees (a pass the record does not hold, a failure removed) fails the gate with
  `the test report was altered` and the test ids; a conftest or helper with `atexit.register`, `os._exit`, a
  session-end hook that writes a file, or a name of the report path is a content-scan hit (L4-IMP-006 (8), L4-VER-039).
- The audit file is written next to the unit's own test files (an option value such as `--ignore tests/legacy` or `--tb
  short` no longer picks the directory), confirmed by a `--collect-only` run when the unit has no test file there
  (L4-VER-033).
- A `[test-infra]` or `[config]` tag in a fix unit's or follow-up unit's task exempts nothing, and brackets in
  model-written finding text become parentheses before they reach a task (L4-IMP-006).
- The test-awareness blocker reads Python with the AST: comments and docstrings are ignored, only reads of `L4_*` or
  `PYTEST_*` variables and names of `.l4-out` or the report path (with word boundaries) block (L4-VER-039).
- A delivery plan with `merge: auto` no longer merges a unit commit that nobody verified. The merge lands the hand-off
  commit H that the hand-off recorded (`pr.ready{head}`), pinned to its sha, and never the branch tip. Any commit after
  H sends the unit back to verification, whatever author, committer or `L4-Run` trailer it claims: before, a commit that
  copied the bot's identity and trailer after the review was squash-merged unseen, and a forged second hand-off commit
  became H (L4-ARC-008, L4-YOLO-040). The archive merge has the same rule: it lands only the archive head that
  `archive.opened{head}` recorded (the harness's own push); a branch head that is not the recorded one, or an archive
  with no recorded head, is not merged and `archive.failed` names the reason (a person merges the archive PR).
- A plan no longer merges a unit whose repository CI is red. A red CI that the sweep recorded on H is dispatched for
  verification before any merge, and the merge itself waits while the CI on H is running, is red and not yet recorded,
  or cannot be read, with a `merge_not_ready` detail that says why (L4-YOLO-041, L4-YOLO-042).
- On GitHub, a failed job is no longer hidden behind a passing job of the same name in another workflow. A check run is
  one job of one workflow (and event), a re-run replaces its earlier attempt, and a job red on H is pre-existing only
  when the same workflow's job is red on the base (L4-CI-010, L4-CI-011).
- A hand-off commit whose only check run is the harness's own skipped `l4` job is reported `not_run`, not green
  (L4-CI-012).
- A merge no longer treats CI that is not there yet, or a job that did not pass, as green. A cancelled job, an
  `action_required` check (a person must act) and a stale run, a failed commit status, a workflow run still queued or in
  progress, an unfinished GitLab pipeline and a required check that H has not reported are all read: cancelled or held
  jobs block the merge with "re-run it" and open no fix round (a cancelled push run whose pull_request twin finished
  does not block), a required check that never reports blocks it whatever `yolo.merge.require_ci` says, and the
  others are red or running. "No CI" is final only ten minutes after the hand-off, unless the repository has no
  workflow but `l4.yml`, requires no check and shows no status on H (L4-CI-013, L4-CI-014, L4-CI-015). Only the
  harness's own job (`l4` of `l4.yml`) is ignored, no job named `l4` in general. A CI read of a hand-off commit with one
  workflow makes about 7 API calls, three workflows that run on both `push` and `pull_request` about 17, and more when the
  base head is read too (not the hundred or more of before): the jobs of `l4.yml` runs and the base head are read only
  when needed.
- The recorded hand-off commit H is read from the unit's lock ref only, never from a `pr.ready` in the branch tree.
  Anyone who can push the lock ref can still forge `pr.ready{head}`: that residual is accepted, and closing it needs
  signed harness commits or a ref only the harness can write.
- A PR that a person merged at another head while the plan held H is recorded with the head that was merged.
- A diff over 120000 characters no longer holds the unit every round. The judge now reads it in parts: whole files,
  ordered so that a test sits next to the code it is named after, at most 8 parts of at most 120000 characters, one judge
  call each, and the replies are merged into one verdict (a `fail` of any part wins, then a `pass`). A diff within the
  cap keeps its one prompt. The prompt template is `judge@11` (`judge@10` added the parts); `verdict.json` lists `judge_parts` and `verification.md`
  says `judged in N parts` (L4-VER-041, L4-VER-042).
- The judge's diff leaves out the harness's bookkeeping, named once: every `.l4/` file, `.serena/memories/harness/**`, and
  the `verification.md`, `questions.md` and `feedback.md` of each unit folder of the family (L4-VER-040). Lock files
  (`uv.lock`, `poetry.lock`, `Pipfile.lock`, `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `go.sum`, `Cargo.lock`,
  `composer.lock`, `Gemfile.lock`) are shown as one line each (path, old and new size, lines added and removed) and never
  hold the unit (L4-VER-045).
- What the judge still cannot see (one file longer than one part, a diff that needs more than 8 parts) is a hold
  `judge view: …` of its own kind. Its question says what `accept` and `reject` mean and asks for no `WHEN … THEN …`. A
  rejected one is a human finding no fix task is derived from: the unit escalates with `judge_view_rejected`, and
  `l4 status`, the refusal of `l4 run --unit`, the sticky note and a plan stopped on the unit name the way out (split the
  change and `l4 restart`, or `--replace` with an accept and `l4 retry`). Before, a reject with a `WHEN … THEN …` made a
  fix unit that could not shrink the diff, and the same hold came back every round (L4-VER-043, L4-VER-044,
  L4-YOLO-055).
- After `l4 questions answer`, `l4 yolo resume` no longer refuses a plan whose answer is pushed and not yet read, and
  `l4 yolo status` says what happens: while a question is open, how to answer and that the plan continues by itself at
  the run that reads the answer; once the answer is pushed, that the next run reads it and how to start it now. The
  wait line shows the live reason, not the stale `open: Q-…` detail. The plan step, the resume and the status decide with
  one rule (L4-YOLO-052, L4-YOLO-053, L4-YOLO-054).
- Requirements and the criteria text no longer disappear behind a long `design.md` (a Kiro unit whose design was 125,492
  characters lost its `requirements.md` to the budget).
- A spec file over 262,144 bytes was dropped from the implementer's and the judge's prompt without a word; it is now read
  up to the limit and named, and the judge holds the round.
- A Kiro leaf's cited criteria were not required in red: a red step that tested one of `_Requirements: 1.1, 1.2_` passed,
  and the no-new-test path ticked such a leaf without proving the other. Red now fails with a reason that names the
  criterion and the line; a criterion that an earlier red already proved needs no copy (review finding implementer-5).
- Red no longer counts a criterion as proved by an earlier test that was merely re-tagged (the proof is per criterion
  and test, in a file only appended to), accepts new tests and fixtures in an existing test file (a constant computed by a call at import is refused; compute it in the test or use a new file), and accepts a step that
  reports every cited id. Hostile steering (deep YAML, huge or complex patterns, forged names) and unsafe capability directory names
  are named and left out; `l4 status` shows the latest prompt's cut; the clarifier charges its line numbers.
- A fix unit's `_Requirements:_` links resolved against the whole family, so the parent's own `Req 2.1` and the fix
  item `2.1` both counted; they resolve against the fix unit's own items.
- PRQ-11 accepted `opencode v2.0.32` as at least 1.18.34 (`sort -V` ranks the digit first); it now needs major 1.
- A hello that OpenCode 2 rejected (`Unrecognized flag: --pure` or `--dir`, exit 1) was classed `transient`, so the
  profile looked unavailable with no named cause. It is now `unsupported_version`, is never cached, and a run that ends
  the same way has a detail beginning `unsupported_version:` (L4-OCG-003).
- `l4 doctor --fix` kept an OpenCode 2 `opencode` that met the profile's `min_version`.
- A probe no longer hangs on a helper that holds its output. `run_process` reads until the child has exited plus a
  2 s grace, then kills the group, and never waits on a pipe that a process outside the group holds (an OpenCode v2
  daemon started by `auth list` did this) (L4-AVL-012).
- A probe step that times out names the CLI, the seconds, the step, the likely cause and `l4 doctor`, as `transient`:
  `opencode did not answer within 20 s (auth step); an OpenCode v2 daemon or a login prompt can cause this: run l4
  doctor`. The hello that timed out no longer says only `timeout`. `l4 doctor` readiness shows the text.
- An agent run ends when an escaped helper holds its output: `ProcRunner` joins its readers with a bound and logs that
  the raw events end there.

### Changed
- `l4 yolo review PLAN --worktree --record` fetches and records only when HEAD is `origin/<base>`: commit, push, then
  `--record`. HEAD ahead, behind or diverged is refused before any judge call, with both short shas, the counts, the
  paths and the command (`git push origin HEAD:<base>` or the pull). A unit whose branch on origin holds another spec is
  refused too. The last line names `l4 yolo findings` or the person's `l4 yolo activate` (L4-YOLO-069).
- A stale review names what differs: `activate: the review of <plan> is stale against origin/<base> (<sha>):`, one line
  per cause and a `Fix:` line. The causes are the review prompt, the plan file's digests, each changed unit's digests
  (where it is read, and its changed files), a subject not judged, and unpushed commits. `l4 yolo status` shows the
  same lines (`--json`: `review.stale`), and `l4 yolo review` prints them before it asks CI. A plan file that is only
  in HEAD is named with the push. The `inputs_changed` stop details name the frozen and the current digests
  (L4-YOLO-068).
- `l4 yolo review PLAN` and `--local` print a `warning:` when HEAD is ahead of `origin/<base>` and the unpushed commits
  change the plan file or a unit folder: CI reviews origin, not your commits (L4-YOLO-070).
- **Breaking:** an adapter profile that cannot judge in `roles.judges`, `roles.verifier_agent`, `roles.clarifier` or
  `roles.s1_judge` is a configuration error at load. An adapter that can judge is `claude-code`, `codex`, `opencode` or
  `fake`; one that cannot is, for example, `kiro-cli`. The error says the profile `cannot judge`, names the role and the
  allowlist. Before, such a profile was skipped at selection. Remove it from the role: kiro-cli becomes a judge in
  0.4.19. Backend profiles are not affected (L4-CFG-006).
- A person's `--yes` replaces the typed plan id in `l4 yolo accept`, `l4 yolo accept --all --force` and
  `l4 yolo waive`; the findings are still printed, and `plan.accepted`, `plan.finding_waived` and `plan.force_accepted`
  record `confirmed: typed` or `confirmed: --yes` (L4-YOLO-063).
- Upgrade note: reading the CI of a hand-off commit (merge-safety, `yolo.merge.require_ci`) needs more of the forge token
  than the pushes did. On GitHub a fine-grained token needs checks, actions and commit statuses READ on top of contents
  and pull requests write (the workflow's own `GITHUB_TOKEN` gets them from the generated `permissions`). Without them the
  read fails closed and the merge waits with a `merge_not_ready` detail. Add them before `l4 upgrade --harness-ref v0.4.18`.
- A hold about a spec file the judge did not see or saw only in part (`the spec file …: the judge saw only …`) is a hold on the judge's view like the ones about the diff: rejecting it stops the unit with `judge_view_rejected` and never makes a fix unit.
- Gate configuration and runner configuration now have exact definitions (the gate files at any depth, the gate and runner
  sections of `pyproject.toml`, `setup.cfg`, `tox.ini` and `package.json`, and the scripts the gate commands run). After
  every agent step, and after every gate run, a change to them is put back to the step's base unless the task has a
  `[config]` or `[test-infra]` tag or a person's answer names the file (`task.config_opened`). The whole file goes back, so
  a dependency added in the same file must be written again. A red or green step may still add a pytest marker. Runner
  configuration is never changed in green. The verifier's step 1 checks the same rule on the commits.
- A step that leaves a symbolic link which points outside the worktree (an absolute target or a `..` escape) fails its
  attempt before the commit, in red, green and fix chores, unless the base held the same link.
- New default gate globs: `pyrightconfig.json`, `pylintrc`, `.eslintignore`, `.prettierrc*`, `.prettierignore`,
  `biome.json`, `biome.jsonc`; `.coveragerc` is runner configuration. The new key `tdd.extra_gate_config_globs` adds
  globs without restating the defaults.
- Per-unit directories under `$L4_CACHE` carry the repository key (`units/<key>/<fw>/<name>`). Caches start empty once
  after the upgrade (a new `uv` cache gets the project's seed copy); the old `units/<fw>/<name>` directories can be
  deleted by hand. A run file of the earlier `pending-unpublished` layout is published by the repository it records (its key, or the
  project path of its CI link); any other, a local run included, is kept and named in one warning.
- A project environment (`.venv`, `node_modules`) that an agent step or a gate changed is removed and built again by the
  next `gates.setup`; the verifier builds its own. A project without `gates.setup` therefore builds its environment in
  every gate: set `gates.setup`. A test gate that writes into `node_modules` other than `.cache` and `.vite` fails
  read-only: move that command to `gates.setup`. Every agent step and every gate but `gates.setup` starts from an empty
  package cache (read-only shared cache plus a scratch), so a test gate that needs a download setup did not make fails
  under `gates.network: none`: move the download to `gates.setup`. The verifier downloads once per round. A dependency upgrade without a lock-file change is a notice, not a
  violation, when a dependency manifest changed in the same step.
- A plan merge waits for the repository's CI on H when it is running, red or unreadable. The new key
  `yolo.merge.require_ci` (default `false`) decides only whether a hand-off commit that no CI ran on waits too. With
  the default it is merged, after waiting up to ten minutes for a CI that may still be created (at once in a
  repository that can start none), and `unit.merged` records `ci: not_run`; a warning goes to the plan report and to a
  note on the merged PR or MR. A PR a person merged at another head records `ci: unknown`. A GitHub repository whose hand-off is pushed with the workflow's `GITHUB_TOKEN`
  (which starts no runs) that wants its CI to gate the merge gives the push a token that starts runs, such as a GitHub
  App, and sets `yolo.merge.require_ci: true`. A job red on H and on the base does not block: `unit.merged` records
  `ci: preexisting` and the job names.
- GitHub job names in `ci.failed` and `ci.preexisting` are `<workflow file> / <job>` (`tests.yml / build`).
- On GitLab, a hand-off commit with no pipeline job is `ci_not_run`; it was `ci_green`.
- A person's accept of a `judge view:` hold is bound to the head content of every file the hold covers and to the full list of
  files the judge did not see (the hold's text names five): it is void, and the hold asked again, when that content changes. The
  question lists every unseen file (L4-VER-046). The file list of a part prompt is capped at 200 files (then
  `+K more files: see verification.md`, which lists them all) and the diff is read with one `git diff` (L4-VER-047). A test is
  packed with the code it imports, a part that shows the code judges its criterion, and a part that cannot see a test cannot
  call it inadequate. A lock file is a lock file only when its old and new names both are, and its line shows the changed lines
  that touch a source field and the hosts they name (L4-VER-045).
- The key `yolo.extend_by_agents` (and `yolo.review.accept_by_agents`) is read from the plan's own target branch, and only when the plan file there is the one the plan recorded; an agent that names
  another base branch in its configuration has no key. `--extend-cost` must be finite. `l4 yolo status` lists the extensions the plan's
  fold applied, follows the unit's answer step for an invalid, dismissed or draft answer, and describes a unit as answered only when an
  answer is recorded (L4-YOLO-056). A rejected judge-view hold beside another unconvertible reject names both ways out.
- `l4 yolo resume PLAN --reason TEXT --extend-…` on an **active** plan raises the limit and records `plan.extended`; it
  resumes nothing and starts no run. Before, it was refused until the plan stopped. Without an `--extend-…` the refusal
  names the four options, and an extension that changes no limit is refused (L4-YOLO-050).
- Every `--extend-…` of `l4 yolo resume` is a person's decision: an agent is refused, with the command a person runs,
  unless `yolo.extend_by_agents` is true on the base branch. Before, the rule was only written in the docs
  (L4-YOLO-051).
- Every implementer prompt carries each criterion's full text and the task's whole block from `tasks.md` (the enclosing
  headings, the parent tasks' lines, the detail bullets and the `_Requirements:_` line), never cut. The rest of the
  budget is filled in a fixed order by whole sections: conventions (at most half), the requirements narrative, the
  design and the proposal, the sections the task names first.
- `implementer.context_budget_tokens` rises from 24000 to 32000.
- The clarifier's documents are chosen by the same builder, order and cut list (`clarifier@5`).
- Step 1's declared scope reads a Kiro unit's `requirements.md` and `bugfix.md`.
- Templates `contract@12` (conventions, the cut list), `red@11` (every listed criterion needs a new test or an earlier
  proof) and `judge@11` (the cut-list rule, the done-tasks block; it also holds the diff in parts of `judge@10`).
- An `opencode` whose `--version` is not major 1 is refused by name where the harness reads a version, whether or not
  the profile sets `min_version`: the probe's `binary` step, doctor `ENV-004`, doctor `LIVE-005` (now an error, never
  the `unrecorded version` warning) and `prereqs.sh` PRQ-11. The reason reads `opencode 2.0.32 is OpenCode v2; this
  profile runs v1 (opencode-ai 1.x): install opencode-ai@1.18.34 (l4 doctor --fix installs it user-locally); OpenCode 2 support comes in a later L4 release`. The supported major follows the pinned `OPENCODE_VERSION` (L4-OCG-001, -002).
- `l4 doctor --fix` treats an `opencode` of another major as not satisfied and installs the pinned `opencode-ai` into
  the harness npm prefix, linked as `~/.local/bin/opencode`. It never replaces a regular file at that path (the action
  fails and names the path and the manual command), and it fails when the `opencode` the harness path resolves is still
  the wrong major. The Node, `laya-serve` and codex links are unchanged (L4-OCG-004).
- `prereqs.sh` PRQ-15 runs `opencode models` only when PRQ-11 passes, because OpenCode 2's `models` starts a shared
  daemon that outlives the call.

## 0.4.17 (2026-10-19)

### Fixed
- An `accept` of a held check now binds to the step the person looked at (L4-IMP-065). On 0.4.16 a task held with a `harness`
  question discarded the step's changes, and an accept covered a criterion only while its candidate tests were among the test
  ids the question named, so the next agent wrote the test again under another name and a new question was raised for the same
  criterion, without end. Now the held step is saved first, as `.l4/held/<task>-<check>.patch` in the unit folder (binary-safe,
  with the agent's result beside it), committed with the questions commit, and `question.raised` records `patch_sha256`. The
  question's Context shows the source of each named test, redacted and cut to 40 lines. The next run after an `accept` starts no
  agent for that step: it checks the digest, applies the patch, runs the guards, gates and checks an agent's changes get, records
  `held.replayed` and counts the criteria for those tests. A missing patch, a different digest or a patch that does not apply gives
  a new question that says why, never a pass. `retry` deletes the patch and runs an agent with the note; a replay deletes it in the
  step's commit; a restarted unit or a reopened task drops it. The question lists every changed path and shows the redacted diff of every changed path; a cut says that the cut lines are replayed
  too and names the patch path. The accept takes effect only through the replay of exactly that saved step: once the replay is used up
  (it failed a gate or the check refuted a criterion; a failed replay counts as an attempt), it covers nothing, and a later step
  that meets the same inconclusive check is held again with a new question. A reopened task drops every earlier accept. Every question of this release records `saved: true|false`; only a question without it (0.4.16) keeps the old rule by test id. A step is always saved whole, whatever its size; a question is bounded (400 characters a line, 48 KB a Context and less as `questions.md` fills, then the path list and the patch path). A replay commits exactly its saved patch: the tree is snapshotted before its first gate and every non-ignored path is put back to it after each gate run (`held.replay_restored`); links are never followed (every read, unlink, rmdir, mkdir and file creation goes through the file descriptor of the path's folder, reached with `O_NOFOLLOW`, checked again right before each action), a link is trusted only where the saved patch creates it, modes are restored, and a link planted by the setup or by a gate fails the step (`held.replay_unsafe`). The set of trusted links comes from a temporary git index, not from patch text, and a link is trusted with the target the patch gives it (a re-pointed link fails the step); the expected state is the step base plus the saved patch (from a temporary index), not the tree after setup, so a tracked file that setup or a gate changed is put back and a build hook of the patch cannot add content to the commit; the commit of a replay stages only the expected paths (not `git add -A`), and the guard lists untracked files by the base's and the work tree's ignore rules together; files are compared by size and a chunked blob hash and streamed in from git, so a large fixture of the patch replays and no file is read whole; the work tree folder is checked to be the same folder before every restore and git call; a gate-written huge file is no longer read to be removed; a folder a gate made unreadable fails the step cleanly; a cache mount at or above `<cache>/worktrees` is refused. `Next:` offers only `retry` for a question whose step was not saved. A refused replay (patch missing, digest differs, does not apply) raises a question that offers only `retry`. A replay that finds a path outside its saved patch after the gates fails as an attempt. A later agent
  attempt gets a notice (data block `accepted tests`) that the earlier accept was for the earlier step only. All four held checks (`pre_satisfied`, `vacuity`, `at_red`, `tests`) do this. A
  question raised by 0.4.16 has no patch and keeps the old behaviour.
- The runbook and the skill no longer say that `l4 questions answer`, `accept`, `l4 retry` and `l4 restart` always start a run:
  they do when the forge token is set, and otherwise print `start a run with: …`.

## 0.4.16 (2026-10-18)

### Fixed
- `yolo.hold` holds a unit that a delivery plan only excludes: listing a held unit in a plan's `exclude` released it, so after
  a plan review the held units ran. Only the units a plan plans (a batch's units) follow the plan; an excluded unit that
  `yolo.hold` matches stays `held by yolo.hold`, and `l4 plan` / `l4 yolo status` say so. The coverage check still counts a held
  unit as covered (L4-ADO-011).
- Review of the zero-value work (L4-IMP-060..062): a missing test is the agent's (no proof) when the innermost frame of
  its own files is not an import of other code (also a `conftest.py` the unit added that stops pytest);
  the keep loop reads module-level calls of pre-existing test-support modules, and a test that failed by assertion in any
  pass counts as a proof.
- The GitHub setup action installs the harness again with `source: action` (the default for a published
  harness): since 0.4.14 the build reads the l4 skill from `plugins/l4/skills/l4` (L4-SKL-003), which the action's
  build copy and cache key left out, so every run failed with "Forced include not found". The copy and the key now
  hold the skill, and a test keeps them in step with every `force-include` of pyproject.toml.
- A check that could not run no longer fails the agent. The pre-satisfied zero-value run, the base run, run (b), the
  `test-at-red` run, the verifier's audit and the extra-proof runs are judged against the real run, per test: a test
  that failed by assertion is a proof, one that passed or failed another way is no proof, and one the run did not run
  (no report, no test collected, its module failed to import only there, skipped only there) is inconclusive. In 0.4.14
  and 0.4.15 a decorator factory zeroed to `None` broke the import of the modules that apply it, pytest stopped with
  45 collection errors and ran 0 tests, and the message said "its tests still pass"; the unit halted after nine red
  attempts on four profiles (L4-IMP-060).
- Zeroing keeps what imports need: a public function annotated to return a callable or a class keeps its body when a
  module of the varied set applies it at import time (a decorator or decorator factory, or a module-level or
  class-level call), and when a run leaves a candidate inconclusive the functions its tracebacks call, and those called
  by the module-level statements of the production module whose import failed, are kept real and the run is made again,
  at most twice (`zero.kept` records them). Every variant run goes on past collection errors
  (`--continue-on-collection-errors`), so the base run of a unit that adds a module no longer stops at the first test
  file that imports it (L4-IMP-061).
- In a zero-value run a test the unit's own files made unrunnable (it skips itself on the zero answer, its test or
  support file raises at collection, a `parametrize` over a production answer loses its id) is no proof, so the
  attempt fails as on 0.4.15; only a production module that failed to import leaves a criterion inconclusive and holds
  the task. An agent can no longer turn "not discriminating" into a held task, and an `accept` covers only the tests
  the question named.
- Every excerpt in the committed ledger, `questions.md` and the console is redacted before it is cut, so no prefix of a
  secret survives.
- A failing assertion in the setup of a fixture counts as a failure on the zero values when the fixture is in a test
  or support file the unit added or changed; in a file that was there before it is inconclusive (L4-IMP-002).
- The verifier no longer rejects an audit test, or ignores a person's or a chore's test, because a zero-value run
  could not run it: the audit records it `inconclusive` (no finding, listed in `verification.md`), and an extra test
  says why it has no proof (L4-VER-050).
- The console no longer says `(expected: zero values must fail)` for a zero-value run that ran no test, and the
  artefacts line says `not uploaded` when `ci.upload_artifacts` is false in GitHub Actions (L4-IMP-064).

### Changed
- An inconclusive check holds the task: no attempt is used, no profile escalates, the step's changes are discarded,
  one question of the new kind `harness` is raised and the unit waits in `awaiting_human` (exit 11); a delivery plan
  waits without chaining runs. A person answers `accept: <why>` (the next run counts those criteria on the evidence of
  the real run when the check is inconclusive again; audited as `via: human_override`) or `retry: <note>` (the check
  runs again, for example after an L4 upgrade). A criterion a run shows to be not discriminating still fails the
  attempt, and the message lists the inconclusive ones apart. The discrimination check of a test chore that cannot
  decide holds the chore the same way. An agent may answer only where
  `clarifier.answer_by_agents` is true on the base branch; its answer is recorded `by: agent` and labelled
  `agent_override`, never as a person's (L4-IMP-063, L4-IMP-017, L4-QMD-004, L4-QMD-009).
- A criterion whose every test imports no project module and reads a dependency's version (a version pin) is no longer
  passed: it is inconclusive ("its tests import no project module: the zero-value check cannot judge them"), the task is
  held with a `harness` question, and nothing is recorded `via: not_applicable` any more (old ledgers are still read). A
  person's `accept` counts it (L4-IMP-062).
- `gate.finished` and `task.attempt_failed` carry an `excerpt` of at most 600 characters (the `E` lines and the deepest
  repository location, redacted) in the committed ledger, for a repository that uploads no job artifacts
  (L4-IMP-064).
- `l4 status --unit`, `l4 plan` and the waiting detail of a plan name a harness question: `Cause:` quotes the check's
  reason, `Next:` the two answers, and the plan says `harness check inconclusive: Q-NNN` (L4-OPS-006).

## 0.4.15 (2026-10-18)

### Added
- `l4 mcp serve [--repo PATH]...` makes L4 an MCP server over stdio (newline-delimited JSON-RPC 2.0, protocol revision
  2025-11-25; no new runtime dependency). Its tools manage delivery plans and debug units: `l4_status`, `l4_doctor`,
  `l4_plan_status`, `l4_plan_check`, `l4_plan_findings`, `l4_plan_report`, `l4_questions`, `l4_question`,
  `l4_unit_events`, `l4_verification` (read) and `l4_plan_draft`, `l4_plan_review`, `l4_question_answer`, `l4_retry`,
  `l4_plan_resume` (write). Each tool runs the `l4` command it names in a repository the instance was started for, as an
  agent (`AI_AGENT=l4-mcp`), so every CLI rule for agents holds; `l4 yolo activate`, `cancel` and `l4 run` are not
  tools. Several `--repo` give every tool a required `repo` argument; a repository that was not named is refused.
- `l4 mcp install --client claude-code|cursor|vscode|kiro|codex|opencode [--project] [--repo PATH] [--name NAME]
  [--dry-run]` writes the client's documented MCP configuration (one entry per repository, other servers kept, atomic,
  an unparseable file refused).
- `l4 status --unit U --events [--type T] [--last N] [--json]` and `--verification` read a unit's ledger events and
  `verification.md`. The tool `l4_plan_check` runs 0.4.14's `l4 yolo check PLAN --worktree` before the push.

### Fixed
- `l4 resume` and `l4 yolo resume` refuse `--extend-cost` of `nan` or `inf` with a usage error (exit 2); the MCP tools
  refuse a non-finite number the same way.
- `l4 mcp serve`: a timed-out or cancelled call now kills its whole process group after the grace period, also when
  the command itself exited and a descendant ignored SIGTERM; the protocol is read and written as UTF-8 under any
  locale (a non-UTF-8 locale used to kill the server on `tools/list`); progress notifications carry a rising
  `progress` value; `initialize` and each tool name the served repositories, so a client with several instances can
  tell them apart.
- `l4 mcp install --client claude-code` prints the `claude mcp add` line shell-quoted, so a path with a space works.
- `l4 mcp serve`: the tool commands run with `python -P`, so a file of the served repository named `yaml.py`,
  `click.py` or an `l4` package can no longer run in place of a dependency; a stopped call's process group keeps its
  grace period after the command exited, so a descendant can clean up before it is killed; no progress notification
  follows the response of its call.
- `l4 mcp install --project` writes what each client can use: Cursor `--repo ${workspaceFolder}` (Cursor documents no
  working directory for servers), VS Code, OpenCode, Codex and Claude Code `l4 mcp serve` (they start in the project
  or set `CLAUDE_PROJECT_DIR`); Kiro, which documents neither, is refused with a hint to use the user scope. A Codex
  entry lists `forge.token_env` of `.l4/config.yaml` (else the default `L4_FORGE_TOKEN`) under `env_vars`, because Codex
  starts a server with an allowlisted environment. An existing user-scope entry whose `--repo` is a client variable is
  refused like another repository's entry instead of being rewritten. The quickstart says a project file serves a
  worktree only for a session started inside it (Claude Code desktop worktree sessions use the main checkout's file).

## 0.4.14 (2026-10-17)

### Added
- `l4 yolo check <plan> --worktree` checks a delivery plan before the push, with the installed `l4`. It reads the plan
  files and the units from the working tree, runs the admission of `l4 yolo check`, and adds the checks across all plan
  files that only `scripts/validate_plan.py` ran (`uncovered`, `covered_twice`). It prints the findings, the order and the
  budget warnings, writes nothing, and exits 0 or 2. `l4 yolo draft` and `l4 yolo review --worktree` name it in their
  hints. The script stays for an agent or a CI step without the harness, and a parity test holds the two together.
- `l4 skills install` puts the `l4` skill into the skill folder of every coding agent, with no network and no clone:
  the skill now ships inside the wheel and the sdist. User scope writes `~/.claude/skills/l4`, `~/.agents/skills/l4`
  (and `~/.codex/skills/l4` when that folder exists), `~/.config/opencode/skills/l4` and `~/.kiro/skills/l4`;
  `--project` writes `.claude/`, `.agents/`, `.opencode/` and `.kiro/` `skills/l4` in the repository. `--agent auto`
  (the default) takes the agents whose home folder or CLI (`claude`, `codex`, `opencode`, `kiro-cli`) is present. Each
  copy has a manifest `.l4-skill.json`; a rerun updates an untouched copy, refuses an edited one (exit 2) unless
  `--force`, and never follows a symbolic link. `--dry-run` prints the plan. `l4 skills status` lists the copies with
  version, `current` or `old`, and edited files. Doctor row SKL-003 warns about an installed skill older than `l4`, and
  `l4 init` names the command (L4-SKL-003).

### Fixed
- A delivery plan no longer starts a run every minute for a unit that waits for capacity. A plan step that dispatches a
  unit in `waiting_capacity` starts no next run, and a unit that parks twice for the same profiles with none cooling
  (an expired provider key, a missing binary) stops the plan with `capacity_needs_fix`; the stop names the profiles,
  their failures and the fix, and `l4 yolo resume` goes on after it (L4-YOLO-035). A park with a cooling profile still
  waits for its reset.

## 0.4.13 (2026-10-17)

### Added
- `ci.toolchains` provides the toolchains a polyglot repository's gates need. The generated GitHub workflow (action,
  copy and plain forms) sets up Go, Node and pnpm before L4 with `actions/setup-go`, `actions/setup-node` and
  `pnpm/action-setup`, pinned by commit sha and with their own dependency caches off; each entry takes exactly one of
  `version` and `version_file` (pnpm: `version`). Without it the workflow is unchanged. New default caches `gobuild`
  (`GOCACHE`) and `pnpm` (the store directory); with a `go` entry the gates run with `GOTOOLCHAIN=local` and
  `GOFLAGS=-mod=readonly`. Doctor row TOOL-001 names a gate command whose first word is not on the gate PATH (a warning
  in `l4 doctor --adoption`, an error in a CI run), and `l4 init` proposes `ci.toolchains` from `go.work`/`go.mod`,
  `.nvmrc`/`engines.node` and `packageManager: pnpm@X`.

### Fixed
- A repository that adopts L4 with finished Kiro specs is no longer stopped by them. Doctor's SPEC-002 was an error and
  intake rejected the unit for history L4 never runs: a done leaf without a `_Requirements:_` line, or with a
  reference no criterion has, a `## Task Dependency Graph` whose block is a mermaid diagram, a whole-requirement
  reference such as `_Requirements: 1_`, `## Requirement N` with `### Acceptance Criteria` (one heading level higher
  than `### Requirement N` with `#### Acceptance Criteria`), and a number inside a word such as `ADR-0014.8` or
  `AC3`. Now a done leaf's missing or unresolvable link and a graph block that is not JSON are warnings (the tasks run
  in document order); a pending leaf keeps its rule, and a JSON graph that is wrong stays an error. A reference `N`
  resolves when requirement `N` has criteria, both heading levels are read, and a number counts as a reference only
  when it stands alone. SPEC-004 lists the pending leaves only.

## 0.4.12 (2026-10-17)

### Changed
- A delivery plan with `merge: auto` now squash-merges each verified unit by default, and deletes the merged branches.
  Behaviour change on upgrade: the harness used to push the unit head to the target as a fast-forward and never deleted a
  branch. Now it calls the forge's merge, pinned to the verified head, so the target gets one commit (the PR title and
  ` (#<pr>)`, with the trailers `L4-Unit`, `L4-Verified-Head` and `L4-Run`; `unit.merged` records `merge_commit`,
  `method` and `raced`), and, once the forge shows the PR merged, it keeps the verified head at
  `refs/l4/merged/<framework>/<name>` and deletes the unit branch under a lease (and the archive branch after the archive
  merge). A branch a person pushed to after the merge stays (`unit.branch_kept`); a plan step also cleans up to five
  branches of earlier merges. The lock ref is not deleted. The forge's token must be allowed to merge PRs; a forge that
  refuses a squash stops the plan with `merge_refused`. To keep the old behaviour set `yolo.merge.method: fast-forward`
  and `yolo.merge.delete_branches: false`. The evidence link in a PR body now names the head commit, not the branch
  (L4-YOLO-008, L4-YOLO-032, L4-YOLO-033).
- The archive step no longer builds a worktree for a merged unit whose folder is already archived on the base.
- The hand-off refreshes the PR body's evidence link only while the body is still the harness's own; a body a person
  edited stays.

## 0.4.11 (2026-10-17)

### Fixed
- A test of a context manager can prove its criterion. The zero-value run rewrote a `@contextmanager` function (or its
  red stub) to `return None`, so every `with` raised a `TypeError` before the test body ran, and no test could fail by
  assertion: on a consumer repository a unit halted after five red attempts on `search_phase`. Now a context manager's
  zero value enters and yields the zero value of what it yields, a generator yields nothing, and a function annotated
  to return a context manager or an iterator returns a null one. The `vacuous` message says how to test a context
  manager.
- A test gate reads every report it lists. With several reports in `gates.test.reports`, the harness read only the
  first one that existed, so the tests of the other suites were invisible to red, green and the verifier (on a
  consumer repository with three Python projects, the 423 tests of two suites). Now every listed report must exist (else
  `report missing: <report>`), and the reports are merged; a test in two reports keeps its worse result.

- Doctor's CI-003 no longer lists a job that a `typecheck` or `build` gate mirrors: verification runs those gates in
  every round, but the row counted them only when a `yolo.profiles` entry named them. It also ignores `uv run`'s
  `--directory`, `--project`, `--package`, `--frozen`, `--locked` and `--no-sync` options when it compares commands.

### Changed
- The adoption docs and the `l4 init` note name the public harness first: the plain `--action` form needs no deploy
  key for any repository. The copy form and the deploy key are for a private harness.

## 0.4.10 (2026-10-17)

### Fixed
- A finding a person rejects with a `WHEN … THEN …` becomes a fix task even when it cites no criterion and the parent
  has several requirements. The fix-unit planner put a scenario under the cited criterion's requirement, else the
  parent's only one, and dropped it otherwise, so the unit escalated with `no finding of this round can be converted
  into a fix task`. That is the path the 0.4.8 runbook gives for `task <key> is ticked as already satisfied, but its
  text is not done`: on a consumer repository, the reject of that finding stopped the delivery plan. Now the scenario
  goes under an ADDED requirement of its own, `<finding title> — finding <id>`, in the parent's first capability by
  name, as a feedback item's does. A judge's spec-gap suggestion that no person asked for is unchanged.

## 0.4.9 (2026-10-17)

### Fixed
- The zero-value run finds the modules a test imports in a workspace layout. It looked each import up under the
  repository root and `src/` only, so in a uv workspace, where each member keeps its code under
  `packages/<name>/src/<namespace>/<name>/`, it found no module to vary and refused every test of existing behaviour
  with `no project source module is imported by those tests`. On a consumer repository, four of six units lost a red
  attempt to it, and one unit then proved a scenario that pins existing behaviour with tests of the new path. Now an
  import is also looked up under every directory named `src` and every directory with a `pyproject.toml`,
  `setup.py` or `setup.cfg` (and its `src`), from git's tracked and not-ignored files. The head stubs of run (b),
  the verifier's audit sampling and the proof of tests people wrote use the same lookup.

## 0.4.8 (2026-10-17)

### Fixed
- A task that an earlier task already did no longer writes a copy of tests that exist. A red step had to add new test
  functions even when an earlier task of the unit had written and proved the tests of every criterion it cites, so
  each such task added a near-copy of them (on a consumer repository, four classes that assert one contract, and about
  4,400 test lines across four units). Now a red step may add no test and report `criteria_ids` and
  `tdd_exemption: {reason: "already_satisfied by <task>"}`. The passing tests that already trace those criteria are
  then its proof, confirmed as new tests are (the earlier red, the zero-value run, the base run), and the task is
  committed `already satisfied` with no test change.
- A test fixture shaped like a token no longer halts the unit. A red step wrote a redaction test whose fixture spells
  a token whole, as the file's existing tests do; the push scan refused the push and the unit halted with `secret in
  the outgoing commits`, and the plan stopped. Now each implementer step's changes are read for secrets before any
  gate or commit: a hit discards the attempt and tells the agent to build such a value from parts at run time
  (`"mk_" + "agent_" + "A" * 24`), and the next attempt gets that advice. The contract template says the same up
  front. The push scan stays as the last net.
- The confirmation by an earlier red holds for tests in a class. It turned `pkg.tests.test_x.TestY::test_z` into the
  path `pkg/tests/test_x/TestY.py`, found no file, and confirmed nothing, so every such criterion took the zero-value
  run and the base run.

### Added
- The judge checks each task ticked as already satisfied against its own text. The prompt lists those tasks with the
  criteria and tests that proved them, and the reply answers `satisfied: [{task, holds, evidence}]`. A `holds: false`
  is a major finding (`task <key> is ticked as already satisfied, but its text is not done`) that goes to a person.
  Before, a task whose criteria an earlier step satisfied was ticked although its own work (a README line) was never
  done, and the round passed. The judge prompt is `judge@9`.
- The red prompt says when to add no test, and that `already_satisfied` needs the task's own text to be true. The
  skill's `spec.md` has a **tasks** rule: put a behaviour's tests in the task that implements it, write no gate-only
  task, and give a document edit a check that a red step can test.

## 0.4.7 (2026-10-17)

### Fixed
- A unit whose verification passed because a person accepted a hold is merged again by a `merge: auto` plan. The hold
  (for example `the diff is longer than 120000 characters`) was accepted, and the next round reused the judged steps
  without calling the judge. That round did not carry the judge's answers to the plan's accepted review findings, so
  the merge guard found none and the plan waited with `accepted_finding_open`, every finding `no answer recorded`. A
  resumed round now records the answers of the round it reuses again, with `reused_from`.
- A judge reply that leaves out an accepted finding or a feedback item it was asked about is asked once more. The
  second call names the missing ids. A valid second reply is the verdict (`reply: retried`). A broken second reply
  keeps the first verdict. Before, the reply counted as valid, the finding was `not answered`, and a feedback item
  counted as not addressed.

### Added
- `l4 yolo waive PLAN F-id --reason TEXT [--withdraw] [--yes] [--no-run]`: a person (or an agent, when
  `yolo.review.accept_by_agents` is true on the base branch) waives an accepted finding of an active plan on record.
  The merge guard counts it as answered and the harness merges the unit itself, through its guarded merge. The
  report and `l4 yolo status` show the waiver.
- For a plan that waits with `accepted_finding_open`, `l4 yolo status` names the ways out in its `Next:` line:
  `l4 retry` when the verifier gave no answer, `l4 feedback add` when the code must change, `l4 yolo waive` when the
  finding needs no handling.

## 0.4.6 (2026-10-17)

### Fixed
- A unit no longer loops on a rejected verification hold after the fix was given as feedback. The round raised a hold
  (for example `the diff is longer than 120000 characters`), a person rejected it in prose with no `WHEN … THEN …`, and
  the round escalated with `no finding of this round can be converted into a fix task`. The person then gave the fix
  with `l4 feedback`, the feedback fix unit finished and round 4 judged every item fixed, but the old reject stayed in
  force: the same hold came back, the verdict was FAIL, and a retry repeated it. Now a feedback-only fix unit consumes
  the rejects its round could not convert: the verifier drops a reject recorded before a `fix.spawned` with
  `feedback_only: true` (so a ledger written by 0.4.5 and older needs no repair), and new ledgers list those
  questions in `fix.spawned.consumed` and mark the event `lists_unconverted: true`, so that only the listed rejects end.
  A hold that is raised again is asked as a new question on the fixed code.
- The escalation `no_convertible_finding` now names its way out. `l4 status --unit`, `l4 status --json`, the refusal of
  `l4 run --unit` and the note on the merge request say that a retry alone repeats the same verdict, and to give the fix
  as feedback (`l4 feedback add --unit U --kind behaviour --when … --then … --text …`, then the git lines) before
  `l4 retry`. Other causes keep their text. The runbook has the procedure (7.3.1).
- `l4 questions answer Q-NNN --unit U --text TEXT --replace` replaces the answer of an answered verdict question on
  purpose. Before, the command refused it and the only way was a hand edit that nothing explained. The new answer is
  recorded as a new verdict (the latest per target wins); the previous answer stays in a comment under it, and the
  commit says `(answer replaced)`. Without `--replace` the refusal stays and its `Fix:` line names the flag. A
  clarification answer is still changed by hand (L4-QMD-006).
- `l4 yolo status` no longer shows a dependency where there is none. A plan runs one unit at a time, and a unit with no
  prerequisite left said `waits for <unit> (not integrated)`, the same words as a real dependency. It now says
  `waits for its turn: <unit> runs first (one unit at a time)`.

## 0.4.5 (2026-10-16)

### Added
- A heartbeat line while an agent step runs: `task <k> <phase> attempt <n>: <profile> working 6m, 14 tool calls, last
  activity 20s ago`, with `, <m> tool calls open for <t>` while a tool call is open. The key `implementer.heartbeat`
  sets the interval (default `2m`, minimum `30s`, `0` turns it off). The line holds counts and times only, and no text
  of the agent.
- `implementer.idle_timeout` (default `10m`, minimum `1m`, `0` turns it off) and the ledger event `agent.idle`: an agent
  that prints nothing for that time and has no open tool call is stopped, and the attempt fails with a reason that names
  the key.
- `l4 status` has the column `LAST`. `l4 status --unit` has the lines `Last activity:` and `Open run:` (with the CI link
  of the run), and `--json` has `last_activity` and `open_run`. `l4 yolo status` shows `last activity` and `open run`
  of the current unit. The event `run.started` records the CI link, as `run.started.ci_url`.
- The red gate line `red: <n> new tests fail, as intended`, and `gate.finished.red_new_failing`.
- The job summary of GitHub Actions lists each finished task.
- The runbook procedure 4.6 `Is the job stuck?`.

### Changed
- An idle agent gets SIGINT and 5 seconds before the kill, and is not stopped while a claude-code, codex or kiro-cli
  tool call is open.
- The failure reasons of an idle stop and of the step time limit (30 minutes) name the cause.
- The step start line is at INFO.
- The new keys need the 0.4.5 pin before the config edit (the schema is strict).

### Fixed
- A person's answer can now open a pre-existing test that the task must change. Before, the test path freeze put such
  a test back in every green attempt, even after a person accepted the harness's own question that named the file and
  the edit (the unit halted on `green broke existing tests`, and no `task.unfrozen` was recorded). Now an answer
  (`accepted` or `answered`, on the same conditions as for a red test or a support file) that names a tracked test file
  that the red step did not touch opens it for that task's green. It is recorded in `task.unfrozen`, listed in the green
  prompt, accepted by the verifier, and `l4 questions show` says that an accept unfreezes the pre-existing test. The
  red tests of the task and the ignore files stay frozen.
- A rejected verification hold of a kind the harness cannot derive a task from (for example `the diff is longer than
  120000 characters`) whose reason ends with a sentence `WHEN … THEN …` is now a behaviour finding with a fix task, not
  an escalation (`no finding of this round can be converted into a fix task`). Without the scenario the unit still
  escalates, and the question of such a hold no longer promises a fix unit: it asks the reason to end with the scenario.
  Scope and coverage holds are unchanged.
- `l4 feedback add --unit U` no longer needs the unit's own branch checked out: a detached HEAD, or a local branch of
  another name, at the head of `origin/<unit branch>` is accepted (L4's worktree cache may hold the branch). The command
  says which branch the feedback goes to and prints `git push origin HEAD:<unit branch>`. From any other commit the
  refusal says how to get there, including `git switch --detach origin/<unit branch>` and `git worktree list`.

## 0.4.4 (2026-10-16)

### Added
- Escalation along `roles.implementer`: `implementer.escalate_after` (default 2, `0` turns it off). After that many
  failed attempts of one task phase on one profile, the next usable profile of the chain takes the phase, in a fresh
  session, with the reasons of the earlier failures. The harness records `implementer.escalated` or
  `implementer.escalation_skipped`. A move never parks a unit and never takes a profile that would leave no independent
  judge. `task.attempt_failed` and `breaker.tripped` name the profiles; the halt detail lists them.
- The retry note: the `--reason` of `l4 retry` and `l4 resume` on a unit halted on `max_task_attempts` reaches the
  implementer of that task, as a capped and redacted data block, until the task is done. `prompt.rendered` records
  `retry_note`. `l4 status --unit` prints a `Retry note:` line.
- Doctor check CFG-009 (warn): an escalation that cannot act (`escalate_after` not below `max_task_attempts`, or two
  profiles with the same adapter and model).
- New progress lines for the escalation, the failed attempt with its profile, the halt with its profiles and the retry
  note.
- The runbook and the skill (`adopt.md`, `operate.md`) teach the cheap-first chain and the note.
- `agent.finished` records `context_peak_tokens` (OpenCode, Claude Code: the largest input of one call, cache
  included) or `context_peak_percent` (Kiro CLI), and the progress line ends with `, context peak <n>k tokens` or
  `, context peak <p>%`. Codex and a command give none. `RunResult` has the new fields `last_message` and
  `result_problem`.
- The ledger event `result.normalized{task, phase, attempt, source, fixes}` and its progress line
  `L4 repaired the result (…)`. The event holds no text of the agent.

### Changed
- A chain of two or more profiles moves a failing task phase to the next profile by default. Each profile has its own
  attempts; the last one has `max_task_attempts`. Set `implementer.escalate_after: 0` for the old behaviour. The tasks
  of a fix unit do not move.
- The config key needs the 0.4.4 pin before the config edit (the schema is strict).
- The `# Output` section of a prompt-contract step (OpenCode, Kiro CLI, command) is the locked template `output@1`
  (`template_version` ends with `+output@1`). It asks for `status` and `summary` first, names `criteria_ids`,
  `suppressions` and `notes_for_verifier` as optional, shows a smaller schema and no longer asks for the fields that the
  harness derives (`phase`, `task_ids`, `files_changed`, `tests_added`). The prompt of Codex and Claude Code does not
  change.
- The harness repairs the result object of a step before it validates it (`result.normalized`): a missing `summary`, a
  `status` that is not allowed, a text over its limit, a malformed question, suppression or criterion id, and the
  fields that the harness derives. The harness never adds a question, never changes `blocked` and never adds a
  suppression. It can take the object from the last JSON object in the agent's final message, never from a file of the
  worktree.
- An attempt fails for its result only when the agent delivered no result object
  (`the agent's result is invalid: no result was delivered`). A `blocked` result with no question is not a failed
  attempt: it keeps raising one question made from its summary.
- The red check no longer reads the `tests_added` list of the agent. It uses the tests that the JUnit diff finds.

## 0.4.3 (2026-10-16)

### Fixed
- `l4 questions accept` and `answer` pushed the answer to the unit branch and relied on that push to start a run.
  GitHub runs a push with the workflow file of the pushed branch, which still pinned the old harness after the base had
  moved its pin: the pin guard (CFG-008) did no work and the unit did not resume. The push also started the
  repository's own CI on a unit that was in the middle of TDD, and its red tests left a misleading red check on the
  pull request. The commit now carries `[skip ci]` and the command starts a run on the base branch, as `l4 retry` does
  (`--no-run` skips it; a refused start prints how to start one by hand and exits 0).
- `l4 upgrade` now names the open unit branches on origin (from the remote-tracking refs it has, no network) whose own
  workflow copy pins another harness than the new one, and says that a push to one of them does no work and that runs
  start on the base.
- The runbook (7.1) and the skill say to start a run on the base after a hand-edited answer is pushed.
- A Python support file named in the heading of a task's section in `tasks.md` (for example `## 1. Root conftest.py`) now opens in green like one named in the task line, under the same trust check (an active plan or the base branch); a heading of another section, a glob or `../` opens nothing.

## 0.4.2 (2026-10-16)

### Added
- `l4 questions`: list the open questions of a unit, `show` one, `accept` the clarifier's suggestion or `answer` it
  with a text. The command edits `questions.md` on the unit branch, commits and pushes, which resumes the unit in CI.
  `--no-push` shows the change and writes nothing. An agent follows the same rule as `l4 yolo accept`
  (`clarifier.answer_by_agents`). Before, the command was listed in `l4 --help` but stopped with exit 2.
- A test-support file that the task's own reviewed text names (for example `` `conftest.py` ``) can be changed in the
  green step of that task. The file must keep its old statements, must not redefine a name and must not patch the
  code of the unit. The red tests of the task stay frozen. The run records `task.unfrozen{reason: "named_by_task"}`.
- A person's answer can unfreeze a named test-support file (never an ignore file).
- `l4 yolo findings --json` gives `accept_refusal {why, fix}` for a subject that cannot be accepted, and the text view
  prints `accept: not available: <why> (<fix>)`.

### Changed
- The green prompt template is version 5: it names the files of "Files this task names" and says how to change them.
- Every command and option that is not implemented says `(not yet implemented)` in `l4 --help` (`l4 unlock`,
  `l4 status --rebuild`, `l4 resume --extend-iterations`, `--extend-cost`, `l4 run --time-budget`,
  `l4 verify --dry-run`). Each one still exits 2. The runbook lists the same set.
- The `cache.seeded` ledger event records its digest as `digest` (it was `key`, which default secret scanners report
  as an API key in a consumer repository's archived ledgers). Readers accept both.
- The note of a blocked green question never offers an edit that the harness refuses.
- The text of a unit pull request and of an archive pull request says who merges it: a person, or the harness when the
  unit is in an active delivery plan with `merge: auto` (it said the harness never merges it).

### Fixed
- `validate_plan.py` read a comment after a key with a nested block (`hold:   # note`) as the key's value, so it
  ignored `yolo.hold` and reported the held units as uncovered.

## 0.4.1 (2026-10-16)

Review resolution and the lessons of the first adoption on a real consumer repository. This release added features
and changed the readiness review.

### Added
- `l4 yolo findings`: the findings of the latest review with a `Resolve:` line per criterion, and the criteria that come
  back (`persistent`).
- `l4 yolo review --worktree`: review the working tree before a push (dry by default; `--record` writes the review to
  the ledger and judges again everything the ledger does not hold).
- `l4 yolo accept` with conditions (two judged versions of the text, no blocking finding) and a reason that the
  implementer and the verifier receive; the merge guard keeps an accepted finding open until the verifier answers it.
- `yolo.review` budgets (`max_file_chars`, `max_folder_chars`, `max_dependency_chars`), `accept_after_rounds`,
  `accept_by_agents`; `yolo.hold` and `l4 init --hold-existing`.
- System One keys rendered into the workflow; Laya as the default System One (`l4 init --s1 laya|jev|none`).
- The pin guard: a run whose harness pin differs from the base branch's workflow does no work and warns.
- Doctor adoption checks; `validate_plan.py` uses the review's budgets and file set.

### Changed
- The readiness review judges only material it has not judged (the material key covers the text, the templates and
  the schema); minor-only findings count as READY; dependency material is shown spec first.
- The judge prompt is version 8. No `l4 eval --compare` baseline was made for it.
- Every material key changed, so each subject is judged once more after the upgrade.

## 0.4.0 (2026-10-15)

### Added
- Delivery plans (`l4 yolo`): plans of OpenSpec and Kiro units with dependencies, a readiness review by the judge in
  CI, activation by a person, a guarded fast-forward merge into an integration branch, `l4 yolo draft`, the plan
  validator and the plan skill reference.
- `OPENCODE_API_KEY` for OpenCode's own providers.
- The experience graph (manual `l4 kg` and `l4 lessons promote`).

### Changed
- Worktrees and unit locks are keyed by repository.

## 0.3.0 (2026-10-14)

### Added
- Operator commands: `l4 retry`, `l4 restart`, the causes shown in `l4 status`, `same_failure`, a spec push that
  re-enters the unit, Kiro reopen.
- The GitLab base branch; `l4 upgrade --action-repo`.

### Changed
- The repository is `OWNER/l4`.

## 0.2.1 (2026-10-13)

### Fixed
- Coverage survives a test that replaces `sqlite3.connect`.
- The GitHub workflow uploads `.l4-out`.
- Corrections in the runbook.

## 0.2.0 (2026-10-13)

### Added
- Human feedback (`l4 feedback`).
- The adoption kit: the harness as a GitHub setup action.
- The `l4` skill.
