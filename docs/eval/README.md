# Eval baselines (`l4 eval`, M1.14)

What `l4 eval` measures, what it cannot see and the rules of the gate are in [../eval.md](../eval.md) (SPEC §20.1).
This folder holds the **committed baselines**: one directory per run, `scorecard.json` (canonical, the file
`l4 eval --compare` and doctor `EVAL-001` read) and `scorecard.md` (the same for people). Nothing else of a run is
committed (the cell directories hold redacted logs and ledgers, but they are evidence of one run, not a baseline).

| Run | Seed set | Harness | Profiles | Status |
|---|---|---|---|---|
| [2026-10-08](2026-10-08/) | `ed59f51d8bf8` (4 units) | `f0c703c` | implementers f-muse, f-longcat, magnitude-qwen (reference judge codex); judges magnitude-qwen, f-longcat, claude-code | **first baseline** |

## How to run (l4-runner, as `gitlab-runner`, outside CI)

The runner rules of [../eval.md](../eval.md) apply: start cells only in quiet windows (the sample-consumer and
dummy-agentic CI lanes have priority), never copy or refresh a CLI login, never print a Mintkey secret. The tools of
the first baseline are in [tools/](tools/); `W=/home/gitlab-runner/l4-eval-<date>` is the run's working directory.

1. **A checkout of the harness on the runner**, at the commit to measure (a real git checkout: the scorecard records
   `harness.commit` and `dirty` from it). The harness repository is never pushed: ship a bundle over the SSH channel.
   ```
   git bundle create docs/eval/tools/harness.bundle main
   cp <project>/.l4/config.yaml docs/eval/tools/profiles.yaml      # the profiles to measure, e.g. dummy-agentic's
   docs/eval/tools/mk-setup.sh > /tmp/setup-remote.sh && docs/live/free/tools/rssh.sh --script /tmp/setup-remote.sh
   ```
   `mk-setup.sh` writes the bundle, `profiles.yaml` and `launch.sh` under `$W`, clones the bundle to `$W/harness`,
   runs `uv sync --frozen` there and creates the hold file `$W/HOLD`. Later commits: `mk-update.sh` (fast-forward).
2. **Warm the uv cache once** (the only step that reaches an index):
   `sudo -u gitlab-runner -H bash -lc 'cd $W/harness && L4_CACHE=$W/cache .venv/bin/python -m l4 eval --config $W/profiles.yaml --warm-cache'`.
3. **The quiet window.** On the Mac, `tools/hold-monitor.sh` (background) asks `scripts/dev/l4_idle.py` every minute and
   mirrors it into `$W/HOLD`; on the runner `scripts/runner/eval-quiet.sh` is the `--idle-check` (busy while a CI job
   runs on the runner or the hold file exists). A cell starts only when both say quiet; between cells the run waits
   (`--idle-wait 8h`) and never stops a CI job.
4. **Start the run detached**, with a **login shell** (`bash -l`: `uv` and `claude` live in `~/.local/bin`, which the
   non-login `sudo` PATH lacks; without it every cell is `harness_error: setup`):
   ```
   uv run --no-project python docs/eval/tools/feed-launch.py $W/out/<date> \
       --impl f-muse --impl f-longcat --impl magnitude-qwen --ref-judge codex \
       --judge claude-code --judge magnitude-qwen --judge f-longcat
   ```
   `feed-launch.py` reads the Mintkey secret `magnetude-api-key` in its own process and writes it only to the SSH
   channel's stdin; `launch.sh` puts it into the eval process's environment (`MAGNITUDE_API_KEY`, the
   `api_key_env` of `magnitude-qwen`) and starts `l4 eval --config $W/profiles.yaml --out ... --runner --idle-check
   .../eval-quiet.sh --idle-wait 8h` with `setsid nohup`. The key is on no command line and in no file. The Mac must
   stay awake for the magnitude cells (`caffeinate -dimsu`); a sleeping Mac makes them `invalid`, which the gate
   leaves out of every rate.
5. **Watch and fetch**: `tools/peek.sh <date>` (the log tail and each `result.json`). `scorecard.json` is rewritten
   after every cell; an interrupted run is finished with the same command plus `--resume`.
6. **Commit** `scorecard.json` and `scorecard.md` under `docs/eval/<date>/` after a token scan
   (`docs/live/free/tools/tokscan.py` and a check that the magnitude key's value is in no file).

## How to compare

```
uv run l4 eval --compare docs/eval/2026-10-08/scorecard.json --new <out>/scorecard.json     # two files, no agent
uv run l4 eval --baseline-dir docs/eval --new <out>/scorecard.json                          # the newest baseline
```

Exit 0: nothing regressed; **15**: a profile's pass rate (or a judge's agreement) fell by more than `--max-drop` (0.20),
or a judge newly passed the designed defect; **2**: a missing, invalid or incomplete scorecard, different seed sets, or
nothing rated in both. Run it on every template version bump, every CLI pin bump and before a free model leaves a chain
(SPEC §20 item 6); when it passes (or the regression is accepted with a note), commit the new run here as the next
baseline. Only cells rated in both scorecards are compared: a profile whose cells were `invalid` in the baseline (below)
is `new` or `unrated` until a later baseline rates it.

