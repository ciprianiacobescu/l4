"""The tools run the l4 command they name, as an agent, in a repository the instance serves (L4-MCP-002/003/005)."""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from l4.cli import redactor_for
from l4.mcp import tools as tools_mod
from l4.mcp.repos import Repos
from l4.mcp.tools import CallControl, Completed, Toolbox, UnknownTool


class Recorder:
    def __init__(self, stdout: str = "", returncode: int = 0, stderr: str = "") -> None:
        self.runs: list[dict] = []
        self.reply = Completed(returncode, stdout, stderr)

    def __call__(self, argv, cwd, env, timeout, control):
        self.runs.append({"argv": list(argv), "cwd": cwd, "env": env, "timeout": timeout})
        return self.reply


def control() -> CallControl:
    return CallControl(threading.Event(), lambda text: None)


def box(repos: Repos, recorder: Recorder, environ=None) -> Toolbox:
    env = {"PATH": os.environ.get("PATH", ""), "CLAUDECODE": "1"} if environ is None else environ
    return Toolbox(repos=repos, environ=env, redactor=redactor_for(env), runner=recorder)


@pytest.fixture
def one(repo_factory):
    root = repo_factory("mint-mory")
    return root, Repos.from_paths([root], cwd=Path("/"))


def call(toolbox, name, arguments=None):
    return toolbox.call(name, arguments or {}, control())


def text_of(result) -> str:
    return result["content"][0]["text"]


# --- which tools, which command -----------------------------------------------------------------------------------

CASES = {
    "l4_status": ({}, ["status", "--json"]),
    "l4_status ": ({"unit": "openspec:a"}, ["status", "--json", "--unit=openspec:a"]),
    "l4_doctor": ({"adoption": True}, ["doctor", "--json", "--adoption"]),
    "l4_plan_status": ({"plan": "p"}, ["yolo", "status", "--json", "--", "p"]),
    "l4_plan_check": ({"plan": "p"}, ["yolo", "check", "--", "p"]),
    "l4_plan_check ": ({"plan": "p", "worktree": True}, ["yolo", "check", "--worktree", "--", "p"]),
    "l4_plan_findings": ({"plan": "p", "worktree": True}, ["yolo", "findings", "--json", "--worktree", "--", "p"]),
    "l4_plan_report": ({"plan": "p"}, ["yolo", "report", "--", "p"]),
    "l4_questions": ({"unit": "openspec:a"}, ["questions", "list", "--json", "--unit=openspec:a"]),
    "l4_question": (
        {"unit": "openspec:a", "id": "Q-001"},
        ["questions", "show", "--json", "--unit=openspec:a", "--", "Q-001"],
    ),
    "l4_unit_events": (
        {"unit": "openspec:a", "type": "task.attempt_failed", "last": 3},
        ["status", "--json", "--unit=openspec:a", "--type=task.attempt_failed", "--last=3", "--events"],
    ),
    "l4_verification": ({"unit": "openspec:a"}, ["status", "--unit=openspec:a", "--verification"]),
    "l4_plan_draft": (
        {"plan": "p", "target": "main", "merge": "human", "update": True},
        ["yolo", "draft", "--target=main", "--merge=human", "--update", "--", "p"],
    ),
    "l4_plan_review": ({"plan": "p", "worktree": True}, ["yolo", "review", "--json", "--worktree", "--", "p"]),
    "l4_plan_review ": ({"plan": "p", "no_run": True}, ["yolo", "review", "--no-run", "--", "p"]),
    "l4_question_answer": (
        {"unit": "openspec:a", "id": "Q-002", "text": "yes, -x", "no_push": True},
        ["questions", "answer", "--unit=openspec:a", "--text=yes, -x", "--no-push", "--", "Q-002"],
    ),
    "l4_retry": (
        {"unit": "openspec:a", "reason": "fixed", "rounds": 2},
        ["retry", "--unit=openspec:a", "--reason=fixed", "--rounds=2"],
    ),
    "l4_plan_resume": (
        {"plan": "p", "reason": "ok", "extend_cost": 5},
        ["yolo", "resume", "--reason=ok", "--extend-cost=5", "--", "p"],
    ),
}


