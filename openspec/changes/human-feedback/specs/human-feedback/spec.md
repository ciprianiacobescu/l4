## Purpose

Let a person ask for changes to a unit, before or after its hand-off and after its merge, with one documented
command and a push. The harness turns each request into a fix task of the right kind, checks that each one was
addressed, and shows the person what happened to it.

## ADDED Requirements

### Requirement: L4-FBK-001 `feedback.md` lives in the unit folder and its owners are fixed
A unit's feedback SHALL live in `feedback.md` at the root of the unit directory, next to `questions.md`:
- OpenSpec: the change folder;
- Kiro: `.kiro/specs/<name>/`.

The file is split between two owners:
- **The person owns:** each item's heading title, *Kind*, *Where*, *Env* and *Lesson* lines, the *Code*, *Feedback*
  and *When / Then* blocks, and the Status values `draft`, `submitted` and `withdrawn`.
- **The harness owns:** the header comment, the index region, the Status values `taken` and `addressed`, and each
  item's *Outcome* block.

Harness edits MUST be span-scoped and MUST preserve every other byte. Item ids are `FB-NNN`, unique per unit and never
reused.

#### Scenario: SCN-FBK-01 (+) Harness edits leave the person's text alone
- **GIVEN** a `feedback.md` with two items whose texts contain Markdown headings in code fences and trailing spaces
- **WHEN** the harness marks FB-001 `taken` and writes its Outcome
- **THEN** only FB-001's Status value, its Outcome block and the index changed, byte for byte

#### Scenario: SCN-FBK-02 (−) A deleted item's id is not reused
- **GIVEN** a file where the person deleted the section of FB-002, which the ledger records as taken
- **WHEN** `l4 feedback add` adds an item
- **THEN** the new item is FB-003

### Requirement: L4-FBK-002 An item is valid by its kind
Each item SHALL carry Status, Kind, Feedback text and, depending on its kind, these fields:

| Kind | Required | Refused |
|---|---|---|
| `refactor` | at least one *Where* | *Env*, *When*, *Then* |
| `duplication` | at least one *Where* | *Env*, *When*, *Then* |
| `tests` | — | *Env*, *When*, *Then* |
| `config` | at least one *Where* and *Env* matching `^[A-Z_][A-Z0-9_]*$` | — (*When* and *Then* together, or neither) |
| `behaviour` | *When* and *Then* | *Env* |

Parsing MUST be tolerant: Status and Kind are case-insensitive, and an unknown Status reads as `draft`. An item that
breaks these rules is invalid: it MUST NOT be taken, and it MUST be reported with its problem in the sticky note and as
`feedback.invalid{id, problem}`.

#### Scenario: SCN-FBK-03 (−) A config item without a variable is not taken
- **GIVEN** a submitted `config` item with no *Env* line
- **WHEN** the next verification round starts
- **THEN** the item is not taken, the note says `FB-001 invalid: config needs Env`, and `feedback.invalid` is recorded

#### Scenario: SCN-FBK-04 (−) A draft is never read
- **GIVEN** a valid item whose Status is `draft`
- **WHEN** the next verification round starts
- **THEN** the item is not taken, and the note lists it as a draft

### Requirement: L4-FBK-003 `l4 feedback` writes the file and nothing else
`l4 feedback` SHALL offer `add`, `list`, `show`, `submit` and `withdraw`. It MUST write only `feedback.md`, and MUST
never commit, push, or call the forge.

- **The unit** is `--unit ID`, else the one named by the checked-out branch `l4/<framework>/<name>`. Otherwise the
  command exits 2 and lists the units.
- **`--at PATH[:L[-L]]`** (up to 5):
  - names a repository-relative file in the working tree, outside `.l4/` and every spec root;
  - its line range MUST exist;
  - the named lines are quoted into the item's *Code* block, at most 40 lines or 4,000 bytes, redacted.
- **Before writing,** the kind rules of L4-FBK-002 MUST be checked. A failed check is exit 2, and nothing is written.
- **After writing,** `add` MUST print the item id, the file, and the `git add`, `git commit` and `git push` lines that
  send it.
- **`--text -`** reads standard input.
- **`--draft`** writes Status `draft`; otherwise the item is `submitted`.
- **`list` and `show`** accept `--json`, printing `{"schema": "l4/feedback@1", …}`.

