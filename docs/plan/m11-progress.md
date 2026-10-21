# M1.1 progress

One row per M1.1 line (docs/plan/implementation-map.md, "M1.1 - close the human loop"). Status: done, partial, blocked.

| line | change task | status | commit | note |
|---|---|---|---|---|
| 1 | G7 (state-vcs-locks, live) | done | b246a81 | custom refs ACCEPTED, see verdict |
| 2 | spec-providers 1.28 | done | d76c675 | byte-span parser `QuestionsFile.parse`; unknown `## ` sections end a question and are never read; code fences are opaque; missing index reported as `index is None` |
| 3 | spec-providers 1.29 | done | d76c675 | `is_answered`, `effective_answer`, `answered_by`, `answer_sha256`, `blocked_tasks`, `QuestionIssue`; an `answered`/`accepted` question with no text is not answered (`empty_answer`) |
| 4 | spec-providers 1.34 | done | d76c675, 47dc0c4 | `set_status`, `set_suggestion`, `save`; `set_status` updates only that question's index row (a row whose section a human deleted keeps its id reserved); a missing index is built once from the sections |
| 5 | implementer-tdd-loop 1.11 | done | 377ee91 | `select_next_step(tasks, blocked)`, `questions_hold`, `open_blocking_questions`, `answers_unblock`; a blocked parent holds its children |
| 6 | state-vcs-locks 1.20 | done | 28c531f | four new rows (`questions_to_clarifier`, `clarifier_answered_all`, `clarifier_needs_human`, `answers_submitted`) plus `in_review -> merged` on `pr_merged`; `rerun_requested` removed; `clarifying` is not a source of `required_role_unavailable` (SPEC row 12a lists it; the clarifier never raises exit 12, clarification-loop 1.13) |
| 7 | implementer-tdd-loop 1.27 | done | 28c531f | `Orchestrator` drives clarifying/awaiting_human re-entry; `Hooks.clarify` slot (no `HOOKS` row until clarification-loop 1.19); `explicit` parameter removed from `run_unit` and `run_unit_in_worktree` |
| 8 | clarification-loop 1.17 | done | ac78974 | `Clarifier.reenter(tasks) -> Reentry`; `question.answered`, `question.unsubmitted_answer`, `question.override`; called by the Orchestrator at the start of every run |
| 9 | clarification-loop 1.16 | done | c655ebb | `l4.clarifier.inject.render_answer_blocks(questions, redact, *, tasks) -> RenderedAnswers(text, consumed)`; redact, then defuse tags, then bound (8000 chars); `consumed` is `answer_sha256`, the value `question.answered` recorded; a dismissed question renders "Q-00N dismissed by a human: proceed without it" |
| 10 | implementer-tdd-loop 1.13 | done | c655ebb | `data_blocks` are now supplier-wrapped blocks (not wrapped a second time); `tdd._answers` reads `questions.md` at prompt time and renders the answers that hold the task or an ancestor; the prompt hash covers them; `prompt.rendered.answers = [{id, answer_sha256}]` records what each prompt carried (L4-QMD-006) |
| 11 | implementer-tdd-loop 1.14 | done | c655ebb | `contract@2`, the two rules; `prompt.rendered.template_version` is `contract@2+<phase>@1` |
| 12 | simulation-harness 1.15 | done | b04a005 | `UnitSnapshot.questions` read from the unit branch blob (regular files only, size capped) or the working tree; `UnitFacts.open_blocking_questions` / `answers_unblock` built by `facts_of` (no `LiveUnitSource` class: `load_snapshot` + `facts_of` is that adapter) |
| 13 | simulation-harness 1.13 | done | b04a005 | `awaiting_human` + unblocking answers -> `implement` ("answers submitted: Q-001"); `clarifying` -> `clarify` (now in `orchestrator.ACTIONABLE`); other `awaiting_human` and `in_review` -> `none`; no path probes. `l4 plan` / `l4 run` without `--unit` close the loop |
| 14 | G8 (state-vcs-locks) | done | b04a005 | `l4.vcs.refresh` (`unit_refspecs`, `refresh_in_ci`); `Git.fetch(refspecs=, prune=)`; `WorktreeManager.ensure` fetches base + unit branches + lock refs with `--prune`; `l4 plan` / `status` / `run` refresh first when `GITLAB_CI=true`, once per run id |
| 15 | G9 (implementer-tdd-loop, L4-ODD-004) | done | 93b2d79 | `l4.gates.odd.scenario_conflicts` / `raise_scenario_questions`, `l4.specs.criteria.base_criteria`; the orchestrator lints at the start of every run in the pre-verification phases and commits `docs(<unit>): questions [skip ci]` |
| 16 | G10 (agent-factory + clarification-loop) | done | 455ed06 | `ClarifierCfg` (typed, strict); `Factory.for_role(..., serves=)`; `l4.llm.agent_judge.open_role_judge` / `RoleJudge`, `JUDGE_ADAPTERS` (moved from the ladder), `workbench_request_factory` (the ladder's request factory, shared); preflight refuses `s1_standin: llm_boolean` with an empty `s1_judge` chain (exit 2). A profile that cannot serve a tool-less call (codex, a backend profile) is `RoleUnavailable` for these two roles, never exit 2 |
| 17 | clarification-loop 1.1, 1.2 | done | eb24f30 | `l4.clarifier.answer` (`CLARIFIER_ANSWER_SCHEMA`, `ClarifierAnswer`, `Citation`, `validate_answer`); `l4.clarifier.ports` (`QuestionView`, `QuestionsPort`, `SpecQuestionsPort`, `RoutingDecision`, `QuestionResult`, `ClarifyOutcome`) |
| 18 | clarification-loop 1.3, 1.4 | done | fc44065 | `l4.clarifier.context.ContextBuilder` (`build_prompt`, `code_context`, `base_specs`), `search_terms`, `CodeExcerpt`, `ClarifierPrompt`; documents and code each get half of `implementer.context_budget_tokens`; a code block's `source` is the bare path and its lines are `<n>: <line>`, so a model's `ref` and `quote` resolve as given (fix 2026-10-04, found in review before the first live use) |
| 19 | clarification-loop 1.5 | done | c2fed64 | `l4.clarifier.backend.BackendClarifier.answer -> ClarifierReply`; a usage limit is `unavailable` and keeps the agent run, never `RoleLimit`; live smoke test of both schemas passed against the real `claude` (`tests/unit/clarifier/test_clarifier_live.py`) |
| 20 | clarification-loop 1.7 | done | b6c29c7 | `l4.clarifier.router.resolve_citation`; the +-2 line tolerance applies to a single line and to a range (SPEC says "at the cited place", design D5 says a range is exact: the map line wins); the quote must lie wholly inside the window |
| 21 | clarification-loop 1.9, 1.8 | done | b6c29c7 | `router_question`, `citation_question`, `trim_state`, `S1Judge`, `LlmBooleanJudge`, `build_s1_judge` (opens the `s1_judge` role at the first question); the L4-CLR-003 strings are checked against docs/SPEC.md |
| 22 | clarification-loop 1.10 | done | ad0c8d6 | `l4.clarifier.router.Router(cfg, s1_cfg, s1, roots).route(view, answer) -> RoutingDecision`; thresholds come from `verifier.s1` (`reject_threshold`, `accept_threshold`, `max_state_tokens`); S1 is asked only when kinds, confidence and the citations (at least one, all resolving) already hold, and the per-citation calls are skipped once the router question says product, so `reasons` lists the conditions that were evaluated; `RoutingDecision.s1` gained `not_asked` (now its default) so a ledger line does not say `unavailable` when no call was made; `clarifier.s1_router: false` means S1 is not consulted and nothing is auto-accepted (SPEC gives the key no other meaning); `NoS1` is public |
| 23 | clarification-loop 1.12, 1.11, 1.13, 1.14 | done | ad0c8d6 | `Clarifier.run(port, prompt_for=, answerer=, router=, cfg=, profile=, blocking=, location=, link=, drafts=) -> ClarifyOutcome`; batch = open, non-verdict, blocking, no earlier `clarifier.result`, capped at `max_open_questions` (the rest wait for a later pass); `clarifier.result{id, status, profile, kind, confidence, auto_accepted, reasons, s1, p_product, citation_support, calls, cost_usd, model, prompt_sha256}` for every question looked at (key `id`, not the design's `question_id`: `clarified_ids` reads `id`); `question.answered{id, by: clarifier, answer_sha256}` with the hash taken from the re-parsed question (`QuestionsPort.answer_sha256`), so `reenter` records no override; unavailable ends the calls and the rest of the batch is recorded `unavailable`; an agent run that reported a limit is written as `availability.limit`; `meta` is one line `confidence: C · kind: K (S1 p=P)` and is prefixed to an auto-accepted answer too (the live protocol reads it there), so it is part of the text the implementer reads |
| 24 | forge-and-ci 1.7 (+ clarification-loop 1.15) | done | 00cbc6e, ad0c8d6 | `GitLabForge.upsert_sticky_note(number, body)`: marker `<!-- l4:sticky -->` at the start of the body, only a note by the token's own user (`GET /user`) counts, no write when equal; `l4.clarifier.notify.build_sticky_section` (ids, kinds, titles, path and link, unavailable / invalid / draft sentences; titles are one line with `@`, backticks, brackets and `<` neutralised); `_Mirror.sync(phase, notes)` writes it after the labels (None leaves the note alone, `()` writes "Nothing is waiting for a human answer."); the link is built from `ctx.shared["project_url"]`, which `forge_hook` now records |
| 25 | clarification-loop 1.19 | done | ad0c8d6 | `clarify_hook(ctx) -> ClarifyOutcome` (HOOKS row added; `Hooks.clarify` now returns the outcome, not a Trigger): `reenter`, then `Clarifier.run` over `BackendClarifier(AgentJudge)`, then `docs(<unit>): clarifier [skip ci]` and a push; the orchestrator maps `next_phase` to the trigger, keeps `outcome.sticky_section` as the mirror's notes and gives the edge the reason `clarifier unavailable: ...` when the clarifier could not answer; an unopenable role (`RoleUnavailable`) is handled inside the hook; `commit_questions` is shared with the orchestrator's own checkpoint commits; preflight now checks that `roles.clarifier` and `roles.s1_judge` name defined profiles (exit 2 before the lease) |
| minor | Stage A: `question.unsubmitted_answer` dedup | done | ad0c8d6 | the event carries `answer_sha256` of the draft text and is written once per id and text; `Reentry.drafts` still lists the draft on every run |
| minor | Stage A: G9 GIVEN | done | 23f66cb | `scenario_conflicts` keys on GIVEN + WHEN (an AND under GIVEN belongs to it); `ScenarioConflict.given`; a scenario with no GIVEN does not conflict with one that has it |

Stage A note closed (3f7ce0a): `effective_answer` for `accepted` and `answered-by-clarifier` returns the text `set_suggestion`
was given (after redaction). `_block` also escapes a line that starts with a backslash and `<!--` is escaped so that an
entity that already looks like the escape gains an `amp;`; `unescape_text` is the exact inverse. `Question` gained
`context_text` and `options_text`.

## Lines 22-25 (stage B, clarifier loop)

Decisions worth knowing:

- **Absent is not unavailable.** `Orchestrator._clarifier_available()` also requires a non-empty `roles.clarifier`: a repo
  with no clarifier profile sends a blocked unit straight to `awaiting_human` (map line 7), with no "unavailable" note on
  the MR. A profile that exists but cannot run (down, wrong adapter) is unavailable (L4-CLR-005).
- **Batch cap.** Questions beyond `max_open_questions` get no `clarifier.result`; the next pass takes them, which only
  happens once a human answer re-enters the unit (design D6, "per escalation").
- **Unavailable is recorded once per question.** A question that got `clarifier.result{status: unavailable}` is not sent
  to the clarifier again; a human answers it.
- **S1 workbench.** The clarifier and the S1 judge each get their own `Workbench`, built with the adapter of the profile
  that serves the call, so the sandbox shows only that adapter's login. The raw logs of both are published in `finally`.
- **Mirror notes.** `Orchestrator._notes` is None (leave the sticky note alone), a one-section tuple (awaiting a human) or
  `()` (answers came in; the note says nothing is waiting). The sticky section is built by `awaiting_section(ctx, **notes)`
  from the file as it is now, so the no-clarifier path and an idle `--unit` run get it too, with draft reminders.

TDD deviation: `test_hook.py` was written after `clarify_hook` (the first run of every test in it passed at once; the
assertions were checked against the prompt text, the pushed file and the fake forge, not only the exit code).

Doc changes owed (none made):

- SPEC L4-CLR-002 / config: `clarifier.s1_router: false` means S1 is not consulted and nothing is auto-accepted.
- SPEC L4-CLR-002: the first line of a clarifier answer or suggestion is `confidence: C · kind: K (S1 p=P)` (`· needs a
  human` on a suggestion), so it is part of what a human `accepted` and of what the implementer reads and the answer hash
  covers.
- design `clarification-loop` D1/D6: `clarifier.result` has the key `id` (not `question_id`) and also `s1`, `p_product`,
  `citation_support`, `calls`, `cost_usd`, `model`, `prompt_sha256`; `RoutingDecision.s1` has a value `not_asked`;
  `question.unsubmitted_answer` carries `answer_sha256`, once per id and text.
- design `clarification-loop` D8 / `forge-and-ci` 1.7: `upsert_sticky_note` only rewrites a note by the token's own user
  that starts with the marker (one `GET /user` per run); the note says "Nothing is waiting for a human answer." when
  answers arrive.
- SPEC L4-ODD-004: the conflict key is GIVEN + WHEN, THEN differs.

## Review fixes (`m1.1(fix)`)

| finding | status | note |
|---|---|---|
| questions.py: an unclosed fence hides later questions | done | fence lines are escaped in harness-written blocks; an unclosed fence ends at the `---` + `## Q-NNN:` the harness writes before every section, and at a `###` subheading when no fence line is left to close it; a `## Q-NNN:` heading still swallowed by a fence open at the end of the file, or sitting in the index, raises `unreadable_section` and holds every pending task |
| tdd.py: the prompt as sent was never on disk | done | `<stem>.prompt.md` next to the published events; sha256 equals `prompt.rendered.sha256` |
| odd.py: question tells the human to edit the base branch | done | the text points at the unit branch |
| odd.py: REMOVED/RENAMED base requirements conflicted with their replacement | done | `criteria.replaced_requirements` (REMOVED names and RENAMED FROM names) feeds `scenario_conflicts(..., removed)` |
| orchestrator: lint commit pushed a parked or rejected unit | done | decision: the lint commit alone does not make the branch worth pushing (`_start` moves past it); the next run raises the pair again |
| clarifier: overrides were measured against the first-seen answer | done | an override needs the id in some `prompt.rendered.answers` with a different hash; an edit before any prompt used it is a fresh `question.answered` (SCN-CLR-06) |
| questions.py: superseded / unreadable Blocking line | done | superseded holds what its named successor does not list (all of it with no successor in the file); an unanswered question with an empty or unreadable Blocking line holds every pending task and raises `unreadable_blocking` |
| tests: `--unit` does not force a re-entry | done | trigger list and probe count are compared across the two runs (the `Run` helper reads the ledger lazily: snapshot it before the second run) |
| tests: eligibility in `answers_unblock`, lint phase gate, `_splice` check | done | two tests added, mutation-checked; the `_splice` check could not fail, so it and its docstring claim are deleted (each caller derives its spans from the parse) |
| orchestrator: clarify hook raising RoleUnavailable | done | `clarifier_needs_human` with reason "clarifier unavailable: ..." (exit 11), a limit is still recorded |
| clarifier: drafts only surfaced on a run; index row never refreshed | partial | `UnitFacts.drafts` / `unreadable` appear in the plan reason; `reenter` refreshes stale index rows and the run commits them (`docs(<unit>): questions index [skip ci]`, before verification only). Not done: the sticky reminder without a run is a Stage B mirror/sweep duty |
| prompt.py: `defuse` variants and unwrapped data blocks | done | tag regex accepts whitespace around `/`, `l4`, `:`; `render_prompt` refuses a data block that is not a run of `<l4:data>` blocks |
| ci-probe-refs.sh: token in argv, lock ref pruned | partial | token rotation is a human action, recorded as owed in docs/runner/README.md; the lock-ref constraint is recorded under line 27 (the code does not exist yet) |

Doc changes owed (not made here): SPEC L4-QMD-005 should say that an `answered`/`accepted`/`answered-by-clarifier`
question with no text does not count as answered, that `superseded` hands a task to its successor only when the
successor lists it, and that an unreadable Blocking tasks line holds every pending task. SPEC L4-QMD-002 should name the
`unreadable_section` and `unreadable_blocking` notices.

## G7 verdict (2026-10-04)

Custom refs are accepted on GitLab 17.5.2 CE: `l4-bot` (token `L4_FORGE_TOKEN`, `oauth2@` push URL, per-command credential
helper) pushed, listed and deleted both `refs/l4/doctor/<nonce>` and `refs/l4/locks/probe/<nonce>` with
`--force-with-lease` (empty lease on create, sha lease on delete) from a job on `l4-runner` (git 2.34.1).
Log: [docs/runner/ci-probe-refs-2026-10-04-pipeline-2548.txt](../runner/ci-probe-refs-2026-10-04-pipeline-2548.txt)
(pipeline 2548, job 5429, probe branch `l4/probe-refs` deleted afterwards). The run used a first version of the script
that masked the token by value; the committed script masks by shape (`password=`, `glpat-`) so the value never reaches an
argv. The log was checked for token shapes (none). The local logic of the final script was re-checked against a bare repo.

**Line 27 namespace: `refs/l4/locks/<fw>/<name>` (not the `l4-lock/*` branch fallback).** G8's lock-ref refspec is
`+refs/l4/locks/*:refs/l4/locks/*`.

**Constraint on line 27 (from the review of G8).** G8 fetches `+refs/l4/locks/*` with `--prune`, so a lock ref that
`PendingLedger.publish` wrote locally before pushing would be deleted by the next fetch. Build the lock commit with
plumbing, push it straight to the remote with `--force-with-lease=<ref>:<expected>`, and write the local ref only after
the push succeeds. Test: a fetch between building the commit and the push does not lose it. (Stage B: line 27 does not
exist yet, so there is no code to change in stage A.)

## Review fixes for stage B (clarification-loop), commit `m1.1(fix)`

Fixed: a model-chosen citation ref can no longer raise (ENAMETOOLONG, huge `#L`), refs are bounded (512 chars, 7-digit
lines, range width 60, no control characters), `questions.md` and `.l4/`, `.l4-out/`, `.git/` are never citable; the
answer is bounded (1200 chars, at most 3 citations, SYSTEM asks for 600) and an S1 "no" on a cut cited text says so;
`budget.cost` for the clarifier and S1 calls and the clarifier/s1_judge profiles in `outcome.json`;
`verifier.s1.enabled: false` disables the S1 stand-in; an implementer `product`/`ambiguous` kind always blocks;
the S1 bench uses the S1 role's own `Selected`; invalid clarifier output also says "unavailable" in the sticky note;
the clarifier and S1 prompts are published as `.prompt.md`; `git grep -z` for non-ASCII paths.

Owed doc changes (not made, SPEC/openspec are read-only for this stage):
- SPEC L4-CLR-005: a clarifier result with status `unavailable` is final for the question (`clarified_ids`); a human
  answer or a later run's explicit re-trigger is the only way back (accepted risk of live step 4a). Re-entering
  automatically would loop inside one run.
- SPEC L4-CLR-002 rule 1: state that an implementer `product`/`ambiguous` kind blocks regardless of `auto_accept_kinds`.
- SPEC L4-CLR-001/002: answer at most 1200 characters and at most 3 citations; refs under `.l4/`, `.l4-out/`, `.git/` and
  `questions.md` never resolve.
- SPEC L4-ODD-004 and map gap G9: the conflict key is GIVEN and WHEN (commit 23f66cb), not WHEN only.
- SPEC L4-CLR-005: invalid-output sticky wording is "unavailable" plus the invalid sentence.

## Review fixes, round 2 for stage B, commit `m1.1(fix)`

Fixed: a ref made of dots and slashes (`.`, `./`, `.#L1`) no longer raises `IndexError` (it fails as "the path must name
a file"), and `Clarifier._decide` turns any exception of the router into an open question with reason
`router error: <type>`; harness output and `questions.md` are matched case-insensitively and on the resolved path
(a directory symlink into `.l4` is no evidence); a task that blocks again after `MAX_CLARIFIER_ROUNDS_PER_TASK` (2)
clarifier rounds in one run goes to `awaiting_human` with reason `clarifier rounds exhausted for task <key>` (a stopgap
for the L4-IMP-009 budgets, M1: implementer-tdd-loop 1.24); a task re-run after a clarifier answer keeps the blocked
step's files (`<key>-<role>-<n>-r2`); clarifier and S1 prompts are published by the request factory under the same stem
as their events (`clarify-1`, `s1-2`, ...); an S1 usage limit is written as `availability.limit` and later questions of
the run do not call S1 again; `clarifier.result.cost_usd` is null when the adapter reported no cost; the answered
questions in a clarifier prompt include those answered earlier in the same batch; the "clarifier unavailable" edge reason
comes from the question that found it unavailable; the unavailable sentence is tested against the forge note.

## Stage C, part M11-C0: stage B carry-over fixes (`m1.1(fix)`)

| line | change task | status | commit | note |
|---|---|---|---|---|
| C0-1 | clarification-loop (L4-CLR-005) | done | bed3fa0 | `Clarifier._ask`: any exception of `prompt_for` or the answerer (not `L4Exit`/`RoleLimit`, which the orchestrator parks) is an `unavailable` reply whose detail is the exception type only; questions stay open, exit 11. A unit parked in `clarifying` is resumed (plan `clarify`; test with a crashed hook then a real one). A crash outside the call (hook setup, push) still ends the run with exit 1 but the unit resumes |
| C0-2 | forge-and-ci 1.7 | done | bed3fa0 | `GitLabForge._author_id`: `GET /user`, else the project's single `project_<id>_bot_*` member (`GET /members/all?query=bot`), else `ForgeError`; the answer is kept per client. `_Forge._sticky` never raises (any exception is a warning, a `ForgeAuthError` included): the unit's exit code cannot change |
| C0-3 | clarification-loop 1.7 | done | bed3fa0 | `router.HARNESS_DIRS` also holds `.venv node_modules .pytest_cache __pycache__ .ruff_cache .mypy_cache dist build`, any depth, case-insensitive, by resolved path; `router.is_no_evidence` is public and the code excerpts of the prompt use it |
| C0-4 | clarification-loop 1.10 | done | bed3fa0 | boundary tests (0.1 and 0.9 pass, one ulp beyond fails), mutation-checked |
| C0-5 | clarification-loop 1.3 | done | bed3fa0 | numbered: spec and document blocks carry `<n>: ` (whole lines, no 300-char cut); SYSTEM says "A spec or code block"; `PROMPT_VERSION` 2 |
| C0-6 | clarification-loop 1.12 | done | bed3fa0 | `QuestionsPort.unreadable_ids()`; `Clarifier.run` counts them as open (was: `implementing` / exit 0 with an unreadable blocker); the sticky section lists them (`build_sticky_section(unreadable=)`, also from `awaiting_section`) |

## Stage C, part M11-C1: pending ledger and routed job (`m1.1(state-vcs-locks)`, `m1.1(forge-and-ci)`)

| line | change task | status | commit | note |
|---|---|---|---|---|
| 26 | forge-and-ci 1.15 | done | 4950c6a | one job `l4` (`.post`, `needs: []`, `tags`, `resource_group: l4`, `timeout: 180m`, `allow_failure.exit_codes`, `GIT_DEPTH "0"`); rules in order: never for a push with `\nL4-Run: `, push to the default branch, push to `l4/**`, sources schedule/web/api/trigger; `before_script` is one quoted line that fetches the default branch and checks it out detached unless the job is on it; script `doctor`, `plan --sweep`, `run`, each `|| l4 ci map-exit $?`. `l4 run` with no actionable unit logs `nothing to do` and returns 0 before any lease, worktree or probe (`run_command`). Golden test, `': '` test over before_script/script/after_script, subprocess tests of the before_script against a bare remote (clone without `origin/main`, stale `origin/main`, on the default branch, failed fetch). **Depends on line 36**: `l4 plan --sweep` still exits 2 ("not yet implemented"), so the job's second script line fails until the sweeper exists |
| 27 | state-vcs-locks 5.4 | done | 50b415d | `l4.state.pending.PendingLedger(git, lock_ref=, unit=, run_id=, ...).publish(run_file) -> sha`; plumbing only (`hash-object`, `mktree`, `commit-tree`), message = L4-LCK-001 JSON, `[skip ci]`, `L4-Unit`, `L4-Run`; parent and kept files come from the remote's value (`ls-remote`); pushed with `--force-with-lease=<ref>:<expected>` (`Git.push_lease`, `build_lease_push_args`: lock refs only, `build_push_args` still refuses force); the local ref is written after the push succeeded; a lost lease rebuilds on the new value (3 attempts, `PendingNotPublished`), any other refusal is a `GitError` for `explain_push_failure`. Bare-remote tests: the commit, tree and blob arrive and `fsck` is clean; a prune fetch between build and push does not lose the commit |
| 28 | state-vcs-locks 5.5 | done | 50b415d | `l4.state.pending.read_pending`, `merge_ledgers(branch, pending)` by `(run_id, seq)`; equal key with a different `(ts, type, payload)` is `LedgerCorrupt`; `load_snapshot` folds branch-or-worktree plus the local lock ref (so `l4 plan`/`status`/`run` see `in_review`); `Orchestrator` does too (a rerun of a unit in review must not hand off twice: tested) |
| 29 | forge-and-ci 2.43 | done | 50b415d | `Orchestrator.close`: in `in_review`, `archived` or `merged` the run's whole file goes to `PendingLedger.publish`, no commit or push to the unit branch; M0's `chore(<unit>): ledger` commit after H and its `[skip ci]` exception are removed. SCN-CI-18 test: branch head equals H, the lock ref holds `ledger-pending/<run>.jsonl` ending in `run.finished`, the branch copy is a prefix of it |

Decisions and facts worth knowing:

- **The whole run file is published**, not a diff of the tail: the lines H already holds fold away by `(run_id, seq)`, so no cut point is tracked.
- **The pending commit is born expired** (`expires_at == acquired_at`): nothing holds a lease (M1.1 simplification), and M2 may take the ref over at once. The JSON has exactly the six L4-LCK-001 fields.
- **Pending files are never dropped here.** State-vcs-locks 5.6 (the archive commit of line 33) folds them into the archived ledger.
- **Other readers of the ledger.** `archive.py` (`_ensure_mr`, `_labels`, `handoff_hook`), `clarifier`, `tdd` and `ladder` still fold the worktree ledger only. None of them runs for a unit in review (the planner says `none`), and the orchestrator, which decides the phase, does read the pending files.
- **A hook that declines the lock ref** ("pre-receive hook declined") is exit 3 through `explain_push_failure`, as for a branch; G12 (line 38) refines that classification. A `[remote rejected]` that is not a lost lease is not retried.
- **TDD deviation (line 26):** the template was rewritten before its tests; the updated golden and rule tests were then run against it (the old template fails every one of them by name: `l4-run`, no timeout, `$L4_UNIT` rule). The runner-fetch assumption behind the before_script (a GitLab runner fetch brings the pipeline's ref but not necessarily a fresh default branch) is [I], so the line fetches the default branch itself.
- Mutation checks (reverted): writing the local lock ref before the push fails `test_a_stale_lease_is_retried...`; folding only the worktree ledger in `Orchestrator._ledger` fails the rerun test.

Doc changes owed (not made): SPEC §16.3 and L4-CI-001 describe `l4-detect` plus child pipelines; the single routed job is the M1.1 form (map line 26). L4-STA-004 / L4-LCK-001: a pending commit carries `L4-Unit` and `L4-Run` trailers and an already-expired `expires_at`. forge-and-ci 2.43 / state-vcs-locks 5.4: the whole run file is published, the fold dedupes by `(run_id, seq)`.

## Stage C, part M11-C2: merge, archive, upgrade (`m1.1(forge-and-ci)` and others)

| line | change task | status | commit | note |
|---|---|---|---|---|
| 30 | forge-and-ci 1.31 | done | 3a4d58e | `PullRequest.merge_commit_sha`; `Forge.get_pr`, `Forge.list_prs(head_prefix, state)` (GitLab has no prefix filter: all MRs of the state are paged and filtered here); states `open / merged / closed / all` |
| 31 | forge-and-ci 1.32 | done | 3a4d58e | `l4.postmerge.MergeDetector.classify(pr, name) -> MergeVerdict` (`needs_archive`, `archived`, `unknown`): `ls-tree` at `merge_commit_sha`; no sha (fast-forward) asks the head of `origin/<base>`; an unknown sha is fetched for once, then `unknown` |
| 32 | spec-providers 1.23 | done | e5706ea | `OpenSpecProvider.done_gate` (every checkbox done, a unit without tasks fails), `archive`: gate, then strict validate, then `archive <id> --yes --json` (TZ=UTC is in `openspec_env`); `ArchiveRefused`, `ArchiveFailed(error_code)`, `GateReport`, `ArchiveReport`. The post-archive `validate <cap> --type spec --strict` of L4-OSP-003 is NOT done (deferred, see below) |
| 33 | forge-and-ci 1.33 (+ state-vcs-locks 5.6 reduced) | done | 3a4d58e | `PostMergeArchiver.open_archive_pr`: worktree from the latest base (`WorktreeManager.ensure_from_base`), pending files folded into the unit's `.l4/ledger/` before the CLI moves the folder, one commit `chore(<name>): archive` with `L4-Run` and `L4-Phase: archived`, no `[skip ci]`, push with the forge credentials, ready MR `[l4] archive <name>`. Verified against the real pinned OpenSpec (`tests/unit/archive/test_post_merge_live.py`, L4_LIVE=1) |
| 34 | forge-and-ci 1.34 | done | 3a4d58e | after `archive` and `git add -A`, every changed path must be under `changes/<name>/`, `changes/archive/<archivedAs>/` or be `specs/<cap>/spec.md` of a capability of the unit's deltas; otherwise `archive.failed` in the pending ledger, no branch pushed, no MR |
| 35 | forge-and-ci 1.35 | done | 3a4d58e | no archive MR while another `l4/archive/` MR is open (`pending`); an open MR of the unit is `existing`; a pushed branch without an MR gets its MR; a branch whose MR a human closed is left alone (`skipped`) |
| 36 | forge-and-ci 1.36 | done | 3a4d58e | `l4.ci.sweeper.Sweeper` / `sweep(...)` behind `l4 plan --sweep` (sweeps before it plans); `l4 archive --unit ID` = the same duty for one unit (`run_archive`). `in_review` + merged MR -> `phase.changed in_review -> merged` (`Trigger.PR_MERGED`) in the sweep run's ledger file, published to the lock ref, then the archive. The sweep run's file lives in `$L4_CACHE/sweeps/...`, never in the unit folder, so the archive diff is the move only. Idle sweeps write nothing and push nothing. **Unblocks the template's second script line** |
| 37 | G11 | done | 122763a | `l4 upgrade [--harness PATH] [--dry-run]` (`l4.init.upgrade:run_upgrade`, `commands.HANDLERS`, `cli.py`); refuses without a config (exit 2, "run l4 init first"); vendor swapped in atomically, template and shim re-rendered, `harness.version` and `harness.commit` rewritten in place (quotes and trailing comments kept, other bytes untouched), config reloaded; `.gitlab-ci.yml` and `.gitignore` untouched; prints what changed and the schema keys the file lacks |
| 38 | G12 | done [I] | b9ce10c | `Git.push` raises `PushRejected` only for `! [rejected] ... (non-fast-forward | fetch first)`; `Git.push_lease` only for a lost lease; `! [remote rejected]` and pre-receive texts are `GitError`s that `explain_push_failure` turns into exit 3 "the forge refused the push (protected branch or push rule)" when a permission marker matches, else exit 1 naming the server's reason; never "non-fast-forward". The two GitLab texts are NOT recorded from the live server (`tests/fixtures/gitlab_push/README.md`): the classification is [I] (inferred from GitLab's documented messages) until one protected-branch and one push-rule refusal are recorded during G13 |
| 39 | verifier 1.5 | done | 0db001b | `PROMPT_VERSION = 2` (`judge@2`): "The harness does not run it: it is recorded for a human to read" |
| 40 | forge-and-ci 1.10 | done | 3a4d58e | `proposal_title`: the `# ` heading minus a leading `Proposal:` (case-insensitive), the first line under `## Why` as the fallback; the body never has an `L4-Run:` line (test) |
| 41 | G13 | done (not run) | a9a736e | `tests/live/test_m1_1_acceptance.py` (marker `live`, L4_LIVE=1) with `tests/live/gitlab_client.py`; one test per protocol step 0-8, read-only (GET only; unit-tested with a mock transport in `tests/unit/live_support/`); a test whose step has not happened skips, one whose step went wrong fails; ids go to `L4_LIVE_RECORD` (default `/tmp/l4_m1_1_ids.json`). **Never run against the live server** |

Decisions and facts worth knowing:

- **Sweep exit code.** `l4 plan --sweep` exits 0 after a definitive archive failure (`archive.failed` is written once to the pending ledger and the unit is not tried again until the base head or the unit folder's tree changes, or `l4 archive --unit ID --retry`; never delete the lock ref, it holds the pending ledger, see Review fixes). The template's script stops at the first failing line, so a failing sweep would stop `l4 run` in every later pipeline. `l4 archive --unit` exits 13 for the same failure. Forge and git errors are not failures of this kind: they raise (a refused push is exit 3), and the next pipeline tries again.
- **Sweep ledger.** One file per sweep run and unit, opened at the first event only. The merged event is published before the archive build (it folds the lock ref), the rest and `run.finished` after.
- **No `archive.done`** (map): the unit leaves the plan when its folder leaves `openspec/changes/`.
- **Pending files are folded as the whole run file**; a branch copy that is not a byte prefix of it, or events that differ under one `(run_id, seq)`, stop the archive (`archive.failed`).
- **`proposal_title` changed meaning** (heading first). `tests/unit/archive/test_render.py` was rewritten accordingly.
- **Refactors:** `init.py`: `validated_config`, `swap_in_vendor`, `write_planned_file` are public (used by `upgrade.py`); `forge.gitlab.push_auth_config(cfg, environ)` is the one place that builds the push `-c` pairs (the archive hooks and the archiver); `WorktreeManager.ensure` split into `_refresh_and_clear` / `_add`, `ensure_from_base` and `remove` added; `UnitNames` gained `archive_branch` and `archive_worktree`; the dispatch test now lists `upgrade` and no longer expects `archive` to be a stub.
- **Flaky existing test:** `tests/unit/agents/test_proc.py::test_interrupt_sends_sigint_then_the_run_ends` failed in 3 of 4 full runs of this part (the child is SIGKILLed before it prints; returncode -9) and passes alone. Not touched.

Deferred (named): L4-OSP-003's post-archive `validate <cap> --type spec --strict --json` (`# M1: spec-providers 1.23`); `auto_merge_archive_pr`, numbered rebuild of an unmergeable archive MR, `archive.done` (forge-and-ci 2.55); lock-ref cleanup on merge (2.51); closed/reopened MRs (2.53).

Doc changes owed (not made): SPEC §2.1 gains `l4 upgrade`; L4-ARC-002 title (heading first, `Proposal:` removed, Why line as fallback); L4-OSP-003 (post-archive validation not done in M1.1; archive failure of the sweeper is `archive.failed`, not `escalated`); L4-ARC-007 (an archive MR whose branch exists and whose MR a human closed is not reopened); forge-and-ci 1.33 (the pending ledger is folded as whole run files before `archive`); forge-and-ci 1.7 / 1.36 (`plan --sweep` exits 0 on an archive failure); G12 text (`pre-receive hook declined` is no longer a credential marker).


## Review fixes of stage C (`m1.1(fix)`)

| finding | status | note |
|---|---|---|
| H pushed, then a failed MR update puts the tail on the unit branch (forge-and-ci 2.43) | fixed | `handoff_hook` sets `HookContext.shared[H_PUSHED]` right after the push; `Orchestrator.close` sends the tail to the lock ref when the phase is after hand-off or that flag is set. `tests/unit/archive/test_handoff_failure.py`: the first run fails with a 502, the branch head stays H, the tail is in the lock ref, the second run marks the MR ready with head == H |
| `_fold_pending` followed symlinks of merged repo content | fixed | `reject_symlinks(unit, ".l4", "ledger")` turns into `ArchiveBlocked` (`archive.failed`), the resolved target must stay in the unit folder, a symlinked `<run>.jsonl` is refused. `tests/unit/archive/test_fold_symlink.py` (symlinked `.l4` and `.l4/ledger`: failed, no branch, no MR, nothing written outside) |
| a refused archive push or a forge 4xx stopped the whole sweep | fixed | `Sweeper.run` isolates each unit. A push refused by the server's hooks (`PushFailed.refused`) and a 4xx that is not 401/403/408/429 are recorded as `archive.failed`; other infrastructure errors are logged and retried by the next pipeline; only exit 3 (environment) and bugs are re-raised, after the last unit. `plan --sweep` therefore exits 0 and `l4 run` is reached |
| "delete the lock ref to retry" dropped the pending ledger | fixed | the docstring no longer says it. `archive.failed` records `base` (head of the base branch) and `tree` (the unit folder's tree at the base); the sweeper tries again when either changed. `l4 archive --unit ID --retry` ignores the record (a cause outside the repo, such as a push rule fixed on the forge). **Doc owed:** SPEC §2.1 gains `--retry` on `l4 archive`; the doc owed for forge-and-ci 1.36 should say "retry with `--retry`", not "delete the lock ref" |
| G13 step 6 base-checkout check could not fail | fixed | the template prints `l4: base checkout <sha>` after the checkout; the live test asserts that line (not GitLab's echo of the script), that the sha is not the pushed head and that it is on main |
| fork MRs passed for harness branches (minor) | fixed | `GitLabForge.find_pr` / `list_prs` drop MRs whose source project is not the target project |
| `l4 archive --unit` exited 0 on a recorded failure (minor) | fixed | exit 13 with "archive.failed is recorded" |
| G12 fixtures never recorded (minor) | not fixable offline | marked [I] in line 38; recording needs the reference server during G13 |
| `FakeGitLab` ignored `order_by`/`sort` (minor) | fixed | `updated_at` per MR; test: two merged MRs of one branch, the newest wins |
| clarifier hid harness bugs behind exit 11 (minor) | fixed | exit 11 kept; the traceback is logged at DEBUG |
| job token could reach a git error line (minor) | fixed | `CI_JOB_TOKEN` is always redacted (`RUNNER_SECRET_ENV`, not part of the config defaults), a `glcbt-` shape, and `sweep()` strips credentials from the origin URL as `forge_hook` does |


## Review fixes of stage C, round 2 (`m1.1(fix)`)

| finding | status | note |
|---|---|---|
| G13 step 5 failed on GitLab's `refs/merge-requests/<iid>/head` pipelines (major) | fixed | `tests/live/protocol.started_by_a_lock_ref_push` looks at the lock namespaces only (`refs/l4/`, `l4-lock/`); merge request pipelines must be skipped or have no `l4` job. Unit tests in `tests/unit/live_support/test_protocol.py`. Live read-only run: step 5 passes |
| steps 2, 4a and 6 skipped whole when no `L4_FORGE_TOKEN` (major) | fixed | the lock-ref assertions are their own tests (`test_step2_lock_ref_...`, `test_step4a_lock_ref_...`, `test_step6_lock_ref_...`); the API checks of the steps always run. `LiveRemote` without a token variable uses the operator's own git credentials (no `credential.helper` reset, no prompt); `L4_LIVE_GIT_TOKEN_ENV` names a variable with a `read_repository` token. A lock ref that git cannot read skips only its test; one that is read and missing fails |
| steps 4b and 7 failed on the state before their step (major) | fixed | 4b skips unless the `Seed add-average-price` commit is on main and the add-vat MR was created after it; 7 considers only `web`/`api` pipelines created after the seed commit (`protocol.happened_after` compares instants across UTC offsets) |
| a reused change name started as `merged`; the merged MR was matched by branch only (minor) | fixed | `Sweeper._own_mr` takes the merged MR whose URL is the ledger's `pr.updated` url (the latest of the branch when none was recorded). Once the archive MR has merged and the folder is gone from the base, `Sweeper._retire` moves the lock ref to `refs/l4/archived/<fw>/<name>/<run-id>` (same commit, pending ledger kept) with one atomic push under a lease on both refs (`Git.retire_lock_ref`). Tests: `test_a_name_used_again_after_its_archive_starts_fresh`, `test_an_older_merged_mr_of_the_same_branch_is_not_the_units_mr`, `tests/unit/vcs/test_push.py`. **Not run against the reference server:** pushing `refs/l4/archived/*` (G7 only recorded `refs/l4/locks/*`); a refusal is logged and retried by the next sweep. Deferred: deleting the archived refs, WIP-branch cleanup (2.51) |
| `list_prs` outside the per-unit isolation (minor) | fixed | a non-auth `ForgeError` is logged and the sweep does nothing this time (exit 0, `l4 run` is reached); `ForgeAuthError` is still raised (exit 3) |
| a hand-off run that could not publish its pending tail lost it (minor) | fixed | the run file is copied to `$L4_CACHE/pending-unpublished/<fw>/<name>/<run>.jsonl`; the next `Orchestrator` publishes those files before it reads the lock ref and drops the copy once published. `test_a_tail_that_could_not_be_published_is_published_by_the_next_run` (pre-receive hook refusing `refs/l4/locks/*`) |
| `MergeVerdict.ARCHIVED` and `UNKNOWN` of the sweeper untested (minor) | fixed | two tests added; the misleading one is renamed `test_a_merge_that_carried_the_archive_leaves_no_unit_to_sweep` |
| rule 1 of the template suppressed the job on a fast-forward merge (minor) | fixed | rule 1 only for `$CI_COMMIT_BRANCH != $CI_DEFAULT_BRANCH`; golden test updated plus `test_a_fast_forward_merge_of_a_handed_off_unit_still_starts_the_job` |
| proxy 5xx failed a live check (minor) | fixed | `LiveGitLab._request` retries 502/503/504 after 1, 2 and 4 s (unit tests with a mock transport) |

Doc owed (not made): SPEC L4-ARC-003/§12 "lock ref deleted on merge" is, in M1.1, "moved to `refs/l4/archived/...`" (G7 for the archived namespace is unrecorded); docs/live/README.md should say how the operator gets a read token for the lock-ref tests (`L4_LIVE_GIT_TOKEN_ENV`).
