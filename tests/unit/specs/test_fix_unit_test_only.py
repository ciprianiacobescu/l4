"""M1.13 line 10 (W-C1): the fix unit of a test-only finding on a criterion is a tests chore citing the criterion."""

from l4.specs.base import Finding
from l4.specs.fixmark import chore_findings, chore_kind, read_fix_marker

from .test_fix_unit import parent, provider_of  # noqa: F401 (fixture)

TASK = "1.1 New tests bypass the HTTP server (F-eeeeeeee; C-11111111)"
GROUP = Finding(
    ("F-eeeeeeee",), "New tests bypass the HTTP server", "Decided by human in Q-004: drive the real server", "major",
    ("C-11111111",), chore=True, tests=True,
)  # fmt: skip


def test_the_marker_and_the_task_line_of_a_criterion_bound_tests_chore(parent):  # noqa: F811
    repo, ref = parent
    provider, _ = provider_of(repo)
    fix = provider.create_fix_unit(ref, 1, [GROUP], None)
    marker = read_fix_marker(fix.path)
    assert marker is not None and marker.chores == ("F-eeeeeeee",) and marker.test_chores == ("F-eeeeeeee",)
    assert "- [ ] 1.1 New tests bypass the HTTP server (F-eeeeeeee; C-11111111)" in (fix.path / "tasks.md").read_text()
    assert chore_findings(fix.path, TASK) == ("F-eeeeeeee",) and chore_kind(fix.path, TASK) == "tests"