@pytest.mark.parametrize("key", list(CASES))
def test_every_tool_runs_the_command_it_names_in_the_repository_as_an_agent(one, key):  # SCN-MCP-03, 05
    root, repos = one
    recorder = Recorder("{}" if "--json" in CASES[key][1] else "ok")
    arguments, tail = CASES[key]
    result = call(box(repos, recorder), key.strip(), arguments)
    assert result["isError"] is False
    [run] = recorder.runs
    assert run["argv"][:3] == [sys.executable, "-m", "l4"]
    assert run["argv"][3:] == tail
    assert run["cwd"] == root
    assert run["env"]["AI_AGENT"] == "l4-mcp"
    assert run["timeout"] > 0


def test_the_full_tool_list_and_no_activation(one):  # SCN-MCP-07
    _, repos = one
    names = {t["name"] for t in box(repos, Recorder()).specs()}
    assert names == {
        "l4_status", "l4_doctor", "l4_plan_status", "l4_plan_check", "l4_plan_findings", "l4_plan_report",
        "l4_questions", "l4_question", "l4_unit_events", "l4_verification",
        "l4_plan_draft", "l4_plan_review", "l4_question_answer", "l4_retry", "l4_plan_resume",
    }  # fmt: skip
    specs = {t["name"]: t for t in box(repos, Recorder()).specs()}
    assert 'l4 yolo activate <plan> --reason "' in specs["l4_plan_status"]["description"]
    for spec in specs.values():
        assert "yolo activate" not in json.dumps(spec["inputSchema"])
        assert spec["inputSchema"]["type"] == "object" and spec["description"]


def test_write_tools_say_what_they_write_and_the_review_says_it_costs(one):
    _, repos = one
    specs = {t["name"]: t["description"] for t in box(repos, Recorder()).specs()}
    for name in ("l4_plan_draft", "l4_plan_review", "l4_question_answer", "l4_retry", "l4_plan_resume"):
        assert "origin" in specs[name] or "working tree" in specs[name]
        assert "CI" in specs[name]
    assert "judge tokens" in specs["l4_plan_review"] and "minutes" in specs["l4_plan_review"]
    assert "push" in specs["l4_retry"].lower() and "pushes" in specs["l4_question_answer"].lower()


def test_the_child_environment_is_the_callers_plus_the_agent_marker_and_stdin_is_closed(one):
    _, repos = one
    recorder = Recorder("{}")
    call(box(repos, recorder, {"PATH": "/bin", "FOO": "bar"}), "l4_status")
    env = recorder.runs[0]["env"]
    assert env["FOO"] == "bar" and env["AI_AGENT"] == "l4-mcp"


def test_the_real_runner_closes_stdin_and_sets_the_marker(tmp_path):
    script = "import os,sys;print(os.environ['AI_AGENT'], sys.stdin.isatty(), repr(sys.stdin.read()))"
    done = tools_mod.run_subprocess(
        [sys.executable, "-c", script], tmp_path, {**os.environ, "AI_AGENT": "l4-mcp"}, 30, control()
    )
    assert done.stdout.strip() == "l4-mcp False ''"
    assert done.returncode == 0


def test_a_nonzero_exit_is_an_error_result_with_the_exit_code(one):
    _, repos = one
    result = call(box(repos, Recorder("refused: agent", 2, "stderr words")), "l4_question_answer",
                  {"unit": "openspec:a", "id": "Q-001", "text": "x"})  # fmt: skip
    assert result["isError"] is True
    assert "refused: agent" in text_of(result) and "stderr words" in text_of(result)
    assert result["structuredContent"]["exit_code"] == 2


def test_json_output_is_parsed_into_structured_content(one):
    root, repos = one
    result = call(box(repos, Recorder('{"units": [1]}')), "l4_status")
    assert result["structuredContent"]["json"] == {"units": [1]}
    assert result["structuredContent"]["repo"] == str(root)


