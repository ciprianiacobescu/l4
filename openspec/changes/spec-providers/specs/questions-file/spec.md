## Purpose

Defines the `questions.md` file in each unit directory: its exact grammar (SPEC §6.2), who owns which bytes, tolerant parsing, section-scoped harness edits, ID rules and the answered/blocked semantics that resume a unit (SPEC §6).

## ADDED Requirements

### Requirement: L4-QMD-001 (part a) Location
`questions.md` MUST live at the root of the unit directory returned by `SpecProvider.unit_dir`, never in `.l4/` and never at the repository root.

#### Scenario: SCN-QMD-N12 (−) No other location is read or written
- **GIVEN** a stray `questions.md` at the repository root and in `<unit>/.l4/`
- **WHEN** the harness loads questions for the unit
- **THEN** neither stray file is read, and a first question is written to `<unit>/questions.md`.

### Requirement: L4-QMD-001 (part b) Human-owned answers
Humans own the Answer blocks and the Status values they set. The harness owns everything else and MUST NOT alter human-written answer text.

#### Scenario: SCN-QMD-N13 (−) Appending a question never touches a human answer
- **GIVEN** Q-001 with a human-written answer and Status `answered`
- **WHEN** the harness raises Q-002
- **THEN** every byte of Q-001's section is unchanged.

### Requirement: L4-QMD-001 (part c) File grammar
The harness MUST write `questions.md` exactly as SPEC §6.2: the title `# Questions — <unit>`, the `<!-- l4:questions v1 … -->` instruction comment, an index table between `<!-- l4:index:start -->` and `<!-- l4:index:end -->`, then per question a `---` rule and `## Q-NNN: <title>` with fields Status, Blocking tasks, Kind, Asked, Criteria, and subsections Context, Options, Clarifier suggestion, Answer.

#### Scenario: SCN-QMD-01 (+) Harness writes a well-formed question
- **GIVEN** an implementer question
- **WHEN** written
- **THEN** the section has ID, Status `open`, Blocking tasks, Kind, Asked, Criteria, Context, Options, Answer block; the index row is added between the index markers; no other byte changes.

### Requirement: L4-QMD-002 (part a) Tolerant parsing
Parsing MUST be tolerant: Status values case-insensitive; a missing index table allowed (regenerated); an unknown Status value treated as `open`. An Answer block is non-empty when it contains non-whitespace text after removing HTML comments.

#### Scenario: SCN-QMD-06 (−) Unknown status value
- **GIVEN** `- **Status:** yes` with a non-empty answer
- **WHEN** parsed
- **THEN** treated as `open` (the answer is not consumed); the sticky comment asks for a valid Status.

#### Scenario: SCN-QMD-N15 (+) Case-insensitive status and missing index
- **GIVEN** a file with `- **Status:** ANSWERED`, a non-empty answer and no index table
- **WHEN** parsed
- **THEN** the status is `answered` and the answer is consumed; the index is regenerated only on the next harness write.

### Requirement: L4-QMD-002 (part b) Drafts are never consumed
An answer MUST count only when its Status is explicitly `answered`, `accepted` or `dismissed`. A non-empty Answer under Status `open` MUST produce the reminder "Q-NNN has an answer but its Status is still open — set it to `answered` to submit" and the event `question.unsubmitted_answer`.

#### Scenario: SCN-QMD-03 (−) A draft answer is not consumed
- **GIVEN** a non-empty answer with Status still `open`
- **WHEN** the next run plans
- **THEN** the answer is ignored, the blocked tasks stay blocked, the sticky comment reminds the human to set `Status: answered`, and `question.unsubmitted_answer` is logged.

### Requirement: L4-QMD-002 (part c) Answers pass the redaction filter
Answer text MUST reach prompts, logs, the ledger and comments only through the L4-OBS-002 redaction filter. The parser MUST flag a question whose raw answer matches a secret pattern so the sticky comment can ask the human to rotate the secret.

#### Scenario: SCN-QMD-09 (−) A secret pasted into an answer
- **GIVEN** an answer containing a `glpat-…` token
- **WHEN** prompts and logs are produced
- **THEN** the token is replaced by `[REDACTED:gitlab-token]` in prompts, logs, ledger and comments; the sticky comment asks the human to rotate it.

### Requirement: L4-QMD-003 (part a) Section-scoped edits
Harness edits MUST be limited to the index region, newly appended sections, and the Status line and Clarifier suggestion block of one question, and MUST preserve every other byte, including sections the harness does not know.

#### Scenario: SCN-QMD-N16 (−) Unknown human section survives a harness edit
- **GIVEN** a human-added `## Notes` section between two questions
- **WHEN** the harness updates a Status line and the index
- **THEN** only those regions differ; the `## Notes` section is byte-identical.

