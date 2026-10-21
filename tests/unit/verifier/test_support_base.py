"""detect-test-tamper 4.1 (L4-VER-033): the unit's test-support files at their base versions for a run, restored byte
for byte after."""

import os
import stat
from types import SimpleNamespace

import pytest

from l4.config.schema import L4Config
from l4.vcs.git import Git
from l4.verifier.support_base import SupportPlan, support_at_base, support_plan
from l4.verifier.types import IntegrityCheck, IntegrityReport

from ._integrity_helpers import new_repo

BASE_FILES = {
    "tests/fixtures/data.json": '{"a": 1}\n',
    "tests/helpers/old.py": "OLD = 1\n",
    "tests/helpers/script.sh": "echo base\n",
    "pyproject.toml": "[project]\nname = 'x'\n",
    "pytest.ini": "[pytest]\n",
    "src/code.py": "X = 1\n",
}


def bench(tmp_path, git_environ):
    repo, base = new_repo(tmp_path, git_environ, BASE_FILES)
    (repo.path / "tests/helpers/script.sh").chmod(0o755)
    repo.git("add", "-A")
    repo.git("-c", "user.name=a", "-c", "user.email=a@b.invalid", "commit", "-q", "-m", "mode")
    base = repo.git("rev-parse", "HEAD").strip()
    repo.write(
        {
            "tests/conftest.py": "import pytest\n",
            "tests/fixtures/data.json": '{"a": 2}\n',
            "pyproject.toml": "[project]\nname = 'y'\n",
            "pytest.ini": "[pytest]\naddopts = -q\n",
            "src/code.py": "X = 2\n",
        }
    )
    repo.delete("tests/helpers/old.py")
    (repo.path / "tests/helpers/script.sh").write_text("echo head\n")
    (repo.path / "tests/helpers/script.sh").chmod(0o644)
    (repo.path / "tests/helpers/link.py").symlink_to("../conftest.py")
    head = repo.commit("unit", task="1.1", tdd="red")
    git = Git(repo.path, environ=git_environ)
    wb = SimpleNamespace(worktree=repo.path, git=git)
    return repo, wb, base, head, support_plan(git, L4Config(), base, head, None)


def snapshot(root):
    out = {}
    for p in sorted(root.rglob("*")):
        if ".git" in p.parts or "__pycache__" in p.parts:
            continue
        if p.is_symlink():
            out[p.relative_to(root).as_posix()] = ("link", os.readlink(p))
        elif p.is_file():
            out[p.relative_to(root).as_posix()] = ("file", p.read_bytes(), stat.S_IMODE(p.stat().st_mode))
    return out


def test_the_plan_names_the_support_changes_and_never_runner_config(tmp_path, git_environ):
    _, _, _, _, plan = bench(tmp_path, git_environ)
    assert dict(plan.changes) == {
        "tests/conftest.py": "A",
        "tests/fixtures/data.json": "M",
        "tests/helpers/old.py": "D",
        "tests/helpers/script.sh": "M",
        "tests/helpers/link.py": "A",
    }  # no pyproject.toml, no pytest.ini, no src/code.py
    assert plan.fallback is False and plan.why_not == "step 1 did not run"


def test_extra_support_globs_and_the_l4_directory(tmp_path, git_environ):
    repo, base = new_repo(tmp_path, git_environ, {"a.txt": "1\n"})
    repo.write({"extra/shared.py": "X = 1\n", "tests/helpers/.l4/x.py": "Y = 1\n", "tests/conftest.py": ""})
    head = repo.commit("unit")
    cfg = L4Config(tdd={"extra_test_support_globs": ["extra/**"]})
    plan = support_plan(Git(repo.path, environ=git_environ), cfg, base, head, None)
    assert [p for p, _ in plan.changes] == ["extra/shared.py", "tests/conftest.py"]


def integrity(status, note=""):
    return IntegrityReport(checks=[IntegrityCheck("content scan", status, note)])


