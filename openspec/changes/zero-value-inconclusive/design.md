## Context

The red step proves that new tests discriminate with *variant runs*: the test gate run again against changed
production code. Run (b) `test-zero` zeroes the red stubs; `test-presatisfied` zeroes every public function of the
modules the candidate tests import and of the modules changed since the unit base; `test-base-run` swaps the changed
production files to the unit base and sets the added ones aside; green's `test-at-red` swaps them to the red commit.
The verifier runs the same functions in step 4 (`test-extra-zero`, `test-extra-base`) and step 4a (the audit). Each
caller reads the variant's report as if the run had worked.

**The reproduction** (an investigator drove the 0.4.14 library against a clone of the consumer repository; names
here are neutral):

| Task | Run | 0.4.14 | With the two experimental fixes (keep a callable-returning function; keep-going) |
|---|---|---|---|
| 2.2 (no new test, 11 criteria) | `test-presatisfied` | exit 2, 0 tests, 45 collection errors (`@telemetry.traced(...)` → `TypeError: 'NoneType' object is not callable`) | exit 1, 2001 tests, 0 collection errors; the 11 candidates ERROR in setup: `assert telemetry.init(...) is True` → `assert False is True`, in a fixture of a test file the unit added |
| 2.2 | `test-base-run` | exit 2, 0 tests, 1 collection error (the unit's own test file imports the added module) | exit 1, 1987 tests; the candidates' module still cannot import at the base |
| 3.1 (new tests, 6 criteria) | `test-presatisfied` | exit 2, 0 tests, 47 collection errors | exit 1, 2017 tests; 5 criteria's test ERRORs in setup by the same fixture assertion (in the step's new test file); the version-pin test passes |
| 3.1 | `test-base-run` | exit 2, 0 tests, 2 collection errors (two unrelated test files import the added module) | exit 1, 1989 tests; the candidates ran |

With only the callable fix and the fixture assertion removed by hand, the five span criteria of 3.1 were confirmed by a
body assertion (`assert 0 == 1`). In every 0.4.14 row the message was `not discriminating: … (its tests still pass …)`.

## Decisions

