# M1.12 — the sample-consumer wave B findings and the MF-7 reject finding (planned 2026-10-07)

## Goal

Wave B of sample-consumer (MF-2, MF-6, MF-3 merged; harness `main` at `287b361`) left four harness findings, K1–K4
(`docs/adoption/sample-consumer/wave-b.md`, kept outside this repository). The MF-7 live resume left two more,
F1 and F2. M1.12 closes them. **29 build lines**, test first: each new test is seen failing for the stated reason
before the code is written.

| Finding | Lines | Finding | Lines |
|---|---|---|---|
| K1 a failed non-limit hello is cached 15 min and skipped silently | 1–7 | K4 a designed stop (11) shows as a failed CI job | 17–22 |
| K2 round-own audit tests never linted, never listed for the judge | 8–14 | F1 (MF-7) reject text lost, buggy behaviour locked in | 23–26 |
| K3 Codex implementer cannot open loopback sockets | 15–16 | F2 (MF-7) frozen red test contradicts the spec | 27–29 |

Labels: [V] read in code or evidence at `287b361`; [I] inferred; [U] not checked (a build line settles it first).

## Facts this plan rests on

* **K1** [V]. `fallback.py` `_remember` caches a failed `hello` when it carries no `LimitSignal`, for
  `availability.cache_ttl` (15m, `config/schema.py`), per L4-AVL-005. `_probe` then reuses the failed report, adds a
  `Skipped(step="hello")` and prints `format_skipped_line`, which has no word for a cached result (`format_selected_line`
  does: `_ok_text(..., cached)`). `Skipped` has no `cached` field; `Selection.cached` and `ProfileProbe.cached` exist.
  * The claude hello failure is `claude reported an error (api_error_status N)` [V `probes.py`]; only a `rejected`
    status or HTTP 429 becomes a limit. A 403 (the org refusal that parked MF-3) is a plain failure, so it is cached
    like a model that answered wrongly. [I] that the live 403 took this path; the wave-b ledgers under `live/` hold the
    text, a build line checks it.
  * A failure of a free step (binary, auth, quota) is never cached, so installing or logging in takes effect at once.
* **K2** [V]. In `ladder.verify_hook`, step 2 (gates incl. `lint`) runs before step 4a (`_audit_step`). The audit
  writer's tests are written in 4a, so no lint ever sees them in that round; they are committed after the judge
  answered (`commit_verifier_tests`, ladder ~1163), and `_round_outputs` hands the judge only the `accepted` ones.
  [I] The judge's "audit test missing from the per-test list" comes from the per-test list being built from the trace
  before `_with_audit` adds the audit tests, or from the audit test not being in `result.trace` yet; a line reproduces it.
  `run_audit` already runs "the audit gate run" on the written test [V `_round_outputs` docstring]; whether that run
  includes `gates.lint` is [U] and line 8 settles it.
* **K3** [V/U]. `codex.py` `build_command` passes `-s workspace-write` for `implement`. `codex` is not installed on this
  machine, so the 0.160 config keys are [U]. From memory [I, unverified]: `workspace-write` takes
  `-c sandbox_workspace_write.network_access=true`, which is all outbound, not loopback only. The harness's own gate
  sandbox (`l4.sandbox`, bwrap `--unshare-net`) is a second layer and already runs loopback tests [per wave-b].
* **K4** [V]. `exitcodes.map_exit` already gives 10/11/12/13 an annotation, and `l4.gitlab-ci.yml` already lists
  `exit_codes: [10, 11, 12, 13]` (11 since the first template commit `96a0dcb`; 13 added by M1.11 line 15). Yet job
  5755 (MF-2) ended `ERROR: Job failed: exit status 11`, and wave-b says it shows as a failed job. So the code list is
  not the whole story: **the cause is [U]** and line 17 finds it before anything is changed. Candidates: the adopted
  project's `.l4/ci/l4.gitlab-ci.yml` is older than the template (not re-rendered by `l4 upgrade`); GitLab shows the
  runner's `ERROR:` line and a "failed (allowed)" badge that wave-b read as a failure; the pipeline of the push is not
  the one that was read. `l4 ci watch` already prints `failed (allowed)` for an allowed failure [V `ci/watch.py`].
