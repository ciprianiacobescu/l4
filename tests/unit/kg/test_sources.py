"""`kg.sources.collect`: what the build reads out of committed git objects, and what it skips (L4-KG-004, L4-KG-002)."""

import re

import pytest

from l4.kg import sources
from l4.kg.sources import FETCH_ATTEMPTS, Collected, UnitRecord, collect
from l4.memory.lessons import HEADER_LINE

from .conftest import Symlink


def build(kg_repo, **kw) -> Collected:
    return collect(kg_repo.recording_git(), kg_repo.cfg, **kw)


def by_id(found: Collected) -> dict[tuple[str, int], UnitRecord]:
    return {(u.unit_id, u.attempt): u for u in found.units}


def run_types(unit: UnitRecord) -> list[str]:
    return [s.event.type for s in unit.events]


# --- 2.2: the base walker ------------------------------------------------------------------------------------------


def test_archived_and_open_units_are_both_read(kg_repo):
    """SCN-KG-06 (the archive part): an archive folder is a unit, with its runs and rounds."""
    kg_repo.unit(
        "openspec:a",
        where="archive",
        runs=[kg_repo.run(("task.red_ok", {"task": "1.1"}))],
        verdicts=[kg_repo.verdict(1, "FAIL"), kg_repo.verdict(2, "PASS")],
    )
    kg_repo.unit("openspec:c", where="base")
    found = build(kg_repo)
    units = by_id(found)
    a = units[("openspec:a", 0)]
    assert a.places == ("archive",)
    assert "task.red_ok" in run_types(a)
    assert sorted(v.round for v in a.verdicts) == [1, 2]
    assert units[("openspec:c", 0)].places == ("base",)
    assert found.skipped == {}


def test_every_archive_folder_of_a_name_is_read_not_only_the_newest(kg_repo):
    kg_repo.unit("openspec:a", where="archive", date="2026-09-01", runs=[kg_repo.run(("x.old", {}))])
    kg_repo.unit("openspec:a", where="archive", date="2026-10-01", runs=[kg_repo.run(("x.new", {}))])
    a = by_id(build(kg_repo))[("openspec:a", 0)]
    assert {"x.old", "x.new"} <= set(run_types(a))
    assert len({s.event.run_id for s in a.events}) == 2


def test_kiro_units_are_read_from_the_kiro_root(kg_repo):
    kg_repo.unit("kiro:k", where="base", runs=[kg_repo.run(("x.kiro", {}))])
    units = by_id(build(kg_repo))
    assert ("kiro:k", 0) in units and units[("kiro:k", 0)].framework == "kiro"
    assert "x.kiro" in run_types(units[("kiro:k", 0)])


def test_the_archive_folder_is_not_a_unit_named_archive(kg_repo):
    kg_repo.unit("openspec:a", where="archive")
    assert {u.unit_id for u in build(kg_repo).units} == {"openspec:a"}


def test_the_base_ref_is_the_remote_tracking_branch_with_its_sha_and_date(kg_repo):
    sha = kg_repo.unit("openspec:a", where="base")
    found = build(kg_repo)
    assert found.base_ref == "refs/remotes/origin/main"
    assert found.base_sha == sha
    assert re.match(r"\d{4}-\d\d-\d\dT", found.base_date or "")
    assert found.warnings == []


def test_without_the_remote_tracking_branch_head_is_read_with_a_warning(kg_repo):
    kg_repo.unit("openspec:a", where="base")
    kg_repo.git.run("update-ref", "-d", "refs/remotes/origin/main")
    found = build(kg_repo)
    assert found.base_ref == "HEAD"
    assert any("HEAD" in w for w in found.warnings)


# --- 2.3: unit branches and the lock ref ---------------------------------------------------------------------------


def test_a_unit_that_is_only_on_its_branch_is_read_from_the_branch(kg_repo):
    kg_repo.unit("openspec:b", where="branch", runs=[kg_repo.run(("x.branch", {}))], verdicts=[kg_repo.verdict(1)])
    found = build(kg_repo)
    b = by_id(found)[("openspec:b", 0)]
    assert b.places == ("branch",)
    assert "x.branch" in run_types(b)
    assert [v.round for v in b.verdicts] == [1]


def test_the_pending_ledger_extends_the_branch_copy(kg_repo):
    run_id = "r-20261001T0900Z-00aa"
    kg_repo.unit("openspec:b", where="branch", runs=[kg_repo.run(("x.one", {}), run_id=run_id)])
    kg_repo.pending("openspec:b", ("x.two", {}), run_id="r-20261001T0910Z-00bb")
    b = by_id(build(kg_repo))[("openspec:b", 0)]
    assert b.places == ("branch", "lock")
    assert {"x.one", "x.two"} <= set(run_types(b))
    two = next(s for s in b.events if s.event.type == "x.two")
    assert two.origin.kind == "lock" and two.origin.path.startswith("ledger-pending/")