def test_the_fallback_needs_a_clean_content_scan_and_says_why_not(tmp_path, git_environ):
    repo, _, base, head, _ = bench(tmp_path, git_environ)
    git = Git(repo.path, environ=git_environ)
    ok = support_plan(git, L4Config(), base, head, integrity("ok", "fine"))
    assert ok.fallback is True and ok.why_not == ""
    skipped = support_plan(git, L4Config(), base, head, integrity("skipped", "not checked: python only"))
    assert skipped.fallback is False
    assert skipped.why_not == "step 1's content scan did not read them: not checked: python only"
    failed = support_plan(git, L4Config(), base, head, integrity("failed", "1 hit(s)"))
    assert failed.fallback is False


def test_inside_the_block_the_files_are_at_the_base_and_after_it_back_byte_for_byte(tmp_path, git_environ):
    repo, wb, base, _, plan = bench(tmp_path, git_environ)
    before, status = snapshot(repo.path), repo.git("status", "--porcelain")
    with support_at_base(wb, base, plan) as reverted:
        assert sorted(reverted) == sorted(p for p, _ in plan.changes)
        assert not (repo.path / "tests/conftest.py").exists()
        link = repo.path / "tests/helpers/link.py"
        assert not link.exists() and not link.is_symlink()
        assert (repo.path / "tests/fixtures/data.json").read_text() == '{"a": 1}\n'
        assert (repo.path / "tests/helpers/old.py").read_text() == "OLD = 1\n"
        assert (repo.path / "tests/helpers/script.sh").read_text() == "echo base\n"
        assert (repo.path / "tests/helpers/script.sh").stat().st_mode & 0o111
        assert (repo.path / "pyproject.toml").read_text() == "[project]\nname = 'y'\n"  # runner config stays
    assert snapshot(repo.path) == before and repo.git("status", "--porcelain") == status


def test_after_an_error_in_the_block_everything_is_back(tmp_path, git_environ):
    repo, wb, base, _, plan = bench(tmp_path, git_environ)
    before = snapshot(repo.path)
    with pytest.raises(ValueError), support_at_base(wb, base, plan):
        raise ValueError("boom")
    assert snapshot(repo.path) == before


def test_a_directory_made_for_a_deleted_file_is_removed_again(tmp_path, git_environ):
    repo, base = new_repo(tmp_path, git_environ, {"tests/helpers/deep/old.py": "OLD = 1\n"})
    repo.delete("tests/helpers/deep/old.py")
    (repo.path / "tests/helpers/deep").rmdir()
    head = repo.commit("unit")
    git = Git(repo.path, environ=git_environ)
    wb = SimpleNamespace(worktree=repo.path, git=git)
    plan = support_plan(git, L4Config(), base, head, None)
    with support_at_base(wb, base, plan):
        assert (repo.path / "tests/helpers/deep/old.py").read_text() == "OLD = 1\n"
    assert not (repo.path / "tests/helpers/deep").exists()


def test_a_parent_that_is_a_link_out_of_the_worktree_is_not_touched(tmp_path, git_environ):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "conftest.py").write_text("OUTSIDE = 1\n")
    repo, base = new_repo(tmp_path, git_environ, {"README.md": "x\n"})
    (repo.path / "tests").symlink_to(outside)
    head = repo.commit("unit")
    wb = SimpleNamespace(worktree=repo.path, git=Git(repo.path, environ=git_environ))
    plan = SupportPlan((("tests/conftest.py", "A"),), False, "")
    with support_at_base(wb, base, plan) as reverted:
        assert reverted == []
        assert (outside / "conftest.py").read_text() == "OUTSIDE = 1\n"
    assert (outside / "conftest.py").read_text() == "OUTSIDE = 1\n"
    assert head


def test_an_empty_plan_touches_nothing(tmp_path, git_environ):
    repo, wb, base, _, _ = bench(tmp_path, git_environ)
    before = snapshot(repo.path)
    with support_at_base(wb, base, SupportPlan()) as reverted:
        assert reverted == [] and snapshot(repo.path) == before


