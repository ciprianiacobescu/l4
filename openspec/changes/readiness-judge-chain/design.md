## Context

This section describes the readiness review in the 0.4.58 source. Each fact was read in the code for this design.

**`l4.yolo.readiness.review_plan_costed(app, cfg, plan, units, *, git, rev, ..., timeout_s=900, prior, fresh, sandbox_for, ...)`**

- It builds one `Subject` per unit that is not done and has a folder. It builds one per batch of more than one unit
  whose units (the ones not done) all have folders.
- It looks up each subject's `material_key(kind, key_text)` in `prior`. A reusable entry (no harness `schema`,
  `unit_missing` or `completeness` finding) is reused with `reused_from`.
- For the rest it creates one `Factory` and selects one judge:
  `factory.for_role("judges", f"plan:{id}", serves=JUDGE_ADAPTERS)`.
- It opens one `_Calls` for that judge, which holds the sandbox spec, the scratch folder and an `AgentJudge`. It then
  asks every subject in turn (units in plan order, then batches) with `_Calls.ask`.

**`_Calls.ask`**

- It makes at most two calls: the answer, and one repair prompt after a `schema_invalid` reply.
- On `limit` it raises `RoleLimit(result.run)`. On `timeout` or `error` it raises `JudgeFailed`, a `RoleUnavailable`.
  A length stop (`StructuredResult.length_stop`, set only by the opencode adapters) is one of these errors.
- A second `schema_invalid` returns `blocked("schema_invalid: ...")`.
- A timeout is not retried.

**The callers**

- `cycle._review` (the CI plan step) catches `(RoleLimit, RoleUnavailable)`. It logs `the review waits, no judge could
  run (...)`, sets `_judge_down` and returns. Nothing is recorded. The cost already spent is lost, because `cost` is a
  local variable of the function that raised.
- `commands.review` (`--local`) and `review_worktree.review` (`--worktree`, with or without `--record`) raise
  `L4Exit(WAITING_CAPACITY)` with "nothing was recorded".
- Each of the three passes a `sandbox_for(adapter, profile)` closure that remembers one profile and one sandbox label.
  `plan.reviewed{judge}` and the `--record` provenance read that one value.

**The fold and its readers**

- `fold_plan` (`state.py`) ignores an event type it does not know.
- These readers read `plan.reviewed` only:
  - `prior_entries`: the material key mapped to the newest reusable entry, with `at`;
  - `history` and `judged`: the findings history; `judged` drops reuses;
  - `rounds_not_ready`: the versions of a subject's text, used by `accept`;
  - `_review_view` and `_reviewed_current`: whether the review is current;
  - `accept.holds`.

**Selection and availability**

- `Factory.for_role` walks the chain with `FallbackSelector.select(role, chain, required=role in REQUIRED_ROLES, ...)`.
  The walk is probes (cached for `availability.cache_ttl`), cool-downs, `serves`, constraints and the login gate.
- `Factory.next_profile` walks from a position.
- `Factory.cool_limited(selected, run)` records a cool-down in the runner cache (`$L4_CACHE/availability.json`). That
  file is new on a hosted runner in every job [I: the CI cache keys hold the agent CLIs, not that file].
- `judge_sandbox.choose` raises `SandboxUnavailable` (exit 3) for a judge that cannot be sandboxed on this machine.

**The CI job's time**

- `orchestrator` calls `yolo_step(..., budget=job_remaining_s)` before `run_units`, and only `run_units` arms
  `l4.deadline`.
- The plan step has `self.budget()`, the seconds left before the soft deadline. Only the merge-window wait reads it.

**Configuration**

- `RolesCfg` has `implementer, clarifier, verifier_agent, judges, s1_judge, spec_writer, delegate`.
- `JUDGE_ROLES` (`config/roles.py`) is `("judges", "verifier_agent", "clarifier", "s1_judge")`. The skill's
  `yolo_preflight.py` holds a copy, and `test_yolo_preflight_script.py::test_the_constants_equal_the_harness` checks
  that the two are equal. `tests/unit/config/test_judge_roles.py` pins the load message.
- `YoloReviewCfg` has the material budgets and the accept settings. `DelegateCfg.timeout` (a duration of at least `1m`)
  is the precedent for a role's own call time.
- The doctor's DLG-001 compares `delegate.timeout` with `ci.time_budget` minus the margin.

## Goals / Non-Goals

