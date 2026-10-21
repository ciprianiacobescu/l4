"""SCN-CFG-05: `l4 doctor` exits 2 with the judge role text when the configuration does not load."""

from pathlib import Path

import pytest

from l4.cli import main

TEXT = "profiles.cmd is in roles.judges, but its adapter command cannot judge"


def test_doctor_exits_2_with_the_judge_role_text(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    (tmp_path / ".l4").mkdir()
    (tmp_path / ".l4" / "config.yaml").write_text(
        "profiles:\n  cmd: {adapter: command, options: {argv: [tool]}}\n  claude: {adapter: claude-code}\n"
        "roles: {judges: [cmd, claude]}\n",
        encoding="utf-8",
    )
    code = main(["doctor", "--repo", str(tmp_path)])
    err = capsys.readouterr().err
    assert code == 2
    assert TEXT in err and "remove cmd from roles.judges at $" in err
