"""detect-test-tamper 3.4 (L4-VER-037, owner decision 1): step 1's rule against support files that patch the unit's code
covers every changed test-support file. An autouse fixture or module-level code that patches a symbol of a production
module the unit changed is a blocker; a fixture a test requests by name (an ordinary mock) is listed."""

from l4.verifier.integrity import check_scan, run_integrity

from ._integrity_helpers import new_repo

PRICING = "def apply_discount(amount, code):\n    return amount\n"
PRICING_NEW = "def apply_discount(amount, code):\n    return amount * 0.9\n"
AUTOUSE = (
    "import pytest\n\nimport pytdd.pricing as p\n\n\n@pytest.fixture(autouse=True)\ndef _swap(monkeypatch):\n"
    "    monkeypatch.setattr(p, 'apply_discount', lambda a, c: a * 0.9)\n"
)
MODULE_LEVEL = "import pytdd.pricing as p\n\np.apply_discount = lambda a, c: a * 0.9\n"
EXPLICIT = (
    "import pytest\n\nimport pytdd.pricing as p\n\n\n@pytest.fixture\ndef cheap(monkeypatch):\n"
    "    monkeypatch.setattr(p, 'apply_discount', lambda a, c: 1.0)\n"
)
CHAINED = (
    "import pytest\n\nimport pytdd.pricing as p\n\n\n@pytest.fixture\ndef cheap(monkeypatch):\n"
    "    monkeypatch.setattr(p, 'apply_discount', lambda a, c: 1.0)\n\n\n"
    "@pytest.fixture(autouse=True)\ndef _always(cheap):\n    yield\n"
)
HELPER = "import pytdd.pricing as p\n\n\ndef install(monkeypatch):\n    monkeypatch.setattr(p, 'apply_discount', len)\n"
BASE = {
    "src/pytdd/pricing.py": PRICING,
    "src/pytdd/__init__.py": "",
    "tests/test_a.py": "def test_a():\n    assert 1\n",
}


def run(tmp_path, git_environ, conftest, *, human=False):
    repo, base = new_repo(tmp_path, git_environ, BASE)
    repo.write({"src/pytdd/pricing.py": PRICING_NEW, "tests/conftest.py": conftest})
    head = repo.commit_as_human("a person's change") if human else repo.commit("work", task="1.1", tdd="green")
    return check_scan(repo.context(base, head))


def blocked(out):
    [finding] = out.findings
    assert finding.title == "a construct that can change what the tests report"
    assert "tests/conftest.py: patches pytdd.pricing.apply_discount, which the unit changed, for every test" in (
        finding.detail
    )


def test_an_autouse_fixture_that_patches_the_units_code_is_a_blocker(tmp_path, git_environ):  # SCN-VER-124
    blocked(run(tmp_path, git_environ, AUTOUSE))


def test_module_level_code_that_assigns_the_units_code_is_a_blocker(tmp_path, git_environ):  # SCN-VER-124
    blocked(run(tmp_path, git_environ, MODULE_LEVEL))


def test_a_fixture_an_autouse_fixture_requests_is_a_blocker_too(tmp_path, git_environ):  # SCN-VER-124
    blocked(run(tmp_path, git_environ, CHAINED))


def test_a_plain_helper_that_patches_is_a_blocker_because_its_use_is_unknown(tmp_path, git_environ):  # SCN-VER-124
    blocked(run(tmp_path, git_environ, HELPER))


def test_a_fixture_a_test_requests_by_name_is_listed_not_blocked(tmp_path, git_environ):  # SCN-VER-125
    out = run(tmp_path, git_environ, EXPLICIT)
    assert out.findings == []
    assert out.mocked == ["tests/conftest.py: patches pytdd.pricing.apply_discount in a fixture a test requests"]
    assert "fixture patch(es) of the unit's code, listed" in out.note


def test_a_persons_commit_is_listed_not_blocked(tmp_path, git_environ):  # SCN-VER-124 (L4-SEC-004)
    out = run(tmp_path, git_environ, AUTOUSE, human=True)
    assert (
        out.findings == [] and len(out.human_scan) == 1 and "patches pytdd.pricing.apply_discount" in out.human_scan[0]
    )


def test_a_patch_of_something_the_unit_did_not_change_is_not_flagged(tmp_path, git_environ):  # SCN-VER-125
    other = AUTOUSE.replace("pytdd.pricing", "pytdd.clock")
    repo, base = new_repo(tmp_path, git_environ, {**BASE, "src/pytdd/clock.py": "def now():\n    return 1\n"})
    repo.write({"src/pytdd/pricing.py": PRICING_NEW, "tests/conftest.py": other.replace("apply_discount", "now")})
    out = check_scan(repo.context(base, repo.commit("work", task="1.1", tdd="green")))
    assert out.findings == [] and out.mocked == []


def test_the_report_carries_the_listed_patches(tmp_path, git_environ):  # SCN-VER-125
    repo, base = new_repo(tmp_path, git_environ, BASE)
    repo.write({"src/pytdd/pricing.py": PRICING_NEW, "tests/conftest.py": EXPLICIT})
    report = run_integrity(repo.context(base, repo.commit("work", task="1.1", tdd="green")))
    assert report.mocked_support == [
        "tests/conftest.py: patches pytdd.pricing.apply_discount in a fixture a test requests"
    ]


HELPER_HOOK = "def pytest_runtest_setup(item):\n    pass\n"


def test_a_helper_module_under_tests_with_no_test_is_read_as_support(tmp_path, git_environ):  # SCN-VER-129, SCN-VER-124
    repo, base = new_repo(tmp_path, git_environ, BASE)
    repo.write({"src/pytdd/pricing.py": PRICING_NEW, "tests/checks.py": HELPER_HOOK})
    out = check_scan(repo.context(base, repo.commit("work", task="1.1", tdd="green")))
    [finding] = out.findings
    assert "tests/checks.py: pytest_runtest_setup: code around every test call" in finding.detail


def test_the_patch_rule_runs_on_a_helper_module_too(tmp_path, git_environ):  # SCN-VER-124
    helper = "import pytdd.pricing as p\n\np.apply_discount = lambda a, c: a\n"
    repo, base = new_repo(tmp_path, git_environ, BASE)
    repo.write({"src/pytdd/pricing.py": PRICING_NEW, "tests/checks.py": helper})
    [finding] = check_scan(repo.context(base, repo.commit("work", task="1.1", tdd="green"))).findings
    assert "tests/checks.py: patches pytdd.pricing.apply_discount, which the unit changed, for every test" in (
        finding.detail
    )


def test_a_file_with_a_test_is_not_read_as_support(tmp_path, git_environ):  # SCN-VER-129 control
    repo, base = new_repo(tmp_path, git_environ, BASE)
    repo.write(
        {"src/pytdd/pricing.py": PRICING_NEW, "tests/test_hooks.py": HELPER_HOOK + "\n\ndef test_x():\n    pass\n"}
    )
    assert check_scan(repo.context(base, repo.commit("work", task="1.1", tdd="green"))).findings == []


def test_a_conftest_that_registers_an_exit_hook_or_names_the_report_path_is_a_hit(tmp_path, git_environ):  # SCN-VER-129
    forger = "import atexit\n\n\ndef _f():\n    open('.l4-out/junit.xml', 'w').write('')\n\n\natexit.register(_f)\n"
    repo, base = new_repo(tmp_path, git_environ, BASE)
    repo.write({"tests/conftest.py": forger})
    [finding] = check_scan(repo.context(base, repo.commit("work", task="1.1", tdd="green"))).findings
    assert "atexit.register" in finding.detail and "names the test output" in finding.detail