#### Scenario: SCN-FBK-05 (+) Add on a unit branch
- **GIVEN** the checked-out branch `l4/openspec/add-reorder-quantity` and `src/inventory/reorder.py` with 20 lines
- **WHEN** the person runs `l4 feedback add --kind refactor --at src/inventory/reorder.py:4-9 --text "extract the rounding into a helper"`
- **THEN** `openspec/changes/add-reorder-quantity/feedback.md` holds FB-001, Status `submitted`, with lines 4–9 quoted
- **AND** the output names FB-001 and the three git lines, and `git status` shows only that file changed

#### Scenario: SCN-FBK-06 (−) A refused item writes nothing
- **GIVEN** the same branch
- **WHEN** the person runs `l4 feedback add --kind behaviour --text "round down"` without `--when`/`--then`
- **THEN** the exit code is 2, the message names `--when` and `--then`, and no file changed

#### Scenario: SCN-FBK-07 (−) A place outside the code is refused
- **GIVEN** the same branch
- **WHEN** `--at` names `.l4/config.yaml`, a spec file, a missing file, or line 40 of a 20-line file
- **THEN** each is exit 2 and writes nothing

### Requirement: L4-FBK-004 Items are taken at step 0 of the next verification round
At step 0 of every verification round of a unit, each takeable item SHALL become a deterministic blocking finding.
The finding has `source: "feedback"`, the item's id, kind and places, and the text whole up to 1,200 characters. When
any item is taken, the round MUST fail at step 0 without running gates or judges, and the fix unit of L4-VER-006 is
written.

An item is takeable when all of these hold:
- it is valid;
- it is not `withdrawn`;
- its Status is `submitted`, or its human content differs from what the last `feedback.taken` recorded
  (L4-FBK-007);
- the feedback round limit (L4-FBK-006) is not reached.

Before the hand-off, items MUST wait for the next round: no running task or fix unit is interrupted. A push of
`feedback.md` after the hand-off re-enters the unit through the existing spec-edit row, then `ALL_LEAVES_DONE` leads
to this round. Each taken item is recorded as `feedback.taken{id, kind, sha256, round, fix_unit}`. Its Status becomes
`taken`, and its Outcome names the fix unit.

#### Scenario: SCN-FBK-08 (+) Feedback after the hand-off re-enters and fails the round at step 0
- **GIVEN** a unit `in_review` at H, and a person's commit that adds a submitted `refactor` item to `feedback.md`
- **WHEN** the next run reads the branch
- **THEN** the phases go `in_review → implementing → verifying → fixing`
- **AND** the round's verdict is FAIL at step 0 with one feedback finding, no gate or judge ran, and a fix unit exists

#### Scenario: SCN-FBK-09 (+) Feedback before the hand-off waits for the round
- **GIVEN** a unit `implementing` task 2.1, and a person's push that adds a submitted item mid-run
- **WHEN** the run that resumes the unit continues
- **THEN** task 2.1 and the remaining tasks run as planned, and the item is taken at step 0 of the unit's verification

#### Scenario: SCN-FBK-10 (−) Nothing to take, nothing changes
- **GIVEN** a unit whose `feedback.md` has only `addressed` and `withdrawn` items with unchanged content
- **WHEN** a verification round starts
- **THEN** step 0 adds no feedback finding

### Requirement: L4-FBK-005 Each kind gets its own kind of fix task
The fix unit SHALL hold one task per taken item. A task is never shared with another finding. The proposal (OpenSpec)
or `bugfix.md` (Kiro) MUST put the person's request first: "Requested by <By> in FB-NNN (<kind>, <places>): <text>".
The request is kept whole up to 1,200 characters and followed by the quoted code. The task for each kind:

- **`refactor` and `duplication`:** a harness chore (marker `refactors`) with no red step.
  - Every path matching `tdd.test_globs` or `tdd.test_support_globs` that the step changed MUST be put back, as
    `guard.restored{paths, reason: "feedback_refactor"}`.
  - At least one other file MUST change, or the attempt fails with `nothing changed`.
  - Every gate MUST pass.
- **`tests`:** the test chore of L4-VER-006 (marker `test_chores`).
- **`config`:** red/green against an ADDED criterion with these scenarios:
  1. `WHEN the environment variable NAME is set THEN the system SHALL use its value instead of the value written at <place>`, or the item's own *When*/*Then* in its place;
  2. `WHEN NAME is not set THEN the system SHALL CONTINUE TO behave as before this change`.