* **F1** [V]. `fixunit._candidates` records each reject as `Q-NNN: <reason>`, and `_decided` prefixes the task detail
  with `Decided by human in Q-NNN: <reason>.` (live-fix `a1a0ca3`). The finding that is a rejected *coverage hold*
  (`is_coverage_hold_finding`) becomes a test chore (`Finding.tests=True`, `FixMarker`), whose prompt is
  `single_tests.md`. That template says "add tests that run that code and check what it does" and gives the implementer
  no sentence about the owner's reason. The MF-7 reject said the code was wrong; the chore's brief was to add tests that
  run it, so it wrote tests that pinned the bug. [I] that the reject text did not reach the task for this case (the
  hold may have had `decisions` empty because the reject targeted the criterion, not the finding); line 23 reproduces it
  from the MF-7 ledger shape before changing anything.
* **F2** [V]. M1.10 C2 (`implementer/unfreeze.py`): a *human* `answered` or `accepted` question that blocks the task and
  names a frozen test file lets that file change in that task's next green. `green.md` already says "report status
  blocked with one question of kind technical". The question the implementer wrote for MF-7 named the test and the
  contradiction (the key `sub_areas` against `subareas`) but not the edit, so a human had to write it. `accepted`
  needs the question itself to name the file (`names_path(asked, path)`).

## Decisions

1. **K1: classify the hello failure, then cache by class.** A new `failure_class` on `ProbeResult` for hello:
   `limit` (as now, never cached), `auth` (HTTP 401/403, `authentication`/`permission` wording), `transient`
   (timeout, 5xx, no result), `other` (wrong reply). Cache TTL by class: `other` keeps `cache_ttl`; `auth` uses
   `availability.auth_failure_ttl` (default `2m`); `transient` is not cached. [I] 2 minutes because an org 403 is fixed
   by a human, and a run that needs the role (not just any run) must re-probe: so an `auth` entry is also **bypassed
   when the role has nothing else usable** (the walk reaches the end of a required chain with only cached failures:
   re-probe those once before parking, the K1 "re-probed when the role is actually needed" case).
2. **K1: say "cached".** `Skipped` gets `cached: bool` and `age_s`; `format_skipped_line` ends with
   `(cached 3m ago; l4 probe --no-cache re-probes)`; the `availability.selected`/`skipped` events carry `cached`. SPEC
   L4-AVL-005 gains the class rule and the line.
3. **K2: lint the round's own audit tests inside the audit step**, not by moving the lint gate. Moving gates after 4a
   would make a bad audit test fail step 2 and stop the ladder (L4-VER-002) over a test the verifier wrote. So: after
   `run_audit` accepts a test, run the project's `gates.lint` (and `typecheck`) on the changed test files at head with
   the same gate runner. A failure is **fixed once by the writer** (the lint output goes back to the audit writer, one
   retry, as the audit already retries a failing test) or the test is **rejected**: status `rejected` with reason
   `lint: <first line>`, it is not committed, not handed to the judge, and the criterion is held for a human as an
   audit failure already is. A lint failure is never handed off (the K2 acceptance).
4. **K2: the judge's per-test list includes the round's accepted audit tests**, built from `result.audit` at the point
   the judge prompt is rendered, labelled `audit`, so "missing from the list" cannot occur for an accepted one.
5. **K3: try the config key first, fall back to the prompt.** (a) If codex 0.160 accepts a loopback-only or
   `network_access` setting for `workspace-write`, pass it only for `implement` mode and only when the profile opts in
   (`options.loopback: true`); an all-outbound switch is **not** taken (the sandbox's no-network rule, L4-SEC-001,
   outranks convenience). (b) Otherwise the implementer prompt (`contract.md`) says what is true: sockets are blocked,
   so HTTP-level scenarios use the handler or app object in-process (call the WSGI/`BaseHTTPRequestHandler` class with
   an in-memory request, or `socketpair`), and the gate run (not the implementer step) can use loopback. Either way
   the judge's "white-box test for an HTTP scenario" finding is not raised against a limitation the prompt names.
