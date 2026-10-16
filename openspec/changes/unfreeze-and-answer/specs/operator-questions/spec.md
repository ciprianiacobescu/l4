## Purpose

A person, or an agent that the project allows, lists, reads, accepts and answers the harness's questions with one L4
command. The command edits `questions.md` on the unit branch with the harness's own parser, commits and pushes, and the
push resumes the unit. Nobody has to edit the file by hand.

## ADDED Requirements

### Requirement: L4-QMD-007 `l4 questions` lists and shows questions from the unit branch
`l4 questions [--unit U] [--json]` (and its alias `l4 questions list`) SHALL list every question whose Status is
`open`, one line per question: unit, id, kind, blocking tasks and title. An open question with a non-empty answer SHALL
show `draft` in place of its kind. A section that the parser cannot read SHALL give one warning line.

With `--unit`, it SHALL read the unit and its fix units. With a fix unit's id, it SHALL read that fix unit only. With
no `--unit`, it SHALL read every unit that has a branch on `origin`.

`l4 questions show Q-NNN --unit U [--json]` SHALL print:
- the question's section as the file has it;
- what `accept` would take, or that there is no clarifier suggestion;
- each frozen path of a task that the question holds which the suggestion names, and whether an accepted suggestion
  would unfreeze it (L4-IMP-015);
- whether the caller may write the answer (L4-QMD-009);
- `Next:` lines with the exact commands.

Both forms SHALL fetch the base branch and the unit refs first. They SHALL read `questions.md` at the fetched unit
branch head, never in the local checkout, and to at most 2 MiB. A tree entry that is a symlink MUST NOT be read.
When the fetch fails, both forms SHALL read the refs that exist and print a warning. Both forms MUST write nothing and
exit 0 unless the unit or the question does not exist.

#### Scenario: SCN-QMD-12 (+) The open questions of every unit
- **GIVEN** unit A with Q-002 `open` (product, blocking 3.1) and Q-001 `answered` on its branch on `origin`, and unit B with Q-001 `open` with a draft answer, and a local checkout of the base branch that has no `questions.md`
- **WHEN** `l4 questions` runs
- **THEN** it prints `A Q-002 product 3.1 <title>` and `B Q-001 draft <tasks> <title>`, no line for A's Q-001, and `Next: l4 questions show Q-002 --unit A`, and exits 0

#### Scenario: SCN-QMD-13 (+) Show says what an accept would unfreeze
- **GIVEN** Q-003, technical, holding task 2.1, whose clarifier suggestion is "Edit `conftest.py`: add the line", and the latest `task.red_ok` of 2.1 that lists `conftest.py` as frozen
- **WHEN** `l4 questions show Q-003 --unit A` runs
- **THEN** it prints the section, `accept takes: Edit conftest.py: add the line`, `an accepted suggestion unfreezes conftest.py for the next green of 2.1`, and `Next: l4 questions accept Q-003 --unit A`

#### Scenario: SCN-QMD-14 (+) A fix unit's question is listed under its parent
- **GIVEN** unit A in `fixing`, and its fix unit `A-fix-1` with Q-001 `open` in `<A folder>-fix-1/questions.md` on A's branch
- **WHEN** `l4 questions --unit A` runs
- **THEN** it lists `A-fix-1 Q-001 …`, and `l4 questions show Q-001 --unit <fw>:A-fix-1` shows it

### Requirement: L4-QMD-008 `l4 questions accept` and `answer` write on the unit branch and push
`l4 questions accept Q-NNN --unit U [--no-push]` SHALL set the Status of an open question to `accepted`.
`l4 questions answer Q-NNN --unit U --text TEXT [--no-push]` SHALL write TEXT as the question's answer and set its
Status to `answered`. `--text -` reads standard input.

Each form SHALL work on the fetched head of the branch that holds the unit's folder. That is the unit's own branch, or
the parent's branch for a fix unit. Each form SHALL change only these spans of `questions.md`:
- the question's Status value;
- for `answer`, the body of its `### Answer` block (the comment line `<!-- write below this line -->` is kept, and a
  missing block is added at the end of the section);
- the question's index row.

Every other byte, the line endings and the BOM MUST stay. After the edit the file MUST parse back with these results,
or the command refuses:
- the new Status;
- for `answer`, an answer text equal to TEXT, stripped;
- every other question with the same id, Status, blocking tasks and effective answer;
- no new parse issue.

