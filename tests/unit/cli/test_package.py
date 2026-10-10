import subprocess
import sys

import l4
from l4.cli import main


def test_version_flag_prints_version(capsys):
    assert main(["--version"], environ={}) == 0
    assert l4.__version__ in capsys.readouterr().out


def test_python_dash_m_runs_the_cli():
    done = subprocess.run(
        [sys.executable, "-m", "l4", "--version"], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0
    assert l4.__version__ in done.stdout


def test_version_matches_distribution_metadata():
    from importlib.metadata import version

    assert version("l4harness") == l4.__version__