- **`behaviour`:** red/green against an ADDED criterion from the item's *When*/*Then*.

The ADDED criterion takes this form:
- OpenSpec: a requirement `### Requirement: <title> — feedback FB-NNN` with the scenarios;
- Kiro: `2.n`/`3.n` items in `bugfix.md`.

Items past `MAX_FIX_TASKS` MUST stay takeable and wait for the next round, as `feedback.waiting{ids, reason: "fix_unit_full"}`. They are never "not converted".

#### Scenario: SCN-FBK-11 (+) A refactor changes code and keeps every test
- **GIVEN** a taken `refactor` item, and an agent step that edits `src/inventory/reorder.py` and also `tests/test_reorder.py`
- **WHEN** the step ends
- **THEN** `tests/test_reorder.py` is put back with `guard.restored{reason: "feedback_refactor"}`, the source change stays, and the gates run on the original tests

#### Scenario: SCN-FBK-12 (−) A refactor that changes nothing fails its attempt
- **GIVEN** a taken `duplication` item, and an agent step that changes only a test file
- **WHEN** the step ends
- **THEN** the test file is put back, and the attempt fails with `nothing changed`

#### Scenario: SCN-FBK-13 (+) A config item goes through red and green
- **GIVEN** a taken `config` item with `Env: PACK_ROUNDING` at `src/inventory/reorder.py:7`
- **WHEN** the fix unit is written and run
- **THEN** it has an ADDED requirement `… — feedback FB-001` with the two scenarios of this requirement
- **AND** its task runs red (a new test fails) and then green

#### Scenario: SCN-FBK-14 (−) A sixth item waits
- **GIVEN** six submitted items
- **WHEN** they are taken at step 0
- **THEN** the fix unit has five tasks, FB-006 stays `submitted`, and the note says `FB-006 waiting for the next round (fix unit full)`

### Requirement: L4-FBK-006 Feedback rounds have their own limit
A fix unit SHALL be a feedback fix unit when every blocking finding it consumes has `source: "feedback"`.
- Feedback fix units MUST NOT count against `verifier.max_fix_rounds`.
- They count against `feedback.max_rounds` (default 5, minimum 0; 0 turns taking off). The limit is raised by
  `budget.extended{feedback_rounds}`, which `l4 resume --extend-feedback-rounds N` and the resume label record.
- At the limit, with takeable items, the unit MUST go to `escalated` (exit 13) with the note
  `feedback round limit reached (N)`.
- A fix unit that also consumes a non-feedback finding is a normal fix round.

#### Scenario: SCN-FBK-15 (+) Feedback does not use up fix rounds
- **GIVEN** `verifier.max_fix_rounds: 1` and a unit that already used its one fix round
- **WHEN** a person submits an item after the hand-off
- **THEN** a feedback fix unit is written, and the unit is not escalated

#### Scenario: SCN-FBK-16 (−) The feedback limit escalates
- **GIVEN** `feedback.max_rounds: 1`, one feedback fix unit already done, and a new submitted item
- **WHEN** the next round's step 0 runs
- **THEN** the unit is `escalated` with exit 13 and the note `feedback round limit reached (1)`

