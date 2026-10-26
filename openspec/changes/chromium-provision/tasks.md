## 1. Chromium in runner provisioning (L4-ADO-020)

- [x] 1.1 Tests first, new file `tests/unit/provision/test_chromium.py`, modelled on `tests/unit/provision/test_laya.py`
  (its `paths`, `env`, `install_fake` fixtures and the fake runner that records argv and answers by command; read
  `tests/unit/provision/conftest.py` and `_install_helpers.py` first; nothing is downloaded):
  - `test_chromium_is_planned_only_with_a_playwright_e2e_gate`: `required_tools` names `chromium` for
    `gates.e2e.command: "npx playwright test"` (Playwright `auto`), not for an empty e2e command, not when
    `verifier.playwright.enabled: false`; it comes after `uv`.
  - `test_a_cached_browser_is_already_present`: the fake dry run (`uv tool run --from playwright==<pin> playwright
    install --dry-run chromium`, `PLAYWRIGHT_BROWSERS_PATH` set to `<cache>/shared/ms-playwright`) prints two
    `Install location:` lines whose directories exist → `plan_fixes` gives `already present` for `chromium` and
    `install_planned` runs no `playwright install chromium`.
  - `test_a_missing_browser_is_installed_into_the_shared_cache`: the dry run names a directory that does not exist;
    the fake install creates it → the action is `applied`; the recorded argv is `[<uv>, "tool", "run", "--from",
    "playwright==<pin>", "playwright", "install", "chromium"]` with `PLAYWRIGHT_BROWSERS_PATH` = the folder; the folder
    was created; the action's `target` is the folder.
  - `test_an_install_that_leaves_the_browser_missing_fails_with_the_manual_command`: the fake install creates nothing
    → `failed`, the message holds the manual command (`PLAYWRIGHT_BROWSERS_PATH=… uvx --from playwright==<pin>
    playwright install chromium`).
  - `test_no_uv_fails_the_chromium_install`: no uv → `failed` with `uv is not available`.
  - `test_self_provision_off_skips_it`: `allow_install=False` → `skipped`.
  Then implement design D1 to D4 in `src/l4/provision/catalog.py`, `src/l4/provision/runner.py`,
  `src/l4/provision/install.py` and `src/l4/config/defaults.py` (`playwright_browsers_dir`), and point ENV-007's
  `playwright_browsers(ctx)` at the same helper (keeping `repo=ctx.repo` for the check of `cache_root`). Run
  `tests/unit/provision` and `tests/unit/doctor/test_checks_memory.py`.
  - Result: done. New `tests/unit/provision/test_chromium.py` (9 tests with the two `no_e2e_gate` cases) and a `ChromiumRunner` double in `_install_helpers.py`. Red on the unchanged code (7 failed, 2 passed): `test_chromium_is_planned_only_with_a_playwright_e2e_gate` (`assert ['uv'] == ['uv', 'chromium']`), the other six (`actions["chromium"]` / `plan[...]["chromium"]`, `KeyError: 'chromium'`): `test_a_cached_browser_is_already_present`, `test_a_listed_directory_that_is_missing_is_not_present`, `test_a_missing_browser_is_installed_into_the_shared_cache`, `test_an_install_that_leaves_the_browser_missing_fails_with_the_manual_command`, `test_no_uv_fails_the_chromium_install`, `test_self_provision_off_skips_it`. Guards that pass before and after: `test_no_e2e_gate_plans_no_chromium_action` (both cases). Implemented: `playwright_browsers_dir`, `BROWSER_LOCATION` and `playwright_enabled` in `l4.config.defaults` (the last moved there because `l4.verifier.playwright` imports `l4.provision.catalog` through the gates, so the catalog could not import it back; `l4.verifier.playwright.playwright_enabled` stays importable), `ToolSpec` kind `chromium` with `required_tools` and `manual_command` (the folder of the process environment), `chromium_installed`, `installed_target` and the `chromium` branch of `installed_version` and `is_satisfied` in `runner.py`, `_install_chromium` in `install.py`, and `ENV-007`'s `playwright_browsers` and `_wanted_browsers` on the shared helper and regex. The real `uv tool run --offline --from playwright==1.63.0 playwright install --dry-run chromium` output was read once on the development machine (wheel cached, nothing downloaded): the two locations match `BROWSER_LOCATION`, the ffmpeg one does not.

