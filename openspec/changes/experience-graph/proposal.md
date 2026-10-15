## Why

L4 records what happens to every unit, but nobody can read it across units. The facts are committed per unit:
ledgers (`.l4/ledger/<run-id>.jsonl`), the per-round `verdict.json`, the stop causes of 0.3.0 (`halt_reason`,
`halt_detail`), and the injected lessons (`lessons.injected`, `prompt.rendered{task, lessons}`). Today:

- **Nothing reads `lessons.injected`** [V: the only writer is `memory/inject.py:105`; no reader exists]. Nobody can see
  whether a lesson helped.
- **The same mistakes repeat across units and nobody counts them.** The red and green attempt failures
  (`task.attempt_failed{task, phase, reason}`, `implementer/loop.py:233`) are the implementer's most expensive
  errors, and they are recorded only per unit. `same_failure` (L4-OPS-007) compares two rounds of one unit only.
- **Lessons have one automatic source that fires.** `LESSON_RULES` has one rule (`memory/curate.py:65`). The
  documented human path, `l4 lessons promote ID` (SPEC 2.1 row, L4-MEM-002), is not built: `memory/cli.py` has only
  `list` and `lint`, and memory-lessons tasks 3.6–3.8 are open.
- **A person who must choose between `l4 retry` and `l4 restart`** reads ledgers by hand. The old attempts of a
  restarted unit exist only under `refs/l4/attempts/` (L4-OPS-004).

A proposal for an "experience graph" was written on 2026-10-14 (`docs/plan/proposal-experience-graph.md` in the main
checkout, not committed). An adversarial review of its usage on the same day found these defects. Each one was
checked in code, and each one is fixed here:

- **Wrong join.** The lesson `Source` line is `verifier round N`, with no finding id and no unit (`curate.py:111`,
  live: `docs/live/m15/s2-lessons-md-on-branch.md`). A lesson cannot be joined to a finding through it.
- **Recurrence by id cannot work.** Finding ids hash the title and the criterion id (`verifier/types.py:32`). A Kiro
  criterion id includes the unit folder (`specs/criteria.py:228`). The same mistake in two units has two ids.
- **Wrong storage.** A repo-local `.l4-cache/` was rejected by L4-CFG-005 (SPEC 427–431). `l4 init` ignores only
  `.l4-out/` (`init/init.py:57`).
- **Units are missed.** `list_units` skips `changes/archive/` (`specs/openspec.py:180`), and a restart keeps the old
  attempt only as a ref (`state/restart.py` step 2).
- **The automatic loops could not be measured, and they would put model text in front of agents.** Eval cells force
  `memory.enabled: False` (`eval/cellconfig.py:103`). The planned `spec-gaps.md` view would carry judge text into a
  harness-owned memory file. Also, the planned dead-scope skip (L1) adds nothing: `select_lessons` already selects a
  scoped lesson only when a task path matches it (`memory/lessons.py:222`, `implementer/tdd.py:529`).
- **The data is small.** `docs/live` holds 32 distinct units and one lesson id (`L-09421538`). Nearly every OpenSpec
  capability has one unit. Every number must show its *n*.

The maintainer asked for a manual-only phase 1 that is usable, cannot break existing functionality, and tells how the
implementer benefits.

## What Changes

- **`l4 kg build`: a derived, disposable index.**
  - It is read from committed git objects only: the base branch (open units and the OpenSpec archive), the unit
    branches, the pending ledgers in the lock refs, and the local `refs/l4/attempts/**`.
  - It is written under the harness cache root (`$L4_CACHE/kg/<repo key>/`), never in the repository.
  - A rebuild from the same ref shas gives the same bytes.
  - It never fetches.
- **`l4 kg report [--out PATH] [--min-units N]`: a markdown report for a person, with *n* on every line.**
  - Coverage: what was read, what was skipped and why, and the attempts that are not local.
  - Lesson outcomes: per lesson, its injections and the attempt failures and matching findings that came after them
    in the same unit. This is a heuristic, and the report says so.
  - Recurring red and green attempt-failure classes, and recurring findings across units. Both are matched by
    normalised text and labelled approximate.
  - Gate candidates.
  - Spec-gap hotspots by capability.
  - Profile outcomes by role.
  - Stops by cause.
- **`l4 kg why ID`.**
  - For a unit: a timeline of its attempts, runs, rounds, stops, retries and restarts. It helps a person choose
    `l4 retry` or `l4 restart`.
  - For a finding, a lesson, a question or a run: its 1-hop neighbourhood. Each line points to the committed source.
- **`l4 kg propose`: draft lesson proposals for a person.** The drafts go into
  `.serena/memories/inbox/kg-<date>/`, the inbox that L4-MEM-002 names. They contain only harness-owned strings and a
  `TODO(person)` line that a person must replace. The command never writes `lessons.md`.
- **`l4 lessons promote ID` is built, as L4-MEM-002 designs it.**
  - A person promotes one inbox proposal.
  - The harness writes `lessons.md` with its canonical writer (origin `human_edit`).
  - One separate commit `chore(memory): lesson <id> promoted [skip ci]` (L4-MEM-005) records it.
  - From then on, the existing scoped injection (L4-MEM-003) gives the lesson to the implementer on matching tasks.
- **Nothing reaches an agent automatically.**
  - No run path imports `l4.kg`.
  - No prompt, gate, verdict, config key or doctor check changes.
  - No model is called and no network is used.
  - Every `l4 kg` failure stays inside the command.

## Capabilities

### New Capabilities

- `experience-graph`: a manual, derived index over committed harness records. It gives a report, a per-unit timeline,
  and draft lesson proposals that a person promotes (L4-KG-001..014).

### Modified Capabilities

- `memory-lessons`: `l4 lessons promote ID` is built as L4-MEM-002 already describes it (memory-lessons task 3.8),
  for inbox proposals that a person reviews. Agent `lesson_proposals` (task 3.6) stay unbuilt. Lesson selection and
  injection (L4-MEM-003) do not change.

## Impact

- **Code:**
  - `src/l4/kg/` (new): `model.py`, `store.py`, `sources.py`, `extract.py`, `normalise.py`, `blame.py`, `report.py`,
    `why.py`, `propose.py`, `cli.py`;
  - `src/l4/memory/inbox.py` and `src/l4/memory/promote.py` (new);
  - `src/l4/memory/cli.py` (`promote`);
  - `src/l4/commands.py` and `src/l4/cli.py` (four `kg` rows, the `kg` group, the `promote` options).
- **Tests:**
  - new `tests/unit/kg/` and `tests/unit/memory/test_promote.py`;
  - a boundary test that no run-path module loads `l4.kg`;
  - the command tables of `tests/unit/cli/test_dispatch.py` get rows only.
- **Ledger, lifecycle, config, CI templates, prompts, doctor:** no change.
- **Docs:**
  - SPEC: §2.1 rows, a new §13.1 with L4-KG-001..014, SCN-KG-01..30, and delivery row 20;
  - `docs/runbook.md` (a section "Reading the history");
  - the README feature state.
- **Compatibility:** with no `l4 kg` command run, nothing changes. `l4 lessons list|lint` keep their behaviour.
