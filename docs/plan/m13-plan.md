# M1.3 — verifier depth and fix specs (planned 2026-10-04)

## Goal

M1.3 makes a PASS mean what SPEC §10 says, not what the M0 traceability override allowed. Each criterion must be
traced, through `@pytest.mark.l4("C-…")`, to a test the harness has proven discriminating: a zero-value red proof, a
pre-satisfied check, or an independent audit test. Integrity step 1 checks that the tests were not gamed (freeze,
suppressions, content scan, TDD history).

A failure now becomes work instead of a dead end:
* NEEDS_HUMAN becomes `Kind: verdict` questions that a human answers with `accept` or `reject`.
* Verifier findings become an OpenSpec change `<unit>-fix-<n>`, which the harness implements on the same branch and
  re-verifies. These findings are deterministic ones, rejected verdicts and, with `fix_minor_findings`, the judge's
  spec gaps, each turned into an ADDED scenario.
* After `max_fix_rounds` fix units the unit is `escalated` (exit 13).

This delivers row 8 of the change map ("findings → fix change"). It removes the M0 Stage C traceability override. It
also closes the two gaps that `docs/live/README.md` lists as not done: fix specs from verifier findings, and
criterion→test traceability (L4-VER-002 steps 1, 4 and 4a, L4-VER-003/006/007/009/011/013, L4-IMP-002/003).

## Decisions

* **D1. A fix unit runs inside its parent's run, branch, worktree and ledger.**
  * The fix unit is `openspec/changes/<parent>-fix-<n>/` on the parent's branch.
  * It has no phase of its own. The parent stays `fixing` while a `fix` hook drives the fix unit's tasks with the
    existing `run_task`; then `fixing → verifying` (round + 1) re-verifies the parent and its fix units as one family.
  * Why: units are listed from the base checkout (`OpenSpecProvider.list_units`, `run_command`) [V, code], so a fix
    unit that exists only on the unit branch could never be scheduled on its own. A second branch, lock and MR would
    double every M1.1 mechanism.
  * A file `<fix>/.l4/fix.json` marks the fix unit, so that after a merge to `main` it is never planned as a unit of
    its own. `.l4/` inside a change passes `validate --strict` [V, M0 step 0 live].
* **D2. The fix loop continues in the same job, and the lifecycle stays additive.**
  * The `verifying → fixing` row keeps exit 10.
  * `Orchestrator._verify` goes on driving when the edge's target is `fixing` and a `fix` hook exists. That is the "0"
    of SPEC's "10 or 0".
  * `l4 verify` runs with `fix=None`, the same way it already runs without `handoff`, so it stops at `fixing` with 10.
  * Why: no continuation dispatch exists (L4-IMP-012 is deferred), and `[skip ci]` checkpoints start no pipeline. So a
    10 would stall the unit until someone started a pipeline by hand.
* **D3. `reject` is consumed; `accept` is durable.**
  * A `reject` produces one fix unit; `fix.spawned{consumed: [Q-…]}` records it. The criterion or finding is then
    judged afresh in the next round.
  * An `accept` holds in later rounds. It becomes void when the criterion text changes (`text_sha256`) or when a
    tracing test fails later.
  * Without this asymmetry a rejected finding would FAIL every round, and `max_fix_rounds` would escalate a unit whose
    fix passed.
