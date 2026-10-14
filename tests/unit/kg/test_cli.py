"""The `l4 kg` handlers (L4-KG-002, L4-KG-009, L4-KG-011; SCN-KG-02, SCN-KG-03, SCN-KG-04, SCN-KG-05, SCN-KG-19,
SCN-KG-21, SCN-KG-22 report part, SCN-KG-23).

The handlers run through `l4.cli.main` on the `kg_repo` fixture, with the real `report`, `why` and `propose`
modules of `l4.kg`.
"""

from pathlib import Path

import pytest

from l4.cli import main
from l4.kg import cli as kg_cli
from l4.kg import store
from l4.kg.store import MANIFEST_FILE, NODES_FILE, index_dir
from l4.redact import Redactor


@pytest.fixture
def seeded(kg_repo):
    """Two units on the base branch, one with a unit branch, a restart and a verdict."""
    kg_repo.unit("openspec:a", runs=[kg_repo.run(("task.red_ok", {"task": "1.1"}))])
    kg_repo.unit(
        "openspec:b",
        where="branch",
        runs=[kg_repo.run(("task.red_ok", {"task": "1.1"}))],
        verdicts=[kg_repo.verdict(1, "FAIL", findings=[kg_repo.finding("lint is red")])],
    )
    return kg_repo


def kg(repo, *args: str, **env: str) -> int:
    environ = {**repo.environ, "L4_CACHE": str(repo.cache), **env}
    return main(["kg", *args, "--repo", str(repo.root)], environ=environ)


def index_files(repo) -> dict[str, bytes]:
    folder = index_dir(repo.app())
    return {path.name: path.read_bytes() for path in sorted(folder.iterdir())}


# --- build ---------------------------------------------------------------------------------------------------------


def test_build_writes_the_index_and_changes_nothing_in_the_repository(seeded, capsys):
    refs, status = seeded.refs(), seeded.status()
    assert kg(seeded, "build") == 0
    out = capsys.readouterr().out
    assert "index built:" in out and "skipped:" in out and "n = " in out
    assert set(index_files(seeded)) == {NODES_FILE, "edges.jsonl", MANIFEST_FILE}
    assert seeded.refs() == refs and seeded.status() == status
    assert not (seeded.root / ".l4").exists()


def test_a_rebuild_is_byte_identical_after_the_folder_was_deleted(seeded):
    """SCN-KG-04"""
    assert kg(seeded, "build") == 0
    first = index_files(seeded)
    folder = index_dir(seeded.app())
    for path in folder.iterdir():
        path.unlink()
    assert kg(seeded, "build") == 0
    assert index_files(seeded) == first
    assert seeded.status() == ""


def test_build_counts_an_attempt_that_is_not_local(kg_repo, capsys):
    kg_repo.unit("openspec:a", where="attempt:1", push=False)
    kg_repo.unit(
        "openspec:a", where="branch", runs=[kg_repo.run(kg_repo.restart_event("openspec:a", 1), ("task.red_ok", {}))]
    )
    assert kg(kg_repo, "build") == 0
    out = capsys.readouterr().out
    assert "attempts not local: 1 (n = 1)" in out
    assert "git fetch origin 'refs/l4/attempts/*:refs/l4/attempts/*'" in out


def test_a_cache_root_inside_the_repository_is_refused(seeded, capsys):
    """SCN-KG-05"""
    inside = seeded.root / ".cache"
    assert kg(seeded, "build", L4_CACHE=str(inside)) == 2
    assert "cache" in capsys.readouterr().err.lower()
    assert not inside.exists()


def test_a_folder_that_is_no_repository_exits_2(tmp_path, git_environ, capsys):
    (tmp_path / "plain").mkdir()
    environ = {**git_environ, "L4_CACHE": str(tmp_path / "c")}
    code = main(["kg", "build", "--repo", str(tmp_path / "plain")], environ=environ)
    assert code == 2
    assert "not a git repository" in capsys.readouterr().err


