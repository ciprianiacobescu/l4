# l4 eval scorecard

## Environment

- harness: `f0c703cca679` [git]
- started: 2026-10-08T06:25:38Z
- seed set: `ed59f51d8bf8`, units add-late-fee, add-reorder-quantity, add-shelf-code, add-tip-amount; k = 1, cell timeout 3000 s
- templates lock: `1f15c8eba5e6`; clarifier v4, implementer/contract v7, implementer/green v4, implementer/red v7, implementer/single v3, implementer/single_tests v4, judge v6, testwriter/audit v4, testwriter/e2e v4
- CLIs: claude-code = claude-code 2.1.288, codex = codex 0.160.0, f-longcat = opencode 1.18.34, f-muse = opencode 1.18.34, magnitude-qwen = opencode 1.18.34
- machine: Linux-6.8.0-138-generic-x86_64-with-glibc2.35, 4 cpu(s), runner True
- scorecard sha256: `942fe8d0b288`

## Profiles

| role | profile | pass rate | agreement | attempts (mean) | median wall | cost | invalid | errors |
|---|---|---|---|---|---|---|---|---|
| implementer | f-longcat | 100.0% | - | red 1.00 / green 1.00 | 157.552 s | $0.0000 | 0 | - |
| implementer | f-muse | 100.0% | - | red 1.00 / green 1.00 | 73.782 s | $0.0000 | 0 | - |
| implementer | magnitude-qwen | 100.0% | - | red 2.67 / green 1.00 | 196.325 s | $0.0000 | 0 | schema 3 |
| judge | claude-code | n/a | n/a | n/a | n/a | n/a | 4 | login 4 |
| judge | f-longcat | 100.0% | 100.0% | n/a | 54.459 s | n/a | 0 | - |
| judge | magnitude-qwen | 100.0% | 100.0% | n/a | 39.197 s | n/a | 0 | - |

## Cells

- `f-longcat` implementer add-reorder-quantity k0: **pass**; red 1 / green 1 attempt(s); verdict PASS; 162.017 s
- `f-longcat` implementer add-shelf-code k0: **pass**; red 1 / green 1 attempt(s); verdict PASS; 145.664 s
- `f-longcat` implementer add-tip-amount k0: **pass**; red 1 / green 1 attempt(s); verdict PASS; 157.552 s
- `f-muse` implementer add-reorder-quantity k0: **pass**; red 1 / green 1 attempt(s); verdict PASS; 73.782 s
- `f-muse` implementer add-shelf-code k0: **pass**; red 1 / green 1 attempt(s); verdict PASS; 64.813 s
- `f-muse` implementer add-tip-amount k0: **pass**; red 1 / green 1 attempt(s); verdict PASS; 75.936 s
- `magnitude-qwen` implementer add-reorder-quantity k0: **pass**; red 3 / green 1 attempt(s); verdict PASS; errors: schema; 211.229 s
- `magnitude-qwen` implementer add-shelf-code k0: **pass**; red 3 / green 1 attempt(s); verdict PASS; errors: schema; 196.325 s
- `magnitude-qwen` implementer add-tip-amount k0: **pass**; red 2 / green 1 attempt(s); verdict PASS; errors: schema; 172.965 s
- `f-longcat` judge add-late-fee k0: **pass**; verdict NEEDS_HUMAN (expected NEEDS_HUMAN), 3 finding(s); worst blocker; 136.711 s
- `f-longcat` judge add-reorder-quantity k0: **pass**; verdict PASS (expected PASS), 0 finding(s); 45.746 s
- `f-longcat` judge add-shelf-code k0: **pass**; verdict PASS (expected PASS), 0 finding(s); 53.429 s
- `f-longcat` judge add-tip-amount k0: **pass**; verdict PASS (expected PASS), 0 finding(s); 55.488 s
- `magnitude-qwen` judge add-late-fee k0: **pass**; verdict NEEDS_HUMAN (expected NEEDS_HUMAN), 8 finding(s); worst blocker; 52.08 s
- `magnitude-qwen` judge add-reorder-quantity k0: **pass**; verdict PASS (expected PASS), 0 finding(s); 33.897 s
- `magnitude-qwen` judge add-shelf-code k0: **pass**; verdict PASS (expected PASS), 0 finding(s); 34.628 s
- `magnitude-qwen` judge add-tip-amount k0: **pass**; verdict PASS (expected PASS), 3 finding(s); worst minor; 43.765 s

## Invalid cells (not in any rate)

- `claude-code` judge add-late-fee k0: login
- `claude-code` judge add-reorder-quantity k0: login
- `claude-code` judge add-shelf-code k0: login
- `claude-code` judge add-tip-amount k0: login
