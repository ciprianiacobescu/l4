"""The implementer's result object (SPEC L4-IMP-005, `l4/implementer-result@1`).

Validated against the packaged JSON Schema first (the contract), then loaded into a model the loop can use. The
schema file is a copy of SPEC 7.4; tests/unit/implementer/test_result.py keeps it equal to the canonical fixture.
M1: implementer-tdd-loop 1.9 (`build_repair_prompt`).
"""

import copy
import json
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from importlib import resources
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from l4.agents.codex import drop_nulls
from l4.agents.contract import phase_hint
from l4.gates.junit import TestCase
from l4.schemacheck import validate
from l4.specs.criteria import trace_ids

RESULT_SCHEMA_ID = "l4/implementer-result@1"


class ResultInvalid(ValueError):
    """The result is missing or does not satisfy the schema. The message names paths, never values."""


def _load_schema() -> dict[str, Any]:
    text = resources.files("l4.implementer").joinpath("implementer-result.schema.json").read_text(encoding="utf-8")
    return json.loads(text)  # type: ignore[no-any-return]


RESULT_SCHEMA = _load_schema()  # what `RunRequest.result_schema` carries


def _file_schema() -> dict[str, Any]:
    """The schema of a result the agent writes to a file: L4 knows the phase, the task and the files, so it asks for
    the status and the summary and the optional parts only."""
    schema = copy.deepcopy(RESULT_SCHEMA)
    schema["$id"] = FILE_RESULT_SCHEMA_ID
    for name in ("phase", "task_ids", "files_changed", "tests_added"):
        schema["properties"].pop(name, None)
    schema["required"] = ["status", "summary"]
    return schema


FILE_RESULT_SCHEMA_ID = "l4/implementer-file-result@1"
FILE_RESULT_SCHEMA = _file_schema()


class _Open(BaseModel):
    model_config = ConfigDict(extra="ignore")  # the schema allows additional properties


class ResultQuestion(_Open):
    title: str
    context: str
    kind: Literal["technical", "product", "ambiguous"]
    options: list[str] = Field(default_factory=list)
    blocking_tasks: list[str] = Field(default_factory=list)


class TddExemption(_Open):
    reason: str = ""


class Suppression(_Open):
    file: str
    line: int
    rule: str
    reason: str


class ImplementerResult(_Open):
    status: Literal["done", "blocked", "failed", "partial"]
    phase: Literal["red", "green", "single"]
    task_ids: list[str]
    summary: str
    criteria_ids: list[str] = Field(default_factory=list)
    tests_added: list[str] = Field(default_factory=list)
    files_changed: list[str] = Field(default_factory=list)
    questions: list[ResultQuestion] = Field(default_factory=list)
    tdd_exemption: TddExemption | None = None
    suppressions: list[Suppression] = Field(default_factory=list)  # the suppression comments it added (step 1)
    notes_for_verifier: str = ""


def parse_result(raw: str | bytes | Mapping[str, Any]) -> ImplementerResult:
    """`null` means absent (Codex's strict schema makes every optional field nullable). Raises `ResultInvalid`."""
    if isinstance(raw, str | bytes):
        try:
            data: Any = json.loads(raw)
        except ValueError:
            raise ResultInvalid("the result is not valid JSON") from None
    else:
        data = dict(raw)
    data = drop_nulls(data)
    problems = validate(data, RESULT_SCHEMA)
    if problems:
        hint = phase_hint(data, RESULT_SCHEMA)
        raise ResultInvalid("; ".join([*problems[:5], *([hint] if hint else [])]))
    try:
        return ImplementerResult.model_validate(data)
    except ValidationError as exc:  # the schema subset accepted what the model does not: name the fields only
        raise ResultInvalid("; ".join(".".join(str(p) for p in e["loc"]) + ": invalid" for e in exc.errors())) from None


_PYTEST_COMMAND = re.compile(r"(?<![\w.-])pytest(?![\w-])")  # the word, not `pytest-xdist` or `mypytest`


@dataclass(frozen=True)
class TraceRules:
    """How a test names the criteria it checks (L4-CRT-002, L4-IMP-005), in the three places the prompt says so."""

    rule: str  # the harness contract's sentence, without its end: what to put on every test
    also: str  # red: how a second test traces the same criterion as well
    form: str  # single_tests: the form of the id, in brackets after "criterion id"
    hint: str  # the retry message of `check_criteria`
    stub: str  # after the contract's stub sentence: how a stub throws outside Python; "" for pytest
    advice_guarded: str  # red retry: a new parameter the code lacks needs a guarded stub, not a TypeError
    advice_other: str  # red retry: any other error is turned into a failed assertion or the stub's error


