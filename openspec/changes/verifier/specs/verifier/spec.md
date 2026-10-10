## Purpose
Define the L4 verifier: an independent, deterministic-first verification ladder that re-runs gates and tests in a fresh worktree, combines tracing evidence with judge panels, aggregates a verdict by code, writes `verification.md`, and turns failures into fix units.

## ADDED Requirements

### Requirement: L4-VER-001 (part a) Fresh worktree and no transcripts
The verifier MUST run in a fresh worktree checked out at the unit branch head and MUST NOT receive the implementer's transcripts; the only implementer-authored input is `notes_for_verifier`, rendered into the prompt labelled as unverified hints.

#### Scenario: SCN-VER-N45 (−) Implementer transcript is withheld
- **GIVEN** an implementer result whose `notes_for_verifier` says "all edge cases covered" and a stored implementer transcript
- **WHEN** the verifier prompt is assembled
- **THEN** the note appears inside a block labelled as an unverified hint, no transcript text appears in the prompt, and the worktree is newly created at the unit branch head SHA

### Requirement: L4-VER-001 (part b) Independence against every implementer profile
Verifier agent and judge selection MUST honour `verifier.independence` against every implementer profile that authored commits in the unit (including fix units and fallbacks), using the vendor of the model actually served: `different_vendor` (default) excludes all those vendors, `different_model` excludes those model ids.

#### Scenario: SCN-VER-27 (−) Same-vendor judge excluded
- **GIVEN** implementer vendor anthropic and judge chain `[judge-opus, judge-sol]`
- **WHEN** the panel is selected
- **THEN** `judge-opus` is skipped (`independence: same vendor`), `judge-sol` is used

#### Scenario: SCN-VER-N46 (−) A fallback implementer widens the exclusion
- **GIVEN** task 1.1 was implemented by `codex-sol` (openai) and task 1.2 by fallback `claude-sonnet` (anthropic), and the judge chain is `[judge-opus, judge-sol, judge-gemini]`
- **WHEN** the panel is selected
- **THEN** `judge-opus` and `judge-sol` are both skipped with their vendor as the reason and `judge-gemini` is used

### Requirement: L4-VER-001 (part c) No independent verifier means waiting
If no independent verifier agent or judge is available, the unit MUST go to `waiting_capacity` with reason `no independent verifier` and exit code 12; independence MUST NOT be relaxed at run time.

#### Scenario: SCN-VER-N47 (−) Only same-vendor judges are left
- **GIVEN** every profile in `roles.judges` shares a vendor with an implementer profile of the unit
- **WHEN** the panel is selected
- **THEN** phase becomes `waiting_capacity` with reason `no independent verifier`, exit code 12, and no judge is called

### Requirement: L4-VER-002a Verifier agent write scope
The verifier agent MAY only change paths matching `tdd.test_globs`, MAY NOT modify pre-existing tests or tests written by the implementer, and MAY only heal selectors and waits of tests it generated itself in the current round; every other change MUST be reverted by the guard and logged.

#### Scenario: SCN-VER-17 (−) Verifier agent touches production code
- **GIVEN** the verifier agent edits `src/` while writing tests
- **WHEN** the guard runs
- **THEN** changes outside `tdd.test_globs` are reverted and logged; only the tests remain

#### Scenario: SCN-VER-41 (−) The verifier agent cannot edit the implementer's tests
- **GIVEN** the verifier agent changes an assertion in a test the implementer wrote, while generating its own tests
- **WHEN** the guard runs
- **THEN** the change is reverted and logged; only the verifier's own new test files remain

#### Scenario: SCN-VER-26 (−) Healer-style expectation edit rejected
- **GIVEN** the verifier agent "heals" an existing Playwright test by changing an `expect` line
- **WHEN** the guard runs
- **THEN** the change is reverted and logged; healing is limited to selectors/waits in tests it generated itself

### Requirement: L4-VER-002 (ladder) Ladder order and hard stop
Verification steps MUST run in order 0 to 10; a hard failure in steps 0 to 3 MUST stop the ladder with verdict FAIL, evidence collected so far MUST still be written, and steps not reached MUST be recorded `not_run`.

#### Scenario: SCN-VER-N48 (−) A step 1 blocker stops the ladder
- **GIVEN** step 1 reports a blocker finding
- **WHEN** the ladder runs
- **THEN** verdict FAIL; steps 2 to 10 are recorded `not_run`; `verification.md` and `verdict.json` are written with the evidence of steps 0 and 1

### Requirement: L4-VER-002 (step 0) Preconditions
Step 0 MUST verify that the done-gate passes, that the branch contains the base branch head (otherwise the base is merged first per the worktree rules), and that the unit validates with `--strict`; any failure is a hard failure.

#### Scenario: SCN-VER-22 (−) Base branch moved with conflicts
- **GIVEN** the base branch changed a file the unit also changed
- **WHEN** step 0 updates the branch
- **THEN** a conflict task (TDD-exempt, reason recorded) is run by the implementer; verification restarts after it; on repeated failure the unit escalates

#### Scenario: SCN-VER-N49 (−) Unit no longer validates strictly
- **GIVEN** the unit's spec fails `validate --strict`
- **WHEN** step 0 runs
- **THEN** verdict FAIL with a blocker finding quoting the validator output, and steps 1 to 10 are recorded `not_run`

### Requirement: L4-VER-002 (step 1, part a) Outstanding guard violations
Step 1 MUST emit a blocker finding for every `guard.violation` or `guard.test_tamper` event of the unit whose offending change is still present at the unit head; a violation the guard reverted is only listed in the report.

#### Scenario: SCN-VER-N50 (−) Unreverted guard violation
- **GIVEN** a `guard.violation{path: .gitlab-ci.yml}` event whose change is still in the head tree
- **WHEN** step 1 runs
- **THEN** FAIL with a blocker finding naming the path and the event

### Requirement: L4-VER-002 (step 1, part b) Pre-existing tests are preserved
Step 1 MUST analyse the unit diff and emit a blocker finding naming the test id for every pre-existing test that is deleted, skipped (skip, xfail, only markers) or weakened (assertions removed or loosened).

#### Scenario: SCN-VER-02 (−) Deleted pre-existing test
- **GIVEN** the diff deletes `tests/test_billing.py::test_refund`
- **WHEN** step 1 runs
- **THEN** FAIL, blocker finding with the deleted test id; fix unit task "restore test_refund"

#### Scenario: SCN-VER-03 (−) Skip marker added
- **GIVEN** `@pytest.mark.skip` added to a pre-existing test
- **WHEN** step 1 runs
- **THEN** FAIL, blocker

