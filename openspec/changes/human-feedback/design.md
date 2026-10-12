## Context

[V, code] marks a survey of `main` at c3afb924 on 2026-10-12.

- **Human inputs today.**
  - `questions.md` (`specs/questions.py`): byte-span edits, ids never reused, drafts never consumed. `Clarifier.reenter`
    records answers and overrides.
  - The `l4 questions` command is a stub (`questions.py:190`, spec-providers 5.9). Nothing reads `Reentry.overrides`,
    so the fix unit of L4-QMD-006 is not built.
- **Re-entry after the hand-off H** (`state/review.py`).
  - A commit that is not strictly the harness's (bot author and committer, an `L4-Run` trailer) is foreign.
  - A foreign change to any unit-folder file other than `verification.md` and `.l4/` is a spec edit:
    `in_review → implementing` (`lifecycle.py:128-130`).
  - `_implement` with no pending task fires `ALL_LEAVES_DONE`, so the unit goes on to `verifying`.
  - A committed `feedback.md` therefore re-enters the unit today, with no code change. `test_review.py:96-111` shows the
    same for `questions.md`.
- **Before H** there is no foreign-commit handling. The next run reads the branch from origin. A push that races a run
  makes that run's push fail non-fast-forward, and the run exits 1 with "a human pushed; the next run continues from
  it".
- **Findings into fix units.**
  - `verifier/preconditions.ci_blockers` turns a re-entry context (a red repository CI job) into deterministic blockers.
    The round then fails at step 0 and spawns a `[chore]` fix unit. This is the pattern feedback reuses.
  - `fixunit._candidates` (`:113-183`) drops a human finding that has no criterion and no WHEN/THEN (`:145-152`).
  - A task is a chore when it has no criterion and no scenario, or when it only adds tests (`:237`).
  - `MAX_FIX_TASKS = 5`. Candidates past it are "not converted".
- **Chores.**
  - Only harness fix tasks named in the marker's `chores` run without red (`loop.py:183` → `tdd.run_single`).
  - A person's `[chore]` title tag only affects `KiroProvider.is_exempt`, the integrity skip and the `[test-infra]`
    freeze.
  - The test chore (`test_chores`) freezes non-test files. Nothing freezes test files for a production-only chore.
- **Rounds.** `decide_fix` counts used rounds as `max(fix_round, len(provider.units()) - 1)` (`fixloop.py:352`) and
  the limit as `max_fix_rounds + fix_rounds_extra` (`:398`, `state/budget.py:11`). `l4 resume --extend-fix-rounds N`
  and the resume label record `budget.extended{fix_rounds}`.
- **Judge.**
  - `build_judge_prompt` (`judge.py:206-265`) gets the criteria, the diff, the gate report, notes, conventions and
    owner changes. It gets no earlier findings and no human decisions.
  - Fix-unit text reaches the judge only as `_family_sources` (proposal, design, requirements, bugfix, spec deltas).
  - `test_judge_schema.py` compares the schema with SPEC §10.3 verbatim.
- **Kiro.**
  - `KiroProvider` has no `create_fix_unit`, and `decide_fix` escalates with "kiro has no fix units" (`fixloop.py:405`).
  - `validate` accepts `bugfix.md` in place of `requirements.md` (`kiro.py:348-353`).
  - Kiro's bugfix template, read from the IDE bundle (research/01 §2.3) [V-run]:
    - `# Bugfix Requirements Document`, then `## Bug Analysis`, then three sections:
      - `### Current Behavior (Defect)`: `1.x WHEN … THEN the system …`;
      - `### Expected Behavior (Correct)`: `2.x … SHALL …`;
      - `### Unchanged Behavior (Regression Prevention)`: `3.x … SHALL CONTINUE TO …`.
    - Bugfix tasks cite these with `_Requirements: 2.1, 3.1_` and may carry `_Bug_Condition:_`, `_Expected_Behavior:_`
      and `_Preservation:_`.
    - `.config.kiro` has `specType: bugfix`.
  - kiro-cli 2.29.1 headless (`--mode spec`) did not use this template when asked for a bugfix spec on 2026-10-12. It
    improvised `spec.md` and a free-form `tasks.md`. The IDE bundle is the ground truth here, not the CLI's output [V].
- **Protection.** `openspec/**` and `.kiro/specs/**` are protected paths (L4-SEC-004). An agent's change to
  `feedback.md` is put back today. The prompt contract (L4-IMP-004) names `tasks.md` and `questions.md` but not
  `feedback.md`.
- **Lessons.** `memory/curate.py` writes lessons from a PASS round's closed deterministic findings and from repeated
  guard violations. The fix-unit reading of L4-MEM-002 (a) is deferred (`curate.py:4-8`). `l4 lessons promote` is not
  built.
