# M1.12 progress (2026-10-07)

Branch `m112` from `main` 287b361, plan commit 0e374d5. Labels: [V] verified, [I] inferred, [U] not checked.

## Settled unknowns

* **Live 403 text (line 1) [V].** The wave-b judge ledgers show the Claude refusal as the hello failure
  `claude reported an error (api_error_status 403)`, with no limit signal. So it took the plain-failure path and was
  cached 15 minutes. It is now class `auth` (cached `availability.auth_failure_ttl`, default 2m).
* **K4 diagnosis (line 17).**
  * [V] The template has allowed 10, 11, 12 and 13 since M1.11. In wave A, jobs 5703, 5709 and 5724 (same project, exit
    11/12 style stops, same `ERROR: Job failed: exit status N` line) are recorded by the watcher as
    `failed allow_failure reason=script_failure`: GitLab shows an allowed failure as `failed (allowed)` and the runner
    prints its own unconditional ERROR line. The pipeline stays green (the MR head pipeline of the same unit is `success`).
  * [I] Job 5755 itself: the watcher recorded only `pending -> running` for it and the repository has no job JSON for
    it, so its `allow_failure` is not read directly; it ended with the same trace line as the three above.
  * [U] The adopted include of the project is not available here, so "stale include" is neither shown nor excluded. The
    job runs `doctor --ci --fix` first, and `l4 upgrade` already re-renders a stale list (`tests/unit/init/test_upgrade.py`).
  * Consequence: K4 is wording. Line 20 (a doctor check of the adopted include) is **not built**: nothing showed it stale.
* **Codex 0.160 keys (line 15) [U].** Codex is not installed on this machine, so no spike was run. What the Codex source
  documents (read through Context7, not run) is one boolean `sandbox_workspace_write.network_access`, which enables ALL
  outbound network, not loopback only. The plan rejects that switch, so branch (b) is taken: the contract says sockets are
  blocked and how to test HTTP in-process. A runner with codex 0.160 should still run the spike; if it finds a
  loopback-only key, it can be added as an opt-in profile option (a new build line).

## Lines

| Lines | Result |
|---|---|
| 1 | class on a failed hello (claude status, codex text/exit, opencode status), kept through the cache JSON. |
| 2-3 | per-class lifetime stored in the cache entry (`put(ttl_s=)`); `availability.auth_failure_ttl`; excluded from the probe identity. |
| 4 | `Skipped.cached/age_s`, the `(cached Nm ago; l4 probe --no-cache re-probes)` suffix, `cached/age_s` in events and `l4 probe --json`. |
| 5 | one re-probe per profile per selection of a required role, after the walk and the busy wait. Adversarial tests: counts per call, optional role, `other` class, a profile later in the chain, a limit at the re-probe. |
| 6 | pin, passed at once (already satisfied). |
| 7 | SPEC L4-AVL-005/007 and the 3.2 sample, with a doc test. |
| 8-14 | audit lint in 4a; see below. Lines 12 and 13 reproduced first (red), the rest by the same file. |
| 15 | not run (see above); the never-appears guard test is in `tests/unit/agents/test_codex_loopback.py`. |
| 16 | `contract.md` 6 -> 7 (an `@codex` line), lock regenerated. |
| 17 | diagnosis above. |
| 18, 19, 21, 22 | `CI_ALLOWED`; template checked against it; the GitLab line `designed stop, not a failure: ...`; heading `Waiting for you: a human answer`; severity pin (passed at once). 20 not built. |
| 23 | the long-decision case failed (cut at 600); fixed by `_fit_detail`. The first two cases passed at once. |
| 24 | `single_tests.md` and `single.md` 1 -> 2. |
| 25 | the blocked-with-failing-test half and the red-reported-done half already held (pins); the passing-tests-against-wrong-code retry was added. |
| 26 | pin, passed at once. |
| 27 | `green.md` 2 -> 3, first option "Edit `<path>`: ..." becomes the question's suggested answer. |
| 28 | pin of M1.10 C2, passed at once. |
| 29 | the template sentence. |