### Requirement: L4-VER-002 (step 1, part c) Red-to-green freeze
Step 1 MUST verify for every task that test files, test-support paths and test-runner config sections are identical at the task's red commit and green commit; any difference is a blocker that no note or judgment can override.

#### Scenario: SCN-VER-16 (−) Assertion changed between red and green
- **GIVEN** a branch where a red test's assertion differs between the red and the green commit (e.g. history assembled outside the guard)
- **WHEN** step 1 runs
- **THEN** the red→green freeze check fails: FAIL with a blocker finding; no note or judgment can override it

### Requirement: L4-VER-002 (step 1, part d) Content scan for result manipulation
Step 1 MUST scan the unit's test-support and runner-config changes for result-manipulating constructs: pytest hooks `pytest_runtest_makereport`, `pytest_report_teststatus`, `pytest_collection_modifyitems`, `pytest_runtest_call` wrappers; jest/vitest custom `reporters`, `testResultsProcessor`, `testPathIgnorePatterns` additions; Playwright reporter or `grepInvert` changes; Go `TestMain` exiting 0. A hit is a blocker unless the task carries a human `[test-infra]` tag.

#### Scenario: SCN-VER-N51 (−) A result-forcing pytest hook is a blocker
- **GIVEN** the unit adds `pytest_runtest_makereport` to `tests/conftest.py` and no task carries `[test-infra]`
- **WHEN** step 1 runs
- **THEN** FAIL with a blocker finding naming the hook and file

#### Scenario: SCN-VER-N52 (+) The same hook under a human test-infra tag is listed
- **GIVEN** the task that adds the hook carries a human-written `[test-infra]` tag
- **WHEN** step 1 runs
- **THEN** no blocker is raised and the hook is listed in `verification.md` as an exemption

### Requirement: L4-VER-002 (step 1, part e) Support files never replace code under test
Test-support files MUST NOT monkeypatch, patch or assign the symbols the unit added or changed, and MUST NOT make any patch conditional on files or environment variables the unit creates; a hit is a blocker. Patching collaborators (clocks, network clients, environment) stays allowed. Python uses an AST rule; per-language rules are [U] until the change-0 fixtures report.

#### Scenario: SCN-VER-N53 (−) A conftest patch of a changed symbol is a blocker
- **GIVEN** `conftest.py` assigns `auth.login = fake_login` where `login` was added by the unit
- **WHEN** step 1 runs
- **THEN** FAIL with a blocker finding naming `auth.login` and the file

#### Scenario: SCN-VER-N54 (+) Patching a clock of a changed module is accepted
- **GIVEN** `conftest.py` patches `auth.time.time` (a collaborator) only
- **WHEN** step 1 runs
- **THEN** no finding is raised

### Requirement: L4-VER-002 (step 1, part f) Test-only dependencies added in green
Step 1 MUST raise a deterministic major finding for each test-only dependency (pytest plugin, jest reporter, test runner) added in a green commit; the same dependency added in a red commit MUST be accepted.

#### Scenario: SCN-VER-N55 (−) A test-only dependency added in green is flagged
- **GIVEN** the green commit of task 2.1 adds `pytest-mock` to the dev dependencies
- **WHEN** step 1 runs
- **THEN** a deterministic major finding names the dependency and commit, and the unit verdict is FAIL

### Requirement: L4-VER-002 (step 1, part g) Gate configuration unchanged
Step 1 MUST verify that gate configuration is unchanged (L4-IMP-006), including the script entries the gate commands resolve to (`package.json` scripts, Makefile, tox, poe and just targets); a change without a human `[config]` tag MUST be a blocker.

#### Scenario: SCN-VER-N56 (−) A weakened lint script is a blocker
- **GIVEN** the unit changes `package.json` `scripts.lint` to `true` and the gate command is `npm run lint`
- **WHEN** step 1 runs
- **THEN** FAIL with a blocker finding naming the script entry

### Requirement: L4-VER-002 (step 1, part h) Inline suppressions must be declared
Step 1 MUST find new inline suppressions in the unit diff (`# noqa`, `# type: ignore`, `@ts-ignore`, `@ts-expect-error`, `eslint-disable`, `//nolint`, `#nosec`/`nosec`, `gitleaks:allow`); each MUST be declared in the implementer result `suppressions: [{file, line, rule, reason}]`, otherwise it is a major finding.

#### Scenario: SCN-VER-N57 (−) An undeclared suppression is a finding
- **GIVEN** the diff adds `# noqa: E501` at `src/a.py:10` and the implementer result declares no suppressions
- **WHEN** step 1 runs
- **THEN** a deterministic major finding names `src/a.py:10`; the fix unit can declare or remove it

### Requirement: L4-VER-002 (step 1, part i) Suppression acceptance rules
`gitleaks:allow` and `nosec` suppressions MUST NOT be accepted without a human `[config]` tag; declared suppressions MUST be listed in the PR and reviewed by the judge panel, and a judge objection is judge-only (a human verdict, never an automatic FAIL).

#### Scenario: SCN-VER-N58 (−) gitleaks:allow without a config tag
- **GIVEN** the diff adds `# gitleaks:allow` and the result declares it, but no task carries `[config]`
- **WHEN** step 1 runs
- **THEN** FAIL with a blocker finding even though the suppression is declared

### Requirement: L4-VER-002 (step 1, part j) No unannounced snapshot updates
Step 1 MUST raise a major finding when a pre-existing snapshot file is modified or rewritten and no task of the unit calls for snapshot updates.

#### Scenario: SCN-VER-N59 (−) Snapshot rewritten without a task
- **GIVEN** the diff rewrites `tests/__snapshots__/render.snap` and no task mentions snapshots
- **WHEN** step 1 runs
- **THEN** a deterministic major finding names the snapshot file

### Requirement: L4-VER-002 (step 1, part k) Secret scan with harness-owned config
Step 1 MUST run the secret scan (`verifier.secret_scan: gitleaks`) on the unit diff with the harness-owned gitleaks config and ignore file, ignoring the repository's `.gitleaksignore`; any finding is a blocker.

#### Scenario: SCN-VER-N60 (−) Repository ignore file cannot hide a secret
- **GIVEN** the diff adds a token-shaped string and the repository `.gitleaksignore` lists its fingerprint
- **WHEN** step 1 runs
- **THEN** FAIL with a blocker finding because the harness-owned ignore file is used instead

### Requirement: L4-VER-002 (step 1, part l) Scope check
Step 1 MUST compare changed paths with the unit's declared paths according to `sdd.scope_check`: `off` skips the check, `warn` records a minor finding, `fail` records a deterministic major finding.

#### Scenario: SCN-VER-N61 (−) Out-of-scope edit with scope_check fail
- **GIVEN** `sdd.scope_check: fail` and the diff edits a file outside the declared paths
- **WHEN** step 1 runs
- **THEN** a deterministic major finding names the file and the unit verdict is FAIL

