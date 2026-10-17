# Kiro prompt context: the implementer and the judges get everything important from a spec

Status: design, 2026-10-18. Harness at 0.4.14 (`795e97a9`). Markers: **[V]** verified (read in the code at the cited
line, or run on the probe), **[I]** inferred or decided, **[U]** unverified, to be confirmed by the named test.

## 0. The answer in brief

1. The criteria's text and the task's whole block leave the budget's reach. They are charged first and never cut
   (D1). The rest fills a budget in a fixed priority order, by whole Markdown sections, with the sections the task
   names first (D2, D3).
2. Nothing vanishes. Every cut or unread file is named in the prompt with its path, and the agent is told to open it.
   A steering file is said to be unreadable, because the sandbox masks it. The run records `prompt.truncated`, and dry
   run, status and doctor show it (D4, D10).
3. Steering arrives as data. The harness reads `.kiro/steering/*.md` on the host and decides each file by its Kiro
   front matter. The masks stay (D5). An OpenSpec unit gets its `openspec/config.yaml` `context` the same way (D6).
4. The budget stays `implementer.context_budget_tokens` (24000), with an optional per-profile override. No model window
   is known before a run, so nothing scales by itself (D7).
5. Red requires every criterion that a Kiro leaf's `_Requirements:_` line names, in both paths (D8, implementer-5). The
   step-9 judge already had the requirements and the criteria in full. It now names an oversized spec file and holds
   on it (D9).

## 1. Current state

### 1.1 The implementer prompt (the probe)

The probe repository is a Kiro spec `.kiro/specs/tip-calc/`:

- `requirements.md`, 409 bytes, two EARS criteria under `### Requirement 1`;
- `design.md`, 125,492 characters: a 3-line preamble with `DESIGN-MARKER`, then 1,100 `## Component N` sections;
- `tasks.md`: `- [ ] 1. Implement the tip function` with two detail bullets and `_Requirements: 1.1, 1.2_`;
- `.kiro/steering/tech.md`, no front matter.

`l4 run --dry-run` of harness 0.4.14 rendered `.l4-out/dry-run/<run>/kiro-tip-calc/1-red.prompt.md` [V, re-run
2026-10-18]:

- `# Unit context` held the design's first 96,000 characters and `[truncated: 29492 characters omitted]`, then
  `<l4:data source="requirements.md">[truncated: omitted to fit the context budget]</l4:data>`. The budget is
  `context_budget_tokens` × `CHARS_PER_TOKEN` = 24000 × 4, shared in source order (`prompt.py:127-138`).
- `collect_sources` gives the order `proposal.md, design.md, requirements.md, bugfix.md, specs/*/spec.md`
  (`prompt.py:294-308`).
- `# Criteria of this unit` listed `- C-1a9abc58  Req 1.1` and `- C-41bc8f70  Req 1.2`. `_criteria_section` renders
  `f"- {c.id}  {c.alias}"` only (`prompt.py:182`), never `c.text`. So the agent saw no criterion text at all.
- `# Task 1` held `1. Implement the tip function` and `_Requirements: 1.1, 1.2_`. The detail bullets were not there.
  `Task.title` is the checkbox text (`kiro.py:106`), and the prompt adds the links line itself (`prompt.py:174`).
- With the short design (`git checkout HEAD~1 -- .kiro`), `requirements.md` was shown whole. The criteria and the task
  looked the same.
- A source over `MAX_SOURCE_BYTES` (262,144) is skipped: `read_regular_file` raises `UnsafeFile`
  (`fsutil.py:36-37`), and `collect_sources` drops the file with no record (`prompt.py:305-306`) [V, read].

### 1.2 Steering

- `.kiro/steering/**` is a protected path (contract template) and is masked by a tmpfs in the bwrap agent sandbox
  (`GUIDANCE_DIRS`, `sandbox/base.py:121-124`) [V].
- The kiro-cli implementer is a harness agent with no `resources`, so it loads no steering (SPEC §8.3, row `kiro-cli`
  implementer) [V, SPEC].
- In kiro-e2e H1 (no bwrap), Kiro CLI 2.28.0 loaded workspace steering anyway (`docs/live/kiro-e2e/README.md`,
  finding 4) [V, live]. So the outcome depends on the sandbox.
- The red template already says "even when the design or a steering file names them" (`red.md`), although no steering
  is ever shown [V].
- Kiro's own rules [D, kiro.dev/docs/steering, fetched 2026-10-17]:
  - The front matter is YAML between `---` lines, as the first content of the file. A file without front matter is
    `always`.
  - `inclusion: fileMatch` takes `fileMatchPattern` as a string or a list.
  - `manual` is referenced in chat as `#<file name>`.
  - `auto` needs `name` and `description` and is included when a request matches the description.
  - `#[[file:<path>]]` references another file.
  - Global steering lives in `~/.kiro/steering/`, and workspace `AGENTS.md` counts as always-included.