def test_output_that_is_not_json_has_no_json_key(one):
    _, repos = one
    result = call(box(repos, Recorder("not json")), "l4_status")
    assert "json" not in result["structuredContent"]


def test_every_result_names_its_repository(one):  # L4-MCP-005
    root, repos = one
    result = call(box(repos, Recorder("x")), "l4_plan_report", {"plan": "p"})
    assert text_of(result).startswith(f"repo: {root}\n")
    assert result["structuredContent"]["repo"] == str(root)


def test_output_is_redacted_again(one):
    _, repos = one
    env = {"PATH": "x", "GITLAB_TOKEN": "glpat-abcdefghijklmnopqrstuvwxyz0123456789"}
    result = call(
        box(repos, Recorder("token glpat-abcdefghijklmnopqrstuvwxyz0123456789 end"), env),
        "l4_plan_report",
        {"plan": "p"},
    )
    assert "glpat-abcdefghijklmnopqrstuvwxyz0123456789" not in json.dumps(result)


def test_output_is_cut_at_64_kib_and_the_cut_is_said(one):
    _, repos = one
    result = call(box(repos, Recorder("a" * 200_000)), "l4_plan_report", {"plan": "p"})
    assert len(text_of(result)) < 70_000
    assert "cut at 65536" in text_of(result)
    assert result["structuredContent"]["truncated"] is True


def test_a_cut_json_is_not_parsed(one):
    _, repos = one
    big = json.dumps({"x": "a" * 200_000})
    result = call(box(repos, Recorder(big)), "l4_status")
    assert "json" not in result["structuredContent"] and result["structuredContent"]["truncated"] is True


# --- arguments --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("l4_plan_check", {}),  # plan required
        ("l4_plan_check", {"plan": 5}),
        ("l4_plan_check", {"plan": "p", "worktree": "yes"}),
        ("l4_plan_check", {"plan": "p", "surprise": 1}),
        ("l4_retry", {"unit": "u", "reason": "r", "rounds": "2"}),
        ("l4_retry", {"unit": "u"}),
        ("l4_plan_draft", {"plan": "p", "merge": "sometimes"}),
        ("l4_unit_events", {"unit": "u", "last": True}),
    ],
)
def test_bad_arguments_are_an_error_result_and_nothing_runs(one, name, arguments):
    _, repos = one
    recorder = Recorder()
    result = call(box(repos, recorder), name, arguments)
    assert result["isError"] is True and recorder.runs == []


def test_an_unknown_tool_raises_unknown_tool(one):
    _, repos = one
    with pytest.raises(UnknownTool):
        call(box(repos, Recorder()), "l4_activate")


def test_a_value_that_looks_like_an_option_stays_a_value(one):
    _, repos = one
    recorder = Recorder()
    call(box(repos, recorder), "l4_plan_report", {"plan": "--repo=/etc"})
    argv = recorder.runs[0]["argv"]
    assert argv[-2:] == ["--", "--repo=/etc"]


def test_tools_cannot_pass_the_global_repo_or_config_options(one):
    _, repos = one
    recorder = Recorder()
    result = call(box(repos, recorder), "l4_status", {"config": "/etc/x", "path": "/etc"})
    assert result["isError"] is True and recorder.runs == []


# --- repositories (L4-MCP-005) ---------------------------------------------------------------------------------


def test_two_instances_run_each_in_its_own_repository(repo_factory):  # SCN-MCP-10
    a, b = repo_factory("mint-mory"), repo_factory("mintkey")
    ra, rb = Recorder("{}"), Recorder("{}")
    res_a = call(box(Repos.from_paths([a], cwd=Path("/")), ra), "l4_status")
    res_b = call(box(Repos.from_paths([b], cwd=Path("/")), rb), "l4_status")
    assert ra.runs[0]["cwd"] == a and rb.runs[0]["cwd"] == b
    assert str(a) in text_of(res_a) and str(b) in text_of(res_b)


