# Review resolution: a plan review that converges, can be run before the push, and can be overridden on record

Status: design draft, 2026-10-15. Harness at v0.4.0 (`main` == `origin/amaster`, 95851428). Markers: **[V]** verified
(read in the code at the cited line, or run), **[I]** inferred (follows from the code or the data, not run end to end).

## 0. The answer in five lines

1. The review does not converge mainly because **every round re-judges every unit and batch** and because a person has
   **no way to see all findings, what changed since the last round, or how to fix each one**. The data of the live plan
   shows 46% of the unit reviews were of material that had not changed, and one unit's same four concerns came back,
   reworded, seven times (section 2).
2. Mechanisms: findings shown in full with an id, a "how to resolve" and the round diff (D1); incremental review keyed
   on the exact material (D2); three small verdict rules (D3); prerequisite cuts no longer block, prerequisites shown
   spec first and `tasks.md` last, budgets with numbers (D4); a working-tree review that runs on macOS, dry by default,
   recorded on request for a committed tree so CI skips (D5); true check marks (D6); `l4 yolo accept`, an audited,
   material-bound override (D7); accepted findings travel to the implementer, the verifier's judge and the `merge:
   auto` guard (D8). Convergence rule chosen: incremental review + minor never blocks + a person's acceptance after 2
   judged versions; no automatic "after N rounds" filter (D10). No System One pre-screen (D11; measured, it does not
   discriminate uncalibrated).
3. The override cannot accept BLOCKED, harness findings (schema, unit missing, material cut of the subject) or
   `blocking` model findings; it needs 2 distinct versions of the subject's text judged not READY; agents need
   `yolo.review.accept_by_agents: true` in the target's committed config. Any change of what the judge saw voids it.
4. Draft spec: L4-YOLO-021..029 (ADDED), L4-YOLO-004 and -005 (MODIFIED), SCN-YOLO-43..70 (28 new scenarios); 29 tasks
   (`tasks.md`): a contract task, 25 implementation tasks for sonnet agents in three waves with disjoint files (wave 1:
   4 agents, wave 2: 3, wave 3: 2 + docs), and 3 orchestrator tasks (integration, adversarial review, live check).
5. The biggest residual risk: under `merge: auto` an accepted gap reaches an unattended merge. The link that contains
   it is the verifier judge's structured answer per accepted finding, which gates the guarded merge (D8.4).

## 1. Current state

### 1.1 How a verdict is produced

- The judge is the first usable profile of `roles.judges`, asked once per unit and once per batch of more than one unit
  (`review_plan_costed`, `src/l4/yolo/readiness.py:466-556`) [V]. **Every unit that is not `done` is asked on every
  review**; there is no per-subject reuse (`readiness.py:506-534`, `cycle.py:799-813`) [V].
- Material: the unit folder (budget `MAX_FOLDER_CHARS` 80,000), each prerequisite's folder (`MAX_DEPENDENCY_CHARS`
  20,000), each file capped at `MAX_FILE_CHARS` 20,000 (`readiness.py:64-66`) [V]. Files are read in **sorted path
  order** (`readiness.py:150`), so in an OpenSpec folder `design.md` and `proposal.md` come before `specs/*/spec.md`, and
  `tasks.md` comes last [V].
- Check marks: `read_folder` applies `normalise_tasks` (`readiness.py:154`, `digest.py:62-65`), so the judge sees every
  task as `[ ]`, with `TASKS_NOTE` saying a task "is never a sign that something is already implemented"
  (`readiness.py:205-208`) [V]. The implementer skips ticked tasks (`implementer/tasks.py:41-45`, `not task.done`) [V],
  so the judge reviews work that will not run.
- Rules (`verdict_of`, `readiness.py:330-346`): schema-invalid or empty → BLOCKED with the harness finding
  `{criterion: "schema", severity: "blocking"}` (`readiness.py:325-327`); the model's READY becomes NEEDS_REVISION when
  any finding is `blocking`; **otherwise the model's own verdict word stands** — a NEEDS_REVISION with only `major` or
  only `minor` findings stays NEEDS_REVISION [V].
- `_amend` (`readiness.py:353-381`): for a batch with acceptance profile `none`, `batch_acceptance` findings become
  assumptions and NEEDS_REVISION becomes READY when no blocking/major finding is left (`:358-372`); material cut by
  the limits — **of the subject or of any prerequisite** — adds a `{criterion: "material", severity: "blocking"}`
  finding whose text lists `"<unit>", "<path>": N characters cut at the size limit` and forces at least NEEDS_REVISION
  (`:373-378`, `FolderText.left_out` `:130-133`) [V]. The text has neither the folder total nor the budget nor the fix.
- Severities in the prompt: `blocking` (an implementer would build the wrong thing or be stuck), `major` (a real gap),
  `minor` (a nit); READY only "when there is no blocking finding and you would let it run unattended"
  (`prompts/readiness.md:22-25`) [V]. The schema has nine criteria (`schemas/readiness.schema.json:13-18`) [V].
- Prompt version 3 (`readiness.py:56-60`); a review with another version is stale everywhere [V].

### 1.2 How it is recorded

- CI: `plan.admitted` (when needed), `plan.reviewed{plan_digest, prompt_version, units: {id: {verdict, digest,
  findings}}, batches: {id: {verdict, findings}}}` and `plan.charged{unit: "plan:review", attempt: 0, cost_usd:
  <running total>}` (`cycle.py:819-842`) [V]. CI drops `assumptions`, `missing` and the cost of this review from the
  event; `review --local` keeps them and adds `by` (`commands.py:622-629`, `:707-716`) [V].
- The fold keeps **only the latest** `plan.reviewed` (`state.py:114-126`: `review` and `review_digests` are reset) [V].
- The review's cost counts against the plan's `max_cost_usd` (`state.py:203-210`; `cycle.py:835-841`) [V].

### 1.3 How it is shown

- CI log: one line `reviewed (u1=READY, u2=NEEDS_REVISION, …)`, no finding (`cycle.py:843-844`) [V].
- `l4 yolo review PLAN` when the review is current: `already reviewed for these inputs (not READY)` and, per item, the
  verdict and **one** finding (`commands.py:675-679`). `_first_line` puts `blocking` first and keeps the judge's order
  otherwise, so the line shown can be a `minor` nit while the `major` that blocks is hidden (`commands.py:298-306`) [V].
- `l4 yolo status`: the same one line per item (`commands.py:1003`, `_render` `:1055-1058`) [V].
- No command prints all findings, the assumptions, the missing list, or a comparison with the last round. The full
  text is only in `ledger.jsonl` of `refs/l4/plans/<id>` [V, grep of `src/l4`].

### 1.4 Currency ("already reviewed for these inputs")

- A review is current when it has the current plan digest, every unit's current digest (on the unit branch when it has
  one, else on the target: `digest.current_unit_ref`, `digest.py:102-110`), every item, and the current prompt version
  (`_review_view`, `commands.py:309-339`; CI `_reviewed_current`, `cycle.py:868-872`) [V]. It is all or nothing for the
  plan: one changed unit makes CI review the whole plan again [V].

### 1.5 How a person resolves it today

Runbook 12.2 steps 4-6: `l4 yolo review`, `l4 yolo status`, "correct the spec of the unit on `<base>`", repeat
(`docs/runbook.md:1366-1374`) [V]. Each round is a push to the target, a CI run, and a judge bill. There is no
override: activation refuses while any item is not READY (`commands.py:799-808`) [V].

### 1.6 `l4 yolo review --local`

- It exists (`cli.py:224-228`). It does **not** review the working tree: it fetches, reads the plan file and the units at
  `origin/<base>` (`_sync`, `_file`, `_read_units`, `commands.py:636-647`) and calls `review_plan_costed(rev=rev)`,
  which reads every folder with `git ls-tree`/`git show` at that revision or the unit branch (`readiness.py:145, 154,
  455-463`). It only moves the judge call to the laptop, and it records `plan.admitted` + `plan.reviewed` +
  `plan.charged` like CI (`commands.py:707-724`) [V]. **A pre-push review does not exist in any form.**
- On macOS it stops with exit 3: `select_sandbox` (`readiness.py:545`) raises `SandboxUnavailable` (an `L4Exit`,
  exit 3, `sandbox/base.py:14-18`) with `bwrap was not found on PATH; install bubblewrap …`; `run_review` catches only
  `RoleLimit`, `RoleUnavailable`, `RevisionMissing` (`commands.py:701-706`) [V: the raise reproduced on this Mac;
  the full command path read, not run].
- Is the sandbox essential for this judge? The judge call allows no tool: claude-code gets `--tools ""`,
  `--strict-mcp-config`, `--safe-mode` (or `--bare`), `--no-session-persistence` (`agents/claude_code.py:107-113`);
  opencode gets `tools: {"*": false}, permission: {"*": "deny"}` (or `ask`, which run mode refuses, for free models,
  `agents/opencode.py:96-100`); the process runs in an empty scratch folder emptied before each call
  (`readiness.py:404-407`), and everything it may see is in the prompt [V]. **codex is the exception**: as a judge it
  runs `codex exec … -s read-only` (`agents/codex.py:208-221`), which keeps its shell tool with read access to the
  whole disk under codex's own sandbox [V for the argv; I for what codex's read-only mode permits]. The harness already
  runs unsandboxed outside CI, with a printed label, for the gate dry run (`gates/dryrun.py:132-152`) [V].

### 1.7 How `l4 yolo activate` checks READY

`run_activate` (`commands.py:744-831`): plan file, status, a rejected unit, admission, then `_review_view`: `none` →
"has not been reviewed"; `stale` → "review … is for other inputs" or "older review prompt"; `problems` → `the review
is not READY for N item(s):` and one line per item (`:792-808`); then the target, other plans, `plan.activated` [V].

### 1.8 Mechanisms to reuse

- **Questions**: `l4 questions … accept` takes the clarifier's suggestion as the answer (`specs/questions.py:34`); a
  person decides on record [V].
- **Feedback** (L4-FBK-007): the verifier's judge gets `<l4:data kind="feedback">` and must answer `feedback: [{id,
  addressed, evidence}]`; a missing answer is `false` (`verifier/judge.py:212-230, 289`;
  `openspec/changes/human-feedback/specs/human-feedback/spec.md:212-236`) [V]. This is the shape D8 reuses.
- **Implementer prompt** `data_blocks` (heading, `<l4:data>` blocks): answered questions, lessons, the previous attempt
  (`implementer/tdd.py:560-564`, `implementer/prompt.py:50-51, 219-221`) [V].
- **Unit-folder harness files**: `.l4/fix.json`, `.l4/followup.json` live in the unit folder, `.l4/**` is outside the
  digest (`digest.py:28`), and `l4 restart` keeps only those two markers (`state/restart.py:75`) [V].
- **Person checks**: `l4 lessons promote` needs a terminal or `--yes` (`memory/promote.py:58, 141`) [V]; `who()` is
  `git config user.email` (`commands.py:146-148`) [V].

## 2. Evidence: a live 10-unit plan on a first real consumer repository (2026-10-15)

Read from `refs/l4/plans/telemetry-and-fixes` (fetched into a scratch bare repository; nothing written to the consumer
repository) and the plan file at `staging` [V]. `merge: auto`, 10 units in 3 batches, limit $30. Seven reviews between
17:20 and 18:04 UTC, all prompt version 3, **$7.36 charged to the plan before activation** (25% of its limit).

| Round | Not READY (of 12) | Unit reviews of unchanged material (own + prerequisites) |
|---|---|---|
| 1 | 8 | – |
| 2 | 5 | 5 of 10 |
| 3 | 3 | 5 |
| 4 | 3 | 6 |
| 5 | 2 | 6 |
| 6 | 2 | 5 |
| 7 | 3 | 5 |

- **Severity**: 4 `blocking` findings in all seven rounds, all of them the harness's `material_cut` in round 1, every one
  caused by a **prerequisite** folder over the 20,000-character dependency budget (`add-telemetry-runtime/tasks.md`
  7,148 characters cut; `add-recurrent-tree-indexing` spec and tasks). The judge itself never said `blocking`. Every
  NEEDS_REVISION after round 1 carried at least one `major`; 89 major, 309 minor in total. So a rule "minor-only
  NEEDS_REVISION becomes READY" would have changed nothing on this plan (it is still right, D3).
- **Reaction to `material_cut`**: the author (an agent) shrank `add-telemetry-runtime/tasks.md` from 11,928 to 7,309
  bytes and `proposal.md` from 5,239 to 2,231 bytes to fit the review budget of the units that depend on it: spec text
  was cut to satisfy a context limit of another unit's review.
- **Flips**: four READY → NEEDS_REVISION flips, each on a unit whose own digest did not change but a prerequisite's did
  (r3 boundary-tracing, r4 and r7 local-observability-stack, r6 heavy-path-spans; and the `telemetry` batch in r7). No
  flip on material that was the same. Each flip carried at least one `major` on `interfaces` or `contradiction`, so a
  rule "a prerequisite-only change can only add cross-unit findings" would have prevented none of them.
- **Persistence**: `add-telemetry-runtime` was NEEDS_REVISION in 7 of 7 rounds with 4-6 majors each, and the same
  concerns came back reworded every round: the wall-clock thresholds (200 spans in under 0.5 s) in rounds 1-7, invalid
  values of the consumer's OTel enablement variable/`OTEL_TRACES_SAMPLER`/… in rounds 1, 2, 4-7, logger names in 2-7. Exact-text
  matching would show all of them as new; the criterion and the topic repeat.
- `batch_acceptance` was raised 10 times on **units** (the criterion is for batches), always `minor`.

Later the same day (reported by the coordinator, not read by me): **nine** CI rounds on this plan; each round raised 2-3
**new** findings on the units the previous fix changed (round 9: missing failure cases for invalid configuration
values, an unstated relation between two helpers, an unstated Dockerfile assumption). A foundation unit with many
dependents was trimmed again and again to stay under the 20,000-character dependency budget while each round asked
for more scenarios in it. To review before pushing, the operator had to build a scratch bare repository as `origin`
(a bare clone plus `refs/l4/*`) and a working clone of it, because `--local` reads `origin`.

## 3. Diagnosis

1. **Cost and noise from whole-plan reviews** (1.1, 1.4): 32 of 70 unit reviews (46%) judged material that had not
   changed [V, ledger]. Each is a chance to flip; none flipped here, but each costs.
2. **The person cannot see what to do** (1.3): one finding line per item, possibly a minor one; no "how to resolve"; no
   round diff, so persistent concerns look like new ones and get half-fixed again.
3. **No decision exists for "the judge keeps finding more"** (1.5): the unit that never converged had real but
   open-ended concerns (one more invalid environment value each round). Only a person can say "enough".
4. **A harness rule pushed the author to delete spec text** (1.1 material, section 2): prerequisite cuts block, and the
   message names no budget and no fix.
5. **The judge reviews the wrong tasks** (1.1 check marks).
6. **Every iteration needs a push and a CI run** (1.6), and the only local variant does not run on macOS.

## 4. Decisions

### D1. Every finding: an id, a "how to resolve", and the change since the last review

- **Finding id** `F-<6 hex>` = sha256 of `subject \0 criterion \0 severity \0 text`, shown, never stored as a key of
  anything (wording drifts). The subject is `openspec:x` / `kiro:y` for a unit, `batch:<id>` for a batch.
- **`l4 yolo findings PLAN [SUBJECT] [--all] [--json]`** (new, reads the ledger, no model, no write): for the latest
  review, per item not READY (all items with `--all`): verdict, then every `blocking` and `major` finding in full
  (minors counted, shown with `--all`), assumptions and missing, each finding with its id, criterion, severity, text,
  and a **Resolve:** line; then **Since the last review:** `new: n`, `repeated: n` (same text), `gone: n`, and
  **persistent criteria** (a criterion at major or above in every not-READY review of this subject at any digest, with
  the count, e.g. `testability ×7, failure_cases ×6`). "The last review" of a subject is the latest earlier entry with
  a **different material key** (an entry reused by D2 is the same judgement, not a new round). Last line: the command that applies next (the review, or
  `l4 yolo accept …` when D7's conditions hold).
- **Resolve** text is harness text per criterion, with the subject's folder and the plan file filled in:

  | Criterion | Resolve |
  |---|---|
  | outcome | State the observable result in `<folder>/proposal.md` or the spec, not only the work. |
  | testability | Give the scenario concrete inputs and outputs in `<folder>/specs/*/spec.md` (Kiro: `requirements.md`); a time bound needs a tolerance or an injected clock. |
  | interfaces | Fix names, signatures, data shapes and error values in the spec (the implementer and the dependent units read the spec, not only `tasks.md`). |
  | failure_cases | State what happens on bad input, absence, concurrency and a failing dependency. |
  | feasibility | Split the unit (a new change folder and a plan entry) or remove the part that needs a person, a secret or a service. |
  | duplicate_scope | Remove the overlap from one of the units the finding names. |
  | contradiction | Make the two statements agree, in this folder or in a prerequisite's. |
  | missing_dependency | Add the unit it needs to `depends_on` of `<subject>` in `.l4/plans/<plan>.json` (batch `<b>`). When the text names a known unit id that is not in `depends_on`, the exact entry is suggested; nothing is parsed beyond known ids. |
  | batch_acceptance | State the batch outcome in a unit's proposal, or give batch `<b>` an acceptance profile that can show it. |
  | material (harness) | D4's message: file, size, budget, config key, the fix. |
  | schema / unit_missing / completeness (harness) | No review happened for this item: run the review again / push the folder or remove the unit from the plan. |

- The **CI log line** becomes `reviewed: N READY, M not READY (l4 yolo findings <plan>)`; `l4 yolo review` (current),
  `l4 yolo status` and the activation refusal keep one line per item but choose it by severity (blocking, then major,
  then minor) and end with `Next: l4 yolo findings <plan>`.
- **Why the diff is by criterion as well as by text**: the data shows rewording every round (section 2); exact matches
  alone would call everything new. Counting by (criterion, severity) plus persistence is honest about that and still
  points at "this concern keeps coming back". No fuzzy matching of free text.

### D2. Incremental review: the same material is not judged twice

- Each subject gets a **material key**: sha256 over the prompt version, the subject kind, and the exact user text the
  judge would get **without the "already delivered" block**. It covers the subject's folder (with its true check marks,
  D6), its plan entry and batch context, and every prerequisite folder as shown.
- Before asking the judge, `review_plan_costed` looks up the key in the plan's earlier `plan.reviewed` events with the
  current prompt version (all of them, newest first, not only the latest: a CI review of the target may have come
  between two working-tree reviews). Found → the verdict is reused at no cost, recorded with `material: <key>,
  reused_from: <at>`. Not found → the judge is asked and the entry records `material: <key>`.
- Never reused: a verdict with a harness `schema`, `unit_missing` or `completeness` finding (no review happened).
- **Why the delivered block is outside the key**: it changes whenever any unit outside the plan is merged or archived
  on the target, which would void every key. Leaving it out is safe in one direction: a newly delivered unit can only
  remove a `missing_dependency` finding, never add one, so a reused verdict is at worst stricter [I]. `--fresh` (D5)
  re-asks a subject when a person wants the newer list considered.
- CI still decides *whether* to review with the plan and unit digests (`_reviewed_current`, unchanged); the key decides
  *which subjects* the judge is asked about. The event still has an entry for every item, so the fold and the activation
  are unchanged.
- **Effect on the live plan**: 32 of 70 unit reviews and the unchanged batches would have been free, about 40% of the
  $7.36 [I, from section 2's table and the per-round cost]. More important: an acceptance (D7) bound to the key survives
  reviews triggered by other units.

### D3. Three verdict rules (deterministic, in `_amend`)

1. A NEEDS_REVISION whose findings are all `minor` becomes READY; the minors stay in the entry. The prompt defines
   minor as "a nit"; the harness already does this for grouping batches (`readiness.py:369-370`). It would not have
   helped the live plan (section 2); it removes a trap, not the main cause.
2. A NEEDS_REVISION with no finding at all gets the harness finding `{criterion: "verdict", severity: "major", text:
   "the judge said NEEDS_REVISION and named no finding; missing: …"}`, so the person has something to read and D7 can
   accept it.
3. A `batch_acceptance` finding on a **unit** becomes an assumption (the criterion applies to batches only,
   `prompts/readiness.md:21`). Observed 10 times, all minor: a correctness fix.

The judge's own `blocking` and BLOCKED are not touched.

### D4. Material budgets: a cut prerequisite no longer blocks, and the message says what to do

- **The subject's own cut still blocks** (R9 stays): the activation freezes that folder's digest, so a cut means frozen
  text no reviewer saw.
- **A prerequisite's cut no longer blocks**: it is listed in `missing` as `not shown in full: "<unit>": <path> (<n> of
  <total> characters shown; dependency budget <b>)`. Argument: a prerequisite that is a unit of the plan is itself a
  subject with the larger budget, so its text is reviewed in full there; one outside the plan is already delivered.
  The R9 reason ("the digest freezes content the judge never saw") does not apply to it [I].
- **Prerequisites are shown spec first**: `proposal.md`, `requirements.md`, `specs/**/spec.md` (the requirements and
  scenarios), then `bugfix.md` and `design.md`, then any other file, and `tasks.md` last, only within what is left of
  the budget. What a dependent needs (the interface and the scenarios) survives a cut; the task list, which the unit
  under review is not judged on, is what gets cut. The subject keeps the sorted order and its full budget.
- This removes the trap of section 2: a foundation unit no longer has to be trimmed for its dependents' reviews. If its
  `specs/` alone pass the dependency budget, the dependents' material says so in `missing` and their verdict is
  unaffected; the unit itself is reviewed in full as a subject.
- **Budgets are configuration**: `yolo.review.max_file_chars` (20,000), `max_folder_chars` (80,000),
  `max_dependency_chars` (20,000). Defaults unchanged.
- **The message** for a subject cut: `material_cut: <path> has <n> characters; the review shows <f> per file and <b>
  per folder (yolo.review.max_file_chars, max_folder_chars). Shorten the file (move background out of the unit
  folder) or raise the limit in .l4/config.yaml on <base>. Splitting it does not help: the implementer reads only
  proposal.md, design.md, requirements.md, bugfix.md and specs/*/spec.md.` The last sentence is true today
  (`implementer/prompt.py:287-301`) [V].

### D5. A review of the working tree before the push

- **`l4 yolo review PLAN --worktree [--fresh SUBJECT …] [--record]`**. It needs no change of `origin` and no scratch
  repository: it fetches the target and the plan refs as every `l4 yolo` command does, and reads everything else from
  the checkout.
  1. Snapshot the working tree into a commit object without touching `HEAD`, the index or any ref: a temporary index
     (`GIT_INDEX_FILE`), `git read-tree HEAD`, `git add -A -- <plan file> <unit folders>`, `git write-tree`, `git
     commit-tree -p HEAD`. `Git.rev_parse` needs a commit (`vcs/git.py:139`, `^{commit}`), hence `commit-tree` and not
     a tree [V: the sequence run in a scratch repository; untracked files included, status and log unchanged].
  2. Read the plan file and the units from the working tree (providers on the checkout path), admit as `l4 yolo check`
     does, read every unit at the snapshot (not on its branch), and call the same `review_plan_costed` with the same
     prompt, schema, rules and incremental keys. For a unit that has a branch on `origin`, one line says `CI reads
     <unit> on its branch <b>; this review read the working tree`.
  3. Print the plan digest and each unit's digest and material key it reviewed, each item's verdict, the D1 rendering
     (findings with `Resolve:` lines and the change since the last recorded review), `cost: $x.xx (n judged, m
     reused)` and the plan's recorded review total against its limit, and `Next:`. Exit 0 when every item is READY or
     accepted, 2 otherwise.
  4. **Records nothing by default** (a dry run): no plan ref write, no charge. Its verdicts go to a local cache,
     `<cache>/yolo/<plan>/review/verdicts.jsonl` (material key, prompt version, judge profile, entry), so the next
     local run asks the judge only about what changed. Lookups use the local cache and every recorded `plan.reviewed`
     (D2), so subjects CI already judged on the same material cost nothing locally.
  5. **`--record`** writes `plan.admitted`, `plan.reviewed{source: "worktree", sandbox, by, …}` and `plan.charged`, as
     `--local` does. It is refused unless the plan file and every unit folder of the plan have no uncommitted change
     (the snapshot equals `HEAD` for those paths), so a recorded review is always of a commit the person can push. The
     digests are the commit's, which by the construction of the unit digest (yolo-mode design D3, `unit_digest` over `git ls-tree` of the same paths) equal what CI computes after the push. Flow: iterate dry until
     READY, commit, `--record` (every subject is a cache hit: $0, seconds), push; CI finds the review current and does
     not review again (`_reviewed_current`), and `l4 yolo accept` can bind to the recorded entries. A review is only
     accepted or skipped from the ledger, never from the local cache: the cache is the person's, the ledger is shared.
     A unit that has a branch on `origin` is digested by CI on that branch (`current_unit_ref`), so a recorded review
     of the working tree is current for CI only when the branch holds the same folder; otherwise CI finds it stale and
     reviews again, which is the safe direction. The event's `sandbox` is `none` when any of its judged entries (from
     this run or from the local cache, whose lines carry the label) was judged unsandboxed.
- **Sandbox decision** (`--worktree` and `--local` alike):
  - bwrap usable → the agent sandbox, as today;
  - else, **outside CI only**, run the judge unsandboxed when the selected profile's adapter enforces "no tool" in its
    own argv: `claude-code`, `opencode`, `fake`. The output says `judge unsandboxed (<why>): it has no tools and runs in
    an empty folder` and the event records `sandbox: "none"`;
  - a `codex` judge without bwrap is refused (`codex keeps a read-only shell as a judge; use a claude-code or opencode
    judge profile here, or let CI review`);
  - in CI: fail closed as today (L4-SEC-005); `sandbox.mode: none` keeps its meaning.
  - **Why this is safe enough**: the threat is spec text that steers the model. A tool-less model can only shape its
    JSON answer; the call is the same exposure as the person running `claude -p` with the prompt by hand; the
    environment is still built by `build_agent_env`. What bwrap adds for this call — hiding other CLIs' credentials and
    the home folder from the CLI process — matters when the process can read files, which is why codex is excluded. The
    gate dry run made the same choice (`gates/dryrun.py:150-152`). A wrong verdict from a steered judge is possible
    in CI too; activation, the verifier and the post-merge profile are the gates after it.
- **Trust of a recorded laptop review**: the ledger is a git ref anyone with push rights can write; a CI-only cache
  would not add integrity. Recording `source`, `sandbox`, `by` and the judge profile keeps it auditable.

### D6. Check marks as they are

- The digest keeps normalising every marker to `[ ]` (R4, L4-YOLO-003): a harness tick must not stop an active plan.
- The material shows `tasks.md` **as it is** (no `normalise_tasks` in `read_folder`); the note becomes: "A ticked task
  (`[x]`) is already delivered on the revision shown: the harness will not implement it again. Judge the specification
  of the open tasks; do not raise a `feasibility` or `duplicate_scope` finding only because work is already done."
- Ticks are part of the material key (D2), not of the digest: a tick change re-asks the judge when a review happens
  anyway, and never makes a review stale by itself. A tick removed after the review (a restart resets the branch's
  ticks) is covered because the judge still judged every task's text.
- `PROMPT_VERSION` 3 → 4. Every plan not yet activated, and every plan stopped with `inputs_changed`, is reviewed once
  more after the upgrade and pays for it (the runbook already says so for prompt changes, `docs/runbook.md:1386-1389`).

### D7. `l4 yolo accept`: a manual, audited override

```
l4 yolo accept PLAN SUBJECT --reason TEXT [--yes]
l4 yolo accept PLAN SUBJECT --withdraw --reason TEXT
```

**What is accepted**: the latest verdict of one subject (a unit id or `batch:<id>`) as a whole, with all its findings
recorded for audit. Not individual findings: their wording changes between reviews (section 2), so a per-finding
binding would break on the next review, and with D2 an unchanged subject keeps exactly the same findings anyway.

**Event** `plan.accepted{subject, material, prompt_version, digests, plan_digest, verdict, findings, findings_sha,
reason, by, actor, marker, rounds}`; `plan.acceptance_withdrawn{subject, reason, by}` (anyone may withdraw, a person
or an agent: withdrawing removes an override and only makes the activation stricter). The fold keeps the latest per
subject in `PlanState.accepted`.

**Binding**: an acceptance holds while the latest review's entry for that subject has the same `material` key and the
same `findings_sha`. Any change the judge would see — the unit's folder or check marks, a prerequisite's folder, its
plan entry or batch — gives a new key, a new judgement, and voids it; so does a prompt version change. For a batch the
key covers all its units' folders.

**Never acceptable** (refused with the reason and the fix):
- BLOCKED, any cause: the judge could not judge or says it cannot be built; the harness's BLOCKED (`schema`,
  `unit_missing`, `completeness`) means no review happened.
- A `material` finding of the subject: frozen text no one reviewed; the fix (D4) is mechanical and in the person's hands.
- A finding the judge marked `blocking`: by the prompt's own definition the implementer would build the wrong thing.
On the live plan this list would have refused nothing after round 1.

**Acceptable**: NEEDS_REVISION whose remaining findings are `major` (minor-only is READY by D3).

**Conditions**:
1. **Rounds**: the recorded reviews of the plan, **of any prompt version**, hold at least
   `yolo.review.accept_after_rounds` (default 2) **distinct versions of the subject's own text** judged not READY: a
   unit's version is its unit digest, a batch's is the list of its units' digests. A verdict reused by D2, or a
   re-judgement after a prompt change or a prerequisite change, is the same version and does not count twice, so the
   condition means "the author changed this subject's text and it is still not READY". Counting across prompt versions
   is deliberate: after the upgrade to prompt version 4 the nine recorded rounds of the live plan still count (its
   never-READY unit had 7 distinct digests judged not READY), so a person can accept as soon as one version-4 judgement
   exists, which the binding (below) needs anyway. The binding itself is always to the latest entry, of the current
   prompt version. Same rule for persons and agents; a person who wants to accept at once sets it to 1 in the target's
   configuration, on record.
2. **Who** — the harness cannot know who types a command [I]: anyone with push rights can append to
   `refs/l4/plans/*` by hand, so these checks keep honest agents from deciding for a person; they are not a security
   boundary. `actor` is `person` when stdin is a terminal (the typed confirmation needs only stdin; `l4 yolo accept …
   | tee log` stays a person's command; `lessons promote` checks stdin alone, `memory/promote.py:58`) and no agent
   marker is set; else `agent`. Markers: `CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT`, `AI_AGENT` [V: set, and stdin is not a
   terminal, in this agent's shell], `CODEX_SANDBOX` [I: the name is not verified], `L4_RESULT_PATH` (set by the harness
   for its own agents, `sandbox/env.py:36`) [V]. A person confirms by typing the plan id after seeing every finding (as `lessons promote` asks,
   `memory/promote.py:141-142`); `--yes` is refused for a person-less run unless agents may accept.
   An agent is refused unless `yolo.review.accept_by_agents: true` **in `.l4/config.yaml` at `origin/<base>`** (not the
   working tree, which the agent can edit; a pushed change to the target's configuration is a person's visible
   decision). The refusal prints the exact command for the person.
3. **Reason**: required, at most 1,000 characters. It is the person's instruction to the implementer (D8), so it should
   say what to do ("keep the thresholds; run the timing tests with a 3× tolerance").
4. **Plan state**: before activation, or stopped with `inputs_changed`/`unit_rejected` (the states in which a review
   can be made). Not on an active plan.

**Activation** (`run_activate`, MODIFIED L4-YOLO-005): an item counts as cleared when READY, or NEEDS_REVISION with an
acceptance that holds. The output lists every accepted subject with `by`, `actor` and the reason;
`plan.activated{accepted: {subject: {findings, reason, by, actor}}}` freezes them for D8. An acceptance by an agent is
shown first, marked `(accepted by an agent)`: the activation is the person's decision (L4-YOLO-005; the skill says
agents never activate, `plugins/l4/skills/l4/references/plan.md:114, 129`), so a person sees each agent acceptance
before anything runs.

**Status**: `l4 yolo status` shows `accepted by <by> (<actor>): <reason>` under the item; `l4 yolo findings` shows the
acceptance and whether it still holds.

### D8. Accepted findings travel with the unit

1. **Carrier**: at each dispatch (and each later run of a unit the plan holds as current), the run writes
   `<unit folder>/.l4/review-accepted.json` (`{plan, subject, findings, reason, by, actor}` for the unit and its batch)
   when it differs, in the run's first commit. `.l4/**` is outside the digest (`digest.py:28`) and is a harness path;
   `l4 restart` drops it (`state/restart.py:75`) and the next dispatch writes it again. The plan step hands the payload
   to the run through `PlanStep` (from `plan.activated{accepted}`), so nothing reads the plan ledger in the unit run.
2. **Implementer**: `tdd._prompt` adds the data block `accepted review findings` (`implementer/tdd.py:560-564`): the
   findings and the person's reason, with the rule "the specification has these accepted gaps; where it is silent,
   follow the reason; write in `notes_for_verifier` how each was handled".
3. **Verifier judge**: the block `<l4:data kind="accepted">` with each finding id, criterion and text, and the reason;
   the reply gets `accepted: [{id, addressed, evidence}]`, a missing answer being `false` (the L4-FBK-007 shape; judge
   prompt version 7 → 8). It is evidence: it does not change PASS or FAIL of the criteria. Recorded as
   `review.accepted_judged{id, round, addressed, evidence}` in the unit ledger.
4. **`merge: auto`**: the guarded merge gets one more precondition, **fail closed**: the unit fold exposes
   `accepted_addressed` (the ids every judge of the latest PASS round answered `addressed: true`); the plan step
   computes `open = ids of step.accepted − accepted_addressed` and waits with `accepted_finding_open` and the detail
   (each open id with its evidence, or `no answer recorded`) when `open` is not empty. No answer is open: a unit adopted
   `in_review` with a PASS (`cycle._adoptable`) or verified before the carrier file reached it has no answers and
   waits. A person then merges the PR by hand (the next step integrates a person's merge, R10), pushes a fix, or runs
   `l4 retry --unit <unit>` to have it verified again with the accepted findings in the judge's prompt. With `merge:
   human` the answers are in the PR body; a person merges anyway.
5. **Report**: `report.md` and the receipt list the accepted findings, who accepted them, and the verifier's answers.

### D9. Documentation

Runbook 12.2 gets a new procedure "12.2a The review is not READY" (the exact commands: findings, fix, `--worktree`,
push, accept, activate), the activation refusals list the acceptance, 12.4 gets the wait `accepted_finding_open`;
`docs/yolo-mode.md` gets a "Review" section; the skill: `plan.md` tells an agent to iterate with `l4 yolo review
--worktree`, to read `l4 yolo findings`, and never to accept unless the target's configuration allows it (then only after
two rounds, with a reason that tells the implementer what to do); `operate.md` lists `findings` and `accept`.

### D10. The convergence rule chosen, and the ones not chosen

Chosen, all deterministic:
1. **Incremental review (D2)**: material the judge already judged is never judged again. This removes re-rolls and
   about 40% of the cost, and makes a person's decision on a subject stable across other units' fixes.
2. **Minor never blocks (D3.1)**: the only automatic downgrade, because the prompt itself calls minor "a nit".
3. **After two not-READY judgements of different material, a person may accept the rest on record (D7)**, with a
   reason that goes to the implementer and the verifier (D8). This is the "after N rounds" rule, made a decision
   instead of a filter: N = 2 distinct versions of the subject's text judged not READY
   (`yolo.review.accept_after_rounds`).

Not chosen:
- **"After N rounds, only findings on text changed since the previous round count."** The harness cannot place a finding
  in the text: the persistent findings are omissions ("no failure case for an invalid value", "the relation of two
  helpers is not stated"), which quote nothing. And the coordinator's round-9 evidence says the new findings are on the
  units the previous fix changed, so such a rule would still count them. A rule that silently drops `major` findings
  under `merge: auto` would also let real gaps through with no record and no instruction to the implementer.
- **"After N rounds, majors on testability or failure_cases stop blocking."** Same objection: an automatic filter with
  no record. D7 gives the same outcome when a person agrees, on record, with the reason forwarded.
- **Telling the judge which text changed** (section 6): a prompt rule the harness cannot enforce.

What the person sees that makes the decision easy: `l4 yolo findings` shows, per subject, the not-READY streak, the
persistent criteria (`testability ×7, failure_cases ×6`), and `accept: l4 yolo accept <plan> <subject> --reason TEXT`
once the rounds condition holds.

### D11. A System One (Jev) pre-screen before the judge: no

Considered: a cheap S1 call per requirement ("has a failure-case scenario?", "names a helper the spec does not
define?") before the LLM judge, on the existing S1 backend (`l4.llm.system_one`, `verifier/s1_step.py`, `S1Cfg`).
Not added, for four reasons:
1. **The problem is convergence, not detection cost.** A pre-screen is a second set of opinions with different
   criteria; when it and the judge disagree, the person gets more findings, not fewer rounds.
2. **It cannot predict the judge.** The persistent findings are open-ended omissions ("one more invalid environment
   value"); a yes/no question per requirement either flags nearly every requirement or misses what the judge raises.
3. **The cheap iteration already exists with the real judge**: D5's dry run asks the judge only about changed subjects
   (D2), so a local round on one changed unit costs one unit review (about $0.10-0.15 on the live plan's rates [I]),
   with exactly the criteria CI will apply.
4. **The harness uses S1 as corroboration only, with calibration rows** (`verifier/s1_step.py:1-7`: "S1 is
   corroborating only"; "Nothing here reads `p` to decide anything"). A readiness pre-screen would need its own labelled
   set and calibration before it could be trusted to gate or to skip a judge call.

**Measured** (by the coordinator, 2026-10-15, not rerun by me): Jev (jev-1.13.0) answered three yes/no questions per
requirement (failure behaviour covered by a scenario? every SHALL tested? unambiguous?) over 28 requirements of 5
OpenSpec changes, about 20k input tokens, under a minute. It put 27 of 28 below 0.5, including requirements the LLM
judge had accepted; "unambiguous" sat at 0.3-0.5 everywhere. A single-question probe on a requirement whose only
scenario is the healthy path did answer correctly (failure covered = 0.03). Uncalibrated, it does not discriminate,
which confirms reason 4.

If anything, later and outside this change: a **calibrated, record-only experiment** — the labelled set is the
requirements of past review rounds (READY vs a finding on that requirement, from the plan ledgers), thresholds are
tuned on it, the scores are recorded next to the judge's verdict (shadow, as `S1Cfg.shadow` does for the verifier) and
never decide anything until the calibration rows show they predict the judge. A second candidate use, also display only:
whether two findings of consecutive rounds raise the **same concern**, to show "repeated" across rewording.

## 5. Risks of the override, and what contains them

| What could get through | Containment | Which link does the work |
|---|---|---|
| A real gap reaches an unattended merge (`merge: auto`) | Only `major` findings; the reason goes to the implementer; the verifier must answer each accepted finding; an unaddressed one blocks the guarded merge (D8.4); the gates, the verifier's criteria and the post-merge profile are unchanged | D8.4 (the structured answer) |
| An agent accepts its own unfinished spec to get the plan moving (the live case was agent-driven) | Off by default; the switch is in the target's committed configuration; 2 rounds; the activation shows agent acceptances to the person who activates | The committed switch + activation |
| An acceptance outlives the text it was about | Bound to the material key and the findings hash; any change voids it | D2's key |
| A wrong READY or a steered judge (prompt injection in a spec) | Unchanged from today: activation by a person, verifier, post-merge profile; unsandboxed judging only for tool-less adapters and only outside CI | Tool-less argv |
| A stale reused verdict hides a new problem | The key covers everything the judge sees but the delivered list, which only removes findings; `--fresh` re-asks | D2 |
| Reviews keep eating the plan's cost limit | D2 cuts repeated judging; `--worktree` shows the cost and the plan's review total before the push | D2, D5 |
| Someone forges `plan.accepted` by pushing to the plan ref | Not prevented (true today for every plan event); `by`, `actor`, `marker` and the git commit author are on record | Audit only |

## 6. Alternatives not taken

- **"A prerequisite-only change keeps READY unless a cross-unit criterion is raised"**: prevented 0 of 4 flips in the
  data (each flip had an `interfaces` or `contradiction` major).
- **Give the judge its previous findings and the diff since the last review, and ask for no new non-blocking findings on
  unchanged text**: a prompt rule the harness cannot check; anchoring risk. Left for a later prompt version if D1-D7 do
  not suffice.
- **Accept individual findings**: breaks on rewording (section 2).
- **Accept BLOCKED or blocking findings**: the cost on the live plan of refusing them is zero; the risk of allowing them
  is the wrong thing built unattended.
- **A CI-only verdict cache**: no integrity gain (D5), and the working-tree review would not save the CI round.
- **Stop charging the review to the plan**: the plan's limit is its total spend; the cost is shown instead.

## 7. Not determined

- What codex's `-s read-only` judge can read on macOS and Linux (I did not run codex) — the design refuses it without
  bwrap, so the answer does not change the design.
- Whether `opencode` with a free model leaves any tool reachable as a judge beyond the `ask` rejection the code comment
  states (`agents/opencode.py:85-89`, marked [I] there).
- The judge's run-to-run variance on identical material: the live data had no flip without a material change, but seven
  rounds are a small sample.
- Whether the `merge: auto` precondition of D8.4 makes plans wait often in practice: depends on how judges answer
  `addressed` for spec-level findings (for example "the scenario has no tolerance"). A live check is in the tasks.
- An optional, owner-level question: a harness convention for silent specs ("an input the spec does not list is
  rejected with an error and never crashes") would let the judge stop listing invalid values one by one (the most
  persistent major in section 2). It is a product decision, not part of this draft.

## 8. Contracts (wave 0 writes them; the wave agents build to them and change them only through the orchestrator)

**Configuration** (`config/schema.py`): `YoloCfg.review: YoloReviewCfg` with `max_file_chars: int = 20_000` (ge 1000),
`max_folder_chars: int = 80_000` (ge 1000), `max_dependency_chars: int = 20_000` (ge 0), `accept_after_rounds: int = 2`
(ge 1), `accept_by_agents: bool = False`. The module constants in `readiness.py` stay as the defaults.

**Types** (`yolo/model.py`):
- `Verdict` gains `material: str | None = None` and `reused_from: str | None = None` (the `at` of the event reused).
- `PlanState` gains `accepted: dict[str, dict[str, Any]]` (subject → the latest `plan.accepted` data, removed by
  `plan.acceptance_withdrawn`, emptied by nothing else) and `activated_accepted: dict[str, dict[str, Any]]` (frozen by
  `plan.activated{accepted}`).
- `YoloStep` (via `cycle.PlanStep`) gains `accepted: Mapping[str, tuple[dict[str, Any], ...]]` (unit id → the accepted
  items that concern it: its own subject and its batch's).

**Identifiers** (`yolo/findings.py`): `finding_id(subject, f) = "F-" + sha256(f"{subject}\0{criterion}\0{severity}\0
{text}")[:6]`; `findings_sha(findings) = sha256(json.dumps(findings, sort_keys=True, separators=(",", ":")))[:16]`.
`readiness.material_key(kind, key_text) = sha256(f"{PROMPT_VERSION}\0{kind}\0{key_text}")[:16]`, where `key_text` is
the user text of the subject filled with the delivered block left empty. A subject is named `<unit id>` or
`batch:<batch id>` everywhere (CLI, events, the cache).

**Ledger events** (all keys optional for older readers; the fold ignores unknown keys):
- `plan.reviewed` gains `source: "ci" | "local" | "worktree"` (absent = `ci`), `sandbox: "bwrap" | "none"`, `judge`
  (profile name); each unit and batch entry gains `material`, `reused_from` (when reused), and CI entries also keep
  `assumptions` and `missing`; a batch entry gains `digests` ({unit: digest} of its units).
- `plan.accepted{subject, material, prompt_version, findings_sha, verdict, findings, reason, by, actor, marker,
  rounds}` with `actor` `"person" | "agent"`, `marker` the first agent variable found or null, `rounds` the count of
  D7.1.
- `plan.acceptance_withdrawn{subject, reason, by, actor}`.
- `plan.activated` gains `accepted: {subject: {findings, reason, by, actor}}` (only acceptances that hold).
- Unit ledger: `review.accepted_judged{id, round, addressed, evidence, profile}`; the unit fold exposes
  `UnitState.accepted_addressed: frozenset[str]` (ids every judge of the latest PASS round answered `addressed: true`).
- Plan wait reason: `accepted_finding_open` (detail: `<unit>: F-xxxxxx not addressed: <evidence>`).

**Files**:
- Local cache `<cache_root>/yolo/<plan>/review/verdicts.jsonl`: one JSON line `{material, prompt_version, judge,
  sandbox, kind, subject, entry, at}` per judged subject (never a reused one).
- `<unit folder>/.l4/review-accepted.json`: `{"schema": "l4/review-accepted@1", "plan": <id>, "items": [{"subject",
  "reason", "by", "actor", "findings": [{"id", "criterion", "severity", "text"}]}]}`, written with sorted keys and a
  final newline, so an unchanged payload writes the same bytes.

**Functions** (signatures the waves share):
- `readiness.review_plan_costed(..., prior: Mapping[str, Mapping[str, Any]] = {}, fresh: Collection[str] = (),
  revs: Mapping[str, str] | None = None, budgets: Budgets | None = None, sandbox_for: Callable[[str, str], Sandbox] |
  None = None)`: `sandbox_for(adapter, profile)` is called once, after the judge profile is chosen, only when a subject
  is judged (the caller remembers the label and the profile for the event); `prior` is material key → recorded entry;
  `revs` overrides the revision of every unit (the working-tree snapshot); returns the result whose verdicts carry
  `material` and `reused_from`.
- `judge_sandbox.choose(cfg, environ, repo, *, adapter, in_ci) -> tuple[Sandbox, str]` (new module
  `yolo/judge_sandbox.py`; the sandbox and its label `bwrap` or `none`), raising `SandboxUnavailable` for a refusal.
  `TOOL_LESS_ADAPTERS = ("claude-code", "opencode", "fake")`.
- `readiness.Budgets(file: int, folder: int, dependency: int)` with `Budgets.of(cfg)` from `cfg.yolo.review`.
- `findings.prior_entries(events, prompt_version) -> dict[str, dict]` (material key → the newest entry with it, never
  one with a harness `schema`/`unit_missing`/`completeness` finding).
- `findings.history(events, subject, prompt_version) -> list[Entry]` (the subject's entries, oldest first, each with
  its event `at`, `source`, `material`); `findings.diff(prev, cur) -> RoundDiff(new, repeated, gone, by_criterion)`;
  `findings.persistent(history) -> dict[str, int]`; `findings.rounds_not_ready(events, subject) -> int` (D7.1: distinct
  own-text versions judged not READY, over every prompt version).
- `findings.resolve(plan_id, base, subject, finding, *, folder, batch, depends_on, known_units) -> str` (the
  `Resolve:` line).
- `findings.render(plan_id, base, review, history_of, *, show_all) -> list[str]` and `render_json(...) -> dict`.
- `accept.check(state, events, subject, latest_entry, cfg_target, actor) -> Refusal | None`;
  `accept.actor(environ, stdin_tty) -> tuple[str, str | None]`; `accept.holds(state, latest_review) ->
  dict[str, bool]`; `accept.target_config(git, ref) -> YoloReviewCfg` (`.l4/config.yaml` at `origin/<base>`, defaults
  when absent or invalid).
- `worktree.snapshot(git, paths) -> str` (a commit sha; `HEAD`, the index and every ref unchanged);
  `worktree.clean(git, paths) -> bool`.
