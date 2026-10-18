"""Round 2 of the review: honest red steps put NEW tests, fixtures, constants and imports into an existing test file."""

import pytest

from l4.agents.fake import Step
from l4.implementer.tdd import run_red

from .._kiro_probe import PROBE_IDS
from .conftest import TIP_STUB, Bench, result

C11, C12 = PROBE_IDS["1.1"], PROBE_IDS["1.2"]
MISC = "tests/test_misc.py"

PLAIN_OLD = "import pytest\n\n\ndef test_misc_existing():\n    assert 1 + 1 == 2\n"
CLASS_OLD = "import pytest\n\n\nclass TestMisc:\n    def test_misc_existing(self):\n        assert 1 + 1 == 2\n"
DEC_OLD = (
    "import pytest\nfrom decimal import Decimal\n\n\ndef test_misc_existing():\n    assert Decimal('1') + 1 == 2\n"
)
NEG = (
    f'\n\n@pytest.mark.l4("{C12}")\ndef test_new_negative():\n    try:\n        tip(10, -1)\n'
    "    except ValueError:\n        return\n    raise AssertionError('no ValueError')\n"
)
ROUNDS = f'\n\n@pytest.mark.l4("{C11}")\ndef test_new_rounds():\n    assert str(tip(10, 12.5)) == "1.25"\n'
IMPORT = "from pytdd.tip import tip\n"


def with_import(old: str) -> str:
    return old.replace("import pytest\n", "import pytest\n" + IMPORT, 1)


VARIANTS = {
    # control: a separate import line at the top and plain top-level tests at the end
    "control_plain_append": (PLAIN_OLD, with_import(PLAIN_OLD) + ROUNDS + NEG),
    # a new fixture for the new tests
    "fixture": (
        PLAIN_OLD,
        with_import(PLAIN_OLD)
        + "\n\n@pytest.fixture\ndef bill():\n    return 10\n"
        + ROUNDS.replace("def test_new_rounds():", "def test_new_rounds(bill):").replace("tip(10,", "tip(bill,")
        + NEG,
    ),
    # a parametrized new test whose cases are Decimal values
    "parametrize_decimal": (
        DEC_OLD,
        with_import(DEC_OLD) + f'\n\n@pytest.mark.l4("{C11}")\n@pytest.mark.parametrize("bill", [Decimal("10")])\n'
        'def test_new_rounds(bill):\n    assert str(tip(bill, 12.5)) == "1.25"\n' + NEG,
    ),
    # a module constant for the new tests
    "constant_call": (
        DEC_OLD,
        with_import(DEC_OLD) + '\n\nTEN = Decimal("10")\n' + ROUNDS.replace("tip(10,", "tip(TEN,") + NEG,
    ),
    # a new method in the file's existing test class
    "method_in_class": (
        CLASS_OLD,
        with_import(CLASS_OLD) + f'\n    @pytest.mark.l4("{C11}")\n    def test_new_rounds(self):\n'
        '        assert str(tip(10, 12.5)) == "1.25"\n' + NEG,
    ),
    # the existing import line gains a name (what isort/ruff produce)
    "import_merged": (
        DEC_OLD,
        DEC_OLD.replace("from decimal import Decimal\n", "from decimal import ROUND_HALF_UP, Decimal\n" + IMPORT)
        + "\n\nassert ROUND_HALF_UP\n".replace("assert ROUND_HALF_UP\n", "")
        + ROUNDS
        + NEG,
    ),
}


# detect-test-tamper's `<module>` rule wins over a computed constant or a call at import in an existing test file:
# such a statement reaches every test of the file (L4-IMP-045, design 6.6 item 7): refused, with the way out
REFUSED = frozenset({"constant_call", "parametrize_decimal"})


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_new_tests_in_an_existing_file(make_kiro_bench, variant):
    old, new = VARIANTS[variant]
    bench: Bench = make_kiro_bench(
        [
            Step(
                writes={MISC: new, "src/pytdd/tip.py": TIP_STUB},
                structured=result("red", task_ids=["1"], criteria_ids=[C11, C12]),
            )
        ]
    )
    wb = bench.wb
    (wb.worktree / MISC).write_text(old)
    wb.git.run("add", MISC)
    wb.git.run("commit", "-q", "-m", "an existing project test")
    (task,) = wb.provider.tasks(wb.ref)
    outcome = run_red(wb, task, attempt=1)
    if variant in REFUSED:
        assert outcome.status == "failed", (variant, outcome.reason)
        assert outcome.reason.startswith("red changed tests that existed before this step: ")
        assert "<module>" in outcome.reason
        assert "compute the value inside the new test" in outcome.excerpt  # the way out is in the retry text
        assert "put the new tests in a new file" in outcome.excerpt
        return
    assert outcome.status == "ok", (variant, outcome.reason)