### Requirement: L4-FBK-007 Each taken item is checked, and an edit re-opens it
In a round whose family holds a feedback fix unit with items taken and not yet addressed, the judge SHALL get the data
block `<l4:data kind="feedback">`. The block holds each such item's id, kind, places, quoted code, text, and its
*When*/*Then* or *Env*. The judge reply MUST carry `feedback: [{id, addressed, evidence}]` (SPEC §10.3; prompt version
7).

An item is addressed when:
- every judge that got the block answers `addressed: true` (a missing answer counts as `false`, with the evidence
  "not answered"); and
- for `config`, NAME appears in a non-test file the family changed. Without it the item is not addressed, whatever the
  judges answer.

An item that is not addressed MUST become a blocking finding (`source: "feedback"`, title
`FB-NNN not addressed: <evidence>`) and the round fails into the next feedback fix unit. An addressed item gets Status
`addressed`, an Outcome with the round and short sha, and `feedback.addressed{id, round, sha, evidence}`.

`feedback.taken` stores the sha256 of the item's human content (kind, places, env, when, then and text, whitespace
normalised). A later change to that content makes the item takeable again (`feedback.changed`), whatever its Status.
`withdrawn` after a take stops the item being judged (`feedback.withdrawn`).

#### Scenario: SCN-FBK-17 (+) Addressed items close
- **GIVEN** a feedback fix unit that is done, with FB-001 (`refactor`) and FB-002 (`config`, `Env: PACK_ROUNDING`)
- **WHEN** the parent is re-verified, the judge answers both `addressed: true`, and `PACK_ROUNDING` appears in `src/inventory/reorder.py`
- **THEN** the round can PASS, both items read `addressed` with the round and sha, and the unit hands off again

#### Scenario: SCN-FBK-18 (−) The judge's yes cannot close a config item without its variable
- **GIVEN** the same, but no changed non-test file contains `PACK_ROUNDING`
- **WHEN** the judge answers `addressed: true` for FB-002
- **THEN** FB-002 is not addressed, and the round fails into a new feedback fix unit

#### Scenario: SCN-FBK-19 (+) An edit after the take re-opens the item
- **GIVEN** FB-001 `addressed`
- **WHEN** the person changes its Feedback text and pushes
- **THEN** the next round takes FB-001 again, and `feedback.changed` records both hashes

### Requirement: L4-FBK-008 Kiro fix units are bugfix specs
`KiroProvider.create_fix_unit` SHALL write `.kiro/specs/<parent>-fix-<n>/` with these files:
- **`bugfix.md`** in Kiro's template. Its sections:
  - `# Bugfix Requirements Document`, then `## Bug Analysis`;
  - `### Current Behavior (Defect)`: one `1.n` per finding;
  - `### Expected Behavior (Correct)`: one `2.n` per criterion a task fixes, or per spec-gap or feedback scenario;
  - `### Unchanged Behavior (Regression Prevention)`: the unnumbered sentence "The system SHALL CONTINUE TO satisfy every
    other acceptance criterion of <parent>." (not a criterion: no test could trace it), plus the `3.n` items of `config`
    items.
- **`design.md`**.
- **`tasks.md`** in Kiro's grammar: leaves cite `2.n`/`3.n` with `_Requirements:_`, chores carry `[chore]` and their
  finding ids in the title and cite nothing (the tag makes them TDD-exempt), and there is a one-wave `## Task Dependency Graph`.
- **`.config.kiro`:** `{"specId": <uuid4>, "workflowType": "requirements-first", "specType": "bugfix"}`.
- **`.l4/fix.json`**.

An Expected Behavior item that restates a parent criterion MUST carry that criterion's id and be read as it, not as a
new criterion. The fix unit MUST pass the provider's validation, or its folder is removed. `decide_fix` MUST NOT
escalate a Kiro unit for lack of fix units.

#### Scenario: SCN-FBK-20 (+) A failed Kiro round gets a bugfix fix unit
- **GIVEN** a Kiro unit whose round 1 fails one criterion `Req 1.2` (C-1a2b3c4d)
- **WHEN** the round ends
- **THEN** `.kiro/specs/<parent>-fix-1/` holds the five files, `bugfix.md` has `2.1` restating C-1a2b3c4d, and the unit is `fixing`, not `escalated`
- **AND** re-verification counts C-1a2b3c4d once

#### Scenario: SCN-FBK-21 (−) An invalid Kiro fix unit leaves nothing behind
- **GIVEN** a Kiro fix unit whose tasks would cite a requirement that does not exist
- **WHEN** validation fails
- **THEN** the folder and any stray files are removed, and the unit escalates with the validation error

### Requirement: L4-FBK-009 Feedback can become a lesson
An item with `Lesson: yes` that is addressed in a PASS round SHALL become or reinforce a lesson (L4-MEM-001), with:
- Origin `feedback`;
- dedupe key `feedback-<first 12 hex of sha256(normalised text)>`;
- scope: the directories of its places (`<dir>/**`), else unscoped;
- body: its text, at most 600 characters;
- source: `human feedback FB-NNN (<unit> round N)`.

It is committed as L4-MEM-005 requires.

#### Scenario: SCN-FBK-22 (+) The same request on a second unit reinforces one lesson
- **GIVEN** a lesson from FB-001 of unit A ("read endpoints from the environment")
- **WHEN** unit B's FB-003, with the same text and `Lesson: yes`, is addressed in a PASS round
- **THEN** the lesson with that dedupe key is reinforced, not duplicated

### Requirement: L4-FBK-010 After the merge, feedback becomes a follow-up unit
`l4 feedback add` on a `merged` unit SHALL write to that unit's folder on the checked-out branch:
- OpenSpec: the archive folder `openspec/changes/archive/*-<name>/` when archived;
- Kiro: `.kiro/specs/<name>/`.

A base-branch run that finds a merged unit with takeable items and no open follow-up MUST create the unit
`<name>-followup-<n>`:
- it uses the parent's framework and a new unit branch from the base head;
- its tasks follow L4-FBK-005;
- its marker is `.l4/followup.json` `{parent, items: [{id, sha256}]}`;
- it takes the items in its own ledger, and sets their Status `taken` in its branch's copy of the parent's file.

Its rounds judge those items (L4-FBK-007). While a follow-up of the parent is open, newer items MUST wait as
`feedback.waiting{reason: "follow_up_open"}`. The parent's phase does not change.

#### Scenario: SCN-FBK-23 (+) Feedback on a merged Kiro unit
- **GIVEN** a merged Kiro unit `add-reorder-quantity`, and a base commit that adds a submitted `duplication` item to its `feedback.md`
- **WHEN** the next base run plans
- **THEN** the unit `add-reorder-quantity-followup-1` exists on its own branch with one chore task, and its PR opens as draft

#### Scenario: SCN-FBK-24 (−) One follow-up at a time
- **GIVEN** an open `add-reorder-quantity-followup-1`, and a new submitted item on the parent
- **WHEN** the next base run plans
- **THEN** no second follow-up is created, and the item reads `waiting (follow-up open)`

### Requirement: L4-FBK-011 The person sees every item, and how to ask
The sticky note SHALL carry a *Your feedback* section while the unit has any item. It has one line per item, giving
its state:
- draft;
- submitted;
- taken into `<fix unit>`;
- waiting (with the reason);
- addressed in round N at `<sha>`;
- not addressed in round N (evidence);
- invalid (the problem);
- withdrawn.

Every sticky note of a unit in `in_review` MUST end with the line:
`To ask for changes: l4 feedback add --kind refactor|duplication|tests|config|behaviour --at FILE:LINE --text "…", then commit and push (docs/feedback.md).`

Elsewhere, `verification.md` MUST list the items taken or judged in its round under `## Feedback`, and `l4 status`
MUST show the item counts per state.

#### Scenario: SCN-FBK-25 (+) The hint is there when the PR is ready
- **GIVEN** a unit that just handed off
- **WHEN** its sticky note is written
- **THEN** the note ends with the `To ask for changes:` line

#### Scenario: SCN-FBK-26 (+) The note follows an item through its life
- **GIVEN** FB-001 submitted after the hand-off
- **WHEN** it is taken, then addressed two rounds later
- **THEN** the note read `taken into add-reorder-quantity-fix-1`, then `addressed in round 3 at <sha>`

### Requirement: L4-FBK-012 Agents cannot write feedback
`feedback.md` SHALL be a protected path for every agent role (L4-SEC-004 already covers the spec roots). The prompt
contract (L4-IMP-004) MUST name it beside `tasks.md` and `questions.md`. A base merge MUST resolve `feedback.md` by
item:
- the union of items by id;
- each item's human content from the side that changed it since the merge base, else from the unit branch;
- harness spans from the unit branch.

#### Scenario: SCN-FBK-27 (−) An agent marking its own item addressed is put back
- **GIVEN** an agent step that sets FB-001's Status to `addressed`
- **WHEN** the step ends
- **THEN** `feedback.md` is restored, and a `guard.violation` names it

### Requirement: L4-FBK-013 Live evidence on a Kiro unit
The change SHALL be proven live on a dummy repository with a Kiro unit authored by kiro-cli. The run goes:
1. the unit runs to a ready PR;
2. a person sends one `refactor` item and one `config` item with `l4 feedback add`, then commits and pushes;
3. both are taken, fixed and judged addressed;
4. the PR returns to ready, and a person merges.

The evidence is recorded under `docs/live/feedback/`.

#### Scenario: SCN-FBK-28 (+) The full loop on a Kiro unit
- **GIVEN** a dummy repository with a Kiro unit at a ready PR
- **WHEN** a person sends a `refactor` and a `config` item and pushes
- **THEN** the run log shows the step-0 FAIL, a Kiro bugfix fix unit, red/green for the config task, a chore for the refactor, a PASS with both items addressed, and a new hand-off