The command SHALL make one commit with the operator's own git identity, without a checkout. The subject is
`answer Q-NNN (<unit name>): <title>` or `accept Q-NNN (<unit name>): <title>`. The body names the Status, the actor
and `Via: l4 questions`. The message MUST NOT carry an `L4-` trailer, and MUST carry a `[skip ci]` line: a push to a
unit branch runs that branch's own copy of the workflow, which can pin an older harness than the base's (its pin guard
then does no work, CFG-008), and it would start the repository's own CI on a unit that is in the middle of TDD. The
command SHALL push the commit to the branch without force, and SHALL write no ledger event. After a successful push it
SHALL start a run on the base branch exactly as `l4 retry` does (L4-OPS-002; `start_run_line`): `run started on <base>`,
`a run is already queued on <base>`, or `start a run with: <the exact command or page>` with exit 0 when the forge refuses
or no token is set. `--no-run` skips the start. The next run records `question.answered` as it does for a hand edit.

`--no-push` SHALL print the diff of `questions.md` and the commit message, and write, commit and push nothing, and start
no run.

The command MUST refuse with exit 2, change nothing, and print `questions: <cause>` and a `Fix:` line in each of these
cases:
- an unknown unit, or a unit without a branch on `origin`;
- no `questions.md`, or an unknown or unreadable question id;
- a question that is not `open` (a superseded question names its successor);
- an open question with a draft answer;
- a finished unit (`merged`, `archived`, `abandoned`), or a run that is working on the unit now;
- `accept` with no clarifier suggestion;
- `accept` on a verdict question;
- a verdict answer that does not start with `accept` or `reject`;
- a text that is empty, too long, has a line that the file would read as structure, holds an HTML comment, or holds a
  value that the redactor changes;
- the agent rule (L4-QMD-009);
- a branch that moved since the fetch (`run the command again: it fetches first`);
- a `questions.md` that is a symlink or larger than 2 MiB.

#### Scenario: SCN-QMD-15 (+) An answer is committed, pushed and read by the next run
- **GIVEN** unit A `awaiting_human` with Q-002 `open`, blocking 3.1, on branch `l4/openspec/a`
- **WHEN** a person runs `l4 questions answer Q-002 --unit openspec:a --text "Block login until the address is verified."`
- **THEN** one commit `answer Q-002 (a): <title>` by the person is pushed to `l4/openspec/a`, without force, without `L4-Run:` and with a `[skip ci]` line; the diff touches only Q-002's Status line, its Answer body and its index row; the command then starts a run on the base branch (as `l4 retry` does; `--no-run` skips it); and that run records `question.answered{id: "Q-002", by: human}` and gives the answer to the prompt of 3.1

#### Scenario: SCN-QMD-16 (+) Accept takes the clarifier suggestion
- **GIVEN** Q-003 `open` with a clarifier suggestion
- **WHEN** `l4 questions accept Q-003 --unit A` runs
- **THEN** the pushed file has `- **Status:** accepted` in Q-003's section and its index row, the Answer block is unchanged, and the effective answer is the suggestion

#### Scenario: SCN-QMD-17 (+) A dry run writes nothing
- **GIVEN** Q-002 `open`
- **WHEN** `l4 questions answer Q-002 --unit A --text "yes" --no-push` runs
- **THEN** it prints the diff and the commit message and `nothing written (--no-push)`, exits 0, and the branch on `origin`, the tracking ref, the local branches and the work tree are unchanged

#### Scenario: SCN-QMD-18 (−) An answered question is refused
- **GIVEN** Q-001 with Status `answered`
- **WHEN** `l4 questions answer Q-001 --unit A --text "no"` runs
- **THEN** it exits 2 with `questions: Q-001 is answered` and a `Fix:` line that names the hand edit and L4-QMD-006, and nothing is pushed

#### Scenario: SCN-QMD-19 (−) The branch moved
- **GIVEN** a person pushes to the unit branch after the command fetched it and before it pushed
- **WHEN** the push is rejected as not a fast-forward
- **THEN** the command exits 2 with `questions: l4/openspec/a moved since the fetch` and `Fix: run the command again: it fetches first`, and the branch keeps the person's commit

