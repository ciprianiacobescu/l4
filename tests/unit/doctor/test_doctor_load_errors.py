"""SCN-CFG-05: `l4 doctor` exits 2 with the judge role text when the configuration does not load."""

from pathlib import Path

import pytest

from l4.cli import main

TEXT = "profiles.kiro is in roles.judges, but its adapter kiro-cli cannot judge"


def test_doctor_exits_2_with_the_judge_role_text(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    (tmp_path / ".l4").mkdir()
    (tmp_path / ".l4" / "config.yaml").write_text(
        "profiles:\n  kiro: {adapter: kiro-cli}\n  claude: {adapter: claude-code}\nroles: {judges: [kiro, claude]}\n",
        encoding="utf-8",
    )
    code = main(["doctor", "--repo", str(tmp_path)])
    err = capsys.readouterr().err
    assert code == 2
    assert TEXT in err and "remove kiro from roles.judges at $" in err
