Every task follows these rules:
- Write the named tests first and see them fail, then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`. Then `ruff check .`,
  `ruff format --check` on the files that changed, and `python scripts/check_spec.py docs/SPEC.md`.
- Never wait on a process with `while pgrep -f ...`; never run tests in the background. Stage explicit paths only.
- Name a consumer "a consumer repository".

## 1. Configuration (L4-YOLO-032, L4-YOLO-033)

- [x] 1.1 Tests in `tests/unit/config/` for `yolo.merge`: defaults `squash` / `true`, `fast-forward` accepted, an
  unknown method or key refused with the loader's message.
- [x] 1.2 `YoloMergeCfg` in `src/l4/config/schema.py`, `YoloCfg.merge`; SPEC §3.2 `yolo:` block lines.

## 2. Forge merge call (D2)

- [x] 2.1 Contract tests of the request shape and answer mapping for GitHub and GitLab (`merged`, `head_moved` on 409,
  `refused` on 405/406/422 with the message), and `LocalForge.merge_pr` (squash commit with the head's tree on the target
  tip, PR merged with `merge_commit_sha`); GitLab `_pr` falls back to `squash_commit_sha`.
- [x] 2.2 `MergeCall`, `Forge.merge_pr` in `forge/base.py`; GitHub, GitLab and local implementations.

## 3. Squash in the guarded merge (D3, D4, D5)

- [x] 3.1 Tests (SCN-YOLO-76, 77, 78, 79, 80, 81) in `tests/unit/yolo/` with `LocalForge`.
- [x] 3.2 `merge_guarded` takes the method; squash path, message, race check; `MergeOutcome.landed`/`raced`;
  `confirm_merged` on `landed`; `cycle._merge` records `merge_commit=landed`, `method`, `raced`; `_integrate` on
  `landed`; receipts and `report.py` read `merge_commit`.

## 4. Branch deletion (D6, D7, D8)

- [ ] 4.1 First: a test on a local bare repository of `delete_branch` (lease matches → gone; a stranger's push moved the
  tip → kept) and `keep_ref`. Then SCN-YOLO-82, 83, 84, 85 and the archive-branch delete after `archive.merged`.
- [ ] 4.2 `vcs/push.py` `delete_branch`, `keep_ref`; the unit-branch delete after the merge in `cycle._merge`; the
  cleanup of earlier merges in the plan step; the archive-branch delete in the sweeper after `archive.merged`; the events.

## 5. Links and docs

- [ ] 5.1 `archive.py` links `verification.md` at the head sha (test).
- [ ] 5.2 `docs/SPEC.md`: L4-YOLO-008 (the method), L4-YOLO-032, L4-YOLO-033, SCN-YOLO-76..85, SCN-YOLO-14 says
  `method: fast-forward`, L4-ARC-003 and SCN-ARC-04 corrected to what the code does (no WIP-branch deletion; the lock ref
  moves to `refs/l4/archived/…`), L4-OPS-009 (a branch deleted after a merge is normal), the change row.
  `docs/yolo-mode.md`, `docs/runbook.md` (a refused squash: set `yolo.merge.method: fast-forward`; §7.13), CHANGELOG.