#### Scenario: SCN-VER-N62 (+) Out-of-scope edit with scope_check warn
- **GIVEN** `sdd.scope_check: warn` and the same diff
- **WHEN** step 1 runs
- **THEN** a minor finding is recorded and the verdict is not affected

### Requirement: L4-VER-002 (step 1, part m) TDD history
For each non-exempt, non-`pre_adoption` task step 1 MUST verify that a red commit (or a verifier red commit) precedes its green commit, the red tests fail at the red commit, and the red tests as committed in the red commit pass at head; otherwise it MUST emit a blocker.

#### Scenario: SCN-VER-15 (−) Missing red commit
- **GIVEN** a non-exempt task with a green commit but no preceding red commit
- **WHEN** step 1 runs
- **THEN** FAIL, blocker `TDD history missing for task 2.3`

### Requirement: L4-VER-002 (step 2) Build, lint and typecheck
Step 2 MUST run `gates.setup`, `gates.build`, `gates.lint` and `gates.typecheck` in the verifier worktree; a non-zero exit or a timeout of any of them is a hard failure with a blocker finding that links the gate log.

#### Scenario: SCN-VER-N63 (−) Lint failure
- **GIVEN** `gates.lint` exits 1 in the verifier worktree
- **WHEN** step 2 runs
- **THEN** FAIL with a blocker finding linking `.l4-out/gates/<run-id>/lint.log`; steps 3 to 10 are recorded `not_run`

### Requirement: L4-VER-002 (step 3, part a) Full test re-run is non-vacuous
Step 3 MUST re-run the full `gates.test` (and `gates.e2e` with `gates.e2e.serve` when configured) in the verifier worktree; the result MUST be non-vacuous (L4-GAT-002) and every test added in the unit MUST appear as executed in the report.

#### Scenario: SCN-VER-04 (−) Zero tests executed is never a pass
- **GIVEN** the test command was broken by the change and the report has 0 tests
- **WHEN** step 3 runs
- **THEN** FAIL (`vacuous`), ladder stops

### Requirement: L4-VER-002 (step 3, part b) Flaky new tests
Step 3 MUST repeat each new test `verifier.flaky_repeats` times; any outcome flip MUST be a deterministic major finding `flaky` that records every outcome.

#### Scenario: SCN-VER-05 (−) Flaky new test
- **GIVEN** a new test passing 2 of 3 repeats
- **WHEN** step 3 runs
- **THEN** FAIL, major finding `flaky`, both outcomes recorded

### Requirement: L4-VER-002 (step 4) Traceability
Step 4 MUST build `criterion -> [tests] -> status` from the test reports by criterion-ID tracing (L4-CRT-002), apply L4-VER-009 and `verifier.max_criteria_per_test`, and mark every criterion without discriminating passing evidence `uncovered`.

#### Scenario: SCN-VER-N64 (−) Criterion without a tracing test is uncovered
- **GIVEN** criterion C-aaaa0001 is named in no test case name, tag or marker
- **WHEN** step 4 runs
- **THEN** C-aaaa0001 is `uncovered`, is listed in the traceability matrix as such, and is not omitted

### Requirement: L4-VER-002 (step 4a, part a) Audit sampling
Step 4a MUST audit ceil(`verifier.audit_sample_ratio` x covered new criteria) criteria, at least 1, chosen by a seeded hash of unit id and round; the verifier agent MUST write an independent test from the criterion text alone, which MUST be discriminating at the synthetic baseline and pass on head; a head failure goes to L4-VER-012.

#### Scenario: SCN-VER-31 (+) Audit sampling catches a weak implementer test
- **GIVEN** 6 covered new criteria (`audit_sample_ratio: 0.3` → 2 audited) and an implementer test for one of them that passes but checks the wrong field
- **WHEN** the verifier writes an audit test in a worktree from which the unit's test files were removed, and that test is discriminating at the baseline and fails on head
- **THEN** the panel confirms the audit test reads the criterion correctly → criterion `fail` → fix unit whose red test is the audit test

#### Scenario: SCN-VER-N65 (−) Audit test that passes at the baseline is rejected
- **GIVEN** an audit test that passes at the synthetic baseline
- **WHEN** step 4a checks it
- **THEN** the test is rejected as non-discriminating and is not counted as audit evidence

### Requirement: L4-VER-002 (step 4a, part b) Audit isolation
Audit tests MUST be written in an exported tree without `.git` from which every test file and test-support file the unit added or changed has been removed; they run with the unit's changed support files reverted to base where those still collect, otherwise with them if the step-1 content scan of those files is clean.

#### Scenario: SCN-VER-N66 (−) Audit tree contains no implementer tests
- **GIVEN** a unit that added `tests/test_login.py` and `tests/conftest.py`
- **WHEN** the audit tree is exported
- **THEN** the tree has no `.git` directory and neither file, so the agent cannot read them even through git history

