"""A task's own reviewed text opens the support files it names (L4-IMP-014, L4-IMP-016; uf 2.1 to 2.3)."""

import json

import pytest

from l4.agents.fake import Step
from l4.implementer.tdd import run_green, run_red, task_source
from l4.yolo.digest import unit_digest

from .conftest import IMPL, KNOWN, STUB, TESTS, UNKNOWN, result

ENV_TEST = (
    "import os\n\nimport pytest\n\n\n"
    f'@pytest.mark.l4("{KNOWN}")\ndef test_otel_default():\n    assert os.environ.get("APP_OTEL_ENABLED") == "false"\n'
)
OLD_CONFTEST = (
    "import os\n\nimport pytest\n\nos.environ.setdefault('APP_NAME', 'demo')\n\n\n"
    "@pytest.fixture\ndef client():\n    return object()\n"
)
NEW_CONFTEST = OLD_CONFTEST.replace(
    "\n\n@pytest.fixture", "os.environ.setdefault('APP_OTEL_ENABLED', 'false')\n\n\n@pytest.fixture"
)
NAMING = "- [ ] 1.1 Add `apply_discount` and set the default in `conftest.py`\n"
PLAIN = (
    '- [ ] 1.1 Add `apply_discount(amount, code)` to `src/pytdd/pricing.py` implementing requirement "Discount codes"\n'
)
CONFTEST = "conftest.py"


def commit(bench, message: str) -> None:
    bench.wb.git.run("add", "-A")
    bench.wb.git.run("-c", "user.name=t", "-c", "user.email=t@x.invalid", "commit", "-q", "-m", message)


def tasks_path(bench):
    return bench.wb.ref.path / "tasks.md"


def prepare(
    bench,
    *,
    text: str = NAMING,
    conftest: str = OLD_CONFTEST,
    base: bool = False,
    plan: bool = False,
    head: str | None = None,
):
    """A root support file and a task text, committed before red. `base`: origin/main has the same text.
    `plan`: the unit folder's digest was frozen at activation."""
    heading = head if head is not None else tasks_path(bench).read_text().split("- [ ]")[0]
    tasks_path(bench).write_text(heading + text)
    (bench.wb.worktree / CONFTEST).write_text(conftest)
    commit(bench, "support file and task text")
    if base:
        bench.wb.git.run("update-ref", "refs/remotes/origin/main", "HEAD")
    if plan:
        bench.wb.activated_plan = "p1"
        bench.wb.activated_digest = unit_digest(bench.wb.git, "HEAD", bench.wb.unit_rel)
    return bench.wb.provider.tasks(bench.wb.ref)[0]


def red_env() -> Step:
    return Step(
        writes={"tests/test_discount.py": TESTS, "tests/test_otel.py": ENV_TEST, "src/pytdd/pricing.py": STUB},
        structured=result(
            "red",
            tests_added=["tests/test_discount.py::test_known_code", "tests/test_otel.py::test_otel_default"],
            criteria_ids=[KNOWN, UNKNOWN],
        ),
    )


def green_writing(conftest: str, **more: str) -> Step:
    return Step(writes={"src/pytdd/pricing.py": IMPL, CONFTEST: conftest, **more}, structured=result("green"))


def run_both(make_bench, green: Step, **kw):
    bench = make_bench([red_env(), green])
    task = prepare(bench, **kw)
    red = run_red(bench.wb, task, attempt=1)
    assert red.status == "ok", red.reason
    return bench, task, red, run_green(bench.wb, task, red, attempt=1)


def violations(bench, rule: str | None = None) -> list[dict]:
    found = bench.events("guard.violation")
    return [e for e in found if rule is None or e.get("rule") == rule]


# --- 2.1 task_source ---


def test_source_of_an_activated_plan(make_bench):
    bench = make_bench([])
    task = prepare(bench, plan=True)
    digest = bench.wb.activated_digest
    assert task_source(bench.wb, task) == f"plan:p1@{digest}"


def test_source_of_the_base_branch(make_bench):
    bench = make_bench([])
    task = prepare(bench, base=True)
    sha = bench.wb.git.rev_parse("refs/remotes/origin/main")
    assert task_source(bench.wb, task) == f"base:{sha[:10]}"


def test_a_text_only_the_unit_branch_has_gives_none(make_bench):
    """SCN-IMP-161 (function level)"""
    bench = make_bench([])
    task = prepare(bench)
    assert task_source(bench.wb, task) is None


