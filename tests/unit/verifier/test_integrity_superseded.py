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


CHANGED = "def test_one():\n    assert 2\n"


def test_a_test_named_by_the_task_text_is_allowed_and_listed_with_its_source(tmp_path, git_environ):  # SCN-IMP-400
    repo, base = new_repo(tmp_path, git_environ, {"tests/test_a.py": PLAIN, "tests/test_b.py": PLAIN})
    repo.events.append(
        event(
            "tests.superseded",
            1,
            task="1.1",
            tests=["tests.test_a::test_one"],
            criteria=[],
            reason="named_by_task",
            source="plan:p1@abc",
        )
    )
    repo.write({"tests/test_a.py": CHANGED})
    out = check_tests(repo.context(base, repo.commit("rewrite in place", task="1.1", tdd="red")))
    assert out.findings == []
    assert "tests.test_a::test_one (named by the task text, plan:p1@abc)" in out.note
    assert "superseded by a changed criterion" not in out.note


def test_a_stale_test_is_listed_as_before_beside_a_named_one(tmp_path, git_environ):
    repo, base = new_repo(tmp_path, git_environ, {"tests/test_a.py": PLAIN, "tests/test_b.py": PLAIN})
    repo.events += [
        event("tests.superseded", 1, task="1.1", tests=["tests.test_a::test_one"], criteria=[], reason="stale"),
        event(
            "tests.superseded",
            2,
            task="1.1",
            tests=["tests.test_b::test_one"],
            criteria=[],
            reason="named_by_task",
            source="base:0123456789",
        ),
    ]
    repo.write({"tests/test_a.py": CHANGED, "tests/test_b.py": CHANGED})
    out = check_tests(repo.context(base, repo.commit("both", task="1.1", tdd="red")))
    assert out.findings == []
    assert "superseded by a changed criterion, not deleted: tests/test_a.py::test_one" in out.note
    assert "tests.test_b::test_one (named by the task text, base:0123456789)" in out.note


def test_a_named_test_of_another_language_excuses_no_python_test_of_the_same_name(tmp_path, git_environ):
    repo, base = new_repo(tmp_path, git_environ, {"tests/test_a.py": PLAIN})
    repo.events.append(
        event(
            "tests.superseded",
            1,
            task="1.1",
            tests=["src/api/codes.test.ts::test_one"],
            criteria=[],
            reason="named_by_task",
            source="plan:p1@abc",
            language="typescript",
        )
    )
    repo.write({"tests/test_a.py": CHANGED})
    [finding] = check_tests(repo.context(base, repo.commit("rewrite", task="1.1", tdd="red"))).findings
    assert "tests/test_a.py::test_one" in finding.detail