- **Merged units.**
  - OpenSpec: after archive, the change folder is `openspec/changes/archive/<date>-<name>/`.
  - Kiro: the folder stays at `.kiro/specs/<name>/` and the lock ref is kept (L4-KSP-004).

## Goals

- A person asks for a change on an open unit branch with one documented command, then commit and push. The harness
  turns the request into work, does it, checks it was done, and hands the unit back for review.
- Behaviour-preserving requests (refactor, duplication) change production code only and keep every test. Requests that
  change behaviour (config, behaviour) go through red and green like any task.
- The person can see, for every item, what happened to it.
- Kiro units get fix units, so a failed round no longer escalates them.

## Non-Goals

- Reading PR or MR comments (a later layer that writes the same file).
- Building `l4 questions` (spec-providers 5.9) or the `in_review → fixing` row of L4-QMD-006.
- An LLM that writes the criterion of a `behaviour` item. The person writes it (D4).
- Feedback on another unit's code. An item is about the unit's own change.

## Decisions

### D1. A file, not comments

`feedback.md` lives in the unit folder, next to `questions.md`.
- A file works the same on GitHub, GitLab and the local forge.
- It is reviewed in the diff, and kept in history.
- The existing re-entry already treats a push of it as a spec edit.

The format copies `questions.md` on purpose:
- a header comment that says how to use it;
- an index between markers;
- one `## FB-NNN: title` section per item;
- byte-span edits;
- ids that are never reused.

Rejected:
- **Items inside `questions.md`.** Questions go from the harness to the person; feedback goes the other way. Mixing them
  would blur who owns which status.
- **Comments first.** That needs member checks on both forges and hides the request outside git.

### D2. Kinds decide the task

| Kind | Means | Needs | Fix task |
|---|---|---|---|
| `refactor` | restructure, same behaviour | `--at` (1+) | harness chore; test files frozen |
| `duplication` | merge repeated code, same behaviour | `--at` (2+ places, or 1 and the text names the other) | harness chore; test files frozen |
| `tests` | missing or weak tests | — | the existing test chore (non-test files frozen) |
| `config` | a hard-coded value becomes an environment variable | `--at` (1+), `--env NAME` | red/green against criteria built from NAME (D4) |
| `behaviour` | the code should behave differently | `--when`, `--then` | red/green against that criterion |

There is no `other` kind. Anything that changes behaviour is `behaviour`, and the person states it as WHEN/THEN. This
keeps L4-IMP-003 whole: an exemption from red comes only from what a person wrote (the kind), never from an agent.

### D3. Taken at step 0, like a red CI job

At step 0 of every verification round of a unit, each takeable item becomes a deterministic blocking finding with
`source: "feedback"`. The round fails at once, without gates or judge, and the fix unit is written. This uses the
lifecycle as it is:

- **In review:** the push is a spec edit, so the unit goes `implementing`, then `ALL_LEAVES_DONE`, then step 0, and
  then `fixing`.
- **Before the hand-off:** items wait until the round in progress ends. A running task is never interrupted, and a fix
  unit in progress finishes first.

**Takeable** means four things hold:
- the item is valid;
- its Status is `submitted`, or `taken`/`addressed` with content whose hash differs from the last take (D7);
- it is not `withdrawn`;
- `feedback.max_rounds` is not used up.

Rejected: a direct `in_review → fixing` edge. It would skip one cheap failed round, but costs a trigger, a table row and
a second path to test.

### D4. Who writes the criterion

`behaviour` items need a criterion, because red tags its tests with criterion ids. The person writes it with `--when`
and `--then`.

`config` items build two scenarios deterministically from `--env NAME` and the place `--at`:
1. `WHEN the environment variable NAME is set THEN the system SHALL use its value instead of the value written at <path>:<line>`
2. `WHEN NAME is not set THEN the system SHALL CONTINUE TO behave as before this change`

`--when`/`--then` replace the first scenario. In the fix unit these become:
- **OpenSpec:** an ADDED requirement `### Requirement: <item title> — feedback FB-NNN`, with the scenarios;
- **Kiro:** `2.n` and `3.n` items in `bugfix.md`.

Rejected: an LLM-written criterion. It is the spec, so a person writes it or a rule builds it.

### D5. Refactor chores freeze the tests

A `refactor` or `duplication` task runs as a harness chore (`run_single`), with these rules:
- Every path matching `tdd.test_globs` or `tdd.test_support_globs` that the step changed is put back
  (`guard.restored{paths, reason: "feedback_refactor"}`).
- At least one other file must change, else the attempt fails with `nothing changed`.
- Every gate must pass.

The unchanged, passing tests are the proof that behaviour did not change. This is the inverse of the test chore's
freeze, and is recorded in the marker as `refactors`.

### D6. The judge checks each item; one deterministic check helps

