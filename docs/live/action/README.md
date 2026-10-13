# Live evidence: the setup action (adoption-kit, L4-ACT-008)

All adoption runs are on `ciprianiacobescu/l4-dummy-action` (private, GitHub-hosted `ubuntu-24.04`). The pin column is
the harness commit the workflow's `uses:` named. The harness repository's own CI runs are on branch `adoption-kit`.
Step timings come from the Actions API. The spike's logs and step files are in [`spike/`](spike/README.md).

## Runs

| Run | Pin | What it shows | Requirement |
|---|---|---|---|
| 38299270512 .. 38299563947 (spike) | spike action | A private action from a public repository fails at "Set up job". The same action from a private repository of the same owner works with no key. A copy of the action with a deploy key works. A warm `l4` starts in 0.28–0.43 s. | SCN-ACT-01, SCN-ACT-02 (SCN-ACT-03 with the spike action) |
| 38301695561 | 20cced6d | Source `action`, cold. The runner setup logs `[HSU-99] OK … bwrap=user-space`. A bad commit stops in 86 ms, before any download. | SCN-ACT-04, SCN-ACT-07 |
| 38302117681 | 744767dc | The harness cache hits. Outputs `harness-cache-hit=true clis-cache-hit=false`. | SCN-ACT-05 (harness cache) |
| 38304739805 | ac51e81f | After `l4 init --ci github --action`, the dummy holds only `.github/workflows/l4.yml`, `.l4/config.yaml` and `.serena/project.yml`. Seed unit `add-shelf-code`: intake to in_review, OpenCode red 40 s then green, Claude judge PASS 2/2, PR #1 ready. Job 174 s (action 6 s cold; doctor 26 s installing openspec, claude and opencode; CLI cache saved in 4 s). | SCN-ACT-08, SCN-ACT-13 |
| 38305164623 | ac51e81f | Warm: both caches hit. The action step took 16 s because the CLI cache was 383 MB (12.0 s restore). This led to the shrink fix. | SCN-ACT-05 |
| 38305400448 | | What the CLI cache held: npm's download cache 353 MB, installed npm 373 MB, claude 235 MB, `~/.local/bin` 47 MB (mostly uv). | L4-ACT-002 |
| 38307444318 | 3cd4cfee | `l4 upgrade --harness-commit` changed one line. Seed unit `add-reorder-quantity`: PR #2, PASS. The ledger names `harness 3cd4cfee6f04`. | SCN-ACT-10, L4-INS-005 (provenance) |
| 38308033922 | 3cd4cfee | The CLI cache missed although it had been saved: the save step's literal paths had drifted from the action's. Fixed in 4463beda (the paths are the action's output `clis-cache-paths`). | L4-ACT-002 |
| 38308990414 | 4463beda | `l4 upgrade` migrated the save step: only the `uses:` line and the path block changed. Cold, both caches saved. | SCN-ACT-10 |
| 38309137948 | 4463beda | Warm: harness cache 24 MB restored in 1.8 s, CLI cache 229 MB in 3.8 s, action step 7 s, doctor 4 s, job 25 s. | SCN-ACT-05, SCN-ACT-13 |

## The harness repository's CI (branch `adoption-kit`)

| Run | Result |
|---|---|
| 38302581274 | First sharded run: 7 of 8 shards failed, 36 tests (no git identity on runners, ambient CI variables, host tools). Fixed by making the suite hermetic. |
| 38311508966 | One failure: a new module was not classified in the login-lock coverage test. Fixed. |
| 38312211032 | All 8 shards green, 103–355 s per shard, about 32 runner-minutes. |

## Open

- SCN-ACT-03 with the final action and `--action-copy`: validated in the spike with the spike action only.
- SCN-ACT-06: a harness-only upgrade keeps the CLI cache. It is pending a harness code change.
- `action-selftest.yml`: it can run only once it is on the default branch, because GitHub dispatches only workflows
  that exist there (HTTP 404 otherwise).
- SCN-ACT-11: one release. It is deferred until after the merge to `amaster`, from a tagged `amaster` commit.
- The skill (L4-SKL-001, L4-SKL-002; tasks 4.1–4.3) is not built.

## With human feedback and Kiro (2026-10-13, integration/feedback-action)

| Run | Pin | What it showed |
|---|---|---|
| 38328650333 | 5e83ea81 | A Kiro native unit (kiro-cli 2.30.0, API key, glm-5) went through the action to PR #3 ready, judged PASS 4/4. **SCN-ACT-06:** after a harness-only upgrade the harness cache missed and the CLI cache was restored as a hit. It also showed the gap: kiro-cli was not in that cache, doctor installed it, and a hit is never re-saved. |
| 38329266005 | 5e83ea81 | **Defect:** on a person's push to a unit branch of a PRIVATE repository, the `base checkout` step's credential-less `git fetch` failed (`could not read Username`). Fixed in 657efb40: detach to `origin/<base>`, already fetched by `fetch-depth: 0`. The fetched form had the same step, so the fix applies there too. |
| 38330251183 | 19a2403a | The dummy was upgraded with the new `l4 upgrade`, which re-renders the whole workflow and printed the diff (the base-checkout step, the pin, the status guard). The CLI cache key now includes the config's CLIs: a new key, a miss, and openspec, claude and kiro-cli installed and saved. The feedback loop ran to PR #3 ready again; see docs/live/feedback on the human-feedback branch. |

Still open:
- SCN-ACT-03 with the final action and `--action-copy`;
- the action self-test workflow and one release (both after the merge to amaster);
- the skill.
