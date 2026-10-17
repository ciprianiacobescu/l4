## Why

A consumer repository has 18 Kiro specs, 17 of them finished long before it adopted L4 (about 700 ticked tasks). With
`spec.frameworks: [openspec, kiro]`, doctor's SPEC-002 is an error, so every L4 job of the repository would stop: the
Kiro provider treats finished history as if it were work to run. Five defects, found by reading the specs with L4's
own provider:

1. A finished leaf without a `_Requirements:_` line, or with a reference no criterion has, is an ERROR under
   `sdd.enforce` (`leaves_without_requirements` and `_task_issues` count done tasks too). L4 never runs a done task.
2. A `## Task Dependency Graph` whose block is not JSON (a mermaid diagram) is an ERROR in validation, although the
   task reader already falls back to document order with a warning.
3. A whole-requirement reference `_Requirements: 1_` is refused, although the link rule says a link `2` cites every
   `2.x`.
4. `## Requirement N:` with `### Acceptance Criteria` (one heading level higher than `### Requirement N` /
   `#### Acceptance Criteria`) gives no criteria.
5. The reference parser takes every number of the line: `ADR-0014.8` becomes `0014.8`, `Req 1 AC3` becomes `1` and `3`.

## What Changes

- **Finished history is not validated as work** (L4-KSP-006): a done leaf's missing or unresolvable `_Requirements:_`
  reference is a WARNING; a pending leaf keeps today's rule (ERROR under `sdd.enforce`).
- **A graph block that is not JSON is a warning**, and the tasks run in document order, as the reader already does; a
  JSON graph that is wrong (an unknown key, a cycle) stays an error.
- **A whole-requirement reference resolves** when the requirement has criteria.
- **Both heading levels are read**: `##`/`###` and `###`/`####` for a requirement and its acceptance criteria.
- **References are read as references only**: a number counts when it stands alone (start of the list, after a comma
  or whitespace, or after `Req`/`Requirement`), not inside a word such as `ADR-0014.8` or `AC3`.

## Impact

- `src/l4/specs/kiro.py` (validation, links, criteria headings), tests under `tests/unit/specs/`.
- `docs/SPEC.md` (L4-KSP-003 text, L4-KSP-006, scenarios, the change row), CHANGELOG (0.4.13).
