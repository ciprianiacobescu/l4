from l4.implementer.opened import check_opened

MODS = frozenset({"app.otel"})

BEFORE = (
    "import os\n\nimport pytest\n\nos.environ['A'] = '1'\nVALUE = 2\n\n\n"
    "@pytest.fixture\ndef client():\n    return object()\n"
)


def run(after: str, *, before: str = BEFORE, named: bool = True, mods: frozenset[str] = MODS) -> str | None:
    return check_opened(before, after, named_by_task=named, unit_modules=mods)


def test_live_case_setdefault_between_old_statements_and_autouse_fixtures_pass() -> None:
    after = BEFORE.replace(
        "VALUE = 2\n",
        "os.environ.setdefault('APP_OTEL_ENABLED', 'false')\nVALUE = 2\n",
    ) + (
        "\n\n@pytest.fixture(autouse=True)\ndef _no_otel(monkeypatch):\n"
        "    monkeypatch.setenv('APP_OTEL_ENABLED', 'false')\n"
        "\n\n@pytest.fixture(autouse=True)\ndef _reset():\n"
        "    from app import telemetry\n\n    telemetry.reset_telemetry()\n"
    )
    assert run(after) is None


def test_unchanged_file_passes() -> None:
    assert run(BEFORE) is None


def test_changed_fixture_body_fails() -> None:
    why = run(BEFORE.replace("return object()", "return None"))
    assert why == "changes an existing statement"


def test_second_def_client_fails() -> None:
    assert run(BEFORE + "\n\ndef client():\n    return 1\n") == "rebinds client"


def test_removed_statement_fails() -> None:
    assert run(BEFORE.replace("VALUE = 2\n", "")) == "changes an existing statement"


def test_new_pytestmark_fails() -> None:
    assert run(BEFORE + "\npytestmark = pytest.mark.skip\n") == "rebinds pytestmark"


def test_new_module_hook_fails() -> None:
    assert run(BEFORE + "\n\ndef pytest_generate_tests(metafunc):\n    pass\n") == "rebinds pytest_generate_tests"


def test_does_not_parse() -> None:
    assert run("def (:\n") == "does not parse"
    assert run(BEFORE, before="def (:\n") == "does not parse"


def test_rules_one_and_two_apply_only_to_an_open_by_task_text() -> None:
    assert run(BEFORE.replace("return object()", "return None"), named=False) is None
