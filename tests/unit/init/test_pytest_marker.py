"""P4: `l4 init` and `l4 upgrade` register the `l4` pytest marker in the project, so that the harness's tests run
under `--strict-markers` in the project's own CI (L4-INS-002). The edit is minimal, verified by a re-parse, and refused
(with the snippet to paste) whenever it cannot be made safely."""

import subprocess
import sys
from pathlib import Path

import pytest

from l4.init import pytest_marker
from l4.init.pytest_marker import MarkerEdit, MarkerRefusal, register_l4_marker

MARKER = "l4(*ids): the acceptance criteria (C-xxxxxxxx) this test checks"


def apply(repo: Path, edit: MarkerEdit) -> None:
    assert edit.data is not None
    (repo / edit.path).write_bytes(edit.data)


def test_appended_to_a_multiline_markers_array_byte_minimal(tmp_path):
    before = (
        '[project]\nname = "demo"\n\n[tool.pytest.ini_options]\nmarkers = [\n    "slow: marks tests as slow",\n'
        '    "net: needs the network",\n]\naddopts = "-q"\n'
    )
    (tmp_path / "pyproject.toml").write_text(before)
    edit = register_l4_marker(tmp_path)
    assert isinstance(edit, MarkerEdit) and edit.path == "pyproject.toml"
    assert edit.data is not None
    after = edit.data.decode()
    # one added line in the file's own style (indent, quotes, trailing comma), every other byte unchanged
    added = f'    "{MARKER}",\n'
    assert after.replace(added, "") == before and after.count("\n") == before.count("\n") + 1
    assert f'"net: needs the network",\n{added}]\n' in after


def test_a_multiline_array_without_a_trailing_comma_gets_one_comma_and_no_more(tmp_path):
    before = "[tool.pytest.ini_options]\nmarkers = [\n  'slow: slow',\n  'net: net'\n]\n"
    (tmp_path / "pyproject.toml").write_text(before)
    edit = register_l4_marker(tmp_path)
    assert isinstance(edit, MarkerEdit) and edit.data is not None
    assert (
        edit.data.decode()
        == f"[tool.pytest.ini_options]\nmarkers = [\n  'slow: slow',\n  'net: net',\n  '{MARKER}'\n]\n"
    )


def test_appended_to_a_one_line_array(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\nmarkers = ["slow: slow"]  # keep\ntestpaths = ["tests"]\n'
    )
    edit = register_l4_marker(tmp_path)
    assert isinstance(edit, MarkerEdit) and edit.data is not None
    assert edit.data.decode().splitlines()[1] == f'markers = ["slow: slow", "{MARKER}"]  # keep'
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\nmarkers = []\n")
    edit = register_l4_marker(tmp_path)
    assert isinstance(edit, MarkerEdit) and edit.data is not None
    assert edit.data.decode() == f'[tool.pytest.ini_options]\nmarkers = ["{MARKER}"]\n'


def test_table_without_markers_gets_one_line(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\n\n[tool.pytest.ini_options]\ntestpaths = ["tests"]\n'
    )
    edit = register_l4_marker(tmp_path)
    assert isinstance(edit, MarkerEdit) and edit.data is not None
    assert edit.data.decode() == (
        f'[project]\nname = "x"\n\n[tool.pytest.ini_options]\nmarkers = ["{MARKER}"]\ntestpaths = ["tests"]\n'
    )


