# M1.11 — the sample-consumer wave A findings (planned 2026-10-06)

## Goal

Wave A of sample-consumer (2026-10-06, harness `c16871c`, runner 12) ran three units end to end: PR-2 and MF-1
merged, MF-7 halted. The run left eleven harness findings, W1–W11. M1.11 closes them:

* **W1 (MF-7).** A retry prompt carries only the failing test's id. It never carries the error, so Codex repeated the
  same mistake three times and the unit halted. Every gate-failure retry reason now carries a bounded, redacted
  excerpt of the failure.
* **W2 (MF-7).** A halted unit can only be resumed from a laptop. `l4 resume` needs bwrap although it starts no agent,
  and the `l4:resume` label is ignored. M1.11 makes resume work from CI.
* **W3 (PR-2).** An Anthropic 529 in a judge or verifier-agent call parked the unit for at least 30 minutes, twice.
  M1.11 retries it in the run.
* **W4 (MF-7).** A halt turns `main`'s push pipeline red although the project's tests pass.
* **W5 (MF-1).** A rejected coverage hold becomes a chore whose prompt says "do not add tests".
* **W6 (PR-2, MF-1).** Tests written by people, and tests written by a coverage chore, are never counted as evidence.
* **W7 (PR-2).** Generated audit tests find the code by reflection and hold literal secret-shaped tokens.
* **W8 (PR-1 J1, PR-2).** The judge reports this round's audit tests as missing.
* **W9.** `l4:needs-answers` outlives the answer, and the MR text says squash merges lose something they do not.
* **W10.** A new unit's first setup gate took 8–11 minutes.
* **W11.** The Mintkey GitLab wrapper re-lists services on every call and fails on one 401 or 502.

**30 build lines**, test first. Each new test is seen failing before the code is written.

The evidence is the local folder `l4/docs/adoption/sample-consumer/live/wave-a/`. It is
private, so this plan names jobs, files, events and harness behaviour only, never the project's source text, test ids
or values.

## Coverage: finding → build lines

| Finding | Lines | Finding | Lines |
|---|---|---|---|
| W1 retry prompts drop the error text | 1–4 | W7 audit-test quality | 23 |
| W2 halted units cannot be resumed from CI | 5–10 | W8 judge reads before the round's own commits | 24 |
| W3 no in-run retry on API overload | 11–14 | W9 labels and MR text | 25, 26 |
| W4 a halt turns `main` red | 15, 16 | W10 slow first setup | 27, 28 |
| W5 a coverage fix chore may not add tests | 17–20 | W11 wrapper re-lists services, no retry | 29 |
| W6 owner-written tests are not evidence | 21, 22 | close-out, SPEC | 30 |

## Facts this plan rests on

Labels: [V] read in code at `cb83afc`, in the wave-A evidence, or probed live (read-only GETs through
`scripts/dev/mk-gitlab-api.sh`); [I] inferred; [U] not checked.

* **W1. The retry reason is a bare id.**
  * [V job 5699] MF-7 task 1.1's red failed three times with `red broke existing tests: <one test id>`, then
    `breaker.tripped{max_task_attempts}`.
  * [V `gates/…/006-test.log`] The red gate's log holds the cause: a `FileNotFoundError` raised in an existing test
    that passed at the base, with its `path:line` and the `E` lines.
  * [V `agent/…/1.1-red-2.prompt.md` line 300] The retry prompt's `# Your previous attempt was rejected` block, a data
    block (`<l4:data source="previous attempt">`), held only the reason line.
  * [V `implementer/tdd.py`] `classify_red` and `check_green` build these reasons from `_list(ids)`.
    * Only the "not by assertion" branch adds `_first_line(message)`, at most 80 characters.
    * The lint reason is already the last 2,000 characters of the log (`run_static_gates`, `LOG_TAIL_CHARS`). Job 5699
      shows a lint retry that carried the ruff output and passed on the next attempt.
  * [V `gates/junit.py`] `parse_junit` keeps the `message` attribute, cut to 500 characters, and drops the
    `<failure>`/`<error>` body, which is pytest's traceback text.
  * [V `implementer/loop.py`] The reason flows into `task.attempt_failed{reason}` (ledger, committed) and into the
    next prompt through `_retry_reason`.
* **W1/W2. Attempts are counted per run.** [V `loop.run_task`] `failures` and `attempts` are local to one
  `run_task` call, and nothing in the ledger counts them back. A resumed unit therefore starts the halted task at
  attempt 1 of each phase, and done tasks stay done (`task.done`). "Reset `max_task_attempts` only for the halted task"
  already holds by construction, so it is a test (line 9), not a build line.
* **W2. Resume today.**
  * [V `state/resume.py`] `l4 resume` calls `run_unit_in_worktree(…, resume_reason=…)`.
  * [V `services.build_services`] That fails closed on `select_sandbox` (`SandboxUnavailable`, exit 3) before
    `Orchestrator.resume` appends `unit.resumed{reason}`, takes `Trigger.RESUMED` and commits
    `chore(<unit>): resume [skip ci]`. No agent or gate runs.
  * [V `resume.py` docstring] "no member check, and the label `l4:resume` is not read".
  * [V] Nothing reads `l4:resume`: the sweeper's `_SWEPT` is `{in_review, merged}`.
