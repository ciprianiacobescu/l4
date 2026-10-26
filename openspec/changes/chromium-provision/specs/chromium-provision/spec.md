## Purpose

A runner whose repository has a Playwright e2e gate gets the browser that gate needs from `l4 doctor --fix`, so no
consumer has to add a step to the rendered workflow.

## ADDED Requirements

### Requirement: Runner provisioning installs the Chromium the pinned Playwright wants
When `gates.e2e.command` is set and Playwright is on (`verifier.playwright.enabled`, `auto` following the gate),
runner provisioning (`l4 doctor --fix`, `l4 doctor --ci --fix`) SHALL install the Chromium that Playwright
`PLAYWRIGHT_VERSION` wants into `<cache root>/shared/ms-playwright`, user-locally, with `uv tool run --from
playwright==<pin> playwright install chromium` and `PLAYWRIGHT_BROWSERS_PATH` set to that folder. It SHALL count as
present when `playwright install --dry-run chromium` names at least one location and every one is a directory, and
SHALL then install nothing. Without an e2e gate, or with Playwright off, it SHALL NOT be planned. ENV-007's `--fix`
SHALL be this install, and its hint SHALL name the system packages as a step a person with root runs.

#### Scenario: an e2e gate gets its browser
- **WHEN** `gates.e2e.command` is set, Playwright is `auto`, the browser folder is empty and `l4 doctor --ci --fix` runs
- **THEN** the provisioning fix runs `uv tool run --from playwright==<pin> playwright install chromium` with
  `PLAYWRIGHT_BROWSERS_PATH` set to the folder, and ENV-007 passes after the fix

#### Scenario: a cached browser is not installed again
- **WHEN** every location the dry run names is a directory
- **THEN** the action is `already present` and nothing is run but the dry run

#### Scenario: no e2e gate, no browser
- **WHEN** `gates.e2e.command` is empty
- **THEN** no Chromium action is planned
