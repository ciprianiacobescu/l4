"""Regression tests of the independent review of the experience graph (findings 2 to 11; finding 1 is in
`test_partial_clone.py`, finding 10 in `test_boundaries.py`). Each one is a reproduction of the review."""

import contextlib
import io

import pytest

from l4.cli import main
from l4.kg import store

SECRET = "zz9SuperSecretValue42"
HOST = "gitlab.acme-internal.example"


def run_kg(repo, *args, root=None, **env):
    out, err = io.StringIO(), io.StringIO()
    environ = {**repo.environ, "L4_CACHE": str(repo.cache), **env}
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["kg", *args, "--repo", str(root or repo.root)], environ=environ)
    return code, out.getvalue(), err.getvalue()


# --- #2: the forge host is scrubbed everywhere -------------------------------------------------------------------


def test_the_forge_host_is_in_no_text_the_graph_writes_or_shows(kg_repo):
    f = kg_repo.finding
    for name, where in (("a", "branch"), ("b", "archive")):
        kg_repo.unit(
            f"openspec:{name}", where=where,
            runs=[kg_repo.run(
                ("prompt.rendered", {"role": "red", "task": "1.1", "lessons": ["L-09421538"]}),
                ("task.attempt_failed", {"task": "1.1", "phase": "red", "attempt": 1,
                                         "reason": f"token {SECRET} at https://{HOST}/x leaked: details"}),
                ("phase.changed", {"from": "implementing", "to": "halted", "reason": "same_failure",
                                   "detail": f"see https://{HOST}/group/p/-/jobs/1 {SECRET}"}),
            )],
            verdicts=[kg_repo.verdict(1, "FAIL", findings=[f(f"gate at https://{HOST}/p failed"),
                                                           f("Out-of-scope change: src/x.py")])],
        )  # fmt: skip
    kg_repo.lessons(kg_repo.lesson(f"Lesson at https://{HOST}/", "some-key"))
    (kg_repo.root / ".git/info/exclude").write_text(".l4-out/\n.serena/memories/inbox/\n")
    env = {"L4_FORGE_TOKEN": SECRET, "CI_SERVER_URL": f"https://{HOST}"}
    texts = {}
    for args in (("build",), ("report",), ("report", "--out", ".l4-out/kg/r.md"), ("why", "openspec:a"),
                 ("why", "openspec:b"), ("propose", "--min-units", "1")):  # fmt: skip
        code, out, err = run_kg(kg_repo, *args, **env)
        assert code == 0, (args, err)
        texts[" ".join(args)] = out + err
    folder = store.index_dir(kg_repo.app())
    texts.update({f"index/{p.name}": p.read_text() for p in folder.iterdir()})
    texts["--out file"] = (kg_repo.root / ".l4-out/kg/r.md").read_text()
    for path in (kg_repo.root / ".serena/memories/inbox").rglob("*.md"):
        texts[str(path.relative_to(kg_repo.root))] = path.read_text()
    assert any(name.endswith(".evidence.md") for name in texts), "the propose step wrote no evidence file"
    assert [name for name, text in texts.items() if HOST in text] == []
    assert [name for name, text in texts.items() if SECRET in text] == []
    assert "<forge>" in texts["index/nodes.jsonl"] + texts["index/edges.jsonl"]


def test_redact_forge_urls_off_scrubs_nothing(kg_repo, tmp_path):
    kg_repo.unit("openspec:a", where="archive", verdicts=[kg_repo.verdict(
        1, "FAIL", findings=[kg_repo.finding(f"gate at https://{HOST}/p failed")])])
    config = tmp_path / "l4.yaml"
    config.write_text("observability:\n  redact_forge_urls: false\n")
    code, _, err = run_kg(kg_repo, "build", "--config", str(config), CI_SERVER_URL=f"https://{HOST}")
    assert code == 0, err
    folder = store.index_dir(kg_repo.app())
    assert HOST in (folder / "nodes.jsonl").read_text()


# --- #3: a command started in a subdirectory acts on the whole repository -----------------------------------------


@pytest.fixture
def in_subdir(kg_repo):
    kg_repo.unit(
        "openspec:a", where="archive",
        runs=[kg_repo.run(("task.attempt_failed", {"task": "1.1", "phase": "red", "attempt": 1, "reason": "x: y"}))],
        verdicts=[kg_repo.verdict(1, "FAIL", findings=[kg_repo.finding("lint is red")])],
    )  # fmt: skip
    kg_repo.unit("openspec:b", where="branch", runs=[kg_repo.run(("task.red_ok", {"task": "1.1"}))])
    kg_repo._raw(kg_repo.root, "pull", "-q", "origin", "main")
    assert (kg_repo.root / "openspec").is_dir()
    return kg_repo, kg_repo.root / "openspec"


def test_a_subdirectory_reads_the_same_graph_as_the_root(in_subdir):
    repo, sub = in_subdir
    code, out, err = run_kg(repo, "build")
    assert code == 0, err
    from_root = out
    code, out, err = run_kg(repo, "build", root=sub)
    assert code == 0, err
    assert out == from_root
    assert " 2 nodes," not in out


def test_a_cache_root_inside_the_repository_is_refused_from_a_subdirectory(in_subdir):
    """SCN-KG-05"""
    repo, sub = in_subdir
    code, _, err = run_kg(repo, "build", root=sub, L4_CACHE=str(repo.root / ".cache"))
    assert code == 2, err
    assert not (repo.root / ".cache").exists()
    assert repo.status() == ""


def test_an_out_path_inside_the_repository_must_be_ignored_from_a_subdirectory(in_subdir):
    """SCN-KG-19"""
    repo, sub = in_subdir
    code, _, err = run_kg(repo, "report", "--out", "../docs/report.md", root=sub)
    assert code == 2, err
    assert not (repo.root / "docs").exists()
    assert repo.status() == ""
    (repo.root / ".git/info/exclude").write_text(".l4-out/\n")
    code, _, err = run_kg(repo, "report", "--out", "../.l4-out/kg/report.md", root=sub)
    assert code == 0, err
    assert (repo.root / ".l4-out/kg/report.md").is_file()
