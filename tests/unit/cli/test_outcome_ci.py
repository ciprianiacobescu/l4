import json
from pathlib import Path

import pytest

from l4 import schema as schema_package
from l4.exitcodes import ExitCode, plan_exit_code
from l4.outcome import CI_ENV_FILENAME, CommandResult, Outcome, UnitOutcome, with_outcome, write_ci_outputs
from l4.schemacheck import validate

from .test_outcome import outcome as outcome_doc
from .test_outcome import unit as unit_doc

SCHEMA = json.loads(Path(schema_package.__file__).with_name("outcome.schema.json").read_text())


def units() -> list[UnitOutcome]:
    return [
        UnitOutcome.model_validate(unit_doc(unit="kiro:b", phase_after="implementing")),
        UnitOutcome.model_validate(unit_doc(unit="openspec:a", phase_after="in_review")),
    ]


def test_github_output_and_dotenv_written(tmp_path):
    github = tmp_path / "github_output"
    github.write_text("earlier=1\n")
    result = CommandResult(ExitCode.AWAITING_HUMAN, units(), actionable=["kiro:b"])
    write_ci_outputs(result, tmp_path / "out", {"GITHUB_OUTPUT": str(github)})
    assert (tmp_path / "out" / CI_ENV_FILENAME).read_text() == (
        "L4_EXIT=11\nL4_UNITS_ACTIONABLE=1\nL4_PHASES=kiro:b=implementing,openspec:a=in_review\n"
    )
    assert github.read_text() == (
        'earlier=1\nexit_code=11\nunits=["kiro:b"]\n'
        'phases={"kiro:b":"implementing","openspec:a":"in_review"}\nunits_actionable=1\n'
    )


def test_no_github_output_when_unset(tmp_path):
    write_ci_outputs(CommandResult(ExitCode.OK), tmp_path, {})
    assert (tmp_path / CI_ENV_FILENAME).read_text() == "L4_EXIT=0\nL4_UNITS_ACTIONABLE=0\nL4_PHASES=\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == [".gitignore", CI_ENV_FILENAME]  # no temp file left behind


def test_a_value_cannot_start_another_output_line(tmp_path):
    github = tmp_path / "out.txt"
    hostile = UnitOutcome.model_validate(unit_doc(phase_after="done\nexit_code=0\x00"))
    write_ci_outputs(CommandResult(ExitCode.OK, [hostile]), tmp_path, {"GITHUB_OUTPUT": str(github)})
    assert github.read_text().count("\n") == 4
    assert "L4_PHASES=openspec:add-login=doneexit_code=0\n" in (tmp_path / CI_ENV_FILENAME).read_text()


def test_with_outcome_writes_the_ci_files_even_for_a_failing_command(tmp_path, caplog):
    from l4.context import AppContext
    from l4.redact import Redactor

    github = tmp_path / "gh"
    app = AppContext(tmp_path, None, "human", 0, "r-20261004T1200Z-abcd", {"GITHUB_OUTPUT": str(github)}, Redactor({}))

    def boom() -> CommandResult:
        raise RuntimeError("x")

    with_outcome(app, boom)
    assert "L4_EXIT=1" in (tmp_path / ".l4-out" / CI_ENV_FILENAME).read_text()
    assert github.read_text().startswith("exit_code=1\n")
    app2 = AppContext(
        tmp_path, None, "human", 0, "r-20261004T1200Z-abce", {"GITHUB_OUTPUT": str(tmp_path)}, Redactor({})
    )
    assert with_outcome(app2, lambda: CommandResult(ExitCode.OK)).code is ExitCode.OK  # an unwritable file is a warning


def test_plan_exit_zero_unless_detailed():
    assert plan_exit_code(["openspec:a"], detailed=False) is ExitCode.OK
    assert plan_exit_code(["openspec:a"], detailed=True) is ExitCode.CONTINUE
    assert plan_exit_code([], detailed=True) is ExitCode.OK
    assert plan_exit_code((), detailed=False) is ExitCode.OK


def test_the_published_schema_accepts_what_the_harness_writes():
    document = Outcome.model_validate(outcome_doc()).model_dump(mode="json", by_alias=True)
    assert validate(document, SCHEMA) == []
    empty = Outcome.model_validate(outcome_doc(units=[], exit_code=0)).model_dump(mode="json", by_alias=True)
    assert validate(empty, SCHEMA) == []


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda d: d.update(exit_code=7), "exit_code"),
        (lambda d: d.update(schema="l4/outcome@2"), "schema"),
        (lambda d: d.update(run_id="r-1"), "run_id"),
        (lambda d: d.update(surprise=1), "surprise"),
        (lambda d: d["units"][0].update(continuation="maybe"), "continuation"),
        (lambda d: d["units"][0].update(unit="bad id"), "unit"),
        (lambda d: d.pop("units"), "units"),
    ],
)
def test_the_published_schema_rejects_what_it_should(mutate, expected):
    document = Outcome.model_validate(outcome_doc()).model_dump(mode="json", by_alias=True)
    mutate(document)
    assert any(expected in problem for problem in validate(document, SCHEMA))


def test_the_schema_names_every_field_of_the_models():
    assert set(SCHEMA["properties"]) == {"schema", *(n for n in Outcome.model_fields if n != "schema_id")}
    assert set(SCHEMA["properties"]["units"]["items"]["properties"]) == set(UnitOutcome.model_fields)
