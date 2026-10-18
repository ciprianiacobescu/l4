"""detect-test-tamper 3.1 and 3.2 (L4-VER-030, L4-VER-031, L4-VER-032): step 1 compares pre-existing tests per test on
the AST. Ports the verifier-8 reproduction (a masked delete) and adds the weakened-test cases."""

from l4.verifier.integrity import check_tests

from ._integrity_helpers import UNIT, event, new_repo, task

PRICING = (
    "from pytdd import total\n\n\ndef test_total_adds_prices():\n    assert total([1.25, 2.5]) == 3.75\n\n\n"
    "def test_total_of_nothing_is_zero():\n    assert total([]) == 0\n"
)
WEAK = PRICING.replace("assert total([1.25, 2.5]) == 3.75", "assert total([1.25, 2.5]) is not None")
CART = "def test_empty():\n    assert compute([]) == 0\n\n\ndef test_other():\n    assert 1\n"
ORDERS = "def test_x():\n    assert 1\n"
CART_NO_EMPTY = "def test_other():\n    assert 1\n"


def titles(out):
    return [f.title for f in out.findings]


def test_a_harness_commit_that_weakens_a_pre_existing_test_is_a_blocker(tmp_path, git_environ):  # SCN-VER-100
    repo, base = new_repo(tmp_path, git_environ, {"tests/test_pricing.py": PRICING})
    repo.write({"tests/test_pricing.py": WEAK})
    out = check_tests(repo.context(base, repo.commit("red", task="1.1", tdd="red")))
    [finding] = out.findings
    assert finding.title == "a pre-existing test was changed"
    assert (
        "tests/test_pricing.py::test_total_adds_prices (its body, decorators or parametrisation changed)"
        in finding.detail
    )


def test_a_rebinding_a_changed_helper_and_an_unparsable_file_are_changes(tmp_path, git_environ):  # SCN-VER-102
    helper = "def _check(v):\n    assert v == 3\n\n\ndef test_h():\n    _check(3)\n"
    files = {"tests/test_a.py": PRICING, "tests/test_b.py": helper, "tests/test_c.py": ORDERS}
    repo, base = new_repo(tmp_path, git_environ, files)
    repo.write(
        {
            "tests/test_a.py": PRICING + "\n\ndef test_total_adds_prices():\n    pass\n",
            "tests/test_b.py": helper.replace("assert v == 3", "return"),
            "tests/test_c.py": "def test_x(:\n",
        }
    )
    [finding] = check_tests(repo.context(base, repo.commit("red", task="1.1", tdd="red"))).findings
    assert finding.title == "a pre-existing test was changed"
    for expected in (
        "tests/test_a.py::test_total_adds_prices (its name is bound again at line",
        "tests/test_b.py::test_h (what it uses in this file changed: _check)",
        "tests/test_c.py::test_x (the file does not parse)",
    ):
        assert expected in finding.detail


def masked(tmp_path, git_environ, *, human, same_name):
    repo, base = new_repo(tmp_path, git_environ, {"tests/test_cart.py": CART, "tests/test_orders.py": ORDERS})
    other = "\n\ndef test_empty():\n    assert True\n" if same_name else "\n\ndef test_y():\n    assert True\n"
    repo.write({"tests/test_cart.py": CART_NO_EMPTY, "tests/test_orders.py": ORDERS + other})
    head = repo.commit_as_human("a person's change") if human else repo.commit("work")
    return check_tests(repo.context(base, head)), head


def test_a_deleted_test_masked_by_a_same_named_test_elsewhere_is_still_deleted(tmp_path, git_environ):  # SCN-VER-103
    out, _ = masked(tmp_path, git_environ, human=False, same_name=True)
    [finding] = out.findings
    assert finding.title == "a pre-existing test was deleted" and "tests/test_cart.py::test_empty" in finding.detail


def test_the_control_without_the_same_name_is_the_blocker_too(tmp_path, git_environ):  # SCN-VER-103
    out, _ = masked(tmp_path, git_environ, human=False, same_name=False)
    assert titles(out) == ["a pre-existing test was deleted"]


def test_a_persons_masked_deletion_is_listed_not_blocked(tmp_path, git_environ):  # SCN-VER-104
    out, head = masked(tmp_path, git_environ, human=True, same_name=True)
    assert out.findings == []
    assert out.human_tests == [f"tests/test_cart.py::test_empty deleted by {head[:10]}"]


def test_a_persons_unmasked_deletion_is_listed_too(tmp_path, git_environ):  # SCN-VER-104 control
    out, head = masked(tmp_path, git_environ, human=True, same_name=False)
    assert out.findings == [] and out.human_tests == [f"tests/test_cart.py::test_empty deleted by {head[:10]}"]