def test_a_text_that_differs_from_the_base_gives_none(make_bench):
    bench = make_bench([])
    task = prepare(bench, text=PLAIN, base=True)
    tasks_path(bench).write_text(tasks_path(bench).read_text().replace(PLAIN, NAMING))
    commit(bench, "a person edits the task")
    assert task_source(bench.wb, task) is None


def test_a_missing_base_ref_gives_none(make_bench):
    bench = make_bench([])
    task = prepare(bench)
    bench.wb.git.run("update-ref", "-d", "refs/remotes/origin/main")
    assert task_source(bench.wb, task) is None


def test_a_changed_folder_digest_gives_none(make_bench):
    bench = make_bench([])
    task = prepare(bench, plan=True)
    (bench.wb.ref.path / "proposal.md").write_text("changed after activation\n")
    commit(bench, "edit")
    assert task_source(bench.wb, task) is None


@pytest.mark.parametrize(
    "marker, body",
    [
        (("fix.json"), {"schema": "l4/fix-unit@1", "parent": "openspec:add-discount-codes", "round": 1}),
        (("followup.json"), {"schema": "l4/followup@1", "parent": "openspec:add-discount-codes"}),
    ],
)
def test_a_fix_or_follow_up_unit_gives_none(make_bench, marker, body):
    """SCN-IMP-166 (function level)"""
    bench = make_bench([])
    task = prepare(bench, base=True, plan=True)
    assert task_source(bench.wb, task) is not None
    (bench.wb.ref.path / ".l4").mkdir(exist_ok=True)
    (bench.wb.ref.path / ".l4" / marker).write_text(json.dumps(body))
    assert task_source(bench.wb, task) is None


# --- 2.2 the grant ---


def test_the_live_case_under_a_plan_source(make_bench):
    """SCN-IMP-159"""
    bench, task, red, green = run_both(make_bench, green_writing(NEW_CONFTEST), plan=True)
    assert green.status == "ok", green.reason
    assert (bench.wb.worktree / CONFTEST).read_text() == NEW_CONFTEST
    assert violations(bench) == [] and bench.events("guard.test_tamper") == []
    [event] = bench.events("task.unfrozen")
    assert event["task"] == "1.1" and event["paths"] == [CONFTEST] and event["reason"] == "named_by_task"
    assert event["source"] == f"plan:p1@{bench.wb.activated_digest}" and event["red_sha"] == red.sha
    assert "question" not in event and "answer_sha256" not in event
    assert "# Files this task names" in bench.adapter.requests[-1].prompt
    assert bench.wb.git.run("show", f"{green.sha}:{CONFTEST}").stdout == NEW_CONFTEST


def test_the_live_case_under_a_base_source(make_bench):
    """SCN-IMP-159, SCN-IMP-160"""
    bench, task, red, green = run_both(make_bench, green_writing(NEW_CONFTEST), base=True)
    assert green.status == "ok", green.reason
    assert violations(bench) == []
    [event] = bench.events("task.unfrozen")
    assert event["paths"] == [CONFTEST] and event["source"].startswith("base:") and len(event["source"]) == 15


def test_text_pushed_only_to_the_unit_branch_opens_nothing(make_bench):
    """SCN-IMP-161"""
    bench, task, red, green = run_both(make_bench, green_writing(NEW_CONFTEST))
    assert bench.events("task.unfrozen") == []
    assert [e["path"] for e in violations(bench)] == [CONFTEST]
    assert "# Files this task names" not in bench.adapter.requests[-1].prompt


def test_a_red_test_the_task_names_stays_frozen(make_bench):
    """SCN-IMP-162"""
    text = "- [ ] 1.1 Add `apply_discount`, set the default in `conftest.py`, see `tests/test_otel.py`\n"
    weak = ENV_TEST.replace('== "false"', "!= None")
    bench, task, red, green = run_both(
        make_bench, green_writing(NEW_CONFTEST, **{"tests/test_otel.py": weak}), text=text, plan=True
    )
    assert green.status == "ok", green.reason
    assert (bench.wb.worktree / "tests/test_otel.py").read_text() == ENV_TEST
    assert [e["path"] for e in bench.events("guard.test_tamper")] == ["tests/test_otel.py"]
    [event] = bench.events("task.unfrozen")
    assert event["paths"] == [CONFTEST]
    assert {"path": "tests/test_otel.py", "why": "a red test of this task"} in event["kept"]


