"""Two small helpers of the setup action (adoption-kit L4-ACT-002, L4-ACT-003): the cache key of the agent CLIs, and
the runner setup script rendered by the installed harness."""

import sys
from typing import TYPE_CHECKING

from l4.ci.render import render_setup
from l4.exitcodes import ExitCode
from l4.outcome import CommandResult
from l4.provision.catalog import catalog_hash

if TYPE_CHECKING:
    from l4.context import AppContext

CACHES = ("clis",)


def run_cache_key(app: "AppContext", *, cache: str) -> CommandResult:
    """`l4 ci cache-key clis`: the key suffix of the agent-CLI cache, made from the catalog's pins only."""
    if cache not in CACHES:
        print(f"l4: unknown cache {cache!r}; the caches with a key here are: {', '.join(CACHES)}", file=sys.stderr)
        return CommandResult(ExitCode.USAGE_ERROR)
    print(catalog_hash())
    return CommandResult(ExitCode.OK)


def run_render_setup(app: "AppContext") -> CommandResult:
    """`l4 ci render-setup`: print `l4-setup.sh` with the catalog's uv pinned in, for `bash`."""
    sys.stdout.write(render_setup())
    return CommandResult(ExitCode.OK)