def test_with_several_repositories_the_repo_argument_picks_one(repo_factory):
    a, b = repo_factory("mint-mory"), repo_factory("mintkey")
    recorder = Recorder("{}")
    toolbox = box(Repos.from_paths([a, b], cwd=Path("/")), recorder)
    call(toolbox, "l4_status", {"repo": "mintkey"})
    call(toolbox, "l4_status", {"repo": str(a)})
    assert [r["cwd"] for r in recorder.runs] == [b, a]
    assert all("--repo" not in r["argv"] for r in recorder.runs)  # the repo argument is not passed to the CLI


def test_the_schema_requires_repo_only_with_several_repositories(repo_factory):
    a, b = repo_factory("mint-mory"), repo_factory("mintkey")
    several = box(Repos.from_paths([a, b], cwd=Path("/")), Recorder()).specs()
    single = box(Repos.from_paths([a], cwd=Path("/")), Recorder()).specs()
    assert all("repo" in t["inputSchema"]["required"] and "repo" in t["inputSchema"]["properties"] for t in several)
    assert all(
        "repo" not in t["inputSchema"].get("required", []) and "repo" in t["inputSchema"]["properties"] for t in single
    )


def test_a_repository_not_served_is_refused_with_the_list_and_nothing_runs(repo_factory):  # SCN-MCP-11
    a, b = repo_factory("mint-mory"), repo_factory("mintkey")
    recorder = Recorder()
    toolbox = box(Repos.from_paths([a, b], cwd=Path("/")), recorder)
    for bad in ("/etc", "other", None):
        arguments = {"plan": "p"} | ({} if bad is None else {"repo": bad})
        result = call(toolbox, "l4_plan_status", arguments)
        assert result["isError"] is True
        assert str(a) in text_of(result) and str(b) in text_of(result)
    assert recorder.runs == []


def test_no_repository_no_guess(tmp_path):  # SCN-MCP-12
    recorder = Recorder()
    toolbox = box(Repos.from_paths([], cwd=tmp_path), recorder)
    for name in ("l4_status", "l4_retry", "l4_plan_report"):
        result = call(toolbox, name, {"unit": "u", "reason": "r", "plan": "p"})
        assert result["isError"] is True and "--repo PATH" in text_of(result)
    assert recorder.runs == []
    assert toolbox.specs()  # listing still works: an IDE may start the server anywhere


def test_the_working_directory_serves_when_it_is_a_repository(repo_factory):
    root = repo_factory("here")
    recorder = Recorder("{}")
    call(box(Repos.from_paths([], cwd=root), recorder), "l4_status")
    assert recorder.runs[0]["cwd"] == root


def test_the_real_runner_stops_on_cancel_and_on_timeout(tmp_path):
    sleeper = [sys.executable, "-c", "import time; time.sleep(60)"]
    stop = threading.Event()
    stop.set()
    cancelled = tools_mod.run_subprocess(sleeper, tmp_path, dict(os.environ), 30, CallControl(stop, lambda t: None))
    assert cancelled.cancelled is True
    timed = tools_mod.run_subprocess(sleeper, tmp_path, dict(os.environ), 0.5, control())
    assert timed.timed_out is True


def test_a_timeout_is_an_error_result_that_says_so(one):
    _, repos = one
    recorder = Recorder()
    recorder.reply = Completed(-9, "partial", "", timed_out=True)
    result = call(box(repos, recorder), "l4_status")
    assert result["isError"] is True and "timed out" in text_of(result)


def test_a_real_command_through_the_real_runner(repo_factory):
    root = repo_factory("real")
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "AI_AGENT")}
    toolbox = Toolbox(repos=Repos.from_paths([root], cwd=Path("/")), environ=env, redactor=redactor_for(env))
    result = call(toolbox, "l4_plan_report", {"plan": "nope"})
    assert result["structuredContent"]["exit_code"] != 0 and result["isError"] is True
    assert subprocess is not None
