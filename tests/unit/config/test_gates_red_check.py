"""L4-CFG-007 (SCN-CFG-08..12): `gates.test.red_check` and the load rule of `gates.test.targeted`."""

from pathlib import Path

import pytest

from l4.config.loader import ConfigSchemaError, load_config
from l4.exitcodes import ExitCode

VITEST = "npx vitest run --reporter=junit --outputFile=.l4-out/junit.xml {files}"


def load(tmp_path: Path, test: str):
    path = tmp_path / ".l4" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"version: 1\ngates:\n  test:\n{test}", encoding="utf-8")
    return load_config(tmp_path)


def refused(tmp_path: Path, test: str) -> ConfigSchemaError:
    with pytest.raises(ConfigSchemaError) as err:
        load(tmp_path, test)
    assert err.value.code is ExitCode.USAGE_ERROR
    return err.value


def test_scn_cfg_08_a_command_that_holds_files_loads_and_the_default_is_full(tmp_path: Path):
    cfg = load(tmp_path, f"    command: npm test\n    red_check: targeted\n    targeted: {VITEST}\n")
    assert cfg.gates.test.red_check == "targeted" and cfg.gates.test.targeted == VITEST
    assert load(tmp_path, "    command: npm test\n").gates.test.red_check == "full"
    assert load(tmp_path, "    command: npm test\n    red_check: full\n").gates.test.red_check == "full"


@pytest.mark.parametrize("targeted", ["", "targeted: ''\n"])
def test_scn_cfg_09_no_command_does_not_load_and_names_both_keys(tmp_path: Path, targeted: str):
    err = refused(
        tmp_path, "    command: npm test\n    red_check: targeted\n" + (f"    {targeted}" if targeted else "")
    )
    text = str(err)
    assert "gates.test.red_check" in text and "gates.test.targeted" in text
    assert err.issues and err.issues[0].path.startswith("$.gates.test")


@pytest.mark.parametrize(
    "command",
    [
        "npx vitest run SECRETWORD --include={files}",
        "npx vitest run SECRETWORD {files} {files}",
        "npx vitest run SECRETWORD {grep}",
        "npx vitest run SECRETWORD",
        "npx vitest run SECRETWORD 'unbalanced {files}",
        "npx vitest run SECRETWORD {files} -t {grep}x",
        "npx vitest run SECRETWORD x{files}",
    ],
)
def test_scn_cfg_10_files_must_be_one_word_once_and_grep_is_refused(tmp_path: Path, command: str):
    err = refused(tmp_path, f'    command: npm test\n    red_check: targeted\n    targeted: "{command}"\n')
    text = str(err)
    assert "gates.test.red_check" in text and "gates.test.targeted" in text
    assert "SECRETWORD" not in text and "vitest" not in text  # the command is never echoed


def test_scn_cfg_10_each_rule_gives_its_own_message(tmp_path: Path):
    texts = set()
    for command in ("a --include={files}", "a {files} {files}", "a {grep}", "a", "a 'b {files}"):
        err = refused(tmp_path, f'    command: x\n    red_check: targeted\n    targeted: "{command}"\n')
        texts.add(err.issues[0].message)
    assert len(texts) == 5


def test_scn_cfg_11_full_does_not_read_the_targeted_command(tmp_path: Path):
    assert load(tmp_path, "    command: x\n    targeted: 'pytest {grep}'\n").gates.test.red_check == "full"
    cfg = load(tmp_path, '    command: x\n    red_check: full\n    targeted: "unbalanced \'quote"\n')
    assert cfg.gates.test.red_check == "full"


def test_scn_cfg_12_quoted_words_around_the_one_files_word_load(tmp_path: Path):
    command = "uv run pytest -k 'slow or fast' --junitxml=.l4-out/junit.xml {files}"
    cfg = load(tmp_path, f'    command: x\n    red_check: targeted\n    targeted: "{command}"\n')
    assert cfg.gates.test.targeted == command


def test_a_value_other_than_full_or_targeted_is_refused(tmp_path: Path):
    err = refused(tmp_path, "    command: x\n    red_check: sometimes\n")
    assert "unknown key" not in str(err) and "red_check" in str(err)