* **D4. Verdict answers resume at aggregation.**
  * `subject_sha` is the last commit that both:
    * does not carry `L4-Phase: verifying`;
    * touches a path other than the unit's harness-owned files (`questions.md`, `verification.md`, `.l4/**`).
  * While it is unchanged, the next round reuses the recorded results of steps 0–9 from `verdict.json` and only
    re-aggregates with the human verdicts. There is no gate run and no judge call.
  * Reuse also requires the family's set of criterion ids to be unchanged. A fix-unit commit carries `L4-Phase:
    verifying` but adds criteria.
  * M1.5's `chore(memory)` commit (trailer `L4-Phase: lessons`, path `.serena/memories/harness/lessons.md`) is not a
    subject either: `subject_sha` skips commits with `L4-Phase: lessons`, and `.serena/memories/harness/**` counts as
    harness-owned (parallel-ownership §4, item 10).
  * A human edit to code or spec restarts the round at step 0.
  * SPEC L4-VER-011 defines `subject_sha` by authorship only (doc change owed).
* **D5. Tool-less test writer, shared with M1.5.**
  * Audit sampling (4a) asks `roles.verifier_agent` through `AgentJudge` for `l4/generated-test@1`: either
    `{criterion, code}` or `{criterion, not_testable}`. This is the schema of M1.5 D2.
  * The harness fixes the file path. The prompt holds the criterion text and the head source of the unit's changed
    non-test modules: no test file, no support file, no git. So it cannot read the unit's tests, and L4-VER-002a holds
    by construction.
  * `src/l4/verifier/testwriter.py` and `generated-test.schema.json` come from the seam commit S0 on `main`
    (`docs/plan/parallel-ownership.md` §3.0): `request_test(judge, kind="audit", …)`, `test_path`,
    `write_test_file`. M1.3 owns the file after S0 and changes it additively only; M1.5 imports it. "Whichever lands
    first" cannot work for two branches built in parallel.
* **D6. Spec-gap scenarios have a source; nothing invents one.** An ADDED regression scenario takes its `WHEN … THEN …`
  from, in order:
  1. the human's `reject` reason;
  2. the judge's `suggested_fix`, which `judge@3` asks to phrase as one WHEN/THEN about the behaviour the code shows
     now.

  A finding with neither is listed and not converted. The spec delta is part of the MR diff, so the reviewer sees
  every behaviour it pins.
* **D7. Zero-value variants are written in place and restored byte-exact (sha256 checked); scratch copies are not
  used.**
  * uv installs the project editable, so a scratch copy would import the original worktree's code [I, pyproject +
    uv default].
  * The harness writes the variant, runs the gate and restores the bytes before any commit. A crash leaves nothing
    behind, because `WorktreeManager.ensure` recreates the worktree on every run [V, code].
* **D8. Deterministic findings that carry no criterion become harness-tagged `[chore]` fix tasks.**
  * Examples: an undeclared suppression, a broken freeze, a content-scan hit, a test that fails at step 3.
  * Each such task runs in a single phase: green prompt, gates, then `L4-TDD: exempt` and `task.tdd_exempt{kind:
    harness}`. TDD history skips it.
  * Human-written tags (implementer-tdd-loop 1.25) stay deferred.

## Parallel lanes (the user asked for faster, parallel work)

Stages run in sequence. Inside a stage, lines of different lanes touch disjoint files and run in parallel. A "join"
line waits for its lanes and is the single writer of the shared files it names.

* **Stage A:**
  * [T] trace: lines 1–4;
  * [P] prompt/result: lines 5–7;
  * [R] red guard: lines 8–11;
  * join: lines 12–13.
* **Stage B:**
  * [I] integrity: lines 14–21;
  * [E] evidence: lines 22–24;
  * [H] human verdicts: lines 25–29;
  * join: line 30.
* **Stage C:**
  * [S] spec writer: lines 31–33;
  * [F] fix loop: lines 34–36;
  * join: lines 37–38;
  * line 39: M1.1 line 33 has landed (`3a4d58e`), so it does not wait;
  * line 40 last.

**Parallel with M1.2, M1.4 and M1.5.** The shared-file anchors and exact names, the contracts (C1, C2, C7–C13, C18,
C19, C21) and the merge order (M1.2 → M1.3 → M1.4 → M1.5; M1.4 may overtake) are in
`docs/plan/parallel-ownership.md`. Line 24 needs the seam commit S0: merge `main` before it.

## Build list

Line format: `change-id task — what M1.3 builds`. 40 lines in total: 34 task lines (several absorb tasks) and 6 gap
tasks, M13-G1…G6.

### Stage A — red-phase evidence and tracing (implementer side)

1. [T] M13-G1 (gap) — record the real pytest 9 JUnit output, for both `junit_family=xunit1` and `xunit2`.
   * What to record:
     * per-testcase `user_properties`;
     * the failure messages of `assert`, `pytest.raises` (`Failed: DID NOT RAISE`), `raise NotImplementedError`,
       `TypeError` and `AttributeError`.
   * Decision rule:
     * if `<properties>` reach each testcase in both families, junit properties are used;
     * otherwise the plugin writes the sidecar `.l4-out/l4-trace.json` (nodeid → ids).
2. [T] M13-G2 (gap) — the harness-owned pytest plugin `l4_trace`:
   * `trace_env()` gives `PYTEST_ADDOPTS=-p l4_trace` and `PYTHONPATH=<plugin dir>`, the dir resolved from the
     installed package and never repo-relative;
   * it goes into every gate run (`run_gate(..., extra_env=)`, `build_gate_env(..., extra=)`) and into the agent env,
     so that projects using `--strict-markers` still collect.
3. [T] implementer-tdd-loop 1.2 (delta) — `parse_junit` fills `TestCase.criteria` (properties or sidecar) and
   `TestCase.failure_kind` (`assertion` | `not_implemented` | `other` | None for an unrecognised message), from the
   shapes recorded in line 1.
4. [T] spec-providers 1.27 — `trace_ids(case) -> frozenset[str]`:
   * ids come from the test name, the classname and the `l4` properties, plus the harness names `test_l4_c_<hex>` and
     `test_l4_audit_c_<hex>` (M1.5's e2e convention);
   * in a test id, `C-<hex>`, `C_<hex>` and `c_<hex>` (any case, 8 hex digits) also trace. That is M1.5 G5's rule, so
     `trace_ids` is a superset of it, and M1.5's interim `trace_e2e` is retired onto it (parallel-ownership C8);
   * comments never trace.
5. [P] implementer-tdd-loop 1.12 + 1.14 (delta) — `contract@3` and `red@2`:
   * tag every test with `@pytest.mark.l4("C-…")` for the criteria it checks;
   * report `criteria_ids`;
   * declare every new `# noqa` and `# type: ignore` in `suppressions`;
   * stubs only: signature-only or guarded-parameter;
   * a red test must fail by assertion or with `NotImplementedError`.
6. [P] implementer-tdd-loop 1.10 — `check_criteria(result, family_criteria, new_tests)`:
   * the cited criteria are `criteria_ids` when that list is not empty, else the union of the traces of the new tests;
   * every cited criterion must be one of the family's and have at least one tracing new test;
   * an untraced new test is recorded (`test.untraced`), not failed;
   * red fails only when neither source yields a criterion.
7. [P] implementer-tdd-loop 2.16 — `ImplementerResult.suppressions`; the declared suppressions go into `task.red_ok`
   and `task.done`.
8. [R] implementer-tdd-loop 1.15 (part 1) — `classify_red_changes(head_src, new_src)`, by Python AST. A change is
   admissible when it is one of:
   * a new function or method whose body is only `raise NotImplementedError` (a docstring is allowed);
   * a guarded-parameter stub: new trailing defaulted parameters, the first statement `if <names/None/True/False>:
     raise NotImplementedError`, and the rest AST-identical to HEAD;
   * a new class with explicit bases whose body is only `pass`, `...`, a docstring, plain annotated fields and
     stub-ified methods (for example `class UnsupportedShippingCountry(Exception): pass`), with decorators from an
     allow-list (`dataclass`, `staticmethod`, `classmethod`, `property`, `abstractmethod`, `overload`);
   * imports and `__all__` entries.
9. [R] implementer-tdd-loop 1.15 (part 2) — `enforce_red_scope`.
   * Every changed non-test `.py` file is rebuilt as HEAD bytes plus its admissible additions:
     * new symbols are stub-ified;
     * new methods go to the end of their class;
     * module-level values and defaults are dropped;
     * anything else is restored to HEAD.
   * Non-Python, non-test production files are restored, and new ones are deleted.
   * Events: `guard.violation{phase: red}` per restored region; `stub.purity{task, stubs, restored}`.
10. [R] implementer-tdd-loop 2.2 — zero-value variants of the red stubs.
    * Values by return annotation (SPEC table, unknown → `None`, `-> None` → `pass`); a guarded stub's guard body gets
      the same treatment.
    * The variants are applied in place, and the gate runs (D7).
    * Run (b): each cited criterion that is not pre-satisfied needs at least one tracing new test failing with kind
      `assertion`. Otherwise it is `vacuous: C-…`, and the feedback names the call-only or zero-answer tests.
    * When red added no stub, run (b) is skipped and the proof is `red_assertion`.
11. [R] M13-G3 (gap) — pre-satisfied criteria (L4-IMP-002): confirmed by a zero-value run over the imported and changed
    source modules; unconfirmed fails red `not discriminating`.
12. join — implementer-tdd-loop 1.18 + 1.19 (delta), wiring `run_red` in SPEC check order:
    1. the protected revert (exists);
    2. `enforce_red_scope`;
    3. run (a);
    4. `check_criteria`;
    5. the pre-satisfied confirmation;
    6. `classify_red(..., failure_kinds=True, allowed_passing=<confirmed tests>)`;
    7. run (b);
    8. the static gates (exist).

    Both keywords default to today's behaviour. `RedOutcome.criteria` and `task.red_ok.criteria = {C: {tests,
    proof}}` are added.
13. join — implementer-tdd-loop 2.11 (reduced) — when every cited criterion is pre-satisfied:
    * commit `test(<unit>): <task> already satisfied` with `L4-TDD: already-satisfied`;
    * tick the task;
    * emit `task.red_ok` with the proofs and `task.done{task, sha, tdd: "already-satisfied", notes}`, so that the fold
      and the TDD history (line 21) see the task;
    * `run_task` skips green.

    The harness proves it, so no agent claim is needed (doc change owed, L4-IMP-003).

*Exit:*
* G1 is recorded.
* Unit tests pass.
* On the fixture repo with `FakeAdapter`, the real pytest and a bare remote:
  * real code in red in an existing module → the file is rebuilt (HEAD plus stubs), with `guard.violation{phase:
    red}`;
  * a call-only test → `vacuous: C-…`;
  * a zero-answer test beside a discriminating sibling passes;
  * tests of existing behaviour → `criterion.pre_satisfied` and an `L4-TDD: already-satisfied` commit, with no green
    step;
  * a `TypeError` red is refused, with feedback;
  * `.l4-out/junit.xml` (or the sidecar) maps the new tests to their `C-…` ids.

### Stage B — verifier ladder depth

14. [I] verifier 2.1 (reduced, Python only) — `tests/fixtures/py_integrity/`, as fixture tests of lines 15–21.
    * Must-catch cases:
      * a call-only test;
      * a `pytest_runtest_makereport` hook in `conftest.py`;
      * `addopts = "-p no:l4_trace"`;
      * an undeclared `# noqa`;
      * a deleted pre-existing test;
      * an added `@pytest.mark.skip`;
      * an assertion changed between red and green.
    * Must-pass cases:
      * a zero-answer test with a sibling;
      * a declared `# type: ignore`;
      * a dataclass with plain fields;
      * a new exception class with a `pass` body;
      * a conftest fixture patching a clock.
15. [I] verifier 2.2 — `run_integrity(ctx) -> IntegrityReport`, step 1 between steps 0 and 2. Each sub-check returns
    findings; a blocker or major finding stops the ladder with FAIL. `verification.md` gets one row per sub-check.
16. [I] verifier 2.3 (reduced) — outstanding protected changes: a contract glob or an `odd.forbidden_paths` path that
    differs between base and head is a blocker. The unit dirs of the family are excluded.
17. [I] verifier 2.4 (reduced) — an AST diff of the test files from base to head:
    * a `test_*` function present at the base and missing at head is a blocker;
    * a `skip`/`skipif`/`xfail` marker, or a `pytest.skip(` added to such a function, is a blocker.
18. [I] verifier 2.5 — the freeze held for each task: the `task.red_ok.frozen` files are identical at the red sha and
    the green sha. So are the `[tool.pytest*]`/`[tool.coverage*]` sections of `pyproject.toml` and the files
    `pytest.ini`, `tox.ini` and `setup.cfg`. Any change is a blocker.
19. [I] verifier 2.6 — content scan of the unit's changed test-support and runner-config files:
    * pytest result hooks (`pytest_runtest_makereport`, `pytest_report_teststatus`, a deselecting
      `pytest_collection_modifyitems`, `pytest_runtest_call`/`pytest_runtest_protocol` hookwrappers);
    * `addopts` additions of `-p`, `--deselect`, `-k`, `--ignore`;
    * any repo module named `l4_trace`.

    A hit is a blocker, unless the task carries a human `[test-infra]` tag.
20. [I] verifier 2.10 — new inline suppressions in the unit diff (`# noqa`, `# type: ignore`, `nosec`,
    `gitleaks:allow`):
    * one not declared by the ledger's steps is major;
    * `nosec` and `gitleaks:allow` without a human `[config]` tag are major;
    * declared ones are listed in the report and in the judge prompt.
21. [I] verifier 2.13 (reduced) — TDD history per `(unit, task)` of the family:
    * the commit order must be either a red commit and then its green commit, or one `already-satisfied` commit. The
      commits are found by `L4-Unit`, `L4-Task` and `L4-TDD`, must be ancestors of head, and must equal the ledger shas;
    * the red tests of the ledger must be present and passing at head;
    * a missing red is a blocker (SCN-VER-15);
    * `exempt` tasks are skipped;
    * re-running the tests at the red commit is deferred.
22. [E] verifier 1.9 + 3.4 + 3.5 (reduced) — `trace_criteria(criteria, report, ledger, cfg, *, extra_reports=()) ->
    list[CriterionEvidence]`. `extra_reports` takes M1.5's e2e report, so M1.5 adds no step 4e2e (parallel-ownership
    C8).
    * `TracingTest(id, status, proof, adequate)`.
    * The proof is one of `zero_value`, `pre_satisfied` or `red_assertion` (from `task.red_ok`), `pass_to_pass` (the
      criterion text is unchanged from the base specs), `audit`, or `generated` (M1.5).
    * A test that traces more than `max_criteria_per_test` criteria is ignored, with a minor finding.
    * A tracing test that fails at head makes the criterion `fail`. With no discriminating passing test, it is
      `uncovered`.
    * `verification.md` gets the traceability matrix.
23. [E] verifier 1.13 + 4.7 (reduced) — `aggregate_criterion(..., *, trace=None, human=None,
    require_traceability=True)` covers every SPEC 10.4 row except S1 and the panel:
    * a test that the judge marks inadequate is not evidence;
    * a human verdict overrides the judge (D3);
    * `aggregate_unit` FAILs on a `fail` criterion;
    * M1.5's `evidence=` folds into `trace`.
24. [E] verifier 3.7 + 3.8 (reduced) — step 4a.
    * Choice: `ceil(audit_sample_ratio × covered new criteria)` criteria (at least 1), plus every pre-satisfied one, by
      a seeded sha256 of unit id and round; 0 disables the step.
    * At most `MAX_AUDIT_PER_ROUND = 2` per round, pre-satisfied criteria first. The rest are recorded as `audit:
      skipped (cap)`.
    * The test is written through `testwriter` (D5) on `roles.verifier_agent`, with M1.2's independence constraint.
    * File: `tests/test_l4_audit_c_<hex>_r<n>.py`, which must carry the marker.
    * Accepted: it passes at head and fails by assertion against zero values (the line-11 scope). Otherwise it is
      rejected with a minor finding. One that fails at head makes the criterion `needs_human`.
    * Accepted audit tests are committed once per round: `test(<unit>): verifier round <n> [skip ci]`, with
      `L4-Phase: verifying`. The commit is made by
      `l4.verifier.evidence.commit_verifier_tests(wb, paths, round_no)` after steps 4a and 5, not by step 4a itself.
      M1.5's generated tests (step 5) go into the same commit (parallel-ownership C9).
    * An empty `roles.verifier_agent` means step 4a is `not_run`.
    * The writer is `testwriter.request_test(kind="audit")` from S0. Until M1.2 is on `main`, the profile comes from
      `require_independent_judge` plus `for_role("verifier_agent", serves=JUDGE_ADAPTERS)`; after that, from
      `select_judge(..., role="verifier_agent")` (C1).
25. [H] verifier 1.17 — `Kind: verdict` questions, one per `needs_human` criterion and one per judge-only blocker or
    major finding.
    * Each has an evidence summary and `**Blocking tasks:** none`, and asks for `accept`, or `reject` plus WHEN/THEN
      for a spec gap.
    * Each gets a `question.raised{kind: verdict}`, so the M1.1 mirror sets `l4:needs-answers` [V, code].
    * `questions.py` gains the verdict rule.
26. [H] verifier 5.8 + 5.9 (reduced) — `consume_verdicts`.
    * The first word must be `accept` or `reject` (any case). Anything else with Status `answered` is invalid: it is not
      consumed, and the sticky note asks for a fix (L4-QMD-004).
    * Writes `human.verdict{question, target, decision, by, reason, text_sha256}`.
    * Implements D3's voiding of an `accept`.
27. [H] verifier 5.2 (reduced) — `evidence.subject_sha` and resume at aggregation (D4).
    * Reuse needs `subject_sha` and the family's criterion-id set both unchanged.
    * `verdict.json` carries the per-criterion evidence, judge verdicts and findings that step 10 needs.
    * Reused steps show `reused (round n)`.
28. [H] state-vcs-locks 1.20 (delta).
    * New triggers:
      * `VERDICTS_ANSWERED`, `awaiting_human → verifying`;
      * `FIX_UNIT_DONE`, `fixing → verifying`;
      * `MINOR_FINDINGS_FIX`, `verified → fixing`;
      * `VERIFY_FAIL_EXHAUSTED`, `verifying → escalated`, exit 13.
    * `fixing` joins the sources of `required_role_unavailable` and `breaker_or_budget`.
    * The fold gains `fix_round`, `children`, `open_fix_unit` and `verdicts_consumed`.
29. [H] simulation-harness 1.13 (delta) + implementer-tdd-loop 2.31 (part) — verdict re-entry.
    * The `UnitFacts` fields `verdicts_open`, `verdicts_ready` and `verdicts_invalid`.
    * The planner: `awaiting_human` whose verdict questions are all validly answered → `verify` ("verdicts answered:
      Q-…"); an invalid answer → `none` with a reason.
    * `Orchestrator._drive`: the `AWAITING_HUMAN` branch tests `verdicts.ready` before the task-answer path.
30. join — verifier 1.19 (delta, part 1) — the ladder runs steps 0, 1, 2, 3, 4, 4a, 9 and 10.
    * Edits: `LADDER`, the `verify.step` ids, and the step calls in `verify_unit`.
    * The report gets the sections Integrity, Traceability, Audit and Human verdicts.
    * `verify_needs_human` writes the verdict questions in the evidence commit.
    * The sticky sections reach the orchestrator through `ctx.shared["notes"]`.

*Exit:*
* Unit tests pass, and every line-14 case behaves as stated.
* On the fixture repo with a fake judge, a fake test writer and a bare remote:
  * a planted conftest hook → FAIL at step 1;
  * an undeclared `# noqa` → FAIL (major);
  * a criterion with no tracing test → NEEDS_HUMAN, with one verdict question and exit 11;
  * the answer `accept: …` pushed to the remote → `l4 plan` says `verify` and round 2 reuses round 1, with no judge
    call in the fake's log → PASS;
  * the answer `yes` → not consumed, and the plan says `none`;
  * an audit test is accepted and committed once;
  * a rejected audit test (it passes against zero values) is a minor finding.

### Stage C — fix units

31. [S] spec-providers 1.32 + 1.33 — `OpenSpecProvider.create_fix_unit(parent, round, findings, spec_delta) -> UnitRef`:
    * runs `openspec new change <parent>-fix-<n>` through the pinned CLI with `TZ=UTC`;
    * writes `proposal.md`, then `tasks.md` (`## 1. Fix`, `- [ ] 1.N <title> (F-…; C-…)`), then the ADDED delta or
      `skip_specs: true`, then `.l4/fix.json`;
    * an existing fix unit raises `FixUnitExists`;
    * `validate --strict`, or the folder is removed and `FixUnitInvalid` is raised (exit 1, nothing committed).

    Plus the new `Finding`, `SpecDelta` and a **separate** `@runtime_checkable` Protocol `FixUnitCapable` (the member
    `create_fix_unit`) in `specs/base.py`. It is not a member of `SpecProvider`: M1.4's `ProviderRegistry` rejects a
    provider that lacks a `SpecProvider` member, and `KiroProvider` has no fix units. For a provider that is not
    `FixUnitCapable`:
    * a FAIL goes straight to `VERIFY_FAIL_EXHAUSTED` (escalated, exit 13);
    * convertible minors on a PASS are listed as "not converted: <framework> has no fix units" (parallel-ownership
      §4, item 7).
32. [S] verifier 1.18 + 5.10 — `plan_fix_unit(family, result, human) -> (groups, SpecDelta | None)`.
    * Convertible findings:
      * on FAIL: deterministic blocker/major findings, `fail` criteria and `reject`ed targets;
      * on PASS, with `fix_minor_findings`: minor findings that have a criterion or a D6 scenario.
    * A spec gap becomes `### Requirement: <requirement of the cited criterion> — regression <round>` plus a
      `#### Scenario: <finding title>`. With no cited criterion, the parent's requirement is used when the parent has
      exactly one; otherwise the finding is not converted.
    * A finding without a criterion becomes a `[chore]` task (D8).
    * Ids are `F-<sha8>`, and at most 5 tasks go into one fix unit. The rest are listed as "not converted".
33. [S] verifier 1.5 (delta) — the judge prompt `judge@3`:
    * the family's criteria, the traceability matrix and the declared suppressions go in as data;
    * a spec-gap finding names its closest criterion, and its `suggested_fix` is one `WHEN … THEN …` sentence.

    The schema stays SPEC 10.3 verbatim.
34. [F] implementer-tdd-loop 1.25 (reduced) — `run_single` for the `[chore]` tasks of a fix unit:
    * template `single@1`;
    * `check_green` with the task's must-pass ids (empty, or the failing tests of the finding);
    * the static gates;
    * `fix(<unit>): <title> [skip ci]` with `L4-TDD: exempt`;
    * `task.tdd_exempt{kind: harness, finding}`.
35. [F] M13-G4 (gap) — `l4.verifier.fixloop`: `fix_hook`, `FamilyProvider`, the child workbench and the child
    re-entry.
36. [F] M13-G5 (gap) — fix-unit identity: `.l4/fix.json`, `is_fix_unit`, `child_snapshots`, the planner rows, and
    `run --unit <fix>` exits 2.
37. join — verifier 1.19 (delta, part 2) — `after_verdict(ctx, wb, result) -> Trigger`, called once at the end of
    `verify_hook`:
    * FAIL with `fix_round < max_fix_rounds` → create the fix unit, then commit `docs(<unit>): fix unit <n> [skip ci]`,
      then `fix.spawned{parent, fix_unit, round, findings, consumed}`, and return `VERIFY_FAIL_FIX`;
    * FAIL with the rounds used up → `VERIFY_FAIL_EXHAUSTED` with a sticky verdict summary (the mirror then labels the
      MR `l4:escalated`);
    * PASS with convertible minors and rounds left → the fix unit, and `VERIFY_PASS`.

    Step 0 covers the family (tasks done, each unit strictly valid). `run_verify` sets `fix=None`.

    After `after_verdict`, M1.5 adds its lesson curation (built on top of this line once M1.3 is on `main`). Curation
    runs only when the trigger is `VERIFY_PASS` and no fix unit was spawned in the round (parallel-ownership C18).
38. join — implementer-tdd-loop 2.31 (reduced) — the `Orchestrator`:
    * `FIXING` → `hooks.fix`:
      * `done` → `FIX_UNIT_DONE`;
      * `blocked` → exit 11, staying `fixing`;
      * `halt` → `BREAKER_OR_BUDGET`;
    * `VERIFIED` with an open fix unit → `MINOR_FINDINGS_FIX`, before the hand-off;
    * `_verify` goes on after `verifying → fixing` (D2);
    * the `fixing` row of `_NEEDS_A_HUMAN` is removed.
39. forge-and-ci 1.33 (delta; M1.1 line 33 has landed, `3a4d58e`) — `PostMergeArchiver._build` archives the parent,
    then `fix_units_of(parent)` in round order, in the one archive commit. The allowed paths and capabilities are
    extended to match.
40. M13-G6 (gap) — `tests/live/test_m1_3_acceptance.py`: the protocol below as code.

*Exit:*
* Unit and contract tests pass. The contract tests use the real pinned OpenSpec 1.14.0 (`skip_specs` and an ADDED
  `— regression 1` delta both validate `--strict`).
* With fakes and a bare remote:
  * **FAIL, then fix, then PASS.** Round 1 FAILs on a rejected criterion. `add-discount-codes-fix-1` is created, its
    task goes red then green with `L4-Unit: openspec:add-discount-codes-fix-1`, and round 2 PASSes. Then the hand-off.
    The ledger order is `verify.verdict FAIL`, `fix.spawned`, `fix.done`, `verify.verdict PASS`.
  * **Minor spec gap.** PASS with a minor spec gap and `fix_minor_findings: true` gives `verified → fixing`, then
    `already-satisfied`, then round 2 PASS, then the hand-off.
  * **No rounds left.** `max_fix_rounds: 0` and a FAIL → `escalated`, exit 13, label `l4:escalated`, sticky summary.
  * **Undeclared suppression.** FAIL → a `[chore]` task (`L4-TDD: exempt`) → PASS.
  * **Blocked fix task.** The question goes into the fix unit's `questions.md`, exit 11, and the plan says `none`.
    After a human answer, the plan says `implement` and the unit resumes.
  * `l4 run --unit openspec:<x>-fix-1` → exit 2.
  * `l4 verify` on a FAIL stops at `fixing` with exit 10.

Then the live protocol (line 40).

## Gaps (no existing task covers them; no tasks.md was edited)

- [ ] M13-G1 Record the JUnit XML of real pytest 9, for `junit_family` xunit1 and xunit2, using a recording
  `conftest.py` that appends `item.user_properties` the way line 2's plugin will.
  * Record failures by `assert`, `pytest.raises` (DID NOT RAISE), `raise NotImplementedError`, `TypeError` and
    `AttributeError`.
  * Commit the outputs with the pytest version.
  * Decide: per-testcase `<properties>` present in both families → properties; else the sidecar
    `.l4-out/l4-trace.json`.

  test: tests/unit/gates/test_junit_recorded.py::test_trace_and_failure_kinds_both_families — code:
  tests/fixtures/recorded/pytest/{trace,failure-kinds}-xunit{1,2}.xml, scripts/record_pytest_junit.sh — verify: uv
  run pytest tests/unit/gates/test_junit_recorded.py -q
  * Why: pytest warns that `record_property` is incompatible with xunit2, and pytest 9's default family is xunit2 [U].
    The red rules need the message shapes [U] (L4-IMP-002 check 3).
- [ ] M13-G2 Add the pytest plugin `l4_trace`.
  * It is a single module in a directory of its own and imports nothing from `l4`.
  * `pytest_configure` registers the marker `l4(*ids)`.
  * Every item with the marker gets one `("l4", id)` user property per id, or a sidecar entry (G1).
  * `l4.gates.trace.trace_env()` gives `PYTEST_ADDOPTS=-p l4_trace` and `PYTHONPATH=<dir>`, the dir taken from
    `importlib.resources`, so that it also works from `.l4/vendor/.venv/.../site-packages`.
  * `Workbench.run_gate` passes it to every gate (`run_gate(..., extra_env=)`, `build_gate_env(..., extra=)`), and
    `agent_step` adds it to the agent env.

  test: tests/unit/gates/test_pytest_trace.py::test_marker_reaches_junit_through_the_gate_env (also
  ::test_plugin_dir_holds_only_the_plugin, ::test_marker_registered_under_strict_markers) — code:
  src/l4/gates/pytest_trace/l4_trace.py, src/l4/gates/trace.py — verify: uv run pytest tests/unit/gates/test_pytest_trace.py -q
  * Why: spike 03 found that `@pytest.mark.l4` never reaches the report without a plugin, and M0 shipped none (implementation map,
    M0 Stage C, verifier 1.14).
- [ ] M13-G3 Pre-satisfied criteria.
  * Trigger: in red, every new test tracing a cited criterion passes in run (a).
  * Check: in place, replace by its zero value every public function and public method of two sets of project source
    modules: those the tests import (resolved inside the repo, outside `tdd.test_globs`), and those changed since the
    unit base. Then run the gate and restore the bytes, checking sha256.
  * Confirmed when at least one of the tests fails by assertion: `criterion.pre_satisfied{task, criterion, tests}`,
    proof `pre_satisfied`, and the tests pass to `classify_red(..., allowed_passing=)`.
  * Otherwise red fails with `not discriminating: C-…`.

  test: tests/unit/implementer/test_presatisfied.py::test_existing_behaviour_is_pre_satisfied_and_a_tautology_is_not —
  code: src/l4/implementer/discrimination.py — verify: uv run pytest tests/unit/implementer/test_presatisfied.py -q
  * Why: the rule is in L4-IMP-002, but implementer-tdd-loop 2.11 covers only `already_satisfied`. The fix units'
    regression scenarios of D6 pin existing behaviour, so their red tests pass on day one.
- [ ] M13-G4 Implement `l4.verifier.fixloop`:
  * `fix_units_of(provider, parent) -> list[UnitRef]`;
  * `FamilyProvider`: criteria, tasks and the done-gate cover the parent plus its fix units, while markers, validation
    and sources stay per unit;
  * `fix_hook(ctx) -> FixOutcome{status: done|blocked|halt, question_ids, reason}`. It opens the last `fix.spawned`
    that has no `fix.done` and runs the leaves of that fix unit with `run_task` on a child workbench:
    * the ref is the fix unit and the provider is `FamilyProvider`;
    * the parent's `LedgerWriter`, push, iteration, sandbox and cache mounts are used (no cold uv cache);
    * the implementer's `Selected` comes from `ctx.shared["implementer"]()`, a zero-argument callable (the bound
      `Orchestrator._select`), so it is the current profile after an M1.2 mid-run fallback; else from its own
      `for_role` (one more `availability.selected` per run);
    * a `RoleLimit` from a fix task: before M1.2 is on `main`, it propagates and parks the unit. After M1.2 is on
      `main`, `fix_hook` calls `ctx.shared["fall_back"](run, task)` (`Orchestrator.switch_profile`, not
      `Factory.on_limit`: `_selected`, the outcome's `profiles` and `L4-Fallback-From` stay current) and retries that
      task once with the returned `Selected` (parallel-ownership C21);
    * `ProtectedSet.extra_dirs` holds the parent's unit dir;
    * `event_context={"fix_unit": <name>}` goes on every event.
  * Before selecting a task, it re-enters the fix unit's own `questions.md`: `question.answered{by: human, fix_unit}`,
    and unblocking is computed over the fix unit's tasks. There is no clarifier, and the parent's verdict questions
    never reach the fix unit's `blocked_tasks`.
  * A blocked task → its questions go into the fix unit's `questions.md`, committed as `docs(<unit>): fix unit questions
    [skip ci]`.
  * All leaves done → `fix.done{fix_unit, round, findings}`.
  * Also: the `HOOKS["fix"]` row and the `Hooks.fix` field.

  test: tests/unit/verifier/test_fixloop.py::test_fix_unit_tasks_run_on_the_parent_branch_and_ledger (also
  ::test_child_question_blocks_then_a_human_answer_resumes, ::test_child_step_cannot_edit_the_parent_spec,
  ::test_child_reuses_the_parent_cache) — code: src/l4/verifier/fixloop.py, src/l4/services.py — verify: uv run pytest
  tests/unit/verifier/test_fixloop.py -q
  * Why: SPEC 12.0 has `fixing → verifying` "when the fix unit's tasks are done", and no task says who runs them
    (verifier 1.18 creates the fix unit; implementer 2.31 only maps edges).
- [ ] M13-G5 Fix-unit identity.
  * `create_fix_unit` writes `<fix>/.l4/fix.json` (`l4/fix-unit@1`: the parent id, the round and the finding ids), and
    `is_fix_unit(ref)` reads it.
  * `l4 plan` shows a fix unit found on the base branch as `none` ("fix unit of <parent>"). `l4 run` never selects one,
    and `--unit` naming one exits 2 ("run the parent").
  * `l4.state.status.child_snapshots(...)` is a separate function, plus one defaulted field `UnitSnapshot.children`. It
    reads each fix unit's `tasks.md` and `questions.md` from the unit branch.
  * Planner rows:
    * `verified` with an open fix unit → `implement` ("fix unit <name> spawned for minor findings");
    * `fixing` → `implement` ("fix unit <name>: d/t tasks");
    * `fixing` whose fix-unit questions are open and not unblocked → `none` ("fixing: fix unit questions open: Q-…").

  test: tests/unit/planner/test_fix_units.py::test_fix_unit_never_planned_alone_and_fixing_waits_for_child_answers
  (also tests/unit/orchestrator/test_fix_unit_cli.py::test_run_unit_naming_a_fix_unit_exits_2) — code:
  src/l4/verifier/fixloop.py, src/l4/state/status.py, src/l4/planner.py, src/l4/orchestrator.py — verify: uv run
  pytest tests/unit/planner tests/unit/orchestrator -q
  * Why: after a merge, `main` holds `<parent>-fix-<n>/` with every task `[x]`. The M1.1 planner would report it as
    `verify` and verify it as a unit of its own [V, `planner.next_action`].
- [ ] M13-G6 Live acceptance of the protocol below: one test per step.
  * It reads pipelines, jobs, MRs, labels, notes, branches, the lock ref, commit trailers, `verification.md`,
    `.l4-out/junit.xml` (artifact) and the ledger through the read-only API and `git ls-remote`.
  * It records the ids.

  test: tests/live/test_m1_3_acceptance.py (marker `live`, needs `L4_LIVE=1`; `L4_LIVE_RECORD` defaults to
  `/tmp/l4_m1_3_ids.json`) — code: tests/live/test_m1_3_acceptance.py
  — verify: L4_LIVE=1 uv run pytest tests/live/test_m1_3_acceptance.py -m live -q
  * Why: verifier 1.22/7.3 and live-validation 2.9 target `add-greeting`/`add-gap` and the M2 pipeline, not this
    protocol.

## Simplifications and deferrals

* **Integrity (step 1).** Deferred:
  * the support-file AST rule (2.7: a patch of the unit's own symbols);
  * test-only dependencies added in green (2.8);
  * gate configuration and script entries (2.9);
  * snapshots and the scope check (2.11);
  * the secret scan (2.12: gitleaks is not on the runner);
  * every language but Python.

  The TDD history trusts the harness's own ledger and the commit graph. Re-running the tests at the red commit is
  deferred.
* **Traceability.**
  * Deferred: the synthetic baseline tree (3.3), `criteria.json` (spec-providers 1.26) and orphan ids (SPEC-005).
  * Implementer tests rest on red-time proofs. Audit tests rest on in-place zero values at head, not on base plus stubs.
* **Audit 4a.**
  * The writer is tool-less (D5). It makes one attempt, with no retry.
  * An audit test that fails at head makes its criterion `needs_human`. The panel review of L4-VER-012 (5.5, 5.6) and
    the verifier red commit are deferred.
  * A `roles.verifier_agent` chain that is configured but unavailable waits for capacity (exit 12, as for judges); an
    empty chain means the step is `not_run`.
* **Deferred verifier steps.** Step 5 (generation; M1.5 builds its e2e form), steps 6 and 7, step 8 S1, the panel with
  `pass_k` and a tie-breaker, the citation re-check (1.12), counterexample execution (it needs the fresh verifier
  worktree, 1.5), flaky repeats (3.2), three internal errors → `escalated` (5.1), and the soft deadline (5.4).
* **Served-model check.** M1.2 builds it: `run_judge` gets `model_mismatch`, and `selection.py` its independence
  constraint. M1.3 only routes the audit writer through it. Fix-unit implementer profiles already land in
  `profiles_used`.
* **Verdicts.**
  * A judge-only finding is identified by its title. A reworded finding in a later round is asked again.
  * An invalid answer (`yes`) still gets a `question.answered` from `Clarifier.reenter`, which clears
    `l4:needs-answers`. The sticky note, not the label, asks for the fix.
* **Fix units.**
  * OpenSpec only: Kiro bugfix specs (5.11) wait for M1.4's Kiro provider.
  * The spec writer is deterministic, so `roles.spec_writer` is unused.
  * Fix-unit questions go to a human, with no clarifier.
  * Not built:
    * `in_review|archived → fixing` (the L4-QMD-006 clarification-apply unit, after H);
    * the base merge in step 0 (5.12);
    * an MR body that lists rounds and fix units;
    * budget extensions for `escalated` (`l4 resume`).
* **Implementer.**
  * `signature_change` (2.4), the green runner-config freeze (2.5; the verifier checks it in line 18) and the scratch
    checkout of the red commit (2.7) are deferred.
  * Human `[docs]`/`[chore]` exemptions in normal units (1.25) are deferred.

## Files

**(a) Owned (new, or mostly this increment's):**

* `src/l4/gates/pytest_trace/l4_trace.py` (the only module in that directory), `src/l4/gates/trace.py`;
* `src/l4/implementer/stubs.py`, `src/l4/implementer/discrimination.py`, `src/l4/implementer/templates/single.md`;
* `src/l4/verifier/{integrity,scan,traceability,audit,verdicts,evidence,fixunit,fixloop}.py`;
* `src/l4/verifier/testwriter.py` and `generated-test.schema.json`, if this increment lands before M1.5 (D5);
* tests:
  * `tests/unit/gates/test_{pytest_trace,junit_recorded}.py`;
  * `tests/unit/specs/test_trace_ids.py`, `tests/contract/test_openspec_fix_unit.py`;
  * `tests/unit/implementer/test_{stubs,vacuity,presatisfied,check_criteria,already_satisfied,single_phase}.py`;
  * `tests/unit/verifier/test_{integrity,scan,traceability,audit,verdicts,resume,fixunit,fixloop,ladder_fix}.py`;
  * `tests/unit/planner/test_fix_units.py`, `tests/unit/orchestrator/test_fix_unit_cli.py`;
  * `tests/fixtures/py_integrity/**`, `tests/fixtures/recorded/pytest/{trace,failure-kinds}-xunit{1,2}.xml`,
    `scripts/record_pytest_junit.sh`;
  * `tests/live/test_m1_3_acceptance.py`;
* `docs/plan/m13-progress.md`, and the `docs/live/` rows.

**(b) Shared files, with the exact edit (additive unless marked):**

| File | Edit | Line |
|---|---|---|
| `src/l4/gates/junit.py` | `TestCase.criteria: tuple[str, ...] = ()`, `TestCase.failure_kind: ... \| None = None`; keyword `parse_junit(..., trace=None)` | 3 |
| `src/l4/gates/runner.py` | keyword `run_gate(..., extra_env=None)` | 2 |
| `src/l4/sandbox/env.py` | keyword `build_gate_env(..., extra=None)` | 2 |
| `src/l4/implementer/workbench.py` | `run_gate` passes `trace_env()`; field `event_context: Mapping[str, Any]` merged in `emit`; `make_workbench(..., event_context=None, extra_unit_dirs=(), caches=None)` | 2, 35 |
| `src/l4/security/protected.py` | `ProtectedSet.extra_dirs: tuple[str, ...] = ()`, matched like `unit_dir` | 35 |
| `src/l4/implementer/tdd.py` | `agent_step`: `\| trace_env()` in the extra env (one expression; M1.2 and M1.4 edit other lines of `agent_step`); `classify_red` keywords `failure_kinds=False`, `allowed_passing=()`; `run_red`: new calls inserted in check order; `RedOutcome.status` value `already_satisfied` and field `criteria`; payload fields `task.red_ok.criteria`, `.suppressions`, `task.done.suppressions` | 2, 7, 12, 13 |
| `src/l4/implementer/loop.py` | `run_task`: `already_satisfied` → no green; a `[chore]` task of a fix unit → `run_single` | 13, 34 |
| `src/l4/implementer/result.py` | `ImplementerResult.suppressions`; new `check_criteria()` | 6, 7 |
| `src/l4/implementer/templates/contract.md`, `red.md` | rules and version lines (`contract@3`, `red@2`) | 5 |
| `src/l4/specs/criteria.py` (M1.4 adds `kiro_criteria`) | new `trace_ids()` | 4 |
| `src/l4/specs/base.py` (M1.4 adds Task fields and the `SpecProvider.done_gate` member) | new `Finding`, `SpecDelta`, `FixUnitExists`, `FixUnitInvalid`; a separate Protocol `FixUnitCapable` with `create_fix_unit` (not a `SpecProvider` member) | 31 |
| `src/l4/specs/openspec.py` | new method `create_fix_unit` | 31 |
| `src/l4/specs/questions.py` | `raise_questions` accepts empty `blocking_tasks` for `Kind: verdict` (rendered `none`); the parser reads `none` as empty, with no `unreadable_blocking` for a verdict question | 25 |
| `src/l4/state/lifecycle.py` (M1.4 adds `RESUMED`) | 4 `Trigger` values, 4 rows; `FIXING` added to two source sets | 28 |
| `src/l4/state/fold.py` (M1.2, M1.4 add fields) | fields `fix_round`, `children`, `open_fix_unit`, `verdicts_consumed`; handlers `fix.spawned`, `fix.done`, `human.verdict` | 28 |
| `src/l4/state/status.py` (M1.4 adds the `parse_tasks=` keyword to `_read_branch` and the `tasks_total` property) | new function `child_snapshots()`; one defaulted field `UnitSnapshot.children`; one call at the end of `load_snapshot` | 36 |
| `src/l4/planner.py` (M1.2 capacity row, M1.4 `required()`) | defaulted `UnitFacts` fields; `facts_of` reads `snapshot.children` and the verdict questions; new rows in `next_action` | 29, 36 |
| `src/l4/orchestrator.py` (M1.2 `_implement`/`_park`, M1.4 `run_command`/`run_unit`) | `_drive`: `FIXING` branch, a verdict branch first in `AWAITING_HUMAN`, an open-fix-unit branch in `VERIFIED`; `_verify`: continues on target `fixing` and copies `ctx.shared["notes"]`; **marked:** the `fixing` row of `_NEEDS_A_HUMAN` is removed; `run_command`: fix units filtered out, `--unit` naming one → exit 2 | 29, 36, 38 |
| `src/l4/services.py` (M1.2 edits `build_services`) | `HOOKS["fix"]`; field `Hooks.fix` | 35 |
| `src/l4/config/preflight.py` (M1.5 adds checks later) | `verifier_agent` joins the optional-roles tuple `("clarifier", "s1_judge")`, so an undefined name is exit 2. This is the only `verifier_agent` name check; M1.5 adds just its "non-empty when e2e is on" rule | 24 |
| `src/l4/verifier/ladder.py` (M1.2 judge selection, M1.5 rows 4e2e/5/8) | `LADDER` rows 1, 4, 4a; step calls in `verify_unit`; one `after_verdict` call at the end of `verify_hook`; `run_verify` nulls `fix` | 30, 37 |
| `src/l4/verifier/aggregate.py` (M1.5 `evidence=`) | keywords `trace`, `human`, `require_traceability`; `aggregate_unit` FAILs on `fail` | 23 |
| `src/l4/verifier/types.py` (M1.2, M1.5 add fields) | `CriterionResult` += `fail`, `disputed`, `uncovered`; `StepStatus` += `reused`; `Finding.id`; `VerifyResult.integrity`, `.trace`, `.audit`, `.human`, `.fix` | 15, 22–27 |
| `src/l4/verifier/report.py` (M1.2, M1.5 add rows) | new sections; `verdict.json` per-criterion evidence | 22–27, 30 |
| `src/l4/verifier/judge.py` (M1.2 edits `run_judge`) | `SYSTEM` and `build_judge_prompt` only; `PROMPT_VERSION = 3` | 33 |
| `src/l4/verifier/preconditions.py` (M1.4: `required()` on the `pending =` line) | step 0 over the family: only the `validate` block becomes a loop over the family's units. Family tasks arrive through `FamilyProvider.tasks`, so the `pending =` line stays M1.4's | 37 |
| `src/l4/postmerge.py` (M1.1 Stage C, landed) | `_build`: the parent, then `fix_units_of(...)` | 39 |

Not touched:
* `config/schema.py`: every key exists [V];
* `commands.py`, `cli.py`;
* `archive.py`: the labels are the generic `l4:<phase>` plus `needs-answers` from the open questions [V];
* `clarifier/*`, `forge/*`, `ci/*`, `state/pending.py`, `init/*`.

Suggested single-writer order for the verifier files edited by three increments (`ladder.py`, `aggregate.py`,
`types.py`, `report.py`): M1.2, then M1.3 (join lines 30 and 37), then M1.5. M1.5 builds its verifier lines (group 2)
on top of the merged M1.3, and does not edit `aggregate.py` (it uses `trace=`).

The exact anchor of every shared-file edit above, and the shared test files (`tests/unit/state/test_lifecycle.py`), are
in `docs/plan/parallel-ownership.md` §2. New tests go in new modules only (rule 2.0.5).

## Interfaces

**Provided to other increments**

* **Traces:**
  * the `l4_trace` plugin;
  * `l4.gates.trace.trace_env()`, `TestCase.criteria`, `TestCase.failure_kind` and `l4.specs.criteria.trace_ids`.

  M1.5's generated and e2e tests trace by the marker or by the name `test_l4_c_<hex>`. Its `trace_e2e` is superseded by
  `trace_criteria`.
* **Red-phase helpers:**
  * `l4.implementer.stubs`: `classify_red_changes`, `enforce_red_scope`, `zero_value_variant`;
  * `l4.implementer.discrimination`: `zero_values_in_place(wb, scope)`, `vacuity_check`, `confirm_pre_satisfied`.
* **Evidence:**
  * `l4.verifier.traceability`: `CriterionEvidence`, `TracingTest(id, status, proof, adequate)` and `trace_criteria`;
  * proofs `zero_value | pre_satisfied | red_assertion | pass_to_pass | audit | generated`. M1.5's `GeneratedEvidence`
    enters as `proof="generated"`;
  * `aggregate_criterion(..., trace=, human=)`.
* `l4.verifier.testwriter` with `l4/generated-test@1` (D5).
* **Verdicts:** `l4.verifier.verdicts` (`raise_verdict_questions`, `verdicts.ready`, `consume_verdicts`) and the
  `human.verdict` event.
* **Fix units:**
  * `SpecProvider.create_fix_unit`, `Finding`, `SpecDelta`;
  * `l4.verifier.fixloop`: `is_fix_unit`, `fix_units_of`, `FamilyProvider`, `fix_hook`;
  * `<fix>/.l4/fix.json` (`l4/fix-unit@1`);
  * events `fix.spawned{parent, fix_unit, round, findings, consumed}` and `fix.done{fix_unit, round, findings}`.

  Consumers:
  * M1.5 curation origin (a): a finding in `fix.done` followed by a PASS round;
  * M1.4: the Kiro bugfix `create_fix_unit` (2.8) and the `verify-fail-fix-pass` scenario (this increment supplies the
    YAML once M1.4's simulation manifest exists).
* **Lifecycle:**
  * triggers `VERDICTS_ANSWERED`, `FIX_UNIT_DONE`, `MINOR_FINDINGS_FIX`, `VERIFY_FAIL_EXHAUSTED`;
  * `UnitState` fields `fix_round`, `children`, `open_fix_unit`, `verdicts_consumed`;
  * the `Hooks.fix` hook.
* **Workbench and gate plumbing:** `Workbench.event_context`, `ProtectedSet.extra_dirs`, `run_gate(extra_env=)`,
  `build_gate_env(extra=)`.

**Needed from other increments**

* **The seam commit S0** (`parallel-ownership.md` §3.0): `l4.verifier.testwriter` and its schema (line 24).
* **M1.1 Stage C (landed, `98e4939`):**
  * `l4 upgrade` (G11) and the routed job;
  * the pending ledger after H, unchanged;
  * `MirrorHook.sync(notes=)` with several sections;
  * `PostMergeArchiver._build` stable before line 39.

  Until line 39 lands, a merged parent's fix units stay on `main`. They are ignored by the planner (G5), but their
  regression requirement does not reach `openspec/specs/`.
* **M1.2:**
  * `verifier/selection.py` (`independence_constraint`, `select_judge`, `vendor_provenance`);
  * the served-model check in `run_judge`;
  * `Factory.for_role(..., constraints=)` serving `verifier_agent` as a required role (`WaitingCapacity`);
  * the `independence:` line.

  If M1.2 has not landed by line 24, the audit writer uses M1.1's `require_independent_judge` on
  `roles.verifier_agent[0]`.
* **M1.4:**
  * `implementer.tasks.required()`: `FamilyProvider`'s done gate uses it when it exists. Fix units are OpenSpec-only,
    so the result is correct before and after M1.4;
  * `status._read_branch(…, *, parse_tasks=parse_openspec_tasks)`, which keeps today's behaviour by default.
    `child_snapshots` calls it without the keyword;
  * `SpecProvider.done_gate` joins the Protocol, and `FamilyProvider` implements it from the start;
  * the simulation manifest and its fixture gate (parallel-ownership C19). Whichever of M1.3 and M1.4 merges second
    re-baselines the expected events of the ready scenarios and supplies and flips `verify-fail-fix-pass`.
* **M1.5:** none. It consumes `testwriter` (from S0), `trace_criteria(extra_reports=)`, `commit_verifier_tests` and
  `after_verdict`. It has no `evidence=` keyword, and its step 4e2e becomes step 4 (C8).

## Live exit protocol on `example-group/dummy-agentic` through `l4-runner`

Facts relied on:
* `main` is protected, merged source branches are deleted, the job timeout is 180 min, and runner #12 is tagged
  `agentic` [V, M1.1 protocol];
* the logins: Claude Code `pro` (judge and audit writer) and Codex (implementer) [V, docs/runner/README.md];
* `L4_FORGE_TOKEN` exists.

No new credential is needed. The operator may act as the human (SPEC Q9).

Costs:
* 1 pipeline (branch 1A) or 2 (branch 1B);
* Codex: 2 red/green steps plus up to 5 fix-task steps;
* Claude: 4–8 calls. Each full round has one judge call and at most 2 audit calls (line 24's cap); repairs come on
  top [I].

0. **Operator, local.**
   0. M1.1's G13 and M1.2's live protocol (with its cleanup, step 6) have passed (parallel-ownership §5.3). The harness
      pinned by `l4 upgrade` is the `main` commit right after M1.3's merge.
   1. M1.3 is built, `uv run pytest -q` is green, the Stage A/B/C exits passed, and the fix-unit contract test passed
      against the pinned OpenSpec 1.14.0.
   2. On a clone of `main`, fetch `l4/*` and `refs/l4/locks/*`, then run `uv run --project <harness> l4 plan --json`.
      Expected: every unit `none`.
   3. Run `l4 upgrade --repo <clone> --harness <harness>`. Expected: changes only under `.l4/vendor/`,
      `.l4/ci/l4.gitlab-ci.yml` and `.l4/bin/l4`, plus the two pin scalars.
   4. Add to `.l4/config.yaml` (`roles` exists; append the chain):

      ```yaml
      roles:
        verifier_agent:
        - claude-code
      verifier:
        fix_minor_findings: true
        max_fix_rounds: 1
        audit_sample_ratio: 0.1
      ```

   5. Write the seed texts below.
   6. Run `openspec validate add-shipping-fee --strict` with the pinned CLI (expected valid), and `l4 doctor` (exit 0).
1. **Maintainer:** push two commits to `main` in one push: "Upgrade the vendored L4 harness to `<sha>` (M1.3)" and
   "Seed add-shipping-fee". Expected pipeline P1 (push, `main`, job `l4`):
   * **Plan:** `add-shipping-fee implement`, every other unit `none`.
   * **Task 1.1, red:**
     * `.l4-out/junit.xml` (or `.l4-out/l4-trace.json`) names both criterion ids on the new tests;
     * `stub.purity{task: "1.1"}`;
     * `task.red_ok.criteria` has both ids with proof `zero_value`;
     * the red commit carries `L4-TDD: red`, the green commit `L4-TDD: green`.
   * **Stop condition:** no id reaches the report. That means the trace env did not reach pytest under bwrap [U]. Record
     it and stop: the round would end NEEDS_HUMAN with both criteria uncovered.
   * **Round 1 `verification.md`:**
     * ladder rows 0, 1, 2, 3, 4, 4a, 9, 10;
     * step 1 `ok`, with its sub-check rows;
     * the matrix: 2/2 covered, proof `zero_value`;
     * 4a: one accepted audit test, committed in `test(add-shipping-fee): verifier round 1 [skip ci]` with `L4-Phase:
       verifying`;
     * the judge's served model. Once M1.2 has landed, also its `independence:` line (`verified`, or `declared
       (unverified)` after a fallback).
   * **Then exactly one of:**
     * **1A, PASS with a convertible minor finding:**
       1. `fix.spawned{fix_unit: add-shipping-fee-fix-1, round: 1}`.
       2. The commit `docs(add-shipping-fee): fix unit 1 [skip ci]` adds `openspec/changes/add-shipping-fee-fix-1/`.
          That folder holds `.openspec.yaml`, `proposal.md`, `tasks.md` (`1.N … (F-…; C-…)`), `.l4/fix.json` and
          `specs/shipping/spec.md`. The spec has `## ADDED Requirements` → `### Requirement: Shipping fee — regression
          1` and one scenario per converted finding.
       3. The phases go `verifying → verified → fixing`.
       4. Each fix task ends either with `L4-TDD: already-satisfied` plus `criterion.pre_satisfied`, or with red then
          green. Its commits carry `L4-Unit: openspec:add-shipping-fee-fix-1`.
       5. `fix.done`, then `fixing → verifying`.
       6. Round 2: 2 + k criteria, all covered → PASS. The remaining minors are listed "not converted: fix rounds used
          1/1".
       7. Hand-off H. The MR `[l4] add-shipping-fee: shipping fee` is ready, labelled `l4:in_review`, and its head is H.
          The lock ref holds the pending ledger. Job exit 0.
     * **1B, NEEDS_HUMAN:**
       * `questions.md` on `l4/openspec/add-shipping-fee` has one `Kind: verdict` question per `needs_human` criterion
         and per judge-only blocker/major finding, each with `Blocking tasks: none`;
       * a draft MR labelled `l4:awaiting_human` and `l4:needs-answers`, whose sticky note lists them;
       * exit 11. Go to step 2.
     * **1C, a miss:** a hand-off with no fix unit (nothing convertible); or Codex reports `blocked`; or task 1.1 halts.
       See the retry rule.
2. **1B only. The operator, as the human:** one Web IDE commit on `l4/openspec/add-shipping-fee`.
   * A criterion question: answer `accept: <reason>` when its tracing tests check the scenario, else `reject:
     <reason>`.
   * A spec-gap question: answer `reject: WHEN an order with a subtotal of 50.00 ships to RO THEN the shipping fee is
     0.00`. The behaviour comes from the requirement text.
   * Set Status `answered` on each.

   Expected P2 (push, `l4/**`):
   * the plan says `verify` ("verdicts answered: Q-…");
   * `question.answered{by: human}`, one `human.verdict` per question, and `awaiting_human → verifying`;
   * round 2 shows steps 0–9 as `reused (round 1)`, there is no `verify.judge` event for it, and it FAILs on the
     rejected finding;
   * `fix.spawned{consumed: [Q-…]}`, and a fix unit as in 1A, holding the operator's scenario verbatim;
   * `fixing`, then the fix tasks, then round 3 with the full ladder → PASS → H → MR ready with only `l4:in_review`. The
     sticky note says nothing is waiting. Exit 0.

   If round 3 is NEEDS_HUMAN: answer `accept` where the evidence holds. Then P3 reuses round 3 and PASSes. A `reject`
   there escalates (exit 13, `max_fix_rounds: 1`): record it and stop.
3. **No human: loop safety**, read-only over every pipeline since step 1:
   * the `[skip ci]` checkpoints (red, green, already-satisfied, verifier round, fix unit, questions) have no pipeline,
     or a skipped one;
   * H has the project's `test` job and no `l4` job;
   * no `l4` job ran on a harness commit.
4. **Operator, read-only**, on a checkout of H:
   * `openspec validate add-shipping-fee-fix-1 --strict` passes;
   * `git log --format='%h %(trailers:key=L4-Unit,valueonly) %(trailers:key=L4-TDD,valueonly)'` shows, per
     (unit, task), red before green, or a single `already-satisfied` commit;
   * the audit test file exists and carries `@pytest.mark.l4`.
5. **Optional, HUMAN (once line 39 has landed):** merge the MR. The archive MR moves `add-shipping-fee`, then
   `add-shipping-fee-fix-1`, under `openspec/changes/archive/`. `openspec/specs/shipping/spec.md` then holds both
   requirements.

**Retry rule (1C).**
1. Record the pipeline and the job.
2. Reset the unit: close its MR, delete `l4/openspec/add-shipping-fee` and `refs/l4/locks/openspec/add-shipping-fee`.
3. Start one web pipeline on `main`.

A second 1C is a FAIL of the live fix loop, recorded in `docs/live/README.md`. The deterministic Stage C exit still
stands.

**Pass** = step 1 then 1A, or 1B then step 2; and steps 3 and 4. Record every pipeline, job and MR id in
`docs/live/README.md`.

### Seed texts (step 0.5)

The requirement text decides everything: country matching, the threshold, a negative subtotal and the order of the
checks. So contract@2's rule "business data the spec leaves open is a product question" cannot block the run. Only the
scenarios are sparse, on purpose.

`openspec/changes/add-shipping-fee/.openspec.yaml`:

```yaml
schema: spec-driven
created: 2026-10-05
```

`openspec/changes/add-shipping-fee/proposal.md`:

```markdown
# Proposal: shipping fee

## Why
Checkout must show what shipping costs before the customer pays, and the fee depends on the country the order ships to.

## What Changes
- Add `pricing.shipping.shipping_fee(subtotal, country)` and the exception `UnsupportedShippingCountry`.

## Capabilities

### New Capabilities
- `shipping`: shipping fees by destination country.

### Modified Capabilities

## Impact
New module `src/pricing/shipping.py`, its exports in `src/pricing/__init__.py`, tests under `tests/`.
```

`openspec/changes/add-shipping-fee/specs/shipping/spec.md`:

```markdown
# Spec Delta

## Purpose
Shipping fees charged on an order, by destination country.

## ADDED Requirements

### Requirement: Shipping fee
`pricing.shipping.shipping_fee(subtotal, country)` SHALL return the shipping fee of an order as a `Decimal` quantized to 0.01 with ROUND_HALF_UP. `subtotal` is a `Decimal`; `country` is an ISO 3166-1 alpha-2 code matched exactly as given, so `ro` is not `RO`. The subtotal is checked first: a negative subtotal SHALL raise `ValueError`. The fee is 4.99 for `RO` and 9.99 for `DE`, and an order to `RO` or `DE` whose subtotal is 50.00 or more ships free (fee 0.00). Any other country SHALL raise `UnsupportedShippingCountry`, defined in `pricing.shipping`, whatever the subtotal.

#### Scenario: Romanian order below the free-shipping threshold
- **WHEN** an order with a subtotal of 20.00 ships to `RO`
- **THEN** the shipping fee is 4.99

#### Scenario: German order below the free-shipping threshold
- **WHEN** an order with a subtotal of 20.00 ships to `DE`
- **THEN** the shipping fee is 9.99
```

`openspec/changes/add-shipping-fee/tasks.md`:

```markdown
# Tasks

## 1. Shipping fee

- [ ] 1.1 Add `src/pricing/shipping.py` with `shipping_fee(subtotal, country)` and `UnsupportedShippingCountry`, and export both from `pricing`
```

The G9 lint (L4-ODD-004) finds no conflict: no base spec has a WHEN about shipping.

## Risks

* **Junit properties under xunit2 are [U].** G1 decides between properties and the sidecar before anything builds on
  them. The `PYTEST_ADDOPTS`/`PYTHONPATH` env reaching pytest inside bwrap on the runner is [U] until P1; P1's stop
  condition catches it.
* **More red attempts.** The stub rebuild, the failure-kind rule and per-criterion vacuity reject reds that M0 accepted.
  Codex on low effort may spend its `max_task_attempts` and halt (exit 13). Mitigations:
  * the must-pass fixtures (line 14);
  * feedback that names the offending test or symbol;
  * a lenient `None` failure kind for unrecognised messages.
* **The judge decides which branch the live run takes** (1A, 1B or 1C). The judge found 4 minor spec gaps on a complete
  spec [V, docs/live]. The seed leaves five behaviours without a scenario, so a convertible finding is likely [I].
  There is one retry.
* **Model-written scenarios in specs.** In branch 1A, a scenario the judge phrased becomes spec text. Bounds:
  * it describes current behaviour (D6), and is usually `already-satisfied`;
  * it is visible in the MR diff;
  * a human reviewer can still reject the MR.
* **The in-place zero-value runs** leave rewritten files if the harness dies mid-gate. The worktree is recreated on every
  run [V, code], and no commit can happen before the sha256-checked restore.
* **Resume at aggregation** treats a questions-only or verifier-only commit as "no new subject" (D4, doc change owed).
  A human who answers and also edits code gets a full round, which is the safe direction.
* **Merge conflicts:**
  * three increments edit `ladder.py`, `aggregate.py`, `types.py` and `report.py`;
  * M1.2, M1.4 and M1.5 also edit `orchestrator.py`, `planner.py`, `fold.py` and `tdd.py`.

  Mitigations:
  * M1.3's logic lives in new modules;
  * shared edits are keywords, new branches or new fields, each at its anchor in `parallel-ownership.md` §2.1;
  * the merge order is M1.2 → M1.3 → M1.4 → M1.5, with M1.5's verifier lines built after M1.3 is on `main`.
* **Fix units on `main` before line 39** keep their ADDED requirement out of `openspec/specs/` (see Interfaces).
* **Claude `pro` usage.** About 4–8 calls on top of M1.1's [I]. With M1.2, an exhausted judge falls back to a declared
  vendor, and the report then says `independence: declared (unverified)`.
* **A mid-round limit on the audit writer.** A configured `roles.verifier_agent` is a required role, so its exhaustion
  is exit 12 (`waiting_capacity`). Without M1.2's planner row, `waiting_capacity` is not actionable [V,
  `planner.py`], so the unit stalls until that row lands. Mitigations: the audit cap of 2 per round; the operator may
  set `audit_sample_ratio: 0` and rerun.
* **Codex and the new contract.** It may still not tag tests. Line 6 derives the criteria from the traces, so a run
  fails only when no test traces anything, and verify then reports the criteria `uncovered`.

## Doc changes owed (no build line; SPEC.md is not edited here)

* **L4-CRT-002 / §4.7:**
  * the marker is registered by the harness plugin, not by `l4 init`;
  * the trace channel is the junit property `l4`, or the sidecar `.l4-out/l4-trace.json` (whichever G1 picks);
  * the names `test_l4_c_<hex>` count as a trace.
* **L4-IMP-002 check 3:** an unrecognised failure message is accepted. **L4-IMP-003:** `already_satisfied` is
  harness-initiated when every cited criterion is pre-satisfied.
* **L4-VER-002 step 4a:**
  * the tool-less writer with `l4/generated-test@1`;
  * at most 2 audit tests per round, pre-satisfied criteria first;
  * an empty `roles.verifier_agent` means the step is `not_run`.
* **L4-VER-006:** deterministic findings without a criterion become `[chore]` single-phase fix tasks (`L4-TDD:
  exempt`); the spec-gap scenario source is the order of D6; at most 5 tasks go into one fix unit.
* **L4-VER-011:** the `subject_sha` definition of D4.
* **L4-VER-013:** `reject` is consumed by the fix unit it produces; `accept` is durable (D3).
* **L4-QMD:** verdict questions have `Blocking tasks: none`.
* **§12.0:** `verifying → fixing` continues in the same run when the fix hook exists (D2).
* **The design `verifier` D1:** step 4 is now built with red-time proofs.
* **L4-STA:** the fix unit's events live in the parent's ledger with `fix_unit` context, and `.l4/fix.json` exists.
