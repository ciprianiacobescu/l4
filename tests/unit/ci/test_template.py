import yaml

from l4.ci.github import doctor_command
from l4.ci.render import render_gitlab_ci
from l4.config.schema import L4Config


def test_first_line_is_doctor_ci_fix():
    first = yaml.safe_load(render_gitlab_ci())["l4"]["script"][0]
    assert first == ".l4/bin/l4 doctor --ci --fix ${L4_ADOPTION_CHECK:+--adoption} || .l4/bin/l4 ci map-exit $?"
    # the static line is what the run-time decision gives on a default GitLab config, plus the adoption check
    assert first.startswith(f".l4/bin/l4 {doctor_command(L4Config(), 'gitlab')} ${{L4_ADOPTION_CHECK:+--adoption}} ||")


def run_doctor_line(tmp_path, **env: str) -> list[str]:
    """The template's first script line under `sh -c`, with a stub `.l4/bin/l4` that prints its argv, one per line."""
    import os
    import subprocess

    bin_dir = tmp_path / ".l4" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "l4"
    stub.write_text('#!/bin/sh\nfor a in "$@"; do echo "$a"; done\n')
    stub.chmod(0o755)
    line = yaml.safe_load(render_gitlab_ci())["l4"]["script"][0]
    done = subprocess.run(
        ["sh", "-c", line], cwd=tmp_path, env={"PATH": os.environ["PATH"], **env}, capture_output=True, text=True,
        check=True,
    )  # fmt: skip
    return done.stdout.split("\n")[:-1]


def test_doctor_line_adds_adoption_only_from_a_non_empty_variable(tmp_path):
    """M1.8 A3: the runner-side GATE-001 is switched on by a pipeline variable; its value is only tested for being
    non-empty, never put on the command line, so a variable cannot inject flags."""
    assert run_doctor_line(tmp_path) == ["doctor", "--ci", "--fix"]
    assert run_doctor_line(tmp_path, L4_ADOPTION_CHECK="") == ["doctor", "--ci", "--fix"]
    assert run_doctor_line(tmp_path, L4_ADOPTION_CHECK="1") == ["doctor", "--ci", "--fix", "--adoption"]
    hostile = run_doctor_line(tmp_path, L4_ADOPTION_CHECK="1 --live; touch pwned")
    assert hostile == ["doctor", "--ci", "--fix", "--adoption"] and not (tmp_path / "pwned").exists()
