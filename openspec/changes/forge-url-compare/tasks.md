## 1. Compare in both forms

- [x] 1.1 Tests first in `tests/unit/yolo/test_yolo_merge_guard.py` (SCN-YOLO-239: stored `<forge>/o/r/pull/7` vs the
  forge's `https://forge.invalid/o/r/pull/7` logs nothing with `caplog`; `<forge>/o/r/pull/8` logs; set
  `GITHUB_SERVER_URL=https://forge.invalid` before the first `app_forge_urls` call, which is cached on `app.redactor`),
  and a github.com `/pull/22` case next to `test_canonical_matches_old_and_new_forms` in
  `tests/unit/forge/test_urls.py`. Then `_find_pr` compares `urls.canonical` of both links, with the scrubber passed in
  from `merge_guarded` (`app_forge_urls(app, cfg)`).
  Result: `_find_pr` compares `canonical` of both links; the new merge-guard test failed before the change and passes now.

## 2. Docs (one pass at the end of the release)

- [x] 2.1 SCN-YOLO-239 after SCN-YOLO-238; change-table row 83 `forge-url-compare`; CHANGELOG 0.4.38 under Fixed.