def test_a_fault_after_the_first_rename_exits_1_and_the_next_read_rebuilds(seeded, monkeypatch, capsys):
    """SCN-KG-03"""
    assert kg(seeded, "build") == 0
    clean = index_files(seeded)
    seeded.unit("openspec:c", runs=[seeded.run(("task.red_ok", {"task": "1.1"}))])  # the refs moved: a new build
    refs, status = seeded.refs(), seeded.status()
    real, calls = store.atomic_write_bytes, []

    def faulty(path, data):
        calls.append(path.name)
        if len(calls) == 2:
            raise OSError("disk full")
        real(path, data)

    with monkeypatch.context() as fault:
        fault.setattr(store, "atomic_write_bytes", faulty)
        assert kg(seeded, "build") == 1
    assert seeded.refs() == refs and seeded.status() == status
    capsys.readouterr()
    assert index_files(seeded) != clean  # nodes.jsonl is the new build's, the manifest the old one
    assert store.read_index(index_dir(seeded.app()), {}).status == "incomplete"
    after_fault = kg_report(seeded, capsys)
    assert "index rebuilt" in after_fault.err
    fresh = index_files(seeded)
    for path in index_dir(seeded.app()).iterdir():
        path.unlink()
    assert kg(seeded, "build") == 0
    assert index_files(seeded) == fresh
    assert kg_report(seeded, capsys).out == after_fault.out


def kg_report(repo, capsys, *args: str):
    capsys.readouterr()
    assert kg(repo, "report", *args) == 0
    return capsys.readouterr()


# --- report, why, propose: the index first ---------------------------------------------------------------------------


def test_report_builds_a_missing_index_and_says_so_on_stderr_only(seeded, capsys):
    got = kg_report(seeded, capsys)
    assert got.out.startswith("# Experience report\n") and "Units: n = 2 units" in got.out
    assert "Base ref: refs/remotes/origin/" in got.out and "committed 20" in got.out  # the date comes from git log
    assert "index rebuilt (no index)" in got.err
    again = kg_report(seeded, capsys)
    assert "index rebuilt" not in again.err and again.out == got.out
    assert "a key needs at least n = 2 units" in got.out  # --min-units defaults to 2


def test_report_rebuilds_when_a_ref_moved_or_the_index_is_damaged(seeded, capsys):
    kg_report(seeded, capsys)
    seeded.unit("openspec:c", runs=[seeded.run(("task.red_ok", {"task": "1.1"}))])
    assert "index rebuilt (refs moved)" in kg_report(seeded, capsys).err
    (index_dir(seeded.app()) / NODES_FILE).write_bytes(b"{}\n")
    assert "index rebuilt (index incomplete)" in kg_report(seeded, capsys).err
    assert "index rebuilt" not in kg_report(seeded, capsys).err


def test_report_passes_min_units_and_rejects_less_than_one(seeded, capsys):
    got = kg_report(seeded, capsys, "--min-units", "5")
    assert "a key needs at least n = 5 units" in got.out
    assert kg(seeded, "report", "--min-units", "0") == 2
    assert "--min-units" in capsys.readouterr().err


def test_all_three_commands_run_with_no_network_and_read_only_git(seeded, monkeypatch):
    """SCN-KG-02: sockets raise, and the recording Git refuses any subcommand outside the read-only list."""
    import socket

    def no_socket(*args, **kwargs):
        raise AssertionError("the network was used")

    monkeypatch.setattr(socket, "socket", no_socket)
    recording = seeded.recording_git()
    monkeypatch.setattr(kg_cli, "Git", lambda repo, environ=None: recording)
    refs = seeded.refs()
    for args in (("build",), ("report",), ("why", "openspec:a"), ("propose", "--dry-run")):
        assert kg(seeded, *args) == 0, args
    assert set(recording.subcommands) <= {"rev-parse", "for-each-ref", "ls-tree", "cat-file", "log", "diff", "config"}
    assert seeded.refs() == refs and seeded.status() == ""


# --- report --out ----------------------------------------------------------------------------------------------------


def ignore(repo, line: str) -> None:
    exclude = repo.root / ".git" / "info" / "exclude"
    exclude.write_text(exclude.read_text(encoding="utf-8") + line + "\n", encoding="utf-8")


def test_a_report_file_that_git_would_commit_is_refused(seeded, capsys):
    """SCN-KG-19"""
    assert kg(seeded, "report", "--out", "docs/report.md") == 2
    assert "docs/report.md is not git-ignored: use .l4-out/kg/ or a path outside the repository" in (
        capsys.readouterr().err
    )
    assert not (seeded.root / "docs").exists()
    assert not index_dir(seeded.app()).exists() or not list(index_dir(seeded.app()).iterdir())


def test_a_tracked_path_is_refused_even_when_a_pattern_matches_it(seeded, capsys):
    seeded.git.run("update-index", "--add", "--cacheinfo", "100644," + seeded.git.write_blob(b"x") + ",keep.md")
    ignore(seeded, "keep.md")
    assert kg(seeded, "report", "--out", "keep.md") == 2
    assert "not git-ignored" in capsys.readouterr().err


