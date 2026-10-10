from l4.implementer.prompt import collect_sources
from l4.implementer.tasks import questions_hold, required, select_next_step, tick_completed_parents, unselectable
from l4.specs.base import Framework, Marker, UnitRef
from l4.specs.kiro import KiroProvider, kiro_tasks

TASKS = (
    b"- [ ] 1. A\n  - [ ] 1.1 first in the file\n  - [ ]* 1.2 optional\n- [ ] 2. B\n  - [ ] 2.1 second in the file\n"
    b"\n## Task Dependency Graph\n\n```json\n"
    b'{"waves": [{"id": 0, "tasks": ["2.1"]}, {"id": 1, "tasks": ["1.1"]}]}\n```\n'
)


def test_the_next_step_follows_the_waves_not_the_document():
    tasks = kiro_tasks(TASKS)
    assert select_next_step(tasks).key == "2.1"
    assert select_next_step(tasks, {"2.1"}).key == "1.1"
    assert [t.key for t in required(tasks)] == ["1", "1.1", "2", "2.1"]


def test_without_a_graph_the_document_order_stands():
    assert select_next_step(kiro_tasks(TASKS.split(b"\n## Task")[0])).key == "1.1"


def test_an_optional_task_with_an_odd_marker_is_not_reported_as_unselectable():
    tasks = kiro_tasks(b"- [x] 1. A\n  - [x] 1.1 a\n  - [-]* 1.2 started by a human\n")
    assert unselectable(tasks) == [] and select_next_step(tasks) is None


def test_a_task_kiro_ide_marked_started_or_queued_is_selectable():
    tasks = kiro_tasks(b"- [ ] 1. A\n  - [-] 1.1 started in the IDE\n  - [~] 1.2 queued in the IDE\n")
    assert unselectable(tasks) == []
    assert select_next_step(tasks).key == "1.1"
    assert select_next_step(tasks, {"1.1"}).key == "1.2"


def test_a_kiro_unit_s_requirements_and_bugfix_files_are_prompt_sources(tmp_path):
    for name in ("requirements.md", "design.md", "tasks.md"):
        (tmp_path / name).write_text(name)
    assert [path for path, _ in collect_sources(tmp_path)] == ["design.md", "requirements.md"]


ONLY_OPTIONAL = b"- [ ] 1. Parent\n  - [ ]* 1.1 optional a\n  - [ ]* 1.2 optional b\n- [ ] 2. Real\n  - [ ] 2.1 leaf\n"


def _unit(tmp_path, data: bytes):
    directory = tmp_path / ".kiro" / "specs" / "u"
    directory.mkdir(parents=True)
    (directory / "tasks.md").write_bytes(data)
    return KiroProvider(tmp_path), UnitRef(Framework.KIRO, "u", directory)


def test_a_parent_with_only_optional_children_is_not_a_leaf_and_is_never_selected():
    tasks = kiro_tasks(ONLY_OPTIONAL)
    assert select_next_step(tasks).key == "2.1"
    done = kiro_tasks(b"- [ ] 1. Parent\n  - [ ]* 1.1 optional\n")
    assert select_next_step(done) is None and not questions_hold(done, {"1"})


def test_a_parent_with_only_optional_children_is_closed_vacuously_changing_only_its_own_byte(tmp_path):
    provider, ref = _unit(tmp_path, ONLY_OPTIONAL)
    path = tmp_path / ".kiro/specs/u/tasks.md"
    before = path.read_bytes()
    assert tick_completed_parents(provider, ref) == ["1"]
    after = path.read_bytes()
    marker = {t.key: t.marker_offset for t in kiro_tasks(before)}["1"]
    assert [i for i, (a, b) in enumerate(zip(before, after, strict=True)) if a != b] == [marker]
    assert tick_completed_parents(provider, ref) == []
    tasks = {t.key: t.marker_char for t in provider.tasks(ref)}
    assert tasks == {"1": "x", "1.1": " ", "1.2": " ", "2": " ", "2.1": " "}


def test_ticking_a_leaf_also_closes_the_vacuous_parent_and_the_normal_parent_behaves_as_before(tmp_path):
    provider, ref = _unit(tmp_path, ONLY_OPTIONAL)
    provider.set_marker(ref, "2.1", Marker.DONE)
    assert {t.key: t.marker_char for t in provider.tasks(ref)} == {
        "1": "x", "1.1": " ", "1.2": " ", "2": "x", "2.1": "x",
    }  # fmt: skip


def test_an_all_optional_branch_under_an_optional_parent_stays_open(tmp_path):
    data = b"- [ ]* 1. Optional parent\n  - [ ] 1.1 inherits optional\n- [ ] 2. R\n  - [ ] 2.1 x\n"
    provider, ref = _unit(tmp_path, data)
    assert tick_completed_parents(provider, ref) == []
