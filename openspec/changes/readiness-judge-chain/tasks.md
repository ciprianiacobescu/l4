Read `design.md` first. It names every function, field and rule. Read L4-YOLO-095 to L4-YOLO-100 in `docs/SPEC.md` too
(search `L4-YOLO-095`), and the scenarios SCN-YOLO-261 to 282.

Rules for every task:
- Write the tests first, run them, and see them fail.
- Then write the code, and run the tests the task names.
- Run only the test files named. Never the whole suite.
- Never use a `while pgrep` loop.

**Test techniques.** The readiness tests use these fixtures and fakes:
- The fixtures of `tests/unit/yolo/yolo_review_world.py` (`World`, `make_cfg`, `plan_of`, `SPEC_A`, `SPEC_B`). See
  `tests/unit/yolo/test_yolo_readiness_review.py` for the call shape.
- For the CI step, `tests/unit/yolo/yolo_cycle_world.py` (`CycleWorld`, `ev`, `READY`, `unit_id`). See
  `tests/unit/yolo/test_yolo_cycle_review.py`.
- A judge is a scripted `l4.agents.fake.FakeAdapter`. Every profile whose adapter is `fake` shares the one script given
  as `adapters={"fake": fake}`, and each call takes the next `Step`.
- To give two judges separate scripts or separate probes, inject a second `FakeAdapter` under a real adapter name, as
  `tests/unit/llm/test_agent_judge_roles.py::test_a_failing_probe_is_unavailable` does. For example,
  `adapters={"fake": ok, "claude-code": other}` with the profile `j1: {adapter: claude-code, vendor: anthropic}`.
- A failing hello is `FakeAdapter([], probes={"hello": ProbeResult("hello", False, reason="hello refused")})`.
- A usage limit is `Step(status="quota", limit=LimitSignal(tool, model, kind, resets_at, source, raw_excerpt))`
  (`l4.agents.base.LimitSignal`; `kind="usage_limit"`, `resets_at` tz-aware UTC).
- Assert which judge answered through the entry's `judge`, and through which `FakeAdapter.requests` grew.

## 1. Configuration and the judge roles (D1, D3; L4-YOLO-095, L4-YOLO-097)

- [x] 1.1 Write the tests first, in a new `tests/unit/config/test_plan_judges_config.py`:
  - `RolesCfg().plan_judges == []`, and a configuration without the key loads.
  - `"plan_judges" in l4.config.roles.JUDGE_ROLES`, placed right after `"judges"`.
  - SCN-YOLO-262, the load part: a `command` profile in `roles.plan_judges` fails the load with
    `profiles.<name> is in roles.plan_judges, but its adapter command cannot judge`. The message names
    `roles.plan_judges` in its role list.
  - SCN-YOLO-270, the load part:
    - `YoloReviewCfg().timeout == "15m"`;
    - `yolo: {review: {timeout: 30s}}` fails with `yolo.review.timeout must be at least 1m`;
    - `30m` loads.
  - `YoloReviewCfg().max_batch_chars == 0` (changed from 160,000 by the review); `0` loads; `-1` fails.
  - `Budgets.of(cfg).batch` equals `max_batch_chars`.

  Then update the tests that pin the old text: `tests/unit/config/test_judge_roles.py` (the message) and
  `tests/unit/yolo/test_yolo_preflight_script.py::test_the_constants_equal_the_harness` and
  `::test_a_command_judge_fails_with_the_harness_text`. Run them and see them fail.

  Two tests already fail on the spec commit, as on the spec commit of `delegate-batch`:
  `tests/unit/config/test_schema.py::test_reference_config_validates_with_placeholder_commit` and
  `tests/unit/docs/test_delegate_docs.py::test_the_reference_configuration_has_the_delegate_section_and_profiles`. SPEC
  §3.2 holds `roles.plan_judges`, `yolo.review.max_batch_chars` and `yolo.review.timeout`, and the schema refuses extra
  keys. Task 1.2 makes them pass. Do not edit SPEC §3.2 to make them pass.