TRACE_HINT_PYTEST = 'tag each test that checks a criterion with @pytest.mark.l4("C-...")'
TRACE_HINT_NAME = 'put the id in the name of each test that checks a criterion, for example it("C-xxxxxxxx: …")'
TRACE_HINT_EITHER = (
    'tag each test that checks a criterion with @pytest.mark.l4("C-...") under pytest, or put the id in each '
    'test\'s name under any other runner, for example it("C-xxxxxxxx: …")'
)
THROWS_NOT_IMPLEMENTED = (  # how a stub throws outside Python: one wording for the prompt and the red retry advice
    '`throw new Error("not implemented")` in TypeScript or JavaScript, `throw new NotImplementedException()` in C#'
)
_PYTEST_RULES = TraceRules(
    'Tag every test with `@pytest.mark.l4("C-xxxxxxxx")` for each criterion id (listed below) that it checks',
    'as `@pytest.mark.l4("<criterion>", "<other criterion>")`',
    '`@pytest.mark.l4("C-...")`',
    TRACE_HINT_PYTEST,
    "",
    (
        "A parameter that does not exist yet needs a guarded stub (a new trailing parameter with a default and `if "
        "<condition>: raise NotImplementedError` as the first statement), not a TypeError"
    ),
    (
        "Make the test fail by assertion: catch the error and call `pytest.fail(...)`, or stub the missing symbol "
        "with `raise NotImplementedError`"
    ),
)
_NAME_RULES = TraceRules(
    "Put each criterion id (listed below) that a test checks in that test's name, for example "
    '`it("C-xxxxxxxx: …")` or `test("C-xxxxxxxx …")`; L4 reads the ids from the test names in the JUnit report',
    'by putting both ids in its name, for example `it("<criterion> <other criterion>: …")`',
    'in its name, as `it("C-...: …")`',
    TRACE_HINT_NAME,
    f" Outside Python a stub's body only throws a not-implemented error: {THROWS_NOT_IMPLEMENTED}; the harness "
    "counts it as the stub's NotImplementedError.",
    (
        "A parameter that does not exist yet needs a guarded stub (a new optional trailing parameter whose first "
        f"statement throws a not-implemented error when it is used: {THROWS_NOT_IMPLEMENTED}), not a TypeError"
    ),
    (
        "Make the test fail by assertion: assert the expected outcome with the runner's own assertion (for example "
        "expect(...) in Vitest or Jest), or stub the missing symbol so it throws a not-implemented error "
        f"({THROWS_NOT_IMPLEMENTED})"
    ),
)


def trace_rules(test_command: str) -> TraceRules:
    """The trace instruction for the project's test gate: the `l4` marker when the gate command runs pytest (the
    word `pytest` in the command, as in `python -m pytest` or `uv run pytest`), else the id in the test name, which
    `trace_ids` reads from the JUnit name and classname of any runner (`npx vitest run`, `go test`)."""
    return _PYTEST_RULES if _PYTEST_COMMAND.search(test_command) else _NAME_RULES


@dataclass(frozen=True)
class CriteriaCheck:
    cited: tuple[str, ...]  # the criteria this red step claims, sorted
    tracing: dict[str, tuple[str, ...]]  # cited criterion -> the new tests that trace it
    untraced: tuple[str, ...]  # new tests that trace nothing: recorded as `test.untraced`, never a failure
    error: str = ""  # why red fails; empty when the step is acceptable


def check_criteria(
    result: ImplementerResult,
    family_criteria: Collection[str],
    new_tests: Mapping[str, TestCase],
    trace_hint: str = TRACE_HINT_EITHER,
    exempt: Collection[str] = (),
) -> CriteriaCheck:
    """The criteria a red step covers (L4-IMP-005): `criteria_ids` when it lists any, else whatever the new tests
    trace. Each must belong to the unit's family and have a new test that traces it. `trace_hint` is how the retry
    message tells the agent to trace: `TRACE_HINT_PYTEST` or `TRACE_HINT_NAME` (what `trace_rules` decides for the
    test gate); the one caller, `tdd.py`, does not pass it yet, so the default names both forms. `exempt`: cited
    criteria that need no NEW test (L4-OPS-015): in the red step of a task a spec edit reopened, the criteria the edit
    left unchanged, whose tests already exist. A cited criterion in `exempt` that no new test traces is not a failure
    and is left out of `tracing`; a changed or added criterion still needs its test."""
    traces = {test_id: trace_ids(case) for test_id, case in new_tests.items()}
    untraced = tuple(sorted(i for i, ids in traces.items() if not ids))
    cited = tuple(sorted(set(result.criteria_ids) or set().union(*traces.values())))
    tracing = {c: tuple(sorted(i for i, ids in traces.items() if c in ids)) for c in cited}
    waived = {c for c in cited if c in exempt and not tracing[c]}
    tracing = {c: t for c, t in tracing.items() if c not in waived}
    if not cited:
        error = f"no criterion is covered: {trace_hint}"
    elif unknown := [c for c in cited if c not in family_criteria]:
        error = f"criteria that are not one of this unit's: {', '.join(unknown)}"
    elif untraced_cited := [c for c in cited if c not in waived and not tracing[c]]:
        error = f"no new test traces {', '.join(untraced_cited)}: {trace_hint}"
    else:
        error = ""
    return CriteriaCheck(cited, tracing, untraced, error)
