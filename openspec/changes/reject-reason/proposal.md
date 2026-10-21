## Why

A consumer's Kiro unit ended round 1 NEEDS_HUMAN on 2026-10-20 with two questions about the same behaviour: a criterion
question ("Criterion C-… (Req N.M): accept as satisfied?", the scenario says a command given an unknown id exits 1)
and a judge-only major spec-gap finding ("… exits 2, not 1"). The judge's suggested fix for that finding read `WHEN
<the command> is given an id with no record THEN the command exits 2 with a usage error …`. A person rejected both with
a reason that said the requirement asks for exit 1 and the code turns the lookup error into a usage error (exit 2). The worry: does the fix
unit follow the person or the judge?

What the code does today (release 0.4.20, da3e7c28; reproduced with `plan_fix_unit` and the Kiro `bugfix.md` writer):

- The person's answer of that day ended with their own `WHEN … THEN … exits 1`, so `fixunit.py:177` took it, and the
  fix unit would have pinned exit 1. That case is safe. (No fix unit was written that day: the round stopped at the
  deadline, so the evidence is the code and the reproduction, not a consumer file.)
- **Without the person's `WHEN … THEN …` the fix unit contradicts itself.** `src/l4/verifier/fixunit.py:176-179` takes
  the scenario from the person's reason, else, for a spec gap, from the judge's `suggested_fix`. The judge prompt
  (`src/l4/verifier/judge.py:183-185`) makes that suggestion "the behaviour the committed code shows", so it is the
  behaviour the person called wrong. The Kiro fix unit then lists under "Expected Behavior (Correct)" both `2.1` (the
  restated criterion: exits 1) and `2.2` (the judge's suggestion: exits 2), and the task cites both. The red step must
  write a test for each listed criterion (`red.md`), and a test of `2.2` passes at once. The green step must make `2.1`
  true, which breaks `2.2`. The task cannot pass both, and an archived fix would add "exits 2" to the specs. The OpenSpec
  fix unit gets the same scenario as an ADDED `— regression 1` requirement. A bare `reject` (no reason) does the same.
- **A criterion's reject can vanish.** `fixunit.py:176` reads `rejects.get(f.id) or rejects.get(criterion)`: when the
  finding has its own reject, the criterion's reject is consumed (`:217-219`) but its reason never reaches the task's
  decisions (`:207-211`), and its `WHEN … THEN …` never becomes a scenario. A person who put the scenario in the
  criterion answer and a short reason in the finding answer gets the judge's suggestion pinned and their scenario dropped.
- The person's reason already comes first in the fix unit: `Decided by human in Q-NNN: <reason>.` opens the task's text
  in `proposal.md`, `bugfix.md` and `design.md` (`fixunit.py:101-110`, L4-VER-006). That part works.
- The questions do not say what a reject without a scenario does. The finding question says only "`reject` and say why:
  a rejected finding is fixed by a fix unit" (`verdicts.py:555`); the criterion question offers `WHEN … THEN …` only "if
  the code is right and the scenarios are incomplete" (`verdicts.py:533`). Neither says that the suggested fix describes
  the code as it is now.

## What Changes

- **A person's reject decides the fix task's check** (L4-VER-059). A fix task's scenarios come only from the `WHEN …
  THEN …` of the rejects it consumes (the finding's, then its criterion's, each text once). The judge's `suggested_fix`
  is a scenario only for a spec gap that no person rejected (a minor on a PASS with `verifier.fix_minor_findings`, as
  today). A rejected finding without a person's scenario cites its criterion and adds no regression requirement, so the
  fix is checked against the criterion's own scenarios; without a criterion it is not converted ("answer again with a
  scenario"), as a rejected finding with no criterion is today. Every reject a task consumes is quoted in its decisions.
- **A bare `reject` of a spec gap is refused at answer time** (L4-VER-060). `l4 questions answer` exits 2 on a `reject`
  with no reason on the question of a spec-gap finding, naming what to add; a reason alone is accepted. A bare reject
  that reached the file by hand is not converted by the planner (L4-VER-059).
- **A reason's scenario is its last `WHEN … THEN …`**, so a reason may quote the criterion's and then give its own.
- **The questions say how to set the check** (L4-VER-060). The criterion and finding questions tell the person to end
  the reason with `WHEN … THEN …` to set the check the fix must pass, say what happens without one, and, for a spec gap,
  that the suggested fix describes the code as it is now and that a reject does not use it (only when the suggested fix
  is a `WHEN … THEN …` sentence).
- **Docs**: SPEC (L4-VER-059, L4-VER-060, SCN-VER-205 to SCN-VER-216, the L4-VER-006 sentence on spec gaps, the Given
  of SCN-VER-18, a change-table row), the runbook's verdict answers, the skill's verdict questions, and CHANGELOG `##
  0.4.21 (unreleased)`.

## Impact

- Code: `src/l4/verifier/fixunit.py` (`_candidates`: the verdicts of a finding, the scenarios from them only, every
  consumed reject in the decisions, a bare reject of a spec gap not converted; the module docstring),
  `src/l4/verifier/verdicts.py` (`_finding_question`, `_criterion_question`, `WHEN_THEN` matches the last scenario),
  `src/l4/specs/questions_cli.py` (`check_question`: the refusal of a bare reject of a spec gap).
- Behaviour change: a rejected spec-gap finding whose criterion the unit does not have, answered without a `WHEN …
  THEN …`, is no longer turned into a task from the judge's suggestion; it is listed as not converted, and when no other
  finding converts, the unit escalates with `no finding of this round can be converted into a fix task` (the runbook's
  way out applies). A rejected spec gap with a criterion and no person's scenario is now checked against that criterion
  (no ADDED requirement) instead of the judge's suggestion. A bare `reject` of a spec-gap finding's question is refused
  by `l4 questions answer` (exit 2) with the sentence to add; a reason alone is accepted, and the red step then writes a
  failing test for that reason.
- No configuration key, no ledger event, no prompt template version, no fix-unit file format change. The fix units that
  already exist are not rewritten.
- Tests that change: none of the existing assertions (every existing test that pins a judge suggestion runs without a
  person's reject; every ladder test that rejects a spec gap answers with a `WHEN … THEN …`). A throwaway prototype of
  both code changes, reverted, passed the 278 tests of the verifier, fix-unit writer and question files unchanged.
- Spec: L4-VER-059, L4-VER-060, SCN-VER-205 to SCN-VER-216, one change-table row.
