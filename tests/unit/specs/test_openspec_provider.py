import json
from pathlib import Path

import pytest

from l4.doctor.context import CmdResult
from l4.specs.base import (
    Framework,
    Marker,
    MarkerNotAllowed,
    OpenSpecCommandError,
    SpecError,
    SpecProvider,
    UnitRef,
)
from l4.specs.openspec import OpenSpecCli, OpenSpecProvider


def provider(repo: Path, environ: dict[str, str], runner=None) -> OpenSpecProvider:
    cli = OpenSpecCli(repo, environ, runner=runner) if runner else None
    return OpenSpecProvider(repo, environ, cli=cli)


def test_list_units_reads_the_disk_and_skips_archive_hidden_symlinked_and_odd_names(
    tmp_path: Path, make_change, fake_install
):
    repo = tmp_path / "repo"
    for name in ("zeta", "add-login", "archive", ".hidden", "Bad_Name", "with space"):
        make_change(repo, name)
    (repo / "openspec" / "changes" / "stray.md").write_text("not a change")
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / "openspec" / "changes" / "linked").symlink_to(outside)
    (repo / "openspec" / "changes" / "archive" / "2026-10-03-old").mkdir(parents=True)

    units = provider(repo, fake_install).list_units()
    assert [u.id for u in units] == ["openspec:add-login", "openspec:zeta"]
    assert units[0].path == repo / "openspec" / "changes" / "add-login" and units[0].framework is Framework.OPENSPEC
    assert isinstance(provider(repo, fake_install), SpecProvider)
    assert provider(tmp_path / "no-such-repo", fake_install).list_units() == []


def test_load_returns_tasks_and_criteria_without_the_cli(add_farewell, fake_install):
    repo, change = add_farewell
    p = provider(repo, fake_install, runner=lambda *a: pytest.fail("load must not start a process"))
    (unit,) = p.list_units()
    assert p.unit_dir(unit) == change
    loaded = p.load(unit)
    assert loaded.ref == unit
    assert [(t.key, t.done) for t in loaded.tasks] == [
        ("1.1", True), ("1.2", True), ("2.1", False), ("2.2", False), ("2.3", False)
    ]  # fmt: skip
    assert len(loaded.criteria) == 3 and p.criteria(unit) == list(loaded.criteria)


def test_no_tasks_md_means_no_tasks_and_a_symlinked_one_is_refused(tmp_path: Path, make_change, fake_install):
    repo = tmp_path / "repo"
    bare = make_change(repo, "bare")
    p = provider(repo, fake_install)
    unit = UnitRef(Framework.OPENSPEC, "bare", bare)
    assert p.tasks(unit) == []
    secret = tmp_path / "secret.md"
    secret.write_text("- [ ] 1.1 leak\n")
    (bare / "tasks.md").symlink_to(secret)
    with pytest.raises(SpecError, match="symlink"):
        p.tasks(unit)


def test_set_marker_ticks_exactly_one_byte_and_only_for_an_unchecked_box(tmp_path: Path, make_change, fake_install):
    repo = tmp_path / "repo"
    body = (
        b"# Tasks\r\n\r\n- [ ]* 2.3 Add retry\r\n- [] 2.4 empty\r\n- [x] 2.5 done\r\n- [-] 2.6 dash\r\n"
        b"- [ ] 2.7 a\r\n- [ ] 2.7 a\r\n"
    )
    change = make_change(repo, "c", tasks=body)
    p = provider(repo, fake_install)
    unit = UnitRef(Framework.OPENSPEC, "c", change)
    p.set_marker(unit, "L3", Marker.DONE)  # the star makes the title "* 2.3 ...": no leading number
    after = (change / "tasks.md").read_bytes()
    assert [i for i, (a, b) in enumerate(zip(body, after, strict=True)) if a != b] == [body.index(b"[ ]*") + 1]
    assert b"- [x]* 2.3 Add retry\r\n" in after and len(after) == len(body)

    for key, marker, reason in [
        ("L3", Marker.DONE, "already"),  # now [x]
        ("2.4", Marker.DONE, "single"),  # [] cannot be written in one byte
        ("2.5", Marker.DONE, "already"),
        ("2.6", Marker.DONE, "already"),
        ("2.7", Marker.DONE, "ambiguous"),
        ("9.9", Marker.DONE, "no task"),
        ("L3", Marker.IN_PROGRESS, "only"),
    ]:
        before = (change / "tasks.md").read_bytes()
        with pytest.raises(SpecError, match=reason) as err:
            p.set_marker(unit, key, marker)
        assert (change / "tasks.md").read_bytes() == before, key
        assert isinstance(err.value, MarkerNotAllowed) or reason == "no task"