**Goals**

- Readiness walks the chain (`plan_judges`, else `judges`) per subject: after an error, a length stop or a schema
  break, the next judge.
- A timeout behaves as in L4-VER-075.
- Answered subjects are kept, within the review and into the next run.
- A batch that does not fit is split, and the parts' verdicts are merged into one.
- An unfinished review is visible in `l4 yolo status` and the run log, with each judge and its failure.
- One configuration key per problem, with defaults that keep old configurations loading.

**Non-goals**

- Splitting a unit subject, or a part again.
- A per-profile timeout.
- Any change to unit verification.
- `l4 yolo go` reading `plan.review_incomplete` during its wait for CI.
- A prompt-version bump.

## Decisions

### D1. The review's chain

`review_chain(cfg) -> tuple[str, list[str]]` (in `readiness.py`) returns `("plan_judges", cfg.roles.plan_judges)` when
that list is not empty, else `("judges", cfg.roles.judges)`.

- A non-empty `plan_judges` replaces `judges`. The two lists are never joined: a consumer that wants a judge of
  `judges` in the review lists it in `plan_judges` too. Joining them would bring back the judge a consumer moved out of
  the review.
- `plan_judges` is not added to `l4.availability.errors.REQUIRED_ROLES`, which `test_shared_types.py` pins. The review
  selects one profile at a time (D2), and a selection that fails is handled the same way for a required role and an
  optional one. The only difference is that an optional role does not probe a remembered auth refusal again within
  `availability.auth_failure_ttl` (2m).
- `plan_judges` joins `JUDGE_ROLES`. It is placed after `judges`, and the load message names it. The load check, the
  preflight script's copy and CFG-011's list of kiro judges all follow.
- CFG-002 (`for role, chain in cfg.roles`) and ENV-004 (`for role in RolesCfg.model_fields`) cover it with no change.
- `l4 doctor --live` (LIVE-001) probes it when it is not empty. A failure there is a warning, like the delegate's.
- `l4 probe --role plan_judges` works through `RolesCfg.model_fields`.

### D2. The walk

A **call** is one subject (a unit, or a batch asked whole) or one part of a batch (D6). Each call has a name (`<unit>`,
`batch:<id>`, `batch:<id>/<unit>`, `batch:<id>/summary`) and a material key.

The review keeps this state:

- `opened`: profile name mapped to its `_Calls` (a judge selected and its sandbox made);
- `unusable`: profiles that failed selection or their sandbox, with the failure;
- `out`: profiles discarded for the rest of the review (`error`, `limit`);
- per call, `avoid`: profiles discarded for that call (`length`, `schema_invalid`).

The judge of a call is the first name in `order(call)` that is not in `unusable`, `out` or `avoid`:

- If it is in `opened`, it is used.
- Otherwise it is opened with a new `Factory.for_profile(role, unit, name, *, serves)`. That method runs the selector on
  the one-element chain `[name]` with `required=False` and `record_unavailable=False`, and returns a `Selected` with
  `request` set, so `cool_limited` works.
  - On `RoleUnavailable` the name goes to `unusable` with kind `unusable` and the exception's text as the detail.
  - On `SandboxUnavailable` from `sandbox_for` it goes there with kind `sandbox`.

`order(call)` is the chain with the names in `failed_before[call.material]` moved to the end, keeping chain order among
them (D5).

Opening one profile at a time keeps the selector's skip lines to one per profile per review, because a profile in
`unusable` is never tried again. Calling `for_role` with a constraint would print a skip line for every vetoed profile
at every selection.

After a call, by `StructuredResult.status`:

| outcome | effect |
|---|---|
| `ok` | answered |
| `schema_invalid` twice (today's repair) | `avoid += judge`, failure `schema_invalid`; next judge |
| `error` with `length_stop`, call not split | `avoid += judge`, failure `length`; next judge |
| `error` with `length_stop`, a batch call that can be split | split (D6), same judge first |
| `error` without `length_stop` | `out += judge`, failure `error`; next judge |
| `limit` | `factory.cool_limited(selected, run)`, `out += judge`, failure `limit`; next judge |
| `timeout`, a batch call that can be split | split (D6), same judge first, no failure recorded |
| `timeout`, anything else | failure `timeout`; the review stops (D3) |

When no judge is left for a call:

- If `schema_invalid` is among that call's failures, the call's verdict is
  `blocked("schema_invalid: <the last detail>")`, as today. The review goes on with the next call. This keeps
  SCN-YOLO-08 for a chain of one judge.
- Otherwise the call has no answer, and the review stops with reason `no_judge`. Precedence: a call that any judge
  answered off the schema is BLOCKED, whatever the later judges did. A judge did answer it, and a BLOCKED verdict lets
  the review finish and shows the person a finding.

The three discard scopes have reasons:

- An error says the judge does not work now.
- A length stop or a schema break depends on the material: the same judge may answer the next, smaller subject.
- A limit is a fact about capacity, which the availability store already owns.

The selections made at the start are recorded as failures with an empty `subject` (kind `unusable`). An example is a
first judge whose hello failed. This is the case the live review hid.

The walk adds no independence rule (L4-YOLO-095). "The next independent judge" here means the next profile of the
chain that is not discarded.

### D3. The timeout

**The key.** `yolo.review.timeout: Duration = "15m"`, with a validator of at least 60 s (message
`yolo.review.timeout must be at least 1m`). It lives in `yolo.review`, where the review's other settings are.
`delegate.timeout` is the precedent.

- `review_plan_costed(timeout_s: int | None = None)` reads `duration_seconds(cfg.yolo.review.timeout)` when it is None.
  The three callers pass nothing.
- `DEFAULT_TIMEOUT_S` stays at 900 as the value of the default, used only by tests.

**A timeout.**

- It is never repeated with the same prompt: one call, as today.
- A whole batch that can be split is split, as L4-VER-071 splits on a timeout.
- Any other timeout stops the review for this run, with failure `timeout` and reason `timeout`. The next judge is not
  asked, because it would spend its own timeout on the same material in the same job (L4-VER-075).
- In the next run, D5 asks that call of the other judges first. Mirroring L4-VER-075 alone would make every run start
  with the judge that timed out.

**The job's time.** `review_plan_costed(time_left: Callable[[], float | None] | None = None)`. The CI step passes
`self.budget`; the commands pass None.

- Before every judge call, the repair prompt after a schema break included, when `time_left()` is not None and is less
  than `timeout_s`, the review stops with reason `job_time`. That call gets no failure entry, since no judge failed. The calls not asked are in `left`.
- The soft-deadline margin that `job_remaining_s` subtracts already leaves room to write the ledger, so no extra
  reserve is needed.

**Doctor.** CFG-012 gains a warning, the same way DLG-001 checks `delegate.timeout`:

- when `duration_seconds(yolo.review.timeout) >= budget - soft_deadline_margin`, with `budget` the `ci.time_budget` when
  it is a duration, else (`auto`) the job's timeout that `shortens_job` reads (`job_timeout`; nothing is said when it is
  unknown),
  it warns `yolo.review.timeout (<t>) is not less than ci.time_budget (<b>) minus ci.soft_deadline_margin (<m>): no
  readiness call can start in a CI job`;
- the fix line says to lower the timeout or raise the budget;
- a CFG-012 that would fail keeps failing, with this warning added to its message.

### D4. One review, attributed per entry

- A review that finishes is one `plan.reviewed`, as today.
- `Verdict` gains `judge: str | None = None`, the profile that answered. For a batch in parts, `judge` is the distinct
  profiles of its parts in part order, joined by `, `.
- `Verdict` also gains `parts: tuple[tuple[str, Verdict], ...] = ()`.
- A reused verdict keeps the `judge` of the entry it reuses, when that entry has one.
- `cycle._entry`, `commands._verdict_json`, `review_worktree._entry` and `_recorded` write `judge`, and `parts` for a
  batch in parts.
- The event carries:
  - `judge`: the profile of the first judged entry, as before, so readers that know one string keep working;
  - `judges`: the distinct profiles that answered in this review, in the order they first answered (a reused entry, and
    a reused part of a batch in parts, name none; the batch entry's own `judge` still lists all its parts' profiles);
  - `failures`: `[{profile, subject, kind, detail}]`, only when there is at least one.
- `ReviewResult` gains `failures: tuple[JudgeFailure, ...] = ()`.
- `JudgeFailure(profile, subject, kind, detail, material=None)` lives in `model.py`. `detail` is redacted and cut to
  its first line and 300 characters. `material` is the call's key, used by D5.
- The `--worktree` `_Sandboxes` keeps a dict from profile to label. `--record` writes `sandbox` per entry from it.