def test_a_unit_on_the_base_and_on_its_branch_is_one_unit(kg_repo):
    kg_repo.unit("openspec:b", where="base")
    kg_repo.unit("openspec:b", where="branch", runs=[kg_repo.run(("x.branch", {}))])
    units = [u for u in build(kg_repo).units if u.unit_id == "openspec:b"]
    assert len(units) == 1 and units[0].places == ("base", "branch")


def test_a_branch_and_the_base_copy_of_one_run_give_each_event_once(kg_repo):
    run = kg_repo.run(("x.same", {}), run_id="r-20261001T0900Z-00aa")
    kg_repo.unit("openspec:b", where="branch", runs=[run])
    kg_repo.unit("openspec:b", where="base", runs=[run])
    b = by_id(build(kg_repo))[("openspec:b", 0)]
    keys = [(s.event.run_id, s.event.seq) for s in b.events]
    assert len(keys) == len(set(keys))


def test_fix_unit_folders_belong_to_their_parent(kg_repo):
    kg_repo.unit("openspec:b", where="branch", runs=[kg_repo.run(("x.parent", {}))], verdicts=[kg_repo.verdict(1)])
    kg_repo.unit("openspec:b", where="branch", fix=1, verdicts=[kg_repo.verdict(1, "PASS")])
    found = build(kg_repo)
    assert {u.unit_id for u in found.units} == {"openspec:b"}
    b = by_id(found)[("openspec:b", 0)]
    assert b.folders == ("b", "b-fix-1")
    assert sorted((v.folder, v.round) for v in b.verdicts) == [("b", 1), ("b-fix-1", 1)]


def test_a_branch_outside_the_unit_namespace_is_not_a_unit(kg_repo):
    kg_repo.commit("l4/archive/openspec/a", {"x.txt": "1"})
    kg_repo.commit("feature/y", {"y.txt": "1"})
    assert build(kg_repo).units == []


# --- 2.4: attempts ---------------------------------------------------------------------------------------------------


def test_a_restarted_unit_keeps_its_old_attempt(kg_repo):
    """SCN-KG-07"""
    kg_repo.unit("openspec:a", where="attempt:1", runs=[kg_repo.run(("x.old", {}))], verdicts=[kg_repo.verdict(1)])
    kg_repo.unit(
        "openspec:a",
        where="branch",
        runs=[kg_repo.run(kg_repo.restart_event("openspec:a", 1), ("x.new", {}))],
        verdicts=[kg_repo.verdict(1, "PASS")],
    )
    found = build(kg_repo)
    units = by_id(found)
    assert set(units) == {("openspec:a", 0), ("openspec:a", 1)}
    assert "x.old" in run_types(units[("openspec:a", 1)]) and "x.new" not in run_types(units[("openspec:a", 1)])
    assert "x.new" in run_types(units[("openspec:a", 0)])
    assert units[("openspec:a", 1)].places == ("attempt",)
    assert [v.round for v in units[("openspec:a", 1)].verdicts] == [1]
    assert found.skipped == {} and found.not_local == []


def test_an_attempt_that_is_not_local_is_counted_and_never_fetched(kg_repo):
    """SCN-KG-09"""
    kg_repo.unit("openspec:a", where="attempt:1", push=False)
    kg_repo.unit("openspec:a", where="branch", runs=[kg_repo.run(kg_repo.restart_event("openspec:a", 1))])
    recording = kg_repo.recording_git()
    found = collect(recording, kg_repo.cfg)
    assert found.skipped == {"attempt_not_local": 1}
    assert found.not_local == ["refs/l4/attempts/openspec/a/1"]
    assert "fetch" not in recording.subcommands
    assert FETCH_ATTEMPTS == "git fetch origin 'refs/l4/attempts/*:refs/l4/attempts/*'"
    assert [u.attempt for u in found.units] == [0]


def test_a_restart_event_naming_a_foreign_ref_is_not_followed(kg_repo):
    kg_repo.unit(
        "openspec:a",
        where="branch",
        runs=[kg_repo.run(("unit.restarted", {"attempt": 1, "attempt_ref": "refs/heads/main"}))],
    )
    found = build(kg_repo)
    assert found.skipped.get("attempt_not_local", 0) == 0


def test_attempts_are_numbered_by_their_ref(kg_repo):
    kg_repo.unit("openspec:a", where="attempt:2")
    kg_repo.unit("openspec:a", where="attempt:1")
    assert sorted(a for (_, a) in by_id(build(kg_repo))) == [1, 2]


# --- 2.5: skips, never fatal ----------------------------------------------------------------------------------------