def test_in_progress_marker_is_not_allowed(tmp_path: Path, make_change, fake_install):
    repo = tmp_path / "repo"
    change = make_change(repo, "c", tasks="- [ ] 1.1 a\n")
    p = provider(repo, fake_install)
    for marker in (Marker.IN_PROGRESS, Marker.QUEUED, Marker.NOT_STARTED):
        with pytest.raises(MarkerNotAllowed, match="only"):
            p.set_marker(UnitRef(Framework.OPENSPEC, "c", change), "1.1", marker)
    assert (change / "tasks.md").read_bytes() == b"- [ ] 1.1 a\n"


def test_archive_info_becomes_error(tmp_path: Path, fake_install, replay):
    repo = tmp_path / "repo"
    repo.mkdir()
    runner = replay("validate-modify-missing-strict")
    p = provider(repo, fake_install, runner=runner)
    report = p.validate(UnitRef(Framework.OPENSPEC, "modify-missing", repo), strict=True)
    # the CLI said valid:true with one INFO; L4-OSP-006 turns "Archive would refuse" into an error
    assert report.valid is False
    assert [(i.level, i.path) for i in report.issues] == [("ERROR", "greeting/spec.md")]
    assert report.issues[0].message.startswith("Archive would refuse this delta:")
    assert runner.calls[0][0][2:] == ["validate", "modify-missing", "--strict", "--json"]


def test_validate_maps_valid_invalid_and_warning_results(tmp_path: Path, fake_install, replay):
    repo = tmp_path / "repo"
    repo.mkdir()
    p = provider(
        repo,
        fake_install,
        runner=replay("validate-add-farewell-strict", "validate-broken-change-strict", "validate-no-shall-strict"),
    )
    ref = lambda name: UnitRef(Framework.OPENSPEC, name, repo)  # noqa: E731
    ok = p.validate(ref("add-farewell"))
    assert ok.valid and ok.issues == ()
    broken = p.validate(ref("broken-change"))
    assert not broken.valid
    assert [(i.level, i.path, i.line) for i in broken.issues] == [
        ("INFO", "badcap/spec.md", 6), ("ERROR", "badcap/spec.md", None)
    ]  # fmt: skip
    no_shall = p.validate(ref("no-shall"))  # strict: a WARNING fails the item
    assert not no_shall.valid and [i.level for i in no_shall.issues] == ["WARNING"]


def test_validate_without_strict_omits_the_flag(tmp_path: Path, fake_install, replay):
    repo = tmp_path / "repo"
    repo.mkdir()
    runner = replay("validate-no-shall-nonstrict")
    unit = UnitRef(Framework.OPENSPEC, "no-shall", repo)
    report = provider(repo, fake_install, runner=runner).validate(unit, strict=False)
    assert runner.calls[0][0][2:] == ["validate", "no-shall", "--json"] and report.valid


def test_unknown_item_and_wrong_item_are_provider_errors(tmp_path: Path, fake_install, replay, recorded):
    repo = tmp_path / "repo"
    repo.mkdir()
    unknown = provider(repo, fake_install, runner=replay("validate-unknown"))
    with pytest.raises(OpenSpecCommandError, match="unknown_item"):
        unknown.validate(UnitRef(Framework.OPENSPEC, "nope", repo))
    # a reply about another change must not be taken for this unit's result
    reply = json.dumps(recorded("validate-add-farewell-strict.json"))
    wrong = provider(repo, fake_install, runner=lambda *a: CmdResult(0, reply, ""))
    with pytest.raises(OpenSpecCommandError, match="no result for"):
        wrong.validate(UnitRef(Framework.OPENSPEC, "someone-else", repo))


def test_a_box_that_would_stop_being_a_checkbox_is_not_ticked(tmp_path: Path, make_change, fake_install):
    """OpenSpec counts `- [ ](url)` through its second alternative; `[x](url)` is a link, so the task would vanish."""
    repo = tmp_path / "repo"
    body = b"- [ ](https://x.example) linked\n- [ ][ref] ref\n- [ ] 1.2 normal\n"
    change = make_change(repo, "c", tasks=body)
    p = provider(repo, fake_install)
    unit = UnitRef(Framework.OPENSPEC, "c", change)
    keys = [t.key for t in p.tasks(unit)]
    assert keys[-1] == "1.2" and len(keys) == 3
    for key in keys[:2]:
        with pytest.raises(MarkerNotAllowed, match="checkbox"):
            p.set_marker(unit, key, Marker.DONE)
    assert (change / "tasks.md").read_bytes() == body
    p.set_marker(unit, "1.2", Marker.DONE)
    assert [(t.key, t.done) for t in p.tasks(unit)][-1] == ("1.2", True)


def test_a_symlinked_parent_directory_lists_no_units_and_writes_nothing(tmp_path: Path, make_change, fake_install):
    foreign = tmp_path / "foreign"
    make_change(foreign, "foreign-unit")
    tasks = foreign / "openspec" / "changes" / "foreign-unit" / "tasks.md"
    tasks.write_text("- [ ] 1.1 a\n")
    for link_at, target in (("openspec", foreign / "openspec"), ("openspec/changes", None)):
        repo = tmp_path / ("repo-" + link_at.replace("/", "-"))
        repo.mkdir()
        if target is None:
            (repo / "openspec").mkdir()
            (repo / link_at).symlink_to(foreign / "openspec" / "changes")
        else:
            (repo / link_at).symlink_to(target)
        assert provider(repo, fake_install).list_units() == []
        ref = UnitRef(Framework.OPENSPEC, "foreign-unit", repo / "openspec" / "changes" / "foreign-unit")
        with pytest.raises(SpecError, match="symlink"):
            provider(repo, fake_install).set_marker(ref, "1.1", Marker.DONE)
    assert tasks.read_bytes() == b"- [ ] 1.1 a\n"


