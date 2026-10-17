## Why

A Kiro spec reaches the implementer only in part, and when a source is too big, nothing says so. This was checked by
rendering real prompts of a probe repository with `l4 run --dry-run` (harness 0.4.14). The probe is a Kiro spec
`.kiro/specs/tip-calc/` with `requirements.md` (two EARS criteria), a `design.md` of 125,492 characters, `tasks.md` (one
leaf with two detail bullets and `_Requirements: 1.1, 1.2_`), and `.kiro/steering/tech.md`, each with a marker string.

- **The criteria text can disappear.** `collect_sources` (`src/l4/implementer/prompt.py`) gives the prompt `proposal.md`,
  `design.md`, `requirements.md`, `bugfix.md` and `specs/*/spec.md` in that order. They share one budget,
  `implementer.context_budget_tokens` (24000) × 4 characters (`_context`). With the long design, `requirements.md` was
  replaced by `[truncated: omitted to fit the context budget]`. The section "Criteria of this unit" lists only ids and
  aliases (`C-1a9abc58  Req 1.1`), never the criterion's text. So the implementer had no acceptance-criterion text at
  all. With the short design, `requirements.md` was there.
- **A task is its title line.** `Task.title` is the checkbox text and `Task.links` comes from `_links_below`
  (`src/l4/specs/kiro.py`). The leaf's detail bullets ("reject a percent above 100 with ValueError as well", "Use
  Decimal throughout") are not in the prompt, and `tasks.md` is not a source.
- **Steering never arrives.** `.kiro/steering/*.md` is not a prompt source. The bwrap sandbox masks it with a tmpfs
  (`GUIDANCE_DIRS`, `src/l4/sandbox/base.py`, kept on purpose), and the kiro-cli adapter runs a harness agent with no
  `resources`. So the project's conventions never reach the agent.
- **A source over 262,144 bytes is skipped without a word** (`read_regular_file(limit=MAX_SOURCE_BYTES)` raises
  `UnsafeFile`, and `collect_sources` drops the file). This hits the implementer and the step-9 judge alike.
- **Red does not require a Kiro task's own criteria** (review finding `implementer-5`, confirmed). `check_criteria`
  takes no task, so a red step that tests only `Req 1.1` of a leaf citing `1.1, 1.2` passes. The no-new-test
  already-satisfied path ticks such a task without proving `Req 1.2`. This breaks the rule of L4-IMP-005's own schema:
  `criteria_ids` "must include the task's cited criteria (Kiro)".

The verifier was checked too (design.md §1.4). The step-9 judge already gets `requirements.md`, `bugfix.md` and every
criterion's full text, with no budget, so a long design does not push the criteria out of its prompt. The S1 state
carries the criterion's text whole. Both lose an oversized file without saying so.

## What Changes

- **Criteria and task are never cut** (L4-IMP-050). The Criteria section carries each criterion's id, alias and full
  text. The Task section carries the task's whole block from `tasks.md`: the enclosing headings, the parent tasks' lines,
  the checkbox line and every line under it (detail bullets, `_Requirements:_`). Both are charged to the budget first and
  are never cut.
