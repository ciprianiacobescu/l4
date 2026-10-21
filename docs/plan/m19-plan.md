# M1.9 — re-verification after the hand-off, and the PR-1 findings (planned 2026-10-05)

## Goal

On sample-consumer PR-1 (MR !1, project 119) the harness handed off a unit whose hand-off commit H was red in the
project's own CI, and when the owner then pushed a CI fix to the unit branch, every later `l4` run printed
`in_review: waiting for merge`. SPEC 12.0 has two rows for this that are not built:
* `in_review` + any commit after H not made by the harness → `verifying` (G1, SCN-ARC-16);
* `in_review` + the repository's own CI fails on H → `verifying` (G2 = P1, SCN-ARC-14, SCN-ARC-19).

M1.9 builds both rows, with loop safety. It also builds the per-commit attribution of integrity findings, so a human
change made during review is listed and not held against the unit (G3, sandbox-security 2.10). It closes the five
smaller findings P2–P6. **32 build lines**, test first. P7 (MR title) is M1.8 R6. P1(b) (doctor compares
`gates.setup` with the project job's install line) belongs to M1.8's `doctor --adoption` and is not built here.

Source: `docs/adoption/sample-consumer/findings-pr1.md` (P1–P7, G1–G3).

## Coverage: finding → build lines

| Finding | Lines | Finding | Lines |
|---|---|---|---|
| G1 human commit after H never re-verified | 1–4, 6–11 | P2 judge misses the skip convention for optional extras | 22, 23 |
| G2 / P1 project CI red on H never acted on | 3–6, 8, 11–18 | P3 audit test re-imports, raw-error failure, no header style | 22, 24 |
| G3 human edit of a forbidden path would be a finding | 19–21 | P4 `l4` marker not registered | 25, 26 |
| | | P5 forge hostname in committed ledgers | 27–29 |
| | | P6 wrong iteration on resume; presatisfied gate reads as a failure | 30, 31 |

## Facts this plan rests on

Labels: [V] read in code or files at `e7de0c6`; [I] inferred; [U] not checked.

* **The review rows are absent** [V]:
  * `state/lifecycle.py` TRANSITIONS: the only `in_review` edge is `PR_MERGED → merged`;
  * `planner.py` `_NOT_ACTIONABLE`: `in_review: waiting for merge`;
  * `orchestrator.py` `_NOTHING_TO_DO` holds `IN_REVIEW`, and `_drive` logs `nothing to do`, exit 0;
  * `ci/sweeper.py` `_sweep`: `in_review` and no merged MR → `return None`.
* **The harness recognises its commits** by bot name **and** e-mail **and** a non-empty `L4-Run` trailer
  [V `verifier/provenance.py` `_is_bot`]. This is L4-ARC-008's rule ("author identity and missing `L4-Run`").
  * `Git.commit` defaults to `BOT_IDENTITY` (`l4-bot`, `l4-bot@users.noreply.invalid`), and `trailers.render`
    refuses a commit without `L4-Run` [V `vcs/git.py`, `vcs/trailers.py`].
  * `provenance` imports `implementer.workbench`, and `verifier.ladder` imports `planner` [V]. So the planner and
    `state/status.py` cannot import `provenance`, and the reader must move to the `vcs` layer.
* **H** is `docs(<name>): hand off to review` (`archive.HANDOFF_SUBJECT`, unchanged since M0 [V `git log -S`]), with
  trailers `L4-Run` and `L4-Phase: verified` and no `[skip ci]` [V `archive.handoff_hook`].
  * `pr.ready{url, number}` does not record H's sha [V].
  * The hook makes H only when `rev-list --count --grep=<subject> origin/<base>..HEAD` is 0 [V]. After a re-entry H1
    is in that range, so a second PASS would push a `[skip ci]` head and no H2 (an L4-ARC-008 breach, and G2 could
    never read that head).
* **After H the branch stays at H** [V `orchestrator.close`, `_AFTER_HAND_OFF`, `state/pending.py`]: the run's
  ledger goes to `ledger-pending/<run-id>.jsonl` on the lock ref. In `post_merge_pr` mode the harness pushes nothing
  to a ready MR's branch (L4-ARC-007).
* **Only `post_merge_pr` exists** [V `config/schema.py` has no `archive` section]. So nothing reaches `archived` before
  the merge, and approvals, the approval label and archive reverts (L4-ARC-001/004/006) have no code.
* **The verifier reads only the worktree ledger** [V `ladder._events` = `read_ledger(wb.ref.path)`]. It never reads
  the lock ref's pending files.
* **CI routing** [V `ci/templates/l4.gitlab-ci.yml`, `l4.github.yml`]:
  * the `l4` job runs on a push to `l4/**` unless the head message has `L4-Run: `; it also runs on a push to the
    default branch, on `schedule|web|api|trigger`, and each job runs `plan --sweep` then `run`;
  * GitHub has a `*/30` schedule;
  * GitLab gets one from M1.8 A9 (`l4 setup gitlab`, `*/30`) [V m18 plan line 31].
  * H carries `L4-Run`, so H's own pipeline has no `l4` job. A sweep therefore reads H's pipeline from a later
    pipeline: a schedule, a push to the default branch, or a human push.
* **Sweep writes cost** [V `sweeper._UnitRun`]:
  * every publish is a lock-ref commit;
  * every sweep run that writes appends a `run.started`, and the fold counts `run.started` as iterations
    [V `state/fold.py` `_run_started`].
* **Forge reads** [V]:
  * GitLab `_pages` yields from a JSON list (pipelines and jobs are lists);
  * GitHub `_pages` also expects a list, but `commits/{sha}/check-runs` returns `{"check_runs": [...]}` [I GitHub
    docs], so it needs its own reader;
  * FakeGitLab and FakeGitHub have no pipeline, job or check-run routes;
  * the forge port of design D4 names `JobResult(name, status, pipeline_id, web_url)` and `list_pipeline_jobs(sha)`
    (forge-and-ci 1.1, 2.2).
* **Integrity attributes nothing per commit** [V `verifier/integrity.py`]:
  * `check_protected` diffs base..head by path, so a forbidden path a human changed is a blocker;
  * `check_tests` flags every skip marker the head has and the base does not, whoever added it.
  * The scope check (`evidence/scope.py`, default `warn`) turns an out-of-scope **code** file into a hold, and
    `aggregate_unit` makes any hold NEEDS_HUMAN [V]. Root files (`.gitlab-ci.yml`) are "not judged" [V `file_kind`].
* **Test fixture identity** [V `tests/unit/verifier/_integrity_helpers.py`]: `Repo.commit` commits with the test
  identity plus `L4-Run`, which per-commit attribution would read as a human commit; `commit_as_harness` uses the bot.
* **Agents cannot commit**: the agent sandbox mounts `.git` read-only [V `sandbox/bwrap.py` docstring, L4-SEC-005]. No
  agent-commit guard exists [V `grep agent_commit`: only a docstring].
* **Judge prompt** [V `verifier/judge.py`]: spec, criteria, `git diff`, gate report and the implementer's hint only;
  `PROMPT_VERSION = 3`. **Audit writer** [V `verifier/testwriter.py`, `audit.py`]:
  * `TEMPLATE = "testwriter@1"`, and the template lock does not pin it [V `templatelock.current`,
    `tests/unit/test_template_lock.py` `CASES`];
  * the writer sees the head source of the changed non-test modules only;
  * `run_audit` does not retry an invalid reply;
  * `_check` parses the code but inspects nothing in it.
* **The `l4` marker** is registered only by the harness's own plugin `gates/pytest_trace/l4_trace.py`, which the
  project's CI does not load [V].
* **Forge URLs in committed files** [V]: `pr.updated{url}`, `pr.ready{url}` (`archive.py`) and `archive.opened{url}`
  (`sweeper.py`). `LedgerWriter.append` writes one payload to the file, to the JSONL mirror (`.l4-out/logs`) and to
  the observers (the console trace). Two comparisons use the URL:
  * `archive._ensure_mr`: `fold(...).pr != pr.url`;
  * `sweeper._own_mr`: `pr.url == wanted`.

  In the archive tests the forge host is `gitlab.example.test` for both `CI_API_V4_URL` and the MR `web_url`
  [V `tests/unit/forge/conftest.py`, `archive/conftest.py::forge_env`].
* **P6** [V]:
  * `run_unit_in_worktree` opens the ledger with `iteration=snapshot.state.iteration`, the count **before** this run;
  * `_commit_ledger` and the hand-off use `max(state.iteration, 1)` after the fold, which counts this run;
  * the zeroed runs are gates named `test-presatisfied` (`discrimination.py:303`) and `test-zero` (`:138`), and
    `progress._gate` prints them like any gate.

## Decisions

1. **The sweep records, the orchestrator transitions.** The task text has the sweep move a red-CI unit to
   `verifying`. Here the sweep only writes the fact `ci.failed` to the pending ledger, and `l4 run` (the next script
   line of the same job) takes the edge. Reasons:
   * the edge must set the MR to draft before the first push (decision 6), and only the orchestrator has the mirror;
   * the step-0 blocker needs the CI detail in the run's own ledger, which is the only ledger the verifier reads (see
     Facts);
   * one component takes all three review edges.

   `l4 plan` reports `verify` as soon as the fact exists, so the state is never hidden. The sweeper's existing
   `PR_MERGED` edge is unchanged.
