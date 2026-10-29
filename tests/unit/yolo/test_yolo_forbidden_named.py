"""A task that names a file odd.forbidden_paths forbids (forbidden-path-intake 1.1; L4-YOLO-092; SCN-YOLO-246, 248 to
250 at the function level)."""

from pathlib import Path

from l4.config.defaults import FORBIDDEN_PATHS
from l4.specs.base import Framework, UnitRef
from l4.yolo.forbidden import PathFinding, TreeIndex, forbidden_named

MIGRATION = "app/migrations/0001_initial.py"


def unit(tmp_path: Path, tasks: str, *, design: str = "", proposal: str = "", spec: str = "") -> UnitRef:
    folder = tmp_path / "openspec" / "changes" / "add-x"
    (folder / "specs" / "cap").mkdir(parents=True, exist_ok=True)
    (folder / "tasks.md").write_text(tasks, encoding="utf-8")
    for name, text in (("design.md", design), ("proposal.md", proposal), ("specs/cap/spec.md", spec)):
        if text:
            (folder / name).write_text(text, encoding="utf-8")
    return UnitRef(Framework.OPENSPEC, "add-x", folder)


def missing(path: str) -> bool:
    return False


def tasks_of(*lines: str) -> str:
    return "## 1. Models\n\n" + "\n".join(lines) + "\n"


def blockers(found: list[PathFinding]) -> list[PathFinding]:
    return [f for f in found if f.blocker]


def test_a_missing_migration_in_a_pending_task_is_a_blocker_with_both_fixes(tmp_path):  # SCN-YOLO-246
    ref = unit(tmp_path, tasks_of(f"- [ ] 1.2 Create `{MIGRATION}` for the new model"))
    (found,) = forbidden_named(ref, missing, FORBIDDEN_PATHS)
    assert found.blocker and found.path == MIGRATION and found.rule == "**/migrations/**"
    assert found.message.startswith("forbidden_path: task 1.2 names app/migrations/0001_initial.py,")
    assert "odd.forbidden_paths rule **/migrations/**" in found.message
    assert "no agent step may write it" in found.message
    assert "set odd.forbidden_paths to an explicit list without **/migrations/**" in found.message
    assert "(there is no exclusion syntax)" in found.message
    assert f"have a person commit {MIGRATION} on the base branch first" in found.message


def test_a_bare_path_is_found_as_well_as_a_backticked_one(tmp_path):
    ref = unit(tmp_path, tasks_of(f"- [ ] 1.1 Write {MIGRATION}."))
    assert [f.path for f in blockers(forbidden_named(ref, missing, FORBIDDEN_PATHS))] == [MIGRATION]


def test_a_list_without_the_glob_finds_nothing(tmp_path):  # SCN-YOLO-247 at the function level
    ref = unit(tmp_path, tasks_of(f"- [ ] 1.2 Create `{MIGRATION}`"))
    assert forbidden_named(ref, missing, ("infra/**",)) == []
    assert forbidden_named(ref, missing, ()) == []


def test_an_existing_file_is_a_warning_not_a_blocker(tmp_path):  # SCN-YOLO-248
    ref = unit(tmp_path, tasks_of(f"- [ ] 1.2 Edit `{MIGRATION}` to add a column"))
    (found,) = forbidden_named(ref, lambda path: path == MIGRATION, FORBIDDEN_PATHS)
    assert not found.blocker and found.path == MIGRATION and found.rule == "**/migrations/**"
    assert "task 1.2" in found.body and "exists" in found.body


def test_a_ticked_task_is_not_read(tmp_path):  # SCN-YOLO-248
    ref = unit(tmp_path, tasks_of(f"- [x] 1.2 Create `{MIGRATION}`"))
    assert forbidden_named(ref, missing, FORBIDDEN_PATHS) == []


def test_a_started_task_is_still_pending(tmp_path):
    ref = unit(tmp_path, tasks_of(f"- [ ] 1.2 Create `{MIGRATION}`", "- [x] 1.1 Add the model in app/models.py"))
    assert [f.path for f in blockers(forbidden_named(ref, missing, FORBIDDEN_PATHS))] == [MIGRATION]


def test_a_line_that_says_not_to_touch_the_path_gives_nothing(tmp_path):  # SCN-YOLO-248
    for lead in ("do not touch", "Do not edit", "don't create", "Never write", "must not change", "without writing"):
        ref = unit(tmp_path, tasks_of(f"- [ ] 1.2 Add the field; {lead} `{MIGRATION}`"))
        assert forbidden_named(ref, missing, FORBIDDEN_PATHS) == [], lead


def test_a_negation_after_the_path_does_not_count(tmp_path):
    ref = unit(tmp_path, tasks_of(f"- [ ] 1.2 Create `{MIGRATION}`, do not skip it"))
    assert [f.path for f in blockers(forbidden_named(ref, missing, FORBIDDEN_PATHS))] == [MIGRATION]