def test_an_ignored_path_inside_the_repository_is_written(seeded, capsys):
    ignore(seeded, ".l4-out/")
    assert kg(seeded, "report", "--out", ".l4-out/kg/report.md") == 0
    assert (seeded.root / ".l4-out/kg/report.md").read_text(encoding="utf-8").startswith("# Experience report\n")
    assert capsys.readouterr().out.strip() == "report written to .l4-out/kg/report.md"


def test_a_path_outside_the_repository_is_allowed(seeded, tmp_path):
    target = tmp_path / "elsewhere" / "report.md"
    assert kg(seeded, "report", "--out", str(target)) == 0
    assert target.read_text(encoding="utf-8").startswith("# Experience report")


def test_a_folder_as_out_is_refused(seeded, tmp_path):
    assert kg(seeded, "report", "--out", str(tmp_path)) == 2


# --- why -------------------------------------------------------------------------------------------------------------


def test_why_prints_what_the_module_returns_for_a_unit_in_the_index(seeded, capsys):
    assert kg(seeded, "why", "openspec:a") == 0
    out = capsys.readouterr().out
    assert "openspec:a" in out and "task.red_ok" not in out.split("\n")[0]


def test_why_with_an_id_of_no_accepted_form_lists_the_forms(seeded, capsys):
    """SCN-KG-21"""
    assert kg(seeded, "why", "X-1") == 2
    err = capsys.readouterr().err
    for form in ("openspec:<name>", "F-<8 hex>", "L-<8 hex>", "r-", "<unit>#Q-<n>"):
        assert form in err


def test_why_with_an_id_that_is_not_in_the_index_exits_2(seeded, capsys):
    assert kg(seeded, "why", "openspec:nope") == 2
    assert "not in the index" in capsys.readouterr().err
    assert kg(seeded, "why", "F-00000000") == 2


# --- propose ---------------------------------------------------------------------------------------------------------


def test_propose_passes_the_options_and_writes_nothing_on_a_dry_run(seeded, capsys):
    assert kg(seeded, "propose", "--min-units", "3", "--dry-run") == 0
    assert "no pattern recurs in at least n = 3 units" in capsys.readouterr().out
    assert kg(seeded, "propose", "--min-units", "0") == 2
    assert seeded.status() == ""


# --- redaction and the repository key --------------------------------------------------------------------------------


def test_the_report_text_is_redacted_again(seeded, monkeypatch, capsys):
    """SCN-KG-22, report part: a value of a redaction variable never reaches stdout or the file, even when a later
    change of `report` lets one through."""
    secret = "s3cret-token-value-1234"
    monkeypatch.setattr(kg_cli.report_module, "render", lambda *args, **kwargs: f"leak {secret}\n")
    app = seeded.app()
    app.redactor.adopt(Redactor({"KG_SECRET": secret}))
    assert kg_cli.run_kg_report(app) == 0
    out = capsys.readouterr().out
    assert secret not in out and "leak " in out


def test_two_repositories_never_mix(kg_repo, make_repo, git_environ, tmp_path, monkeypatch):
    """SCN-KG-23"""
    other_root = make_repo("other")
    assert store.repo_key(other_root) != store.repo_key(kg_repo.root)
    kg_repo.unit("openspec:a", runs=[kg_repo.run(("task.red_ok", {"task": "1.1"}))])
    read: list[Path] = []
    real = kg_cli.read_index

    def recording(folder, refs, inputs=None):
        read.append(folder)
        return real(folder, refs, inputs)

    monkeypatch.setattr(kg_cli, "read_index", recording)
    assert kg(kg_repo, "report") == 0
    own = index_dir(kg_repo.app())
    assert read and set(read) == {own}
    assert own.name == store.repo_key(kg_repo.root)


# --- 6.4: end to end -------------------------------------------------------------------------------------------------

LESSONS = ".serena/memories/harness/lessons.md"
INBOX = ".serena/memories/inbox"


def porcelain(repo) -> list[str]:
    out = repo._raw(repo.root, "status", "--porcelain", "--untracked-files=all")
    return [line for line in out.splitlines() if line]


def lessons_cli(repo, *args: str) -> int:
    return main(["lessons", *args, "--repo", str(repo.root)], environ={**repo.environ, "L4_CACHE": str(repo.cache)})


