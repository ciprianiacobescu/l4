# Commands that read a unit's state fetch first, also on a person's computer

## Why

`l4 status`, `l4 plan`, `l4 resume`, `l4 run` (with or without `--unit`) and `l4 run --dry-run` fold the unit branches,
the lock refs and the plan refs, but fetch them only in a CI job (`refresh_in_ci`, src/l4/vcs/refresh.py) [V]. On a
person's computer they read whatever the last `git fetch` left: a spec edit a person pushed from another computer, a
run's ledger, a merged or deleted branch, the plan's progress. L4-OPS-014 even says so ("`l4 run --unit` outside CI
does not fetch, so a stale ref can miss a remote spec edit; `l4 retry` fetches"), and the runbook tells people to use
`l4 retry` instead. `l4 retry`, `l4 restart`, `l4 questions` and the plan commands already fetch locally
(`fetch_unit_refs`). This is item 4 of phase 1 of the local-runs proposal, deferred from 0.4.44 because it reverses
L4-OPS-014's last sentence and SCN-CLI-12's "the refresh does not fetch as a job does".

## What changes

- The refresh of refs runs outside a CI job too: the unit branches and the lock refs with `--prune`, and the plan
  refs, once per process, with the credentials `fetch_unit_refs` uses (`fetch_auth_config` with the origin URL). A
  checkout without an `origin` remote is not fetched (today's rule).
- Every command that refreshes takes `--no-fetch`: then nothing is fetched and the local refs are read, as today.
- A failed local fetch: `l4 status` warns once (`could not refresh from the forge (<reason>); showing local refs`) and
  shows the local refs, whatever the git error (a laptop may be offline); `plan`, `resume`, `run` and `run --dry-run`
  stop (L4-CLI-003: they must not read stale refs) with the reason and `--no-fetch` named as the way to read the local
  refs. In a CI job nothing changes (only `status` tolerates a refused job token; no `--no-fetch` default).
- The sandbox preflight of a local `run` stays before the refresh (L4-SEC-041).

## Impact

- Code: `l4.vcs.refresh` (the refresh outside CI), `l4.state.status.refresh_refs` (the failure rules, the flag), its
  callers (`state/status.py`, `planner.py`, `orchestrator.run_command`, `sim/dryrun.py`, `state/resume.py`,
  `state/retry.py`, `state/restart.py`), `l4.cli` (`--no-fetch` on `status`, `plan`, `resume`, `run`).
- Spec: L4-CLI-005 added; L4-CLI-003, L4-CLI-004 and L4-OPS-014 amended; SCN-CLI-12 amended; SCN-CLI-15 to SCN-CLI-19
  added; change-table row 102. Runbook §11 (`l4 run --unit` on your computer does not fetch) and the module docstring.
- Not in this change: the other phases of the local-runs proposal (a local run that takes no plan step without
  `--plan-step`, a local hold, `forge.token_command`, container mode).