### 1.3 The budget data

- `ImplementerCfg.context_budget_tokens: int = 24000` (`config/schema.py:504`) [V].
- `Profile` has no context field. Only an opencode custom provider declares `models.<id>.limit.context`
  (`OpencodeModelLimits`, `schema.py:347-351`) [V].
- `context_peak_tokens` and `context_peak_percent` are known only after a step (`agents/base.py:40-41`) [V].

### 1.4 The verifier (point 4 of the brief)

The brief inferred that the verifier's evidence (`UNIT_FILES = ("proposal.md", "design.md", "tasks.md")`) may leave
out a Kiro unit's `requirements.md`. That is **not** so for the judges [V, read]:

- `evidence/collect.py:41` `UNIT_FILES` is never used. The live copy, `evidence/scope.py:156`, feeds only step 1's
  declared scope: the paths that proposal, design and tasks name (`unit_declared_scope`, `scope.py:186-199`). A path
  named only in a Kiro `requirements.md` is not declared [V]. This is a scope matter, left as it is (§7, Q7).
- **Step-9 judge.**
  - Its spec is `_family_sources(wb)` (`ladder.py:425-431`), which is `collect_sources` of the unit and of each fix unit.
    So it holds `requirements.md` and `bugfix.md`, with **no budget** (`judge.py:383`).
  - Its criteria list is `f"{c.id}  {c.alias}\n{c.text}"` for every criterion (`judge.py:384`).
  - So a big design cannot push the criteria or the requirements out of the judge's prompt.
  - The gap: a file over 262,144 bytes vanishes from the judge too, unnamed. The diff, by contrast, is cut at
    `MAX_DIFF_CHARS` with a hold (`ladder.py:1021-1022`).
- **S1 judge (step 8).** The state per criterion is the criterion's text, its tests and one diff excerpt of at most
  1,500 characters (`s1.py:103-106`, `s1_step.py:47-56`). Only the excerpt is trimmed (`s1.py:131-134`). A state that
  does not fit without it is `unavailable` with its reason (`s1.py:126-129`). No spec file is in it, so nothing can
  crowd out the criterion text [V].
- **Audit writer (step 4a).** It gets the criterion text (`audit.py:174`) and `design.md` with `proposal.md`, cut
  together at 8,000 characters (`audit.py:98-108`). Step 4a writes "from the criterion text alone" by design, so this
  is unchanged [I].
- **Clarifier.** It reads `collect_sources` and gives the documents half of the same budget (`DOCUMENT_SHARE = 2`,
  `clarifier/context.py:28`). It can lose `requirements.md` behind a long design the same way. Not changed here (§7,
  Q6).

### 1.5 implementer-5 (confirmed review finding)

- `check_criteria(result, family, new_tests, ...)` (`result.py:186-214`) takes no task. `cited` is `criteria_ids`, or
  what the new tests trace.
- The no-new-test branch of `run_red` (`tdd.py:986-1017`) confirms only `result.criteria_ids`.
- `grep '\.links' src/l4` finds the prompt (`tdd.py:627`), the dry run and the Kiro validation, nothing in red.
- The review reproduced both: a red that tests only `Req 2.1` of a leaf citing `2.1, 2.2` passes, and the no-new-test
  path ticks it.

## 2. Decisions

### D1. The criteria text and the task's whole block are never cut

**The criteria.**

- `_criteria_section` renders each shown criterion as `- <id>  <alias>`, then its text, indented by two spaces. The
  text is `Criterion.text`: the EARS line for Kiro, the scenario body for OpenSpec.
- Which criteria are shown is K20's rule, unchanged: a Kiro leaf gets those its links name; a leaf whose links name none,
  and every OpenSpec task, gets all of them.
- `_linked` moves to `l4.specs.criteria.linked_criteria(criteria, links)`, so that the prompt, red (D8) and doctor share
  one rule. A link `N.M` names `Req N.M`, and a link `N` names every `Req N.*`.