A round whose family holds a feedback fix unit with items taken but not yet addressed passes the judge a data block
`<l4:data kind="feedback">`. For each item it carries:
- id, kind and places;
- the quoted code;
- the text, and the WHEN/THEN or the variable.

The judge reply (SPEC §10.3) gains `feedback: [{id, addressed, evidence}]`, and `PROMPT_VERSION` becomes 7.

An item is **addressed** when every judge that received the block answers `addressed: true`. A missing answer counts as
`false`, with the evidence "not answered". A `config` item also needs NAME to appear in a non-test file changed by the
family. A missing NAME is a deterministic `not addressed`, and no judge answer can override it.

When an item is **not addressed**, it becomes a blocking finding (`source: "feedback"`, title
`FB-NNN not addressed: <evidence>`). The round fails into the next feedback fix unit.

When it is **addressed**, the round's evidence commit sets its Status `addressed`, writes the round and the short sha
in its *Outcome* block, and records `feedback.addressed`.

Rejected: asking the person a verdict question on every disagreement. It adds a wait for a check that the next round
does cheaply. The feedback round limit bounds the loop.

### D7. Content hash, not status, decides re-taking

`feedback.taken` records the sha256 of the item's human content: kind, places, env, when, then and text, with
whitespace normalised. An edit after the take makes the item takeable again (`feedback.changed`), whatever its Status.
This mirrors L4-QMD-006.

`withdrawn` before a take means the item is never taken. After a take, the item is no longer judged
(`feedback.withdrawn`). Tasks already written still run, because a fix unit is not unwound.

### D8. Their own round limit

A fix unit is a feedback fix unit when every blocking finding it consumes has `source: "feedback"`.
- `decide_fix` counts only the other fix units against `verifier.max_fix_rounds`.
- Feedback fix units count against `feedback.max_rounds` (default 5; 0 turns taking off).
- At the limit, with takeable items, the unit is `escalated` (exit 13) with the note "feedback round limit reached".
  `l4 resume --extend-feedback-rounds N` and the resume label add rounds through
  `budget.extended{feedback_rounds}`, as for fix rounds.

A round with both a red CI job and feedback is a normal fix round. Its feedback items are still marked taken.

At most `MAX_FIX_TASKS` (5) tasks fit in one fix unit. Feedback items past that stay takeable and are reported as
"waiting for the next round", never "not converted".

### D9. Kiro fix units (L4-KSP-005)

`KiroProvider.create_fix_unit` writes `.kiro/specs/<parent>-fix-<n>/` with:
- **`bugfix.md`** in Kiro's template (Context):
  - Current Behavior `1.n`: one per finding, its title and detail;
  - Expected Behavior `2.n`: one per criterion a task fixes, or per spec-gap or feedback scenario;
  - Unchanged Behavior: the unnumbered sentence "The system SHALL CONTINUE TO satisfy every other acceptance criterion
    of <parent>." (a numbered item would be a criterion no test can trace); `3.n` only for real `CONTINUE TO`
    scenarios.
- **`design.md`:** Overview, then the findings and decisions in the order of L4-VER-006.
- **`tasks.md`** in Kiro grammar:
  - one leaf per task, citing its `2.n`/`3.n` items with `_Requirements:_`;
  - chores carry `[chore]` and the finding ids in the title and cite nothing (TDD-exempt for SPEC-004, by the marker);
  - a one-wave `## Task Dependency Graph`.
- **`.config.kiro`:** `{"specId": <uuid4>, "workflowType": "requirements-first", "specType": "bugfix"}`. The
  `workflowType` value stays [I].
- **`.l4/fix.json`:** the fix marker.

When an Expected Behavior item restates a parent criterion, it carries the parent's alias and id. The harness reads it
as that criterion (same id), not as a new one, so traceability counts it once.

The provider validates the fix unit like any Kiro unit. On failure the folder is removed, as in OpenSpec. `decide_fix`
no longer escalates for Kiro.

### D10. Lessons from feedback

An item with `Lesson: yes` that is addressed in a PASS round becomes a lesson through `memory/curate.py`:
- **Origin:** `feedback`;
- **dedupe key:** `feedback-<first 12 hex of sha256(normalised text)>`, so the same request on two units reinforces one
  lesson;
- **scope:** the directories of its places (`<dir>/**`), else unscoped;
- **body:** the text, at most 600 characters;
- **source:** "human feedback FB-NNN (<unit> round N)".

This builds the fix-unit reading of L4-MEM-002 (a) for feedback only.

### D11. After the merge: follow-up units

`l4 feedback add` on a `merged` unit writes to that unit's folder on the checked-out base branch:
- OpenSpec: the folder under `openspec/changes/archive/` when archived;
- Kiro: `.kiro/specs/<name>/`.

The person merges that commit to the base by their usual route.

