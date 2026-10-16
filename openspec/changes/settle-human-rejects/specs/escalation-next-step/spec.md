## Purpose

A unit escalated because no finding of its round can be converted into a fix task tells the person what to do, and
does not send them to a retry that repeats the verdict.

## ADDED Requirements

### Requirement: L4-OPS-022 The escalation with no convertible finding names feedback as its way out
For a unit in phase `escalated` whose recorded cause is `no_convertible_finding`, the `Next:` line of
`l4 status --unit` and the `next` of `--json`, the `Next:` line of the refusal of `l4 run --unit` (L4-OPS-010) and the
sticky note section `Escalated` SHALL say: give the fix that the human's finding asks for as feedback
(`l4 feedback add --unit U --kind behaviour --when ... --then ... --text ...`, then the git lines that `add` prints),
then `l4 retry --unit U --reason TEXT`, and that a retry alone repeats the same verdict. Every other cause SHALL keep
its text.

#### Scenario: SCN-OPS-38 (+) The status line names feedback first
- **GIVEN** a unit `escalated` with `halt_reason: no_convertible_finding`
- **WHEN** `l4 status --unit U` and `l4 status --json` run
- **THEN** `Next:` and `next` name `l4 feedback add --unit U --kind behaviour --when`, then `l4 retry --unit U --reason TEXT`, and say that a retry alone repeats the same verdict

#### Scenario: SCN-OPS-39 (−) Other causes keep their text
- **GIVEN** units `escalated` with `fix_rounds_exhausted` and with `same_failure`, and a unit `halted`
- **WHEN** `l4 status --unit U` runs for each
- **THEN** `Next:` is `l4 retry --unit U --reason TEXT`