# --- detect-test-tamper 9.1: the revert set of the amendment (design D13 step 3, D16) ---------------------------------


def unit_plan(tmp_path, git_environ, base_files, edits, deletes=(), cfg=None, integrity=None):
    from l4.verifier.support_base import unit_test_plan

    repo, base = new_repo(tmp_path, git_environ, base_files)
    repo.write(edits)
    repo.delete(*deletes)
    head = repo.commit("unit", task="1.1", tdd="red")
    git = Git(repo.path, environ=git_environ)
    return unit_test_plan(git, cfg or L4Config(), base, head, integrity), repo, base, head


def test_the_revert_set_holds_test_and_support_files_and_leaves_data_and_runner_config(tmp_path, git_environ):
    base = {
        "tests/fixtures/data.json": '{"a": 1}\n',
        "tests/test_old.py": "def test_old():\n    assert 1\n",
        "tests/helpers.py": "X = 1\n",
        "pyproject.toml": "[project]\nname = 'x'\n",
        "src/code.py": "X = 1\n",
    }
    edits = {
        "tests/fixtures/data.json": '{"a": 2}\n',  # changed data is reverted
        "tests/fixtures/factory.py": "X = 1\n",  # added code under fixtures/ is reverted
        "fixtures/cart.html": "<p>4 items</p>\n",  # added data stays
        "tests/testdata/new.csv": "a,b\n",  # added data stays
        "tests/checks.py": "def assert_total():\n    return None\n",  # a test-glob file with no test
        "tests/test_new.py": "def test_new():\n    assert 1\n",
        "pyproject.toml": "[project]\nname = 'y'\n",
        "src/code.py": "X = 2\n",
        "tests/.l4/x.py": "X = 1\n",
    }
    plan, *_ = unit_plan(tmp_path, git_environ, base, edits, deletes=["tests/test_old.py"])
    assert dict(plan.changes) == {
        "tests/fixtures/data.json": "M",
        "tests/fixtures/factory.py": "A",
        "tests/checks.py": "A",
        "tests/test_new.py": "A",
        "tests/test_old.py": "D",
    }


def test_extra_globs_count_and_the_fallback_follows_the_scan(tmp_path, git_environ):
    cfg = L4Config(tdd={"extra_test_support_globs": ["extra/**"]})
    plan, *_ = unit_plan(tmp_path, git_environ, {"a.txt": "1\n"}, {"extra/shared.py": "X = 1\n"}, cfg=cfg)
    assert dict(plan.changes) == {"extra/shared.py": "A"}
    assert plan.fallback is False and plan.why_not == "step 1 did not run" and plan.base_sha
    (tmp_path / "ok").mkdir()
    ok, *_ = unit_plan(tmp_path / "ok", git_environ, {"a.txt": "1\n"}, {"extra/s.py": "X\n"}, cfg=cfg,
                       integrity=integrity("ok"))  # fmt: skip
    assert ok.fallback is True


def test_the_runner_keeps_the_support_files_and_helpers_but_not_the_units_test_modules(tmp_path, git_environ):
    from l4.verifier.support_base import runner_support

    edits = {
        "e2e/conftest.py": "import pytest\n",
        "e2e/helpers.py": "X = 1\n",
        "e2e/test_cart.py": "def test_cart():\n    assert 1\n",
        "e2e/test_utils.py": "def fetch():\n    return 1\n",  # named like a test module, defines no test
        "e2e/cart.spec.ts": "export {};\n",
        "tests/fixtures/factory.py": "X = 1\n",
    }
    plan, repo, *_ = unit_plan(tmp_path, git_environ, {"a.txt": "1\n"}, edits)
    assert {p for p, _ in runner_support(plan, L4Config(), Git(repo.path, environ=git_environ)).changes} == {
        "e2e/conftest.py",
        "e2e/helpers.py",
        "e2e/test_utils.py",
        "tests/fixtures/factory.py",
    }
    assert runner_support(plan, L4Config(), Git(repo.path, environ=git_environ)).base_sha == plan.base_sha