- [x] 1.2 Then change the code:
  - `src/l4/config/schema.py`:
    - add `plan_judges: list[str]` to `RolesCfg`, after `judges`, with a comment `optional (L4-YOLO-095): the
      readiness review's chain; empty: judges`;
    - add `max_batch_chars: int = Field(default=0, ge=0)` and `timeout: Duration = "15m"` to `YoloReviewCfg`,
      with a `field_validator` like `DelegateCfg._timeout`;
    - list `roles.plan_judges` in the message of `_judge_roles_can_judge`.
  - `src/l4/config/roles.py`: `JUDGE_ROLES`.
  - `src/l4/yolo/readiness.py`: `Budgets.batch`.
  - `plugins/l4/skills/l4/scripts/yolo_preflight.py`: `JUDGE_ROLES` and its message.

  Run `uv run --frozen pytest tests/unit/config/test_plan_judges_config.py tests/unit/config/test_judge_roles.py
  tests/unit/config/test_schema.py tests/unit/config/test_schema_yolo.py tests/unit/docs/test_delegate_docs.py
  tests/unit/yolo/test_yolo_preflight_script.py tests/unit/agents/test_shared_types.py -q`.
- [x] 1.3 Doctor. Write the tests first:
  - SCN-YOLO-262, the doctor part, in `tests/unit/doctor/test_checks_config.py`: an undefined profile in
    `roles.plan_judges` fails CFG-002, naming `roles.plan_judges`. This needs no code change; it shows CFG-002 covers
    the key.
  - In `tests/unit/doctor/test_checks_cfg_011.py`: a `kiro-cli` profile in `roles.plan_judges` only is listed by
    CFG-011.
  - SCN-YOLO-272, the doctor part, in `tests/unit/doctor/test_checks_cfg_012.py`:
    - with `ci.time_budget: 20m`, `ci.soft_deadline_margin: 10m` and `yolo.review.timeout: 15m`, CFG-012 warns with
      `yolo.review.timeout (15m) is not less than ci.time_budget (20m) minus ci.soft_deadline_margin (10m)`;
    - `yolo.review.timeout: 5m` passes;
    - `time_budget: auto` passes when the job's timeout is unknown or fits (the review adds the case of a known job timeout
      that does not fit).
  - In `tests/unit/doctor/test_checks_agents.py`: with `roles.plan_judges` set, LIVE-001 probes it, and a failure is
    a warning, not an error. With it empty, LIVE-001 is as before.

  Then change the code:
  - `src/l4/doctor/checks_config.py`: `_cfg_011` reads `[*judges, *plan_judges, *clarifier]`; `_cfg_012` gets the
    warning of D3.
  - `src/l4/doctor/checks_agents.py`: in `_live_001`, `plan_judges` joins the probed roles as an optional role when it
    is not empty, the way the delegate does.

  Run those four test files.

## 2. The factory and the fake (D2)

- [x] 2.1 Write the tests first, in a new `tests/unit/agents/test_factory_for_profile.py`:
  - `Factory.for_profile("judges", "plan:p1", "j2", serves=JUDGE_ADAPTERS)` on the chain `[j1, j2]` returns `j2`. It
    never probes `j1`: the `FakeAdapter` under j1's adapter name records no probe.
  - It sets `request`, so `factory.cool_limited(selected, run)` works on its result.
  - A profile whose hello fails raises `RoleUnavailable` whose text holds the hello's reason.
  - A name that is not in the role's chain raises `ValueError`.

  Also write a test in `tests/unit/agents/test_fake.py` that `Step(status="error", length_stop=True)` gives
  `RunResult.length_stop`. Run them and see them fail.
- [x] 2.2 Then add `for_profile` to `src/l4/agents/factory.py`. It runs `self._selector().select(role, [name],
  required=False, serves=serves, record_unavailable=False)`, builds the `Selected` as `for_role` does with
  `request=SelectionRequest(role, unit, serves, ())`, and appends `availability.selected` when there is an event sink.
  Add `length_stop: bool = False` to `l4.agents.fake.Step` and pass it to `RunResult`. Run the two files and
  `uv run --frozen pytest tests/unit/agents/test_factory_select.py tests/unit/agents/test_factory_next_profile.py -q`.

## 3. The walk of the chain (D2, D3, D4, D5; L4-YOLO-095, -096, -097)

