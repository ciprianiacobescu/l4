"""L4-OPS-015: a test that a `tests.superseded` event records (a stale test a reopened task's red step replaced) is not
"a pre-existing test was deleted"; it is listed in the note. Every other deleted test is still a blocker."""

from l4.verifier.integrity import check_tests

from ._integrity_helpers import event, new_repo

PLAIN = "def test_one():\n    assert 1\n"


def test_a_recorded_stale_test_is_not_a_deleted_test_and_is_listed(tmp_path, git_environ):
    repo, base = new_repo(tmp_path, git_environ, {"tests/test_a.py": PLAIN, "tests/test_b.py": PLAIN})
    repo.events.append(
        event("tests.superseded", 1, task="1.1", tests=["tests.test_a::test_one"], criteria=["C-0123abcd"])
    )
    repo.delete("tests/test_a.py")
    repo.write({"tests/test_new.py": "def test_new():\n    assert 1\n"})
    out = check_tests(repo.context(base, repo.commit("replace", task="1.1", tdd="red")))
    assert out.findings == []
    assert "superseded" in out.note and "tests/test_a.py::test_one" in out.note


def test_a_test_that_is_not_recorded_stays_a_blocker_beside_a_superseded_one(tmp_path, git_environ):
    repo, base = new_repo(tmp_path, git_environ, {"tests/test_a.py": PLAIN, "tests/test_b.py": PLAIN})
    repo.events.append(
        event("tests.superseded", 1, task="1.1", tests=["tests.test_a::test_one"], criteria=["C-0123abcd"])
    )
    repo.delete("tests/test_a.py", "tests/test_b.py")
    out = check_tests(repo.context(base, repo.commit("replace", task="1.1", tdd="red")))
    [finding] = out.findings
    assert finding.title == "a pre-existing test was deleted"
    assert "tests/test_b.py::test_one" in finding.detail and "test_a.py" not in finding.detail


def test_a_recorded_name_in_another_module_stays_protected(tmp_path, git_environ):
    repo, base = new_repo(tmp_path, git_environ, {"tests/test_a.py": PLAIN, "tests/test_b.py": PLAIN})
    repo.events.append(event("tests.superseded", 1, task="1.1", tests=["tests.test_a::test_one"], criteria=[]))
    repo.delete("tests/test_b.py")
    [finding] = check_tests(repo.context(base, repo.commit("drop b", task="1.1", tdd="red"))).findings
    assert "tests/test_b.py::test_one" in finding.detail
