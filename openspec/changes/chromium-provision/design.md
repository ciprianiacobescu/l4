# Design: Chromium as a provisioned tool

## D1. When it is needed

`required_tools(cfg, …)` appends `ToolSpec("chromium", "chromium", "playwright", PLAYWRIGHT_VERSION, None)` after the
other tools when `cfg.gates.e2e.command.strip()` and `playwright_enabled(cfg)` (the predicate ENV-007 uses). `uv` is
always first in the list, so it is present before Chromium is installed. If importing `playwright_enabled` from
`l4.verifier.playwright` into `l4.provision.catalog` makes an import cycle, move the function to a module both can
import (for example `l4.config.defaults`) and keep the old name importable from `l4.verifier.playwright`.

## D2. Where, and when it is present

The folder is `playwright_browsers_dir(env) = cache_root(env) / "shared" / "ms-playwright"` (a small helper next to
`cache_root` in `l4.config.defaults`; ENV-007's `playwright_browsers(ctx)` uses `cache_root(ctx.env, repo=ctx.repo)`,
the same path). `installed_version` for kind `chromium`: run `uv tool run --from playwright==<pin> playwright install
--dry-run chromium` with `PLAYWRIGHT_BROWSERS_PATH=<folder>` (the `uv` that `find_tool("uv", …)` finds; no `--offline`,
the probe may fetch the wheel), read the `Install location:` lines with the pattern ENV-007 uses (`_REVISION_DIR`,
moved to a shared place or imported), and return the pin when there is at least one location and each one is an
existing directory; otherwise `None`. No uv, a failed dry run, or no location: `None`. `is_satisfied` treats kind
`chromium` like `openspec` and `laya` (the found version equals the pin).

## D3. Install and verify

`_install` calls `_install_chromium(ctx, tool)`: no uv → `InstallFailed("uv is not available: install uv first")`;
create the folder (`parents=True, exist_ok=True`); run `_checked(ctx, [uv, "tool", "run", "--from",
f"playwright=={tool.version}", "playwright", "install", "chromium"], env={**ctx.clean, "PLAYWRIGHT_BROWSERS_PATH":
str(folder)})`. `_verified` needs no change beyond what `installed_version` and `is_satisfied` give (it raises when the
dry run still lists a missing directory). The FixAction's `target` for Chromium is the folder (the other tools name a
binary; `find_tool("playwright")` finds nothing): set it in `_apply` and in `plan_fixes`'s `already present` branch
for this kind.

## D4. Manual command and the hint

`manual_command` for kind `chromium`: `PLAYWRIGHT_BROWSERS_PATH=<folder> uvx --from playwright==<pin> playwright
install chromium` (the folder from `playwright_browsers_dir` of the process environment, `~/.cache/l4/shared/
ms-playwright` by default). ENV-007's failing results get the hint `` `l4 doctor --fix` installs it (on CI runners:
`l4 doctor --ci --fix`); system packages need root: a person runs `sudo npx -y playwright@<pin> install-deps
chromium` `` in place of `prereqs.sh --with-playwright` (prereqs.sh stays a way to do it on a self-hosted runner and
may stay named after it).

## D5. The fix of ENV-007

`checks_provision.py` attaches `INSTALL_FIX` to `ENV-007` as it does to ENV-001, ENV-003, ENV-004 and ENV-015 (the
attach must run after ENV-007 is registered: `checks_memory` is imported before the attach, as `checks_env` is).
`--fix` then runs the provisioning fix when ENV-007 fails and re-runs ENV-007, which passes.

## D6. What stays

ENV-007's check itself, `prereqs.sh`, the gate sandbox's read-only mount, `ci.self_provision` (false: the action is
`skipped`, as for every tool), and the root rule: nothing here runs `sudo` or installs system packages.