### D5. The memory between runs

`findings.failed_before(events, prompt_version) -> dict[str, list[str]]` maps a material key to the profiles that
failed it. Its sources are the `failures` of every `plan.review_incomplete` after the plan's latest `plan.reviewed`,
of the given prompt version, whose `kind` is `error`, `length`, `schema_invalid` or `timeout` and that have a
`material`. Failures accumulate across those events, so two runs that each time out on another judge do not swap back
and forth between them.

- The CI step, `--local` and `--worktree` pass it to `review_plan_costed(failed_before=...)`.
- A `plan.reviewed` resets the memory.
- A changed material has a new key, so no memory applies to it.
- `unusable`, `sandbox` and `limit` are left out: the selection already skips those profiles while they fail.

The ledger holds this memory, not the availability store, because the runner cache of a hosted runner is new in every
job [I].

### D6. A batch in parts

**When.** A batch subject whose shown units (`left`, the units not done) are two or more is split in three cases:

1. `yolo.review.max_batch_chars > 0` (the default is `0`: no pre-split) and `len(subject.user) > max_batch_chars`;
2. any of its parts' material keys was kept by a `plan.review_incomplete` after the plan's latest `plan.reviewed`
   (`findings.kept_keys`, passed as `kept`; a `--worktree` dry run adds the parts of its local cache, which no
   `plan.reviewed` ends). A part that only a `plan.reviewed` holds in `prior` is reused when the batch is split, and
   never splits it: without this a batch split once stays split, and `max_batch_chars: 0` would not turn the split off
   after a prerequisite changed;
3. its whole call ends `error` with `length_stop`, or `timeout`, and the same judge is asked the parts first.

In cases 1 and 2 the whole batch is never asked. A batch whose whole key is in `prior` is reused whole, as today.

**The parts.** For the units `U1..Un` of the batch's shown units, in plan order:

- **Part `batch:<b>/<Ui>`.** It is built by `_batch_part(plan, batch, unit, folders, siblings, deps, delivered)` with the
  material template:
  - `SUBJECT_KIND` is `batch`. `SUBJECT_ID` is the batch id in a data block, as today.
  - `ENTRY` is the batch's entry block, then `TASKS_NOTE`, `GROUPING_NOTE` when the batch only groups units, then
    `PART_NOTE_UNIT`.
  - `DEPENDENCIES` are the prerequisites of `Ui` outside the batch, each at the dependency budget, then the batch
    prerequisites and the delivered note.
  - `FOLDERS` are the folder block of `Ui` in full, as `_batch_subject` shows a folder, then, for each other `Uj`, a
    `folder` data block labelled `<Uj> (<path>), read in part` with the blocks of
    `read_folder(git, rev, folder, budget=SIBLING_CHARS, file_budget=SIBLING_CHARS, order="prerequisite")`.
- **Part `batch:<b>/summary`.** `ENTRY` is as above but ends with `PART_NOTE_SUMMARY`. `DEPENDENCIES` is one data block
  `batch prerequisites outside it` that lists their names, then the batch prerequisites and the delivered note.
  `FOLDERS` is every `Uj` read in part as above.

`SIBLING_CHARS = 6_000` is a module constant.

The part notes are harness text. They contain no ids:

- `PART_NOTE_UNIT`: "This call reviews one part of the batch: the unit whose folder is shown in full, with each other
  unit of the batch read in part (its first 6,000 characters, in the order proposal, requirements, specs, bugfix,
  design, other files, tasks). Each unit is also reviewed on its own, and the batch as a whole from every unit read in
  part, in other calls. Report what lies between the unit shown in full and the other units: contradiction,
  duplicate_scope, missing_dependency and the interfaces they share, and batch_acceptance."
- `PART_NOTE_SUMMARY`: "This call reviews the batch as a whole from every unit read in part (its first 6,000
  characters, in the order proposal, requirements, specs, bugfix, design, other files, tasks). Each unit is also
  reviewed on its own, and in full with the others read in part, in other calls. Report what lies between the units:
  contradiction, duplicate_scope, missing_dependency and the interfaces they share, and batch_acceptance."

**What a part can see.** A unit part sees the full text of one unit against the first 6,000 characters of every sibling:
usually the proposal and the start of the specs. The summary part sees every unit at that depth.

- What stays caught: a contradiction or a duplicate between one unit's detail and what a sibling states up front, a
  dependency a sibling's proposal implies, and the batch outcome.
