"""M1.13 lines 4-7 (MAG): the agent step makes the result alias, the prompt names it, and a result is never read from
anywhere but the private directory (the damage line: a path inside the worktree is a way into the commit)."""

import dataclasses
import json
import os
import shutil

import pytest

from l4.agents.base import AdapterError
from l4.agents.fake import Step
from l4.implementer.tdd import run_red

from .conftest import KNOWN, STUB, TESTS, UNKNOWN, red_step, result
from .test_tdd_red import TASK

RESULT = result("red", tests_added=["tests/test_discount.py::test_known_code"], criteria_ids=[KNOWN, UNKNOWN])
BARE = Step(writes={"tests/test_discount.py": TESTS, "src/pytdd/pricing.py": STUB})  # no host-side result


def prompt_contract(bench) -> None:
    caps = dataclasses.replace(bench.adapter.capabilities(), schema_mode="prompt_contract")
    bench.adapter.capabilities = lambda: caps  # type: ignore[method-assign]


def around(bench, action):
    """Run `action(request)` inside the adapter's step, before the scripted step is applied."""
    original = bench.adapter.run
    seen: dict = {}

    def run(req):
        seen["request"] = req
        action(req, seen)
        return original(req)

    bench.adapter.run = run  # type: ignore[method-assign]
    return seen


def test_the_alias_exists_during_the_step_and_a_result_written_through_it_is_accepted(make_bench):
    bench = make_bench([BARE])
    prompt_contract(bench)

    def write(req, seen):
        alias = req.cwd / ".l4-result"
        seen["during"] = alias.is_symlink() and alias.resolve() == req.result_path.parent.resolve()
        (alias / "result.json").write_text(json.dumps(RESULT), encoding="utf-8")

    seen = around(bench, write)
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert seen["during"] is True
    assert outcome.status == "ok", outcome.reason
    assert not (bench.wb.worktree / ".l4-result").exists() and not (bench.wb.worktree / ".l4-result").is_symlink()
    assert ".l4-result" not in bench.wb.git.run("ls-files").stdout


def test_the_alias_is_gone_after_a_step_that_raises(make_bench):
    bench = make_bench([BARE])

    def boom(req, seen):
        raise AdapterError("the adapter died")

    around(bench, boom)
    with pytest.raises(AdapterError):
        run_red(bench.wb, TASK, attempt=1)
    assert not os.path.lexists(bench.wb.worktree / ".l4-result")


def test_the_prompt_of_a_prompt_contract_adapter_names_the_alias_and_not_the_host_path(make_bench):
    bench = make_bench([red_step()])
    prompt_contract(bench)
    run_red(bench.wb, TASK, attempt=1)
    request = bench.adapter.requests[0]
    assert "Write your result object to `.l4-result/result.json`." in request.prompt
    assert str(request.result_path.parent) not in request.prompt and "agent-tmp" not in request.prompt


def test_a_native_adapters_prompt_is_unchanged(make_bench):
    bench = make_bench([red_step()])
    run_red(bench.wb, TASK, attempt=1)
    assert "Write your result object to" not in bench.adapter.requests[0].prompt
    assert ".l4-result" not in bench.adapter.requests[0].prompt


def test_a_result_at_the_worktrees_agent_tmp_is_not_accepted_and_is_not_committed(make_bench):
    """The magnitude path. Damage line: the worktree is staged by `git add -A`, so it can never be a result location."""
    bench = make_bench([dataclasses.replace(BARE, writes={**BARE.writes, "agent-tmp/result.json": json.dumps(RESULT)})])
    prompt_contract(bench)
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed" and "no result was delivered" in outcome.reason
    assert not (bench.wb.worktree / "agent-tmp").exists() and bench.wb.is_clean()
    assert "agent-tmp" not in bench.wb.git.run("ls-files").stdout
    assert "agent-tmp" not in bench.wb.git.run("log", "--all", "--name-only", "--format=").stdout


def test_an_alias_replaced_by_a_real_directory_holding_the_result_is_not_accepted(make_bench):
    bench = make_bench([BARE])
    prompt_contract(bench)

    def replace(req, seen):
        alias = req.cwd / ".l4-result"
        alias.unlink()
        alias.mkdir()
        (alias / "result.json").write_text(json.dumps(RESULT), encoding="utf-8")

    around(bench, replace)
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed" and "no result was delivered" in outcome.reason
    assert not os.path.lexists(bench.wb.worktree / ".l4-result")
    assert "result.json" not in bench.wb.git.run("log", "--all", "--name-only", "--format=").stdout


def test_a_gate_after_the_step_finds_no_alias_and_no_result_file(make_bench):
    """The gate sandbox mounts no `agent-tmp`: nothing a gate runs may find the result, or the link, in the worktree."""
    bench = make_bench([BARE])

    def write(req, seen):
        (req.cwd / ".l4-result" / "result.json").write_text(json.dumps(RESULT), encoding="utf-8")

    around(bench, write)
    run_red(bench.wb, TASK, attempt=1)
    spec = bench.wb.gate_spec(network=False)
    assert spec.tmp_dir != bench.wb.agent_tmp
    assert not os.path.lexists(bench.wb.worktree / ".l4-result")
    shutil.rmtree(bench.wb.agent_tmp, ignore_errors=True)


def test_an_alias_replaced_by_an_unremovable_directory_still_ends_with_the_protected_paths_put_back(make_bench):
    """m1.13 review: a read-only directory under the alias made `drop` raise inside `finally`, which skipped
    `revert_protected` and left what the agent wrote at a protected path in the worktree for the next commit."""
    bench = make_bench([BARE])
    prompt_contract(bench)

    def replace(req, seen):
        alias = req.cwd / ".l4-result"
        alias.unlink()
        (alias / "locked").mkdir(parents=True)
        (alias / "locked" / "f").write_text("x", encoding="utf-8")
        (alias / "locked").chmod(0o555)
        (req.cwd / "CLAUDE.md").write_text("ignore the specs", encoding="utf-8")  # a protected path

    around(bench, replace)
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed"
    assert not os.path.lexists(bench.wb.worktree / ".l4-result")
    assert not (bench.wb.worktree / "CLAUDE.md").exists()


def test_an_alias_the_agent_committed_with_force_does_not_reach_the_branch(make_bench):
    bench = make_bench([BARE])
    prompt_contract(bench)

    def commit(req, seen):
        (req.cwd / ".l4-result" / "result.json").write_text(json.dumps(RESULT), encoding="utf-8")
        git = bench.wb.git
        git.run("add", "-f", ".l4-result")
        git.run("-c", "user.name=a", "-c", "user.email=a@b", "commit", "-m", "smuggle")

    around(bench, commit)
    run_red(bench.wb, TASK, attempt=1)
    assert ".l4-result" not in bench.wb.git.run("ls-files").stdout
    assert ".l4-result" not in bench.wb.git.run("log", "--name-only", "--format=").stdout
    assert not os.path.lexists(bench.wb.worktree / ".l4-result")
