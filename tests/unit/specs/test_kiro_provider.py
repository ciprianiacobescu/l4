import shutil
from pathlib import Path

import pytest

from l4.specs.base import (
    ArchiveRefused,
    Framework,
    Marker,
    MarkerNotAllowed,
    ParentHasOpenChildren,
    SpecError,
    SpecProvider,
    UnitRef,
)
from l4.specs.kiro import KiroProvider

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "specs" / "kiro" / "user-auth"


@pytest.fixture
def repo(tmp_path):
    shutil.copytree(FIXTURE, tmp_path / ".kiro" / "specs" / "user-auth")
    return tmp_path


def make(repo, **kw) -> tuple[KiroProvider, UnitRef]:
    provider = KiroProvider(repo, **kw)
    (unit,) = provider.list_units()
    return provider, unit


def tasks_path(repo) -> Path:
    return repo / ".kiro/specs/user-auth/tasks.md"


def test_provider_satisfies_the_protocol_and_lists_units(repo):
    provider, unit = make(repo)
    assert isinstance(provider, SpecProvider)
    assert unit.id == "kiro:user-auth" and unit.framework is Framework.KIRO
    assert provider.unit_dir(unit) == repo / ".kiro/specs/user-auth"
    loaded = provider.load(unit)
    assert [t.key for t in loaded.tasks][:3] == ["1", "1.1", "1.2"]
    assert len(loaded.criteria) == 5
    assert {t.key: t.wave for t in loaded.tasks if t.wave is not None} == {"2.1": 0, "1.1": 0, "1.2": 1}


def test_listing_skips_dirs_without_spec_files_and_symlinks(repo):
    specs = repo / ".kiro/specs"
    (specs / "empty").mkdir()
    (specs / "empty" / ".config.kiro").write_text("{}")
    (specs / "link").symlink_to(specs / "user-auth")
    (specs / "Bad Name").mkdir()
    (specs / "Bad Name" / "tasks.md").write_text("- [ ] 1.1 x\n")
    assert [u.name for u in KiroProvider(repo).list_units()] == ["user-auth"]


def test_leaf_done_closes_parent_and_optional_stays_open(repo):
    provider, unit = make(repo)
    before = tasks_path(repo).read_bytes()
    provider.set_marker(unit, "1.1", Marker.DONE)
    provider.set_marker(unit, "1.2", Marker.DONE)
    after = tasks_path(repo).read_bytes()
    state = {t.key: t.marker_char for t in provider.tasks(unit)}
    assert state["1"] == "x"  # SCN-TMW-02: parent 1 closed with the optional 1.3 still open
    assert state["1.3"] == " "
    assert state["2"] == " "
    assert sum(a != b for a, b in zip(before, after, strict=True)) == 3 and len(before) == len(after)
    assert not provider.done_gate(unit).passed


def test_parent_cannot_close_over_an_open_required_child(repo):
    provider, unit = make(repo)
    provider.set_marker(unit, "2.1", Marker.DONE)
    before = tasks_path(repo).read_bytes()
    with pytest.raises(ParentHasOpenChildren, match="2.2"):  # SCN-KSP-N2
        provider.set_marker(unit, "2", Marker.DONE)
    assert tasks_path(repo).read_bytes() == before
    assert issubclass(ParentHasOpenChildren, MarkerNotAllowed)


def test_only_done_is_written_and_done_tasks_are_refused(repo):
    provider, unit = make(repo)
    for marker in (Marker.IN_PROGRESS, Marker.QUEUED, Marker.NOT_STARTED):
        with pytest.raises(MarkerNotAllowed):
            provider.set_marker(unit, "1.1", marker)
    provider.set_marker(unit, "1.1", Marker.DONE)
    with pytest.raises(MarkerNotAllowed, match="already done"):
        provider.set_marker(unit, "1.1", Marker.DONE)
    with pytest.raises(SpecError, match="no task"):
        provider.set_marker(unit, "9.9", Marker.DONE)


def test_in_progress_marker_left_by_kiro_can_be_ticked(repo):
    path = tasks_path(repo)
    path.write_text(path.read_text().replace("- [ ] 1.1 Add", "- [-] 1.1 Add"))
    provider, unit = make(repo)
    provider.set_marker(unit, "1.1", Marker.DONE)
    assert "- [x] 1.1 Add" in path.read_text()