- What is lost: a defect visible only when two units' designs are read in full together. The `missing` line of the
  merged verdict says so: "no call saw two units of the batch in full together".

**A part's `Subject`.**

- `kind="batch"` and `id=<batch>` (the prompt and `_amend` treat it as a batch).
- A new field `part: str = ""` (`unit id` or `summary`). `name` becomes `batch:<id>/<part>` when `part` is set.
- `left_out`, `not_shown` and `not_in_full` are those of `Ui` (unit part) or empty (summary).
- `groups_only` is the batch's.
- `key_text` is the text without the delivered block, as today. The material key is
  `material_key("batch-part", key_text)`.
- The fingerprint inside `material_key` is unchanged, so every existing key stays valid. A change to a part note changes
  only the part keys, through `key_text`.

**Merging.** When every part has a verdict (answered, reused, or BLOCKED for a schema break):

- `merge_parts(raw_verdicts, cause) -> Verdict` takes the verdicts as `verdict_of` returned them, not amended, in part
  order.
- before the merge, a part whose verdict is NEEDS_REVISION and names no finding gets the harness finding `verdict` (the text
  `_amend` gives it, from the part's own `missing`). `_amend` adds that finding only to a verdict with no finding at all,
  so after the merge another part's minor finding would hide it, and "all minor" would give READY;
- verdict: the worst, by `{"BLOCKED": 2, "NEEDS_REVISION": 1, "READY": 0}`;
- findings: concatenated, with a repeated `(criterion, severity, text)` kept once, at its first place;
- assumptions and missing: concatenated, with an exact repeat kept once;
- then one `missing` line: `judged in <n> parts (each unit in full with the other units read in part, and every unit
  read in part): no call saw two units of the batch in full together; why: <cause>`.
- Then `_amend(merged, whole_batch_subject)` runs once. The whole batch's `left_out`, `not_shown` and `not_in_full` are
  the union of the unit parts', so a `material_cut` of a unit's folder blocks the batch exactly as before.
- After `_amend`, one harness finding is appended: `IN_PARTS_FINDING`, criterion `parts`, severity `minor`, text `this
  batch was reviewed in parts: no judge saw two units' full text together, so defects visible only across units may be
  missed`. It comes after `_amend` so that no rule of `_amend` reads it (a verdict of only minor findings would become
  READY, and a BLOCKED batch with its findings moved would lose its `not findings` test). It accompanies the `missing`
  line. A minor finding blocks nothing, so a READY batch stays READY. `l4 yolo findings` shows a batch that carries it
  even when it is READY, and `l4 yolo status` lists the batches of the current review that were judged in parts.
- The batch verdict's `material` is the whole batch's key. Its `parts` are `(part name, part verdict with material,
  judge, reused_from)`.

A part that is reused keeps its recorded verdict. A part entry in `prior` is always an unamended entry, because parts
are recorded raw: `parts` rows hold what `verdict_of` returned, with `material` and `judge`.

**The cause** is one of:

- `its material has <c> characters, over yolo.review.max_batch_chars (<m>)`;
- `an earlier review run answered a part of it`;
- `the whole batch stopped at the output limit of <profile>`;
- `the whole batch timed out on <profile>`.

When more than one applies, the first in this order is used.

**No unit split.** A unit subject has no siblings to read in part, and its material is bounded by `max_folder_chars`
plus its prerequisites' budgets. A length stop there goes to the next judge.

### D7. The record of a review that does not finish

`readiness.ReviewIncomplete(JudgeFailed)` carries:

- `answered: dict[str, Verdict]`: the calls judged in this run, parts included. Reuses are left out, and so are verdicts
  with a harness finding;
- `left: tuple[str, ...]`;
- `failures: tuple[JudgeFailure, ...]`;
- `cost: float`;
- `reason: Literal["no_judge", "timeout", "job_time"]`.

Its message is `judge_error: the review is incomplete (<reason>): <a> answered, <l> left; <profile>: <subject>: <kind>:
<detail>; …`. As a `RoleUnavailable`, it still reaches every existing `except`.

`review_plan_costed` raises it after its loop whenever a call has no answer. It raises it also when no judge can be
opened at all: then `answered` is empty and the failures are the `unusable` ones.

The CI step (`cycle._review`) catches `ReviewIncomplete` before `(RoleLimit, RoleUnavailable)`. It:

- logs one line per failure, then the summary line;
- sets `_judge_down`;
- writes, through a `_write_incomplete(ctx, events, digest)` that handles `PlanMoved` the way `_write_review` does:
  - `plan.admitted`, under the condition the review that finishes uses: the state is not already `admitted` or
    `reviewed` with this plan digest and order. The admission passed, and a first review that does not finish would
    otherwise leave the plan `new`;
  - `plan.review_incomplete{plan_digest, prompt_version: PROMPT_VERSION, source: "ci", target_rev, reason, answered:
    {name: _entry(v, judge=..., digest=...)}, left, failures: [...], cost_usd}`;
  - when the cost is more than 0, the running-total `plan.charged{unit: REVIEW_KEY, attempt: 0}`.

On a lost lease, it drops the write when a `plan.reviewed` or another `plan.review_incomplete` arrived since it read
the ledger.

**Dedupe.** `findings.latest_incomplete(events, prompt_version)` returns the newest `plan.review_incomplete` after the
latest `plan.reviewed`. Nothing is written when all of these hold:

- that event exists and has the same `plan_digest` and `reason`;
- the set of `(profile, subject, kind, material)` of its failures equals this run's (the material key is part of it: a
  judge that fails a unit again after a person changed the unit is new, and `failed_before` learns the new key only from
  the event);
