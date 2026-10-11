"""The files `l4 init` writes for CI: the GitLab include template (forge-and-ci 1.15) and the shim every job line starts
(1.14, the vendor branch only).

M1: forge-and-ci 1.14's `uvx --from git+URL@SHA` branch waits for SPEC Q1; 1.16/1.17 `l4-detect`, child pipelines and
`l4 ci render`; 1.12/1.18 linting of the rendered YAML.
"""

from importlib.resources import files

from l4.provision.catalog import UV_VERSION

TEMPLATE_RELPATH = ".l4/ci/l4.gitlab-ci.yml"
SHIM_RELPATH = ".l4/bin/l4"
SETUP_RELPATH = ".l4/bin/l4-setup"
VENDOR_RELPATH = ".l4/vendor"
INCLUDE_SNIPPET = f"include:\n  - local: {TEMPLATE_RELPATH}\n"

# `--frozen` runs the vendored uv.lock as it is (never relocks the tracked file), `--no-dev` leaves pytest and ruff
# out; ~/.local/bin is where the runner's uv lives (runner-provisioning PRQ-05).
_SHIM = f"""#!/bin/sh
# Starts the vendored l4 harness. Run it from the repository root, as the CI template does.
PATH="$HOME/.local/bin:$PATH"
export PATH
if ! command -v uv >/dev/null 2>&1; then
  echo "l4: uv was not found on PATH or in ~/.local/bin; install uv first" >&2
  exit 3
fi
exec uv run --frozen --no-dev --project {VENDOR_RELPATH} l4 "$@"
"""


def render_gitlab_ci() -> str:
    return files("l4.ci").joinpath("templates", "l4.gitlab-ci.yml").read_text(encoding="utf-8")


def render_shim() -> str:
    return _SHIM


def render_setup() -> str:
    """`.l4/bin/l4-setup` (L4-PRV-020): bash, run before the shim; uv's pin is the catalog's."""
    text = files("l4.ci").joinpath("templates", "l4-setup.sh").read_text(encoding="utf-8")
    return text.replace("@@UV_VERSION@@", UV_VERSION)