def test_a_support_file_red_changed_stays_frozen_though_the_task_names_it(make_bench):
    """SCN-IMP-163"""
    red_conftest = OLD_CONFTEST + "\n\n@pytest.fixture\ndef red_fixture():\n    return 1\n"
    red = red_env()
    red.writes[CONFTEST] = red_conftest
    bench = make_bench([red, green_writing(NEW_CONFTEST)])
    task = prepare(bench, plan=True)
    red_result = run_red(bench.wb, task, attempt=1)
    assert red_result.status == "ok", red_result.reason
    run_green(bench.wb, task, red_result, attempt=1)
    assert (bench.wb.worktree / CONFTEST).read_text() == red_conftest
    assert bench.events("task.unfrozen") == [] or all(CONFTEST not in e["paths"] for e in bench.events("task.unfrozen"))
    kept = [k for e in bench.events("task.unfrozen") for k in e["kept"]]
    assert {"path": CONFTEST, "why": "the red step of this task changed it"} in kept


def test_a_symlink_an_ignore_file_and_a_data_file_stay_frozen(make_bench):
    """SCN-IMP-165"""
    text = "- [ ] 1.1 Add `apply_discount`; touch `conftest.py`, `.gitignore` and `tests/fixtures/expected.json`\n"
    bench = make_bench(
        [red_env(), green_writing(NEW_CONFTEST, **{".gitignore": "x\n", "tests/fixtures/expected.json": "{}\n"})]
    )
    (bench.wb.worktree / "tests" / "fixtures").mkdir(parents=True)
    (bench.wb.worktree / "tests/fixtures/expected.json").write_text("[]\n")
    (bench.wb.worktree / "real_conftest.py").write_text(OLD_CONFTEST)
    task = prepare(bench, text=text, plan=True)
    (bench.wb.worktree / CONFTEST).unlink()
    (bench.wb.worktree / CONFTEST).symlink_to("real_conftest.py")
    commit(bench, "a symlinked conftest and a data file")
    bench.wb.activated_digest = unit_digest(bench.wb.git, "HEAD", bench.wb.unit_rel)
    bench.wb.cfg.tdd.test_support_globs = [*bench.wb.cfg.tdd.test_support_globs, "tests/fixtures/**"]
    red = run_red(bench.wb, task, attempt=1)
    assert red.status == "ok", red.reason
    run_green(bench.wb, task, red, attempt=1)
    [event] = bench.events("task.unfrozen")
    assert event["reason"] == "named_by_task" and event["paths"] == []
    why = {k["path"]: k["why"] for k in event["kept"]}
    assert why[CONFTEST] == "a symlink at the red commit"
    assert why[".gitignore"] == "an ignore file"
    assert why["tests/fixtures/expected.json"] == "not a Python file: a person decides"


def test_a_fix_units_task_opens_nothing(make_bench):
    """SCN-IMP-166"""
    bench = make_bench([red_env(), green_writing(NEW_CONFTEST)])
    task = prepare(bench, base=True, plan=True)
    (bench.wb.ref.path / ".l4").mkdir(exist_ok=True)
    marker = {
        "schema": "l4/fix-unit@1",
        "parent": "openspec:add-discount-codes",
        "round": 1,
        "findings": [],
        "chores": [],
    }
    (bench.wb.ref.path / ".l4" / "fix.json").write_text(json.dumps(marker))
    commit(bench, "fix marker")
    red = run_red(bench.wb, task, attempt=1)
    assert red.status == "ok", red.reason
    run_green(bench.wb, task, red, attempt=1)
    assert [e for e in bench.events("task.unfrozen") if e.get("reason") == "named_by_task"] == []
    assert [e["path"] for e in violations(bench)] == [CONFTEST]


# --- 2.3 what an opened file may become ---


def test_green_that_rewrites_a_fixture_of_the_opened_file_is_put_back(make_bench):
    """SCN-IMP-171"""
    changed = NEW_CONFTEST.replace("return object()", "return None")
    bench, _, red, green = run_both(make_bench, green_writing(changed), plan=True)
    [event] = violations(bench, "opened file")
    assert event["path"] == CONFTEST and event["phase"] == "green" and event["why"] == "changes an existing statement"
    assert green.status == "failed"  # the red version has no default, so the red test still fails
    assert (bench.wb.worktree / CONFTEST).read_text() == OLD_CONFTEST


