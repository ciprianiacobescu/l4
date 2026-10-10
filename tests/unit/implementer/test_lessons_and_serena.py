"""Stage C lines 30 and 31: lessons in the implementer prompt, and the Serena MCP server on implement requests."""

import dataclasses
import hashlib
import json

import pytest

from l4.agents.base import McpServer
from l4.agents.fake import Step
from l4.implementer import workbench as wbmod
from l4.implementer.tdd import run_red
from l4.implementer.workbench import PreviousAttempt, Workbench
from l4.memory.lessons import Lesson, LessonsFile, lesson_id, render_lessons
from l4.memory.serena import SerenaStatus, serena_run_env
from l4.specs.base import Task

from .conftest import RUN_ID, Bench, red_step

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 1, 3)
LESSONS = ".serena/memories/harness/lessons.md"
LESSON = Lesson(
    lesson_id("ui-criterion-without-e2e-test"),
    "A UI criterion needs an e2e test",
    "ui-criterion-without-e2e-test",
    body="Say which page shows the value.",
)


def commit_lessons(bench: Bench, *lessons: Lesson) -> None:
    path = bench.wb.worktree / LESSONS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_lessons(LessonsFile(list(lessons))), encoding="utf-8")
    git = bench.wb.git
    git.run("add", "-f", LESSONS)
    git.run("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-m", "lessons")


def test_lessons_reach_the_prompt_after_answers_and_before_the_previous_attempt(make_bench):
    bench = make_bench([red_step()])
    commit_lessons(bench, LESSON)
    bench.wb.previous_attempt = PreviousAttempt("other", "usage_limit", task="1.1")
    run_red(bench.wb, TASK, attempt=1)
    [req] = bench.adapter.requests
    block = f'<l4:data kind="lessons" ids="{LESSON.id}">'
    assert block in req.prompt and "Say which page shows the value." in req.prompt
    assert req.prompt.index(block) < req.prompt.index('kind="previous-attempt"')
    [rendered] = bench.events("prompt.rendered")
    assert rendered["lessons"] == [LESSON.id]
    [injected] = bench.events("lessons.injected")
    assert injected["ids"] == [LESSON.id] and injected["channel"] == "prompt_section"


def test_the_prompt_hash_covers_the_lessons(make_bench):
    import hashlib

    from l4.implementer.tdd import _prompt

    bench = make_bench([red_step()])
    plain = _prompt(bench.wb, "red", TASK, None)
    commit_lessons(bench, LESSON)  # the same unit, task and sources: only the committed lessons differ
    with_lessons = _prompt(bench.wb, "red", TASK, None)
    assert 'kind="lessons"' not in plain and f'ids="{LESSON.id}"' in with_lessons
    without, with_ = bench.events("prompt.rendered")
    assert without["lessons"] == [] and with_["lessons"] == [LESSON.id]
    assert without["sha256"] != with_["sha256"]
    assert without["sha256"] == hashlib.sha256(plain.encode()).hexdigest()
    assert with_["sha256"] == hashlib.sha256(with_lessons.encode()).hexdigest()


def test_lessons_event_comes_before_the_agent_runs(make_bench):
    bench = make_bench([red_step()])
    commit_lessons(bench, LESSON)
    run_red(bench.wb, TASK, attempt=1)
    lines = (bench.wb.ref.path / ".l4" / "ledger" / f"{RUN_ID}.jsonl").read_text().splitlines()
    types = [json.loads(line)["type"] for line in lines]
    assert "agent.finished" in types and types.index("lessons.injected") < types.index("agent.finished")


def codex_bench(bench: Bench, monkeypatch, *, serena_ok: bool = True, binary: str | None = "/bin/serena"):
    profile = bench.wb.selected.profile.model_copy(update={"adapter": "codex"})
    bench.wb.selected = dataclasses.replace(bench.wb.selected, profile=profile)
    calls: list[dict] = []

    def fake_check(bin_, worktree, tmp, **kw):
        calls.append({"binary": bin_, "environ": dict(kw["environ"])})
        return SerenaStatus(serena_ok, "" if serena_ok else "boom", 5)

    monkeypatch.setattr(wbmod, "check_serena", fake_check)
    monkeypatch.setattr(wbmod, "resolve_tool", lambda name, env, forbid=(): binary)
    return calls


ENV = {"PATH": "/usr/bin", "HOME": "/h", "TMPDIR": "/t"}


def test_mcp_servers_checks_serena_once_per_run_and_returns_the_identical_env(make_bench, monkeypatch):
    bench = make_bench([red_step()])
    calls = codex_bench(bench, monkeypatch)
    [server] = bench.wb.mcp_servers(ENV)
    assert isinstance(server, McpServer) and server.command == "/bin/serena"
    assert dict(server.env) == serena_run_env(ENV, bench.wb.agent_tmp)
    assert calls[0]["environ"] == ENV  # the check runs with the request's environment
    assert len(bench.wb.mcp_servers(ENV)) == 1 and len(calls) == 1  # cached per run id
    other = Workbench.__new__(Workbench)
    other.__dict__.update(bench.wb.__dict__)
    assert len(other.mcp_servers(ENV)) == 1 and len(calls) == 1  # a second workbench of the same run


