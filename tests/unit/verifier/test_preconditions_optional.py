from l4.specs.base import ValidationReport
from l4.specs.kiro import parse_kiro_tasks
from l4.verifier.preconditions import check_preconditions

from ..conftest import UNIT  # noqa: F401


class OptionalLeafOpen:
    """A Kiro unit whose only open task is optional."""

    def tasks(self, unit):
        return parse_kiro_tasks(b"- [x] 1. Greet\n  - [x] 1.1 Add greet\n  - [ ]* 1.2 Blank name test\n")

    def validate(self, unit, strict=True):
        return ValidationReport(True, ())


def test_optional_leaf_does_not_block_step_0(make_bench):
    wb = make_bench([]).wb
    wb.provider = OptionalLeafOpen()  # type: ignore[assignment]
    assert check_preconditions(wb).findings == []