6. **K4: one table.** `exitcodes` gets `CI_ALLOWED = (10, 11, 12, 13)` (the codes a designed stop returns); the GitLab
   template, `map_exit`, SPEC 2.2 and the tests all derive from or are checked against it. `1, 2, 3, 14` stay failures.
   If line 17 shows the live job was already "failed (allowed)", the fix is the words: the `l4` job prints one line
   "designed stop, not a failure: exit 11 (awaiting_human): <reason>" before returning the code, and `l4 upgrade`/`doctor`
   flag an adopted include whose list differs from `CI_ALLOWED`.
7. **K4: the reason is in the MR note for 10/11/12 as it is for 13.** The sticky note section for a unit with
   `exit_reason` (13 today) is written for `awaiting_human` (which questions), `waiting_capacity` (which profiles,
   `retry_after`) and `continue`. Exit 11 with no MR (a unit that has no MR yet) writes the reason to the job log only.
8. **F1: the reject text is the first thing in a fix task for every kind of finding, and the tests chore says what it
   is for.** `plan_fix_unit` keeps `Decided by <who> in <Q>: <reason>.` first for a hold task as it does for a verdict
   reject; when a coverage hold's reject has no finding-level match the criterion-level reject is used
   (`rejects.get(criterion)` already). `single_tests.md` (and `single.md`) gain: "If the task begins with a decision by
   a human, the tests you add MUST assert the behaviour that decision describes. A test that asserts what the code does
   now, when the decision says that is wrong, is rejected; if the code cannot meet the decision, add the test that
   asserts the decision (it fails) and report `blocked` with that as the reason." This forks from the current rule
   (tests may pass at once): a test chore with a decision may write a failing test; the harness must accept that
   outcome as `blocked`, not as a rejected step.
9. **F2: the question names the edit.** `green.md` and the `ambiguous`/`technical` question template ask for a `Suggested
   answer` of the form "Edit `<path>`: <exact change>"; the clarifier suggestion path writes it into
   `Clarifier suggestion`, so one `accepted` by the owner unfreezes the file (`names_path` over the answer, and the
   question text names the file too). The path is **not** changed; M1.10 C2 stays the only unfreeze route.

## Build lines (test first)

**K1: failed hello caching** (SPEC L4-AVL-005, L4-AVL-007; `availability/fallback.py`, `probes.py`, `config/schema.py`)

1. Test: a claude hello that returns `is_error` with `api_error_status 403` yields `ProbeResult.failure_class ==
   "auth"`; 429 with no limit info is `limit`; a wrong reply is `other`; timeout and 5xx are `transient`. Fails: no
   `failure_class`. Add it to `ProbeResult` and `_hello_verdict`, and the codex/opencode hello paths.
2. Test: `_remember` stores an `other` failure for `cache_ttl`, an `auth` failure for `auth_failure_ttl`, and nothing
   for `transient` (read back through `store.probes.get` with a clock moved 3m: auth gone, other still there). Fails: all
   are cached 15m.
3. Test: `availability.auth_failure_ttl` parses as a Duration, default `2m`, rejects a negative value; listed in
   `l4 config` output and SPEC 5 sample. Fails: unknown key.
4. Test: a cached failed hello produces a `Skipped` with `cached=True` and the skipped line ends `(cached 3m ago; ...)`;
   a fresh one has no such text; the JSON of `l4 probe --json` carries `cached` and `age_s`. Fails: no field, no text.
5. Test: a required chain whose every profile is skipped only by cached `auth` failures re-probes each of them once
   before `WaitingCapacity` is raised; a cached `other` failure does not; a fresh probe that passes is selected and the
   cache entry replaced. Fails: parks at once from the cache.
6. Test: `l4 probe --no-cache` still ignores both classes (regression pin, expected to pass at once; recorded as
   `already_satisfied`).
7. Test: SPEC L4-AVL-005 text and `docs/SPEC.md` sample config list `auth_failure_ttl` and the class rule (a doc test
   like the existing SPEC-id tests).

**K2: audit tests are linted and listed** (SPEC L4-VER-002 step 4a, L4-VER-009; `verifier/audit.py`, `ladder.py`)