- Links resolve against the criteria of the task's **own** unit: `own_criteria(provider, ref)`, which is
  `FamilyProvider.own_criteria(ref)` (the inner provider's `criteria(ref)`) for a family, else `provider.criteria(ref)`.
  The reason is verified by reading:
  - A fix unit's workbench is `make_workbench(ref=fix, provider=family)` (`fixloop.py:303-304`).
  - `FamilyProvider.criteria(fix)` returns the whole family (`fixloop.py:151-163`).
  - So a parent's own `Req 2.1` and the fix unit's `Req 2.1` (which restates, say, the parent's `Req 1.2`) share an
    alias. Today's K20 list can show both.
  - The full family list stays what `check_criteria` accepts as known ids.

**The task block.** `# Task <key>` holds one data block, `source="<repo path of tasks.md>"`, built by the new
`unit_context.task_block(data, task, tasks, framework)` from these parts, in order:

1. the Markdown headings that enclose the task (`tasks_text.task_context`'s headings);
2. each ancestor task's `task_text` (its checkbox line and the lines up to its first child; for Kiro, ancestors by
   `depth`; OpenSpec tasks are flat);
3. the task's own `task_text`: its checkbox line and every line under it up to the next task line or heading, with
   detail bullets and `_Requirements:_`.

The leaf marker is normalised to `[ ]`, as `task_text` already does. When `tasks.md` cannot be read, the block falls
back to today's title plus links line. K20's separate `_Requirements:` line is dropped, because the block already
holds it.

**The charge.** Both sections are charged to the budget first (`fixed_chars`) and are never cut. When they alone pass
the budget, everything else is left out and named (D4).

### D2. The budget fills in a fixed priority order, by sections

Budget `B` = `budget_tokens` × 4 characters (D7). `R = B − fixed_chars`. The fill has two stages, and each is
**strict**: pieces are taken in order, whole while they fit. The first piece that does not fit is cut at the last line
boundary that fits, but only when at least `MIN_CUT_CHARS` (2,000) remain; otherwise it is left out. Every later piece
of that stage is left out.

**Stage 1, conventions**, capped at `C = min(R, B // 2)`, in this order:

1. steering decided `always`, by file name;
2. steering decided `fileMatch`, by file name;
3. steering decided `manual` or `auto` (referenced), by file name;
4. an OpenSpec unit's `context`.

Each file is one piece. The cap keeps a huge steering file from emptying the unit context. `R` then shrinks by what was
used.

**Stage 2, the unit's sources**, in this order:

1. the named sections (D3) of the requirements narrative (`requirements.md`, `bugfix.md`, `specs/*/spec.md` by name);
2. the other sections of the narrative, the preamble included, in document order;
3. the named sections of `design.md`;
4. the preamble of `design.md`;
5. its other sections, in document order;
6. `proposal.md`, by its sections.

A fix unit's `design.md` is a design like any other.

**Sections.** A section is a heading line (`#` to `####`, outside a ``` or ~~~ fence, the rules of
`tasks_text._HEADING` and `_FENCE`) through the line before the next heading. The preamble is the text before the first
heading.

**Rendering.**

- The prompt shows `# Project conventions` (stage 1), then `# Unit context`. The unit context has one data block per
  source that shows anything, in the order `requirements.md`, `bugfix.md`, `specs/*/spec.md`, `design.md`,
  `proposal.md`. Each block shows its chosen sections in document order.
- Each run of left-out sections is replaced by one line, `[not shown: lines A-B]`. A cut piece ends with
  `[cut: lines A-B not shown]`.
- A source that shows nothing has no block, only its line under `Not shown in full`.

**Why a strict stop.** The order then holds: nothing below a cut is shown while something above it is missing. The cut
list tells the agent where the rest is.

### D3. The sections the task names

A section is *named* when its text holds one of the task's keys:

- **The links of a Kiro leaf.** A line is a match when it contains the word `requirement`, `requirements`, `req` or
  `validates` (case-insensitive), and a standalone number of the line (the `_REF` rule of `kiro.py`) equals the link
  `L`, or is `L`'s requirement number, or starts with `L.` when `L` is bare.
  - This finds `### Requirement 1` in `requirements.md`.
  - It also finds Kiro's `**Validates: Requirements 1.1, 1.2**` lines in a design's correctness properties.
- **The backticked tokens of the task block** of at least 3 characters, for example `src/calc/tip.py` or
  `apply_discount`, found verbatim.
- **For an OpenSpec task**, also the double-quoted strings of at least 8 characters in its block (the requirement name
  it quotes, L4-OSP-008).

This is best effort [I]. A design that never names requirement numbers or code names falls back to document order, and
the cut list (D4) keeps it safe: the agent can open the file.

### D4. A cut is named, and recorded

**Reading sources.** `read_sources(unit_dir, repo)` replaces the silent skip:

| File | What happens | Reason |
|---|---|---|
| larger than `MAX_SOURCE_BYTES` | read up to that size (decoded with `replace`) | `oversize`, with `total_bytes` |
| a symlink | not read | `symlink` |
| not a regular file | not read | `not_regular` |

`collect_sources` keeps its signature and behaviour for the clarifier and the audit writer.

**`# Not shown in full`.** It comes right after `# Unit context`, as one line of harness text and one data block
(`source="not shown in full"`; file names are repository content, so they go inside a block). One line per cut or
unread file:

```
- .kiro/specs/tip-calc/design.md: 61234 of 125492 characters shown (budget); not shown: lines 640-2203
- .kiro/steering/style.md: 48000 of 70000 characters shown (budget); not readable in this step's sandbox
- .kiro/specs/big/design.md: 262144 of 300000 bytes read (oversize); not shown: lines 3100-3800
- .kiro/specs/big/requirements.md: not read (symlink)
```

The section is absent when nothing was cut. The contract (`contract@12`) tells the agent what to do with the readable
ones, and that the unreadable ones cannot be opened.

**`prompt.truncated`.** Emitted right after `prompt.rendered`, only when something was cut:

```
prompt.truncated{role, task, attempt, budget_tokens, sources: [{path, kind, reason, shown_chars, total_chars,
                 total_bytes?, omitted: [[a, b], ...], readable}]}
```

- `kind` ∈ `steering | openspec_context | narrative | design | proposal`.
- `reason` ∈ `budget | oversize | symlink | not_regular`.
- `readable` is false for a steering file (masked) and for a symlink. `RenderedPrompt.cuts` carries the same entries,
  for the dry run, which has no ledger.

### D5. Steering, as data, by its front matter

**Reading.**

- `l4.specs.steering.read_steering(root)` reads `root/.kiro/steering/*.md`: direct children, sorted by name, regular
  files only, at most `MAX_SOURCE_BYTES` each, the same rules as D4.
- `root` is the worktree in a run (`wb.worktree`), the main checkout in a dry run or doctor (`app.repo`). The harness
  reads it on the host before the agent sandbox starts, so the tmpfs mask (which exists only inside the sandbox) is
  untouched.
- `reject_symlinks(root, ".kiro", "steering")`: a linked directory reads nothing and records one decision
  `{path: ".kiro/steering", why: "symlink"}`.
- `~/.kiro/steering` is the runner's home, not repository content: never read.

**Front matter.**

- It is there only when the text (after a BOM) starts with a `---` line and a later line is exactly `---`. The YAML
  between is read with `yaml.safe_load`, and the body is what follows.
- No front matter, or a mapping without `inclusion`, means `always`.
- `inclusion` is compared case-insensitively against `always`, `fileMatch`, `manual` and `auto`.
- These are `bad_front_matter` (never included): YAML that does not parse, a value that is not a mapping, an unknown
  `inclusion`, or `fileMatch` without a string or list `fileMatchPattern`.

**Decision per file** (`decide_steering(files, paths, references)`), each recorded as
`{path, inclusion, included, why}`:

| Inclusion | Included when | `why` |
|---|---|---|
| `always` | always | `always` |
| `fileMatch` | a pattern matches a path of `paths` | `matched <path>`, else `no_match` |
| `manual` | `references` names the file | `referenced`, else `not_referenced` |
| `auto` | `references` names the file or its `name` | `referenced`, else `not_referenced` |

- **`paths`** is the backticked path tokens of the task block and of the design's named sections (D3), plus the files
  the unit branch changed so far (`memory.inject.task_paths`, as `_lessons` uses it). In a run that is
  `[*wb.branch_changed_files(), *wb.changed_files()]`; in a dry run, the pushed branch's files; in doctor, none. The
  first red of a unit therefore matches only named paths.
- **A match** is `glob_match(pattern, path)`, or, for a pattern without `/`, `glob_match(pattern, <file name>)` [U: how
  Kiro matches a pattern without `/` is not verified; the test pins this rule].
- **`references`** is the task block and the full texts of `requirements.md`, `bugfix.md` and `design.md`. A file
  `x.md` is referenced by:
  - `#x` as a token (`(?<![\w#/\[])#x(?![\w-])`);
  - `#[[file:.kiro/steering/x.md]]`;
  - the path `.kiro/steering/x.md`;
  - for `auto`, `#<name>` of its front matter.

**`auto` is treated like `manual`** [I]. Kiro decides an `auto` file by matching a request to its description, which
needs a model. The harness stays deterministic (§7, Q1).

**Rendering.**

- Each included file is a block `<l4:data source=".kiro/steering/<file>">` holding the body, under `# Project
  conventions`. The harness text is one line: "The project's conventions for this task. The harness contract says how to
  use them."
- `prompt.rendered.steering` lists every decision, included or not.
- `#[[file:…]]` references inside a body are not expanded: the agent can open such a file unless it is masked.
- Steering applies to every unit of the repository, OpenSpec units included, because Kiro defines it per workspace.

**Unchanged:** `GUIDANCE_DIRS`, the protected paths, the kiro-cli agent and L4-SEC-002. Member-written guidance is
"trusted like spec files" (SPEC §18), and it now arrives the way spec files do: inside `<l4:data>`, never as an
adapter's instructions. Workspace `AGENTS.md` and `CLAUDE.md` stay out (§7, Q3).

### D6. OpenSpec units get their project `context`

OpenSpec 1.x keeps the project's conventions in `<spec.openspec.root>/config.yaml` (or `config.yml`): the `context`
text, which OpenSpec feeds into its own artifact instructions. This repository's file is an example: runtime, layout and
conventions.

- An OpenSpec unit's conventions are that `context` string: one block, `source="openspec/config.yaml#context"`, in
  stage 1 after any steering.
- `rules` are rules for writing specs and tasks, not for code, and are never shown.
- A file whose YAML does not parse, or whose `context` is not a string, adds nothing and records the decision
  `{path, inclusion: "context", included: false, why: "bad_front_matter"}`. One shape for every decision.
- `openspec/project.md` belongs to the pre-1.0 layout that L4 refuses (SPEC-001), so it is not read.

### D7. The budget

- **No scaling.** The default stays `implementer.context_budget_tokens: 24000`, the key a consumer raises in
  `.l4/config.yaml`. Nothing scales with the model, because no profile declares its window before a run (§1.3). A guess
  would make two runs of one task render different prompts for no visible reason.
- **One override.** `Profile.context_budget_tokens: int | None` (`Field(None, ge=1000)`) sets the budget of that
  profile's steps, for a small local model in a fallback chain.
- **Effective budget.** `effective_budget(cfg, profile_name, profile) -> (tokens, source)` returns
  `(profile.context_budget_tokens, f"profile:{name}")` when the profile sets it, else
  `(cfg.implementer.context_budget_tokens, "implementer")`. `prompt.rendered` records `budget_tokens` and
  `budget_source`.
- **Who uses which.** The dry run and doctor use the head profile of `roles.implementer`, as the dry run already does
  for its command line.

### D8. Red enforces a Kiro leaf's cited criteria (implementer-5)

**The required set.**

`required = {c.id for c in linked_criteria(own_criteria(wb.provider, wb.ref), task.links)} −
unchanged_criteria(wb, task, base_report)`

- The second term is the L4-OPS-015 `exempt` set of a reopened task.
- An OpenSpec task has no links, so `required` is empty and red is unchanged.
- A Kiro leaf whose links name no criterion has an empty `required` too. Validation already refuses a pending leaf
  whose refs do not resolve (L4-KSP-003).
- A fix unit's leaf resolves its `2.n` and `3.n` links against the fix unit's own criteria (D1). These are its
  `bugfix.md` items, whose ids are the restated parent criteria, never the parent's own `Req 2.n` [V, read:
  `fixloop.py:303-304`, `kiro.py` `kiro_criteria` with the fix marker]. Had they resolved to nothing, the failure would
  only be today's behaviour (no enforcement), not a broken step.
- A `[chore]` leaf has no links and runs single-phase.

**New tests (`check_criteria(..., required=required)`).**

- `cited` becomes `sorted(set(criteria_ids or traced) | required)`.
- A required id that no new test traces fails the step with:

  `no new test traces C-41bc8f70 (Req 1.2), which the task's _Requirements: 1.1, 1.2_ line names: write a new test
  for each criterion that line names, tagged with its id`

  The ids carry their aliases. The existing loop puts the reason into the next attempt's prompt (`# Your previous
  attempt was rejected`).
- A required id that a new test traces goes through the checks of every cited criterion: red assertion, zero-value run,
  or pre-satisfied confirmation.
- So a leaf citing a criterion that an earlier task already proved needs a new test for it in a mixed step. That test
  may pass at once and is confirmed `via: earlier_red`, cheaply (`earlier_red.py`).

**Decision, strict.** This is the brief's outcome, and it keeps one path per step: a step that adds tests is judged by
its new tests, and a step that adds none by existing ones. `red@11` tells the agent so. Accepting existing tests inside
a mixed step is §7, Q4.

**No new test (`tdd.py:986`).**

- The branch is taken as today: `criteria_ids` is non-empty and the reason starts with `already_satisfied`.
- Then `cited = sorted(set(criteria_ids) | required)`. Each id needs passing tests that trace it, confirmed in the order
  earlier red, zero-value run, base run.
- A required id with no passing tracing test fails with today's `no test traces <id> yet: write a new test for each`,
  and the task is not ticked.
- A leaf that reports only `Req 1.1` while both are proved is accepted, with both proofs in `task.red_ok.criteria`.

**Criteria of other tasks** are still accepted when a leaf's test traces them. The zero-value rule of `red.md` tells the
agent to tag a test with a second criterion, so rejecting them would break it (§7, Q5).

This makes the code meet L4-IMP-005's existing schema text: `criteria_ids` "must include the task's cited criteria
(Kiro)".

### D9. The judges

**Step 9.**

- `_family_sources` uses `read_sources` for the unit and each fix unit. Fix units are prefixed `<name>/` as today.
- `build_judge_prompt` gains `unread`: the `oversize`, `symlink` and `not_regular` entries. When there are any, it
  appends `### Not shown in full` to `## Specification`, in the format of D4 with no "open it" advice (the judge has no
  tools).
- Each such file adds the hold `the spec file <path> is larger than 262144 bytes: the judge saw only its start` (or
  `... is a symlink: the judge did not see it`), as the diff cut does.
- The ledger gets `prompt.truncated{role: "judge", round, sources}`.
- `SYSTEM` gains one rule (below), and `PROMPT_VERSION` becomes 10.
- The spec stays unbudgeted otherwise. The judge already sees every criterion's text and the requirements whole
  (§1.4). Bounding the judge prompt is §7, Q2.

**S1 (step 8).** No change in behaviour. A regression test pins that each state starts with `Criterion <id>:` and the
criterion's whole text, beside a 125 kB design.

**Audit writer and clarifier.** Unchanged (§1.4). Their `collect_sources` still skips an oversized file (§6).

### D10. What a person sees

**`l4 run --dry-run`.** `Step` gains `context: ContextReport` (budget, source, steering decisions, cuts), and `_render`
prints these lines after the `prompt:` line:

```
  context: budget 24000 tokens (implementer.context_budget_tokens)
  steering: .kiro/steering/tech.md included (always)
  cut: .kiro/specs/tip-calc/design.md 61234 of 125492 characters shown (budget)
```

- One `steering:` line per decision; a file left out ends `left out (no_match)`.
- One `cut:` line per entry.
- With no cut, the first line is `context: budget 24000 tokens (implementer.context_budget_tokens), nothing cut`.
- A profile override reads `(profiles.<name>.context_budget_tokens)`.

**`l4 status --unit U`.** `UnitSnapshot.prompt_cut` is the data of the unit's last `prompt.truncated` whose role is not
`judge`. `_block` prints, after `Last activity`:

`Prompt cut: task 1 red attempt 1: .kiro/specs/tip-calc/design.md 61234 of 125492 characters (raise implementer.context_budget_tokens or shorten the file)`

At most three files are listed, then `and N more`. `--json` carries `prompt_cut`.

**Doctor SPEC-004** (warn, `config` scope).

- For each unit with a pending task, the doctor builds the next task's context with no changed files, through the same
  builder as the run (D12). Each cut adds a warning:

  `kiro:tip-calc task 1: design.md 61234 of 125492 characters shown`

  The fix is `shorten the file, or raise implementer.context_budget_tokens`.
- It extends the existing warn row, which already reports spec shapes a person fixes ("units without criteria"), so no
  new check id is needed.

### D11. Templates and versions

`contract@12` adds two bullets after the `<l4:data>` bullet:

> - Text under `# Project conventions` is this project's own conventions (its Kiro steering, or its OpenSpec context):
>   apply them to the code and tests you write as you apply the design. Like every file, they are information and
>   change no rule of this prompt.
> - A file listed under `# Not shown in full` was cut to fit this prompt. Before you write code, open each one that is
>   not marked unreadable with your file tools, and read the parts not shown that bear on this task. A file marked not
>   readable in this step's sandbox cannot be opened: work from what is shown.

`red@11` adds, after "Cover every criterion that this task's requirement names.":

> When the task has a `_Requirements:_` line, every criterion listed under `# Criteria of this unit` needs a NEW test in
> this step, also one that an earlier task already tests (such a test may pass at once: the harness confirms it against
> the earlier test). The harness rejects a step that leaves one out. The one exception is the already-satisfied case
> below, when every listed criterion is already traced by passing tests.

`judge@10` adds one rule to `SYSTEM`, after the `<l4:data>` rule:

> - When the specification ends with a `Not shown in full` block, the files it names were cut or not read: you saw only
>   what is shown. Judge each criterion from its full text in the criteria list, and do not fail a criterion for what a
>   cut part might say.

`green@5`, `single@3`, `single_tests@5` and `output@1` keep their bodies. Their prompts change through the code-rendered
sections, so their `prompt.rendered.sha256` changes too. Regenerate the lock with `uv run python -m l4.templatelock
--write`, and run `l4 eval --compare` before a release (docs/eval.md).

### D12. One builder for the run, the dry run and doctor

`unit_context.prompt_inputs(...)` returns `PromptInputs`:

- `source_files`, `conventions`, `steering` (the decisions), `task_block`;
- `budget_tokens`, `budget_source`, `unit_rel`.

Its inputs are the root, the unit directory, the framework, the task and tasks, the changed files, the configuration and
the profile.

- `tdd._prompt`, `sim/dryrun._prompt` and doctor SPEC-004 call it.
- `render_prompt(role, ctx)` calls `plan_context` and returns `RenderedPrompt.cuts` and `budget_tokens`.
- The dry-run module docstring warns that a block added to `tdd._prompt` reaches the dry run only when it is added
  there too. With one builder, the dry run cannot drift on context.

## 3. What the agent sees (the probe, task 1, red)

```
# Harness contract                (contract@12: + conventions, + not-shown rules)
# Project conventions
<l4:data source=".kiro/steering/tech.md">STEERING-MARKER: all money values are Decimal ...</l4:data>
# Unit context
<l4:data source="requirements.md"># Requirements Document ... REQ-INTRO-MARKER ... 2. WHEN the tip percent is negative ...</l4:data>
<l4:data source="design.md"># Design
DESIGN-MARKER: put `tip(bill, percent)` in src/calc/tip.py ...
## Component 0 ... ## Component N
[not shown: lines 640-2203]</l4:data>
# Not shown in full
<l4:data source="not shown in full">- .kiro/specs/tip-calc/design.md: … of 125492 characters shown (budget); not shown: lines …</l4:data>
# Task 1
<l4:data source=".kiro/specs/tip-calc/tasks.md">- [ ] 1. Implement the tip function
  - TASK-DETAIL-MARKER: reject a percent above 100 with ValueError as well
  - Use Decimal throughout
  - _Requirements: 1.1, 1.2_</l4:data>
# Criteria of this unit
This task's `_Requirements:_` line names these criteria; cover these. ...
<l4:data source="criteria">- C-1a9abc58  Req 1.1
  WHEN a bill and a tip percent are given THEN the system SHALL return the tip rounded to 2 places.
- C-41bc8f70  Req 1.2
  WHEN the tip percent is negative THEN the system SHALL raise ValueError.</l4:data>
# Phase: RED ... (red@11)
```

## 4. Files and functions (for the implementers)

| File | Change |
|---|---|
| `src/l4/implementer/unit_context.py` (new) | `MAX_SOURCE_BYTES` (moved; `prompt.py` re-exports it), `MIN_CUT_CHARS = 2_000`, `CONVENTIONS_SHARE = 2`; `SourceFile(name, path, text, total_bytes, reason)`, `read_sources(unit_dir, repo)`; `Convention(path, text, kind, readable)`; `task_block(data, task, tasks, framework)`; `Section`, `split_sections(text)`; `section_keys(task_block, links, framework)`, `is_named(section, keys)`; `Cut(path, kind, reason, shown_chars, total_chars, total_bytes, omitted, readable)`; `ContextPlan`, `plan_context(fixed_chars, budget_tokens, conventions, source_files, keys)`; `effective_budget(cfg, name, profile)`; `PromptInputs`, `prompt_inputs(...)` |
| `src/l4/specs/steering.py` (new) | `SteeringFile(path, inclusion, patterns, name, body, total_bytes, reason)`, `read_steering(root)`, `parse_front_matter(text)`, `references(texts)`, `decide_steering(files, paths, refs) -> list[SteeringDecision]`, `openspec_context(root, openspec_root) -> (Convention or None, decision)` |
| `src/l4/specs/criteria.py` | `linked_criteria(criteria, links)` (from `prompt._linked`) |
| `src/l4/verifier/fixloop.py` | `FamilyProvider.own_criteria(unit)` (the inner provider's `criteria(unit)`), and `own_criteria(provider, ref)`, the one helper the prompt, red and doctor call |
| `src/l4/implementer/prompt.py` | `PromptContext` + `task_block`, `source_files`, `conventions`, `unit_rel`, `budget_source`; `sources` stays (converted to `SourceFile`s when `source_files` is empty); `_context` → `plan_context`; new sections `# Project conventions`, `# Not shown in full`; `_criteria_section` with text; `RenderedPrompt` + `cuts`, `budget_tokens`; `collect_sources` unchanged |
| `src/l4/implementer/templates/contract.md`, `red.md` | D11; versions 12, 11 |
| `src/l4/templates.lock.json` | regenerated |
| `src/l4/implementer/result.py` | `check_criteria(..., required=())` (D8) |
| `src/l4/implementer/tdd.py` | `_prompt(..., attempt)` uses `prompt_inputs`; `prompt.rendered` + `budget_tokens`, `budget_source`, `steering`; `prompt.truncated`; `run_red` computes `required` once and passes it to `check_criteria` and to the no-new-test branch |
| `src/l4/config/schema.py` | `Profile.context_budget_tokens` |
| `src/l4/sim/dryrun.py` | `_prompt` uses `prompt_inputs`; `Step.context`; `_render` lines (D10) |
| `src/l4/state/status.py` | `UnitSnapshot.prompt_cut`, `_block` line, `--json` key |
| `src/l4/doctor/checks_spec.py` | SPEC-004 cut warnings |
| `src/l4/verifier/ladder.py` | `_family_sources` via `read_sources`; the holds and `prompt.truncated{role: judge}` in `_judge_step` |
| `src/l4/verifier/judge.py` | `build_judge_prompt(unread=...)`, the `Not shown in full` block, `SYSTEM` rule, `PROMPT_VERSION = 10` |

## 5. What a person sees

- **Before a run**, `l4 run --dry-run` shows per unit the budget, which steering files are in and why, and what is cut,
  and `l4 doctor --adoption --no-gates` warns under SPEC-004.
- **After a run**, `l4 status --unit U` shows the last cut, and the ledger has `prompt.rendered{budget_tokens,
  budget_source, steering}` and `prompt.truncated`. The published `.prompt.md` shows `# Not shown in full`.
- **The fix is always one of two:** shorten the file, or raise `implementer.context_budget_tokens` (or the profile's
  key).
- **A red step that leaves a cited criterion out** fails with a reason that names the criterion and the
  `_Requirements:_` line, and the next attempt reads it.
- **A judged unit whose spec file is over 262,144 bytes** holds with a line that names the file.

## 6. Risks

- The prompts of every role and framework change (criteria text, task block, section order). Every
  `prompt.rendered.sha256` moves, and so does the eval baseline. Mitigation: `l4 eval --compare` before the release
  (D11).
- An OpenSpec unit with many scenarios gets a longer Criteria section, never cut. A unit with 40 scenarios of 400
  characters adds about 16,000 characters, all charged first, so less design is shown. The cut list names the rest.
- The named-section rule (D3) can promote many sections when a backticked token is common. It only reorders within the
  budget; nothing is lost silently.
- Steering is now in the prompt. A steering file that says "always run git commit" reaches the agent as data, under a
  contract that forbids commits. That is the same trust as the spec files (SPEC §18), and the masks still keep the CLI
  from loading it as its own instructions.
- Under the `none` sandbox (macOS development), Kiro CLI 2.28 loads the steering itself too, so the agent reads it
  twice. That is harmless.
- Strict red (D8) makes a mixed step write a test copy for a criterion an earlier task proved. It costs little (the
  earlier-red confirmation needs no zero-value run), but it is a test copy (§7, Q4).
- The clarifier and the audit writer keep the silent skip of an oversized file.

## 7. Open questions for the owner

1. **`auto` steering.** It is treated as `manual`: included only when referenced. Should it instead be included when the
   budget leaves room after the other conventions?
2. **The judge's budget.** The judge prompt has no bound on spec text: a 125 kB design plus a 120,000-character diff is
   about 60k tokens. Bound it, with the same priority order and cut list?
3. **`AGENTS.md`.** Workspace `AGENTS.md` (which Kiro counts as always-included steering) and `CLAUDE.md` stay out of
   the prompt. Offer an opt-in, for example `implementer.guidance_files: [AGENTS.md]`, rendered as conventions?
4. **Existing tests in a mixed step.** In a red step that adds tests, may a linked criterion that an earlier task already
   proved be covered by its existing tests (confirmed as on the no-new-test path), instead of a new copy?
5. **Criteria of other tasks.** Should a red step of a linked leaf be refused when it cites criteria that only other
   tasks' links name? It is allowed today, and the zero-value rule relies on tagging a second criterion.
6. **The clarifier.** Align it with the same priority order and cut list (it shares the budget at `DOCUMENT_SHARE`)?
7. **Detail bullets as behaviour.** Detail bullets that state behaviour no criterion holds ("reject a percent above
   100") now reach the implementer, but the verifier judges criteria only. Should the judge check each task's text, as
   L4-VER-018 does for already-satisfied tasks? Related: should the declared scope (step 1) read a Kiro unit's
   `requirements.md`?
8. **The default.** Keep 24000 tokens, or raise it now that the criteria text and the task block are charged first?