## Deviations and limits (read these)

1. **Line 5 reading.** The rule is per profile: every profile skipped on a *cached auth-class hello* is re-probed once
   when a required role has nothing else usable, also when other profiles of the chain are skipped for other reasons
   (cooling, constraint, binary). The plan's "skipped only by" could be read as "every profile of the chain"; that would
   leave a chain `[cooling, cached 403]` parked until the cool-down ends although the 403 may be fixed. Cost: one hello per
   such profile per selection; no age guard (a hidden clock would make the behaviour harder to test).
2. **Line 12.** Only `ruff check` is narrowed to the audit file (`narrow_ruff_paths`); any other lint or typecheck command
   runs as configured (the whole repository). It still guards the head: at that point only the audit files differ.
   `gates.typecheck` is included as well as `gates.lint` (decision 3).
3. **Line 21.** The existing sections already list ids and how to answer (11) and profiles and `retry_after` (12). The
   change is the heading of the 11 section, `Waiting for you: a human answer`, in the clarifier note and the fix-unit note;
   the capacity section keeps `Waiting for capacity`. An existing test and a live-test string were updated.
4. **Line 19** prints the new phrase on GitLab only; the GitHub annotation text is unchanged (`::warning::`).
5. **Line 25 retry** is a cue-word check on the decision text (wrong, bug, incorrect, must not, instead of ...) and
   applies on attempt 1 only, so a legitimate passing test set is delayed by one attempt at most. It cannot tell a pinned bug
   from a right test.
6. **Line 27.** The question's status stays `open` (the plan said `proposed`, which is not a status). The suggestion is
   written by the harness from the agent's first option, only for a technical question whose first option starts with
   "Edit `path`: ". If a clarifier runs afterwards it may replace the suggestion.
7. **Decision 5 last sentence** (the judge not raising "white-box test for an HTTP scenario" against the named limit) is
   not built: the judge does not see the implementer prompt, and changing the judge prompt changes its version and goldens.
8. The test fixture `with_verifier` moved from `test_ladder_depth.py` to `tests/unit/verifier/conftest.py`.

## Audit lint (lines 8-14), in one place

After `run_audit` accepts a test, each `gates.lint` / `gates.typecheck` command runs on its file through `Workbench.run_gate`
(gate name `lint-audit`). A failure goes back to the writer once with the output and the test; the fixed file is judged like
a new one (it must still pass at head and fail against zero values) and linted again. Still failing: `rejected`, reason
`lint: <first line>`, file removed, not in `out.accepted` (so not in `commit_verifier_tests`), not in the judge's round
outputs, criterion held (`needs_human`). Ledger: `verify.audit_lint{outcome: failed|fixed|rejected|not_accepted}`.
`verification.md` has a `Rejected audit tests` section. The judge's per-test list now carries each accepted audit test
labelled `(audit test of C-...)`.

## Suite

See the section appended below by the final run.

### Final run (chunks as ordered; collected = passed + skipped + xfailed)

| Chunk | Collected | Passed | Skipped | Xfailed | Note |
|---|---|---|---|---|---|
| agents, availability, llm | 555 | 550 | 5 | 0 | 1 timing flake under load (`test_interrupt_sends_sigint_then_the_run_ends`, passes alone, not touched by M1.12) |
| verifier, implementer, gates | 1285 | 1281 | 3 | 1 | 1 failure found by the run (`test_green_prompt_lists_the_unfrozen_paths` pinned green version 2): fixed, re-run passes |
| orchestrator, archive, state, vcs, specs | 597 | 595 | 2 | 0 | |
| every other tests/unit dir and test_*.py | 1933 | 1928 | 5 | 0 | |
| contract, scenarios, integration, live | 122 | 59 | 63 | 0 | live tests skip without `L4_LIVE` |

`uv run ruff check .` clean; `python3 scripts/check_spec.py docs/SPEC.md` clean. The two re-runs above were of the failing test files only (agents, test_prompt, template lock: 260 passed), not of the whole chunk.
