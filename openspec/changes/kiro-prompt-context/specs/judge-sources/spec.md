## Purpose

The verifier's judges see a Kiro unit's requirements, bugfix items and criteria whole, and a spec file the harness
could not read whole is named to the judge and held, never dropped.

## ADDED Requirements

### Requirement: L4-KSP-014 The judges see a unit's criteria, tasks and spec files, and say what they did not see
The step-9 judge SHALL receive each criterion's full text, each done task's whole block, and the spec files of the unit
and its fix units, in the implementer's priority order within `verifier.judge_context_budget_tokens` (48000). It SHALL
name every file not shown whole under `Not shown in full`; an unread file, or a cut requirements, bugfix or spec file,
SHALL hold the round. It SHALL check each task's text against the diff. Step 1's scope SHALL read a Kiro unit's
requirements and bugfix files.

#### Scenario: SCN-IMP-298 (+) The judge and S1 see the requirements and the criteria beside a long design
- **GIVEN** the probe unit with its 125,492-character `design.md`, and a fix unit `tip-calc-fix-1` whose `bugfix.md`
  restates `Req 1.2`
- **WHEN** the step-9 judge prompt and the S1 states of round 2 are built
- **THEN** the judge's specification holds `requirements.md`, `design.md` and `tip-calc-fix-1/bugfix.md` whole, its
  criteria list holds each criterion's full text, and no hold names a spec file
- **AND** each S1 state starts with `Criterion <id>:` and the criterion's whole text

#### Scenario: SCN-IMP-299 (−) A spec file too big to read is named to the judge and held
- **GIVEN** a Kiro unit whose `design.md` has 300,000 bytes
- **WHEN** its judge prompt is built
- **THEN** the specification shows the start of `design.md`, its `Not shown in full` block names
  `.kiro/specs/<unit>/design.md` (`oversize`, `262144 of 300000 bytes read`), and the prompt version is `judge@10`
- **AND** the round has the hold `the spec file .kiro/specs/<unit>/design.md is larger than 262144 bytes: the judge
  saw only its start`, and the ledger has `prompt.truncated{role: judge}` naming it

#### Scenario: SCN-KSP-001 (+) The judge checks each done task's text, detail bullets included
- **GIVEN** the probe unit with its leaf ticked done, and a diff that never rejects a percent above 100
- **WHEN** the step-9 judge prompt is built
- **THEN** it holds `## Done tasks` with a block `<l4:data kind="tasks">` that carries the checkbox line, `TASK-DETAIL-MARKER:
  reject a percent above 100 with ValueError as well`, `Use Decimal throughout` and the `_Requirements:_` line
- **AND** the system rule asks for a finding titled `task 1: …` of severity major or minor, never blocker for this
  reason alone, and a task that the `satisfied` block already asks about is not listed twice

#### Scenario: SCN-KSP-002 (−) A requirements file cut by the judge's budget holds the round
- **GIVEN** `verifier.judge_context_budget_tokens: 1000` and a `requirements.md` of 30,000 characters in 80 sections
- **WHEN** the judge prompt is built
- **THEN** `Not shown in full` names `requirements.md` as cut (`budget`) and the round has the hold `the spec file
  .kiro/specs/tip-calc/requirements.md was cut to fit the judge's budget: the judge saw only part of it`
- **AND** a cut `design.md` is only named, with no hold

#### Scenario: SCN-KSP-003 (+) Step 1's scope reads a Kiro unit's requirements
- **GIVEN** a Kiro unit whose `requirements.md` names `` `src/shop/pricing.py` `` and whose design and tasks name no path
- **WHEN** the unit's declared scope is read
- **THEN** `src/shop/pricing.py` is declared, as if the design had named it

