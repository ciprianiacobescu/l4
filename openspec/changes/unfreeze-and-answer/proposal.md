## Why

A live run with L4 0.4.1 on a consumer repository stopped twice where a person should not have been needed, and the
way out was a hand edit of a file.

1. **A task could not do what its own text said.** A task of the activated plan's spec said: add
   `os.environ.setdefault("APP_OTEL_ENABLED", "false")` beside an existing line in the root `conftest.py`, and add an
   autouse fixture. The red step wrote a test that asserts that default. The green step made exactly that edit. The
   guard logged `guard.violation path=conftest.py phase=green` and put the file back, because every tracked
   test-support file is frozen between red and green. The red test could never pass. After the green attempts, the
   harness raised a technical question: option 1 "unfreeze `conftest.py`", option 2 "drop the assertion".
   Option 1 could not work either: an answer never unfreezes a support file (`src/l4/implementer/unfreeze.py:122-124`).
   A probe on this branch confirmed both facts (design section 1.1). The `[test-infra]` task tag does not help: it
   lifts the test-path freeze, not the red-to-green freeze (design D1).
2. **`l4 questions` does not exist.** `l4 --help` lists "List, show, answer or accept questions of a unit", but the
   command exits 2 with `not yet implemented (M1: spec-providers 5.9)` (`src/l4/specs/questions.py:190-192`). The
   runbook (section 7.1) and the skill (`references/operate.md`) tell people and agents to edit `questions.md` by hand
   on the unit branch, then commit and push.

## What Changes

- **A task opens the support files that its own text names.** In the green step of a task, a frozen test-support file
  (for example the root `conftest.py`) that the task's text names exactly may change. The task text must come from a
  spec that a person reviewed: the digest that an active delivery plan froze at activation, or the same text on the
  base branch. The harness records `task.unfrozen{reason: "named_by_task"}`. These stay frozen: every red test of the
  task, every support file that the red step changed, ignore files, files that are not Python, symlinks, and every
  path the task does not name.
- **An opened file is checked.** It must keep every top-level statement of its red version. It must not rebind a name
  of that version, and it must not patch or assign the code that the unit changed. A file that breaks a rule is put
  back, and the retry note says why. The verifier lists each opened file and checks it again.
- **A person's answer can unfreeze a support file.** The rule of L4-IMP-002 extends from test files to test-support
  files, except ignore files. The note that the harness adds to a blocked green question says what an answer can
  unfreeze and what it cannot. It never offers an edit that the harness would refuse.
- **`l4 questions`** lists open questions (all units, or one with `--unit`) and shows one question.
  `l4 questions accept Q-NNN --unit U` and `l4 questions answer Q-NNN --unit U --text TEXT` edit `questions.md` on the
  unit branch with the harness's own parser and section-scoped edits. They make one commit that names the question
  and push it, and the push starts the run that resumes the unit. `--no-push` shows the change and writes nothing.
  Each refusal exits 2 with a `Fix:` line.
- **Agents.** The actor rule of `l4 yolo accept` applies. An agent may answer a question of a kind in
  `clarifier.auto_accept_kinds` whose answer names no frozen path. A product, ambiguous or verdict question, and an
  answer that would unfreeze a frozen path, need the new key `clarifier.answer_by_agents: true` in `.l4/config.yaml` on
  the base branch.
- **Docs.** `docs/SPEC.md` rows, the runbook (7.1, 10.4, 10.5, 11), the skill (`operate.md`, `spec.md`), the `l4
  --help` text and the green prompt template.

Not in this change:
- a change to the `[test-infra]` tag (design D1 says why);
- opening a support file that is not Python, a new support file, an ignore file or a runner-config section by task
  text;
- `l4 questions dismiss` (a hand edit still works);
- the AST rule "support files never replace the code under test" (§10.2 step 1) for every support change; this change
  builds it only for opened files;
- recording the actor of an answer in the ledger (the commit says it).

## Capabilities

### New Capabilities

- `freeze-named-paths`: the support files that a task's own reviewed text names open for that task's green, with the
  trust sources, the path rules and the checks of an opened file; a person's answer can unfreeze a support file; the
  harness note on a blocked green question is true (L4-IMP-014..016).
- `operator-questions`: `l4 questions` lists, shows, accepts and answers questions on the unit branch, with its
  refusals and its agent rule (L4-QMD-007..009). The runbook and the skill teach it (L4-OPS-017).

### Modified Capabilities

None as an OpenSpec delta: `openspec/specs/` holds no baseline (only `.gitkeep`). Section 6 of `tasks.md` holds the
`docs/SPEC.md` work:
- the new requirements L4-IMP-014..016, L4-QMD-007..009 and L4-OPS-017, with SCN-IMP-159..173, SCN-QMD-12..25 and
  SCN-OPS-27;
- the amendments of L4-IMP-002 (green), L4-IMP-006 (7), and of §2.1, §3.2, §10.2, §12.1 and §21.

SCN-IMP-155..158 are skipped: the unmerged local branch `dashboard-trial` uses them.

## Impact

- **Code:**
  - `src/l4/implementer/guards.py`, `unfreeze.py`, `tdd.py`, `loop.py`, `prompt.py`, `templates/green.md`, and a new
    `src/l4/implementer/opened.py` (the checks of an opened file);
  - `src/l4/specs/tasks_text.py` (new: the text block of a task), `src/l4/specs/questions.py` (`set_answer`, the
    command);
  - `src/l4/yolo/cycle.py` (`PlanStep.activated`), `src/l4/orchestrator.py` and `src/l4/implementer/workbench.py`
    (carry the activated digest);
  - `src/l4/verifier/integrity.py`, `src/l4/progress.py`;
  - `src/l4/config/schema.py` (`clarifier.answer_by_agents`), `src/l4/yolo/accept.py` (the actor rule moves to a shared
    module), `src/l4/cli.py`, `src/l4/commands.py`.
- **Docs:** `docs/SPEC.md`, `docs/runbook.md`, `plugins/l4/skills/l4/references/operate.md` and `spec.md`.
- **Config:** a new optional key, `clarifier.answer_by_agents` (default `false`). The schema is strict, so the order
  is: release, pin move, config edit.
- **Ledger:** `task.unfrozen` gains `reason` (`human_answer` or `named_by_task`), `source` and, for an open by task
  text, no `question`. An event without `reason` reads as `human_answer`.