def test_corrupt_and_unsafe_inputs_are_skipped_and_counted(kg_repo):
    """SCN-KG-08"""
    good = kg_repo.run(("x.good", {}))
    rel_a = kg_repo.unit_path("openspec:a")
    kg_repo.unit(
        "openspec:a",
        where="base",
        runs=[good],
        files={f"{rel_a}/.l4/ledger/r-20261001T0001Z-0001.jsonl": '{"seq": 1}\nnot json\n{"seq": 3}\n'},
    )
    rel_b = kg_repo.unit_path("openspec:b")
    kg_repo.unit(
        "openspec:b",
        where="base",
        runs=[kg_repo.run(("x.b", {}))],
        files={f"{rel_b}/.l4/evidence/round-1": Symlink("/etc")},
    )
    found = build(kg_repo)
    assert found.skipped == {"ledger_corrupt": 1, "not_regular": 1}
    units = by_id(found)
    assert "x.good" in run_types(units[("openspec:a", 0)])
    assert "x.b" in run_types(units[("openspec:b", 0)])
    assert units[("openspec:b", 0)].verdicts == []
    assert {s.reason for s in found.skips} == {"ledger_corrupt", "not_regular"}


def test_an_unreadable_verdict_is_skipped(kg_repo):
    kg_repo.unit(
        "openspec:a",
        where="base",
        verdicts=[
            kg_repo.verdict(1, raw=b"{not json"),
            kg_repo.verdict(2, raw=b'{"schema": "other@1", "round": 2}'),
            kg_repo.verdict(3, raw=b"[1]"),
            kg_repo.verdict(4, "PASS"),
        ],
    )
    found = build(kg_repo)
    assert found.skipped == {"verdict_unreadable": 3}
    assert [v.round for v in by_id(found)[("openspec:a", 0)].verdicts] == [4]


def test_an_oversized_ledger_is_skipped_as_oversize(kg_repo, monkeypatch):
    monkeypatch.setattr(sources, "MAX_LEDGER_FILE_BYTES", 200)
    kg_repo.unit("openspec:a", where="base", runs=[kg_repo.run(*[("x.pad", {"pad": "y" * 50})] * 10)])
    found = build(kg_repo)
    assert found.skipped == {"oversize": 1}
    assert by_id(found)[("openspec:a", 0)].events == []


def test_a_symlinked_ledger_file_is_not_followed(kg_repo):
    rel = kg_repo.unit_path("openspec:a")
    kg_repo.unit(
        "openspec:a", where="base", files={f"{rel}/.l4/ledger/r-20261001T0001Z-0001.jsonl": Symlink("/etc/hosts")}
    )
    found = build(kg_repo)
    assert found.skipped == {"not_regular": 1}


def test_an_exception_inside_one_unit_skips_only_that_unit(kg_repo, monkeypatch):
    kg_repo.unit("openspec:a", where="base", runs=[kg_repo.run(("x.a", {}))])
    kg_repo.unit("openspec:b", where="base", runs=[kg_repo.run(("x.b", {}))])
    real = sources._read_ledger_file

    def boom(*args, **kw):
        if "changes/a/" in args[2]:
            raise RuntimeError("boom")
        return real(*args, **kw)

    monkeypatch.setattr(sources, "_read_ledger_file", boom)
    found = build(kg_repo)
    assert found.skipped == {"error": 1}
    assert {u.unit_id for u in found.units} == {"openspec:b"}


def test_an_empty_repository_gives_an_empty_collection(kg_repo):
    found = build(kg_repo)
    assert found.units == [] and found.lessons == [] and found.skipped == {}


# --- 2.6: lessons ---------------------------------------------------------------------------------------------------


def test_the_lessons_file_and_its_archive_are_read_at_the_base(kg_repo):
    kg_repo.lessons(kg_repo.lesson("One", "key-one", scope=["src/**"]), kg_repo.lesson("Two", "key-two"))
    kg_repo.lessons(kg_repo.lesson("Old", "key-old"), archive="L-00000001")
    found = build(kg_repo)
    assert sorted((r.lesson.title, r.archived) for r in found.lessons) == [
        ("Old", True),
        ("One", False),
        ("Two", False),
    ]
    one = next(r for r in found.lessons if r.lesson.title == "One")
    assert one.lesson.scope_globs == ("src/**",) and one.origin.kind == "base"
    assert one.origin.path == kg_repo.cfg.memory.lessons_file