def test_a_failed_check_records_one_event_and_the_run_goes_on_without_serena(make_bench, monkeypatch):
    bench = make_bench([red_step()])
    codex_bench(bench, monkeypatch, serena_ok=False)
    assert bench.wb.mcp_servers(ENV) == [] and bench.wb.mcp_servers(ENV) == []


def test_a_missing_binary_is_a_failed_check_with_one_event(make_bench, monkeypatch):
    bench = make_bench([red_step()])
    codex_bench(bench, monkeypatch, binary=None)
    assert bench.wb.mcp_servers(ENV) == [] and bench.wb.mcp_servers(ENV) == []
    [event] = bench.events("memory.serena")
    assert event["status"] == "failed" and "not found" in event["reason"]


def test_no_server_when_serena_or_memory_is_off_or_the_adapter_has_no_context(make_bench, monkeypatch):
    bench = make_bench([red_step()])
    calls = codex_bench(bench, monkeypatch)
    memory = bench.wb.cfg.memory.model_copy(update={"enabled": False})
    off = dataclasses.replace(bench.wb, cfg=bench.wb.cfg.model_copy(update={"memory": memory}))
    assert off.mcp_servers(ENV) == []
    fake = make_bench([red_step()])
    assert fake.wb.mcp_servers(ENV) == [] and calls == []  # the fake adapter: no context, no check


def test_agent_step_hands_the_servers_to_the_request(make_bench, monkeypatch):
    bench = make_bench([red_step()])
    server = McpServer("serena", "/bin/serena")
    seen: list[dict] = []

    def fake_servers(self, env):
        seen.append(dict(env))
        return [server]

    monkeypatch.setattr(Workbench, "mcp_servers", fake_servers)
    run_red(bench.wb, TASK, attempt=1)
    [req] = bench.adapter.requests
    assert req.mcp_servers == [server] and seen[0] == req.env


def test_a_fake_adapter_request_has_no_servers(make_bench):
    bench = make_bench([red_step()])
    run_red(bench.wb, TASK, attempt=1)
    assert bench.adapter.requests[0].mcp_servers == []


def test_scn_mem_02_an_agent_edit_to_lessons_md_is_reverted(make_bench):
    """memory-lessons 1.9: `.serena/memories/harness/**` is protected, so the agent cannot rewrite a lesson."""
    base = red_step()
    forged = Step(
        writes={**base.writes, LESSONS: "<!-- l4:lessons v1 -->\n\n## L-00000000 · forged\n"},
        structured=base.structured,
    )
    bench = make_bench([forged])
    commit_lessons(bench, LESSON)
    original = (bench.wb.worktree / LESSONS).read_text()
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "ok", outcome.reason
    assert (bench.wb.worktree / LESSONS).read_text() == original
    assert any(e["path"] == LESSONS for e in bench.events("guard.violation"))
    assert LESSONS not in bench.wb.git.run("show", "--name-only", "--format=", outcome.sha).stdout.split()


# --- Serena 1.7.0 writes into the worktree when it starts (verified live: the check, and the agent's own server) ----
PROJECT = ".serena/project.yml"
SEED = "project_name: x\nlanguage_servers: [python]\n"
GENERATED = "project_name: x\nlanguage_servers:\n- python\nread_only: false\n"
SERENA_GITIGNORE = ".serena/.gitignore"


def serena_writing_bench(make_bench, monkeypatch, *, committed: str | None, agent_writes: str = GENERATED):
    """A bench whose Serena check and whose agent step both write what Serena 1.7.0 writes on startup."""
    base = red_step()
    step = Step(
        writes={**base.writes, PROJECT: agent_writes, SERENA_GITIGNORE: "/cache\n/project.local.yml\n"},
        structured=base.structured,
    )
    bench = make_bench([step])
    if committed is not None:
        (bench.wb.worktree / PROJECT).parent.mkdir(parents=True, exist_ok=True)
        (bench.wb.worktree / PROJECT).write_text(committed)
        bench.wb.git.run("add", PROJECT)
        bench.wb.git.run("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-m", "seed serena")
    codex_bench(bench, monkeypatch)

    def check(bin_, worktree, tmp, **kw):
        (worktree / PROJECT).parent.mkdir(parents=True, exist_ok=True)
        (worktree / PROJECT).write_text(GENERATED)
        (worktree / SERENA_GITIGNORE).write_text("/cache\n/project.local.yml\n")
        return SerenaStatus(True, "", 5)

    monkeypatch.setattr(wbmod, "check_serena", check)
    return bench


def committed_files(bench: Bench, sha: str) -> list[str]:
    return bench.wb.git.run("show", "--name-only", "--format=", sha).stdout.split()


