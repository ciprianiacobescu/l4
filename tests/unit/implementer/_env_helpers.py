"""Shared pieces of the environment-plant tests (L4-SEC-035..037): a setup command that builds a REAL venv the way
`uv sync --frozen` does (idempotent: it never removes a file that belongs to no distribution), and the files the
reviewer's reproduction plants."""

import sys
import textwrap

from l4.specs.base import Task

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 3, 3)
HOST_SITE = next(p for p in sys.path if p.endswith("site-packages"))
SITE = f".venv/lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
MKREALVENV = textwrap.dedent(
    f"""\
    import glob, os, subprocess, sys
    if not os.path.exists(".venv/bin/python"):
        subprocess.run([sys.executable, "-m", "venv", "--without-pip", ".venv"], check=True)
    site = glob.glob(".venv/lib/python3*/site-packages")[0]
    with open(os.path.join(site, "_host.pth"), "w") as handle:
        handle.write({HOST_SITE!r} + "\\n")
    """
)
PTH = "import os; os.environ['PYTEST_PLUGINS'] = 'l4plant'\n"
PLUGIN = textwrap.dedent(
    """\
    import pytest


    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(item, call):
        outcome = yield
        report = outcome.get_result()
        if report.failed:
            report.outcome, report.longrepr = "passed", None
    """
)
# a setup command that builds a node_modules the way `npm ci` leaves one: a package with a file in it
MKNODE = textwrap.dedent(
    """\
    import os
    os.makedirs("node_modules/vitest/dist", exist_ok=True)
    with open("node_modules/vitest/dist/index.js", "w") as handle:
        handle.write("export const real = true;\\n")
    """
)