## The first baseline (2026-10-08)

l4-runner, as `gitlab-runner`, harness `f0c703c` (clean checkout; templates red@7, green@4, judge@6, contract@7),
opencode 1.18.34, codex 0.160.0, claude-code 2.1.288, uv 0.12.22, OpenSpec 1.14.0, k = 1, `availability.probe_timeout:
150s` from dummy-agentic's `.l4/config.yaml` (the profiles are that file's, unchanged). Scorecard
[2026-10-08/scorecard.md](2026-10-08/scorecard.md), sha256 `942fe8d0b288…`, `complete: true`, 21 cells. Every cell
started in a quiet window: the runner was busy with sample-consumer and dummy-agentic CI from 01:56Z to 06:39Z
(apart from 90 s at 05:10Z, one cell), so the run, launched at about 02:05Z and resumed at 06:25Z with the magnitude-qwen
cells first (`--resume` kept the one measured cell), measured its cells between 05:10Z and 07:07Z. Token scan: the 86
files of the run directory, 0 token shapes, the magnitude key's value in none.

**Implementer cells** (red and green through the real `l4 run`, then the fixed reference judge `codex`
(`gpt-6-luna`, `reasoning_effort: low`); pass = red and green ok and the verdict PASS):

| Profile | Pass | Red attempts (mean) | Green attempts | Median wall | Errors |
|---|---|---|---|---|---|
| f-muse | **3 / 3** | 1.00 | 1.00 | 74 s | none |
| f-longcat | **3 / 3** | 1.00 | 1.00 | 158 s | none |
| magnitude-qwen | **3 / 3** | 2.67 (3, 3, 2) | 1.00 | 196 s | 3 `schema` |

magnitude-qwen's 8 red attempts: 3 wrote `"status": "red"` (the phase, the M1.13 failure mode; once per unit, on
attempt 1 of add-tip-amount and on the retry after another failure on the other two), 1 wrote a vacuous test
(add-reorder-quantity: the scenario whose answer is 0 passed against the zero-value stubs), 1 left the new tests
without their `@pytest.mark.l4` traces (add-shelf-code). Every attempt after a status error succeeded: the retry's
hint works, the first prompt's allowed-values line does not stop it. Red succeeded on attempt 3, the last allowed,
in 2 of the 3 units. No halt, green on attempt 1 everywhere, codex PASS on all 9 implementer cells.

**Judge cells** (the reference red and green replayed by `python -m l4.eval.replay`, then one judge; pass = the
expected verdict; `add-late-fee` holds the designed defect, expected NEEDS_HUMAN with at least one finding):

| Profile | Agreement | Designed defect | Median wall | Invalid |
|---|---|---|---|---|
| magnitude-qwen | **4 / 4** | caught: NEEDS_HUMAN, 8 findings, worst blocker | 39 s | 0 |
| f-longcat | **4 / 4** | caught: NEEDS_HUMAN, 3 findings, worst blocker | 54 s | 0 |
| claude-code | n/a | not measured | n/a | **4 / 4 `login`** |

claude-code was **not measured**: `claude auth status` on the runner answers `loggedIn: false` [V] (the login was
lost before this work began: the credentials file was last written at 18:33Z on 2026-10-07 [V, `stat` on the runner];
the harness's login-lock change `0de761f` is the root-cause work, not this run). Re-login is the maintainer's action
(`sudo -iu gitlab-runner`, `claude`, `/login`); until then a compare rates no claude-code row. The first attempt at
this run (Claude as the reference judge) is why `reference_unavailable` exists (`f0c703c`): its cell had blocked
f-muse for the run as `endpoint_unavailable` although f-muse had written red and green.

**The reference judge is codex** (eval.md's examples use claude-code): every implementer verdict above is codex's. A
later run with another `--ref-judge` changes every implementer verdict, and `--compare` shows that only in the
environment diff (it does not refuse). Keep `--ref-judge codex` until Claude is logged in again and a new baseline is
taken with it.

Cost: $0 reported for every rated cell (opencode reports $0; codex runs on the subscription and reports no cost).
What this baseline cannot say: k = 1 and 3 or 4 cells per profile (one lost cell is a 0.33 or 0.25 drop, past the
0.20 threshold); toy units; magnitude-qwen ran on the maintainer's Mac while it was kept awake and shared
with other workflows (its wall times include that load).