A base run then finds a merged unit with takeable items and no open follow-up. Planner action `follow_up` creates
`<name>-followup-<n>`:
- it is a new unit of the parent's framework, on a new unit branch from the base head;
- its tasks follow D2 and D4;
- its proposal or `bugfix.md` lists the items;
- its marker is `.l4/followup.json {parent, items: [{id, sha256}]}`.

The items are taken in the follow-up's ledger, and the follow-up's branch sets their Status `taken` in the parent's
file. The follow-up then runs the normal lifecycle, and its rounds judge the parent's items (D6). One follow-up per
parent is open at a time; newer items wait (`feedback.waiting{reason: "follow_up_open"}`). The parent's phase does not
change, so the lifecycle table gains no row.

### D12. Visibility and the hint

- **Sticky note.** A *Your feedback* section appears while the unit has any item, with one line per item: draft,
  submitted (waiting for the next round), taken into `<fix unit>`, waiting (fix unit full or follow-up open), addressed
  in round N at `<sha>`, not addressed in round N (evidence), invalid (the problem), or withdrawn.
- **Hint.** Every sticky note of a unit in `in_review` ends with one line:
  `To ask for changes: l4 feedback add --kind refactor|duplication|tests|config|behaviour --at FILE:LINE --text "…", then commit and push (docs/feedback.md).`
- **`verification.md`** gains `## Feedback` for the items taken or judged in the round.
- **`l4 status`** shows counts per state.
- **`docs/feedback.md`** is the how-to: one worked example per kind, what happens after the push, and the limits.

### D13. The command

```
l4 feedback add      --kind KIND --text TEXT|- [--title T] [--at PATH[:L[-L]]]… [--env NAME]
                     [--when W --then T] [--lesson] [--draft] [--unit ID]
l4 feedback list     [--unit ID] [--json]
l4 feedback show     FB-NNN [--unit ID] [--json]
l4 feedback submit   FB-NNN [--unit ID]
l4 feedback withdraw FB-NNN [--unit ID]
```

- **The unit** is `--unit`, else the unit named by the checked-out branch `l4/<framework>/<name>`. Otherwise it is a
  usage error that lists the units.
- **`--at`** is a repository-relative file in the working tree. It may not be under `.l4/` or inside any spec root, and
  its line range must exist. The command quotes those lines (at most 40 lines or 4,000 bytes, redacted) into a *Code*
  block. It repeats up to 5 times.
- **`--text -`** reads standard input.
- **Kind rules** (D2) are checked before anything is written. A bad item is exit 2 and writes nothing.
- **Output.** The command creates `feedback.md` when it is missing, appends the item, and prints the item id, the file
  and the exact `git add`/`git commit`/`git push` lines. It writes no other file and makes no network call.
- **Merged units** follow D11. An `abandoned` unit is exit 2.
- **`--json`** prints `{"schema": "l4/feedback@1", …}`.

## SPEC amendments required by this change

1. §2.1: a row for `l4 feedback`.
2. §3.2: `feedback: {max_rounds: 5}`.
3. §6: new subsection 6.3 `feedback.md` (grammar, ownership, ids, takeable).
4. L4-IMP-004: the contract's "Do not edit" list names `feedback.md`.
5. L4-VER-006: feedback findings, the fix task for each kind, the refactor freeze, items past the task cap wait.
6. L4-VER-007: feedback fix units are not counted, and get their own limit (D8).
7. §10.3: the judge reply's `feedback` array; `PROMPT_VERSION` 7.
8. L4-KSP-005: Kiro fix units as built (D9); the `workflowType` value stays [I].
9. L4-MEM-002: feedback lessons (D10).
10. L4-ARC-002: the *Your feedback* section and the hint (D12).
11. §12.1: the events `feedback.taken`, `.addressed`, `.not_addressed`, `.changed`, `.withdrawn`, `.invalid`,
    `.waiting` and `.follow_up`.
12. §21: delivery row 17 `human-feedback`.
13. `l4 resume`: `--extend-feedback-rounds N`.

## Risks

- **A refactor that needs a test change** (a renamed public function) cannot pass the freeze. The attempt fails and the
  item comes back not addressed. The person resubmits it as `behaviour`. docs/feedback.md says so.
- **Judge leniency.** A judge can call a weak change "addressed". Mitigations: the `config` deterministic check, the
  quoted code in the block, and the person's own review of the next hand-off. A wrong "addressed" costs one more item.
- **The Kiro template is read from the IDE bundle, not from a Kiro-made bugfix spec on disk.** The `workflowType` stays
  [I]. A Kiro release that changes the template would only change which headings L4 writes, because the harness
  validates its own fix units.
- **Follow-ups touch the base branch's units after merge.** One open follow-up per parent, and items taken only by
  content hash, keep two runs from doing the same item twice.