def test_a_lessons_file_with_problems_counts_and_keeps_what_parsed(kg_repo):
    good = kg_repo.lesson("Good", "key-good")
    text = (
        HEADER_LINE
        + "\n\n## L-deadbeef · Bad\n- **Scope:** `x`\n\nno dedupe key here\n\n"
        + "## "
        + good.id
        + " · Good\n- **Dedupe key:** key-good\n- **Source:** s\n\nUse the helper.\n"
    )
    kg_repo.lessons(text=text)
    found = build(kg_repo)
    assert found.skipped == {"lessons_problem": 1}
    assert [r.lesson.title for r in found.lessons] == ["Good"]


def test_no_lessons_file_is_no_lessons_and_no_skip(kg_repo):
    kg_repo.unit("openspec:a", where="base")
    found = build(kg_repo)
    assert found.lessons == [] and found.skipped == {}


# --- the read-only rule, provenance, determinism --------------------------------------------------------------------


def test_collect_runs_only_read_only_git(kg_repo):
    kg_repo.unit("openspec:a", where="archive", runs=[kg_repo.run(("x.e", {}))], verdicts=[kg_repo.verdict(1)])
    kg_repo.unit("openspec:b", where="branch", runs=[kg_repo.run(("x.e", {}))])
    kg_repo.pending("openspec:b", ("y.e", {}))
    kg_repo.unit("openspec:b", where="attempt:1")
    kg_repo.lessons(kg_repo.lesson("One", "key-one"))
    before = kg_repo.refs()
    recording = kg_repo.recording_git()
    collect(recording, kg_repo.cfg)
    assert set(recording.subcommands) <= {"for-each-ref", "ls-tree", "cat-file", "rev-parse", "log"}
    assert kg_repo.refs() == before and kg_repo.status() == ""


def test_the_recording_git_refuses_a_fetch(kg_repo):
    with pytest.raises(AssertionError, match="fetch"):
        kg_repo.recording_git().run("fetch", "origin")


def test_every_source_pointer_resolves(kg_repo):
    """SCN-KG-10 (the reading side): `<sha10>:<path>` names a blob, the line `seq` holds the event, the pointer of a
    verdict names the file."""
    import json

    kg_repo.unit("openspec:a", where="archive", runs=[kg_repo.run(("x.a", {"k": 1}))], verdicts=[kg_repo.verdict(1)])
    kg_repo.unit("openspec:b", where="branch", runs=[kg_repo.run(("x.b", {}))], verdicts=[kg_repo.verdict(2)])
    kg_repo.pending("openspec:b", ("x.p", {}))
    kg_repo.unit("openspec:b", where="attempt:1", runs=[kg_repo.run(("x.old", {}))])
    found = build(kg_repo)
    assert found.units
    for unit in found.units:
        for s in unit.events:
            lines = kg_repo.git.run("show", f"{s.origin.sha}:{s.origin.path}").stdout.splitlines()
            assert json.loads(lines[s.event.seq - 1])["seq"] == s.event.seq
            assert s.src == f"{s.origin.sha[:10]}:{s.origin.path}#{s.event.seq}"
        for v in unit.verdicts:
            data = json.loads(kg_repo.git.run("show", f"{v.origin.sha}:{v.origin.path}").stdout)
            assert data["round"] == v.data["round"] == v.round
            assert v.src("/round") == f"{v.origin.sha[:10]}:{v.origin.path}#/round"


def test_a_rebuild_gives_the_same_collection(kg_repo):
    kg_repo.unit("openspec:a", where="archive", runs=[kg_repo.run(("x.e", {}))], verdicts=[kg_repo.verdict(1)])
    kg_repo.unit("openspec:b", where="branch", runs=[kg_repo.run(("x.e", {}))])
    kg_repo.pending("openspec:b", ("y.e", {}))
    first, second = build(kg_repo), build(kg_repo)
    assert first == second
    assert first.refs == second.refs and first.refs
    assert [(u.unit_id, u.attempt) for u in first.units] == sorted((u.unit_id, u.attempt) for u in first.units)


def test_ref_shas_is_what_collect_records(kg_repo):
    """`read_index` compares the manifest's refs with these to say `stale`."""
    kg_repo.unit("openspec:b", where="branch", runs=[kg_repo.run(("x.e", {}))])
    kg_repo.pending("openspec:b", ("y.e", {}))
    kg_repo.unit("openspec:b", where="attempt:1")
    git = kg_repo.recording_git()
    assert sources.ref_shas(git, kg_repo.cfg) == collect(git, kg_repo.cfg).refs
    assert set(sources.ref_shas(git, kg_repo.cfg)) >= {
        "refs/remotes/origin/main",
        "refs/remotes/origin/l4/openspec/b",
        "refs/l4/locks/openspec/b",
        "refs/l4/attempts/openspec/b/1",
    }


def test_the_verdict_schema_is_the_one_the_verifier_writes():
    from l4.verifier.report import VERDICT_SCHEMA_ID

    assert sources.VERDICT_SCHEMA == VERDICT_SCHEMA_ID