def test_promote_through_the_cli_commits_only_the_lessons_file(seeded):
    """The last leg of 6.4 with a hand-written draft: `--yes` and `--from` reach `promote`, and git shows the inbox
    files before it and nothing after it but one new commit."""
    from l4.memory.lessons import Lesson, LessonsFile, lesson_id, render_lessons

    key = "kg-a-no-new-test-traces"
    lid = lesson_id(key)
    draft = Lesson(lid, "Recurring red failure: no new test traces", key, "Name the criterion in the test name.",
                   ("src/web/**",), source="l4 kg propose 2026-10-14: 2 units, 2 attempts")  # fmt: skip
    folder = seeded.root / INBOX / "kg-2026-10-14"
    folder.mkdir(parents=True)
    (folder / f"{lid}.md").write_text(render_lessons(LessonsFile([draft])), encoding="utf-8")
    (folder / f"{lid}.evidence.md").write_text("units: a, b\n", encoding="utf-8")
    for args in (("build",), ("report",), ("why", "openspec:a"), ("propose", "--dry-run")):
        assert kg(seeded, *args) == 0
    only_inbox = [f"?? {INBOX}/kg-2026-10-14/{lid}.evidence.md", f"?? {INBOX}/kg-2026-10-14/{lid}.md"]
    assert porcelain(seeded) == only_inbox
    before = seeded.sha("HEAD")
    assert lessons_cli(seeded, "promote", lid) == 2  # no terminal and no --yes
    assert seeded.sha("HEAD") == before
    assert lessons_cli(seeded, "promote", lid, "--from", str(folder), "--yes") == 0
    assert porcelain(seeded) == []
    assert seeded._raw(seeded.root, "rev-list", "--count", f"{before}..HEAD").strip() == "1"
    assert seeded._raw(seeded.root, "show", "--name-only", "--format=", "HEAD").split() == [LESSONS]


def test_no_commit_keeps_the_proposal(seeded):
    from l4.memory.lessons import Lesson, LessonsFile, lesson_id, render_lessons

    key = "kg-a-other-class"
    lid = lesson_id(key)
    draft = Lesson(lid, "Recurring red failure: other", key, "Do the other thing.", (), source="l4 kg propose")
    folder = seeded.root / INBOX / "kg-2026-10-14"
    folder.mkdir(parents=True)
    (folder / f"{lid}.md").write_text(render_lessons(LessonsFile([draft])), encoding="utf-8")
    before = seeded.sha("HEAD")
    assert lessons_cli(seeded, "promote", lid, "--yes", "--no-commit") == 0
    assert seeded.sha("HEAD") == before and (folder / f"{lid}.md").exists()
    assert f" M {LESSONS}" in porcelain(seeded) or f"?? {LESSONS}" in porcelain(seeded)


def test_build_report_why_propose_then_promote_on_the_real_modules(kg_repo, capsys):
    """6.4 with the real `report`, `why` and `propose`: a failure class that recurs in two units becomes a draft; a
    person edits it; `l4 lessons promote` makes the one commit."""
    reason = "no new test traces C-e25f06d8: tag your test with the criterion id"
    for name in ("a", "b"):
        failed = ("task.attempt_failed", {"task": "1.1", "phase": "red", "attempt": 1, "reason": reason})
        kg_repo.unit(f"openspec:{name}", where="branch", runs=[kg_repo.run(failed)])
    for args in (("build",), ("report",), ("why", "openspec:a"), ("propose",)):
        assert kg(kg_repo, *args) == 0, args
    capsys.readouterr()
    status = porcelain(kg_repo)
    assert status and all(line.startswith(f"?? {INBOX}/kg-") for line in status)
    drafts = sorted(p for p in (kg_repo.root / INBOX).glob("kg-*/L-*.md") if not p.name.endswith(".evidence.md"))
    assert len(drafts) == 1
    text = drafts[0].read_text(encoding="utf-8")
    assert "TODO(person):" in text
    lines = [
        "Name the criterion id in the test name." if line.startswith("TODO(person):") else line
        for line in text.splitlines()
    ]
    drafts[0].write_text("\n".join(lines) + "\n", encoding="utf-8")
    before = kg_repo.sha("HEAD")
    assert lessons_cli(kg_repo, "promote", drafts[0].stem, "--yes") == 0
    assert porcelain(kg_repo) == []
    assert kg_repo._raw(kg_repo.root, "rev-list", "--count", f"{before}..HEAD").strip() == "1"
