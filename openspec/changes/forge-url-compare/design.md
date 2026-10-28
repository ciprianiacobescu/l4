# Design: compare the pull request link in both forms

## D1. `canonical`, not the number or an unredacted copy

- Comparing numbers needs a parser per forge (`/pull/N`, `/-/merge_requests/N`) and drops the repository part.
- Storing the link unredacted breaks L4-OBS-002 and would put the host into the plan ledger (`unit.merged{pr}` takes
  the stored link when a person merged).
- Expanding `<forge>` on read does nothing when the web base is unknown and does not match an old ledger that holds the
  full link. `canonical` scrubs both sides and matches both, and it is what the sweeper (`ci/sweeper.py`) and the
  archive already use.

## D2. Scope

Only the log line changes. Whether a link mismatch should stop the merge is not decided here.