8. Test (reproduction): an audit writer (fake backend) returns a test with an unused import; with `gates.lint =
   ["ruff check"]` the current ladder accepts it and commits it. Assert the new behaviour: status `rejected`, reason
   starts `lint:`, not in `vc.verifier_tests`, no commit of it by `commit_verifier_tests`. Fails: accepted.
9. Test: the writer is given the lint output once and returns a fixed test: accepted, one extra `audit` retry in the
   ledger, the committed file is lint clean. Fails: no retry path.
10. Test: with the retry also failing lint, the criterion is held (`held` text names the lint failure), the round's
    verdict cannot be PASS on that criterion, and the hand-off head contains no failing audit test. Fails: handed off.
11. Test: with no `gates.lint` configured, nothing changes (an accepted test stays accepted, no gate call). Pin.
12. Test: the lint run uses only the audit test files (not the whole repository), through the same gate runner and
    sandbox as step 2 (the fake runner records the command and the cwd). Fails: no lint call.
13. Test (reproduction): after an accepted audit, the judge prompt's per-test list holds the audit test with its
    `audit` label and ids; today it does not when the audit ran after the trace was captured. Fails: absent.
14. Test: a rejected audit test is absent from the per-test list and from `_round_outputs`, and listed under "rejected
    audit tests" in `verification.md` with the reason. Fails: no such section.

**K3: loopback sockets for the Codex implementer** (SPEC L4-SEC-001, L4-IMP-004; `agents/codex.py`, `implementer/templates/contract.md`)

15. Spike first, on a runner with codex 0.160 (private evidence only; record the exact keys and the result in
    `docs/plan/m112-progress.md`): run `codex exec -s workspace-write` with `-c sandbox_workspace_write.network_access=true`
    and without it, executing `python -c "import socket,http.server,threading,http.client; ..."` against port 0 on
    127.0.0.1, then a `socketpair()`. The outcome picks branch (a) or (b) of decision 5. Test (offline, builds on the
    result): `build_command` passes the setting only when the profile opts in and the mode is `implement`, never for
    `judge` or `read`. Fails: no opt-in key.
16. Test: `contract.md` (version bumped) states that sockets are blocked in the implementer step and how an HTTP
    scenario is tested in-process; the rendered implementer prompt of a unit whose criteria mention HTTP carries it
    (`render_prompt` golden). `uv run python -m l4.templatelock --write` after the bump. Fails: sentence absent. If
    branch (a) is taken the sentence says loopback is allowed and an all-outbound switch is rejected by a test that
    asserts `network_access` never appears with an `implement` run that did not opt in.

**K4: a designed stop is a warning** (SPEC L4-CLI-001, 2.2, 16.2, 16.3; `exitcodes.py`, `ci/templates/*`, `ci/watch.py`, forge note)

17. Diagnosis, no code: with the private job and pipeline records for 5755 (MF-2) and the project's include as
    adopted, read the job JSON `allow_failure` and `status`, compare `.l4/ci/l4.gitlab-ci.yml` with the template, and
    write what was found in `docs/plan/m112-progress.md` (the cause, [V] after this line). Lines 18–22 are the part
    that holds whatever the cause is; line 20 is only built if the include was stale.
18. Test: `exitcodes.CI_ALLOWED == (10, 11, 12, 13)`; the GitLab template's `exit_codes` parsed from the YAML equals it;
    the GitHub template calls `map-exit` for each step; `map_exit(c, "github")` exits 0 for every code in it and 1 for
    1, 2, 3, 14, and for 127/137. Fails: no constant (the template check is the part that pins the future).
19. Test: `l4 ci map-exit 11` on GitLab prints `designed stop, not a failure: ...` with the unit's `exit_reason` and
    returns 11; the same text is present for 10, 12, 13 and absent for 14. Fails: the generic meaning only.
20. Test (if line 17 says stale): `l4 doctor --ci` reports `CI-0xx` when the adopted include's `exit_codes` list differs
    from `CI_ALLOWED`, and `l4 upgrade` re-renders it. Fails: no check.
21. Test: for `awaiting_human` the MR sticky note has a section `Waiting for you` listing the open question ids (Q-NNN,
    title) and the one command or label that answers; for `waiting_capacity` the profiles and `retry_after`. Fails:
    only halted units have the section (the M1.11 line-16 section is the base).
