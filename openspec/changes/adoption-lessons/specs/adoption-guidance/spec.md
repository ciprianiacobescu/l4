## Purpose

What people and agents read when they adopt L4 or write specs for it: a short spec-writing checklist in the skill, and adoption docs and messages that match the code.

## ADDED Requirements

### Requirement: L4-ADO-014 The skill teaches specs that pass the readiness review
The skill SHALL hold `references/spec.md` (at most 450 words, linked from `SKILL.md`), a checklist with one line
per rule:
- scenarios for every SHALL, failure cases included;
- no line anchors;
- named helpers;
- delivered work in prose;
- the review budgets;
- ADDED with a Purpose where there is no baseline;
- kept scenario names;
- `depends_on` for a shared function;
- no hidden dependencies;
- the runner's tools;
- short requirements;
- both validators run before the push.

#### Scenario: SCN-ADO-40 (+) A delta on a capability without a baseline
- **GIVEN** an agent with the skill, asked to write a change that adds behaviour to a capability that
  `openspec/specs/` lacks
- **WHEN** it writes the delta
- **THEN** it writes `## ADDED Requirements` with a `## Purpose`, and runs `openspec validate <change> --strict` and
  `validate_plan.py` before the push

#### Scenario: SCN-ADO-41 (+) The skill stays short
- **GIVEN** the skill files
- **WHEN** their words are counted
- **THEN** `references/spec.md` has at most 450 words, and `SKILL.md` gains one line

### Requirement: L4-ADO-018 The adoption docs and messages say what the code does
The adoption reference, the quickstart, the runbook, the README and the workflow template comments SHALL agree with
the harness on six points:
- the default branch on an integration base;
- the forge token and CI;
- the action repository;
- a laptop's push credentials;
- the review budgets;
- holding existing specs.

`l4 init --action` without an install origin SHALL name the cause and the command that runs the released harness.

#### Scenario: SCN-ADO-50 (+) An integration-base adoption from the reference
- **GIVEN** a person who follows the adoption reference on a repository with existing specs and a `staging` base
- **WHEN** they finish
- **THEN** they have set `yolo.hold`, made no backlog plan, and added no deployment branch by hand

#### Scenario: SCN-ADO-51 (−) init from a checkout
- **GIVEN** `l4` running from a checkout, and no `--action-repo`
- **WHEN** `l4 init --ci github --action` runs
- **THEN** it exits 2, says that a checkout has no install origin, and prints the
  `uv tool run --from git+https://github.com/OWNER/l4@vX.Y.Z` form and `--action-repo`