- [x] 3.1 Write the tests first, in a new `tests/unit/yolo/test_yolo_readiness_chain.py`. Call `review_plan_costed`
  directly, as `test_yolo_readiness_review.py` does:
  - SCN-YOLO-261: `roles.judges: [j-unit]` and `roles.plan_judges: [j-plan]`, with separate fakes. Only the fake of
    `j-plan` is asked, and the verdict's `judge == "j-plan"`. Also check that `review_chain(cfg)` gives `("judges",
    [...])` without the key and with `[]`.
  - SCN-YOLO-263: j1's hello fails. j2 answers every subject. `result.failures` holds one `JudgeFailure(profile="j1",
    subject="", kind="unusable")` whose detail holds the hello's reason.
  - SCN-YOLO-264: units A and B in batch b1, chain `[j1, j2]`. j1 answers A and ends `error` on B; j2 answers B and the
    batch. Check:
    - `judge` per verdict;
    - `failures == (JudgeFailure("j1", B, "error", ...),)`;
    - j1's fake got exactly 2 requests;
    - the returned cost sums all four calls (`Step(cost_usd=...)`).
  - SCN-YOLO-265: j1's two replies to A break the schema (`Step(final_text="x")` twice) and j1 answers B; j2 answers A.
  - SCN-YOLO-266, all three cases. The third raises `ReviewIncomplete` with `reason == "no_judge"`, `left` holding A,
    and `answered` empty. Check that it is a `JudgeFailed` and a `RoleUnavailable`.
  - SCN-YOLO-267: j1's call on A ends `Step(status="quota", limit=LimitSignal("fake", None, "usage_limit", <now + 2h>,
    "test", ""))`. Check:
    - the factory's availability store (pass an `AvailabilityStore` on a temp path through the cache root, or read
      `$L4_CACHE/availability.json`) holds j1's cool-down;
    - j2 answers A and B;
    - no `RoleLimit` is raised.
  - SCN-YOLO-268: pass `failed_before={<material key of A>: ["j1"]}` (compute the key with `material_key("unit",
    subject.key_text)`, or take it from a first run's `verdict.material`). A is asked of j2 first and B of j1 first.
  - SCN-YOLO-270, the request part: the fake's `requests[0].timeout_s` is 1800 with `yolo.review.timeout: 30m` and 900
    without the key.
  - SCN-YOLO-271, the function part: j1 answers A and times out on B (`Step(status="timeout")`). `ReviewIncomplete`
    has `reason == "timeout"`, A in `answered`, B and the batch in `left`, and j2's fake got no request.
  - SCN-YOLO-272, the function part: `time_left=lambda: 600.0` with the default timeout. No request is made, and
    `ReviewIncomplete(reason="job_time")`.
  - SCN-YOLO-276, the last clause: a unit whose reply ends `error` with `length_stop=True` goes to j2, with failure kind
    `length`, unsplit.
  - An empty chain still raises `RoleUnavailable` and is not a `ReviewIncomplete`. The existing
    `test_no_judge_profile_is_role_unavailable` covers this.

  Run them and see them fail.
- [x] 3.2 Then change `src/l4/yolo/model.py`:
  - `Verdict.judge: str | None = None`;
  - `Verdict.parts: tuple[tuple[str, "Verdict"], ...] = ()`;
  - `ReviewResult.failures: tuple[JudgeFailure, ...] = ()`;
  - the frozen dataclass `JudgeFailure(profile: str, subject: str, kind: str, detail: str, material: str | None =
    None)`.
- [x] 3.3 Then change `src/l4/yolo/readiness.py`:
  - `review_chain(cfg)`;
  - `ReviewIncomplete(JudgeFailed)`, with its attributes and message (D7);
  - the walk of D2: `opened`, `unusable`, `out`, the per-call `avoid` and `order(call)`, using `Factory.for_profile`
    and `cool_limited`;
  - `_Calls.ask` returns a status instead of raising, for example `(Verdict | None, cost, StructuredResult)`, so the
    walk decides;
  - the new parameters `timeout_s=None`, `time_left` and `failed_before` (D9);
  - `ReviewResult.failures`, and `judge` on every judged verdict;
  - `_reused` keeps the entry's `judge`.

  Rules for the rewrite:
  - Keep `JudgeFailed` and the module docstring's R9 sentence, rewritten for the chain.
  - Keep the order: units first, in plan order, then batches.
  - A `SandboxUnavailable` from `sandbox_for` makes the judge `unusable` with kind `sandbox`. When the walk ends with no
    judge and every failure is `sandbox`, raise the first `SandboxUnavailable` again, so `--worktree` keeps exit 3
    (SCN-YOLO-61).

  Run the new file, then the files that pin the old shape:
  `uv run --frozen pytest tests/unit/yolo/test_yolo_readiness_review.py tests/unit/yolo/test_yolo_readiness_material.py
  tests/unit/yolo/test_yolo_readiness_incremental.py tests/unit/yolo/test_yolo_readiness_budgets.py
  tests/unit/yolo/test_yolo_readiness_delivered.py tests/unit/yolo/test_yolo_readiness_grouping_batch.py
  tests/unit/yolo/test_yolo_readiness_batch_prerequisites.py tests/unit/yolo/test_yolo_readiness_own_homes.py -q`.
  `test_a_judge_that_cannot_answer_raises…`, `test_a_judge_error_or_timeout_raises…` and
  `test_a_judge_that_fails_on_the_repair_prompt_raises_too` must still pass unchanged: `ReviewIncomplete` is a
  `RoleUnavailable` whose text holds `judge_error`.

## 4. A batch in parts (D6, D8; L4-YOLO-098)

- [x] 4.1 Write the tests first, in a new `tests/unit/yolo/test_yolo_readiness_parts.py`:
  - SCN-YOLO-276, first:
    - record the prompt text (`fake.requests[i].prompt`) and `verdict.material` of a unit and of a two-unit batch
      under the bound;
    - hard-code the expected material keys as literals taken by running the test once on the unchanged 0.4.58 code,
      before you touch `readiness.py` (`git stash` your change, or run it at commit `f0bc8a3c`);
    - assert `PROMPT_VERSION == 4`;
    - also cover a batch with one unit left (the others in `done`) and `max_batch_chars: 0` on a large batch: both
      are asked whole.
  - SCN-YOLO-273: three units, with `yolo: {review: {max_batch_chars: 1000}}` and folders large enough. Check:
    - the request order: A, B, C, then the parts of A, B and C, then the summary, and no whole-batch request;
    - the part of A holds A's folder text in full, and B's and C's within 6,000 characters (give B a 9,000-character
      `design.md` and check its tail is absent);
    - the summary holds no folder in full;
    - neither part note holds a unit id or the batch id outside `<l4:data` blocks (strip the data blocks with a regex,
      then search);
    - the batch verdict's `material` equals `material_key("batch", whole_subject.key_text)`;
    - `len(verdict.parts) == 4`;
    - `verdict.missing[-1]` starts with `judged in 4 parts` and names `yolo.review.max_batch_chars`.
  - SCN-YOLO-274:
    - the whole batch call ends `error` with `length_stop=True`, then j1 answers the unit parts and stops again on the
      summary, and j2 answers the summary;
    - the `missing` line names the output limit of j1;
    - `failures` holds `("j1", "batch:b1/summary", "length")`;
    - a variant whose whole call is `Step(status="timeout")` splits too;
    - a variant where a part times out raises `ReviewIncomplete(reason="timeout")`.
  - SCN-YOLO-275: test `merge_parts` directly with four raw `Verdict`s:
    - the worst verdict wins, F is kept once, and the minor finding is kept;
    - one BLOCKED part makes the batch BLOCKED;
    - a groups-only batch (`acceptance_profile: none`, see `test_yolo_readiness_grouping_batch.py`) whose parts' only
      finding is `batch_acceptance` is READY, with the finding moved to its assumptions by `_amend`.
  - SCN-YOLO-277, the function part:
    - put a part entry (`{"verdict": "READY", "findings": [], "assumptions": [], "missing": [], "material": <part
      key>}`) in `prior` for two of the four parts. Only the other two are asked, with no whole-batch request;
    - with `fresh=("batch:b1",)`, all four are asked.
    - A `prior` entry under the whole batch's key reuses the batch whole, with no request.

  Run them and see them fail.
- [x] 4.2 Then add the parts to `src/l4/yolo/readiness.py`: `SIBLING_CHARS`, `PART_NOTE_UNIT` and `PART_NOTE_SUMMARY`
  as in D6; `Subject.part` and its `name`; `_batch_part` and `_batch_summary`; the three split triggers; `merge_parts`;
  the cause text; and the batch verdict's `parts`. Run the new file and the files named in 3.3.

## 5. The record of a review that does not finish, and its readers (D7; L4-YOLO-099, L4-YOLO-022)

- [x] 5.1 Write the pure tests first, in a new `tests/unit/yolo/test_yolo_findings_incomplete.py`, with `PlanEvent`s
  built by hand (see `tests/unit/yolo/yolo_review_events.py`):
  - `prior_entries` reads the `answered` entries of a `plan.review_incomplete`, with `at` = the event's `at`. It also
    reads the `parts` rows of a `plan.reviewed` batch entry. It skips a harness `schema` entry and another prompt
    version.
  - `history(events, A, 4)` yields A's entry from a `plan.review_incomplete`, with its `source`. It never yields a part
    name.
  - SCN-YOLO-268, the ledger part: `failed_before` sees only events after the latest `plan.reviewed`, accumulates two
    events, and leaves out `unusable`, `sandbox` and `limit`.
  - `latest_incomplete` returns None after a newer `plan.reviewed`.
  - `fold_plan` of a ledger with `plan.review_incomplete` gives the same `PlanState` as without it.
  - `rounds_not_ready` is unchanged by it.

  Then change `src/l4/yolo/findings.py`. Run the file and `tests/unit/yolo/test_yolo_findings*.py` (the ones that
  exist).
- [x] 5.2 Write the CI-step tests first, in a new `tests/unit/yolo/test_yolo_cycle_review_incomplete.py`, with
  `CycleWorld`. Set `world.cfg` to a configuration with two judge profiles, and `world.judge` or the injected adapters
  to the scripts; if `CycleWorld.step` cannot take a second adapter, add an `adapters` attribute to `CycleWorld`.
  - SCN-YOLO-278:
    - `world.kinds()` is `["plan.admitted", "plan.review_incomplete", "plan.charged"]`: the admission is written under
      the condition the review that finishes uses (D7), and no `plan.reviewed` is written;
    - check the event's `source`, `reason`, `answered` (A and B with `judge: j2` and their `digest`), `left` and both
      failures;
    - the step's `actions` hold the failure lines and `the review is incomplete (no_judge): 2 answered and kept, 1
      left`;
    - `fold_plan(...).status == "admitted"`;
    - `step.start_next_run is False`.
  - SCN-YOLO-279: run the step again with j2 answering. Only the batch is asked. The one `plan.reviewed` holds A and B
    with `reused_from` equal to the incomplete event's `at`, the batch with `judge: "j2"`, `judges` and `failures`.
  - SCN-YOLO-280: a second failing run with no cost leaves the plan ref's head unchanged and still logs. After a commit
    that changes A's spec (as in `test_a_reviewed_plan_is_not_reviewed_again_until_an_input_changes`), A is asked again
    and B is not.
  - SCN-YOLO-271, the cycle part: the event has `reason: timeout`. In the next step B is asked of j2 first.
  - SCN-YOLO-272, the cycle part: `world.step(budget=lambda: 600.0)` records `reason: job_time` and asks nothing. Check
    how `yolo_step` takes `budget` in `cycle.py` (`yolo_step(..., budget=...)`).
  - Status:
    - run `l4 yolo status p1` the way the existing status tests do (`grep -rn "def test.*status" tests/unit/yolo |
      head`, for example `test_yolo_commands_manage.py`);
    - assert the `incomplete` line, the failure lines and the `fix:` line, and `--json`'s `review.incomplete`;
    - after a later `plan.reviewed`, no `incomplete` line.

  Then change the code:
  - `src/l4/yolo/cycle.py`: catch `ReviewIncomplete` first; `_write_incomplete`; the dedupe; the charge; the lines;
    `budget` passed as `time_left`, and `failed_before`; `_entry` writes `judge` and `parts`; the event-level `judge`,
    `judges` and `failures` on `plan.reviewed`; the failure lines of a review that finishes.
  - `src/l4/yolo/commands.py`: the status document and `_render`.

  Run the new file and `uv run --frozen pytest tests/unit/yolo/test_yolo_cycle_review.py
  tests/unit/yolo/test_yolo_cycle_integration.py tests/unit/yolo/test_yolo_cycle_final_review.py
  tests/unit/yolo/test_yolo_commands_manage.py -q`. The existing
  `test_a_judge_error_records_nothing_and_starts_no_next_run` and
  `test_a_judge_that_cannot_run_for_a_waiting_plan_does_not_starve_the_active_plan` raise a plain `JudgeFailed`,
  `RoleUnavailable` or `RoleLimit` through a monkeypatch. They must still pass unchanged: that path records nothing and
  logs `no judge could run`.
- [x] 5.3 Write the command tests first, in a new `tests/unit/yolo/test_yolo_review_incomplete_cli.py`. Follow how
  `tests/unit/yolo/test_yolo_review_worktree.py` drives `--local` and `--worktree` (its `real = review_plan_costed`
  wrapper injects the fake).
  - SCN-YOLO-281: `--local` records `plan.review_incomplete{source: local, by}` and the charge, and exits 12 with the
    lines. A `--worktree` dry run leaves the plan ref's head unchanged, writes the answered entries to
    `review_worktree.cache_path(...)`, and exits 12; a second dry run asks only the batch. `--worktree --record` on a
    clean tree at `origin/main` records `source: worktree`.
  - SCN-YOLO-269: with `sandbox.mode: auto` and `judge_sandbox._bwrap` monkeypatched to report no bwrap, the chain
    `[codex-judge, claude-judge]` skips codex-judge with kind `sandbox`, and claude-judge answers. With
    `[codex-judge]` alone the command exits 3 with the SCN-YOLO-61 text.
  - SCN-YOLO-277, the command part: `--worktree --fresh batch:b1` asks every part again.
  - `--record` writes `judge` and `sandbox` per entry from the judge that answered it (D4).

  Then change the code:
  - `src/l4/yolo/commands.py`: in the `--local` review, catch `ReviewIncomplete`, write the event, exit 12;
    `_verdict_json` writes `judge` and `parts`.
  - `src/l4/yolo/review_worktree.py`: `_Sandboxes` keeps a profile-to-label dict; `ReviewIncomplete` is handled for
    the dry run and for `--record`; the cache lines cover parts.

  Run the new file, `tests/unit/yolo/test_yolo_review_worktree.py`, `tests/unit/yolo/test_yolo_go_review.py` and
  `tests/unit/yolo/test_yolo_commands_activate.py`.

## 6. Documentation (L4-YOLO-100)

- [x] 6.1 Write the test first, in a new `tests/unit/docs/test_readiness_judge_chain_docs.py` (SCN-YOLO-282), in the
  style of `tests/unit/docs/test_yolo_guardrails_docs.py`:
  - `docs/runbook.md` names `roles.plan_judges`, `yolo.review.timeout`, `yolo.review.max_batch_chars`,
    `plan.review_incomplete` and the three reasons;
  - `docs/yolo-mode.md` no longer holds `L4 records no review`;
  - `plugins/l4/skills/l4/references/adopt.md` names `roles.plan_judges`;
  - `references/operate.md` and `references/plan.md` hold `the review is incomplete`;
  - the CHANGELOG's `## Unreleased` names `roles.plan_judges` and `yolo.review.timeout`.

  Run it and see it fail.