### Requirement: L4-VER-002 (step 5, part a) Test generation for uncovered criteria
For each uncovered criterion, when `verifier.generate_missing_tests` is true, step 5 MUST have the verifier agent write a test tagged with the criterion ID (Playwright when UI-facing, else the project's framework) that fails at the synthetic baseline and passes on head.

#### Scenario: SCN-VER-06 (+) Missing test generated and accepted
- **GIVEN** criterion C-bbbb0002 uncovered
- **WHEN** the verifier agent writes a tagged test
- **THEN** it fails by assertion at the synthetic baseline and against the zero-value stubs, passes on head, and is committed with the round's verifier commit (`L4-Phase: verifying`); the criterion becomes pass

#### Scenario: SCN-VER-N67 (−) First attempt passes at the baseline
- **GIVEN** a generated test that passes at the synthetic baseline and a retry that fails there
- **WHEN** step 5 checks both
- **THEN** the first is rejected as non-discriminating, the retry is accepted, and exactly one retry is used

### Requirement: L4-VER-002 (step 5, part b) Generation impossible
Generation MUST be treated as impossible when the verifier agent returns `not_testable` with a reason, when two attempts are non-discriminating, or when the test cannot be collected; the criterion then stays uncovered.

#### Scenario: SCN-VER-07 (−) Non-discriminating generated test
- **GIVEN** the generated test passes on base, and so does the retry
- **WHEN** step 5 runs
- **THEN** both are rejected; the criterion stays uncovered → with `require_traceability: true`, NEEDS_HUMAN

### Requirement: L4-VER-002 (steps 6 and 7) Opt-in quality, contract and security gates
Steps 6 and 7 MUST run the opt-in `gates.extra` entries (quality such as diff coverage or mutation testing; contracts and security such as schemathesis or `semgrep --baseline-commit <base>`); a failing entry with `required: true` MUST be a deterministic major finding, otherwise a minor finding.

#### Scenario: SCN-VER-N68 (−) Required extra gate fails
- **GIVEN** `gates.extra` has `{name: semgrep, required: true}` and it exits 1
- **WHEN** step 7 runs
- **THEN** a deterministic major finding names `semgrep` and links its log; the unit verdict is FAIL

### Requirement: L4-VER-002 (step 8, part a) S1 judge
Step 8 MUST ask the S1 judge, per criterion, one `noul` question "Does this evidence show that the criterion is satisfied?" over a compact evidence state (criterion text, tracing tests with status, most relevant excerpt) kept within `verifier.s1.max_state_tokens` as measured by the S1 tokenizer, and record `p`.

#### Scenario: SCN-VER-N69 (−) Oversized evidence state is trimmed
- **GIVEN** an evidence state of 900 tokens and `max_state_tokens: 450`
- **WHEN** step 8 builds the state
- **THEN** the state is trimmed to the most relevant excerpt and is at most 450 tokens by the S1 tokenizer

### Requirement: L4-VER-002 (step 8, part b) S1 unavailable degrades gracefully
When S1 is disabled or no `s1_judge` profile is usable, step 8 MUST be recorded `unavailable` and aggregation MUST proceed, because S1 is corroborating only.

#### Scenario: SCN-VER-24 (+) Laya missing degrades gracefully
- **GIVEN** `verifier.s1.enabled: true` and Laya not installed
- **WHEN** verification runs
- **THEN** step 8 is recorded `unavailable`; aggregation proceeds (S1 is corroborating only); doctor warns ENV-006 (that doctor check is owned by bootstrap-core)

### Requirement: L4-VER-002 (step 9, part a) Judge panel verdicts and adequacy
Step 9 MUST have each panel judge return, per criterion, a verdict with findings and an adequacy review of every tracing test ("does this test check the criterion's observable outcome?"), as JSON conforming to `l4/judge-verdict@1` (SPEC 10.3), where `riskiest_assumptions` has exactly three entries.

#### Scenario: SCN-VER-N70 (−) Two riskiest assumptions are schema-invalid
- **GIVEN** a judge answer with only two `riskiest_assumptions`
- **WHEN** step 9 validates it
- **THEN** the answer is schema-invalid, one repair prompt is sent, and if the repaired answer is still invalid that judge's verdicts are discarded

### Requirement: L4-VER-002 (step 9, part b) Citations are re-checked by code
Step 9 MUST re-check every evidence reference of a judge verdict by code (`file:line` exists and contains the quote; test id exists in the report with the claimed status); an unverifiable citation MUST downgrade that verdict to `insufficient_evidence`.

#### Scenario: SCN-VER-11 (−) Fabricated citation
- **GIVEN** a judge cites `src/auth.py:88` with a quote not present at that line
- **WHEN** citations are checked
- **THEN** that criterion verdict is downgraded to `insufficient_evidence`; if no deterministic evidence exists the criterion is `needs_human`

### Requirement: L4-VER-003 (part a) Criterion pass
A criterion MUST be `pass` when at least one adequate discriminating tracing test passes (including accepted generated and audit tests) and the judge panel passes it; S1 `p` MUST NOT change this result, and a disagreement is only logged for calibration.

#### Scenario: SCN-VER-14 (+) S1 never overrides deterministic evidence
- **GIVEN** a criterion with a discriminating passing test and S1 p = 0.02
- **WHEN** aggregation runs
- **THEN** the criterion passes; the disagreement is logged to the calibration file only

### Requirement: L4-VER-003 (part b) Disputed criterion
A criterion with an adequate discriminating passing test but a judge `fail` with validated evidence MUST be `disputed`; the tie-breaker judge decides when configured, otherwise the criterion MUST be `needs_human`.

#### Scenario: SCN-VER-N71 (−) Passing test against a failing judge is disputed
- **GIVEN** a criterion with an adequate discriminating passing test and a judge `fail` whose citations validate, and no tie-breaker judge available
- **WHEN** aggregation runs
- **THEN** the criterion is `disputed` and then `needs_human`; it is not `pass` and not `fail`

### Requirement: L4-VER-003 (part c) Criterion fail
A criterion MUST be `fail` when a tracing or audit test fails on head and the test is not a misreading (L4-VER-012), whatever the judges or S1 say.

#### Scenario: SCN-VER-N72 (−) Judges cannot rescue a failing test
- **GIVEN** a tracing test of C-eeee0005 fails on head and the judge passes the criterion with valid citations
- **WHEN** aggregation runs
- **THEN** C-eeee0005 is `fail`

### Requirement: L4-VER-003 (part d) Uncovered criterion needs a human
An uncovered criterion MUST be `needs_human` when `sdd.require_traceability` is true (the default); neither a judge pass nor S1 can pass it alone.

#### Scenario: SCN-VER-13 (−) Judgment-only pass is impossible while traceability is required
- **GIVEN** an uncovered criterion (generation returned `not_testable`), judge pass with valid evidence, S1 p = 0.97, `sdd.require_traceability: true`
- **WHEN** aggregation runs
- **THEN** the criterion is `needs_human` (a verdict question is written, L4-VER-013); neither the judge nor S1 can pass it alone

### Requirement: L4-VER-003 (part e) Judgment pass with traceability off
With `sdd.require_traceability: false`, an uncovered criterion with a validated judge `pass` MUST be `pass (judgment)`, flagged in the report, when S1 `p` is at least `accept_threshold`, and MUST be `needs_human` when `p` is below it.

#### Scenario: SCN-VER-N73 (+) Flagged judgment pass
- **GIVEN** `require_traceability: false`, an uncovered criterion, a validated judge pass and S1 p = 0.95 with `accept_threshold: 0.9`
- **WHEN** aggregation runs
- **THEN** the criterion is `pass (judgment)` and the report flags it

#### Scenario: SCN-VER-N74 (−) Low S1 probability blocks a judgment pass
- **GIVEN** the same criterion with S1 p = 0.6
- **WHEN** aggregation runs
- **THEN** the criterion is `needs_human`

### Requirement: L4-VER-003 (part f) Not verifiable and failed judges fail closed
A criterion MUST be `needs_human` when its judge verdict is `not_verifiable`, or the judge answer is an error, refusal, truncation, schema-invalid after repair, or from a mismatched served model.

#### Scenario: SCN-VER-N75 (−) not_verifiable is never a pass
- **GIVEN** a judge verdict `not_verifiable` for a criterion that has a passing discriminating test
- **WHEN** aggregation runs
- **THEN** the criterion is `needs_human`

### Requirement: L4-VER-003 (part g) Unit verdict FAIL
The unit verdict MUST be FAIL if any of steps 0 to 3 failed, any criterion is `fail`, or any deterministic blocker or major finding exists (for example a flaky test, an undeclared suppression, a test-only dependency added in green, a scope violation with `scope_check: fail`).

#### Scenario: SCN-VER-44 (−) A deterministic major finding fails the unit
- **GIVEN** every criterion passes but a new test is flaky (passes 2 of 3 repeats)
- **WHEN** aggregation runs
- **THEN** verdict FAIL (deterministic major finding), not PASS

### Requirement: L4-VER-003 (part h) Unit verdict NEEDS_HUMAN
Otherwise the unit verdict MUST be NEEDS_HUMAN if any criterion is `disputed` or `needs_human`, or a judge raised a blocker or major finding with validated citations that no deterministic check confirms; LLM judgments alone MUST NOT fail a unit.

#### Scenario: SCN-VER-40 (−) A judge-only finding cannot FAIL a unit
- **GIVEN** all deterministic checks pass and a judge raises a `major` finding with valid citations that no test or gate confirms
- **WHEN** aggregation runs
- **THEN** verdict NEEDS_HUMAN with a verdict question; phase `awaiting_human`, exit 11; `reject` by the human creates a fix-unit finding

### Requirement: L4-VER-003 (part i) Unit verdict PASS and minor findings
Otherwise the unit verdict MUST be PASS; `minor` findings MUST NOT block, MUST be listed in the PR, and if `verifier.fix_minor_findings` is true MUST become a fix unit after PASS.

#### Scenario: SCN-VER-N76 (−) Minor findings never block
- **GIVEN** every criterion passes, all steps pass and the only finding is a `minor` over-tagged test
- **WHEN** aggregation runs
- **THEN** verdict PASS, not FAIL and not NEEDS_HUMAN; the minor finding is listed for the PR

### Requirement: L4-VER-004 (part a) Panel selection and agreement
The panel MUST run the first `verifier.panel.size` (at least 1) profiles in `roles.judges` that are available and independent; with two or more judges a criterion `pass` MUST require all judges to agree, and a split MUST be `disputed`.

#### Scenario: SCN-VER-N77 (−) A split panel is disputed
- **GIVEN** `panel.size: 2` and one judge passes C-ffff0006 while the other fails it
- **WHEN** aggregation runs
- **THEN** C-ffff0006 is `disputed`, not `pass`

### Requirement: L4-VER-004 (part b) pass^k and tie-breaker
`verifier.panel.pass_k` greater than 1 MUST repeat each judge k times and require all runs to pass (pass^k); the tie-breaker MUST be the next available independent judge in the chain.

#### Scenario: SCN-VER-N78 (−) One failing repeat prevents a pass
- **GIVEN** `pass_k: 2` and a judge passes a criterion in the first run and fails it in the second
- **WHEN** aggregation runs
- **THEN** the judge does not pass the criterion

#### Scenario: SCN-VER-N79 (+) Tie-breaker settles a dispute
- **GIVEN** a `disputed` criterion, `panel.tie_breaker: true` and a third independent judge in the chain
- **WHEN** aggregation runs
- **THEN** the next available independent judge in the chain is called and its verdict settles the dispute

### Requirement: L4-VER-005 (part a) Report header and ladder table
`verification.md` MUST contain the verdict and round, the base SHA and head SHA the evidence refers to, the profiles used (with fallbacks), and the ladder table with status and timings per step.

#### Scenario: SCN-VER-01 (+) Clean PASS
- **GIVEN** all tasks done; every criterion traced by a discriminating, adequate passing test; judges pass with valid citations
- **WHEN** verification runs
- **THEN** verdict PASS; `verification.md` complete (SPEC 10.6); phase `verified` → the hand-off push makes the PR ready → phase `in_review`; nothing is archived yet (`on_approval`)

### Requirement: L4-VER-005 (part b) Report body
`verification.md` MUST contain the traceability matrix (alias, ID, tests, discriminating?, adequacy, S1 p, judge verdicts, human verdicts), findings with evidence, TDD exemptions and `pre_adoption` tasks, guard events, links to CI artifacts, and cost.

#### Scenario: SCN-VER-N80 (−) Uncovered criteria are never omitted from the matrix
- **GIVEN** a unit with one covered and one uncovered criterion
- **WHEN** `verification.md` is rendered
- **THEN** both criteria appear in the matrix, the uncovered one marked `uncovered`

### Requirement: L4-VER-005 (part c) Report files and rounds
The verifier MUST write `<unit>/verification.md`, overwritten per round with previous rounds kept in `.l4/evidence/round-<n>/verification.md`, and the machine version to `.l4/evidence/round-<n>/verdict.json`; both MUST also be written when the verdict is FAIL.

#### Scenario: SCN-VER-N81 (−) FAIL still writes both files
- **GIVEN** round 1 fails at step 2
- **WHEN** the round ends
- **THEN** `verification.md` and `.l4/evidence/round-1/verdict.json` exist with verdict FAIL, and later steps are recorded `not_run`

### Requirement: L4-VER-006 (part a) Fix unit per round
On FAIL, while fewer than `verifier.max_fix_rounds` fix units exist for the parent, the spec writer MUST create one fix unit for the round's blocker and major findings, with one TDD task per finding (or per group of findings on the same criterion); tasks cite finding and criterion IDs.

#### Scenario: SCN-VER-N82 (−) Minor findings do not enter the fix unit
- **GIVEN** round 1 FAIL with one major and one minor finding
- **WHEN** the fix unit is written
- **THEN** it has one task for the major finding and none for the minor one

### Requirement: L4-VER-006 (part b) Spec gap adds a regression requirement
A finding with `spec_gap: true` MUST produce, before its task, an ADDED regression requirement with a scenario (OpenSpec: `## ADDED Requirements` → `### Requirement: <parent requirement> — regression <n>`; Kiro: a new acceptance criterion in `bugfix.md`); fix units MUST NOT use MODIFIED, REMOVED or RENAMED deltas.

#### Scenario: SCN-VER-18 (+) Spec gap → fix unit with an ADDED regression requirement
- **GIVEN** a finding `spec_gap: true` ("unverified e-mail login not specified") on parent `add-login`
- **WHEN** the fix unit is written
- **THEN** it contains `## ADDED Requirements` → `### Requirement: <parent requirement> — regression 1` with a scenario (no MODIFIED/REMOVED/RENAMED), validates strict, and has a task whose red test traces the new criterion's ID

### Requirement: L4-VER-006 (part c) No spec gap means skip_specs
Without a spec gap the fix unit MUST set `skip_specs: true` in its `.openspec.yaml` (OpenSpec).

#### Scenario: SCN-VER-19 (+) Plain defect → fix unit with `skip_specs`
- **GIVEN** a finding against an existing criterion
- **WHEN** the fix unit is written
- **THEN** `.openspec.yaml` has `skip_specs: true`; tasks cite the finding and criterion IDs; `validate --strict` passes

### Requirement: L4-VER-006 (part d) Validation and re-verification
The fix unit MUST be validated strict before commit; the parent then moves to `fixing`, and when the fix unit's tasks are done the parent MUST be re-verified as a whole (round + 1) covering parent and fix criteria.

#### Scenario: SCN-VER-20 (+) Fix loop converges
- **GIVEN** (`archive.mode: on_approval`) round 1 FAIL with 2 findings
- **WHEN** the fix unit is implemented, round 2 re-verifies the whole branch, and a member later approves
- **THEN** round 2 PASS → phase `in_review`; on approval the parent is archived first, then the fix unit, in one archive commit; the PR body lists both rounds

#### Scenario: SCN-VER-N83 (−) An invalid fix unit is never committed
- **GIVEN** a fix unit that fails `validate --strict`
- **WHEN** the spec writer finishes it
- **THEN** nothing is committed, the parent stays in `verifying`, and the run exits 1 as an internal error

### Requirement: L4-VER-006 (part e) Fix unit uses the parent's framework
The spec writer MUST create the fix unit through the parent's spec provider: OpenSpec via `openspec new change <parent>-fix-<n>`; Kiro as a bugfix spec directory `<parent>-fix-<n>` (see L4-OSP-005 and L4-KSP-005).

#### Scenario: SCN-VER-28 (+) Kiro fix unit is a bugfix spec
- **GIVEN** a FAIL on a Kiro unit `user-auth`
- **WHEN** the fix unit is written
- **THEN** `.kiro/specs/user-auth-fix-1/` contains `bugfix.md`, `design.md`, `tasks.md` and `.config.kiro` with `specType: bugfix`; tasks cite finding and criterion IDs; Kiro validation passes

### Requirement: L4-VER-007 Fix rounds exhausted
On FAIL when `verifier.max_fix_rounds` fix units already exist (at most `max_fix_rounds + 1` verification rounds), the unit MUST go to `escalated` with label `l4:escalated`, a sticky comment with the verdict summary, exit code 13, and no further fix unit.

#### Scenario: SCN-VER-21 (−) Fix rounds exhausted
- **GIVEN** `max_fix_rounds: 3` and round 3 FAIL
- **WHEN** aggregation ends
- **THEN** phase `escalated`, label `l4:escalated`, sticky comment with findings, exit 13; no fix unit 4

### Requirement: L4-VER-008 S1 calibration data
Each S1 judgment MUST be appended as one JSON line to `.l4-cache/s1-calibration.jsonl` (state hash, question, `p`, deterministic outcome, judge outcome, later human outcome) and summarised in the round's evidence.

#### Scenario: SCN-VER-29 (+) S1 judgments become calibration data
- **GIVEN** a verification with S1 enabled
- **WHEN** step 8 runs
- **THEN** one JSONL line per judgment is appended to `.l4-cache/s1-calibration.jsonl` with state hash, question, `p`, deterministic outcome and judge outcome; the human outcome is filled in when the PR is merged or changes are requested

#### Scenario: SCN-VER-N84 (−) No S1, no calibration line
- **GIVEN** step 8 is recorded `unavailable`
- **WHEN** the round ends
- **THEN** no line is appended and no error is raised

### Requirement: L4-VER-009 (part a) Synthetic baseline
The synthetic baseline MUST be the unit's base tree (the merge-base for a parent unit, the parent's head at fix-unit creation for a fix unit) plus all red-phase stubs of the unit and their zero-value variants, so that new symbols exist and every test reports individually.

