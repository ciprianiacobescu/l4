"""The files `l4 init` writes for CI: the GitLab include template (forge-and-ci 1.15) and the shim every job line starts
(1.14, the vendor branch only).

M1: forge-and-ci 1.14's `uvx --from git+URL@SHA` branch waits for SPEC Q1; 1.16/1.17 `l4-detect`, child pipelines and
`l4 ci render`; 1.12/1.18 linting of the rendered YAML.
"""

import re
from importlib.resources import files

from l4.config.schema import L4Config
from l4.provision.catalog import UV_VERSION
from l4.vcs.names import check_branch_prefix, valid_base_branch

TEMPLATE_RELPATH = ".l4/ci/l4.gitlab-ci.yml"
SHIM_RELPATH = ".l4/bin/l4"
SETUP_RELPATH = ".l4/bin/l4-setup"
VENDOR_RELPATH = ".l4/vendor"
# the interpreter the vendored harness runs on (L4-PRV-025): the version checks.yml and scripts/runner/prereqs.sh use
HARNESS_PYTHON = "3.12"
INCLUDE_SNIPPET = f"include:\n  - local: {TEMPLATE_RELPATH}\n"

# `--frozen` runs the vendored uv.lock as it is (never relocks the tracked file), `--no-dev` leaves pytest and ruff
# out, `--python` pins the interpreter (a bare image's system Python may be older, uv's newest may be too new);
# ~/.local/bin is where the runner's uv lives (runner-provisioning PRQ-05).
_SHIM = f"""#!/bin/sh
# Starts the vendored l4 harness. Run it from the repository root, as the CI template does.
PATH="$HOME/.local/bin:$PATH"
export PATH
if ! command -v uv >/dev/null 2>&1; then
  echo "l4: uv was not found on PATH or in ~/.local/bin; install uv first" >&2
  exit 3
fi
exec uv run --frozen --no-dev --python {HARNESS_PYTHON} --project {VENDOR_RELPATH} l4 "$@"
"""

# The fetched harness (github-parity L4-GHP-010, D10): no vendored copy; `uvx` builds the harness from the pinned commit
# (uv caches the tool environment by commit, so a warm cache fetches nothing). The pins are read from the `harness:`
# block of `.l4/config.yaml` with awk alone (L4-INS-005: one place), no Python and no yq, since neither is there yet.
_FETCHED_SHIM = """#!/bin/sh
# Starts the l4 harness fetched at the commit pinned in .l4/config.yaml. Run it from the repository root.
PATH="$HOME/.local/bin:$PATH"
export PATH
config=".l4/config.yaml"
# the value of a scalar key of the top-level `harness:` block: quotes and a trailing comment are dropped
pin() {
  awk -v key="$1" '
    BEGIN { sq = sprintf("%c", 39); dq = sprintf("%c", 34) }
    /^harness:[ \t]*(#.*)?$/ { inside = 1; next }
    inside && /^[^ \t#]/ { inside = 0 }
    inside && match($0, "^[ \t]+" key ":") {
      v = substr($0, RLENGTH + 1)
      sub(/^[ \t]+/, "", v)
      if (substr(v, 1, 1) == dq) { v = substr(v, 2); sub(dq ".*$", "", v) }
      else if (substr(v, 1, 1) == sq) { v = substr(v, 2); sub(sq ".*$", "", v) }
      else { sub(/[ \t]*#.*$/, "", v); sub(/[ \t]+$/, "", v) }
      print v
      exit
    }
  ' "$config" 2>/dev/null
}
repository=$(pin repository)
commit=$(pin commit)
if [ -z "$repository" ]; then
  echo "l4: $config harness.repository is empty or missing; the fetched harness needs it" >&2
  exit 3
fi
case $commit in
  *[!0-9a-f]*) commit="" ;;
esac
if [ "${#commit}" -ne 40 ]; then
  echo "l4: $config harness.commit must be exactly 40 lowercase hex characters (the harness commit to fetch)" >&2
  exit 3
fi
if ! command -v uvx >/dev/null 2>&1; then
  echo "l4: uvx was not found on PATH or in ~/.local/bin; install uv first" >&2
  exit 3
fi
exec uvx --python @@PYTHON@@ --from "git+${repository}@${commit}" l4 "$@"
""".replace("@@PYTHON@@", HARNESS_PYTHON)


def _gitlab_regex(text: str) -> str:
    """`text` as the body of a GitLab `/.../` regex literal: every metacharacter and the `/` delimiter escaped."""
    return re.sub(r"([/.\\^$*+?()\[\]{}|])", r"\\\1", text)


def render_gitlab_ci(cfg: L4Config | None = None) -> str:
    """The GitLab job (L4-OPS-016): the configured `forge.base_branch` and `forge.branch_prefix` are written into the
    rules and the `L4_BASE_BRANCH` variable the base checkout reads, so a base that is not the project's default
    branch works. ValueError for a base or prefix that is not safe to write into YAML (nothing is rendered)."""
    forge = (cfg or L4Config()).forge
    if not valid_base_branch(forge.base_branch):
        raise ValueError(f"not a usable base branch: {forge.base_branch!r}")
    check_branch_prefix(forge.branch_prefix)
    text = files("l4.ci").joinpath("templates", "l4.gitlab-ci.yml").read_text(encoding="utf-8")
    return text.replace("@@BASE@@", forge.base_branch).replace("@@PREFIX_RE@@", _gitlab_regex(forge.branch_prefix))


def render_shim() -> str:
    return _SHIM


def render_fetched_shim() -> str:
    return _FETCHED_SHIM


def render_setup() -> str:
    """`.l4/bin/l4-setup` (L4-PRV-020): bash, run before the shim; uv's pin is the catalog's."""
    text = files("l4.ci").joinpath("templates", "l4-setup.sh").read_text(encoding="utf-8")
    return text.replace("@@UV_VERSION@@", UV_VERSION)
