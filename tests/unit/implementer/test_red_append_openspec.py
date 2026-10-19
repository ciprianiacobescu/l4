"""Round 2 of the review: an OpenSpec unit (py_tdd) adds a fixture and tests to an existing test file."""

from l4.agents.fake import Step
from l4.implementer.tdd import run_red

from .conftest import KNOWN, KNOWN_TEST, STUB, UNKNOWN, UNKNOWN_TEST, result

OLD = "import pytest\n\n\ndef test_misc_existing():\n    assert 1 + 1 == 2\n"


def test_openspec_red_with_a_new_fixture_in_an_existing_file(make_bench):
    new = (
        OLD.replace("import pytest\n", "import pytest\n\nfrom pytdd.pricing import apply_discount\n", 1)
        + "\n\n@pytest.fixture\ndef amount():\n    return 50.0\n\n\n"
        + KNOWN_TEST.replace("test_known_code():", "test_known_code(amount):").replace("50.0", "amount")
        + "\n\n"
        + UNKNOWN_TEST
    )
    step = Step(
        writes={"tests/test_misc.py": new, "src/pytdd/pricing.py": STUB},
        structured=result("red", criteria_ids=[KNOWN, UNKNOWN]),
    )
    bench = make_bench([step])
    wb = bench.wb
    (wb.worktree / "tests" / "test_misc.py").write_text(OLD)
    wb.git.run("add", "tests/test_misc.py")
    wb.git.run("commit", "-q", "-m", "an existing project test")
    task = next(t for t in wb.provider.tasks(wb.ref) if t.key == "1.1")
    outcome = run_red(wb, task, attempt=1)
    assert outcome.status == "ok", outcome.reason
