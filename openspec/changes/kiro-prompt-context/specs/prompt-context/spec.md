## Purpose

The implementer's prompt always carries the text of the criteria and the task's whole block, fills the rest of its
context budget in a fixed order, and names everything it could not show, so that the agent and a person know what
is missing and where to read it.

## MODIFIED Requirements

### Requirement: L4-IMP-004 Prompt assembly
Prompts MUST be assembled from versioned templates (`l4harness/prompts/*.md`, overridable in
`.l4/prompts/`) with these sections, in order: harness contract (rules below); project conventions (the steering files that apply, L4-KSP-010, or an OpenSpec unit's `context`, L4-IMP-051), when there are any; unit context (the requirements narrative, spec deltas, design and proposal, chosen within the context budget by L4-IMP-051 and L4-IMP-053); `Not shown in full`, when a source was cut or not read (L4-IMP-052); the task's whole block (L4-IMP-050); its criteria with ids, aliases and full text (L4-IMP-050);
answered questions relevant to the task; selected lessons (§13); the previous attempt (a limit or an escalation, L4-IMP-017); the person's note on a retry (`# A person's note`, one data block, the last of the data blocks, L4-OPS-018; `prompt.rendered{retry_note: {event, ts, sha256}}`); gate commands; output contract and
`$L4_RESULT_PATH`. The rendered prompt's sha256, template version, budget (`budget_tokens`, `budget_source`) and steering decisions (`steering`) MUST be recorded in the ledger (`prompt.rendered`), and a cut or unread source as `prompt.truncated` (L4-IMP-052). The output contract of a prompt-contract step comes from the template `output.md` (L4-IMP-019), and `template_version` names it (`+output@1`); the output contract of a native step does not change. The phase section MUST carry one `result values:` line, built from the result schema, that names the allowed `status` values and the step's `phase` (a model that has just read `# Phase: RED` otherwise writes `"status": "red"`). The Codex implementer's sandbox blocks sockets, loopback included (an all-outbound `network_access` switch is not taken, L4-SEC-001; verified on macOS seatbelt, where `network.enabled` without a proxy opens full egress and the seccomp profile of Linux denies every IP socket call): the contract says so, tells Codex to WRITE the real-server test a task or design asks for (port 0 in a thread, every read bounded), which the gate run executes with loopback, and to add in-process tests beside it, never instead of it and never a `socket.socketpair()` in place of a requested server (wave D W-D3: five units without a real-server test, because the earlier text recommended the in-process route). A loopback-only profile (`default_permissions` with `network.enabled`, `allow_local_binding` and the `network_proxy` feature, no `domains`) works on macOS and is NOT adopted until a Linux spike confirms it inside bwrap (the Linux seccomp ProxyRouted mode also denies AF_UNIX sockets). A blocked green step on a frozen test that contradicts the spec asks one technical question whose first option is "Edit `<path>`: <the exact change>", which is also written as its suggested answer, so one `accepted` unfreezes exactly that file (L4-IMP-002). The question ends with a harness note (`Harness note: ...`, M1.13) that names the frozen test files the question already names, at most three, and says how they are unfrozen: the answer, or `accepted` on the suggested edit, must name the path, and an answer edited after a run has used it counts as an override and unfreezes nothing; a question that names no frozen file says that it cannot unfreeze anything. The note never names a file the agent did not, so it cannot widen what an `accepted` suggestion unfreezes.
The harness contract MUST name the run's own ledger file and say that `git status` shows it as modified, that this is
expected, and that nothing under any `.l4/` directory, at any depth, may be edited, restored, checked out or
overwritten; this holds for every step, a fix unit's included (it names its parent's ledger). For an adapter whose
agent resets files it did not touch (codex), the contract MUST also forbid git commands that write the work tree and
shell redirects into tracked files. The contract also says that the spec root (`openspec/**`, `.kiro/specs/**`: the archived
specs, other changes, the archive) is human-owned and read-only for every step, the current unit's own directory included;
a copy of a scenario made there is reverted and recorded as `guard.violation`.
When `gates.e2e` is configured, the red prompt's gate section MUST name the
directory its browser tests live in (the first directory word after `pytest` in `gates.e2e.command` that exists in the
worktree, else `e2e/`, the directory of the verifier's generated tests, L4-VER-002a), say that a browser test goes
there and never under `tests/` (the unit gate has no server, so a browser test there fails and costs a red attempt),
or, when that directory is itself under `tests/` (`tests/e2e`), that it goes there and nowhere else, and name the
environment variable that carries the app's address (`verifier.playwright.base_url_env`). The lesson about UI criteria
without an end-to-end test (§13) is one text for every project and names the default directory, `e2e/`; the prompt's
gate section, which names the configured one, wins (`red.md`). Without an e2e gate the prompt says
nothing about browser tests. [V, live M1.5 P3, job 5528: Codex put the browser test under `tests/` and lost one red
attempt; template `red@5`.]

#### Scenario: SCN-IMP-280 (+) A Kiro red prompt has its sections in order
- **GIVEN** the probe unit `kiro:tip-calc` with its short `design.md`, its `requirements.md`, its `tasks.md` and
  `.kiro/steering/tech.md`, and the default budget
- **WHEN** the red prompt of task 1 is rendered
- **THEN** its sections are `# Harness contract`, `# Project conventions`, `# Unit context`, `# Task 1`,
  `# Criteria of this unit`, `# Phase: RED`, `# Gate command` and `# Output`, in that order
- **AND** it has no `# Not shown in full` section, and its template version is `contract@12+red@11`

## ADDED Requirements

### Requirement: L4-IMP-050 The criteria and the task's whole block are never cut
The Criteria section SHALL list each criterion the task is given (for a Kiro leaf, those its `_Requirements:_` line
names, else all of the unit's) with its id, alias and full text. The Task section SHALL hold the task's whole block
from `tasks.md`: its enclosing headings, its parent tasks' lines, its checkbox line and every line under it up to the
next task or heading. Neither SHALL ever be cut, and both SHALL be charged to the context budget first.

#### Scenario: SCN-IMP-281 (−) A long design no longer takes the criteria text away
- **GIVEN** the probe unit with its `design.md` of 125,492 characters (the preamble with `DESIGN-MARKER`, then 1,100
  `## Component N` sections) and the default budget of 24000 tokens
- **WHEN** the red prompt of task 1 is rendered
- **THEN** the Criteria section holds `C-1a9abc58  Req 1.1` followed by `WHEN a bill and a tip percent are given THEN
  the system SHALL return the tip rounded to 2 places.`, and `C-41bc8f70  Req 1.2` followed by `WHEN the tip percent
  is negative THEN the system SHALL raise ValueError.`
- **AND** `requirements.md` is in the unit context whole, `REQ-INTRO-MARKER` included, where 0.4.14 showed
  `[truncated: omitted to fit the context budget]`

#### Scenario: SCN-IMP-282 (+) A Kiro leaf's detail bullets reach the prompt
- **GIVEN** the probe's leaf `- [ ] 1. Implement the tip function` with the lines `- TASK-DETAIL-MARKER: reject a
  percent above 100 with ValueError as well`, `- Use Decimal throughout` and `- _Requirements: 1.1, 1.2_` under it
- **WHEN** its red, green and single prompts are rendered, once with the default budget and once with a budget of 1
  token
- **THEN** each `# Task 1` block holds the checkbox line and the three lines under it, in the file's order, inside one
  data block whose source is `.kiro/specs/tip-calc/tasks.md`

### Requirement: L4-IMP-051 The context budget is filled in priority order
After the criteria and the task block, the budget SHALL be filled in this order: the project conventions
(L4-KSP-010, or an OpenSpec unit's `context` of `openspec/config.yaml`, never its `rules`), at most half the budget;
the requirements narrative, named sections first; `design.md`, named sections first, then its preamble and the rest;
`proposal.md`. A source SHALL be cut by whole sections, each gap marked, and every later piece left out.

#### Scenario: SCN-IMP-283 (+) A short budget keeps the conventions, then the requirements, then the design
- **GIVEN** the probe unit whose 125,492-character `design.md` has `**Validates: Requirements 1.2**` in its section
  `## Component 1050`, and the default budget
- **WHEN** the red prompt of task 1 is rendered
- **THEN** `tech.md` and `requirements.md` are whole, and `design.md` shows, in document order, its preamble
  (`DESIGN-MARKER`), its first sections and `## Component 1050`, although that section lies past the point where the
  budget runs out
- **AND** one line `[not shown: lines A-B]` stands for each run of sections left out
- **AND** the conventions and the unit context together hold at most 96,000 characters less the criteria and the
  task block

#### Scenario: SCN-IMP-284 (+) An OpenSpec unit gets its project context and not its rules
- **GIVEN** an OpenSpec unit in a repository whose `openspec/config.yaml` has `context: "Runtime: Python >= 3.11, uv,
  src layout"` and `rules: {tasks: ["Tasks are TDD-shaped"]}`
- **WHEN** its red prompt is rendered
- **THEN** `# Project conventions` holds one block with the source `openspec/config.yaml#context` and the text
  `Runtime: Python >= 3.11, uv, src layout`, and no text of the rules

### Requirement: L4-IMP-052 A cut or unread source is named and recorded
A source that is cut or not read SHALL never vanish. The prompt's `# Not shown in full` section SHALL name each by
its repository path with the characters shown and in total, the lines left out and the reason (`budget`, `oversize`
over 262,144 bytes, `symlink`, `not_regular`), and the contract SHALL tell the agent to open a readable one with its
tools. The run SHALL record `prompt.truncated{role, task, attempt, budget_tokens, sources}` with the same entries.

#### Scenario: SCN-IMP-285 (−) A cut file is named with its path, and the agent is told to open it
- **GIVEN** the probe unit of SCN-IMP-281 and a run whose red step of task 1 starts
- **WHEN** the prompt is rendered and the step records it
- **THEN** `# Not shown in full` lists `.kiro/specs/tip-calc/design.md: <shown> of 125492 characters shown (budget);
  not shown: lines <A>-<B>`, and the contract tells the agent to open such a file with its file tools
- **AND** the ledger has, right after `prompt.rendered`, `prompt.truncated{role: red, task: "1", attempt: 1,
  budget_tokens: 24000}` whose one source is `{path: ".kiro/specs/tip-calc/design.md", kind: design, reason: budget,
  total_chars: 125492, readable: true}`

#### Scenario: SCN-IMP-286 (−) An oversized or linked source is named, never dropped
- **GIVEN** a Kiro unit whose `design.md` has 300,000 bytes and whose `requirements.md` is a symbolic link
- **WHEN** its red prompt is rendered
- **THEN** the unit context shows the first part of the 262,144 bytes read from `design.md`, and `# Not shown in full`
  names `design.md` with the reason `oversize` (`262144 of 300000 bytes read`) and `requirements.md` with the reason
  `symlink` (`not read`), and `prompt.truncated` lists both with `readable: false` for the link
- **AND** the probe unit with its short design gets no `# Not shown in full` section and no `prompt.truncated`

### Requirement: L4-IMP-053 The context budget and how to raise it
The context budget SHALL be `implementer.context_budget_tokens` (default 24000) tokens of 4 characters, unless the
selected profile sets `context_budget_tokens`, which SHALL then hold for that profile's steps. No model window SHALL be
guessed. `prompt.rendered` SHALL record `budget_tokens` and `budget_source` (`implementer` or `profile:<name>`).

#### Scenario: SCN-IMP-287 (+) A raised budget shows the whole design, and a profile's own budget wins
- **GIVEN** the probe unit of SCN-IMP-281, first with `implementer.context_budget_tokens: 40000`, then with the
  default and a selected profile `local` that sets `context_budget_tokens: 4000`
- **WHEN** the red prompt of task 1 is rendered in each case
- **THEN** with 40000, `design.md` is whole, nothing is cut, and `prompt.rendered` has `budget_tokens: 40000,
  budget_source: implementer`
- **AND** with the profile, `tech.md` and `requirements.md` are whole, `design.md` is cut, and `prompt.rendered` has
  `budget_tokens: 4000, budget_source: "profile:local"`

### Requirement: L4-IMP-054 A person sees the cuts before and after a run
`l4 run --dry-run` SHALL print, for each unit whose prompt it renders, the budget and its key, each steering decision,
and each cut source with its path and the characters shown and in total. `l4 status --unit U` SHALL print the unit's
last implementer `prompt.truncated`, and doctor SPEC-004 SHALL warn about each unit whose next task's prompt would cut
a source, naming the file and the key to raise.

#### Scenario: SCN-IMP-288 (+) The dry run shows the cut before a run
- **GIVEN** the probe repository with the 125,492-character design
- **WHEN** `l4 run --dry-run` runs
- **THEN** under `kiro:tip-calc` it prints `context: budget 24000 tokens (implementer.context_budget_tokens)`,
  `steering: .kiro/steering/tech.md included (always)` and `cut: .kiro/specs/tip-calc/design.md <shown> of 125492
  characters shown (budget)`
- **AND** with the short design it prints `context: budget 24000 tokens (implementer.context_budget_tokens), nothing
  cut` and no `cut:` line

#### Scenario: SCN-IMP-289 (+) Status and doctor name the cut
- **GIVEN** a unit whose ledger ends with the `prompt.truncated` of SCN-IMP-285, and the probe repository with the
  long design
- **WHEN** `l4 status --unit kiro:tip-calc` and `l4 doctor --adoption --no-gates` run
- **THEN** the status prints `Prompt cut: task 1 red attempt 1: .kiro/specs/tip-calc/design.md <shown> of 125492
  characters (raise implementer.context_budget_tokens or shorten the file)`, and `--json` carries `prompt_cut`
- **AND** doctor's SPEC-004 warns `kiro:tip-calc task 1: design.md <shown> of 125492 characters shown` with the fix
  `shorten the file, or raise implementer.context_budget_tokens`
