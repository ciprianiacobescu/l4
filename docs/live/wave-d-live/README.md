# Wave D live check on `example-group/dummy-agentic` (118), 2026-10-08 (harness `299774d`)

**Verdict: upgrade-safe.** Steps 1 to 4 pass, and no spurious cancel was seen.

* **Step 1:** the job API answers a running job's own token with `200` and `running`, from curl and from Python's
  urllib (the watchdog's own call).
* **Step 2:** the upgrade to `299774d` is live.
* **Step 3:** a Kiro unit with dotted criteria (`1.1. WHEN …`) went to MR ready. A person's `# noqa: E402` was
  listed in `verification.md`, not failed, and no fix unit was spawned. The done-gate recorded `archive.done` after the
  merge.
* **Step 4:** a real cancel during the S1-judge step, after two pushes of the unit branch, gave this sequence:
  * the watchdog stopped `l4 run` 28.6 s later, with exit 16, `run.cancelled` and `lock.released`;
  * nothing was pushed and nothing was written to the forge;
  * the job was `canceled` 34 s after the cancel, with no 10-minute wait;
  * no process of the job was left at +60 s;
  * the deleted branch stayed deleted for 13.4 min, until the next scheduled job;
  * that job took the lock with no `lock.busy` and restarted the unit afresh under a new run id.
* **W-D1:** not live-checked. No per-test timeout occurred.

Two caveats matter most:

1. The cancel was caught by the **watchdog**, not by a signal from the runner. GitLab Runner 19.4.1 (shell executor,
   `--user gitlab-runner`) did not stop the job shell. The job sat in `canceling` until `l4` exited. Then the same shell
   ran `l4 ci map-exit` and the `after_script`. Without the W-D2 watchdog this job would have waited in `canceling`.
   Detection takes up to one poll (30 s).
2. `l4 status` in the `after_script` of the cancelled job crashed with `internal error: GitError … HTTP Basic: Access
   denied`. This is harmless (the runner ignores an `after_script` failure) but reads as a crash (finding F2).

Setup:

* A fresh SSH clone of `main` at `c120b9e` (the H3 restore). Identity `CiprianSpot <maintainer@example.invalid>`,
  no trailers.
* Every push and merge came after `scripts/dev/l4_idle.py` said `idle`.
* GitLab was reached only through `scripts/dev/mk-gitlab-api.sh`. The runner was read only, through
  `scripts/runner/mk-ssh.sh` (`ps`, `cat`, `stat`, `git log`). No runner change, no GitLab setting changed, no agent CLI
  run by hand.
* The runner's Claude login is still wiped: `judges: claude-code skipped — claude is not logged in`, then
  `magnitude-qwen … → selected, fallback #1` (expected).

## Per step

| Step | Result | Ids | Quoted lines |
|---|---|---|---|
| 1 job API probe (before any upgrade) | **PASS** [V] | temp branch `tmp/wd-live-jobapi-probe` @ `46a68ce` (pushed 16:00:14Z, deleted after), pipeline 3768, job **6255** on runner #12 `l4-runner` | `api: https://gitlab.example.com/api/v4`; `curl: http_code=200 status=running`; `system-python3 (python 3.10.12, OpenSSL 3.0.2 15 Mar 2022): http_code=200 status=running`; `uv-python-3.12 (python 3.12.15, OpenSSL 3.5.9 29 Sep 2026): http_code=200 status=running`. The probe ([s1/](s1/)) printed only the code and the `status` field. The vendored harness later ran on CPython 3.13.16 (doctor `ENV-001`), and steps 3 and 4 are the proof for that interpreter. |
| 2 upgrade, doctor, push | **PASS** [V] | dummy `f649daf` (vendored harness `299774d73fe4`), pushed 16:01:42Z; pipeline 3769, job **6257**; schedule pipeline 3770, job 6259 | `l4 upgrade --harness <harness repo>`: `changed .l4/vendor/ (2 added, 29 changed, 0 removed) to the harness at 299774d73fe4` (the 2 added are `cancel.py` and `gates/hang.py`). `diff -r` of `src/l4` against `.l4/vendor/src/l4` showed only `_commit.py`. Local `l4 doctor` exited 0 (Mac-only warnings), and `plan --json` showed no actionable unit. Job 6257: `[l4] run: nothing to do: no unit has a next step`, `Job succeeded`, and `outcome.json` `harness_commit 299774d…, exit_code 0`. In 6257 and 6259, `only the session check`, `stopping the run`, `job API` and `cancelled` all count **0**. Caveat: that `l4 run` lasted about 1.5 s, so this job alone cannot show that the watchdog's first check finished. Steps 3 and 4 show it. |
| 3a Kiro spec, dotted criteria | **PASS** [V] | seed `283b215` `.kiro/specs/add-gift-wrap-fee` (2 requirements, criteria `1.1.`–`1.3.`, `2.1.`–`2.2.`, 2 leaves, wave graph) | The new parser reads 5 criteria (`C-90db6a39` `Req 1.1` … `C-cf5f094c` `Req 2.2`). The old parser (harness `9bcfb9c`'s `criteria.py`, run as an oracle) reads **0** of them, so the dotted form is new reading. Local doctor: `SPEC-002 pass 4 Kiro unit(s) validate`, `SPEC-004 pass … every leaf cites a requirement`. On the runner (job 6263): `SPEC-002 error pass 4 Kiro unit(s) validate` ([criteria-parsers.txt](s3/criteria-parsers.txt), [prepush-doctor.txt](s3/prepush-doctor.txt)) |
| 3b unit to MR ready | **PASS** [V] | pipeline 3772, job **6263**, run `r-20261008T1618Z-366e`, MR **!39** | `implementer: f-muse ok (… hello 4.1s) → selected`; `task 1.1 red ok: 3 new test(s) failing as expected`; `pushed l4/kiro/add-gift-wrap-fee 283b2157ba..9347a4388a`; `task 1.1 green ok`; `task 2.1 red ok: 2 new test(s)`; `task 2.1 green ok`; `verdict PASS (round 1, 5/5 criteria pass, 0 finding(s))`; `MR … marked ready for review`; `run finished: exit 0 in 458.2s`. The trace has **no** watchdog line: `only the session check …` and `stopping the run` count 0 across a 458 s run, about 15 watchdog polls at 30 s [I]. There is no "armed" line in the harness, so this absence and the step 4 cancel are the proof (finding F4). No throttle, in-run wait or already-satisfied line occurred. |
| 3c person's `# noqa: E402`, M1.9 re-verify | **PASS** [V] | human commit `d03302a` (`tests/test_gift_wrap_checkout.py`, a `sys.path` line before the import) pushed 16:26:57Z; pipeline 3784, job **6266**, run `r-20261008T1627Z-4e4c` | `phase in_review → verifying (commit_after_handoff: 1 commit, d03302a104 Add a gift-wrap check … by CiprianSpot)`; `pushed l4/kiro/add-gift-wrap-fee d03302a104..bb061def86` (the lease fix `51b7b2f`: a person moved the branch and the run's push landed); `verdict PASS (round 2, 5/5 criteria pass, 0 finding(s))`; `run finished: exit 0 in 267.2s`. `verification.md` round 2 has `suppressions \| ok \| 1 new suppression(s), 0 declared (+1 by humans, listed)` and the section **`## Suppressions added by humans (allowed, listed: SPEC 2.10)`** with `- tests/test_gift_wrap_checkout.py:10 # noqa: E402 (added by d03302a104)`; `## Findings` is `None.` The run's events have no `fix.spawned`, and no fix folder exists ([verification-round2.md](s3/verification-round2.md)) |
| 3d human merge, Kiro done-gate | **PASS** [V] | `PUT …/merge_requests/39/merge` at 16:33:03Z: merge `29ce2e7`; pipeline 3788, job **6269**; schedule job 6271 | `[l4] sweeper: kiro:add-gift-wrap-fee: MR !39 merged`; `[l4] sweeper: kiro:add-gift-wrap-fee: the done-gate passed on 29ce2e78cd; no archive MR (Kiro has no archive folder)`. The pending ledger on `refs/l4/locks/kiro/add-gift-wrap-fee` has `phase.changed in_review → merged (pr_merged)` and `archive.done {via: done_gate, base: 29ce2e78…}`. Job 6271: `the done-gate passed earlier (archive.done is recorded)` ([pending-ledger-donegate.txt](s3/pending-ledger-donegate.txt)) |
| 4a cancel mid-run, delete the branch | **PASS** [V]. The cancel was meant for the green implementer agent, but the trace reached the poller about 44 s late. It landed in verify step 8 (the S1 judge, with the `laya-serve` child running), after two unit-branch pushes. | seed `40f005f` (OpenSpec `add-three-for-two`) pushed 16:48:51Z; pipeline 3790, job **6273**, run `r-20261008T1649Z-76d0`, draft MR !40 | Before the cancel: `pushed l4/openspec/add-three-for-two 40f005f0a2..7d25fa77de` (red), `… 7d25fa77de..2b841b96ad` (green), `phase implemented → verifying`, `s1_judge: laya ok → selected`, `laya-serve started: pid 1263446` (16:51:06). **16:51:08.040Z** `POST jobs/6273/cancel` → `canceling`; 16:51:08.548Z `DELETE …/branches/l4%2Fopenspec%2Fadd-three-for-two` → 2xx; 16:51:09.473Z `GET` → 404 ([timeline.txt](s4/cancel/timeline.txt)) |
| 4b the run stops, exit 16 | **PASS** [V] | job 6273 trace (GitLab still took trace lines while `canceling`) and the run log copied from the runner | `16:51:36.680 [l4] cancel: the CI job is over (cancelled or its session is gone): stopping the run`; `16:51:39.155 [l4] system_one: laya-serve stopped: pid 1263446, exit code -15`; `16:51:39.194 … run finished: exit 16 in 122.3s`; `[l4] run: openspec:add-three-for-two: run cancelled; the final ledger is not pushed`; `[l4] cli: run cancelled (signal 15); nothing more was pushed`; `l4 exit 16 (cancelled): the run was cancelled by a signal or its CI job ended; nothing was pushed`; `ERROR: Job failed: exit status 16`. `outcome.json` `exit_code 16`, `l4.env` `L4_EXIT=16`. The unit worktree ledger (`~gitlab-runner/.cache/l4/worktrees/openspec/add-three-for-two/…/r-20261008T1649Z-76d0.jsonl`) ends `run.cancelled {signal: 15}` (16:51:39.171), `lock.released` (.184), `run.finished {exit_code: 16}` (.188). The lease file `locks/openspec/add-three-for-two.lock` was truncated to 0 bytes at 16:51:39.199 ([runner-disk/](s4/runner-disk/), [trace-final.txt](s4/cancel/trace-final.txt)) |
| 4c nothing pushed, no forge write | **PASS** [V] | worktree refs; MR !40 notes and label events | The worktree's `refs/remotes/origin/l4/openspec/add-three-for-two` and local branch are still `2b841b9`, the last push before the cancel. The branch was not recreated by job 6273. MR !40's last harness event is `add l4:verifying` at 16:50:44 and no note or label came after the cancel. GitLab closed MR !40 itself when the branch was deleted ([mr40-label-events.txt](s4/mr40-label-events.txt), [mr40-notes.txt](s4/mr40-notes.txt)) |
| 4d processes, no force-kill wait | **PASS** [V] | runner `ps` at +30 s, +60 s and +150 s | +30 s (16:51:40Z): only the `after_script` of the same job (`bash -l`, `uv run … l4 status`, started 16:51:39) and the user's systemd session. There was no `l4 run`, no `laya-serve`, no bwrap or agent process. **+60 s (16:52:10Z) and +150 s (16:53:40Z): no process of `gitlab-runner` at all** (only the root runner service). Job `finished_at` 16:51:42.277Z is **34.2 s** after the cancel POST (no 10-minute wait) ([runner-plus30.txt](s4/cancel/runner-plus30.txt), [runner-plus60.txt](s4/cancel/runner-plus60.txt), [runner-plus150.txt](s4/cancel/runner-plus150.txt)) |
| 4e branch stays deleted; next job takes the lock | **PASS** [V] (recreated by the next job, as SPEC L4-CLI-003 declares) | polls every ~30 s ([branchwatch.txt](s4/branchwatch.txt)); schedule pipeline 3795, job **6275**, run `r-20261008T1703Z-5b71`, MR !41 | `branch: absent` at every poll from 16:51:09 to 17:03:59, including the first 44 s of job 6275, which started at 17:03:15. The branch was recreated by job 6275's first push at 17:04:34, **13.4 min** after the delete. Job 6275: `phase none → intake (unit_discovered_pending)`, `phase ready → implementing (lease_acquired)`, ledger `lock.acquired {holder: gitlab-runner:1265370}` at 17:04:00, `lock.busy` count **0**. `pushed l4/openspec/add-three-for-two 40f005f0a2..b1b910b884` is a fresh first push from the base, not the cancelled run's `7d25fa7`/`2b841b9`. Every commit on the recreated branch carries `L4-Run: r-20261008T1703Z-5b71` and none the cancelled run's id ([commits-restart.txt](s4/commits-restart.txt)). `verdict PASS (round 1, 3/3 criteria pass, 1 finding(s))`, `run finished: exit 0 in 358.8s` |
| 4f leave the dummy clean | **done: closed and removed** | MR !41 closed 17:11:21Z, branch deleted; human commit `36152ed` removes `openspec/changes/add-three-for-two`, pushed 17:11:50Z; pipeline 3803, job 6278 | Job 6278: `[l4] run: nothing to do: no unit has a next step`. The harness's lock ref `refs/l4/locks/openspec/add-three-for-two` (`026667f`) is left as harness state. The Kiro unit `add-gift-wrap-fee` stays merged with its done-gate recorded ([refs-diff.txt](refs-diff.txt)) |
| 5 W-D1 per-test timeout | **not live-checked** | — | No `l4-test-timeout`, `L4_TEST_HANG` or hung-test line occurred in any job of this check (grep over every saved log and run log) |
| config restore | **PASS** [V] | `.l4/config.yaml` | The only change is the upgrade's own pin (`harness.commit 9bcfb9c… → 299774d…`). `cmp` of the config on `main` (`36152ed`) against the bytes written by the upgrade succeeds, and nothing else was ever changed. The pre-test bytes are kept as [config-before.yaml](config-before.yaml), the diff as [s2/config-upgrade.diff](s2/config-upgrade.diff) |

## Findings

* **F1 (W-D2 behaviour, important, not a defect) [V log, I mechanism].** On this runner the watchdog does the work, not
  the runner's signal. These are verified from the logs:
  * after the cancel the job shell lived on;
  * `l4 run` got no signal for 28.6 s;
  * after `l4` exited, the same shell ran `l4 ci map-exit` and the `after_script`.

  These are inferred:
  * the forge check is what fired (`GET /job` answered `canceling` or a refused token), not the session check, because
    the session leader was still alive;
  * the runner (19.4.1, shell executor, `--user`) waits in `canceling` instead of killing the shell.

  Consequences:
  * the cancel latency is up to one `POLL_S` (30 s);
  * the session check was not exercised here;
  * a run whose job API check fails open would not stop until the runner's force-kill.

  The first two are acceptable for W-D2, and the third is the case the fail-open warning exists for.
* **F2 (minor defect) [V].** `l4 status` in the `after_script` of a cancelled job ends with `[l4] cli: internal error:
  GitError: … fetch --quiet --prune origin +refs/heads/l4/*:… +refs/l4/locks/*:… failed (128): remote: HTTP Basic:
  Access denied`. In a normal job the same `after_script` prints the status table (job 6263).
  * Inferred cause: the fetch authenticates with the CI job token in the runner's `origin` URL, which GitLab refuses
    once the job is cancelled.
  * Harmless (`WARNING: after_script failed, but job will continue unaffected`), but it is logged as an internal error.
  * Fix idea: `status` should fall back to local refs when the refresh fetch is refused, or say so in one line.
* **F3 (as specified) [V state, I cause of the close].**
  * The cancelled run's ledger exists only in the runner's worktree. The branch that carried it was deleted, and there
    is no lock ref for a unit before its hand-off, so the next run started at `phase none` with no record of the
    cancelled attempt on the forge.
  * MR !40 is `closed` with the stale label `l4:verifying` [V]. No bot or person closed it after 16:50:44, so GitLab
    closed it when its source branch was deleted [I]. The restart opened MR !41.
  * Both match the SPEC residual ("a NEW run after a person deleted the branch starts the unit afresh").
* **F4 (observability) [V].** No log line says that the watchdog is armed, so a normal job proves the watchdog only by
  absence (no fail-open warning, no spurious cancel). An INFO line at start (`cancel: watching CI job <id> (job API +
  session <sid>)`) would make step 2 of a live check direct evidence. The task asked to quote one.
* **F5 (W-D6 detail) [V].** ruff exempts `sys.path` changes from E402, so this `noqa` is not needed for the project's
  ruff gate. pycodestyle does flag the line without it (`E402 module level import not at top of file`), so the comment
  is a realistic suppression. The harness listed it by commit, as built.
* **F6 (seen in passing, not wave D) [V].** The f-muse implementer did not follow the steering rules of
  `.kiro/steering/pricing-rules.md`: `GIFT_WRAP_FEE_PER_UNIT` is not in `__all__`, and `gift_wrap_fee` has no
  docstring ending in `(Req …)`. The magnitude-qwen judge passed it (K10/F5 of the Kiro H2 and H3 checks, still open).
* **Not seen live:** a throttle, a kiro-polish in-run wait (`availability.wait_in_run`), an already-satisfied leaf,
  `step.finished` with `rate_limited`, and a W-D1 per-test timeout. W-D3 (Codex real-server tests) was not in scope:
  the free-first chain chose f-muse.

## Evidence

* [s1/](s1/) holds the probe CI file and script (`probe.gitlab-ci.yml`, `jobapi_probe.py`), the job log, and the
  temporary branch push and delete.
* [s2/](s2/) holds the upgrade output, the local doctor and plan, and jobs 6257 and 6259 with the 6257 artefacts.
* [s3/](s3/) holds:
  * the seed spec and the criteria parsed by both parsers;
  * job 6263 (with artefacts), 6266, 6269 and 6271;
  * `verification-round1.md` and `verification-round2.md`;
  * the human test file;
  * the commits;
  * MR !39 before and after the merge;
  * the done-gate pending ledger.
* [s4/](s4/) holds:
  * `cancel/`: the timeline, the trace before the cancel and the final trace, the runner snapshots and the job 6273
    artefacts;
  * `runner-disk/`: the run log, worktree ledger, outcome and lease stat read from the runner before the next job;
  * `branchwatch.txt`;
  * `ci/`: job 6275 with its artefacts;
  * `cleanup/`.
* [tools/](tools/) holds the scripts used:
  * `cancel4.sh`: wait for the first unit-branch push and the next step, then cancel, delete and take the runner
    snapshots;
  * `runner-snap.sh`: a read-only `ps`/`cat`/`stat`;
  * `branchwatch.sh`, `watchjob.sh` and `tracejob.sh`;
  * `collect.py`.

ANSI sequences were stripped. The runner's `token=` upload fragments and every e-mail shape other than the commit
identity were redacted. The token-shape scan (glpat-, glcbt-, glptt-, apikey_, sk-, sk-ant-, mk_agent_, JWT, `aoa…`,
`mag-`) over all 216 files found none. Job artefact folders are named `l4-out/` here (the repository ignores
`.l4-out/`).