22. Test: severity order is unchanged (`1 > 2 > 3 > 14 > 13 > 11 > 12 > 10 > 0`) and a run with units at 11 and 14
    exits 14. Pin, passes at once. SPEC 2.2 gets one sentence: 10/11/12/13 are designed stops.

**F1: a reject is the first thing in the fix task** (SPEC L4-VER-006; `verifier/fixunit.py`, `implementer/templates/single*.md`)

23. Test (reproduction): a verify result with a coverage-hold finding and a human `reject` verdict with a reason
    ("the code is wrong: sub_areas must be removed from the rename payload"); `plan_fix_unit` returns one group whose
    `detail` starts `Decided by human in Q-NNN: the code is wrong ...` and whose `tests` is True; a second case where
    the reject targets the criterion and not the finding id; a third where the reason is longer than 600 characters
    (the decision is kept whole, the finding detail is the part cut). One of these fails today; the test says which.
24. Test: the rendered `single_tests.md` prompt for a task titled with a decision contains the decision first among
    the task text and the sentence of decision 8 (version bumped, lock regenerated). Fails: sentence absent.
25. Test: a test chore that adds a test failing against the current code and reports `blocked` with the decision as the
    reason is **not** rejected as "a test that fails" and raises a question (`kind: technical`, text naming the test and
    the decision); one that adds tests that all pass against code the decision calls wrong gets a retry reason naming the
    decision ("this test asserts what the code does now; the decision above says otherwise"). Fails: the second is
    accepted, the first is rejected.
26. Test: `l4 verify` on a fix unit whose parent hold was rejected carries the reject text in `proposal.md` and the task
    title's first 600 characters (file written by `create_fix_unit`), redacted. Pin of the `a1a0ca3` path for holds.

**F2: a frozen red test that contradicts the spec** (SPEC L4-IMP-002, L4-QMD-005/006; `implementer/templates/green.md`, `loop.py`, `unfreeze.py`)

27. Test (the MF-7 shape): a frozen red test asserts `body["sub_areas"]`; the spec and design say `subareas`. A fake
    green agent reports `blocked` with a question that names the test file and the contradiction. Assert the raised
    question has kind `technical`, a `Clarifier suggestion` of the form `Edit <path>: <change>` (or a title and context
    that name the file, line and the one-key change), and Status `proposed`. Fails: no suggested edit.
28. Test: that question, set to `accepted` by a human (and to `answered` with an answer naming the file), makes
    `unfrozen()` grant exactly that file for that task, and nothing else; the next green may edit it, the integrity step
    lists `unfrozen by Q-NNN`, and a second test file the answer does not name stays frozen. Pin of M1.10 C2 for the
    MF-7 case; expected to pass at once and recorded as `already_satisfied` if so.
29. Test: `green.md` (version bumped, lock regenerated) asks for the question to name the test, the line, the
    contradiction and the exact edit; the rendered prompt of a unit with a frozen test carries the sentence. Fails:
    sentence absent.

## Order, size and risk

* Order: 17 (diagnose) and 15 (spike) first, since they decide branches; then K1, F1, F2, K2, K4, K3. Each commit
  carries its tests; templates changed (`contract.md`, `green.md`, `single_tests.md`, `single.md`) are version-bumped
  and `uv run python -m l4.templatelock --write` is run in the same commit.
* Unit and contract suites only on the worktree (`tests/unit/availability`, `verifier`, `ci`, `implementer`,
  `cli`); the full suite in the background tool mode, never piped into `tail` in an `&&` chain.
* Highest damage if wrong: **line 5** (re-probing auth failures when a role is needed: a wrong rule loops probes or
  hides a real outage), **line 10** (a lint failure must never reach a hand-off head), **line 25** (a failing test
  accepted as a result must not open a way to hand off a red test). Each gets an adversarial test beside the line.
* Out of scope: moving the lint gate before 4a; an all-outbound codex network switch; a new unfreeze route; changes to
  the 14-is-a-failure rule; MF-7's own resume (it runs on the landed harness).
* [U] to settle in the build, not here: the live 403 text (line 1), the include actually adopted (line 17), the codex
  0.160 keys (line 15).