#### Scenario: SCN-VER-42 (+) Synthetic baseline makes Go tests discriminate
- **GIVEN** a Go unit whose red stubs added `ParseToken` to an existing package, and a verifier-written test for it
- **WHEN** step 5 checks the test at the baseline
- **THEN** the baseline is the merge-base plus the unit's red stubs, the package builds, the test reports individually and fails by assertion; on head it passes → accepted

#### Scenario: SCN-VER-39 (+) Fix-unit criteria use the pre-fix head as baseline
- **GIVEN** a fix unit adding a regression requirement to a feature that exists only on the unit branch
- **WHEN** a verifier-written test for the regression criterion is checked
- **THEN** it must fail at the parent's head recorded when the fix unit was created (not at the merge-base, where the whole feature is absent)

### Requirement: L4-VER-009 (part b) When a passing test counts as evidence
A passing tracing test MUST count as evidence for a criterion only if it traces at most `verifier.max_criteria_per_test` criteria, the panel did not mark it inadequate, and it fails at the synthetic baseline; the criterion's evidence MUST include at least one test that also fails by assertion against the zero-value stubs.

#### Scenario: SCN-VER-30 (−) One weak test tagged with every criterion is not evidence
- **GIVEN** a single test tagged with five criterion IDs (`max_criteria_per_test: 3`)
- **WHEN** traceability runs
- **THEN** the test is evidence for none of them; the five criteria are uncovered → step 5 generates tests; a `minor` finding records the over-tagged test