def test_green_that_adds_a_second_client_is_put_back(make_bench):
    """SCN-IMP-171"""
    second = NEW_CONFTEST + "\n\n@pytest.fixture\ndef client():\n    return 1\n"
    bench, _, _, _ = run_both(make_bench, green_writing(second), plan=True)
    [event] = violations(bench, "opened file")
    assert event["why"] == "rebinds client"


UNIT_CODE = "src/pytdd/pricing.py"


def test_green_that_patches_the_units_code_from_the_opened_file_is_put_back(make_bench):
    """SCN-IMP-172"""
    patching = NEW_CONFTEST + (
        "\n\n@pytest.fixture(autouse=True)\ndef _quiet(monkeypatch):\n"
        '    monkeypatch.setattr("pytdd.pricing.apply_discount", lambda a, c: a)\n'
    )
    bench, _, _, green = run_both(make_bench, green_writing(patching), plan=True)
    [event] = violations(bench, "opened file")
    assert event["why"] == "patches pytdd.pricing.apply_discount, which the unit changed"
    assert green.status == "failed"


def test_green_that_sets_the_environment_from_an_autouse_fixture_is_kept(make_bench):
    """SCN-IMP-172 (the allowed twin)"""
    env = OLD_CONFTEST + (
        "\n\n@pytest.fixture(autouse=True)\ndef _no_otel(monkeypatch):\n"
        '    monkeypatch.setenv("APP_OTEL_ENABLED", "false")\n'
    )
    bench, _, _, green = run_both(make_bench, green_writing(env), plan=True)
    assert green.status == "ok", green.reason
    assert violations(bench) == []


def test_green_that_replaces_the_opened_file_with_a_symlink_is_put_back(make_bench):
    """SCN-IMP-173"""
    bench = make_bench([red_env(), green_writing(NEW_CONFTEST)])
    task = prepare(bench, plan=True)
    red = run_red(bench.wb, task, attempt=1)
    assert red.status == "ok", red.reason
    target = bench.wb.worktree.parent / "elsewhere.py"
    target.write_text(NEW_CONFTEST)

    def link(request):  # runs the adapter's own step, then swaps the file for a link
        out = original(request)
        (bench.wb.worktree / CONFTEST).unlink()
        (bench.wb.worktree / CONFTEST).symlink_to(target)
        return out

    original = bench.adapter.run
    bench.adapter.run = link  # type: ignore[method-assign]
    run_green(bench.wb, task, red, attempt=1)
    [event] = violations(bench, "opened file")
    assert event["why"] == "a symlink"
    assert not (bench.wb.worktree / CONFTEST).is_symlink()
    assert (bench.wb.worktree / CONFTEST).read_text() == OLD_CONFTEST


# --- the section heading is part of the reviewed text ---

SECTION_ONLY = "- [ ] 1.1 Add `apply_discount` and the fixtures of the spec\n"


def test_a_heading_that_names_the_file_opens_it_under_a_plan_source(make_bench):
    """SCN-IMP-174"""
    bench, task, red, green = run_both(
        make_bench, green_writing(NEW_CONFTEST), text=SECTION_ONLY, head="## 1. Root conftest.py\n\n", plan=True
    )
    assert green.status == "ok", green.reason
    assert violations(bench) == []
    [event] = bench.events("task.unfrozen")
    assert event["paths"] == [CONFTEST] and event["source"].startswith("plan:p1@")


def test_a_heading_that_names_the_file_opens_it_under_a_base_source(make_bench):
    """SCN-IMP-174"""
    bench, task, red, green = run_both(
        make_bench, green_writing(NEW_CONFTEST), text=SECTION_ONLY, head="## 1. Root conftest.py\n\n", base=True
    )
    assert green.status == "ok", green.reason
    [event] = bench.events("task.unfrozen")
    assert event["paths"] == [CONFTEST] and event["source"].startswith("base:")


def test_a_heading_edited_after_the_base_branch_gives_no_source(make_bench):
    bench = make_bench([])
    task = prepare(bench, text=SECTION_ONLY, head="## 1. Group\n\n", base=True)
    tasks_path(bench).write_text(tasks_path(bench).read_text().replace("## 1. Group", "## 1. Root conftest.py"))
    commit(bench, "a person edits the heading")
    assert task_source(bench.wb, task) is None


