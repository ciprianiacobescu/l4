"""`l4 plan --detailed-exitcode` and `--probe` (M1.4 line 35), and the CI outputs plan writes."""

import json
from pathlib import Path

import pytest

from l4.agents import factory
from l4.agents.base import ProbeResult
from l4.cli import main

TASKS = "# Tasks\n\n## 1. Discounts\n\n- [ ] 1.1 Parse codes\n"
CONFIG = """\
profiles:
  impl: {adapter: fake, vendor: a}
  judge: {adapter: fake, vendor: b}
roles: {implementer: [impl], judges: [judge]}
"""


class Scripted:
    """Counts the probes it is asked; `fail` names a step that fails."""

    def __init__(self, fail: str | None = None) -> None:
        self.steps: list[str] = []
        self.fail = fail

    def probe(self, profile, step, ctx):
        self.steps.append(step)
        ok = step != self.fail
        return ProbeResult(step, ok, {}, reason=None if ok else f"{step} refused")


@pytest.fixture
def project(make_repo, git_environ, tmp_path: Path):
    repo = make_repo()
    change = repo / "openspec" / "changes" / "add-discount-codes"
    change.mkdir(parents=True)
    (change / "tasks.md").write_text(TASKS)
    (repo / ".l4").mkdir()
    (repo / ".l4" / "config.yaml").write_text(CONFIG)
    return repo, {**git_environ, "L4_CACHE": str(tmp_path / "cache")}


def plan(project, capsys, *argv: str, extra: dict | None = None):
    repo, environ = project
    code = main(["plan", *argv, "--repo", str(repo)], environ={**environ, **(extra or {})})
    out = capsys.readouterr()
    return code, out.out, out.err


def test_plan_exits_0_and_10_only_with_detailed_flag(project, capsys):
    assert plan(project, capsys)[0] == 0  # actionable work, no flag
    assert plan(project, capsys, "--detailed-exitcode")[0] == 10
    repo, _ = project
    (repo / "openspec" / "changes" / "add-discount-codes" / "tasks.md").write_text("- [x] 1.1 done\n")
    # a finished unit with no verification record is still actionable (verify); a merged one is not
    assert plan(project, capsys, "--detailed-exitcode")[0] == 10


def test_nothing_actionable_is_exit_0_even_with_the_flag(make_repo, git_environ, tmp_path, capsys):
    repo = make_repo()
    environ = {**git_environ, "L4_CACHE": str(tmp_path / "cache")}
    assert main(["plan", "--detailed-exitcode", "--repo", str(repo)], environ=environ) == 0


def test_plan_writes_the_ci_outputs_and_the_github_output_file(project, capsys, tmp_path):
    github_output = tmp_path / "gh-output"
    code, _, _ = plan(project, capsys, "--detailed-exitcode", extra={"GITHUB_OUTPUT": str(github_output)})
    repo, _ = project
    assert code == 10
    env_file = (repo / ".l4-out" / "l4.env").read_text().splitlines()
    assert env_file == ["L4_EXIT=10", "L4_UNITS_ACTIONABLE=1", "L4_PHASES=openspec:add-discount-codes=none"]
    lines = dict(line.split("=", 1) for line in github_output.read_text().splitlines())
    assert lines["exit_code"] == "10" and lines["units_actionable"] == "1"
    assert json.loads(lines["units"]) == ["openspec:add-discount-codes"]


def test_uncached_profiles_unknown_and_no_probe_without_flag(project, capsys, monkeypatch):
    agent = Scripted()
    monkeypatch.setitem(factory.ADAPTERS, "fake", lambda: agent)
    code, out, _ = plan(project, capsys, "--json")
    assert code == 0 and agent.steps == []  # no probe unless asked
    assert "availability" not in json.loads(out)  # the plan's shape does not change without --probe


def test_probe_runs_binary_auth_hello_for_the_heads_the_next_action_needs(project, capsys, monkeypatch):
    agent = Scripted()
    monkeypatch.setitem(factory.ADAPTERS, "fake", lambda: agent)
    code, out, _ = plan(project, capsys, "--json", "--probe")
    document = json.loads(out)
    assert code == 0
    # the implementer only: the next action is `implement`; the ladder is M1.2's, with the quota window
    assert agent.steps == ["binary", "auth", "quota", "hello"]
    assert document["availability"] == {"implementer": {"profile": "impl", "status": "usable"}}
    assert document["units"][0]["next_action"] == "implement"


def test_a_failed_probe_is_reported_and_never_fails_the_plan(project, capsys, monkeypatch):
    agent = Scripted(fail="auth")
    monkeypatch.setitem(factory.ADAPTERS, "fake", lambda: agent)
    code, out, _ = plan(project, capsys, "--probe")
    assert code == 0 and agent.steps == ["binary", "auth"]  # stops at the first failing step
    assert "availability:" in out and "implementer: impl unavailable" in out and "auth probe" in out


def test_probe_with_nothing_actionable_probes_nothing(make_repo, git_environ, tmp_path, capsys, monkeypatch):
    agent = Scripted()
    monkeypatch.setitem(factory.ADAPTERS, "fake", lambda: agent)
    repo = make_repo()
    environ = {**git_environ, "L4_CACHE": str(tmp_path / "cache")}
    assert main(["plan", "--probe", "--repo", str(repo)], environ=environ) == 0
    assert agent.steps == []