### Requirement: L4-VER-009 (part c) Discrimination per evidence source
Discrimination MUST be established per source: implementer tests by the red-phase proof re-checked by the TDD-history step; verifier-written tests by the verifier at the baseline and with zero-value stubs; existing criteria (text unchanged from the base specs) by pass-to-pass; for `pre_adoption` units a collection or import error at the baseline does not count.

#### Scenario: SCN-VER-10 (+) Preserved behaviour may pass on base
- **GIVEN** a MODIFIED requirement whose scenario text is unchanged from the base spec, traced by a test that passes on base and head
- **WHEN** traceability runs
- **THEN** the test counts as evidence (pass-to-pass for an existing criterion)

#### Scenario: SCN-VER-N85 (−) A baseline import error is not discrimination
- **GIVEN** a `pre_adoption` unit whose tracing test fails at the baseline only with an import error
- **WHEN** traceability runs
- **THEN** the test does not count as discriminating and its criterion goes to step 5

### Requirement: L4-VER-009 (part d) Non-discriminating tests are ignored
A non-discriminating or inadequate tracing test MUST be ignored as evidence and recorded as a `minor` finding.

#### Scenario: SCN-VER-09 (−) A vacuous but tagged test is not evidence
- **GIVEN** a verifier or `pre_adoption` test tagged `@C-cccc0003` (a new criterion) that only calls the new function
- **WHEN** it is run against the zero-value stubs
- **THEN** it passes there, so it is non-discriminating → not evidence → criterion uncovered → step 5 generation, plus a `minor` finding `non-discriminating test` (an implementer test of this kind never gets past its red phase)

