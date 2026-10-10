# l4 eval scorecard

## Environment

- harness: `d475e6b00000` [git]
- started: 2026-10-07T10:00:00Z
- seed set: `ssssssssssss`, units add-late-fee, add-reorder-quantity, add-shelf-code, add-tip-amount; k = 1, cell timeout 3000 s
- templates lock: `llllllllllll`; implementer/red v5, judge v6
- CLIs: j1 = claude-code 2.1.288, p1 = opencode 1.4.2
- machine: Linux-6.8-x86_64, 8 cpu(s), runner True
- scorecard sha256: `fe1e10be2701`

## Profiles

| role | profile | pass rate | agreement | attempts (mean) | median wall | cost | invalid | errors |
|---|---|---|---|---|---|---|---|---|
| implementer | p1 | 66.7% | - | red 1.00 / green 1.67 | 143 s | n/a | 1 | rate_limit 1, schema 1 |
| judge | j1 | 66.7% | 66.7% | n/a | 5 s | $0.1875 | 0 | - |

## Cells

- `p1` implementer add-reorder-quantity k0: **fail**; red 1 / green 3 attempt(s); halted at green; errors: schema; 900 s
- `p1` implementer add-shelf-code k0: **pass**; red 1 / green 1 attempt(s); verdict PASS; 107 s
- `p1` implementer add-tip-amount k0: **pass**; red 1 / green 1 attempt(s); verdict PASS; 143 s
- `j1` judge add-late-fee k0: **pass**; verdict NEEDS_HUMAN (expected NEEDS_HUMAN), 2 finding(s); worst major; 5 s
- `j1` judge add-shelf-code k0: **pass**; verdict PASS (expected PASS), 0 finding(s); 5 s
- `j1` judge add-tip-amount k0: **fail**; verdict NEEDS_HUMAN (expected PASS), 1 finding(s); worst minor; 5 s

## Invalid cells (not in any rate)

- `p1` implementer add-late-fee k0: rate_limited