def test_crlf_file_changes_one_byte_per_marker(repo):
    path = tasks_path(repo)
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    provider, unit = make(repo)
    before = path.read_bytes()
    offset = {t.key: t.marker_offset for t in provider.tasks(unit)}["1.1"]
    provider.set_marker(unit, "1.1", Marker.DONE)
    after = path.read_bytes()
    assert [i for i, (a, b) in enumerate(zip(before, after, strict=True)) if a != b] == [offset]
    assert after.count(b"\r\n") == before.count(b"\r\n")


def test_done_gate_counts_required_leaves_only(repo):
    provider, unit = make(repo)
    for key in ("1.1", "1.2", "2.1", "2.2"):
        provider.set_marker(unit, key, Marker.DONE)
    assert provider.done_gate(unit).passed  # the optional 1.3 is still open
    report = provider.archive(unit)
    assert report.archived_as == "user-auth"
    assert report.moved_to is None  # SCN-KSP-N8: state only, the folder stays
    assert (repo / ".kiro/specs/user-auth").is_dir()


def test_archive_refuses_an_unfinished_unit(repo):
    provider, unit = make(repo)
    with pytest.raises(ArchiveRefused):
        provider.archive(unit)


def test_validate_reports_missing_files(repo):
    provider, unit = make(repo, exempt_kinds=["docs"])
    report = provider.validate(unit)
    assert report.valid and not report.issues
    (repo / ".kiro/specs/user-auth/tasks.md").unlink()
    broken = provider.validate(unit)
    assert not broken.valid and "tasks.md missing" in [i.message for i in broken.issues]  # SCN-KSP-N7
    (repo / ".kiro/specs/user-auth/requirements.md").unlink()
    (repo / ".kiro/specs/user-auth/design.md").unlink()
    messages = [(i.level, i.message) for i in provider.validate(unit).issues]
    assert ("ERROR", "requirements.md or bugfix.md missing") in messages
    assert ("WARNING", "design.md missing") in messages


def test_dangling_reference_and_bad_graph_and_grammar(repo):
    tasks_path(repo).write_text(
        "- [ ] 1.1 Do it\n  - _Requirements: 9.9_\n1. [ ] ordered\n\n## Task Dependency Graph\n\n```json\n{oops\n```\n"
    )
    provider, unit = make(repo)
    report = provider.validate(unit)
    text = "\n".join(i.message for i in report.issues)
    assert not report.valid
    assert "1.1 cites _Requirements: 9.9_" in text  # SCN-KSP-N6
    assert "Task Dependency Graph" in text
    assert "not a task under Kiro's grammar" in text
    lenient = [i for i in provider.validate(unit, strict=False).issues if "grammar" in i.message]
    assert lenient and lenient[0].level == "WARNING"


def test_leaf_without_requirements_blocks_intake_unless_exempt(tmp_path):
    spec = tmp_path / ".kiro/specs/x"
    spec.mkdir(parents=True)
    (spec / "requirements.md").write_text("### Requirement 1\n#### Acceptance Criteria\n1. WHEN a THEN b\n")
    (spec / "design.md").write_text("d")
    (spec / "tasks.md").write_text(
        "- [ ] 1.1 Linked\n  - _Requirements: 1.1_\n- [ ] 1.2 Naked\n- [ ] 1.3 [docs] Exempt\n"
        "- [ ]* 1.4 Optional naked\n"
    )
    strict, unit = make(tmp_path, enforce=True, exempt_kinds=["docs"])
    report = strict.validate(unit)
    assert [(i.level, i.line) for i in report.issues] == [("ERROR", 3)]  # SCN-KSP-N5: only 1.2
    assert not report.valid
    assert [t.key for t in strict.leaves_without_requirements(unit)] == ["1.2"]
    lax, unit = make(tmp_path, enforce=False, exempt_kinds=["docs"])
    report = lax.validate(unit)
    assert report.valid and [i.level for i in report.issues] == ["WARNING"]


def test_root_must_stay_inside_the_repo(tmp_path):
    for bad in ("/etc", "../x", ""):
        with pytest.raises(SpecError):
            KiroProvider(tmp_path, root=bad)


def test_symlinked_unit_dir_is_refused(repo):
    provider, unit = make(repo)
    outside = repo / "outside"
    outside.mkdir()
    shutil.rmtree(repo / ".kiro/specs/user-auth")
    (repo / ".kiro/specs/user-auth").symlink_to(outside)
    with pytest.raises(SpecError, match="symlink"):
        provider.tasks(unit)