### Requirement: L4-VER-010 (part a) Internal errors keep the unit verifying
An internal verifier error (exception or infrastructure failure) MUST leave the unit in `verifying` with no verdict written and exit code 1.

#### Scenario: SCN-VER-23 (−) Verifier crash
- **GIVEN** an exception inside the verifier
- **WHEN** the run ends
- **THEN** exit 1, phase stays `verifying`, no verdict written, never PASS; after 3 consecutive internal errors the unit escalates

### Requirement: L4-VER-010 (part b) Three internal errors escalate
After 3 consecutive internal errors on the same unit the unit MUST go to `escalated`.

#### Scenario: SCN-VER-N86 (−) Third consecutive internal error
- **GIVEN** two earlier consecutive internal errors on unit `add-login`
- **WHEN** a third internal error occurs
- **THEN** phase becomes `escalated`, exit 13, and a success in between would have reset the counter

### Requirement: L4-VER-011 (part a) Step records
Each completed step MUST be recorded as ledger event `verify.step{round, step, subject_sha, evidence_hash, status}`, where `subject_sha` is the last commit not authored by the verifier.

#### Scenario: SCN-VER-N87 (−) The verifier's own commit does not move subject_sha
- **GIVEN** a round whose verifier commit `test(add-login): verifier round 1` is the branch head
- **WHEN** a step is recorded
- **THEN** `subject_sha` is the last non-verifier commit, not the verifier commit

### Requirement: L4-VER-011 (part b) Resume or restart
A continuation MUST resume at the first incomplete step when `subject_sha` is unchanged, and MUST restart at step 0 when a non-verifier commit arrived (human push, base merge in step 0).

#### Scenario: SCN-VER-34 (+) Verification resumes after a soft deadline
- **GIVEN** the job reaches its soft deadline during step 5 with steps 0–4 recorded for head SHA H
- **WHEN** the continuation runs with the head still at H
- **THEN** it resumes at step 5 without re-running steps 0–4; if the head had changed, it restarts at step 0

#### Scenario: SCN-VER-N88 (−) A human push restarts the round
- **GIVEN** steps 0 to 3 recorded for H and a human commit H2 on the branch
- **WHEN** the continuation runs
- **THEN** the round restarts at step 0

### Requirement: L4-VER-011 (part c) Verifier tests committed once
Verifier-generated tests MUST live in the round's evidence directory and the verifier worktree until the round ends, and then be committed once as `test(<unit>): verifier round <n>` with trailer `L4-Phase: verifying`.

#### Scenario: SCN-VER-37 (+) Step-5 tests and a continuation do not loop
- **GIVEN** step 5 wrote two tests (kept in the evidence directory, not yet committed) when the soft deadline hit
- **WHEN** the continuation starts with the last non-verifier commit unchanged
- **THEN** it resumes at step 5, keeps the two tests, finishes the round and commits all verifier tests once

#### Scenario: SCN-VER-N89 (−) No verifier commit without generated tests
- **GIVEN** a round in which step 5 and step 4a wrote no tests
- **WHEN** the round ends
- **THEN** no verifier commit is created

### Requirement: L4-VER-011 (part d) Soft deadline in long steps
Long steps MUST honour the soft deadline like agent phases (L4-IMP-012): a step interrupted by the deadline MUST NOT be recorded complete and its partial evidence MUST be kept for the continuation.

#### Scenario: SCN-VER-N90 (−) An interrupted step is not complete
- **GIVEN** the soft deadline arrives while step 3 repeats flaky checks
- **WHEN** the verifier stops
- **THEN** step 3 has no `verify.step` record with status `ok`, a continuation is requested, and the partial evidence remains in the round directory

### Requirement: L4-VER-012 (part a) Misreading tests are discarded
When a verifier-written test fails on head, the panel MUST review it against the criterion text; if any available independent judge sets `generated_test_misreads_criterion`, the test MUST be discarded, the criterion made `needs_human`, and no fix unit spawned for it.

#### Scenario: SCN-VER-32 (−) A misreading generated test does not force fix rounds
- **GIVEN** a verifier-generated test that fails on head
- **WHEN** a judge marks it `generated_test_misreads_criterion: true`
- **THEN** the test is discarded, the criterion becomes `needs_human` (verdict question), and no fix unit is spawned for it

### Requirement: L4-VER-012 (part b) A confirmed failing test becomes the red test
Otherwise the failing test MUST make the criterion `fail` and become the fix unit's red test: the round's verifier commit MUST carry `L4-TDD: red` and `L4-Task: <fix-unit task id>`.

#### Scenario: SCN-VER-08 (−) Generated test exposes a defect
- **GIVEN** a verifier-generated test that fails on head and that no judge marks as misreading the criterion
- **WHEN** the round ends
- **THEN** FAIL with a finding against the criterion; the test is committed in the round's verifier commit with `L4-TDD: red` and the fix unit's task id, and step 1 later accepts it as that task's red commit

### Requirement: L4-VER-012 (part c) Fix unit first, then the red commit
The spec writer MUST create the fix unit before the verifier commit is made; the fix task starts directly at green, and its TDD-history check considers only the tests tagged to that task.

#### Scenario: SCN-VER-43 (+) Fix unit exists before the verifier's red commit
- **GIVEN** round 1 fails because a generated test fails on head
- **WHEN** the round ends
- **THEN** the fix unit is created first, then the verifier commit carries `L4-TDD: red` and `L4-Task: 1.1` of the fix unit; fix task 1.1 starts at green; its TDD-history check considers only the test tagged to it

#### Scenario: SCN-VER-N91 (−) Fix task without its tagged test fails TDD history
- **GIVEN** a fix task 1.1 whose tagged test is absent from the verifier commit
- **WHEN** step 1 runs on the next round
- **THEN** a blocker `TDD history missing for task 1.1` is raised

### Requirement: L4-VER-012 (part d) Implementer may not edit a verifier test
The fix-unit prompt MUST instruct an implementer that believes the verifier's test is wrong to report `blocked` with a `technical` question instead of editing the test.

#### Scenario: SCN-VER-N92 (−) Fix prompt forbids editing the verifier test
- **GIVEN** a fix unit whose red test was written by the verifier
- **WHEN** the implementer prompt is rendered
- **THEN** it contains the instruction to report `blocked` with a `technical` question and not to edit that test

### Requirement: L4-VER-013 (part a) Verdict questions
On NEEDS_HUMAN the verifier MUST write one `Kind: verdict` question per affected criterion into `questions.md` ("Criterion C-... (alias) is disputed: accept as satisfied?") plus the evidence summary; judge-only blocker or major findings are asked the same way.

