# The guarded merge compares the unit's pull request link in both forms

## Why

The committed ledger keeps a unit's pull request link with the forge host replaced by `<forge>` (L4-OBS-002, a privacy
measure for committed history), so a unit's folded state holds `<forge>/<owner>/<repo>/pull/<n>`. L4-OBS-002 says that
URL comparisons accept both forms, and the sweeper and the archive compare with `urls.canonical`. The guarded merge's
`_find_pr` (`l4.yolo.merge`) compares the forge's link with the stored one as plain strings, so it logs, on every merge
of every unit [V, a consumer's delivery plan, 2026-10-28]:

    yolo.merge: <unit>: the open pull request https://github.com/<owner>/<repo>/pull/22 is not the unit's <forge>/<owner>/<repo>/pull/22

Today the line is only logged (the pull request the forge found is still used), but it reads as an alarm and hides a
real mismatch, which it would print the same way.

## What changes

- `_find_pr` compares `canonical` of both links (the run's forge URL scrubber, `app_forge_urls`), as the sweeper does;
  the line is logged only when they differ.

## Impact

- Code: `l4.yolo.merge` (`_find_pr` and its callers pass the scrubber).
- Behaviour: no merge decision changes; the false line goes.
- Docs: SCN-YOLO-239, change-table row 83, CHANGELOG 0.4.38.
