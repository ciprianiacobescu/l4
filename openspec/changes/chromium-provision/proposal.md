# Runners install Chromium when the e2e gate uses Playwright

## Why

A consumer repository's first unit with an e2e gate failed verification (`test_health_reports_ok[chromium]`) although
its server answered: the hosted runner had no Chromium in L4's shared browser cache. `l4 doctor --ci` reported it
(ENV-007: `no Chromium under …/shared/ms-playwright: UI tests cannot run`) but has no fix for it, and the gate sandbox
mounts that cache read-only, so a `gates.setup` command cannot fill it [V, consumer run log and code: ENV-007 has no
`attach_fix`]. The consumer added its own step to the rendered `l4.yml` (`uvx --from playwright==1.63.0 playwright
install chromium` with `PLAYWRIGHT_BROWSERS_PATH`). `l4 upgrade` renders that file from the configuration with no
place for an extra step [V, `upgrade._plan_action` → `render_github_action_ci`], so the next pin move would drop the
step and break the e2e gate again; the repository stays on an old pin to keep it.

`l4 doctor --ci --fix`, which the rendered workflow runs before every `l4` command, already installs the agent CLIs,
OpenSpec and Laya user-locally (L4-DOC-002, L4-ADO-019). Chromium is one more such tool.

## What Changes

- Runner provisioning installs the Chromium that the pinned Playwright (`PLAYWRIGHT_VERSION`) wants into the shared
  browser cache (`<cache root>/shared/ms-playwright`, where the gate sandbox mounts it) whenever the e2e gate is set and
  Playwright is on (`gates.e2e.command` and `verifier.playwright.enabled`, `auto` following the gate), user-locally with
  `uv tool run --from playwright==<pin> playwright install chromium`. Without an e2e gate nothing is installed.
- ENV-007 gets that install as its `--fix`, so `l4 doctor --ci --fix` fills the cache and ENV-007 passes in the same
  run. Its hint names the system packages (`playwright install-deps chromium`), which need root and stay a person's
  step (L4-PRV-006).
- `doctor --fix` on a laptop does the same (the cache under `~/.cache/l4` unless `L4_CACHE` or `XDG_CACHE_HOME` say
  otherwise).

## Impact

- Code: `l4.provision.catalog` (`required_tools`, `ToolSpec.kind`, `manual_command`), `l4.provision.runner`
  (`installed_version`, `is_satisfied`), `l4.provision.install` (`_install`, `_verified`), `l4.doctor.checks_memory`
  (ENV-007's hint) and `l4.doctor.checks_provision` (the fix attached to ENV-007).
- A consumer that added its own Chromium step can delete it and move its pin.
- Out of scope: a CI cache of the browsers (each hosted run downloads Chromium once, as the consumer's own step did);
  the system packages (root).
- Docs: L4-ADO-020, the ENV-007 row of the doctor table, SCN-ADO-57 and SCN-ADO-58, change-table row 78, CHANGELOG.