**D1. Classify per test, not per run.** The task statement says a run with more collection errors than the real run is
inconclusive. Taken per run, that voids every base run of a unit that adds a module: the base run *must* set the added
module aside, so a test file that imports it fails collection (row 3.1/base: two unrelated files failed while every
candidate ran). So the classifier has three levels:
- *run*: no report, or no test executed (`TestReport.executed == 0`) → every candidate is inconclusive;
- *test*: a candidate absent from the variant's report is inconclusive when a production module failed to import there
  (D1a decides when the cause is the unit's own files); one that failed by assertion is a
  *proof*; one that passed, or failed or errored by another kind, is *no proof* (unchanged check 5: an error shows the
  test touched the answer, not that it checked it);
- *criterion*: confirmed when any test is a proof; inconclusive when none is and any is inconclusive; refuted ("not
  discriminating") only when every test ran and none is a proof.
The new collection errors (those the real run does not have) are named in the reason, so "more collection errors"
still reaches the person, as the cause of the missing tests.

**D1a. The cause decides (review M1).** In a zero-value run (not the base run, which only confirms) a test the unit's
own files made unrunnable is *no proof*, as D6 does for a fixture assertion: skipped only there; absent because the
collection error of its module failed, in the unit's own test module (`own_statement`), at a statement that is not an
import, whatever the deepest frame (a pre-existing helper the module calls raised: round-2 N1); or absent while its module collected (collection-time code read a production answer, a `parametrize` over it).
Inconclusive stays for a failing import statement of the own test module, that is a PRODUCTION module that failed to import.
Round 2 also narrows the pin rule (N3: not the repository's own distribution, a whole-token name with a version beside it
in the criterion's text, a compared version), counts a proof from any pass of the keep loop (H1: one extra pass keeps
nothing by annotation) and reads module-level calls of pre-existing test-support modules (m1). Otherwise an agent that writes `if not got:
pytest.skip()` turns "not discriminating" into a hold, and a person's `accept` into a pass.

**D2. Precedence: the agent's fault wins.** When at least one unconfirmed criterion is refuted, the attempt fails as
today (counted, escalating), and the message lists the inconclusive ones apart (`inconclusive: …`) so the retry is
not told to fix what it cannot. Only when *every* unconfirmed criterion is inconclusive is the task held (D7).

**D3. Order and roles of the runs.** The order stays: earlier red, zero-value run, base run. The base run can only
confirm: a test that passes at the base, or cannot import there, says nothing about a criterion the unit's earlier
task already satisfied (a preservation criterion passes at the base by design). So:

| zero-value run says | base run says | criterion |
|---|---|---|
| proof | (not run) | confirmed |
| refuted | proof | confirmed |
| refuted | anything else, or skipped | refuted (the agent's) |
| inconclusive | proof | confirmed |
| inconclusive | anything else, or skipped | inconclusive (held) |
| nothing to vary, or no project module | proof | confirmed |
| nothing to vary, or no project module | anything else, or skipped | refuted, as today |
| dependency only (D9) | (not run) | inconclusive: held for a person |

A *skipped* base run (manifest changed, symlink, no unit base) was not made, so it is not classified; its reason is
kept in the message as today (open question 1).

**D4. Keep-going everywhere; the gate result travels.** Every variant run merges
`PYTEST_ADDOPTS=--continue-on-collection-errors` (harmless for a non-pytest gate, which ignores the variable; the trace
plugin's `-p l4_trace` is already in it). `run_with_code_of` returns the `GateResult`, so a caller can tell no report
(`report is None`), no test (`executed == 0`) and a missing id apart, and quote the log.

**D5. What zeroing keeps.**
- *By annotation* (public mode): a function whose return annotation is `Callable` (any module prefix, subscripted or
  not, also `X | None` / `Optional[X]` of it) or `type`/`Type` AND whose name a module of the varied set applies at
  import time (`import_time_names`: decorators and decorator-factory calls, module-level and class-level calls; review
  M4) keeps its body: the zero value of a decorator factory or a class factory is not a value a test can meet, it
  breaks the import. A function that predates the unit and that nothing applies at import is zeroed, so an honest test
  of it (`f = make_adder(2); assert f is not None; assert f(3) == 5`) keeps its proof. Red-stub mode (run (b)) needs no such
  rule: a stub is `raise NotImplementedError` in run (a) as well, so a stub that a module applies at import time
  already fails run (a) at collection (`tests not collected individually`), and run (b) never sees it. (An identity
  decorator for a `Callable[[A], A]` stub was considered and dropped for that reason.)
- *By traceback* (public mode): when a zero-value run leaves a candidate inconclusive, the harness reads the
  tracebacks of the run's new collection errors (the JUnit `<error>` bodies) and of the candidates' setup assertions
  outside the unit's files (D6), takes the names *called* on their code lines (`a.b.c(` → `c`, `@a.b(` or `@a.b` →
  `b`), keeps every zeroed function of the varied files with that simple name, and runs again. A name that is not a
  zeroed function is ignored, so an ordinary word on the line keeps nothing. The names also include those called by
  the module-level statements of each production module in the failing traceback (review m1: `_CFG = load()` above
  `RATE = _CFG["rate"]`, where the failing line calls nothing).
- *Bound*: at most 2 reruns (3 runs in all), and a rerun only when it keeps at least one new function; at most 50
  functions are kept per check. Two layers cover the cases seen (one decorator factory, or a factory whose real body
  calls a second one at import time); each rerun is a whole suite run (about 2 minutes for the consumer).
- *Record*: `zero.kept{gate, rerun, cause: annotation|collection|setup, functions}` (functions as `path::qualname`, at
  most 50), so a person sees what ran real.

**D6. A setup assertion counts in the unit's own files only.** A fixture's assertion on a production answer is the
unit's test checking that answer when the unit wrote the fixture: the setup-phase assertion of a candidate counts as a
failure on the zero values when the deepest repository location of its traceback is a test or support file that the
unit added or changed (the worktree's changes and `git diff --diff-filter=AM <unit base> HEAD`). A pre-existing shared
fixture that asserts (a database ping in `conftest.py`) would fail every test that uses it and confirm every vacuous
test, so outside the unit's files it is inconclusive, and the keep loop of D5 tries to make the setup pass so the body
decides. A setup error of another kind stays no proof (check 5's advice, `assert result is not None` first, is what
turns it into an assertion). Rejected alternative: always keep the fixture's function and let the body decide. It is
stricter, but a body that then fails with `IndexError` on an empty list would be *refuted*, turning row 2.2 (fixable
today by the rule above) into an agent failure.

**D7. An inconclusive check holds the task with a `harness` question.** The hold reuses the `blocked` path
(`TaskOutcome("blocked")`, which uses no attempt and starts no escalation, L4-IMP-017): the step's changes are
discarded, one question is raised and committed, the unit goes to `awaiting_human` (through `clarifying` when a
clarifier runs, which never takes a `harness` question; exit 11),
and a plan waits (`unit_awaiting_human`, no chained run, L4-YOLO-012). The loop must return, never `continue`: a
`continue` would spin, since nothing counts the attempt. Why a new kind:
- `technical` is in the default `clarifier.auto_accept_kinds`, so the clarifier or an agent could accept an override
  of a harness check; `product`/`ambiguous` mean something else and can be auto-accepted by configuration;
- `verdict` is read by `verdicts.py` and the planner as a verifier verdict (an answered one routes the unit to
  `verify`), and `raise_questions` lets it have no blocking task.
`harness` behaves like `verdict` for who may answer (a person, or an agent only with `clarifier.answer_by_agents: true`
on the base) and for the clarifier (never asked), and like an implementer question for blocking (it holds its task).
The answer's first word decides: `accept` or `retry` (`dismissed` reads as `retry`); anything else is not an answer
and keeps holding, with the planner saying so.

**D8. What `accept` means.** The next run runs the red step again (one more agent step: the trade-off for not
persisting the held tree). When the same check is inconclusive again for criteria that the accepted question names
(read from its `question.raised` event, which the harness wrote, not from the editable file), and the answer's digest
is recorded in a `question.answered{by: human}` event (the unfreeze rule; `by: agent` when an agent answered under
`clarifier.answer_by_agents`, found from the `By:` line of the commit of `l4 questions`), those criteria count when
their candidate tests are among the `tests` of that `question.raised` event (an answer about one test does not carry a
later different one; review M1): pre-satisfied ones with
`proof: pre_satisfied, via: human_override, question, answer_sha256` and the passing tests of run (a) as
`discriminating`; run (b) ones with `proof: zero_value, via: human_override`. An agent's answer is labelled
`via: agent_override` everywhere, the judge included (review m3). A conclusive result wins over the
answer: a confirmed criterion is confirmed, a refuted one fails the attempt. `check.accepted` records the use. An
override is never evidence for a later task's earlier-red confirmation. `retry` needs nothing from the harness: the
answer unblocks the task, and its text reaches the red prompt as any answer does (L4-CLR-006).

**D9. A dependency check is held, never passed (round 3).** A test is *dependency-only* when its function, parametrize lists and defaults use no
name bound to a module inside the repository, no module-level definition of its file other than a constant, no fixture beyond pytest's built-ins and
its own `parametrize`, reach no project code by a string, and read a dependency's version with a literal name. `depcheck.dependency_only` is now only a
CLASSIFIER: a criterion whose every candidate it accepts is `inconclusive` ("its tests import no project module: the zero-value check cannot judge
them") and takes the existing hold with a `harness` question; every other criterion with no project import is refuted as on 0.4.15. Neither is a
pass, so the precision of the heuristic decides the message a person sees, not whether an agent's test is believed (rounds 1-3 kept finding test
shapes, `version(x) != ""`, `version(x) == version(x)`, that no static rule could tell from a pin). `not_applicable` is never written; readers keep
accepting it in old ledgers (L4-VER-051).
Step 4a samples pre-satisfied criteria first but audits at most `MAX_AUDIT_PER_ROUND` (2) per round and is off without
a verifier agent: the label is the guarantee, the audit is not.

**D10. Evidence in the committed ledger.** `excerpt.py` says the failure excerpt goes in the prompt fence, never in
the committed ledger. This change narrows that: the ledger gets `excerpt` (at most 600 characters, the audit's bound)
made only of `E` lines and the deepest repository location line. The raw text is redacted by `wb.redactor` BEFORE it
is cut, and the result again (review M3: a cut inside a secret leaves a prefix no redactor recognises; the same order
holds for the reasons of `variant.classify` and `test_outcome`), on `gate.finished` of a test gate that failed with no report, no test executed or a collection error, and on
`task.attempt_failed`. Precedents: `task.attempt_failed.reason` already names agent-written tests and error classes,
and `ci.failed.tail` already carries a redacted job log end. The ledger field is never read into a prompt. The
artefacts line tells the truth about uploads; a gates-only upload is deferred (proposal).

**D11. The verifier.** The audit passes its head run as the real run. An inconclusive confirmation records
`AuditRecord(status="inconclusive", reason=…)`, removes the file, raises no finding and is listed in `verification.md`
(the criterion keeps its implementer evidence). A not-applicable audit test is accepted with its label.
`discriminate_extra` returns the inconclusive ids with their reasons (`inconclusive: <reason>`); the verifier's minor
finding then says that, not "passes against the zero values and on the base". A test chore whose added tests are all
inconclusive is held with a harness question (`check: tests`, review m2), not accepted: accepting it would let an agent
pass a chore with tests made unrunnable on purpose; the no-unit-base case, where no run can be made at all, is still
accepted. The extra-proof bound becomes two gate runs plus at most two keep reruns of the zero-value run.

**D12. The two evidence tasks, traced through the new rules.**
- *2.2*: `traced` is kept by annotation → the run imports every module (verified: 2001 tests, 0 collection errors) →
  the 11 candidates fail in the setup of their fixture by assertion, at a line of a test file the unit added
  (verified with `git diff --name-status <unit base> HEAD`) → confirmed (D6). No base run.
- *3.1*: same run → the five span criteria fail in the setup of the step's new test file by assertion → confirmed.
  The version-pin criterion: its test is dependency-only if it reads a dependency's version without a project name
  (inferred from the test's name, which says it checks a dependency's verified version pin; its source was not kept)
  → not applicable.
  If it is not dependency-only, the zero-value run shows it passing (verified: it is not among that run's
  failures and errors) → refuted → the attempt fails for that
  one criterion, with the others confirmed: the retry has a concrete fix.
Neither needs the hold; the hold is the backstop for the next shape the keep loop cannot fix.

## Risks

- A wrongly kept function (a zeroed name that also appears called on a traceback line for another reason) runs real,
  so a test that only checks it can pass instead of failing: a refutation the agent did not cause. The names come
  only from the failing lines of new collection errors and of foreign setup assertions, which bounds it.
- The setup rule lets one fixture of the unit's own file confirm every criterion whose tests use it (11 in row 2.2).
  That is the unit's own assertion on a production answer; the judge reviews their tests (the audit samples at most two
  criteria per round).
- The dependency-only rule can accept a test that reads a dependency but checks nothing of the criterion; the label
  puts it before the judge.
- `harness` questions are new in `questions.md`: a harness before 0.4.16 parses the kind as unknown; an answer written
  for it is still read as an answer by that older harness, which has no hold to consume it.

## Decisions on the open questions (owner, before the build)

1. A *skipped* base run for a project the zero-value run cannot read (a non-Python unit) behaves as today: it fails
   the agent, with the skip reason in the message.
2. A criterion about the interpreter (`sys.version_info`) reads only the standard library, so it is not
   dependency-only and stays not discriminating when pre-satisfied.
3. No PR-label answer for a `harness` question now.
4. `accept` re-runs the agent step once (the held work is not persisted); that is accepted.

## Follow-ups

- A PR label that answers a `harness` question (`l4:retry` already restarts a halted unit), once the question has been
  used on a real unit.
- Keep the held work for `accept`: persist the discarded step so that an accepted claim needs no second agent step.
