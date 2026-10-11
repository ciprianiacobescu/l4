from pathlib import Path

from l4.ci.render import SETUP_RELPATH, render_setup
from l4.cli import main


def test_setup_script_written_and_upgraded(target: Path, harness_repo: Path, git_environ):
    argv = ["init", "--repo", str(target), "--harness", str(harness_repo), "--ci", "github", "--vendor"]
    assert main(argv, environ=git_environ) == 0
    setup = target / SETUP_RELPATH
    assert setup.read_bytes() == render_setup().encode()
    assert setup.stat().st_mode & 0o777 == 0o755

    setup.write_text("#!/bin/sh\n# an old setup\n")
    setup.chmod(0o644)
    upgrade = ["upgrade", "--repo", str(target), "--harness", str(harness_repo)]
    assert main(upgrade, environ=git_environ) == 0
    assert setup.read_bytes() == render_setup().encode()
    assert setup.stat().st_mode & 0o111 != 0