#### Scenario: SCN-VER-N93 (−) One question per affected criterion
- **GIVEN** two criteria `needs_human` and one judge-only major finding
- **WHEN** the round ends with NEEDS_HUMAN
- **THEN** `questions.md` gains three `Kind: verdict` questions, each with its evidence summary, and the phase becomes `awaiting_human` with exit 11

### Requirement: L4-VER-013 (part b) Recording human verdicts
An answer whose first word is `accept` or `reject` (case-insensitive) with Status `answered` MUST be recorded as `human.verdict{criterion, decision, by, reason}`, and aggregation MUST use it for that criterion in this and later rounds.

#### Scenario: SCN-VER-33 (+) Human verdict ends a dispute permanently
- **GIVEN** NEEDS_HUMAN for C-dddd0004 and a verdict question in `questions.md`
- **WHEN** the human answers `accept — the 302 redirect is intended` with Status `answered`
- **THEN** `human.verdict{criterion: C-dddd0004, decision: accept}` is recorded, round N+1 treats the criterion as passed without re-asking, and `verification.md` shows "accepted by <human>" with the reason

#### Scenario: SCN-VER-N94 (−) An answer without accept or reject is not consumed
- **GIVEN** a verdict question answered `looks fine to me` with Status `answered`
- **WHEN** the answer is parsed
- **THEN** no `human.verdict` is recorded and the criterion stays `needs_human`

### Requirement: L4-VER-013 (part c) A regression voids an acceptance
A human `accept` MUST be void as soon as the criterion text changes or any deterministic check tracing the criterion fails later; the criterion then follows the normal rules, so a failing check makes it `fail`.

#### Scenario: SCN-VER-38 (−) An accepted criterion that later regresses fails
- **GIVEN** a human accepted C-dddd0004 in round 1, and in round 2 a tracing test of C-dddd0004 fails
- **WHEN** aggregation runs
- **THEN** the human acceptance is void; the criterion is `fail`; the report shows both facts

### Requirement: L4-VER-013 (part d) Reject becomes a finding
A human `reject` MUST turn the criterion into a `fail` finding that leads to a fix unit under L4-VER-006.

#### Scenario: SCN-VER-N95 (−) Reject creates a fix-unit finding
- **GIVEN** a human answered `reject — redirect must be 301` for C-dddd0004
- **WHEN** round N+1 aggregates
- **THEN** C-dddd0004 is `fail`, a finding cites it, and a fix unit is created while fix rounds remain

### Requirement: L4-VER-014 (part a) UI-facing criteria
A criterion MUST be UI-facing when the unit's changed or declared paths match `verifier.playwright.ui_paths`, or when the S1 choice question "Is this criterion about user-visible UI behaviour?" gives p at least `accept_threshold`.

#### Scenario: SCN-VER-N96 (−) Backend criterion is not UI-facing
- **GIVEN** a unit changing only `src/billing/refund.py` and an S1 choice answer p = 0.12
- **WHEN** UI-facing detection runs
- **THEN** the criterion is not UI-facing and gets no Playwright test

### Requirement: L4-VER-014 (part b) Served app for Playwright
UI-facing criteria MUST get Playwright tests when Playwright is enabled (`auto` means when `gates.e2e` is configured); the app MUST be started with `gates.e2e.serve` separately for the merge-base worktree and the head worktree and stopped after each run.

#### Scenario: SCN-VER-35 (+) UI criteria use Playwright against a served app
- **GIVEN** a criterion on a unit whose paths match `web/**`, and `gates.e2e.serve` configured
- **WHEN** step 5 generates a test
- **THEN** it is a Playwright test tagged `@C-…`; the app is started from the merge-base worktree for the base run and from the head worktree for the head run, and stopped after each

#### Scenario: SCN-VER-N97 (−) Server that never becomes ready
- **GIVEN** `gates.e2e.serve.ready_url` does not answer within `timeout`
- **WHEN** the head run starts
- **THEN** the serve process is stopped, the failure is an internal error (unit stays `verifying`, exit 1), and no criterion is marked failed

#### Scenario: SCN-VER-N98 (−) Playwright disabled falls back to the project framework
- **GIVEN** `verifier.playwright.enabled: false` and a UI-facing uncovered criterion
- **WHEN** step 5 runs
- **THEN** the verifier writes a test with the project's unit framework or returns `not_testable`, in which case the criterion is `needs_human`

### Requirement: L4-VER-014 (part c) Playwright evidence
Playwright runs MUST be headless with traces and screenshots, the tests MUST be tagged `@C-…`, and the trace and screenshot paths MUST be linked in `verification.md`.

#### Scenario: SCN-VER-25 (+) UI criterion verified with Playwright
- **GIVEN** a UI criterion and `gates.e2e` configured with `L4_E2E_BASE_URL`
- **WHEN** steps 3/5 run
- **THEN** Playwright runs headless with traces; trace and screenshot paths are linked in `verification.md`; the criterion is traced by `@C-…`

### Requirement: L4-VER-015 (part a) Failure precedence
A required role with no usable profile MUST give `waiting_capacity` (exit 12); a harness exception or infrastructure failure MUST keep the unit in `verifying` (exit 1); a judge answer that is refused, truncated, schema-invalid after repair or from a mismatched model MUST discard that judge's verdicts, try the next independent judge, and make affected criteria `needs_human` when none remains.

#### Scenario: SCN-VER-12 (−) Judge failures follow one precedence table
- **GIVEN** three runs: (a) the only judge returns HTTP 429; (b) it returns schema-invalid output twice; (c) the harness raises an exception while parsing reports
- **WHEN** aggregation is due
- **THEN** (a) phase `waiting_capacity`, exit 12; (b) affected criteria `needs_human` → verdict questions → phase `awaiting_human`, exit 11; (c) phase stays `verifying`, exit 1; none of them produces PASS

### Requirement: L4-VER-015 (part b) Limit signals and timeouts
A judge call failing mid-request with a limit signal MUST be treated as "no usable profile" for that judge (cool-down recorded, `retry_after` set); a judge call timing out MUST be retried once and a second timeout MUST discard that judge like a refused answer.

#### Scenario: SCN-VER-36 (−) A judge 429 is a capacity problem, not a verdict
- **GIVEN** the only independent judge answers HTTP 429 with `retry-after: 600`
- **WHEN** aggregation is due
- **THEN** a cool-down is recorded, phase `waiting_capacity`, exit 12, `retry_after` set; no criterion is marked `needs_human` for this

#### Scenario: SCN-VER-N99 (−) Second timeout discards the judge
- **GIVEN** a judge that times out twice and a second independent judge that answers
- **WHEN** the panel runs
- **THEN** the first judge is discarded, the second judge's verdicts are used, and no criterion is `needs_human` for the timeout
