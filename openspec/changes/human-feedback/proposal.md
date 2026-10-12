## Why

A person who reviews a unit's merge request has no way to ask for changes. The harness reacts to three human inputs
only [V, code, 2026-10-12]:

- **Answers** to the questions it asked, in `questions.md`.
- **Accept or reject** on a verdict question: a reject with a reason becomes a finding and a fix unit (L4-VER-013).
- **A push to the unit branch after the hand-off.** A code commit sends the unit back to `verifying`, and an edit in the
  unit folder sends it back to `implementing` (L4-ARC-004, `state/review.py`).

Nothing turns review feedback into work. Feedback means things like "refactor this function", "this is duplicated" or
"this value is hard-coded and should come from an environment variable":

- **A comment on the PR or MR is never read.** The harness only writes its own sticky note.
- **A task added by hand to `tasks.md` misbehaves.**
  - A refactor goes through red and green. Red cannot fail when behaviour does not change, so the task is confirmed
    "already satisfied" and no code changes.
  - A `[chore]` tag written by a person does not skip red either. Only harness-made fix tasks run as chores
    (`implementer/loop.py:183`, `fixmark.chore_findings`).
- **Nothing checks the feedback was acted on.** The judge never sees earlier findings or human decisions
  (`verifier/judge.py:206`).
- **Kiro units have no fix units at all.** `decide_fix` escalates with "kiro has no fix units" (`fixloop.py:405`), so
  any failed round on a Kiro unit escalates. The live Kiro runs H2 and H3 passed in round 1 and never reached it.

The maintainer asked for this on 2026-10-12: keep the branch open, use a well-documented command that writes the right
file, and let commit and push trigger the change and a new check.

## What Changes

- **`feedback.md`**, a harness-format file in the unit folder, next to `questions.md`.
  - Each item is `FB-NNN`, with a kind, the code it points at, the person's text, and a status.
  - The kinds are `refactor`, `duplication`, `tests`, `config` and `behaviour`.
  - The person owns the text; the harness owns the index, its own status values and an *Outcome* block.
- **`l4 feedback`**: `add`, `list`, `show`, `submit` and `withdraw`.
  - It writes only `feedback.md`. It never commits, pushes or calls the forge.
  - It checks the item, quotes the code at `--at FILE:LINE`, and prints the exact `git` commands to send it.
  - It finds the unit from the checked-out `l4/…` branch.
  - Its `--help` and `docs/feedback.md` carry an example for every kind.
- **Taking the feedback.** At step 0 of the unit's next verification round, every submitted item becomes a
  deterministic blocking finding. The round fails at once and a fix unit is written, as for a red repository CI job
  (`ci_blockers`).
  - After the hand-off, a push of `feedback.md` already re-enters the unit (spec edit → `implementing`). No new
    lifecycle row is needed.
  - Before the hand-off, items wait for the end of the running round. The agent is never interrupted.
- **One fix task per item, by kind:**
  - `refactor` and `duplication`: a harness chore. It has no red step, and every test file is frozen, so the existing
    tests prove the behaviour did not change.
  - `tests`: the existing test chore.
  - `config` and `behaviour`: red and green, against a new criterion.
    - `behaviour` takes the criterion from the person's `--when` and `--then`.
    - `config` builds it from `--env NAME` ("WHEN NAME is set …", "WHEN NAME is not set … CONTINUE TO …").
- **The judge checks every taken item.** Its reply gains `feedback: [{id, addressed, evidence}]`.
  - An item that is not addressed becomes a finding for the next round.
  - For a `config` item, the deterministic check also requires the variable's name in a changed non-test file.
  - An addressed item gets status `addressed`, with the round and the commit.
- **Feedback rounds have their own limit.** They do not use up `verifier.max_fix_rounds`, which stops agent failures
  from looping. The new setting is `feedback.max_rounds`, default 5.
- **Kiro fix units, as Kiro bugfix specs** (L4-KSP-005, never built until now): `bugfix.md` in Kiro's template,
  `design.md`, `tasks.md`, `.config.kiro` and the fix marker. This fixes any failed Kiro round, not only feedback.
- **`--lesson`.** An addressed item marked as a lesson becomes a lesson for future units, such as "no hard-coded
  endpoints".
- **After the merge.** `l4 feedback add` on a merged unit writes to its folder on the base branch. The next base run
  creates a follow-up unit `<name>-followup-<n>`, which runs and is judged like any unit.
- **Visibility.** The sticky note gains a *Your feedback* section with the state of each item. Every note of a unit in
  review ends with a one-line hint on how to ask for changes. `verification.md` and `l4 status` show the items too.
- **Protection.** Agents may not edit `feedback.md` (denylist and post-step guard). A base merge resolves the file by
  item.

**Not in this change:**
- Reading PR or MR comments, for example `/l4 feedback …` comments. Files come first: they are auditable, the same on
  both forges, and kept in history. Comments are a later layer that would write the same file.
- `l4 questions` stays a stub (spec-providers 5.9).
- The direct `in_review → fixing` row of L4-QMD-006.

## Capabilities

### New Capabilities

- `human-feedback`: `feedback.md` and `l4 feedback`; taking items into fix units by kind; the judge's check of every
  item; the feedback round limit; lessons from feedback; follow-up units after the merge; Kiro fix units as bugfix
  specs.

### Modified Capabilities

None as an OpenSpec delta. design.md lists the SPEC lines this change amends: §2.1, §3.2, §6, L4-IMP-004 (denylist),
L4-VER-006 and L4-VER-007, §10.3 (judge schema), L4-KSP-005, L4-MEM-002, L4-ARC-002 (sticky note), §12.1 (events) and
§21 (delivery row 17).

## Impact

- **Code:**
  - `src/l4/specs/feedback.py`, new: parse, write, take, and the command.
  - `src/l4/specs/harness_merge.py`: the resolver.
  - `src/l4/specs/kiro.py`: `create_fix_unit` and the bugfix criteria.
  - `src/l4/specs/fixmark.py` and `openspec.py`: refactor chores, feedback marker fields.
  - `src/l4/verifier/`: `preconditions.py` (step 0), `fixunit.py` (by kind), `fixloop.py` (round count, Kiro),
    `judge.py` (data block, schema, `PROMPT_VERSION` 7), `ladder.py`, `report.py` and `notes.py`.
  - `src/l4/implementer/`: `tdd.py` (the refactor freeze) and the guard.
  - `src/l4/state/fold.py` and `budget.py`.
  - `src/l4/memory/curate.py`, plus `planner.py` and `orchestrator.py` (follow-up).
  - `src/l4/archive.py`: the sticky note section and the hint.
  - `src/l4/commands.py`, `cli.py` and `config/schema.py`.
- **Docs:** `docs/SPEC.md`, `docs/feedback.md` (new: the how-to), `docs/quickstart.md` §5.
- **Live:** a Kiro unit on a dummy repository. Its PR is ready, then one `refactor` item and one `config` item are sent.
  Both are addressed in a later round, the PR goes back to ready, and a person merges.