def test_no_pytest_table_writes_conftest(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
    edit = register_l4_marker(tmp_path)
    assert isinstance(edit, MarkerEdit) and edit.path == "conftest.py" and edit.created
    assert edit.data is not None and f'config.addinivalue_line("markers", "{MARKER}")' in edit.data.decode()
    assert "def pytest_configure(config):" in edit.data.decode()
    (tmp_path / "conftest.py").write_text("import pytest\n\n\n@pytest.fixture\ndef a():\n    return 1\n")
    appended = register_l4_marker(tmp_path)
    assert isinstance(appended, MarkerEdit) and appended.path == "conftest.py" and not appended.created
    assert appended.data is not None and appended.data.decode().startswith("import pytest\n\n\n@pytest.fixture\n")
    assert appended.data.decode().endswith(f'    config.addinivalue_line("markers", "{MARKER}")\n')


def test_pytest_ini_present_uses_conftest(tmp_path):
    """pytest reads `pytest.ini` before `pyproject.toml`: a marker added to the pyproject would never be seen."""
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = -q\n")
    (tmp_path / "pyproject.toml").write_text('[tool.pytest.ini_options]\nmarkers = ["a: b"]\n')
    edit = register_l4_marker(tmp_path)
    assert isinstance(edit, MarkerEdit) and edit.path == "conftest.py"
    # tox.ini or setup.cfg configuration that the pyproject has no table to shadow is just as untouchable
    (tmp_path / "pytest.ini").unlink()
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
    (tmp_path / "tox.ini").write_text("[pytest]\naddopts = -q\n")
    assert register_l4_marker(tmp_path).path == "conftest.py"  # type: ignore[union-attr]


def test_existing_pytest_configure_is_refused_with_the_snippet(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "conftest.py").write_text("def pytest_configure(config):\n    pass\n")
    refusal = register_l4_marker(tmp_path)
    assert isinstance(refusal, MarkerRefusal)
    assert "pytest_configure" in refusal.reason and f'"{MARKER}"' in refusal.snippet
    assert (tmp_path / "conftest.py").read_text() == "def pytest_configure(config):\n    pass\n"  # nothing written


@pytest.mark.parametrize(
    "text",
    [
        '[tool]\npytest.ini_options = {markers = ["a: b"]}\n',
        '[tool.pytest]\nini_options = { testpaths = ["tests"] }\n',
        'tool.pytest.ini_options.markers = ["a: b"]\n',
    ],
)
def test_an_inline_or_dotted_table_is_refused(tmp_path, text):
    (tmp_path / "pyproject.toml").write_text(text)
    refusal = register_l4_marker(tmp_path)
    assert isinstance(refusal, MarkerRefusal) and "pyproject.toml" in refusal.reason
    assert (tmp_path / "pyproject.toml").read_text() == text


def test_second_run_writes_nothing(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\nmarkers = [\n    'slow: slow',\n]\n")
    first = register_l4_marker(tmp_path)
    assert isinstance(first, MarkerEdit)
    apply(tmp_path, first)
    again = register_l4_marker(tmp_path)
    assert isinstance(again, MarkerEdit) and again.data is None and again.path == "pyproject.toml"
    # the same for the conftest route, and for an entry the project wrote itself
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
    apply(tmp_path, register_l4_marker(tmp_path))  # type: ignore[arg-type]
    assert register_l4_marker(tmp_path).data is None  # type: ignore[union-attr]
    (tmp_path / "conftest.py").unlink()
    (tmp_path / "pyproject.toml").write_text('[tool.pytest.ini_options]\nmarkers = ["l4: the project\'s own"]\n')
    assert register_l4_marker(tmp_path).data is None  # type: ignore[union-attr]


def test_reparse_mismatch_refuses(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text('[tool.pytest.ini_options]\nmarkers = ["a: b"]\n')
    monkeypatch.setattr(pytest_marker, "_edit_pyproject", lambda text: text.replace("a: b", "a: c"))  # a wrong edit
    refusal = register_l4_marker(tmp_path)
    assert isinstance(refusal, MarkerRefusal) and "re-parse" in refusal.reason


@pytest.mark.parametrize(
    "files",
    [
        {"pyproject.toml": "[tool.pytest.ini_options]\nmarkers = [\n    'slow: slow',\n]\n"},
        {"pyproject.toml": "[tool.pytest.ini_options]\ntestpaths = ['tests']\n"},
        {"pyproject.toml": '[project]\nname = "x"\n'},
        {"pytest.ini": "[pytest]\naddopts = -q\n", "conftest.py": "import os\n"},
    ],
    ids=["array", "table", "no-table", "ini"],
)
def test_strict_markers_collects_an_l4_test(tmp_path, files):
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    (tmp_path / "test_x.py").write_text(
        'import pytest\n\n\n@pytest.mark.l4("C-0a1b2c3d")\ndef test_x():\n    assert 1\n'
    )
    edit = register_l4_marker(tmp_path)
    assert isinstance(edit, MarkerEdit)
    apply(tmp_path, edit)
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "--strict-markers", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert done.returncode == 0 and "test_x.py" in done.stdout, done.stdout + done.stderr
    # and without the edit it is an error: the marker really is the missing piece
    for name in files:
        (tmp_path / name).write_text(files[name])
    (tmp_path / "conftest.py").unlink(missing_ok=True)
    plain = subprocess.run(
        [sys.executable, "-m", "pytest", "--strict-markers", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert plain.returncode != 0


def _edited(tmp_path, before: str) -> str:
    (tmp_path / "pyproject.toml").write_text(before)
    edit = register_l4_marker(tmp_path)
    assert isinstance(edit, MarkerEdit) and edit.data is not None, edit
    return edit.data.decode()


def test_a_double_quoted_entry_holding_single_quotes_keeps_double(tmp_path):
    """M1.8 live F3: the array's own quotes are `"`, and one entry holds `'not ui'`: the new entry is `"`-quoted too."""
    before = (
        '[tool.pytest.ini_options]\nmarkers = [\n    "slow: slow tests",\n'
        "    \"ui: browser tests (deselect with -m 'not ui')\",\n]\n"
    )
    after = _edited(tmp_path, before)
    assert after == before[: -len("]\n")] + f'    "{MARKER}",\n]\n'  # one added line, in the array's own quotes
    one_line = "[tool.pytest.ini_options]\nmarkers = [\"ui: run with -m 'not ui'\"]\n"
    assert (
        _edited(tmp_path, one_line)
        == f'[tool.pytest.ini_options]\nmarkers = ["ui: run with -m \'not ui\'", "{MARKER}"]\n'
    )
    literal = "[tool.pytest.ini_options]\nmarkers = [\n  'slow: say \"hi\"',\n]\n"
    assert f"  '{MARKER}',\n" in _edited(tmp_path, literal)  # a literal string holding double quotes stays literal


def test_a_hash_inside_the_last_string_is_not_a_comment(tmp_path):
    before = '[tool.pytest.ini_options]\nmarkers = [\n    "slow: tests # not a comment"\n]\n'
    after = _edited(tmp_path, before)
    assert after == f'[tool.pytest.ini_options]\nmarkers = [\n    "slow: tests # not a comment",\n    "{MARKER}"\n]\n'
    real = '[tool.pytest.ini_options]\nmarkers = [\n    "slow: tests"  # keep this\n]\n'
    assert _edited(tmp_path, real) == (
        f'[tool.pytest.ini_options]\nmarkers = [\n    "slow: tests",  # keep this\n    "{MARKER}"\n]\n'
    )
    both = '[tool.pytest.ini_options]\nmarkers = [\n    "a # b"  # c # d\n]\n'
    assert '    "a # b",  # c # d\n' in _edited(tmp_path, both)


def test_a_bracket_or_quote_inside_a_string_does_not_end_the_array(tmp_path):
    before = "[tool.pytest.ini_options]\nmarkers = [\n    '''c ] \"\"\" d''',\n    \"a ] b '\",\n]\naddopts = \"-q\"\n"
    after = _edited(tmp_path, before)
    assert after.endswith(f'    "{MARKER}",\n]\naddopts = "-q"\n')