def test_a_heading_of_another_section_does_not_count(make_bench):
    """SCN-IMP-175"""
    head = "## 1. Root conftest.py\n\n- [ ] 0.1 Other\n\n## 2. Pricing\n\n"
    bench = make_bench([red_env(), green_writing(NEW_CONFTEST)])
    task = prepare(bench, text=SECTION_ONLY, head=head, plan=True)
    task = next(t for t in bench.wb.provider.tasks(bench.wb.ref) if t.key == "1.1")
    red = run_red(bench.wb, task, attempt=1)
    assert red.status == "ok", red.reason
    run_green(bench.wb, task, red, attempt=1)
    assert bench.events("task.unfrozen") == []
    assert [e["path"] for e in violations(bench)] == [CONFTEST]


@pytest.mark.parametrize("heading", ["## 1. Fixtures in `**/conftest.py`", "## 1. Fixtures in `../conftest.py`"])
def test_a_heading_with_a_glob_or_dot_dot_opens_nothing(make_bench, heading):
    """SCN-IMP-175"""
    bench, task, red, green = run_both(
        make_bench, green_writing(NEW_CONFTEST), text=SECTION_ONLY, head=f"{heading}\n\n", plan=True
    )
    assert bench.events("task.unfrozen") == []


# --- named-tests 2.1: a helper red stubbed, which green fills in (L4-IMP-083) ---

FAKES = "tests/fakes_store.py"
FAKES_STUB = "def make_store():\n    raise NotImplementedError\n"
FAKES_FILLED = "def make_store():\n    return {'a': 1}\n"
STORE_TEST = "from fakes_store import make_store\n\n\ndef test_store_has_a():\n    assert make_store()['a'] == 1\n"
HELPER_TEXT = "- [ ] 1.1 Add `apply_discount` and fill in the fake in `tests/fakes_store.py`\n"


def red_with_helper() -> Step:
    step = red_env()
    step.writes = {
        **{k: v for k, v in step.writes.items() if k != "tests/test_otel.py"},
        FAKES: FAKES_STUB,
        "tests/test_store.py": STORE_TEST,
    }
    step.structured = result(
        "red", tests_added=["tests/test_discount.py::test_known_code"], criteria_ids=[KNOWN, UNKNOWN]
    )
    return step


def run_helper(make_bench, helper: str):
    bench = make_bench(
        [red_with_helper(), Step(writes={"src/pytdd/pricing.py": IMPL, FAKES: helper}, structured=result("green"))]
    )
    task = prepare(bench, text=HELPER_TEXT, plan=True)
    red = run_red(bench.wb, task, attempt=1)
    assert red.status == "ok", red.reason
    return bench, run_green(bench.wb, task, red, attempt=1)


def test_the_helper_red_stubbed_is_opened_for_green(make_bench):  # SCN-IMP-405
    bench, _ = run_helper(make_bench, FAKES_FILLED)
    [event] = bench.events("task.unfrozen")
    assert event["reason"] == "named_by_task" and event["paths"] == [FAKES] and event["kept"] == []
    assert "tests/test_store.py" not in event["paths"]
    assert f"- {FAKES}" in bench.adapter.requests[-1].prompt


def test_green_fills_in_the_helper_red_stubbed_and_the_task_completes(make_bench):  # SCN-IMP-405
    bench, green = run_helper(make_bench, FAKES_FILLED)
    assert green.status == "ok", green.reason
    assert violations(bench) == [] and bench.events("guard.test_tamper") == []
    assert (bench.wb.worktree / FAKES).read_text() == FAKES_FILLED
    assert bench.wb.git.run("show", f"{green.sha}:{FAKES}").stdout == FAKES_FILLED


def test_green_may_not_rename_a_function_of_the_helper(make_bench):  # SCN-IMP-406
    bench, green = run_helper(make_bench, FAKES_FILLED.replace("make_store", "build_store"))
    [event] = violations(bench, "opened file")
    assert event["path"] == FAKES and event["why"] == "drops make_store" and event["action"] == "restored"
    assert (bench.wb.worktree / FAKES).read_text() == FAKES_STUB
    assert green.status == "failed"


def test_green_may_not_add_a_test_to_the_helper(make_bench):  # SCN-IMP-406
    bench, _ = run_helper(make_bench, FAKES_FILLED + "\n\ndef test_fake():\n    assert 1\n")
    [event] = violations(bench, "opened file")
    assert event["why"] == "adds a test test_fake"
    assert (bench.wb.worktree / FAKES).read_text() == FAKES_STUB