- `answered` is empty;
- the cost is 0.

**How each reader treats `plan.review_incomplete`:**

| reader | change |
|---|---|
| `fold_plan` | none: the event is unknown to it and ignored |
| `_reviewed_current`, `_review_view`, activation, `accept.holds`, `rounds_not_ready` | none |
| `prior_entries` | also reads its `answered` entries, and the `parts` rows of `plan.reviewed` batch entries (same version, same harness-finding rule, `at` = the event's `at` or the row's `reused_from`) |
| `history` | also yields its `answered` entries whose name is a unit or `batch:<id>` (not a part), with `source` from the event |
| `failed_before`, `latest_incomplete` | new (D5, dedupe) |
| `l4 yolo status` | the `incomplete` block |

An entry the final review takes from it is a reuse there. Its judgement stays in the history where it was made, so
`judged()` dropping reuses loses nothing. `rounds_not_ready` reads `plan.reviewed` only. The reused entry carries the
unit digest, so the version counts once there, as any reuse does.

**Status.** `commands` builds the status document and finds `latest_incomplete`.

- When `out["review"]["state"]` is not `current` and the event is newer than the latest `plan.reviewed`,
  `out["review"]["incomplete"]` is `{at, source, reason, answered: len, left: len, failures: [...], cost_usd}`.
- `_render` prints, after the review line:
  - `    incomplete <ago> ago (<source>, <reason>): <a> answered and kept, <l> left`;
  - one line per failure, `      <profile>: <subject or "selection">: <kind>: <detail>`;
  - `      fix: <text>`, from a dict keyed by reason.

**`--local`.** `commands.review` catches `ReviewIncomplete` before `RoleUnavailable`. It appends
`plan.admitted` (same condition), `plan.review_incomplete{source: "local", by: ctx.who(), ...}` and the charge, prints the lines, and raises
`L4Exit(WAITING_CAPACITY, "review: the review is incomplete: …")`. `--worktree --record` does the same with `source:
"worktree"`.

**The `--worktree` dry run.** It appends the answered entries to its cache, one line per call with `kind` `unit`,
`batch` or `batch-part`. It writes nothing to the ref, and exits 12 with the lines.

### D8. Prompt version and keys

- The prompt of a subject that is not split is the same string as in 0.4.58, so its `material_key` is the same and
  `PROMPT_VERSION` stays 4.
- An upgrade therefore asks no new review. A batch over the bound is split only when it is reviewed again for another
  reason.
- A test holds the material key of a fixed unit and a fixed small batch equal to the value 0.4.58 computes. The expected
  value is taken by running the test once on the 0.4.58 code, before the change.

### D9. The API the callers see

```python
def review_plan_costed(app, cfg, plan, units, *, git, rev, adapters=None, digest_of=None, sandbox=None,
                       timeout_s: int | None = None, done=(), delivered={}, prior={}, fresh=(), revs=None,
                       budgets=None, sandbox_for=None, refuse_fresh_of_prior=False,
                       time_left: Callable[[], float | None] | None = None,
                       failed_before: Mapping[str, Sequence[str]] = {}) -> tuple[ReviewResult, float]
```