def test_a_test_moved_unchanged_to_another_changed_file_is_not_deleted(tmp_path, git_environ):  # SCN-VER-105
    one = "def test_one():\n    assert 1\n"
    repo, base = new_repo(tmp_path, git_environ, {"tests/test_a.py": one + "\n\ndef test_keep():\n    assert 1\n"})
    repo.write({"tests/test_a.py": "def test_keep():\n    assert 1\n", "tests/test_b.py": one})
    moved_head = repo.commit("move", task="1.1", tdd="red")
    assert check_tests(repo.context(base, moved_head)).findings == []
    repo.delete("tests/test_b.py")
    findings = check_tests(repo.context(base, repo.commit("drop", task="1.1", tdd="red"))).findings
    [finding] = [f for f in findings if f.title == "a pre-existing test was deleted"]
    assert "tests/test_a.py::test_one" in finding.detail


def test_a_persons_change_is_listed_and_a_harness_change_on_top_blocks(tmp_path, git_environ):  # SCN-VER-106
    repo, base = new_repo(tmp_path, git_environ, {"tests/test_pricing.py": PRICING})
    repo.write({"tests/test_pricing.py": WEAK})
    first = repo.commit_as_human("a person weakens it")
    out = check_tests(repo.context(base, first))
    assert out.findings == []
    assert out.human_tests == [f"tests/test_pricing.py::test_total_adds_prices changed by {first[:10]}"]
    repo.write({"tests/test_pricing.py": WEAK.replace("is not None", "is not False")})
    assert titles(check_tests(repo.context(base, repo.commit("again", task="1.1", tdd="green")))) == [
        "a pre-existing test was changed"
    ]


def test_superseded_test_infra_and_unfrozen_changes_are_allowed_and_listed(tmp_path, git_environ):  # SCN-VER-107
    files = {f"tests/test_{n}.py": f"def test_{n}():\n    assert 1\n" for n in "abc"}
    repo, base = new_repo(tmp_path, git_environ, files)
    repo.events += [
        event("tests.superseded", 1, task="1.1", tests=["tests.test_a::test_a"], criteria=[]),
        event("task.unfrozen", 2, task="1.1", paths=["tests/test_c.py"], reason="human_answer", question="Q-1"),
    ]
    repo.write({"tests/test_a.py": "def test_a():\n    assert 2\n"})
    repo.commit("stale", task="1.1", tdd="red")
    repo.write({"tests/test_b.py": "def test_b():\n    assert 2\n"})
    repo.commit("infra", task="2.1", tdd="red")
    repo.write({"tests/test_c.py": "def test_c():\n    assert 2\n"})
    head = repo.commit("green", task="1.1", tdd="green")
    tasks = [(UNIT, task("1.1")), (UNIT, task("2.1", "2.1 [test-infra] Share the fixture"))]
    out = check_tests(repo.context(base, head, tasks=tasks))
    assert out.findings == []
    assert sorted(out.allowed_tests) == [
        "tests/test_b.py::test_b changed (task 2.1: [test-infra])",
        "tests/test_c.py::test_c changed (task 1.1: unfrozen by Q-1)",
    ]
    assert "(+2 allowed, listed)" in out.note and "superseded by a changed criterion" in out.note


def test_a_task_unfrozen_of_another_task_allows_nothing(tmp_path, git_environ):  # SCN-VER-108
    repo, base = new_repo(tmp_path, git_environ, {"tests/test_c.py": "def test_c():\n    assert 1\n"})
    repo.events.append(event("task.unfrozen", 1, task="1.1", paths=["tests/test_c.py"], reason="human_answer"))
    repo.write({"tests/test_c.py": "def test_c():\n    assert 2\n"})
    head = repo.commit("green", task="1.2", tdd="green")
    out = check_tests(repo.context(base, head, tasks=[(UNIT, task("1.1")), (UNIT, task("1.2"))]))
    assert titles(out) == ["a pre-existing test was changed"]


def test_an_added_skip_marker_is_reported_once(tmp_path, git_environ):  # SCN-VER-109
    repo, base = new_repo(tmp_path, git_environ, {"tests/test_a.py": "def test_a():\n    assert 1\n"})
    repo.write(
        {
            "tests/test_a.py": (
                "import pytest\n\npytestmark = pytest.mark.skip\n\n\ndef test_a():\n    pytest.skip('no')\n"
            )
        }
    )
    out = check_tests(repo.context(base, repo.commit("skip", task="1.1", tdd="red")))
    assert titles(out) == ["a skip or xfail marker was added"]