- [x] 6.2 Then write the docs. Plain sentences, the runbook's style. No consumer or project names.
  - `docs/runbook.md`, 12.2 (search `The review does not run if the judge agent fails`): replace that paragraph. Say
    which chain reviews a plan, that a subject goes to the next judge and the answers are kept, what `incomplete` under
    `review:` in `l4 yolo status` shows, and the fix per reason. Name `yolo.review.timeout` (15m) and
    `yolo.review.max_batch_chars` (0) with what they do, and the `judged in <n> parts` line.
  - `docs/runbook.md`, the capacity section (search `Every judge was discarded in step 9`): add a bullet for the plan
    review, and name `roles.plan_judges` beside `roles.judges` in the paragraph on judge adapters.
  - `docs/yolo-mode.md` (search `L4 records no review`): one paragraph in its place.
  - `plugins/l4/skills/l4/references/adopt.md`, section 4b: one bullet on `roles.plan_judges`.
  - `plugins/l4/skills/l4/references/operate.md`, the error table: replace the row `review: no judge could answer,
    nothing was recorded` with a row for `review: the review is incomplete (<reason>)`, its cause and the fix, and keep
    a row for the old text, which a plain `RoleUnavailable` still prints.
  - `plugins/l4/skills/l4/references/plan.md` (search `When no judge can run`): say what the incomplete review means
    and what to do. An agent never runs `--force`; it prints the person's command.

  Run the docs test and `uv run --frozen pytest tests/unit/docs -q`. Also run `uv run --frozen pytest
  tests/unit/skills -q` if the skill is hashed or checked there (`grep -rln "operate.md\|plan.md" tests/unit/skills`).
- [x] 6.3 `CHANGELOG.md` already has the Unreleased entry. Check it against what you built, and correct any number or
  name that differs.

## 7. Checks

- [x] 7.1 `uv run --frozen python scripts/check_spec.py docs/SPEC.md` and `openspec validate readiness-judge-chain
  --strict`.
- [x] 7.2 Check the code against L4-YOLO-095..100 and SCN-YOLO-261..282 in `docs/SPEC.md`. Fix the code, or report to
  the orchestrator where they differ. Do not change the requirements yourself.
- [x] 7.3 `uv run --frozen ruff check .` and `uv run --frozen ruff format --check` on the files you changed. Run
  `uv run --frozen mypy` on `src/l4/yolo src/l4/agents/factory.py src/l4/config` if the repository's CI runs mypy
  (`grep -n mypy .github/workflows/*.yml pyproject.toml`).
