## Purpose

The verifier's judges see a Kiro unit's requirements, bugfix items and criteria whole, and a spec file the harness
could not read whole is named to the judge and held, never dropped.

## ADDED Requirements

### Requirement: L4-KSP-014 The judges see a Kiro unit's requirements and criteria whole
The step-9 judge SHALL receive the `requirements.md` and `bugfix.md` of the unit and of each fix unit, and every
criterion's full text, whatever the size of `design.md`. A spec file over 262,144 bytes, or one that is not a regular
file, SHALL be named under `Not shown in full` in the judge prompt and SHALL add a hold that names it. The S1 state of
a criterion SHALL keep the criterion's text whole.

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
- **THEN** the specification shows the first 262,144 bytes of `design.md`, its `Not shown in full` block names
  `.kiro/specs/<unit>/design.md` (`oversize`, `262144 of 300000 bytes read`), and the prompt version is `judge@10`
- **AND** the round has the hold `the spec file .kiro/specs/<unit>/design.md is larger than 262144 bytes: the judge
  saw only its start`, and the ledger has `prompt.truncated{role: judge}` naming it
