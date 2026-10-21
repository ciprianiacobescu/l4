## Purpose

A test fixture that spells a token whole fails the implementer's attempt with advice on how to write it, before any
gate or commit, instead of halting the unit at the push.

## ADDED Requirements

### Requirement: L4-SEC-008 An implementer step's changes are read for secrets before any gate or commit
After an implementer step (red, green or single) returns and the protected paths are put back, the harness SHALL read
the lines that the worktree adds to `HEAD`: the added lines of a tracked file, every line of a new file, never the
run's ledger. It SHALL use the redactor of L4-OBS-002, as L4-SEC-007 does for outgoing commits. On a hit the attempt
SHALL fail before any gate runs. Its changes SHALL be discarded, and one `guard.secret {path, kind, task, phase,
attempt}` SHALL be recorded per path and kind, never with the value. The failure SHALL name each path and kind and say
how to build such a value at run time from parts, so that no file holds the whole shape. The attempt SHALL count as any
failed attempt does. The push scan of L4-SEC-007 SHALL stay as the last net. A deleted file, a symlink, a binary file
and a new file over 2,000,000 bytes add nothing to the step check.

#### Scenario: SCN-SEC-20 (−) A fixture that spells a token whole fails the attempt, not the unit
- **GIVEN** a red step whose new test in `tests/test_redact.py` holds `SECRET = "mk_agent_…"` (20 characters after the
  prefix), in a file whose existing tests already hold such strings
- **WHEN** the step returns
- **THEN** no gate runs, the changes are discarded, the ledger has `guard.secret{path: tests/test_redact.py, kind:
  mintkey, task, phase: red, attempt: 1}` and no `breaker.tripped`, and the attempt fails with a message that names the
  path and the kind and says to build the value from parts

#### Scenario: SCN-SEC-21 (+) A value built from parts and a token already at head pass the step check
- **GIVEN** a step that adds `NEW = "mk_" + "agent_" + "A" * 24` to a file whose unchanged line holds a whole token
- **WHEN** the step returns
- **THEN** the step check finds nothing and the step goes on to its gates
