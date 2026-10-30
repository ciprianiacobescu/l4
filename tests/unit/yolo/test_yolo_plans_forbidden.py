"""The forbidden-path intake on the plan side (forbidden-path-intake 4.2; L4-YOLO-092): the phase gate, and existence
read from the tracked files of the revision checked, not from the disk."""

from types import SimpleNamespace

import pytest

from l4.config.defaults import FORBIDDEN_PATHS, SCOPE_EXEMPT, TEST_GLOBS, TEST_SUPPORT_GLOBS
from l4.specs.base import Framework, UnitRef, ValidationReport
from l4.yolo.forbidden import TreeIndex
from l4.yolo.plans import unit_infos
from l4.yolo.testpaths import PathGlobs

MIGRATION = "app/migrations/0001_initial.py"


class Provider:
    def validate(self, ref, strict=True):
        return ValidationReport(True, ())


def kiro_unit(tmp_path, phase):
    folder = tmp_path / ".kiro" / "specs" / "add-x"
    folder.mkdir(parents=True)
    (folder / "tasks.md").write_text(f"- [ ] 1.1 Create `{MIGRATION}`\n")
    ref = UnitRef(Framework.KIRO, "add-x", folder)
    snapshot = SimpleNamespace(ref=ref, state=SimpleNamespace(phase=phase), questions=None)
    return [(Provider(), snapshot)]


@pytest.mark.parametrize("phase", [None, "intake", "ready"])
def test_a_unit_before_implementing_is_refused(tmp_path, phase):
    infos = unit_infos(tmp_path, kiro_unit(tmp_path, phase), ["kiro:add-x"], forbidden=FORBIDDEN_PATHS)
    info = infos["kiro:add-x"]
    assert not info.intake_ok and info.intake_detail.startswith("forbidden_path: task 1.1 names")
    assert info.warnings == ()


@pytest.mark.parametrize("phase", ["implementing", "awaiting_human", "clarifying", "in_review", "fixing"])
def test_a_unit_already_implementing_gets_a_warning_not_a_blocker(tmp_path, phase):
    infos = unit_infos(tmp_path, kiro_unit(tmp_path, phase), ["kiro:add-x"], forbidden=FORBIDDEN_PATHS)
    info = infos["kiro:add-x"]
    assert info.intake_ok and info.intake_detail == ""
    (line,) = info.warnings
    assert line.startswith(f"warning: forbidden_path: kiro:add-x: task 1.1 names {MIGRATION},")


def test_an_untracked_file_on_disk_does_not_turn_the_blocker_into_a_warning(tmp_path):
    found = kiro_unit(tmp_path, None)
    (tmp_path / "app" / "migrations").mkdir(parents=True)
    (tmp_path / MIGRATION).write_text("# local, never committed\n")
    tree = TreeIndex(lambda: [".kiro/specs/add-x/tasks.md"])
    info = unit_infos(tmp_path, found, ["kiro:add-x"], forbidden=FORBIDDEN_PATHS, tree=tree)["kiro:add-x"]
    assert not info.intake_ok and "forbidden_path: task 1.1 names" in info.intake_detail


def test_a_tracked_file_is_a_warning(tmp_path):
    tree = TreeIndex(lambda: [MIGRATION])
    info = unit_infos(tmp_path, kiro_unit(tmp_path, None), ["kiro:add-x"], forbidden=FORBIDDEN_PATHS, tree=tree)[
        "kiro:add-x"
    ]
    assert info.intake_ok and len(info.warnings) == 1 and "already exists" in info.warnings[0]


def test_without_a_tree_the_checkout_on_disk_answers(tmp_path):
    found = kiro_unit(tmp_path, None)
    (tmp_path / "app" / "migrations").mkdir(parents=True)
    (tmp_path / MIGRATION).write_text("x\n")
    assert unit_infos(tmp_path, found, ["kiro:add-x"], forbidden=FORBIDDEN_PATHS)["kiro:add-x"].intake_ok


DOCS_FIXTURE = "docs/waitlist/fixtures/a.json"
GLOBS = PathGlobs(test=TEST_GLOBS, support=TEST_SUPPORT_GLOBS, exempt=SCOPE_EXEMPT)


def docs_unit(tmp_path, phase, task=f"Write `{DOCS_FIXTURE}`"):
    folder = tmp_path / ".kiro" / "specs" / "add-x"
    folder.mkdir(parents=True)
    (folder / "tasks.md").write_text(f"- [ ] 1.1 {task}\n")
    ref = UnitRef(Framework.KIRO, "add-x", folder)
    return [(Provider(), SimpleNamespace(ref=ref, state=SimpleNamespace(phase=phase), questions=None))]


@pytest.mark.parametrize("phase", [None, "intake", "implementing", "fixing"])
def test_a_test_path_finding_is_a_warning_in_every_phase_and_never_refuses(tmp_path, phase):  # SCN-YOLO-256
    info = unit_infos(tmp_path, docs_unit(tmp_path, phase), ["kiro:add-x"], test_paths=GLOBS)["kiro:add-x"]
    assert info.intake_ok and info.intake_detail == ""
    (line,) = info.warnings
    assert line.startswith(f"warning: test_path: kiro:add-x: task 1.1 names {DOCS_FIXTURE}, which the test glob ")


def test_without_test_path_globs_there_is_no_test_path_warning(tmp_path):
    info = unit_infos(tmp_path, docs_unit(tmp_path, None), ["kiro:add-x"])["kiro:add-x"]
    assert info.intake_ok and info.warnings == ()


def test_a_tagged_task_gives_no_test_path_warning(tmp_path):  # SCN-YOLO-257
    found = docs_unit(tmp_path, None, task=f"[test-infra] Write `{DOCS_FIXTURE}`")
    assert unit_infos(tmp_path, found, ["kiro:add-x"], test_paths=GLOBS)["kiro:add-x"].warnings == ()


def test_the_warnings_of_both_rules_are_listed_forbidden_first(tmp_path):
    found = docs_unit(tmp_path, "implementing", task=f"Write `{MIGRATION}` and `{DOCS_FIXTURE}`")
    info = unit_infos(tmp_path, found, ["kiro:add-x"], forbidden=FORBIDDEN_PATHS, test_paths=GLOBS)["kiro:add-x"]
    assert [w.split(":")[1].strip() for w in info.warnings] == ["forbidden_path", "test_path"]