* **W2. What the SPEC says.**
  * The `l4:resume` label is named in L4-CI-004 ("the sweeper MUST … honour the `l4:resume` label"), in L4-SEC-004
    (members with at least Developer/Write access only) and in SCN-RES-01 ("or sets the `l4:resume` label … set by a
    non-member is ignored").
  * The §12.0 table's only edge out of `halted` is "`l4 resume` by a member".
  * A spec-edit edge exists only for `in_review`/`archived` (L4-ARC-004, M1.9 `spec_edit_after_handoff`).
* **W2. The forge, probed** [V, project 119, 2026-10-06]:
  * `GET merge_requests/3/resource_label_events` returns `[{id, action: add|remove, created_at, user: {id,
    username, name, state, …}, label: {name, …}}]`. MR !3's one event is the harness adding `l4:halted` (event 1396,
    user 62).
  * `GET members/all/62` returns `{id, username, access_level: 30, state, …}`. User 62 is the project's bot, and it is
    a Developer, so a level check alone would accept the harness's own label. The token's own user has to be excluded.
  * The first try of that GET answered `502 bad gateway: vault error` (W11's failure).
* **W2. The mirror and the ledgers.**
  * [V `forge/gitlab.set_managed_labels`] The mirror removes every `l4:`-prefixed label it does not want. The first
    mirror sync after a resume (`_go` → `_sync_mirror`) therefore removes `l4:resume` together with `l4:halted`.
  * [V `state/status.load_snapshot`:138] The planner and the orchestrator fold branch plus pending ledger in every
    phase.
* **W2. MF-7 after its halt** [V jobs 5743, 5750]. The owner pushed a task edit to the halted branch (job 5742). The
  next `l4` jobs printed `halted: needs l4 resume` and `nothing to do`, and exited 0.
* **W2. Budgets.** [V `grep`] There are no budget halts in M1: `max_cost_usd_per_unit` and
  `max_iterations_per_unit` are not enforced. The breakers that halt are `max_task_attempts`, the fix loop's
  (`fixloop.py:221`), `unselectable_task`, `baseline_failed` and `secret_in_push`. `l4 resume` refuses `--extend-*` and
  `escalated`.
* **W3. The 529.**
  * [V `job-5709/…/verify-audit-r3-1.jsonl`, `job-5703/…/verify-judge-r3-3.jsonl`] The result event is `is_error:
    true`, `api_error_status: 529`, `terminal_reason: api_error`, `num_turns: 1`, cost 0. The text starts
    `API Error: 529 Overloaded`. **No retry-after is given.** The call lasted 4.6 s and 12.3 s.
  * [V `agents/claude_code._parse`] This becomes `status: error`, detail `claude reported an error (api_error_status
    529)`.
  * [V `llm/agent_judge.AgentJudge.complete_structured`] That becomes `StructuredResult("error")`. In turn it becomes
    `RoleUnavailable` (`ladder.py:811`, `audit.run_audit`), so the unit parks in `waiting_capacity` with `retry_after`
    +30 min (job 5709: `retry_after 12:51:23Z`).
  * [V SPEC 8.3] `CLAUDE_CODE_MAX_RETRIES=1`, so the CLI retried once at most itself.
  * [V `limits._claude`] A non-429 status is not a limit signal.
  * [V] `AgentJudge` serves the judge (`ladder.backend`), the audit and e2e writer (`writer_for`) and the clarifier.
    `probes.py:215` turns a `hello` that ends in an error into a failed probe.
* **W4. The red `main`.**
  * [V job 5699, pipeline 2993] The push pipeline on `main` ran the halting run, and the job ended `l4 exit 13
    (halted): …` and `ERROR: Job failed: exit status 13`. The project's test job 5698 passed (198 tests).
  * [V jobs 5738, 5750, 5753] Later `main` pipelines with MF-7 still halted printed `nothing to do`, exit 0. The red
    is transient: only the halting pipeline shows it.
  * [V] The persistent record is the MR: `l4:halted` (MR !3) and the run's `exit_reason`.
  * [V] SPEC §2.2 renders 13 as "failure", the template allows `[10, 11, 12]` (`ci/templates/l4.gitlab-ci.yml:26`), and
    `map_exit` on GitHub exits 1 for 13.
  * [V] The severity order is `1 > 2 > 3 > 13 > 14 > 11 > 12 > 10 > 0` (`exitcodes.SEVERITY_ORDER`).
  * [V `init/upgrade.py:3`] `l4 upgrade` re-renders `.l4/ci/l4.gitlab-ci.yml`. The include is not in the template lock.
* **W5. The coverage chore.**
  * [V `verdicts.settle_holds`:160–178] A rejected coverage hold becomes the finding "Changed code that no test runs",
    whose detail starts "Add tests that run the changed code the hold names". `hold_kind()` already tells coverage
    holds apart.
  * [V `fixunit.plan_fix_unit`] It has no criterion and no scenario, so it becomes `chore=True`.
  * [V `fixmark.FixMarker.chores`] The marker records it, and `loop.run_task` runs it through `run_single`.
  * [V `templates/single.md` v1] The prompt says "no criterion of the unit needs a new test for it … Do not add tests".
  * [V `tdd.run_single`:880] `restore_frozen` puts back every proved test file after the step.
  * [V MF-1, jobs 5703, 5709, 5715] Codex asked twice (Q-001 "no-new-tests constraint", Q-002 "which instruction
    governs"). The owner answered twice, the second time to override the phase line and name a new file.
* **W6. The evidence mismatch.**
  * [V `mf1-verification-round3.md` rows C-d2e3b20c, C-9b260ef1, C-e31cb8c5] The three "ignored as evidence (no
    proof that it discriminates)" tests of MF-1 round 3 were written by the fix unit's chore (commit `9cc1420`,
    l4-bot, `L4-TDD: exempt`) at the owner's instruction, not by a person.
  * [V `wave-a.md`] The person-written case is PR-2's owner commit `49d74c5d` ("fixed by an owner commit with
    discriminating tests"). Its round-5 report is not in the evidence folder [U for its exact rows].
  * [V `verifier/traceability.py`] A test is evidence only with a `red_assertion`/`zero_value`/`pre_satisfied` red
    record, an accepted `verify.audit`, `generated`, or `pass_to_pass`. Every other test that carries a criterion id
    becomes a minor "a test is ignored as evidence" finding, round after round.
  * [V `evidence/collect._human_commit`] The per-commit attribution exists: every commit of `base..H` that touches the
    path is not the harness's.
  * [V `discrimination.py`] `confirm_pre_satisfied` (zero-value run) and `red_code_in_place` (swap the production
    files to an older commit's content, sha256-checked restore) exist.
* **W7. The audit tests** [V `verify-audit-r1-1`, `-r3-1`, `-r3-2` of jobs 5699, 5703, 5724].
  * Five of the eight audit tests in the evidence locate the code under test with `inspect.getmembers` and call
    whatever member answers.
  * Three hold a literal 14-character mixed-case alphanumeric token.
  * [V `testwriter._KIND_RULES["audit"]`, `_check`/`_reimport`] The rules and the AST rejection cover only re-import.
    `TEMPLATE_VERSION = 2`.
* **W8. What the judge sees.**
  * [V `pr2-verification-round3.md`:125, `round4.md`:130] The judge raised "The traceability matrix cites audit
    tests that are absent from the diff and the per-test outcomes".
  * [V `ladder._judge_step`] The judge reads `_git_diff(base, H)` and `_gate_summary(result)`. The round's accepted
    audit files are written to the worktree in step 4a and committed only at the end of the round
    (`evidence.commit_verifier_tests`, L4-VER-011). Their outcomes come from the separate `audit` gate run, not from
    the `test` gate the summary lists.
  * [V M1.10 C3] `verification.md` is already out of the diff, which closes PR-1 J1's "stale verification.md" half.
* **W9. Labels and text.**
  * [V jobs 5709, 5715] MF-1 fix-1's Q-001 was recorded answered at 12:17:27, and the MR kept `l4:fixing,
    l4:needs-answers` with nothing open until Q-002 was raised at 12:19:22. Q-002 was answered at 12:23:30, and the
    label stayed until the chore's push at 12:27:55.
  * [V `archive._Mirror`] The mirror is synced only in `Orchestrator._go` and `push`, and `_labels` reads
    `questions.open` at sync time.
  * [I] The answers are recorded (`question.answered`, `clarifier.py:169`) with no edge and no push in between, so the
    stale label is the mirror's timing, not the fold. The exact call site of the fix-unit clarifier is not read yet.
  * [V `archive.render_pr_body`, SPEC L4-ARC-003] The body text and the SPEC rule say "recommend the merge-commit
    method (squash discards trailers)".
  * [V `findings-pr1.md` S1, `tests/unit/state/test_review.py:135`] Merge and archive detection read the MR state and
    the tree, and H is found beneath a squash commit.
* **W10. Where the setup time goes.**
  * [V job 5699, `001/011/053-setup.log`] Each unit's first `gates.setup` downloaded the same ten large wheels (52
    packages, about 170 MB): `Prepared 52 packages in 11m 24s`, `8m 03s` and `21.58s` for the three units. The trace
    agrees: task start to `gate setup pass` was 11.5 min, 8.1 min and 29 s.
  * [V jobs 5703, 5709, 5715, 5724] Every later setup of the same unit read `Prepared 1 package in <1 s` and
    `Installed 52 packages in 3–4 s`. **The per-unit cache persists across runs; it is not masked.**
  * [V `config/defaults.CACHES`, `sandbox/env.build_gate_env`] `UV_CACHE_DIR=$L4_CACHE/units/{unit}/cache/uv` is bound
    read-write into the gate sandbox.
  * [V job 5698] The project's own test job installs the same 52 packages in 47 ms from the runner's `~/.cache/uv`.
  * [V] The units ran one after another in one job (timestamps), so concurrency was not the cause.
  * [U] Why the third download was 30× faster.
  * [V log text] `Failed to hardlink files; falling back to full copy` is a cross-mount `EXDEV` (the cache and the
    worktree are separate binds). It costs 2–6 s, not minutes.
  * [V SPEC L4-SEC-005] "per-unit caches so that agent-written code cannot poison another unit's cache".
  * [I] `uv sync` builds the project from an agent-editable `pyproject.toml`, so even the setup gate runs agent
    influence.
  * [V `config/defaults.cache_root`] `$L4_CACHE` is per runner user, not per project.
  * [U] Whether uv's cache uses absolute symlinks that a copy must re-point.
* **W11. The wrapper** [V `scripts/dev/mk-gitlab-api.sh`]:
  * it calls `list_services` on every call, then `request_token` only when the cached JWT is within 60 s of expiry;
  * a 401 or 502 of the proxy call exits 22 at once;
  * a Mintkey call failing with `curl -fsS` stops the script (`set -euo pipefail`);
  * [V probe above] the 502 is intermittent: the retry seconds later answered 200;
  * tests: `tests/unit/forge/test_mk_scripts.py` with a fake `curl` that answers by URL.

## Decisions

1. **W1: the excerpt comes from the report, per named test.**
   * `parse_junit` keeps a bounded slice of the `<failure>`/`<error>` body as `TestCase.detail`: at most 4,000
     characters, the end kept.
   * `failure_excerpt(report, ids, …)` takes, for each named id:
     * the `E   ` lines, at most 6;
     * the `>` line of the deepest frame in a repository file;
     * the last `path:line: ErrorName` line.

     When there is no body, it falls back to `message`.
   * Bounds: at most 8 lines per test and **at most 40 lines and 3,000 characters in total**. Identical lines are
     kept once, with `(same for N tests)`.
   * Paths: the worktree prefix becomes relative, and the gate-tmp root becomes `<tmp>`. The text goes through
     `wb.redactor.redact_text`.
   * The lint reason keeps the log, cut to the first 36 lines plus the summary line, deduplicated, and no more than
     40 lines.
   * The excerpt goes **into the next prompt only**, inside the existing `previous attempt` data fence (it is
     agent-influenced output and stays data).
   * The ledger's `task.attempt_failed{reason}` and the console keep the one-line headline and add
     `excerpt_lines: n`. A committed ledger should not carry 40 lines of test output per attempt. The gate log already
     holds the full text, uploaded as a job artifact.
   * No template changes: the block header lives in `prompt.py`, which the lock does not pin.
2. **W2 (a): `l4 resume` needs no sandbox.**
   * `build_services(…, sandbox=False)` gives `Services.sandbox = NoSandbox(reason)`, whose `wrap` and `available`
     raise `SandboxUnavailable("resume runs no agent or gate")`. Any accidental agent or gate use therefore fails
     closed.
   * Only the resume path passes it.
   * `l4 run` keeps the fail-closed selection.
3. **W2 (b): the label, not a commit, is the CI resume signal.** The deciding constraint is who set it.
   * The SPEC names the label three times (L4-CI-004, L4-SEC-004, SCN-RES-01). §12.0 has no commit edge out of
     `halted`, so a commit signal would be a new lifecycle edge and a SPEC change. The label is already specified.
   * A label event is forge-attributed: `user.id`, then `access_level` from `members/all/:id`. A commit's author is
     self-asserted text, and git does not record the pusher. The L4-SEC-004 member check (Developer, 30, or more) can
     be built for the label and **cannot** be built for a push.
   * A halt does not always need a spec edit. MF-7's cause was the harness (W1), and the owner's task edit was
     optional. The label covers both cases.
   * A person's push on a halted branch still gets a pointer: the planner reason and a sweep line say "add the label
     `l4:resume` to the merge request (members), or run `l4 resume`".
4. **W2 (b): how the sweep honours it.** `l4 plan --sweep` gains one duty for each `halted` unit with an open MR that
   carries `<prefix>resume`:
   * **Signal.** The latest `add` event of that label whose user is not the token's own user (`GET /user`, the bot)
     and has `access_level >= 30`.
   * **One resume per signal.** The signal id is `label:<event id>`. `unit.resumed` gains `signal`, and an id
     already in the fold is never acted on again. A unit that halts again in the same pipeline needs a new label
     event: a member adds the label again (the resume's mirror sync removed it).
   * **Mechanism.** The same function as `l4 resume` (`resume_unit`, decision 2): the unit's lease and worktree,
     `unit.resumed{reason: "label l4:resume", by: "member", signal}`, `Trigger.RESUMED`, and the commit
     `chore(<unit>): resume [skip ci]`, which carries `L4-Run` and starts no pipeline. The push follows.
   * The resume's own mirror sync removes `l4:resume` and `l4:halted` (Facts). That is cosmetic; the event-id dedupe
     is the loop guard.
   * The `l4 run` of the same job then continues the unit. It sees the resume because its `refresh_refs` fetches the
     branch the sweep pushed [I: the fetch order is read, not tested]. The halted task starts at attempt 1 (Facts),
     and only that task is retried.
   * **Lease.** `resume_unit` takes the unit's `LocalFileLease` itself. The halted-unit duty never opens a
     `_UnitRun` for that unit first, which would deadlock the sweep on its own lease.
   * **`by` is `member`, not the username.** PR-1 P5: the project's privacy rule forbids the owner's username in
     commits, and the event id is enough to audit it on the forge.
   * **Refusals** get one warning line and one MR sticky-note section per event id, recorded as
     `resume.refused{signal, why}` in the pending ledger so they are not repeated:
     * a non-member, or a level below Developer;
     * the bot;
     * an `escalated` unit (as `l4 resume`);
     * a forge that cannot read label events. GitHub returns none, so it fails closed there; M1 note.
5. **W3: retry transient server errors where the role calls meet.**
   * `ClaudeCodeAdapter._parse` sets `RunResult.transient = True` for `is_error` with `api_error_status` 529 or 503,
     or `overloaded_error` in the result. The status stays `error`, so nothing else changes meaning.
   * `AgentJudge.complete_structured` retries a transient run: **3 tries, waits 20 s then 60 s**. A `retry_after_s`
     that an adapter reports is used instead, capped at 60 s; Claude reports none (Facts). The wait plus the calls stay
     within about 2 minutes.
   * Each retry is recorded as `availability.transient{role, profile, status, attempt, wait_s}`. After the third,
     today's path runs (`RoleUnavailable` → `waiting_capacity`).
   * The `hello` probe gets one retry after 20 s for the same statuses.
   * L4-AVL-006 (fail fast, no waiting) concerns usage limits. A 529 is not a limit (`limits._claude`), so this adds
     to the SPEC and does not contradict it.
   * **The implementer is out of scope.** A retried agent step is not idempotent once it has edited the worktree.
6. **W4: a halt is a warning in CI; 1, 2, 3 and 14 stay failures.**
   * L4-CLI-001 already says that one failing unit MUST NOT stop the run. A halt is unit state the forge already
     mirrors: `l4:halted`, the `exit_reason`, `after_script: l4 status`, and from line 16 a sticky note naming the
     reason and how to resume. It is not a harness or environment fault (1/2/3).
   * The red is also transient (Facts), so it says less than the label.
   * **13 joins `exit_codes: [10, 11, 12, 13]`**. On GitHub, `map_exit` gives 13 a `::warning::` and exit 0.
   * **14 (rejected) stays a failure.** A rejected unit has no MR to carry a note, so the pipeline is its only signal,
     and an invalid spec on `main` is the members' to fix.
   * The severity order becomes `1 > 2 > 3 > 14 > 13 > 11 > 12 > 10 > 0`, so a run with one rejected and one halted
     unit still fails.
   * Adopted projects get the new include from `l4 upgrade`, which re-renders it.
7. **W5: a coverage chore is a test-adding chore.**
   * `plan_fix_unit` marks a finding from a coverage hold (`hold_kind == "coverage"`) as `tests=True`, and the marker
     gains `test_chores`. A marker without the key reads as today (`fix`).
   * `run_task` routes it to `run_single(kind="tests")` with a new template `single_tests.md` (v1, added to
     `IMPLEMENTER_TEMPLATES`). `single.md` stays v1.
   * The chore may add test files, and may append new tests to the unit's own (frozen) test files. A frozen file is
     kept when `appended_only(base, head)` holds: every top-level statement of the step base survives unchanged
     (`ast.dump`), so nothing existing was edited or removed, **and** no added top-level `def`, `class` or assignment
     rebinds a name already bound at the base. Python rebinds a name, so an appended `def test_<same name>(): pass`
     would shadow a proof test while its id stays present and passing. Otherwise the file is restored as today, with
     a guard note.
   * A new or changed `conftest.py` (or any `tdd.test_support_globs` file) is not a test file for this chore: it is
     put back. An autouse fixture there would reach every existing test.
   * It must add at least one new passing test, otherwise the reason is `no tests added`. A change to a non-test file
     fails the attempt.
   * `check_green`'s regressed check (`i not in report.tests`) is the backstop against a deleted or broken proof
     test.
   * The step emits `task.tests_added{task, files, tests}`.
   * The hold's subjects are checked by the next round's diff coverage, not by a second coverage run in the chore.
     The round runs it anyway, and `max_fix_rounds` bounds a chore that adds an irrelevant test.
8. **W6: one discrimination step for tests no proof covers.**
   * At step 4, a test that traces a criterion is a candidate when it is ignored only for "no proof" and:
     * every commit of `base..H` that touches its file is a person's (`source: human`); or
     * its file is listed in a `task.tests_added` of the family (`source: chore`).
   * The candidates run against the zero values (`confirm_pre_satisfied`).
   * Those still passing run once more with the unit's changed production files swapped to the unit base:
     `red_code_in_place`, generalised to take a sha and paths.
   * A test that fails in either run is accepted, **failing closed as `fails_at_red` does (M1.10 `13bda39`)**: an id
     counts as failing only when the run's report lists it as `failed` or `error`. A collection error (the base has
     no module the unit added, so the test cannot import), a skipped id, an id the report lacks and a run without a
     report are no proof. Accepted: `verify.extra_proof{round, criterion, tests, source, via:
     zero_value|base, files: {path: sha10}}`. `red_proofs` reads the accepted events, so the proof is `human` or
     `chore` and the matrix shows `(passed, human)`.
   * A rejected candidate stays a minor finding, with the reason "passes against the zero values and on the base".
   * At most two gate runs per round, only when there are candidates. An accepted proof is kept for the same file
     content, like an audit record. A rejection is keyed by (file sha, H): the production code changes between
     rounds, and a rejected test can become discriminating.
9. **W7: rules plus an AST rejection, like P3's re-import rule.**
   * The audit rules gain:
     * "import the public names you test; never locate code by reflection or introspection";
     * "never write a secret-shaped literal (12 or more letters and digits): build such a value at run time from short
       parts";
     * "follow the project test conventions shown".
   * `_check` rejects as `invalid`, with the reason, retried once by the caller:
     * `import inspect`, and `dir(…)`, `vars(…)` and `__dict__`;
     * `getattr` and `hasattr` with a non-constant name;
     * a string constant matching `redact.TOKEN_SHAPES`, or `[A-Za-z0-9_-]{12,}` with an upper-case letter, a
       lower-case letter and a digit. A hex digest has no upper case and stays allowed.
   * `TEMPLATE_VERSION` 2 → 3. Both the `audit` and `e2e` lock entries move, because they share the constant.
10. **W8: give the judge the round's outputs instead of filtering its words.**
    * A block `## Written by the harness this round (committed after your review)` lists each accepted audit test:
      its path, its test outcomes from the `audit` gate run, and its source (at most 6,000 characters each; at most
      2 per round, `MAX_AUDIT_PER_ROUND`).
    * The block also says that this round's `verification.md` is written after the review.
    * Rubric line: these files are not in the diff and their tests are not in the gate report's list; judge them as
      evidence, and raise no finding that they are missing.
    * A text filter on judge findings would be fragile and could drop a real finding.
    * `PROMPT_VERSION` 5 → 6.
11. **W9.**
    * After a run records `question.answered` for the parent or the open fix unit and the fold's open set changes,
      the orchestrator syncs the mirror once, before any agent step.
    * The body line becomes: "Any merge method works: the harness detects the merge from the merge request and the
      tree. A merge commit keeps the commits' L4 trailers in the history; a squash drops them."
    * SPEC L4-ARC-003 changes from MUST recommend merge-commit to MUST say both work.
12. **W10: a trusted seed, copied into each new unit cache.** A shared read-write uv cache violates L4-SEC-005's
    per-unit rule. uv takes one cache directory [I, no layering option known], and a hard-link seed shares inodes that
    agent code could rewrite. So:
    * **The seed** lives at `$L4_CACHE/seed/<sha256(origin URL without credentials)[:16]>/uv`. It is keyed per
      project, because `$L4_CACHE` is shared by every project on the runner and one project's members must not fill
      another's cache.
    * It is filled by running `gates.setup` unchanged in the gate sandbox, with `UV_CACHE_DIR` set to the seed. The
      run uses a detached scratch worktree at the base branch's head: member-written content only (L4-SEC-003), and no
      agent has run there.
    * It runs under an flock, and only when `seed.json{key}` is stale: key = sha256 of the base's `uv.lock` and the
      setup commands.
    * It runs only when the base has `uv.lock` and the first setup command's program is `uv`.
    * The seed is never mounted into any sandbox that runs agent or agent-written code.
    * **The copy.** When `mount_caches` creates a unit's uv cache directory (absent or empty), it is a copy of a
      complete seed. Absolute symlinks that point into the seed are re-pointed into the copy [U, uv's layout].
    * The copy is skipped when the unit cache already has content. A failed seed or copy is recorded
      (`cache.seed_failed{reason}`) and the unit downloads as today.
    * `UV_LINK_MODE=copy` is set in the gate env when a uv cache is mounted. It names what already happens across
      binds and silences the warning.
    * Events: `cache.seeded{cache, key, seconds, bytes}` and `cache.seed_failed`.
    * Rejected options: binding the runner's own `~/.cache/uv`. The project's host CI jobs read it outside any
      sandbox, so a poisoned entry would run in the CI job's context.
13. **W11.**
    * `$ENVF` holds `SVC` next to `JWT` and `EXP`, so `list_services` runs only with a new token.
    * A helper `call()` wraps every curl:
      * one retry on 502 after 2 s;
      * on 401 of the proxy, drop the cache, list services and request a token again, then one retry;
      * a second failure exits 22, as today.
    * The Mintkey `tools` calls get the same single retry for 401 and 502.
    * The JWT is never printed.

## Build lines

Line format: `n. ids — what · test (write it first, see it fail) · code · verify`.

**Stage A — the failure in the retry prompt (W1)**

1. L4-GAT-002 — `TestCase.detail`: a bounded slice of the `<failure>`/`<error>` body (decision 1). Tests in
   `tests/unit/gates/test_junit.py`:
   * `::test_the_failure_body_is_kept_bounded`;
   * `::test_a_passing_case_has_no_detail`;
   * the existing tests unchanged.

   Code: `src/l4/gates/junit.py`. Verify: `uv run pytest tests/unit/gates -q`.
2. L4-IMP-008, L4-OBS-002 — `l4/implementer/excerpt.py`, pure: `failure_excerpt(report, ids, *, worktree, tmp_root,
   redact) -> str` and `lint_excerpt(text) -> str` (decision 1). Tests in `tests/unit/implementer/test_excerpt.py`:
   * `::test_an_error_in_an_existing_test_gives_its_location_and_e_lines` (a synthetic FileNotFoundError report shaped
     like job 5699's, no project text);
   * `::test_forty_lines_and_3000_characters_at_most`;
   * `::test_identical_lines_are_kept_once_with_a_count`;
   * `::test_paths_are_made_relative_and_tmp_is_masked`;
   * `::test_a_token_in_the_output_is_redacted`;
   * `::test_no_body_falls_back_to_the_message`.

   Code: `src/l4/implementer/excerpt.py`. Verify: `uv run pytest tests/unit/implementer/test_excerpt.py -q`.
3. L4-IMP-008, L4-IMP-002 — the wiring:
   * `RedVerdict`, `GreenOutcome` and the static-gate failures carry `excerpt`:
     * `classify_red`'s "broke existing tests" and "not by assertion" branches;
     * `check_green`'s "red tests still failing", "broke existing tests" and "new failing tests";
     * lint, through `lint_excerpt`;
   * `loop._retry_reason` composes headline, excerpt and guard note;
   * `task.attempt_failed` keeps the headline and adds `excerpt_lines`.

   Tests:
   * `tests/unit/implementer/test_tdd_red.py::test_a_red_that_breaks_an_existing_test_tells_the_next_attempt_why`;
   * `tests/unit/implementer/test_tdd_green.py::test_green_failing_tests_carry_their_errors`;
   * `tests/unit/implementer/test_tdd_static.py::test_the_lint_reason_is_bounded_and_deduplicated`;
   * `tests/unit/implementer/test_loop.py::test_attempt_failed_keeps_the_headline_only`.

   Code: `src/l4/implementer/tdd.py`, `src/l4/implementer/loop.py`. Verify: `uv run pytest tests/unit/implementer -q`.
4. W1 end to end — `tests/unit/implementer/test_loop.py::test_the_second_red_attempt_sees_the_first_attempts_error`.
   * A scripted agent's red attempt 1 edits an existing test so that it raises `FileNotFoundError`.
   * The attempt-2 prompt file holds the `E` line and the test file's `path:line` inside the `previous attempt`
     fence.
   * Attempt 2 leaves the existing test alone, and red is ok.

   Code: whatever lines 1–3 missed. Verify: as line 3.

**Stage B — resume from CI (W2)**

5. §2.1 `resume`, L4-IMP-013 — `build_services(sandbox=False)` and `NoSandbox` (decision 2); `state/resume.py` passes
   it. Tests:
   * `tests/unit/state/test_resume.py::test_resume_needs_no_sandbox` (`sandbox.mode: auto`, no bwrap on `PATH`: the
     unit leaves `halted`, and the resume commit is pushed);
   * `tests/unit/sandbox/test_select.py::test_no_sandbox_refuses_every_wrap`;
   * `tests/unit/orchestrator/test_run_unit.py::test_run_still_fails_closed_without_bwrap` (exit 3, unchanged).

   Code: `src/l4/services.py`, `src/l4/sandbox/none.py`, `src/l4/state/resume.py`. Verify:
   `uv run pytest tests/unit/state tests/unit/sandbox tests/unit/orchestrator -q`.
6. L4-SEC-004, forge port — `label_events(number) -> list[LabelEvent(id, label, action, user_id, created_at)]`,
   `member_access(user_id) -> int | None` (404 → None) and `own_user_id()` (`GET /user`). GitLab is built; FakeGitLab
   and LocalForge are scripted; GitHub returns `[]` (fail closed). Tests in
   `tests/unit/forge/test_gitlab_labels.py`:
   * `::test_label_events_parse_the_probed_shape` (a fixture of the 2026-10-06 answer, ids only);
   * `::test_member_access_reads_access_level_and_a_404_is_none`;
   * `::test_own_user_id_reads_the_token_user`;
   * `tests/unit/forge/test_github_pr.py::test_github_has_no_label_events_yet`.

   Code: `src/l4/forge/base.py`, `src/l4/forge/gitlab.py`, `src/l4/forge/github.py`, `src/l4/forge/local.py`,
   `tests/unit/forge/conftest.py`. Verify: `uv run pytest tests/unit/forge -q`.
7. L4-SEC-004, SCN-RES-01 — `resume_signal(labels, events, *, label, own_id, access, consumed) -> ResumeSignal |
   Refusal | None`, pure (decision 4). Tests in `tests/unit/ci/test_resume_label.py`:
   * `::test_a_developer_label_is_a_signal`;
   * `::test_a_reporter_is_refused`;
   * `::test_the_bot_is_refused_although_it_is_a_developer` (the probed level 30);
   * `::test_a_consumed_event_id_is_no_signal`;
   * `::test_the_latest_add_wins_and_a_removed_label_is_none`.

   Code: `src/l4/ci/resume_label.py`. Verify: `uv run pytest tests/unit/ci/test_resume_label.py -q`.
8. L4-CI-004, L4-IMP-013 — the sweep duty (decision 4). `resume_unit(…, reason, signal)` is shared with
   `l4 resume`; `unit.resumed{signal}`; `resume.refused` and its sticky-note section. Tests in
   `tests/unit/ci/test_sweeper.py`:
   * `::test_a_member_label_resumes_a_halted_unit_once`;
   * `::test_a_non_member_label_is_ignored_and_said_once`;
   * `::test_the_same_label_event_never_resumes_twice` (the unit halts again; the next sweep acts on nothing);
   * `::test_an_escalated_unit_is_refused`;
   * `::test_the_resume_commit_carries_l4_run_and_skip_ci`.

   Code: `src/l4/ci/sweeper.py`, `src/l4/state/resume.py`, `src/l4/orchestrator.py` (`resume(reason, signal)`),
   `src/l4/state/fold.py` (`resumed_signals`). Verify: `uv run pytest tests/unit/ci tests/unit/state -q`.
9. SCN-RES-01 end to end —
   `tests/unit/orchestrator/test_reentry.py::test_a_label_resumed_unit_retries_only_the_halted_task`:
   * a unit halts on `max_task_attempts` at task 1.2 (1.1 done);
   * a member's label arrives, `plan --sweep` resumes it, and `run` restarts 1.2 at red attempt 1 of 3, with 1.1
     untouched;
   * the mirror's label set no longer holds `l4:resume` or `l4:halted`;
   * a second sweep with the same event does nothing.

   Code: whatever lines 5–8 missed. Verify: `uv run pytest tests/unit/orchestrator -q`.
10. L4-OBS-001 — the planner reason becomes `halted: a member adds the label l4:resume (or runs l4 resume)`. The sweep
    prints `halted; a person pushed after the halt: add the label l4:resume to resume` once per head when a
    non-harness commit follows the halt. Tests:
    * `tests/unit/planner/test_next_action.py::test_the_halted_reason_names_the_label`;
    * `tests/unit/ci/test_sweeper.py::test_a_push_on_a_halted_branch_names_the_label_once`.

    Code: `src/l4/planner.py`, `src/l4/ci/sweeper.py`. Verify: `uv run pytest tests/unit/planner tests/unit/ci -q`.

**Stage C — overload retries (W3)**

11. L4-FAC-002 — `RunResult.transient` for 529 or 503 and `overloaded_error` (decision 5). Tests in
    `tests/unit/agents/test_claude_code.py`:
    * `::test_a_529_result_is_transient` (the fields of the job-5709 result event);
    * `::test_a_404_or_401_is_not_transient`;
    * `::test_a_429_stays_rate_limited`.

    Code: `src/l4/agents/base.py`, `src/l4/agents/claude_code.py`. Verify: `uv run pytest tests/unit/agents -q`.
12. L4-AVL-006, L4-AVL-008 — `AgentJudge` retries transient runs (3 tries, 20 s and 60 s, injectable sleep) and emits
    `availability.transient`. The ladder's `backend`/`writer_for` and the clarifier pass the ledger and the role. Tests
    in `tests/unit/verifier/test_agent_judge.py`:
    * `::test_a_529_is_retried_and_the_answer_is_used`;
    * `::test_three_529s_end_as_error_with_two_transient_events`;
    * `::test_a_limit_or_schema_error_is_not_retried`;
    * `::test_waits_are_20_and_60_seconds`.

    Code: `src/l4/llm/agent_judge.py`, `src/l4/verifier/ladder.py`, `src/l4/clarifier/clarifier.py`. Verify:
    `uv run pytest tests/unit/verifier tests/unit/llm tests/unit/clarifier -q`.
13. L4-AVL-001 — the `hello` probe retries once after 20 s on a transient status ·
    `tests/unit/availability/test_probes.py::test_a_529_hello_is_retried_once` · `src/l4/availability/probes.py` ·
    `uv run pytest tests/unit/availability -q`
14. W3 end to end — `tests/unit/verifier/test_ladder.py::test_an_overloaded_audit_writer_is_retried_in_the_run`. A
    fake adapter answers 529 once, then a test. The round finishes with no `waiting_capacity` and one
    `availability.transient`. Code: whatever lines 11–13 missed. Verify: `uv run pytest tests/unit/verifier -q`.

**Stage D — a halt in CI (W4, with W2's note)**

15. L4-CLI-001, §16.2, §16.3 (decision 6) — the changes:
    * `SEVERITY_ORDER = (1, 2, 3, 14, 13, 11, 12, 10, 0)`;
    * `_GITHUB_LEVEL[HALTED] = "warning"`;
    * the template's `exit_codes: [10, 11, 12, 13]` and its comment;
    * the GitHub render, where it lists codes.

    Tests:
    * `tests/unit/cli/test_exitcodes.py::test_a_rejected_unit_outranks_a_halted_one`;
    * `tests/unit/cli/test_map_exit.py::test_github_renders_13_as_a_warning_and_14_as_an_error`;
    * `tests/unit/ci/test_render_gitlab.py::test_a_halt_is_an_allowed_failure_and_1_2_3_14_are_not`;
    * `tests/unit/init/test_upgrade.py::test_upgrade_re_renders_the_allowed_codes`.

    Code: `src/l4/exitcodes.py`, `src/l4/ci/templates/l4.gitlab-ci.yml`, `src/l4/ci/commands.py` (if the GitHub file
    lists codes). Verify: `uv run pytest tests/unit/cli tests/unit/ci tests/unit/init -q`.
16. L4-ARC-002, L4-CLI-002 — the sticky note of a `halted` unit gets a section "Halted: `<exit_reason>`. To continue, a
    member adds the label `l4:resume` to this merge request, or runs `l4 resume --unit <id> --reason TEXT`." An
    `escalated` unit gets its own wording. The section is written by the halting run's last mirror sync. Tests:
    * `tests/unit/archive/test_hooks.py::test_a_halted_unit_note_names_the_reason_and_the_label`;
    * `::test_the_section_goes_when_the_unit_resumes`.

    Code: `src/l4/archive.py`, `src/l4/orchestrator.py` (`_notes`). Verify: `uv run pytest tests/unit/archive -q`.

**Stage E — the coverage chore adds tests (W5)**

17. L4-VER-006, D8 — `plan_fix_unit` marks coverage-hold findings `tests=True`; `FixMarker.test_chores`;
    `chore_kind(unit_dir, title) -> "fix" | "tests" | None`. Tests:
    * `tests/unit/verifier/test_fixunit.py::test_a_rejected_coverage_hold_becomes_a_test_chore`;
    * `::test_a_scope_hold_stays_a_fix_chore`;
    * `tests/unit/specs/test_fix_unit.py::test_a_marker_without_test_chores_reads_as_fix`.

    Code: `src/l4/verifier/fixunit.py`, `src/l4/specs/base.py`, `src/l4/specs/fixmark.py`, `src/l4/specs/openspec.py`
    (writes the marker). Verify: `uv run pytest tests/unit/verifier/test_fixunit.py tests/unit/specs -q`.
18. L4-IMP-004, HB-11 — the template `implementer/single_tests.md` (v1) and `IMPLEMENTER_TEMPLATES` gains
    `single_tests`, then `uv run python -m l4.templatelock --write`. The template says:
    * this task adds tests that run the changed code the finding names;
    * new test files, or new tests appended to this unit's own test files;
    * no change to an existing test or to non-test code;
    * tag a test with a criterion id only when it checks that criterion's outcome.

    Tests:
    * `tests/unit/implementer/test_prompt.py::test_a_test_chore_prompt_allows_new_tests_and_names_the_subjects`;
    * `tests/unit/test_template_lock.py`.

    Code: `src/l4/implementer/templates/single_tests.md`, `src/l4/implementer/prompt.py`, `src/l4/templatelock.py`,
    `src/l4/templates.lock.json`. Verify: `uv run pytest tests/unit/implementer/test_prompt.py tests/unit/test_template_lock.py -q`.
19. L4-IMP-002, L4-IMP-006 — `run_single(kind="tests")` (decision 7): `appended_only`, at least one new passing test,
    no non-test change, `task.tests_added`. Tests in `tests/unit/implementer/test_single_phase.py`:
    * `::test_a_test_chore_keeps_a_new_test_file`;
    * `::test_tests_appended_to_the_units_test_file_are_kept`;
    * `::test_an_edited_existing_test_is_put_back_with_a_note`;
    * `::test_a_test_chore_that_adds_no_test_fails`;
    * `::test_a_production_change_in_a_test_chore_fails`;
    * `::test_an_appended_test_that_shadows_an_existing_one_is_put_back`;
    * `::test_a_new_conftest_in_a_test_chore_is_put_back`;
    * `::test_a_fix_chore_is_unchanged`.

    Code: `src/l4/implementer/tdd.py`, `src/l4/implementer/loop.py`, `src/l4/implementer/guards.py`
    (`appended_only`). Verify: `uv run pytest tests/unit/implementer -q`.
20. MF-1 end to end — `tests/unit/orchestrator/test_review_reentry.py::test_a_rejected_coverage_hold_is_fixed_by_tests_without_a_question`:
    * the human rejects the hold;
    * the fix unit's chore adds a test file and appends one test to the unit's own test file;
    * no question is raised;
    * the next round has no coverage hold and records `task.tests_added`.

    Code: whatever lines 17–19 missed. Verify: `uv run pytest tests/unit/orchestrator -q`.

**Stage F — tests people (or a test chore) wrote count when they discriminate (W6)**

21. L4-VER-009, L4-SEC-004 — `extra_candidates(evidence, attribution, chore_files) -> {criterion: [(test, source)]}`,
    pure (decision 8). Tests in `tests/unit/verifier/test_traceability.py`:
    * `::test_a_test_only_people_wrote_is_a_human_candidate`;
    * `::test_a_file_the_harness_also_touched_is_no_candidate`;
    * `::test_a_test_chore_file_is_a_chore_candidate`;
    * `::test_a_test_ignored_for_tracing_too_many_criteria_is_no_candidate`.

    Code: `src/l4/verifier/traceability.py`. Verify: `uv run pytest tests/unit/verifier/test_traceability.py -q`.
22. L4-VER-002 step 4, L4-VER-009 — the step-4 discrimination run, `verify.extra_proof`, and proofs `human`/`chore` in
    `red_proofs` and the matrix. `red_code_in_place(wb, sha, paths)` is generalised. Tests:
    * `tests/unit/verifier/test_ladder_evidence.py::test_an_owner_regression_test_that_fails_on_the_base_is_evidence`;
    * `::test_an_owner_test_that_fails_on_zero_values_is_evidence`;
    * `::test_an_owner_test_that_passes_both_stays_ignored_with_the_reason`;
    * `::test_a_test_whose_module_does_not_exist_at_the_base_is_no_proof` (fails closed);
    * `::test_an_accepted_proof_is_not_rerun_and_a_rejection_is_rerun_at_a_new_head`;
    * `tests/unit/verifier/test_report.py::test_the_matrix_shows_human_and_chore_proofs`;
    * `tests/unit/implementer/test_tdd_green.py` (the green caller of `red_code_in_place`, unchanged).

    Code: `src/l4/verifier/ladder.py`, `src/l4/verifier/traceability.py`, `src/l4/implementer/discrimination.py`,
    `src/l4/verifier/report.py`, `src/l4/verifier/types.py`. Verify: `uv run pytest tests/unit/verifier tests/unit/implementer -q`.

**Stage G — audit-test quality (W7)**

23. L4-VER-002a, L4-VER-002 step 4a, L4-IMP-004 — the rules and the AST rejections (decision 9), `TEMPLATE_VERSION =
    3`, then the lock. Tests in `tests/unit/verifier/test_testwriter.py`:
    * `::test_inspect_getmembers_is_rejected_with_a_reason`;
    * `::test_getattr_with_a_computed_name_is_rejected_and_a_constant_one_is_not`;
    * `::test_a_secret_shaped_literal_is_rejected_and_one_built_at_run_time_is_not`;
    * `::test_a_hex_digest_literal_is_not_secret_shaped`;
    * `tests/unit/verifier/test_audit.py::test_a_rejected_reply_is_retried_once_with_the_reason`;
    * `tests/unit/test_template_lock.py`.

    Code: `src/l4/verifier/testwriter.py`, `src/l4/templates.lock.json`. Verify:
    `uv run pytest tests/unit/verifier/test_testwriter.py tests/unit/verifier/test_audit.py tests/unit/test_template_lock.py -q`.

**Stage H — the judge sees the round's own outputs (W8)**

24. L4-VER-001, L4-VER-011 — the `Written by the harness this round` block and its rubric line (decision 10),
    `PROMPT_VERSION = 6`, then the lock. Tests:
    * `tests/unit/verifier/test_prompt.py::test_round_outputs_block_and_rubric_line` (the block is absent without
      accepted audit tests; the line is always present);
    * `tests/unit/verifier/test_judge_step.py::test_the_judge_sees_the_rounds_audit_tests_and_their_outcomes`;
    * `tests/unit/test_template_lock.py`.

    Code: `src/l4/verifier/judge.py`, `src/l4/verifier/ladder.py`, `src/l4/templates.lock.json`. Verify:
    `uv run pytest tests/unit/verifier/test_prompt.py tests/unit/verifier/test_judge_step.py tests/unit/test_template_lock.py -q`.

**Stage I — labels and text (W9)**

25. L4-ARC-002, L4-QMD-005 — after answers are recorded, the mirror syncs once (decision 11). Tests in
    `tests/unit/orchestrator/test_reentry.py`:
    * `::test_needs_answers_goes_when_the_fix_units_answer_is_recorded` (the forge's label set before the chore's
      first agent step);
    * `::test_needs_answers_stays_while_another_question_is_open`.

    Code: `src/l4/orchestrator.py` (and the fix loop's clarifier call site, `src/l4/verifier/fixloop.py`, once read).
    Verify: `uv run pytest tests/unit/orchestrator -q`.
26. L4-ARC-003 — the MR body line (decision 11) · `tests/unit/archive/test_render.py::test_the_body_says_any_merge_method_works`
    (and no "squashing discards") · `src/l4/archive.py` · `uv run pytest tests/unit/archive -q`

**Stage J — the first setup of a new unit (W10)**

27. L4-SEC-005, L4-CFG-005 — `l4/sandbox/seed.py`, pure plus file system:
    * `seed_dir(cache_root, origin_url)`, where a credential in the URL never reaches the key;
    * `seed_key(uv_lock_bytes, setup_commands)`;
    * `copy_seed(seed, target)`, which re-points absolute in-seed symlinks and skips a non-empty target;
    * `seed_complete(seed, key)`.

    Tests in `tests/unit/sandbox/test_seed.py`:
    * `::test_the_key_is_per_project_and_per_lock`;
    * `::test_copy_re_points_symlinks_into_the_copy`;
    * `::test_a_non_empty_unit_cache_is_never_overwritten`;
    * `::test_an_incomplete_seed_is_not_copied`.

    Code: `src/l4/sandbox/seed.py`. Verify: `uv run pytest tests/unit/sandbox -q`.
28. L4-SEC-005, L4-GAT-001 — `ensure_uv_seed(wb)` before the first `run_setup` of a unit whose uv cache is new. It
    runs on the scratch base worktree under an flock, then copies. `cache.seeded`, `cache.seed_failed`, and
    `UV_LINK_MODE=copy` in the gate env (decision 12). Tests:
    * `tests/unit/implementer/test_setup.py::test_a_new_unit_cache_is_copied_from_the_seed`;
    * `::test_the_seed_runs_on_the_base_head_not_the_unit_worktree` (a planted change in the unit worktree is not in
      the seed run's tree);
    * `::test_the_seed_is_not_mounted_into_agent_or_gate_sandboxes`;
    * `::test_a_failed_seed_falls_back_to_todays_download_with_an_event`;
    * `::test_no_uv_lock_or_a_non_uv_setup_runs_no_seed`;
    * `tests/unit/sandbox/test_env.py::test_uv_link_mode_is_copy_when_a_uv_cache_is_mounted`.

    Code: `src/l4/implementer/tdd.py` (`run_setup`), `src/l4/sandbox/caches.py`, `src/l4/sandbox/env.py`,
    `src/l4/sandbox/seed.py`. Verify: `uv run pytest tests/unit/implementer tests/unit/sandbox -q`.

**Stage K — the wrapper (W11)**

29. scripts/dev (A12) — the cached service id and the single retries (decision 13). The fake `curl` learns
    `FAKE_PROXY_CODES=502,200` and `FAKE_TOOLS_CODES` sequences. Tests in `tests/unit/forge/test_mk_scripts.py`:
    * `::test_the_service_id_is_cached_with_the_token` (one `list_services` for two calls);
    * `::test_a_502_is_retried_once`;
    * `::test_a_401_refreshes_the_token_and_retries_once`;
    * `::test_a_second_failure_exits_22_with_the_status`;
    * `::test_the_jwt_is_never_printed`;
    * the existing three unchanged.

    Code: `scripts/dev/mk-gitlab-api.sh`. Verify: `uv run pytest tests/unit/forge/test_mk_scripts.py -q` and
    `bash -n scripts/dev/mk-gitlab-api.sh`.

**Stage L — close-out**

30. Close-out:
    * `uv run pytest -q` in the tool's background mode (never piped into `tail`), then `uv run ruff check .` and
      `uv run ruff format --check .` (no new file in the count; M1.10 left 69);
    * `uv run python -m l4.templatelock --write` leaves no diff: `implementer/single_tests` v1, `testwriter/*` v3,
      `judge` v6. The CI include is not locked and goes out through `l4 upgrade`;
    * SPEC edits, small and local:
      * L4-CLI-001: 13 is "warning (GitLab `allow_failure: exit_codes`; GitHub `::warning::` + success)", and the order
        is `1 > 2 > 3 > 14 > 13 > 11 > 12 > 10 > 0`;
      * §16.2 (`map-exit` exits 0 for 10–13) and §16.3 (`exit_codes: [10, 11, 12, 13]`);
      * §2.1 `resume`: runs no agent and needs no sandbox;
      * L4-CI-004, L4-SEC-004, SCN-RES-01: the label's mechanics. These are the latest `add` event by a member with at
        least Developer access who is not the token's user, one resume per label event (`unit.resumed{signal}`),
        `by: member`, the label removed by the next mirror sync, and refusals said once;
      * L4-AVL-006: a transient server error (529, 503, `overloaded_error`) is not a limit. Judge and verifier-agent
        calls retry it 3 times over about 2 minutes (`availability.transient`), then the role is unavailable as today;
      * L4-IMP-003, L4-VER-006: a coverage hold's fix task is a test chore;
      * L4-VER-009, L4-VER-002 step 4: the `human` and `chore` proofs;
      * L4-VER-002 step 4a: the audit writer's reflection and secret-literal rules;
      * L4-VER-001: the round-outputs block;
      * L4-ARC-003: either merge method;
      * L4-SEC-005: the per-project uv seed;
      * 12.1: the events `availability.transient`, `resume.refused`, `task.tests_added`, `verify.extra_proof`,
        `cache.seeded`, `cache.seed_failed`, and `unit.resumed{signal}`;
    * `scripts/check_spec.py` reports no problem; no openspec ticks are expected (W1–W11 refine built tasks);
    * write `docs/plan/m111-progress.md`.

## Live protocol

The protocol runs on `example-group/dummy-agentic` (118), runner 12, then on sample-consumer for MF-7. Save every job
log (ANSI and section markers stripped) under `docs/live/m111/` and token-scan them as in M1.10. GitLab reads go only
through `scripts/dev/mk-gitlab-api.sh`. No CLI login is copied, moved or refreshed.

| Step | Action | Expected |
|---|---|---|
| 0 | `uv run pytest -q` at the M1.11 head | suite green |
| 1 (W10 before) | on the runner, note the size of `$L4_CACHE/units/*/cache/uv` for dummy-agentic. From the M1.10 live logs (`docs/live/m110/`), read task start → first `gate setup pass` for a new unit | baseline seconds and the `Prepared N packages in X` line |
| 2 (W10 after, W1, W4) | push `l4 upgrade` to M1.11 and two seeds. Seed A has one task whose red, by the task text, tends to edit an existing test; seed B is a plain task | the first new unit fills the seed (`cache.seeded`, seconds). The second copies it: its first setup shows `Prepared` with no downloads, and task start → `gate setup pass` is under 1 min. Record both, against step 1. If A's red breaks an existing test, the next prompt holds the `E` line (W1, read the prompt artefact) |
| 3 (W4, W2) | let seed B's task halt (set `implementer.max_task_attempts: 1` in dummy-agentic's `main` config for this step, since branch config is ignored (SCN-CFG-01), or seed a task that cannot pass) | `l4 exit 13 (halted): …` and the job `failed (allowed)`; the pipeline on `main` is **passed**; MR label `l4:halted`, and the sticky note names the reason and the label |
| 4 (W2) | as the maintainer (Developer or more), add `l4:resume` to the halted MR; wait for the `*/30` schedule or start a web pipeline | sweep: `unit.resumed{signal: label:<id>, by: member}`, the commit `chore(<unit>): resume [skip ci]` and no pipeline for it; `run` restarts the task at attempt 1; the label set no longer holds `l4:resume`. A second pipeline does nothing for that event |
| 5 (W2 negative) | as a Reporter account, if one exists, add the label | one `resume.refused` line and one note section; no resume. If no such account exists, this rests on line 7 [U] |
| 6 (W3, opportunistic) | none: watch for a 529 in any judge or audit call | `availability.transient` events and an answer within the same run. Without a live 529 this rests on lines 11–14 |
| 7 (MF-7) | on sample-consumer, push `l4 upgrade` to M1.11, then add `l4:resume` to MR !3 | MF-7 resumes from CI (W2), and its red retries carry the error excerpt (W1). Its own uv cache exists from wave A, so no seed copy happens there; W10 is measured on dummy-agentic only |
| 8 (W11) | ten consecutive `GET projects/118` through the wrapper | one `list_services` per token; any 502 is retried once and every call ends 200 |
| cleanup | leave the MRs for the maintainer; delete the throwaway seeds | `nothing to do` |

W5–W9 rest on the end-to-end tests of lines 9, 20, 22, 23 and 24 unless wave B produces the shapes. Spend: Codex 4–6
agent steps, Claude 2–4 judge and audit calls, about $1 [I, wave-A rates].

## Risks

* **W2 trusts the forge's member level.** A Developer who adds the label resumes a unit and so spends agent quota.
  That is the trust L4-SEC-004 already gives the label. The bot is excluded by id. A project bot or token with a
  different user than the harness's own would count if it is a Developer [I: none exists on 118 or 119].
* **W2 on GitHub** is not built: no label events are read, so the label is never honoured there (fail closed).
* **W3 waits in the run** up to about 80 s per call, three times at most per round step. A real outage still parks
  the unit, as today. The retry runs only for judge, audit and clarifier calls.
* **W4 makes a halt quieter in the pipeline view.** The MR label, the sticky note and the `exit_reason` carry it. A
  project that wants red on halt can drop 13 from its include by hand, which `l4 upgrade` would overwrite [I]. That is
  a config knob for later, not built.
* **W5 widens what a chore may touch** to test files, bounded by:
  * the coverage-hold origin (a human rejected the hold);
  * `appended_only` on frozen files;
  * no non-test change;
  * the next round's diff coverage and integrity.

  A test that weakens nothing but checks little still passes the chore. The judge's adequacy review and W6's
  discrimination run decide whether it counts.
* **W6 runs agent-written or person-written tests against swapped code.** It uses the same sandbox and restore
  checks as `fails_at_red`, and it fails closed like it. A flaky owner test can be accepted once, because an accepted
  decision is cached per file content.
* **W7's secret-shape rule can reject a legitimate high-entropy fixture.** The writer is retried with the reason
  once; then the audit records `invalid`, which is a minor finding, not a block.
* **W10's seed** [U: uv's cache layout under copy; the copy time on runner 12's disk]. Whatever fails here falls
  back to today's per-unit download with `cache.seed_failed`.
  * The seed runs member-written base code with the network on. That is the same trust as the project's own CI.
  * The seed's disk use is one more copy of the project's wheels per project and per runner.
* **Pre-existing, not fixed here**:
  * `$L4_CACHE/worktrees/<fw>/<name>` and `units/{unit}` are not keyed by project, so two projects on one runner with
    the same unit name share them [V `cache_root`, `UnitNames`; I that it collides]. Recorded for a later milestone.
  * `l4 ci map-exit` printed exit 11 with another unit's exit-12 reason (job 5709), because `_run_reason` joins every
    unit's `exit_reason`. Not built: the code was right and the text only confusing.

## Overlap

No other milestone is in flight: `m111` is branched from `main` at `cb83afc`, and the strict-author change merged
there. Shared files change at small seams:
* `implementer/tdd.py`: the reasons, `run_single(kind)` and `run_setup`;
* `implementer/loop.py`: `_retry_reason`, the chore kind;
* `verifier/ladder.py`: the backends, step 4's extra proofs and the judge block;
* `verifier/judge.py`, `verifier/testwriter.py`, `verifier/traceability.py`, `verifier/fixunit.py`;
* `ci/sweeper.py`: the resume duty;
* `archive.py`: body text and the note;
* `orchestrator.py`: `resume(signal)`, the post-answer sync, `_notes`;
* `forge/gitlab.py`: label events, member access, own user;
* `exitcodes.py`, `services.py`, `sandbox/caches.py`, `sandbox/env.py`, `agents/claude_code.py`,
  `llm/agent_judge.py`, `availability/probes.py`, `gates/junit.py`;
* the CI include.

New modules hold the logic: `implementer/excerpt.py`, `ci/resume_label.py`, `sandbox/seed.py`.