2. **Harness commit** = bot name **and** bot e-mail **and** a non-empty `L4-Run` (the existing `_is_bot`, moved to
   `l4/vcs/authorship.py`). Every other commit is foreign. **H** is the newest commit on the first-parent chain of the
   branch head that is a harness commit with `L4-Phase: verified` and subject `HANDOFF_SUBJECT.format(name)`. The
   scan stops after 500 commits. If no H is found while the unit is `in_review` (history rewritten), the result is
   `lost`, which re-verifies like a foreign commit. `HANDOFF_SUBJECT` moves to `authorship`, and `archive` imports it.
3. **Precedence.** Foreign commits after H come first (G1), then a CI failure recorded for H (G2), else nothing to do.
   G2 acts only when the branch head **is** H: a later human commit supersedes the old pipeline (in PR-1 the owner's
   commit fixed exactly that).
4. **Routing of foreign commits (both SPEC rows built).**
   * If the net diff `H..head` touches the unit folder outside its harness-owned files (`verification.md`, `.l4/**`),
     these are "answers or spec edits", which go to `implementing` (trigger `spec_edit_after_handoff`). With every task
     done, `implementing` goes on to `implemented` and `verifying` in the same run; an added task is implemented.
   * Anything else goes to `verifying` (trigger `commit_after_handoff`).
   * Edge context: `{handoff, commits: [{sha, author, subject}] (≤ 10), lost}`.
5. **Sources: `in_review` only.** `archived` before the merge exists only in `on_approval`, and leaving it requires the
   archive revert first (L4-ARC-004), which is not built. Adding `archived` as a source would skip that revert. The
   approval-voiding half of L4-ARC-008 and SCN-ARC-16 is N/A without `on_approval`, so forge-and-ci 2.41 is ticked
   with that note.
6. **Draft before any push.** `_Mirror.sync` sets the MR to draft (`update_pr(draft=True)`) whenever the phase is
   neither `in_review`, `archived` nor `merged` and the MR is not a draft. It only ever flips toward draft: marking
   ready stays the hand-off's job.
   * The review edges are the first thing `_drive` does in the run, and `_go` syncs the mirror, so the draft flip comes
     before the run's first push (L4-ARC-008 (c)).
   * Labels follow the phase (`l4:verifying` / `l4:implementing`).
   * A sticky section `### Re-verifying after the hand-off` names the reason (the commits, or the red jobs with H).
   * Commit status `pending` is N/A (forge-and-ci 1.8 is not built).