- It returns as today when every subject has a verdict. `ReviewResult.failures` lists what was discarded on the way.
- It raises `ReviewIncomplete` otherwise.
- It raises `FreshRefused` and `RevisionMissing` as today.
- It no longer raises `RoleLimit` or a bare `JudgeFailed`. `JudgeFailed` stays as the base class and for the tests that
  raise it through a monkeypatch.
- `fresh` naming `batch:<id>` also skips the prior entries of that batch's parts.
- `review_plan` (the wrapper without the cost) is unchanged in shape.

`Budgets` gains `batch: int` (`max_batch_chars`).

### D10. Alternatives rejected

- **Joining `plan_judges` and `judges`.** A judge moved out of the review would come back as its fallback.
- **`plan_judges` in `REQUIRED_ROLES`.** That pins a set a test holds, changes `waiting_capacity` semantics no one asked
  for, and gains only a re-probe of an auth refusal.
- **A per-profile `timeout`.** Every role would read it, unit verification included, and no profile has one today.
- **`roles.plan_judges_timeout` or a top-level key.** The review's settings are under `yolo.review`.
- **Retrying a timeout, or asking the next judge after one.** This spends a second timeout in the same job. L4-VER-075
  holds the round for the same reason. D5 moves the next run to another judge instead.
- **The availability store as the memory between runs.** It is new in every hosted job [I], and a timeout is no
  cool-down.
- **A partial `plan.reviewed`.** The fold would replace `state.review` and set the status to `reviewed` with subjects
  missing. An older harness would read it as a review.
- **Not keeping answers across runs.** Every failed run would pay for every unit again.
- **Splitting a unit subject by halves of its criteria (as L4-VER-071).**
  - No unit subject has stopped at the limit [V: the live stops were batches].
  - A readiness verdict weighs all criteria together.
  - L4-VER-071 notes that a reasoning model whose thinking fills the limit is not helped by fewer criteria.
  - This is an open question.
- **Halving a batch's units recursively.** It needs depth bookkeeping and gives no fixed size. Per-unit parts are the
  smallest unit of material and need no second level.
- **Only a summary part.** That is one call, but no unit would be read in full against its siblings.
- **Merging amended part verdicts.** `_amend` would run once per part, and its rules (all minor findings make READY, a
  NEEDS_REVISION with no finding gets one) would apply to fragments.
- **Bumping `PROMPT_VERSION`.** CI would review every plan that is not yet active again, at the consumer's cost, for
  prompts that did not change.
- **A bound from `Profile.context_window`.** The key is optional and rarely set, and the live stop was the output limit,
  not the window.
- **A constant bound.** The other review budgets are keys, and a consumer whose judge stops on smaller batches needs to
  lower it.

## Risks / Trade-offs

- **A batch in parts sees less than a whole batch.** A defect visible only when two full designs are read together is
  missed. Mitigation: the merged verdict says so in `missing`, and a consumer can raise `max_batch_chars`.
- **More calls.** A batch of n units in parts costs n + 1 calls instead of 1, and the parts are charged to the plan.
- **A part over the bound is asked anyway.** For example, one huge unit with many siblings. A length stop there goes to
  the next judge, and no third level exists.
- **The default bound is `0`: no pre-split.** A bound that splits before any call is a guess, since no measurement
  links a size to an output limit, and a batch in parts sees less than a whole batch. So the whole batch is asked
  first, and split only after its call ends with a length stop or a timeout, or for a part an incomplete review kept. A
  consumer whose judge stops silently (an adapter that reports no length stop) sets a positive bound.
- **A batch in parts is visible.** Its verdict always carries a minor harness finding of criterion `parts`, added after
  `_amend` so it cannot change the verdict, and `l4 yolo findings` and `l4 yolo status` show it.
- **Asking another judge first after a failure assumes the failure follows the judge and the material.** A judge that
  failed for a passing cause waits until the others have failed too.
- **An `error` discards the judge for the whole review, even when the error was the material's.** One example is a
  request too large for one batch. The next judge takes the rest.
- **`job_time` with a short CI budget and a long timeout can end every review at once.** CFG-012 warns about this.
- **Ledger growth.** The dedupe covers a review that fails the same way every run. A review that makes progress each
  run writes one event per run, as it should.