- [x] 1.2 Tests first, in `tests/unit/doctor/test_checks_memory.py` (next to `test_env_007_playwright_browsers`):
  ENV-007's failing results carry the new hint (it names `l4 doctor --ci --fix` and
  `sudo npx -y playwright@<pin> install-deps chromium`); and in the doctor fix tests (find where `INSTALL_FIX` is
  asserted to be attached to ENV-001/003/004/015, e.g. `grep -rn "ENV-015" tests/unit/doctor tests/unit/provision`),
  that ENV-007 has the same fix. Then design D4 (hint) and D5 (attach). Run `tests/unit/doctor` and
  `tests/unit/provision`.
  - Result: done. Red on the unchanged code (3 failed): `test_env_007_failures_name_the_doctor_fix_and_the_root_step` (`assert ('l4 doctor --fix' in 'prereqs.sh --with-playwright')`), `test_the_install_fix_hangs_on_env_001_003_004_and_007_as_one_fix` (`assert all(f is checks_provision.INSTALL_FIX for f in fixes)`), and `test_ci_fix_installs_chromium_and_env_007_passes_in_the_same_run` (the chromium action stayed `('planned', 'missing')`: `--ci --fix` only surveys when no failing check carries the fix). Guards that pass before and after: the first assertion of the last test (ENV-007 `fail` before the fix), the ENV-007 tests of `test_checks_memory` and the other fix-attachment tests. Done: `CHROMIUM_FIX` hint in `checks_memory.py` on both failing results, `checks_provision.py` imports `checks_memory` (it is loaded after `checks_provision` in `CHECK_MODULES`) and attaches `INSTALL_FIX` to ENV-007.

- [x] 1.3 Docs:
  - `docs/SPEC.md`: after L4-ADO-019 (the paragraph that ends "Without such a profile, nothing is installed or
    cached."), add `**L4-ADO-020** Runners install Chromium when the e2e gate uses Playwright.` with the requirement of
    this change's spec delta (when, where, how, present, not planned, ENV-007's fix and hint), in the voice of
    L4-ADO-019.
  - `docs/SPEC.md`, the doctor table row `| ENV-007 | warn | Playwright + browsers (if an e2e gate exists) | — |`: the
    last cell becomes `install the Chromium of the pinned Playwright into the shared browser cache (L4-ADO-020)`.
  - `docs/SPEC.md`: after SCN-ADO-56, `#### SCN-ADO-57 (+) An e2e gate gets its browser from the doctor · L4-ADO-020`
    and `#### SCN-ADO-58 (−) No e2e gate, no browser · L4-ADO-020`, Given/When/Then as the scenarios of the spec delta
    (the cached-browser case may go into SCN-ADO-57's Then as a second run that installs nothing).
  - `docs/SPEC.md` change table: row 78 `chromium-provision` after row 77, in the form of rows 76 and 77 (what changed;
    the cause: a consumer's e2e gate found no Chromium on a hosted runner, ENV-007 had no fix, and the step the
    consumer added to the rendered workflow is dropped by `l4 upgrade`; the requirements; the folder; checked by
    `test_chromium`, `test_checks_memory`, and a consumer e2e gate on a hosted runner with no added step).
  - `CHANGELOG.md`: `## 0.4.35 (unreleased)` above `## 0.4.34 (2026-10-26)`, `### Added`: `l4 doctor --fix` and
    `--ci --fix` install the Chromium of the pinned Playwright into the shared browser cache when the e2e gate uses
    Playwright (ENV-007 now has a fix), so a repository needs no Chromium step of its own in the rendered workflow,
    which `l4 upgrade` would drop (L4-ADO-020).
  - `docs/runbook.md` or the adoption docs: if a page tells a GitHub consumer to add a Chromium step or to run
    `prereqs.sh --with-playwright` on a hosted runner, say that `l4 doctor --ci --fix` does it now (grep
    `with-playwright`, `ms-playwright`, `ENV-007` in `docs/` and `plugins/l4/skills/`; change only what says otherwise).
  Run `uv run python scripts/check_spec.py docs/SPEC.md` and `uv run pytest tests/unit/docs -q`.
  - Result: done. L4-ADO-020 after L4-ADO-019, the ENV-007 row, SCN-ADO-57 (second run installs nothing) and SCN-ADO-58, change-table row 78, CHANGELOG `## 0.4.35 (unreleased)`. No page in `docs/`, `docs/runner/README.md` or the plugin skills tells a GitHub consumer to add a Chromium step (the PRQ-14 row of `docs/runner/README.md` describes `prereqs.sh --with-playwright` on a self-hosted runner, which stays true), so nothing else changed. `check_spec.py` exit 0; `tests/unit/docs` and `test_release_notes` pass.