7. **Hand-off idempotency.** H is made unless HEAD **is** this unit's H, which covers the retry after a failed
   `update_pr` (`test_handoff_failure.py`). `pr.ready` gains `head` (H's sha) as a record; nothing reads it for
   decisions.
8. **What counts as red** (`l4/ci/repo_ci.py`, pure):
   * The jobs are those of every pipeline for sha H, newest pipeline first, keeping the newest pipeline's job per name.
   * The jobs named `l4` are ignored (the harness's own; on GitHub a skipped check run).
   * Red: `failed` and not `allow_failure`.
   * Unfinished (`created|waiting_for_resource|preparing|pending|running|scheduled`; GitHub `queued|in_progress`)
     defers the decision. A still-running pipeline is not a failure.
   * `manual`, `skipped`, `canceled` (GitHub `neutral|skipped|cancelled`) are not red.
   * **Base comparison** (L4-ARC-002, SCN-ARC-19): the same rules on the base head's sha.
     * A job red on H and red on the base is `preexisting`.
     * A base pipeline that is still running defers.
     * No base pipeline, or no job of that name on it, counts the job as **new**. A unit should not hand off red;
       the cost is at most one fix round per H, bounded by `max_fix_rounds`.
9. **Writes once per H, only on red.**
   * `ci.failed{head, pipeline, jobs: [{name, stage, url, tail}], preexisting: [names]}`, or
     `ci.preexisting{head, pipeline, jobs: [names]}` when every red job is pre-existing.
   * Green, running or deferred: one INFO log line, no lock-ref commit (Facts: every publish is a commit and bumps
     the fold's iteration).
   * The fold keeps `ci_heads: {head: failed|preexisting}` (the idempotency key) and `ci_failure` (the last
     `ci.failed`).
   * `tail` is the job log, at most 40 lines and 3,000 characters, ANSI-stripped and redacted, for at most 3 jobs;
     the other red jobs are listed by name. On GitLab it comes from `jobs/:id/trace`; on GitHub from
     `actions/jobs/:id/logs`, with the redirect followed without the token. A check run that is not from Actions
     has no tail.
10. **The round.**
    * The orchestrator's `phase.changed{trigger: repository_ci_failed}` carries the `ci_failure` data into the run's
        own ledger.
    * Verifier step 0 adds one deterministic blocker per red job, `repository CI failed: <job>` (the SCN-ARC-14 text);
        the detail holds stage, H, URL and tail. This happens only while no `verify.verdict` follows that event, so in
        the first round after the edge only.
    * Step 0 fails, so the verdict is FAIL with no judge call, and `plan_fix_unit` makes one `[chore]` task per job
        (M1.3 D8).
    * The next round is a full ladder without these blockers. Its PASS makes H2, and H2's pipeline is judged afresh.
    * Known cost: `verify_hook` selects the judge before the ladder [V], so this round still needs a judge profile
        (exit 12 without one).
11. **Loop safety**, by construction:
    * (a) every harness commit is bot + `L4-Run` (Facts), so its own commits are never foreign;
    * (b) the reference point moves to H2 at the next hand-off;
    * (c) in review the harness pushes nothing to the branch;
    * (d) H2 and every harness push carry `L4-Run`, so they start no `l4` job;
    * (e) G2 acts once per H;
    * (f) fix rounds are bounded by `max_fix_rounds` and end in `escalated`.

    Tested in line 12.
12. **G3 per-commit attribution** (L4-SEC-004 "changed by a human on the unit branch, they are allowed but the PR body
    MUST list them"; sandbox-security 2.10).
    * For each protected path in `diff base..head`, the commits in `base..head` that touch it (`git log` default
      history simplification) decide.
    * Only non-harness commits: the path is listed as information (path, commit sha10, author).
    * Any harness commit: a blocker as today. A path both sides touched stays a blocker (conservative).
    * Extensions (lines 20, 21), because G1's round must be able to pass on a human's commit:
      * `check_tests` replays the commits that touch a test file and keeps as blockers only the skip markers and
        deletions that harness commits introduced;
      * the scope check marks a file that only human commits changed `exempt: changed by human commit <sha10>`, so it
        raises no hold.
    * The MR body is static in M1, so the listing lives in `verification.md`, which the body links, and in the step-1
      note.
13. **P2.**
    * A deterministic block `Project test conventions` (`l4/verifier/conventions.py`), read at the **base**: in
      `conftest.py` files (root and under the test globs, ≤ 5 files), module-level lines that define skip helpers
      (`pytest.mark.skipif(`, `pytest.importorskip(`, a name bound to `pytest.mark.<x>`), plus the `markers` of
      pyproject, `pytest.ini` or `.pytest.ini`.
    * At most 40 lines and 3,000 characters, as `path:line: text`. It is empty when the project defines none.
    * Without the block a rubric line cannot fire, because the judge sees only the diff.
    * Rubric line, generic: "When the prompt lists the project's test conventions for optional dependencies, a new
      test that needs such a dependency must use them; one that would error where the dependency is missing is a
      major finding." `PROMPT_VERSION` 3 → 4.
14. **P3.** The audit rules gain three lines:
    * never re-import the module under test (`importlib.reload`, `del sys.modules[...]`, `sys.modules.pop`); import it
      once at the top;
    * fail by assertion on the values the criterion names, not by a raw exception;
    * follow the header of the existing test file shown, below the harness's marker line.

    Two data blocks are added:
    * the header (up to the first `def test_` or `class Test`, ≤ 40 lines) of one **base** test file that the unit did
      not change, preferring the same directory as the audit path. L4-VER-002a forbids only the unit's tests;
    * the conventions block of decision 13.

    Enforcement and versioning:
    * `_check` rejects an audit reply whose AST calls `importlib.reload` or `importlib.invalidate_caches`, or mutates
      `sys.modules` (`del`, `.pop`, item assignment);
    * `run_audit` retries an `invalid` reply once with the reason;
    * `TEMPLATE = testwriter@2`;
    * the lock pins `testwriter/audit` and `testwriter/e2e` (system text plus the kind's rules).
15. **P4.** `register_l4_marker(repo)` returns an edit or a refusal with a snippet. It never fails `init` or `upgrade`.
    Marker text: `l4(*ids): the acceptance criteria (C-xxxxxxxx) this test checks` (the plugin's text). The order:
    * any existing `markers` entry starting with `l4(` or `l4:` means it is already there: no write;
    * `pytest.ini` or `.pytest.ini` present (pytest reads them before pyproject): go to the conftest route;
    * pyproject has `[tool.pytest.ini_options]`:
      * with `markers` (an array, single- or multi-line): append the entry in the file's own style (indent, quotes,
        trailing comma);
      * without `markers`: one `markers = [...]` line under the header;
      * then re-parse with `tomllib` and require exactly the original document plus the one entry, else refuse;
      * an inline or dotted-key table form refuses;
    * conftest route, root `conftest.py`:
      * absent: create it with a `pytest_configure`;
      * present without `pytest_configure` (AST): append the function;
      * present with one: refuse and print the snippet.

    `upgrade` (the docstring today says "project files are never touched") adds the marker too and says so. It runs
    only when `gates.test.command` contains `pytest`.
16. **P5: `observability.redact_forge_urls: bool = True` in the schema.** Set in the schema, not written by `init`.
    Reasons:
    * committed history cannot be taken back, so privacy is the safe default;
    * the harness needs no host from a committed record: links are rebuilt from the run's environment;
    * `render_config` lives in `init.py`, which M1.8 is editing;
    * the two repositories adopted so far are the owner's own, and sample-consumer's repo-privacy spec asks for it.

    Behaviour:
    * Hosts come from `CI_SERVER_URL`, `CI_API_V4_URL`, `GITHUB_SERVER_URL`, `GITHUB_API_URL`,
      `forge.gitlab.api_url` and the `origin` URL (`parse_remote_url`).
    * `scheme://host[:port]` of these hosts becomes `<forge>`, so `<forge>/group/project/-/merge_requests/1` is the
      committed form.
    * It applies to the ledger **file** (branch and lock-ref copies), `verification.md`, `verdict.json` and
      `evidence.json`.
    * The JSONL mirror in `.l4-out/logs` and the console observers keep full URLs.
    * `outcome.json` and `l4 status` expand `<forge>` back to the web base when it is known.
    * The URL comparisons in `_ensure_mr` and `_own_mr` compare canonical forms, so both old full and new placeholder
      ledgers match. Past commits are not rewritten.
17. **P6.**
    * `run.started.iteration` = the folded count + 1, the iteration of this run, equal to its trailers.
    * `test-presatisfied` and `test-zero` lines read `gate test-presatisfied fail (expected: zero values must fail)
      (exit …)`.
    * A zeroed run that **passes** keeps the plain line, because that is the notable case.

## Build lines

Line format: `n. ids — what · test (write it first, see it fail) · code · verify`. New modules first; the M1.8-shared
files (`orchestrator.py`, `archive.py`, `ladder.py`, `init/init.py`, `config/schema.py`) change by small seams only.
Merge `main` before stage C if M1.8 has landed.

**Stage A — authorship, H, the hand-off (G1, G2 foundations)**
1. L4-ARC-008 (d) — `l4/vcs/authorship.py`:
   * `commit_records(git, *args)` and `is_harness(record)`, moved from `provenance` (which now imports them, no
     behaviour change);
   * `HANDOFF_SUBJECT`;
   * `handoff_commit(git, head, name, scan=500) -> str | None`.

   Test: `tests/unit/vcs/test_authorship.py::test_harness_commit_needs_bot_identity_and_l4_run` (bot without trailer,
   trailer without bot: both foreign), `::test_handoff_is_the_newest_first_parent_harness_commit_with_the_subject`.
   Code: `src/l4/vcs/authorship.py`, `src/l4/verifier/provenance.py`, `src/l4/archive.py` (import only). Verify:
   `uv run pytest tests/unit/vcs/test_authorship.py tests/unit/verifier/test_fixunit.py tests/unit/verifier/test_integrity.py -q`.
2. forge-and-ci 2.41, SPEC 12.0 — `after_handoff(git, head, name, unit_rel) -> AfterHandoff(handoff, foreign, spec_edit,
   lost)` (decisions 2 and 4), pure over git.
   Tests in `tests/unit/state/test_review.py`:
   * `::test_foreign_commits_after_h_are_listed_harness_ones_are_not`;
   * `::test_a_bot_named_commit_without_l4_run_is_foreign`;
   * `::test_unit_folder_edit_is_a_spec_edit_but_verification_md_and_l4_are_not`;
   * `::test_a_human_merge_of_the_base_after_h_is_foreign`;
   * `::test_h_missing_from_the_branch_is_lost`.

   Code: `src/l4/state/review.py`. Verify: `uv run pytest tests/unit/state/test_review.py -q`.
3. L4-ARC-008 (a) — H is made unless HEAD is this unit's H; `pr.ready{head}` (decision 7).
   Tests: `tests/unit/archive/test_handoff_reentry.py::test_a_second_pass_after_reentry_makes_a_new_handoff_commit`
   (H2 exists, is the MR head, has no `[skip ci]`), plus the existing
   `test_handoff_failure.py::test_failed_mr_update_after_h_leaves_the_branch_at_h` unchanged. Code: `src/l4/archive.py`
   (`handoff_hook`). Verify: `uv run pytest tests/unit/archive -q`.

**Stage B — lifecycle, fold, snapshot, planner**

4. SPEC 12.0 rows — three edges, no exit code: `in_review` on `commit_after_handoff` → `verifying`, on
   `spec_edit_after_handoff` → `implementing`, on `repository_ci_failed` → `verifying`. Lifecycle docstring updated.
   Test: `tests/unit/state/test_lifecycle.py::test_table_matches_spec_rows` (`BUILT_ROWS` gains the three rows; the
   assertion also checks that `archived` is no source). Code: `src/l4/state/lifecycle.py`. Verify:
   `uv run pytest tests/unit/state/test_lifecycle.py -q`.
5. L4-STA-001, L4-ARC-002 (d) — the fold reads `ci.failed` and `ci.preexisting` into `ci_heads` and `ci_failure`
   (decision 9) · `tests/unit/state/test_fold.py::test_ci_results_are_folded_per_head` · `src/l4/state/fold.py` ·
   `uv run pytest tests/unit/state -q`
6. SPEC 2.1 `l4 plan`, 12.0 — `UnitSnapshot.review` (computed only for an `in_review` unit read from its branch) and
   new `UnitFacts` fields: `after_handoff`, `spec_edit_after_handoff`, `handoff_lost`, `ci_failed_jobs` (only when
   `ci_failure.head` == H == the branch head).
   `next_action` rows (decision 3):
   * `implement`: `in_review: answers or spec edits after the hand-off (<sha10>)`;
   * `verify`: `in_review: commit(s) after the hand-off not made by the harness: <sha10>[, …]`;
   * `verify`: `in_review: repository CI failed on <H10>: <jobs>`;
   * else `none`, as today.

   Tests in `tests/unit/planner/test_review_rows.py`:
   * `::test_a_human_commit_plans_verify`, `::test_a_spec_edit_plans_implement`;
   * `::test_ci_failed_on_h_plans_verify`, `::test_ci_failed_on_an_older_head_is_ignored`;
   * `::test_only_harness_commits_after_h_still_wait` (also the `l4 run` selection: `ACTIONABLE`).

   Code: `src/l4/state/status.py`, `src/l4/planner.py`. Verify: `uv run pytest tests/unit/planner tests/unit/state -q`.

**Stage C — the orchestrator's review re-entry (G1, the G2 edge)**

7. SPEC 12.0, L4-ARC-004 (M1 form) — `_drive` handles `IN_REVIEW` with `review_trigger(after_handoff(HEAD), state)`
   (a pure function in `state/review.py`) and takes the edge of decision 3; `ARCHIVED` and `MERGED` stay in
   `_NOTHING_TO_DO`. The worktree's HEAD is the remote branch head [V `WorktreeManager.ensure`].
   Test: `tests/unit/orchestrator/test_review_reentry.py::test_human_code_commit_after_handoff_reverifies_and_hands_off_again`
   (SCN-ARC-16, `post_merge_pr` form). The test drives `run_l4` to `in_review`, then a human commit on `origin`
   touching `src/`, then a second run, and expects:
   * `phase in_review → verifying (commit_after_handoff)`;
   * a new round whose subject is the human commit;
   * PASS, then H2 as MR head with the human commit in its history.

   Code: `src/l4/orchestrator.py` (one branch in `_drive`), `src/l4/state/review.py`. Verify:
   `uv run pytest tests/unit/orchestrator/test_review_reentry.py -q`.
8. Same file, spec route and evidence:
   * `::test_spec_edit_after_handoff_goes_to_implementing` (an added task is implemented, then verify and H2);
   * `::test_ci_failure_on_h_runs_a_round_that_fails_at_step_0_and_spawns_a_fix_unit` (SCN-ARC-14 end to end: a
     sweep against a FakeGitLab red pipeline, then `l4 run`; the round FAILs at step 0 with
     `repository CI failed: test`, the judge is not called, and a `[chore]` fix task names the job and carries the
     tail. After the fix, a full round, PASS and H2; a green sweep on H2 writes nothing).

   Code: whatever lines 7, 13 and 16 missed. Verify: as line 7.
9. L4-ARC-008 (c) — the mirror goes to draft before the first push, with labels and the sticky section (decision 6).
   Tests:
   * `test_review_reentry.py::test_reentry_sets_the_mr_back_to_draft_before_any_push` (ordered log of FakeGitLab
     PUTs and pushes, with the draft PUT first);
   * `::test_sticky_note_names_the_foreign_commits_or_the_red_jobs`.

   Code: `src/l4/archive.py` (`_Mirror.sync`, `_Mr.draft`), `src/l4/orchestrator.py` (`_notes`). Verify:
   `uv run pytest tests/unit/orchestrator/test_review_reentry.py tests/unit/archive -q`.
10. Loop safety (decision 11) — `test_review_reentry.py::test_the_harness_never_retriggers_itself`:
    * after H2, a third run says `nothing to do`, with no commit, push, MR write or lock-ref commit;
    * a bot commit with `L4-Run` after H: still nothing;
    * an `l4-bot`-named commit without `L4-Run`: re-verifies;
    * a fix round that cannot fix ends in `escalated` after `max_fix_rounds`.

    No code expected. Verify: as line 7.
11. Trace (L4-OBS-001) — `progress.py`:
    * `phase.changed` with a review trigger prints the reason: `… (commit_after_handoff: 1 commit, <sha10> <subject>
      by <author>)`;
    * `ci.failed` → WARNING `repository CI failed on <H10>: test, lint (pipeline <id>); l4 run re-verifies`;
    * `ci.preexisting` → INFO `CI jobs red on H and on the base: <jobs> (pre-existing, no fix round)`.

    Test: `tests/unit/obs/test_progress.py::test_review_reentry_and_ci_lines`. Code: `src/l4/progress.py`. Verify:
    `uv run pytest tests/unit/obs -q`.
12. Step 0 (decision 10) — the CI blockers come from the last `phase.changed{trigger: repository_ci_failed}` that no
    `verify.verdict` follows. The round is not reused: its subject is unchanged since H, but `evidence.reusable` reuses
    only after a NEEDS_HUMAN round [V], and the previous round was a PASS.
    Tests:
    * `tests/unit/verifier/test_preconditions.py::test_ci_failure_of_the_reentry_is_a_step_0_blocker_once` (a round
      after the verdict has none);
    * `tests/unit/verifier/test_fixunit.py::test_a_repository_ci_blocker_becomes_a_chore_task_with_the_tail`.

    Code: `src/l4/verifier/preconditions.py`. Verify: `uv run pytest tests/unit/verifier/test_preconditions.py tests/unit/verifier/test_fixunit.py -q`.

**Stage D — repository CI on H (G2)**

13. forge-and-ci 1.1, 2.2 — the forge port: `JobResult(name, stage, status, allow_failure, pipeline_id, job_id,
    web_url)`, `list_pipeline_jobs(sha)` (decision 8 merge rule) and `job_log_tail(job_id, max_lines)`. GitLab:
    `pipelines?sha=`, `pipelines/:id/jobs` (retried attempts excluded), `jobs/:id/trace`; FakeGitLab routes. Tests in
    `tests/unit/forge/test_gitlab_pipelines.py`:
    * `::test_jobs_listed_for_sha_across_pipelines`;
    * `::test_newest_pipeline_wins_per_job_name`;
    * `::test_job_log_tail_is_capped_and_ansi_stripped`.

    Code: `src/l4/forge/base.py`, `src/l4/forge/gitlab.py`, `tests/unit/forge/conftest.py`. Verify:
    `uv run pytest tests/unit/forge -q`.
14. forge-and-ci 2.9 (check-run part) — GitHub:
    * check runs of sha H (an own reader for `{"check_runs": …}` [I shape], paged by `Link`) become `JobResult`
      (`status`/`conclusion` mapped per decision 8);
    * the log tail follows the `actions/jobs/:id/logs` redirect without the token [U: redirect host and body form];
    * `LocalForge` serves scripted jobs.

    Tests: `tests/unit/forge/test_github_checks.py::test_check_runs_of_sha_become_job_results`,
    `::test_log_redirect_is_followed_without_the_token`, and
    `tests/unit/forge/test_local_forge.py::test_pipeline_jobs_are_scripted`. Code: `src/l4/forge/github.py`,
    `src/l4/forge/local.py`, `tests/unit/forge/_github_helpers.py`. Verify: as line 13.
15. forge-and-ci 2.44, L4-ARC-002 (d) — `evaluate_ci(head_jobs, base_jobs, ignore=("l4",)) -> CiVerdict(status:
    running|green|failed|preexisting, failed, preexisting)` (decision 8). Tests in `tests/unit/archive/test_repo_ci.py`:
    * `::test_preexisting_red_job_is_not_a_finding` (SCN-ARC-19), `::test_new_red_job_returns_to_verifying`
      (SCN-ARC-14);
    * `::test_a_running_pipeline_is_not_a_failure`, `::test_the_l4_job_itself_is_ignored`;
    * `::test_allow_failure_manual_and_canceled_jobs_are_not_red`;
    * `::test_a_job_absent_on_the_base_counts`, `::test_a_running_base_pipeline_defers`.

    Code: `src/l4/ci/repo_ci.py` (a new module, not `archive.py` as the task line says, because M1.8 edits that file).
    Verify: `uv run pytest tests/unit/archive/test_repo_ci.py -q`.
16. The sweep duty — for an `in_review` unit with an open MR whose branch head is H and whose H is not in `ci_heads`:
    `list_pipeline_jobs(H)`, then on red the base head's jobs, then `ci.failed` with tails or `ci.preexisting`, under
    the unit's lease and published to the lock ref. One `list_prs(prefix, "open")` per sweep. A forge read error is
    logged and the unit retried next time, as for the merge duty. Tests in `tests/unit/ci/test_sweeper.py`:
    * `::test_red_project_job_on_h_is_recorded_once_per_h` (the second sweep makes no write and no lock-ref commit);
    * `::test_green_or_running_pipeline_writes_nothing`;
    * `::test_a_branch_past_h_is_left_to_the_run`;
    * `::test_preexisting_red_is_recorded_without_a_failure`.

    Code: `src/l4/ci/sweeper.py`. Verify: `uv run pytest tests/unit/ci -q`.
17. Redaction of the evidence — the tails go through `app.redactor` before the event and are clipped. A token-shaped
    string in a job log never reaches the ledger · `tests/unit/ci/test_sweeper.py::test_a_secret_in_a_job_log_is_redacted`
    · same · same
18. CLI surface — `l4 plan --sweep` prints the CI decision per unit (`ci: H <sha10> red: test (recorded)` / `running` /
    `green`), and `l4 archive --unit` is unaffected · `tests/unit/ci/test_sweep_cli.py::test_plan_sweep_reports_the_ci_decision`
    · `src/l4/ci/sweeper.py` (`SweepAction` kinds `ci_failed|ci_preexisting|ci_waiting`), `src/l4/planner.py` ·
    `uv run pytest tests/unit/ci tests/unit/planner -q`

**Stage E — per-commit attribution (G3)**

19. sandbox-security 2.10, L4-SEC-004 — `protected_changes_by_human(git, base, head, paths) -> list[HumanChange(path,
    commits)]`, and `check_protected` lists those paths in `Outcome.human` (not findings) while every other hit stays a
    blocker.
    * `IntegrityReport.human_protected` gets a `verification.md` section "Protected paths changed by humans (allowed,
      L4-SEC-004)" and the step-1 note `(+n changed by humans, listed)`.
    * `_integrity_helpers.Repo.commit` commits as the bot (it already writes `L4-Run`), and a new `commit_as_human`
      serves the tests that mean a human.

    Tests:
    * `tests/unit/security/test_protected.py::test_human_ci_edit_is_listed_not_reverted`;
    * `tests/unit/verifier/test_integrity.py::test_human_commit_changing_gitlab_ci_on_the_unit_branch_is_listed_not_a_finding`;
    * `::test_a_path_a_harness_commit_also_touched_stays_a_blocker`;
    * the whole integrity suite, unchanged in meaning.

    Code: `src/l4/security/protected.py`, `src/l4/verifier/integrity.py`, `src/l4/verifier/types.py`,
    `src/l4/verifier/report.py`, `tests/unit/verifier/_integrity_helpers.py`. Verify:
    `uv run pytest tests/unit/security tests/unit/verifier/test_integrity.py tests/unit/verifier/test_integrity_c22.py tests/unit/verifier/test_integrity_generated.py tests/unit/verifier/test_integrity_harness_plugins.py tests/unit/verifier/test_report.py -q`.
20. G3 extension — `check_tests` replays the commits touching each test file. Skip markers and test deletions that only
    human commits introduced are listed, not blockers · `test_integrity.py::test_a_skip_marker_a_human_added_after_handoff_is_listed_not_a_blocker`,
    `::test_a_skip_the_harness_added_is_still_a_blocker` · `src/l4/verifier/integrity.py` · as line 19
21. G3 extension — scope: a file changed only by human commits is `exempt` (`changed by human commit <sha10>`), so no
    hold · `tests/unit/evidence/test_scope.py::test_a_file_only_a_human_changed_raises_no_hold` · `src/l4/evidence/scope.py`,
    `src/l4/evidence/collect.py` · `uv run pytest tests/unit/evidence -q`

**Stage F — prompts (P2, P3)**

22. P2/P3 shared — `test_conventions(git, base_sha, cfg) -> str` and `base_test_header(git, base_sha, changed,
    near)` (decisions 13, 14). Tests in `tests/unit/verifier/test_conventions.py`:
    * `::test_skip_helpers_and_markers_are_listed`;
    * `::test_a_project_without_helpers_gives_nothing`;
    * `::test_only_the_base_is_read`;
    * `::test_the_header_comes_from_a_base_file_the_unit_did_not_change`.

    Code: `src/l4/verifier/conventions.py`. Verify: `uv run pytest tests/unit/verifier/test_conventions.py -q`.
23. P2, L4-VER-005 — the judge rubric line and a `## Project test conventions` block when non-empty;
    `PROMPT_VERSION = 4`; `uv run python -m l4.templatelock --write`. Tests:
    * `tests/unit/verifier/test_prompt.py::test_conventions_block_and_rubric_line` (the block is absent when empty, the
      line always present);
    * `tests/unit/test_template_lock.py`.

    Code: `src/l4/verifier/judge.py`, `src/l4/verifier/ladder.py` (one keyword argument), `src/l4/templates.lock.json`.
    Verify: `uv run pytest tests/unit/verifier/test_prompt.py tests/unit/verifier/test_judge_step.py tests/unit/test_template_lock.py -q`.
24. P3, L4-VER-002a — the audit rules, the header and conventions blocks, the AST rejection, one retry on `invalid`,
    and `testwriter@2`. `templatelock.current` pins `testwriter/audit` and `testwriter/e2e`; `CASES` gains both; the
    lock is regenerated. Tests:
    * `tests/unit/verifier/test_testwriter.py::test_audit_rules_and_header_block`;
    * `::test_reload_or_sys_modules_mutation_is_rejected_with_a_reason`;
    * `tests/unit/verifier/test_audit.py::test_an_invalid_reply_is_retried_once_with_the_reason`;
    * `tests/unit/test_template_lock.py`.

    Code: `src/l4/verifier/testwriter.py`, `src/l4/verifier/audit.py`, `src/l4/templatelock.py`,
    `src/l4/templates.lock.json`. Verify: `uv run pytest tests/unit/verifier/test_testwriter.py tests/unit/verifier/test_audit.py tests/unit/test_template_lock.py -q`.

**Stage G — adoption and trace (P4, P5, P6)**

25. P4, L4-INS-002 — `register_l4_marker(repo) -> MarkerEdit | MarkerRefusal` (decision 15). Tests in
    `tests/unit/init/test_pytest_marker.py`:
    * `::test_appended_to_a_multiline_markers_array_byte_minimal`, `::test_appended_to_a_one_line_array`;
    * `::test_table_without_markers_gets_one_line`, `::test_no_pytest_table_writes_conftest`;
    * `::test_pytest_ini_present_uses_conftest`;
    * `::test_existing_pytest_configure_is_refused_with_the_snippet`;
    * `::test_second_run_writes_nothing`;
    * `::test_reparse_mismatch_refuses`;
    * `::test_strict_markers_collects_an_l4_test` (a real `pytest --strict-markers --collect-only` in a tmp repo).

    Code: `src/l4/init/pytest_marker.py`. Verify: `uv run pytest tests/unit/init/test_pytest_marker.py -q`.
26. P4 wiring — `plan_init` and `plan_upgrade` carry the edit (one field each). `upgrade` prints `registered the l4
    pytest marker in <file>`, or the snippet, and its docstring is amended. Tests:
    * `tests/unit/init/test_init_cli.py::test_init_registers_the_l4_marker`;
    * `tests/unit/init/test_upgrade.py::test_upgrade_registers_the_marker_once_and_reports_it`.

    Code: `src/l4/init/init.py`, `src/l4/init/upgrade.py`. Verify: `uv run pytest tests/unit/init -q`.
27. P5, L4-OBS-002 — `ForgeUrls(hosts, web_base)`: `scrub`, `expand`, `canonical`; `forge_urls(cfg, environ,
    origin_url)`; `observability.redact_forge_urls: bool = True`. Tests:
    * `tests/unit/forge/test_urls.py::test_forge_hosts_become_the_placeholder_and_others_stay`;
    * `::test_expand_restores_the_web_base`;
    * `::test_canonical_matches_old_and_new_forms`;
    * `tests/unit/config/test_schema.py::test_redact_forge_urls_defaults_on`.

    Code: `src/l4/forge/urls.py`, `src/l4/config/schema.py`. Verify: `uv run pytest tests/unit/forge/test_urls.py tests/unit/config -q`.
28. P5 — `LedgerWriter.open(..., file_filter=)`: the file and the tamper copy get the filtered payload, while the JSONL
    mirror and the observers get the full one · `tests/unit/state/test_ledger.py::test_file_filter_applies_to_the_file_only`
    · `src/l4/state/ledger.py` · `uv run pytest tests/unit/state tests/unit/obs -q`
29. P5 wiring — `run_unit_in_worktree`'s writer, the sweeper's `_UnitRun`, `write_round_evidence`, the canonical
    comparisons in `_ensure_mr` and `_own_mr`, and expansion in `outcome.json` (`orchestrator._outcome`, `planner._outcome`) and `l4 status` (the only readers of `state.pr`
    besides `_own_mr` [V grep]). Tests in
    `tests/unit/archive/test_forge_urls.py`:
    * `::test_committed_ledgers_hold_the_placeholder_and_the_trace_keeps_the_link` (branch and lock-ref files hold
      `<forge>/`; the console line, `.l4-out/logs` and `outcome.json` hold the full URL);
    * `::test_a_rerun_writes_no_second_pr_updated`;
    * `::test_the_sweeper_matches_a_placeholder_url_to_the_merged_mr`;
    * `::test_off_keeps_full_urls`.

    The assertion `event["url"] == mr_url(...)` in
    `test_hooks.py::test_hooks_mirror_after_phase_change_and_handoff_marks_ready` changes to the placeholder form.
    Code: `src/l4/orchestrator.py`, `src/l4/ci/sweeper.py`, `src/l4/verifier/report.py`, `src/l4/archive.py`,
    `src/l4/state/status.py`. Verify: `uv run pytest tests/unit/archive tests/unit/ci tests/unit/verifier/test_report.py -q`.
30. P6 — `run.started.iteration` = folded count + 1 ·
    `tests/unit/archive/test_progress_trace.py::test_a_resumed_run_prints_the_iteration_of_its_trailers` (a unit with
    one earlier run: trace `iteration 2` = `L4-Iteration: 2`) · `src/l4/orchestrator.py` (`open_writer`) ·
    `uv run pytest tests/unit/archive/test_progress_trace.py tests/unit/orchestrator -q`
31. P6 — zeroed-run gate lines say they are expected to fail (decision 17) ·
    `tests/unit/obs/test_progress.py::test_zeroed_runs_say_they_are_expected_to_fail` · `src/l4/progress.py` ·
    `uv run pytest tests/unit/obs -q`

**Stage H — close-out**

32. Close-out:
    * `uv run pytest -q` in the tool's background mode, then `uv run ruff check .` and `uv run ruff format --check .`;
    * `uv run python -m l4.templatelock --write` leaves no diff;
    * SPEC edits, small and local (M1.8 edits SPEC too):
      * 12.0: a note on the M1 form of the review rows (sources `in_review` only, approval half N/A);
      * 12.1: events `ci.failed`, `ci.preexisting`, `pr.ready{head}`;
      * 3.2: `observability.redact_forge_urls: true`;
      * L4-OBS-002: one sentence on the placeholder;
      * L4-ARC-002: no base pipeline means the job counts;
      * L4-SEC-004: per-commit attribution;
    * openspec ticks: forge-and-ci 2.2, 2.41 (note: approval half N/A in `post_merge_pr`), 2.44; sandbox-security
      2.10. Each ticked line's `test:`/`code:` pointers are rewritten to the files that exist (`test_review_reentry.py`,
      `ci/repo_ci.py`, ...). 2.9 stays open (only its check-run part is built);
    * write `docs/plan/m19-progress.md`.

## Live protocol on `example-group/dummy-agentic` (runner `l4-runner`)

The operator acts as human and maintainer. Save every job log (ANSI stripped) under `docs/live/m19/`. If the `*/30`
schedule of M1.8 exists on the dummy, pause it during steps 2–5, or expect its sweep to take the step first. One new unit:
**C `add-cart-total-items`**, modelled on `add-is-empty` (one task, two scenarios, no open question).

| Step | Action | Expected (job log, ledger, GitLab API) |
|---|---|---|
| 0 | `uv run pytest -q` at the M1.9 head | suite green |
| 1 | push to `main`: `l4 upgrade` to M1.9, two project jobs and the seed of C. `always-red: script: exit 1` (red on main and on every H). `fail-on-handoff`, rule `$CI_COMMIT_TITLE =~ /hand off to review$/`, script `'[ "$CI_COMMIT_SHA" != "$FAIL_SHA" ]'` (green while the project variable `FAIL_SHA` is unset) | `upgrade` prints `registered the l4 pytest marker in pyproject.toml` (or the conftest form) [U: the dummy's pytest config]. C runs red → green → PASS, H pushed, MR ready. Trace `run … started (iteration 1, …)` = `L4-Iteration: 1`; `gate test-presatisfied fail (expected: …)` if C has a pre-satisfied criterion |
| 1 checks | branch ledger, lock ref | `pr.updated`/`pr.ready` hold `<forge>/example-group/dummy-agentic/-/merge_requests/<n>`, the job log line shows the full URL, `pr.ready.head` = H |
| 2 (G2) | set `FAIL_SHA` = H, retry H's `fail-on-handoff` job (red), then run a pipeline on `main` (web) | sweep: `repository CI failed on <H10>: fail-on-handoff (pipeline <id>)`, `always-red` pre-existing; pending ledger `ci.failed{jobs: [fail-on-handoff], preexisting: [always-red]}`. `l4 run`: `phase in_review → verifying (repository_ci_failed)`, MR draft and `l4:verifying`, step 0 FAIL `repository CI failed: fail-on-handoff`, no judge call, a fix unit with one `[chore]` task; the fix loop goes on in the same run (M1.3 D2) |
| 3 | none (same job) | the chore task runs [U: what Codex does with a task it cannot fix in code; an empty change may halt it]; round n+1 is a full ladder, PASS, H2 (a new commit, no `[skip ci]`), MR ready. H2's pipeline: `fail-on-handoff` green (another sha), `always-red` red. A web pipeline on `main`: `ci.preexisting` once, the unit stays `in_review`; a second one writes nothing |
| 4 (G1 + G3) | a human commit on C's branch: a comment line in `.gitlab-ci.yml` and a docstring in a module C's spec does not name (`src/pricing/<other>.py` [U: which exists]) (no `L4-Run`) | the push starts the `l4` job: `phase in_review → verifying (commit_after_handoff: 1 commit, <sha10> …)`, MR draft. The round's step 1 note lists `.gitlab-ci.yml` (human, listed), with no protected-path blocker and no scope hold for the other module. Then PASS, H3 with the human commit in its history, MR ready |
| 5 (loop safety) | a web pipeline on `main`, then another | both: `in_review: waiting for merge`, `nothing to do`, no push to the branch. The first records `ci.preexisting` for H3 (`always-red`, one lock-ref commit); the second writes nothing (`git ls-remote` unchanged) |
| cleanup | delete the two project jobs and `FAIL_SHA`; leave C's MR for the maintainer | `nothing to do` |

Spend: Codex 2 agent steps (C) plus 1 chore attempt. Claude: 3 judge calls (C, round n+1, round after step 4), about
$0.55 [I, M1.3 rates]. The clarifier is not involved.

## Risks

* **The CI fact and the run are two steps.** If `l4 run` fails after the sweep recorded `ci.failed`, the next pipeline
  takes the edge: `plan` says `verify`, so nothing is lost.
* **A fix round that cannot fix.** Some red jobs cannot be fixed in code (infrastructure, a forbidden CI file, a
  flaky job), and each new H then burns one fix round until `escalated`. This is bounded and visible on the MR.
  A human can add the job name to a future ignore list (not built: M2).
* **The judge on a human change.** The judge still sees the human's diff and may raise findings about it. Integrity,
  tests and scope are attributed (lines 19–21); the judge is not.
* **Authorship is trusted.** It is safe because agents cannot commit, `.git` being read-only in the agent sandbox. With
  `sandbox.mode: none` an agent could commit as a "human" and turn its forbidden-path change into a listed one. There
  is no agent-commit guard yet (sandbox-security 1.16).
* **A closed MR plus a human commit** re-verifies and opens a new MR (`find_pr` reads open MRs only), because
  `abandoned` (L4-ARC-005) is not built.
* **GitHub log redirect** [U], line 14. If the redirect cannot be followed safely, GitHub check runs carry no tail;
  the finding still names the job and its URL.
* **P5 changes the committed form for existing adopters.** Old full URLs stay in history, and the comparisons accept
  both forms (line 29).
* **Iteration count.** Each recorded CI result is a sweep run with a `run.started`, so the fold's iteration (and the
  next run's trace and trailers, line 30) goes up by one, as it already does for `PR_MERGED`. Not a P6 regression.
* **P4 edits a project file.** It refuses rather than guess, and the re-parse check makes a wrong edit impossible to
  write.

## Overlap with M1.8 (`../l4-wt/m18`)

M1.8 touches `orchestrator.py` (`capacity_section`, `_park`), `archive.py` (`proposal_title`), `ladder.py`,
`init/init.py`, `config/schema.py`, the GitLab template, `test_run_unit.py` and `test_ladder.py`. M1.9 keeps logic in
new modules: `vcs/authorship.py`, `state/review.py`, `ci/repo_ci.py`, `forge/urls.py`, `verifier/conventions.py`,
`init/pytest_marker.py`. It writes new test files instead of extending M1.8's, and makes no template change (G2 relies
on M1.8's schedule). The shared files change only at these seams:
* `_drive`'s `IN_REVIEW` branch;
* `open_writer`'s iteration and file filter;
* `handoff_hook` and `_Mirror.sync`;
* one keyword argument in `ladder._judge_step`;
* one field each in `plan_init` and `plan_upgrade`;
* one schema field.
