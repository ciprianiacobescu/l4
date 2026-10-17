## Purpose

The project's Kiro steering reaches the implementer as data, as Kiro's own inclusion rules choose it, inside the
context budget, while the sandbox keeps the CLI from loading it as instructions; every decision is on record.

## ADDED Requirements

### Requirement: L4-KSP-010 Applicable steering reaches the implementer as data
Each `.kiro/steering/*.md` that applies SHALL reach the implementer's prompt as a `<l4:data>` block under `# Project
conventions`, read by the harness on the host; the sandbox masks of `.kiro/steering` SHALL stay. By its front matter a
file applies when it has none or `always`; `fileMatch` and a pattern matches a path of the task; `manual` and the task
block, `requirements.md`, `bugfix.md` or `design.md` references it; `auto`, last, when the budget has room.

#### Scenario: SCN-IMP-290 (+) A steering file without front matter is always included, as data
- **GIVEN** the probe's `.kiro/steering/tech.md`, which has no front matter and the line `STEERING-MARKER: all money
  values are Decimal, never float; round half up to 2 places.`
- **WHEN** a run renders the red prompt of task 1 and builds the step's bwrap sandbox
- **THEN** `# Project conventions` holds `<l4:data source=".kiro/steering/tech.md">` with that line, and
  `prompt.rendered.steering` is `[{path: ".kiro/steering/tech.md", inclusion: always, included: true, why: always}]`
- **AND** the sandbox still covers `.kiro/steering` with a tmpfs, and nothing under `~/.kiro/steering` is read

#### Scenario: SCN-IMP-291 (+) A fileMatch steering file applies to the task's paths only
- **GIVEN** `.kiro/steering/calc.md` with the front matter `inclusion: fileMatch` and `fileMatchPattern:
  ["src/calc/**"]`
- **WHEN** the prompt of a task whose block names `src/calc/tip.py` is rendered, and then the prompt of a task whose
  block names only `docs/usage.md`, on a unit branch that has changed no file
- **THEN** the first prompt holds `calc.md`, recorded with `why: "matched src/calc/tip.py"`
- **AND** the second does not, and its `steering` lists `calc.md` with `included: false, why: no_match`; once the
  branch has changed `src/calc/tip.py`, the second task's prompt holds it too

#### Scenario: SCN-IMP-292 (−) Manual steering needs a reference, auto steering comes last, bad front matter is left out
- **GIVEN** `money.md` with `inclusion: manual`, `api.md` with `inclusion: auto`, `name: api-design` and
  `description: REST conventions`, and `bad.md` whose front matter is not YAML
- **WHEN** the prompt of a task whose block says `follow #money for amounts` is rendered
- **THEN** `money.md` is included with `why: referenced`, `bad.md` is not (`bad_front_matter`), and all three are
  listed in `prompt.rendered.steering`
- **AND** `api.md` is included after `money.md` with `why: auto`, and a task whose block says `see #api-design` gets it
  with `why: referenced`

### Requirement: L4-KSP-011 Every steering decision is recorded, and a cut steering file is named unreadable
`prompt.rendered.steering` SHALL list every steering file with its inclusion, whether it was included, and why
(`always`, `matched <path>`, `referenced`, `no_match`, `not_referenced`, `bad_front_matter`, `bad_name`, `symlink`). A steering
file cut by the budget SHALL be named under `# Not shown in full` as not readable in the step's sandbox, never with an
instruction to open it, and with `readable: false` in `prompt.truncated`.

#### Scenario: SCN-IMP-293 (−) A long steering file is cut at half the budget and named unreadable
- **GIVEN** the probe unit with an extra `.kiro/steering/style.md` of 70,000 characters and no front matter, and the
  budget of 24000 tokens (`implementer.context_budget_tokens: 24000`)
- **WHEN** the red prompt of task 1 is rendered
- **THEN** the `style.md` block holds at most 48,000 characters, `requirements.md` is still whole, and `# Not shown in
  full` lists `.kiro/steering/style.md: <shown> of 70000 characters shown (budget); not readable in this step's
  sandbox`, with no instruction to open it
- **AND** `prompt.truncated` lists it with `kind: steering, readable: false`