def test_a_negation_on_another_line_does_not_count(tmp_path):
    ref = unit(tmp_path, tasks_of("- [ ] 1.2 Do not forget the field.", f"  Create `{MIGRATION}`."))
    assert [f.path for f in blockers(forbidden_named(ref, missing, FORBIDDEN_PATHS))] == [MIGRATION]


def test_the_path_on_a_continuation_line_of_the_task_is_the_tasks_text(tmp_path):
    ref = unit(tmp_path, tasks_of("- [ ] 1.2 Add the model", f"  - create {MIGRATION}", "- [ ] 1.3 Next"))
    (found,) = blockers(forbidden_named(ref, missing, FORBIDDEN_PATHS))
    assert found.message.startswith("forbidden_path: task 1.2 names")


def test_a_directory_token_is_a_warning(tmp_path):  # SCN-YOLO-249
    ref = unit(tmp_path, tasks_of("- [ ] 1.2 Move the files into `infra/`"))
    (found,) = forbidden_named(ref, missing, FORBIDDEN_PATHS)
    assert not found.blocker and found.path == "infra/" and found.rule == "infra/**"
    assert "directory" in found.body


def test_a_path_with_no_extension_is_a_directory_token(tmp_path):
    ref = unit(tmp_path, tasks_of("- [ ] 1.2 Add a folder app/migrations"))
    (found,) = forbidden_named(ref, missing, FORBIDDEN_PATHS)
    assert not found.blocker


def test_a_design_mention_is_a_warning(tmp_path):  # SCN-YOLO-249
    ref = unit(
        tmp_path, tasks_of("- [ ] 1.1 Add the model in app/models.py"), design="Compose lives in infra/compose.yml."
    )
    (found,) = forbidden_named(ref, missing, FORBIDDEN_PATHS)
    assert not found.blocker and found.path == "infra/compose.yml" and "design.md" in found.body


def test_a_proposal_and_a_spec_delta_mention_is_a_warning(tmp_path):
    ref = unit(
        tmp_path,
        tasks_of("- [ ] 1.1 Add the model in app/models.py"),
        proposal=f"Adds {MIGRATION}.",
        spec=f"#### Scenario: x\n- **WHEN** {MIGRATION} runs\n",
    )
    found = forbidden_named(ref, missing, FORBIDDEN_PATHS)
    assert [f.blocker for f in found] == [False, False]
    assert {("proposal.md" in f.body, "spec.md" in f.body) for f in found} == {(True, False), (False, True)}


def test_a_negated_design_mention_gives_nothing(tmp_path):
    ref = unit(tmp_path, tasks_of("- [ ] 1.1 Add app/models.py"), design=f"We never edit {MIGRATION} by hand.")
    assert forbidden_named(ref, missing, FORBIDDEN_PATHS) == []


def test_a_contract_glob_offers_only_the_persons_commit(tmp_path):  # SCN-YOLO-250
    ref = unit(tmp_path, tasks_of("- [ ] 1.2 Add a job in `.github/workflows/new.yml`"))
    (found,) = forbidden_named(ref, missing, FORBIDDEN_PATHS)
    assert found.blocker and found.rule == ".github/workflows/**"
    assert "have a person commit .github/workflows/new.yml on the base branch first" in found.message
    assert "odd.forbidden_paths to an explicit list" not in found.message
    assert "there is no exclusion syntax" not in found.message


def test_a_longer_name_is_a_path_of_its_own(tmp_path):
    ref = unit(tmp_path, tasks_of("- [ ] 1.2 Add app/migrations/0001_initial.py.bak and app/other.py"))
    assert [f.blocker for f in forbidden_named(ref, missing, FORBIDDEN_PATHS)] == [True]  # .bak is a file of its own


def test_one_finding_per_task_and_path(tmp_path):
    ref = unit(tmp_path, tasks_of(f"- [ ] 1.2 Create `{MIGRATION}`, then re-read {MIGRATION}"))
    assert len(forbidden_named(ref, missing, FORBIDDEN_PATHS)) == 1


def test_a_kiro_unit_reads_its_pending_required_leaves(tmp_path):
    folder = tmp_path / ".kiro" / "specs" / "add-x"
    folder.mkdir(parents=True)
    (folder / "tasks.md").write_text(
        f"# Tasks\n\n- [ ] 1. Models\n  - [ ] 1.1 Create `{MIGRATION}`\n  - [ ]* 1.2 Optional: write infra/extra.tf\n"
        "- [x] 2. Done: write infra/main.tf\n",
        encoding="utf-8",
    )
    ref = UnitRef(Framework.KIRO, "add-x", folder)
    found = forbidden_named(ref, missing, FORBIDDEN_PATHS)
    assert [(f.blocker, f.path) for f in found] == [(True, MIGRATION)]
    assert found[0].message.startswith("forbidden_path: task 1.1 names")