### Requirement: L4-QMD-003 (part b) Restore from the ledger
The `question.raised` ledger event MUST store the full harness-written section. A section deleted or mangled by a human edit MUST be re-rendered from the ledger (`question.restored`) while any surviving human answer text is kept.

#### Scenario: SCN-QMD-05 (−) A human deletes a question section
- **GIVEN** Q-002's section removed by a human edit
- **WHEN** parsed
- **THEN** the harness re-renders the harness-owned parts of Q-002 from the ledger (`question.restored`), keeps any surviving human text, and leaves Q-002 open; unknown human-added sections are preserved untouched.

### Requirement: L4-QMD-004 (part a) Question IDs
IDs MUST be `Q-NNN`, unique per unit and never reused, even after a question is dismissed or superseded. A `superseded` question MUST name its successor.

#### Scenario: SCN-QMD-N14 (−) A used ID is never reissued
- **GIVEN** Q-001 dismissed and Q-002 superseded by Q-003
- **WHEN** the harness raises a new question
- **THEN** it is Q-004, and Q-002's section names Q-003.

### Requirement: L4-QMD-004 (part b) Verdict answers
For `Kind: verdict` questions the answer MUST start with the word `accept` or `reject` (case-insensitive). Any other answer with Status `answered` is invalid: it MUST NOT be consumed, and the sticky comment asks for a fix.

#### Scenario: SCN-QMD-11 (−) Invalid verdict answer
- **GIVEN** a `Kind: verdict` question answered "looks fine to me" with Status `answered`
- **WHEN** parsed
- **THEN** the answer is not consumed; the sticky comment asks to start the answer with `accept` or `reject`.

### Requirement: L4-QMD-004 (part c) Raise-batch limit
The questions writer MUST refuse a batch larger than `clarifier.max_open_questions` (default 3) with `TooManyQuestions` and write nothing; the implementer-result schema (`maxItems: 3`) enforces the same limit upstream.

#### Scenario: SCN-QMD-10 (−) More than three questions
- **GIVEN** a result with five questions
- **WHEN** validated
- **THEN** the result is schema-invalid (`maxItems: 3`) → repair prompt asking for the three most blocking ones; `QuestionsFile.raise_questions` called with the five raises `TooManyQuestions` and `questions.md` is unchanged.

### Requirement: L4-QMD-005 Answered and unblocked
A question MUST count as answered when Status is one of `answered`, `accepted`, `answered-by-clarifier` or `dismissed`; `accepted` makes the clarifier suggestion the effective answer. A unit MUST be unblocked only when every question listing a pending task under Blocking tasks is answered.

#### Scenario: SCN-QMD-02 (+) Human answers → run resumes
- **GIVEN** Q-002 open and blocking 3.1
- **WHEN** a human writes an answer, sets `Status: answered`, commits and pushes to the unit branch
- **THEN** the unit leaves `awaiting_human`; the implementer prompt for 3.1 contains the answer; `question.answered{by: human, answer_sha256}` is logged. (The CI trigger on push is owned by forge-and-ci.)

#### Scenario: SCN-QMD-04 (+) Accepting the clarifier suggestion
- **GIVEN** Status set to `accepted`
- **WHEN** parsed
- **THEN** the clarifier suggestion text becomes the effective answer.

#### Scenario: SCN-QMD-07 (+) Dismissed question unblocks
- **GIVEN** Status `dismissed`
- **WHEN** planning
- **THEN** the blocked tasks become eligible; the prompt notes "Q-00N dismissed by a human: proceed without it".

#### Scenario: SCN-QMD-N17 (−) One open question keeps its tasks blocked
- **GIVEN** Q-001 answered and Q-002 open, both listing task 3.1, while task 3.2 is listed by neither
- **WHEN** blocked tasks are computed
- **THEN** 3.1 is blocked by Q-002 only and 3.2 is not blocked.

### Requirement: L4-QMD-006 Override of a consumed answer
The harness MUST store `sha256(answer text)` per question consumed by the implementer. If a later commit changes the answer of a consumed question, the harness MUST spawn a fix unit "apply clarification Q-NNN" and MUST NOT edit the parent's `tasks.md`.

#### Scenario: SCN-QMD-08 (+) Override of a consumed answer spawns a fix unit
- **GIVEN** Q-003's answer was consumed by task 2.1 (hash H1) and a human later changes it (hash H2)
- **WHEN** the next run plans
- **THEN** a fix unit `<unit>-fix-<n>` "apply clarification Q-003" is created; `tasks.md` of the parent is untouched.

#### Scenario: SCN-QMD-N18 (−) Unchanged answer re-commit spawns nothing
- **GIVEN** a consumed answer re-committed with unchanged text (hash H1 again)
- **WHEN** the next run plans
- **THEN** no fix unit is created.