def test_a_link_original_is_restored_in_the_tree_when_the_block_repoints_a_directory_link(tmp_path, git_environ):
    outside = tmp_path / "outside"
    outside.mkdir()
    repo, base = new_repo(tmp_path, git_environ, {"pkg/conftest.py": "BASE = 1\n"})
    repo.delete("pkg/conftest.py")
    (repo.path / "pkg").rmdir()
    (repo.path / "src/pkg").mkdir(parents=True)
    (repo.path / "src/pkg/real.py").write_text("REAL = 1\n")
    (repo.path / "src/pkg/conftest.py").symlink_to("real.py")
    (repo.path / "pkg").symlink_to("src/pkg")
    repo.commit("unit")
    git = Git(repo.path, environ=git_environ)
    wb = SimpleNamespace(worktree=repo.path, git=git, refused_write=lambda exc, **kw: None)
    plan = support_plan(git, L4Config(), base, git.run("rev-parse", "HEAD").stdout.strip(), None)
    before = snapshot(repo.path)
    failure = None
    try:
        with support_at_base(wb, base, plan):
            (repo.path / "pkg").unlink()
            (repo.path / "pkg").symlink_to(str(outside))
    except RuntimeError as exc:
        failure = exc
    assert sorted(outside.iterdir()) == []  # nothing is created outside the work tree
    assert failure is None  # the canonical file is inside the tree and comes back; `pkg` is not the harness's to fix
    assert (repo.path / "src/pkg/conftest.py").is_symlink()
    assert os.readlink(repo.path / "src/pkg/conftest.py") == "real.py"
    assert before["src/pkg/real.py"] == snapshot(repo.path)["src/pkg/real.py"]


def test_two_plan_paths_with_one_canonical_file_restore_it_once_and_exactly(tmp_path, git_environ):
    repo, base = new_repo(tmp_path, git_environ, {"pkg/conftest.py": "BASE = 1\n"})
    repo.delete("pkg/conftest.py")
    (repo.path / "pkg").rmdir()
    (repo.path / "src/pkg").mkdir(parents=True)
    (repo.path / "src/pkg/conftest.py").write_text("HEAD = 1\n")
    (repo.path / "pkg").symlink_to("src/pkg")
    repo.commit("unit")
    git = Git(repo.path, environ=git_environ)
    wb = SimpleNamespace(worktree=repo.path, git=git, refused_write=lambda exc, **kw: None)
    plan = support_plan(git, L4Config(), base, git.run("rev-parse", "HEAD").stdout.strip(), None)
    assert {p for p, _ in plan.changes} >= {"pkg/conftest.py", "src/pkg/conftest.py"}
    before = snapshot(repo.path)
    with support_at_base(wb, base, plan):
        pass
    assert snapshot(repo.path) == before


def test_a_link_original_that_is_not_back_as_recorded_fails_the_restore(tmp_path, git_environ, monkeypatch):
    repo, base = new_repo(tmp_path, git_environ, {"tests/conftest.py": "BASE = 1\n"})
    repo.delete("tests/conftest.py")
    (repo.path / "tests/real.py").write_text("R = 1\n")
    (repo.path / "tests/conftest.py").symlink_to("real.py")
    repo.commit("unit")
    git = Git(repo.path, environ=git_environ)
    refused = []
    wb = SimpleNamespace(worktree=repo.path, git=git, refused_write=lambda exc, **kw: refused.append(kw))
    plan = support_plan(git, L4Config(), base, git.run("rev-parse", "HEAD").stdout.strip(), None)
    monkeypatch.setattr("l4.verifier.support_base.confined.put_entry", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="could not restore conftest.py"), support_at_base(wb, base, plan):
        pass