#### Scenario: SCN-QMD-20 (−) A live run refuses the write
- **GIVEN** the lock ref's pending ledger of unit A has a `run.started` with no `run.finished`
- **WHEN** `l4 questions accept Q-002 --unit A` runs
- **THEN** it exits 2 with `questions: a run is working on A (run <id>)` and `Fix: try again when it ends: l4 ci watch`

#### Scenario: SCN-QMD-21 (−) The verdict rules hold
- **GIVEN** Q-004 of kind `verdict`, `open`
- **WHEN** `l4 questions accept Q-004 --unit A` runs, and then `l4 questions answer Q-004 --unit A --text "looks fine"`
- **THEN** both exit 2: the first with `accept is not an answer to it` and a `Fix:` line `l4 questions answer Q-004 --unit A --text "accept <reason>"`, the second with `a verdict answer starts with accept or reject`; `--text "reject: WHEN … THEN …"` is accepted

#### Scenario: SCN-QMD-22 (−) A text that would break the file, or holds a secret, is refused
- **GIVEN** Q-002 `open`
- **WHEN** `--text` holds a line `## Notes`, or a line `- **Status:** dismissed`, or a `glpat-…` token
- **THEN** the command exits 2, names the line number or the kind of secret, and writes nothing

### Requirement: L4-QMD-009 Agents need the project's consent for a person's decisions
The writing forms SHALL use the actor rule of `l4 yolo accept`. A caller is an agent when one of the agent markers is
set, or when standard input is not a terminal. An agent MAY accept or answer a question only when all of these hold:
- its kind is in `clarifier.auto_accept_kinds`;
- its kind is not `verdict`;
- the effective answer names no frozen path (`task.red_ok.frozen`) of a task that the question holds.

Any other write by an agent MUST be refused unless `clarifier.answer_by_agents` is `true`. Both keys MUST be read
from `.l4/config.yaml` on the base branch, never on the unit branch. `clarifier.answer_by_agents` SHALL default to
`false`. The commit body SHALL name the actor: `person`, or `agent: <marker>`.

#### Scenario: SCN-QMD-23 (+) An agent answers a technical question
- **GIVEN** `CLAUDECODE=1`, the default `clarifier.auto_accept_kinds: [technical]`, and Q-005, technical, whose answer text names no frozen path
- **WHEN** the agent runs `l4 questions answer Q-005 --unit A --text "Use argon2id."`
- **THEN** the answer is pushed, and the commit body says `By: <name> (agent: CLAUDECODE)`

#### Scenario: SCN-QMD-24 (−) An agent cannot unfreeze a test path on its own
- **GIVEN** `CLAUDECODE=1`, and Q-003, technical, whose suggestion names `conftest.py`, which the latest `task.red_ok` of the held task lists as frozen
- **WHEN** the agent runs `l4 questions accept Q-003 --unit A`
- **THEN** it exits 2 with a `Fix:` line `a person runs the command, or set clarifier.answer_by_agents: true in .l4/config.yaml on <base>`; with that key `true` on the base branch the accept is pushed; with the key `true` only on the unit branch it is still refused

#### Scenario: SCN-QMD-25 (−) An agent cannot answer a product question
- **GIVEN** an agent caller, the default configuration, and Q-002 of kind `product`
- **WHEN** it runs `l4 questions answer Q-002 --unit A --text "Allow it."`
- **THEN** it exits 2 with the agent refusal, and nothing is pushed

### Requirement: L4-OPS-017 The runbook and the skill answer a question with `l4 questions`
The runbook's procedure for `awaiting_human` SHALL give `l4 questions show`, `accept` and `answer` as the first way to
answer, and the hand edit of `questions.md` as the other way. It MUST NOT say that `l4 questions` is not available. Its
command table SHALL list the command. The skill's operating reference SHALL teach the command and the agent rule of
L4-QMD-009, and SHALL tell an agent to give a question outside that rule to a person. `l4 --help` SHALL describe
`questions` as "List and show open questions; accept or answer one on the unit branch (commits and pushes)".

#### Scenario: SCN-OPS-27 (+) The runbook and the skill name the command
- **GIVEN** the docs of this change
- **WHEN** a person reads runbook section 7.1, and an agent reads `references/operate.md`
- **THEN** both give `l4 questions answer Q-NNN --unit <unit> --text TEXT` before the hand edit, the runbook no longer lists `l4 questions` as unavailable, and `operate.md` says which questions an agent must give to a person
