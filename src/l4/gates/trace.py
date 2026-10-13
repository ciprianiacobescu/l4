"""The environment that loads the `l4_trace` pytest plugin (M13-G2) into every gate run and agent run.

The plugin directory is taken from the installed package, never from the repository under test, so that it also works
from `.l4/vendor/.venv/.../site-packages` and a repository cannot shadow it.
"""

from importlib import resources
from pathlib import Path

PLUGIN_MODULE = "l4_trace"


def plugin_dir() -> Path:
    return Path(str(resources.files("l4.gates").joinpath("pytest_trace")))


def trace_env(test_timeout_s: int = 0) -> dict[str, str]:
    """`test_timeout_s` > 0 also sets the plugin's per-test limit (`gates.test_timeout`, SPEC L4-GAT-004)."""
    env = {"PYTEST_ADDOPTS": f"-p {PLUGIN_MODULE}", "PYTHONPATH": str(plugin_dir())}
    return {**env, "L4_TEST_TIMEOUT_S": str(test_timeout_s)} if test_timeout_s > 0 else env
