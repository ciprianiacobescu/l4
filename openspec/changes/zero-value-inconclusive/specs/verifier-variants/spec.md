## Purpose

The verifier judges its own variant runs the way the red phase does, so a run that could not run a test is never a
rejection, and the judge sees the pre-satisfied evidence that the harness did not prove.

## ADDED Requirements

### Requirement: L4-VER-050 The audit tells an inconclusive run from a rejection
Step 4a SHALL judge the zero-value run of its audit tests by L4-IMP-060 against the audit's head run: confirmed is
accepted, not applicable (L4-IMP-062) is accepted with its label, refuted is rejected (a minor finding), and
inconclusive is recorded `inconclusive` with its reason: no finding, not committed, listed in `verification.md`. A test
chore whose added tests are all inconclusive SHALL be held with a harness question (L4-IMP-063), not accepted.

#### Scenario: SCN-VER-150 (−) An inconclusive audit run is not a rejection
- **GIVEN** an audit test for a pre-satisfied criterion that passes at head, and a zero-value run that ran no test
  (`E   TypeError: 'NoneType' object is not callable` in every collection error)
- **WHEN** step 4a judges it
- **THEN** `verify.audit` records `status: inconclusive` with that line in its reason, no minor finding is raised, the
  file is not committed, and `verification.md` lists the record with its reason

#### Scenario: SCN-VER-151 (+) A test chore whose check cannot decide is held
- **GIVEN** a test chore that added two tests citing a criterion, and a `discriminate_extra` whose zero-value run and
  base run were both inconclusive for them
- **WHEN** the chore's discrimination check runs
- **THEN** the chore is held with a harness question (`check: tests`), no attempt is used and nothing is committed

#### Scenario: SCN-VER-155 (+) The audit's zero-value run keeps a decorator factory
- **GIVEN** an audit test of `Store.add` and the modules of SCN-IMP-302
- **WHEN** step 4a runs its zero-value run
- **THEN** `traced` keeps its body, the audit test fails by assertion there, and the record is `accepted`

### Requirement: L4-VER-051 The judge sees evidence the harness did not prove
A tracing test whose red proof has `via: not_applicable`, `human_override` or `agent_override` SHALL count as evidence and
be labelled in the judge's per-test list, in the satisfied block of L4-VER-018 and in `verification.md`. The label is the
guarantee: step 4a samples such a criterion first but audits at most `MAX_AUDIT_PER_ROUND` per round and may be off.

#### Scenario: SCN-VER-153 (+) The judge sees a not-applicable criterion
- **GIVEN** a unit whose `task.red_ok` proves a criterion with `via: not_applicable`
- **WHEN** the judge prompt and `verification.md` are written
- **THEN** the criterion's test reads `(passed, pre_satisfied, not applicable: no project code)` in both

#### Scenario: SCN-VER-154 (+) The judge sees an override
- **GIVEN** an already-satisfied task whose criterion was accepted by harness question Q-007
- **WHEN** the judge prompt is written
- **THEN** the satisfied block's line reads `Proved by: C-… (tests: …; accepted by Q-007: the check was
  inconclusive)`

#### Scenario: SCN-VER-156 (+) The judge tells an agent's acceptance from a person's
- **GIVEN** an already-satisfied task whose criterion was accepted through harness question Q-007 by an agent, under
  `clarifier.answer_by_agents`
- **WHEN** the judge prompt and `verification.md` are written
- **THEN** the proof is `via: agent_override`, the ledger has `question.answered{by: agent}` and `check.accepted{by:
  agent}`, and the satisfied block reads `…; accepted by an agent through Q-007: the check was inconclusive)`

#### Scenario: SCN-VER-157 (−) A label is not an audit
- **GIVEN** five pre-satisfied criteria recorded `via: not_applicable`
- **WHEN** step 4a samples them
- **THEN** at most two are audited and the others are listed as skipped, and every one still carries its label in the
  judge's list; with no verifier agent none is audited

## MODIFIED Requirements

### Requirement: L4-VER-009 Tests people or a test chore wrote: bounded runs and a true reason
The rest of L4-VER-009 is unchanged. The verifier's two runs for tests that people or a test chore wrote SHALL be
judged by L4-IMP-060: at most two gate runs per round, plus at most two keep reruns of the zero-value run
(L4-IMP-061), none without such a test. A test whose runs were inconclusive is no proof, and its minor finding SHALL say
`inconclusive: <reason>`, not that it passes against the zero values and on the base.

#### Scenario: SCN-VER-152 (−) An extra test whose runs were inconclusive says so
- **GIVEN** a test a person wrote, carrying a criterion, whose zero-value run did not import its module and whose
  module cannot import at the unit base
- **WHEN** step 4 decides its proof
- **THEN** it is no evidence, and its minor finding says `inconclusive:` with the `E` line