def test_a_missing_tasks_file_finds_nothing(tmp_path):
    ref = UnitRef(Framework.OPENSPEC, "add-x", tmp_path / "gone")
    assert forbidden_named(ref, missing, FORBIDDEN_PATHS) == []


# --- review fixes (forbidden-path-intake 4.2) ---


def test_a_dot_slash_path_after_a_negation_gives_nothing(tmp_path):
    for task in (
        "- [ ] 1.2 Add the model; do not create ./app/migrations/0002.py",
        "- [ ] 1.2 Add the model; do not create `./app/migrations/0002.py`",
    ):
        ref = unit(tmp_path, tasks_of(task))
        assert forbidden_named(ref, missing, FORBIDDEN_PATHS) == [], task


def test_a_dot_slash_path_without_a_negation_is_still_a_blocker(tmp_path):
    ref = unit(tmp_path, tasks_of("- [ ] 1.2 Create `./app/migrations/0002.py`"))
    assert [f.path for f in blockers(forbidden_named(ref, missing, FORBIDDEN_PATHS))] == ["app/migrations/0002.py"]


def test_a_token_that_starts_with_a_host_is_not_a_repository_path(tmp_path):
    ref = unit(tmp_path, tasks_of("- [ ] 1.2 See github.com/org/repo/blob/main/app/migrations/0001.py for the shape"))
    assert forbidden_named(ref, missing, FORBIDDEN_PATHS) == []


def test_a_dot_directory_is_not_taken_for_a_host(tmp_path):
    ref = unit(tmp_path, tasks_of("- [ ] 1.2 Add `.github/workflows/new.yml`"))
    assert [f.blocker for f in forbidden_named(ref, missing, FORBIDDEN_PATHS)] == [True]


def test_a_file_that_exists_below_another_directory_is_a_warning(tmp_path):
    ref = unit(tmp_path, tasks_of(f"- [ ] 1.2 In `backend/`, read `{MIGRATION}`"))
    found = forbidden_named(ref, missing, FORBIDDEN_PATHS, nested=lambda path: path == MIGRATION)
    assert [(f.blocker, f.path) for f in found] == [(False, MIGRATION)]
    assert "below another directory" in found[0].body


def test_a_person_who_delivers_the_file_is_not_a_blocker(tmp_path):
    for task in (
        f"- [ ] 1.2 A person commits `{MIGRATION}` first, then add the model",
        f"- [ ] 1.2 Add the model; `{MIGRATION}` is committed by a person",
        f"- [ ] 1.2 Add the model once a person adds {MIGRATION}",
        f"- [ ] 1.2 Add the model; `{MIGRATION}` is Committed By A Person",
    ):
        ref = unit(tmp_path, tasks_of(task))
        assert forbidden_named(ref, missing, FORBIDDEN_PATHS) == [], task


def test_a_person_on_another_line_does_not_exempt_the_path(tmp_path):
    ref = unit(tmp_path, tasks_of("- [ ] 1.1 A person commits the config.", f"  Create `{MIGRATION}`."))
    assert [f.path for f in blockers(forbidden_named(ref, missing, FORBIDDEN_PATHS))] == [MIGRATION]


def test_the_blocker_names_the_way_out_by_rewording_the_task(tmp_path):
    for task, path in (
        (f"- [ ] 1.2 Create `{MIGRATION}`", MIGRATION),
        ("- [ ] 1.2 Add `.github/workflows/new.yml`", ".github/workflows/new.yml"),
    ):
        ref = unit(tmp_path, tasks_of(task))
        (found,) = forbidden_named(ref, missing, FORBIDDEN_PATHS)
        assert f"or reword the task (for example `Do not create {path}`; a person commits it)" in found.message


def test_the_tree_index_answers_files_directories_and_nested_names():
    tree = TreeIndex(lambda: ["app/models.py", "backend/app/migrations/0001_initial.py", "infra/main.tf"])
    assert tree.has("app/models.py") and tree.has("infra") and tree.has("infra/") and tree.has("backend/app")
    assert not tree.has("app/migrations/0001_initial.py") and not tree.has("app/mod") and not tree.has("models.py")
    assert tree.nested("app/migrations/0001_initial.py") and not tree.nested("app/models.py")


def test_a_tree_that_cannot_be_read_falls_back_to_the_files_on_disk(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "models.py").write_text("x\n")

    def broken():
        raise OSError("no git")

    tree = TreeIndex(broken, fallback=lambda path: (tmp_path / path).exists())
    assert tree.has("app/models.py") and not tree.has("app/other.py") and not tree.nested("app/models.py")