DONE_TASKS = "# Tasks\n\n- [x] 1.1 first\n- [X] 1.2 second\n"


def archive_unit(tmp_path: Path, make_change, tasks: str = DONE_TASKS, name: str = "with-extras"):
    repo = tmp_path / "repo"
    return repo, UnitRef(Framework.OPENSPEC, name, make_change(repo, name, tasks=tasks))


def test_done_gate_lists_every_open_task_and_a_unit_without_tasks_fails(tmp_path: Path, make_change, fake_install):
    repo, unit = archive_unit(tmp_path, make_change, "- [x] 1.1 a\n- [ ] 1.2 b\n- [-] 1.3 c\n- [ ]\n")
    gate = provider(repo, fake_install).done_gate(unit)
    assert not gate.passed
    assert [r.split(" ")[1] for r in gate.reasons] == ["1.2", "1.3", "L4"]  # the text-less box has the key L<line>
    ok_repo, ok = archive_unit(tmp_path / "ok", make_change)
    assert provider(ok_repo, fake_install).done_gate(ok) == type(gate)(True, ())
    empty_repo, empty = archive_unit(tmp_path / "empty", make_change, "# Tasks\n")
    assert provider(empty_repo, fake_install).done_gate(empty).reasons == ("the unit has no tasks",)


def test_archive_refuses_before_invoking_cli(tmp_path: Path, make_change, fake_install, replay):
    """SCN-OSP-N4/N5: `archive --yes` archives with open tasks and validates non-strictly, so this is the barrier."""
    from l4.specs.base import ArchiveRefused

    repo, unit = archive_unit(tmp_path, make_change, "- [x] 1.1 a\n- [ ] 1.2 b\n")
    calls = []
    p = provider(repo, fake_install, runner=lambda *a: calls.append(a) or pytest.fail("the CLI must not start"))
    with pytest.raises(ArchiveRefused, match="1.2"):
        p.archive(unit)
    assert calls == []
    # a valid gate but a strict validation failure: validate runs, archive does not
    repo, unit = archive_unit(tmp_path / "b", make_change, name="no-shall")
    runner = replay("validate-no-shall-strict")
    with pytest.raises(ArchiveRefused, match="validation"):
        provider(repo, fake_install, runner=runner).archive(unit)
    assert [c[0][2] for c in runner.calls] == ["validate"]


def test_archive_runs_the_gate_then_strict_validate_then_archive_yes_json_in_utc(
    tmp_path: Path, make_change, fake_install, replay
):
    repo, unit = archive_unit(tmp_path, make_change)
    runner = replay("validate-with-extras-strict", "archive-with-extras-yes-json")
    report = provider(repo, fake_install, runner=runner).archive(unit)
    assert [c[0][2:] for c in runner.calls] == [
        ["validate", "with-extras", "--strict", "--json"], ["archive", "with-extras", "--yes", "--json"]
    ]  # fmt: skip
    assert all(c[2]["TZ"] == "UTC" and c[1] == repo.resolve() for c in runner.calls)
    assert report.archived_as == "2026-10-03-with-extras" and report.specs_updated is True


def test_archive_errors_carry_the_cli_code(tmp_path: Path, make_change, fake_install, replay):
    from l4.specs.base import ArchiveFailed

    repo, unit = archive_unit(tmp_path, make_change)
    runner = replay("validate-with-extras-strict", "archive-target-exists-yes-json")
    with pytest.raises(ArchiveFailed) as caught:
        provider(repo, fake_install, runner=runner).archive(unit)
    assert caught.value.error_code == "archive_target_exists" and "already exists" in str(caught.value)


@pytest.mark.parametrize("name", ["../../etc", "2026-10-03-other", "x/y", ""])
def test_archive_rejects_a_folder_name_that_is_not_the_units_dated_folder(
    tmp_path: Path, make_change, fake_install, name
):
    from l4.specs.base import ArchiveFailed

    repo, unit = archive_unit(tmp_path, make_change)
    valid = json.dumps({"items": [{"id": "with-extras", "valid": True, "issues": []}]})
    reply = json.dumps({"archive": {"change": "with-extras", "archivedAs": name, "specsUpdated": True}})
    replies = iter([CmdResult(0, valid, ""), CmdResult(0, reply, "")])
    p = provider(repo, fake_install, runner=lambda *a: next(replies))
    with pytest.raises(ArchiveFailed, match="archivedAs"):
        p.archive(unit)