DISCOUNT = "def test_known_code():\n    assert 1 == 1\n"


def test_a_later_red_that_weakens_an_earlier_reds_test_is_a_blocker(tmp_path, git_environ):  # SCN-VER-110
    repo, base = new_repo(tmp_path, git_environ)
    repo.write({"tests/test_discount.py": DISCOUNT})
    repo.commit("red 1.1", task="1.1", tdd="red")
    repo.write({"tests/test_discount.py": "def test_known_code():\n    assert True\n"})
    head = repo.commit("red 1.2", task="1.2", tdd="red")
    tasks = [(UNIT, task("1.1")), (UNIT, task("1.2"))]
    [finding] = check_tests(repo.context(base, head, tasks=tasks)).findings
    assert finding.title == "a red step changed a test that an earlier step wrote"
    assert f"tests/test_discount.py::test_known_code (task 1.2, red commit {head[:10]}:" in finding.detail


def test_appending_to_an_earlier_reds_file_is_no_change(tmp_path, git_environ):  # SCN-VER-111
    repo, base = new_repo(tmp_path, git_environ)
    repo.write({"tests/test_discount.py": DISCOUNT})
    repo.commit("red 1.1", task="1.1", tdd="red")
    repo.write({"tests/test_discount.py": DISCOUNT + "\n\ndef test_more():\n    assert 2\n"})
    head = repo.commit("red 1.2", task="1.2", tdd="red")
    assert check_tests(repo.context(base, head, tasks=[(UNIT, task("1.1")), (UNIT, task("1.2"))])).findings == []


GO = (
    'package cart\n\nimport "testing"\n\nfunc TestTotal(t *testing.T) {\n'
    '\tif Total([]float64{1.25, 2.5}) != 3.75 {\n\t\tt.Fatal("total")\n\t}\n}\n'
)
GO_WEAK = 'package cart\n\nimport "testing"\n\nfunc TestTotal(t *testing.T) {\n\t_ = Total([]float64{1.25, 2.5})\n}\n'
TS = (
    "import { total } from '../src/cart';\n\n"
    "test('adds prices', () => {\n  expect(total([1.25, 2.5])).toBe(3.75);\n});\n"
)
TS_WEAK = "import { total } from '../src/cart';\n\ntest('adds prices', () => {\n  expect(true).toBe(true);\n});\n"
PY = "def test_other():\n    assert 1 + 1 == 2\n"


def test_weakened_go_and_typescript_tests_are_named_as_checked_by_the_run(tmp_path, git_environ):  # SCN-VER-137
    base_files = {"cart/cart_test.go": GO, "web/cart.test.ts": TS, "tests/test_other.py": PY}
    repo, base = new_repo(tmp_path, git_environ, base_files)
    repo.write({"cart/cart_test.go": GO_WEAK, "web/cart.test.ts": TS_WEAK})
    out = check_tests(repo.context(base, repo.commit("red", task="1.1", tdd="red")))
    assert not out.findings
    assert out.note == "no Python test file changed; 2 other test file(s) are checked by the run of pre-existing tests"
    repo.write({"tests/test_other.py": PY + "\n\ndef test_new():\n    assert True\n"})
    out = check_tests(repo.context(base, repo.commit("red 2", task="1.2", tdd="red")))
    assert not out.findings and "2 other test file(s) are checked by the run of pre-existing tests" in out.note


def test_a_human_tag_in_a_fix_units_task_exempts_nothing(tmp_path, git_environ):  # SCN-VER-107 (third review, M3)
    from l4.verifier.integrity import check_tests

    def edited(root, unit):
        (root).mkdir()
        repo, base = new_repo(root, git_environ, {"tests/test_c.py": "def test_c():\n    assert 1\n"})
        repo.write({"tests/test_c.py": "def test_c():\n    assert 2\n"})
        return repo, base, repo.commit("fix", task="1.1", tdd="green", unit=unit)

    tagged = task("1.1", "1.1 Fix the check [test-infra]")
    repo, base, sha = edited(tmp_path / "fix", f"{UNIT}:fix-1")
    out = check_tests(repo.context(base, sha, tasks=[(f"{UNIT}:fix-1", tagged)]))
    assert [f.title for f in out.findings] == ["a pre-existing test was changed"]
    repo, base, sha = edited(tmp_path / "own", UNIT)
    own = check_tests(repo.context(base, sha, tasks=[(UNIT, tagged)]))
    assert own.findings == [] and own.allowed_tests  # the unit's own task: a person wrote the tag