- **The budget fills in priority order** (L4-IMP-051). The project conventions come first, at most half the budget: a
  Kiro unit's applicable steering, or an OpenSpec unit's `context` from `openspec/config.yaml`. Then the requirements
  narrative, then the sections of `design.md` that the task names (with the design's preamble), then the rest of the
  design and `proposal.md`. A source is cut by whole sections, and a gap is marked where it stands.
- **A cut is named, never silent** (L4-IMP-052). The prompt gets a `# Not shown in full` section that lists each cut or
  unread file by its repository path, with the characters shown and the total, the lines left out and the reason
  (`budget`, `oversize`, `symlink`, `not_regular`). The contract tells the agent to open a readable file with its tools.
  The run records `prompt.truncated`. A source over 262,144 bytes is read up to that size and named, not skipped.
- **The budget** (L4-IMP-053). `implementer.context_budget_tokens` rises from 24000 to 32000 (owner decision 8) and stays the way a consumer raises it. A
  profile can set its own `context_budget_tokens`, for a small local model in a fallback chain. No model window is read,
  because no profile declares one before a run. `prompt.rendered` records `budget_tokens` and `budget_source`.
- **A person sees the cuts** (L4-IMP-054). `l4 run --dry-run` prints per unit the budget, the steering decisions and each
  cut. `l4 status --unit` prints the last `prompt.truncated`. Doctor SPEC-004 warns when the next task's prompt of a
  unit would cut a source.
- **Steering as data** (L4-KSP-010, L4-KSP-011). Each `.kiro/steering/*.md` is read by the harness on the host, before
  the sandbox starts. It is injected as a `<l4:data>` block under `# Project conventions` according to its Kiro front
  matter:
  - no front matter, or `always`: included;
  - `fileMatch`: included when a pattern matches a path of the task;
  - `manual` and `auto`: included when the task block, `requirements.md` or `design.md` references the file.

  Every decision is recorded in `prompt.rendered.steering`. A cut steering file is named as not readable in the
  sandbox. The sandbox masks stay.
- **Red enforces a Kiro leaf's cited criteria** (L4-KSP-012, L4-KSP-013, implementer-5). Every criterion that the leaf's
  `_Requirements:_` line names must be traced by a new test of the red step, or the step fails with a reason that the
  next attempt reads. The no-new-test already-satisfied path must confirm passing, discriminating tests for every one of
  them.
- **The judges** (L4-KSP-014; owner decisions 2 and 7). The step-9 judge gets its spec text within
  `verifier.judge_context_budget_tokens` (48000) in the implementer's priority order, each spec file whole or named as
  cut, and each done task's whole block, which it checks against the diff. An oversized, unread or budget-cut
  requirements file is a hold, like a truncated diff. The S1 state keeps the criterion text whole. Step 1's scope reads
  a Kiro unit's `requirements.md` and `bugfix.md`.
- **Owner decisions of 2026-10-18** (design §7): `auto` steering is included last when the budget has room; the root
  `AGENTS.md` joins with `implementer.include_agents_md`; a criterion an earlier red proved needs no copy in a red step;
  the clarifier uses the same builder; the default budget is 32000.
- MODIFIED: L4-IMP-004 (prompt sections), L4-IMP-003 (the cited set of a Kiro leaf), L4-KSP-003 (what the links bind).
- Templates: `contract@12` (conventions and cut files), `red@11` (every listed criterion of a linked leaf needs a new
  test or an earlier proof), `judge@10` (cut spec files, the done-tasks rule), `clarifier@5`.

## Impact

- New: `src/l4/implementer/unit_context.py` (read, rank, cut), `src/l4/specs/steering.py` (front matter, decisions,
  OpenSpec `context`).
- Changed:
  - `src/l4/implementer/prompt.py`: `PromptContext`, `render_prompt`, `_criteria_section`; `_linked` moves to
    `l4.specs.criteria.linked_criteria`.
  - `src/l4/implementer/tdd.py`: `_prompt`, `run_red`.
  - `src/l4/implementer/result.py`: `check_criteria(required=...)`.
  - `src/l4/sim/dryrun.py`.
  - `src/l4/state/status.py`.
  - `src/l4/doctor/checks_spec.py`.
  - `src/l4/verifier/ladder.py`: `_family_sources`, `_judge_step`.
  - `src/l4/verifier/judge.py`: `build_judge_prompt`, `SYSTEM`, `PROMPT_VERSION`.
  - `src/l4/config/schema.py`: `Profile.context_budget_tokens`.
  - The templates `contract.md` and `red.md`, and `src/l4/templates.lock.json`.
- Unchanged on purpose:
  - the sandbox masks (`GUIDANCE_DIRS`) and the protected paths;
  - the kiro-cli agent definition;
  - `CLAUDE.md` and nested `AGENTS.md` files, which no adapter loads and the prompt does not carry (the root
    `AGENTS.md` only with the opt-in);
  - `collect_sources` for the audit writer (the clarifier now uses `read_sources` and the shared planner).
- Tests: new `tests/unit/implementer/test_prompt_context.py`, `tests/unit/specs/test_steering.py`,
  `tests/unit/implementer/test_red_cited_criteria.py`, `tests/unit/verifier/test_judge_sources.py`. Updated: the tests
  that pin `contract@11`, `red@10` or `judge@9`, the K20 tests in `test_prompt.py`, the dry-run tests.
- Docs:
  - `docs/SPEC.md`: L4-IMP-050..054, L4-KSP-010..014 and the three MODIFIED requirements; SCN-IMP-280..299; §3.2;
    §8.3; §12.1; §15 SPEC-004; §18; change-table row 40.
  - `CHANGELOG.md` under `## 0.4.16 (unreleased)`.
  - The skill's `references/spec.md`, `docs/quickstart.md` (Kiro) and `docs/runbook.md`.