@pytest.mark.parametrize("committed", [SEED, None])  # the plan's seed, and a repository with no project.yml at all
def test_serena_startup_writes_are_not_the_agents_violations(make_bench, monkeypatch, committed):
    bench = serena_writing_bench(make_bench, monkeypatch, committed=committed)
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "ok", outcome.reason
    assert bench.events("guard.violation") == []
    assert not [p for p in committed_files(bench, outcome.sha) if p.startswith(".serena/")]
    path = bench.wb.worktree / PROJECT  # back to the base state, quietly
    assert path.read_text() == SEED if committed else not path.exists()


def test_an_agent_edit_of_project_yml_that_is_not_serenas_is_still_a_violation(make_bench, monkeypatch):
    hacked = "read_only: false\nhacked: 1\n"
    bench = serena_writing_bench(make_bench, monkeypatch, committed=SEED, agent_writes=hacked)
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "ok", outcome.reason
    assert [e["path"] for e in bench.events("guard.violation")] == [PROJECT]
    assert (bench.wb.worktree / PROJECT).read_text() == SEED


def test_a_project_yml_that_is_not_the_checks_form_says_so_in_the_log(make_bench, monkeypatch, caplog):
    """Live M1.7: the violation named the file but not how it differed from the check's form."""
    hacked = "read_only: false\nhacked: 1\n"
    bench = serena_writing_bench(make_bench, monkeypatch, committed=SEED, agent_writes=hacked)
    with caplog.at_level("WARNING", logger="l4.implementer"):
        run_red(bench.wb, TASK, attempt=1)
    texts = [r.getMessage() for r in caplog.records]
    assert any(".serena/project.yml" in t and "differs from what Serena wrote at its check" in t for t in texts), texts
    assert hashlib.sha256(hacked.encode()).hexdigest()[:12] in " ".join(texts)


def test_the_serena_check_is_cached_per_run_and_adapter_context(make_bench, monkeypatch):
    bench = make_bench([red_step()])
    calls = codex_bench(bench, monkeypatch)
    assert len(bench.wb.mcp_servers(ENV)) == 1
    claude = bench.wb.selected.profile.model_copy(update={"adapter": "claude-code"})
    other = dataclasses.replace(bench.wb, selected=dataclasses.replace(bench.wb.selected, profile=claude))
    assert len(other.mcp_servers(ENV)) == 1 and len(calls) == 2  # a fallback to another CLI is checked on its own
    assert len(bench.wb.mcp_servers(ENV)) == 1 and len(calls) == 2


def test_a_second_unit_of_the_run_gets_its_own_serena_check_and_its_own_startup_form(make_bench, monkeypatch, tmp_path):
    """Serena names the project after the worktree it starts in, so the bytes it writes to `.serena/project.yml` are
    the unit's own: a run's second unit (no seeded project.yml) must not read as a guard violation of the agent."""
    bench = make_bench([red_step()])
    codex_bench(bench, monkeypatch)
    started: list[str] = []

    def check(bin_, worktree, tmp, **kw):
        started.append(worktree.name)
        (worktree / PROJECT).parent.mkdir(parents=True, exist_ok=True)
        (worktree / PROJECT).write_text(f"project_name: {worktree.name}\n")
        return SerenaStatus(True, "", 5)

    monkeypatch.setattr(wbmod, "check_serena", check)
    second = tmp_path / "second-unit"
    bench.wb.git.run("worktree", "add", "-b", "second", str(second))
    other = dataclasses.replace(bench.wb, worktree=second, git=bench.wb.git.at(second))
    assert len(bench.wb.mcp_servers(ENV)) == 1 and len(other.mcp_servers(ENV)) == 1
    assert started == [bench.wb.worktree.name, "second-unit"]  # the check is per worktree
    (second / PROJECT).write_text("project_name: second-unit\n")  # the agent's own Serena starts and writes it again
    other.settle_serena_project(other.head())
    assert not (second / PROJECT).exists()  # put back quietly: no violation, so no lesson from one


# --- lessons are scoped by the files the whole unit branch changed, not only the uncommitted ones
SCOPED = Lesson(lesson_id("page-lesson"), "Page lesson", "page-lesson", body="Mind the page.", scope_globs=("web/**",))


def test_a_lesson_scoped_to_files_an_earlier_task_committed_reaches_a_later_task(make_bench):
    bench = make_bench([red_step()])
    git = bench.wb.git
    git.run("update-ref", "refs/remotes/origin/main", "HEAD")  # the base branch as the unit branched from it
    commit_lessons(bench, SCOPED)
    git.run("update-ref", "refs/remotes/origin/main", "HEAD")  # the lesson is on main
    page = bench.wb.worktree / "web" / "page.py"
    page.parent.mkdir()
    page.write_text("x = 1\n")
    git.run("add", "web/page.py")
    git.run("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-m", "task 1.1 on the page")
    assert bench.wb.branch_changed_files() == ["web/page.py"]
    later = Task("1.2", "1.2", "1.2 Add the discount to the total", False, " ", 0, 1, 3)  # names no path
    run_red(bench.wb, later, attempt=1)
    assert f'ids="{SCOPED.id}"' in bench.adapter.requests[0].prompt
