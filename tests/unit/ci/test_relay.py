"""run-continuation 6.2 (L4-IMP-072): a GitHub run on a stale copy of the workflow relays to the base before it reads
the configuration. The real commands run through `l4.cli.main` on a real repository with a bare origin; the forge is a
fake whose `relay_run` answer the test sets."""

import json
import re
from pathlib import Path

import pytest

from l4 import orchestrator
from l4.ci import pin_guard, relay
from l4.ci.github import WORKFLOW_RELPATH, ActionPin, render_github_action_ci
from l4.cli import main
from l4.config.schema import L4Config
from l4.forge.base import ForgeUnavailable

RUNNING = "a" * 40
PINNED = "b" * 40
BASE = "staging"
CONFIG = f"version: 1\nharness:\n  delivery: action\nforge:\n  base_branch: {BASE}\n"
ACTIVE = '{"type":"plan.activated","at":"2026-10-20T10:00:00Z"}\n'
WAITING = ACTIVE + '{"type":"plan.waiting","at":"2026-10-20T10:01:00Z","reason":"question"}\n'
STOPPED = ACTIVE + '{"type":"plan.stopped","at":"2026-10-20T10:01:00Z","reason":"limit_runs"}\n'
NOTICE = f"::notice::l4 relayed this run to {BASE}: started l4.yml on {BASE}, which runs the base's pin"
HOW = f"gh workflow run l4.yml --ref {BASE}"


class FakeForge:
    """What `make_forge` builds in the relay: records the call, answers what the test says (or raises it)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.answer: object = "dispatched"

    def relay_run(self, ref: str, *, exclude_run_id: str | None) -> str:
        self.calls.append((ref, exclude_run_id))
        if isinstance(self.answer, Exception):
            raise self.answer
        return str(self.answer)


@pytest.fixture
def forge(monkeypatch) -> FakeForge:
    fake = FakeForge()
    monkeypatch.setattr(relay, "make_forge", lambda cfg, environ, **kwargs: fake)
    monkeypatch.setattr(pin_guard, "harness_commit", lambda: RUNNING)
    return fake


def push_ref(tmp_path: Path, raw, origin: Path, ref: str, files: dict[str, str]) -> None:
    """A commit with `files` on `ref` of the bare origin (a plan ref), made in a scratch repository."""
    scratch = tmp_path / f"scratch-{len(list(tmp_path.glob('scratch-*')))}"
    scratch.mkdir()
    raw(scratch, "init", "-q")
    for name, text in files.items():
        (scratch / name).write_text(text)
    raw(scratch, "add", "-A")
    raw(scratch, "commit", "-q", "-m", "seed")
    raw(scratch, "push", "-q", str(origin), f"HEAD:{ref}")


class World:
    def __init__(self, tmp_path: Path, raw, git_environ: dict[str, str]) -> None:
        self.tmp_path, self.raw = tmp_path, raw
        self.origin = tmp_path / "origin.git"
        raw(tmp_path, "init", "-q", "--bare", str(self.origin))
        self.repo = tmp_path / "repo"
        self.repo.mkdir()
        raw(self.repo, "init", "-q")
        raw(self.repo, "checkout", "-q", "-b", BASE)
        (self.repo / ".l4").mkdir()
        (self.repo / ".l4/config.yaml").write_text(CONFIG)
        (self.repo / WORKFLOW_RELPATH).parent.mkdir(parents=True)
        (self.repo / WORKFLOW_RELPATH).write_text(render_github_action_ci(L4Config(), ActionPin("o/harness", PINNED)))
        raw(self.repo, "add", "-A")
        raw(self.repo, "commit", "-q", "-m", "base")
        raw(self.repo, "remote", "add", "origin", str(self.origin))
        raw(self.repo, "push", "-q", "origin", BASE)
        raw(self.repo, "fetch", "-q", "origin")
        self.env = {
            **git_environ,
            "GITHUB_ACTIONS": "true", "GITHUB_REF_NAME": "main", "GITHUB_REF_TYPE": "branch",
            "L4_BASE_BRANCH": BASE, "GITHUB_RUN_ID": "900", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_JOB": "l4",
            "RUNNER_TEMP": str(tmp_path / "runner"),
        }  # fmt: skip
        (tmp_path / "runner").mkdir()

    def plan(self, ledger: str, plan_id: str = "p1") -> None:
        push_ref(self.tmp_path, self.raw, self.origin, f"refs/l4/plans/{plan_id}", {"ledger.jsonl": ledger})

    def unit_branch(self, name: str = "l4/openspec/add-x") -> None:
        self.raw(self.repo, "push", "-q", "origin", f"HEAD:refs/heads/{name}")
        self.raw(self.repo, "fetch", "-q", "origin")

    def write(self, relpath: str, text: str = "x\n") -> None:
        (self.repo / relpath).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / relpath).write_text(text)

    def run(self, *argv: str, **env: str) -> int:
        return main([*argv, "--repo", str(self.repo)], environ={**self.env, **env})

    def outcome(self) -> dict:
        return json.loads((self.repo / ".l4-out/outcome.json").read_text())


@pytest.fixture
def world(tmp_path, raw, git_environ) -> World:
    return World(tmp_path, raw, git_environ)


@pytest.fixture
def working(world) -> World:
    """A base with an active plan: the relay has work to relay for."""
    world.plan(ACTIVE)
    return world


# --- the lenient read --------------------------------------------------------------------------------------------


def test_the_lenient_settings_ignore_unknown_keys(tmp_path):
    (tmp_path / ".l4").mkdir()
    config = tmp_path / ".l4/config.yaml"
    config.write_text(
        "bogus_key: 1\nharness:\n  delivery: action\n  repository: o/h\n  nope: 2\n"
        "forge:\n  type: github\n  base_branch: staging\n  branch_prefix: l4/\n  token_env: L4_TOKEN\n"
        "spec:\n  openspec:\n    root: ox\n  kiro:\n    root: kx\n"
    )
    assert relay.lenient_settings(tmp_path) == {
        "harness.delivery": "action", "harness.repository": "o/h", "forge.type": "github",
        "forge.base_branch": "staging", "forge.branch_prefix": "l4/", "forge.token_env": "L4_TOKEN",
        "spec.openspec.root": "ox", "spec.kiro.root": "kx",
    }  # fmt: skip
    config.write_text("a: [\n")
    assert relay.lenient_settings(tmp_path) == {}
    config.write_text("- not a mapping\n")
    assert relay.lenient_settings(tmp_path) == {}


def test_the_lenient_read_keeps_yaml_1_2_values_and_finds_the_delivery(tmp_path):  # SCN-IMP-384
    (tmp_path / ".l4").mkdir()
    config = tmp_path / ".l4/config.yaml"
    config.write_text("bogus: 1\nforge:\n  base_branch: on\n  token_env: L4_TOKEN\n  type: github\n")
    workflow = tmp_path / WORKFLOW_RELPATH
    workflow.parent.mkdir(parents=True)
    workflow.write_text(render_github_action_ci(L4Config(), ActionPin("o/harness", PINNED)))
    found = relay.lenient_settings(tmp_path)
    assert found["forge.base_branch"] == "on" and found["forge.token_env"] == "L4_TOKEN"
    assert found["harness.delivery"] == "action"  # no key, a setup-action pin in the workflow
    config.write_text("forge:\n  base_branch: [a, b]\n  token_env: {x: 1}\nharness:\n  repository: o/h\n")
    found = relay.lenient_settings(tmp_path)
    assert "forge.base_branch" not in found and "forge.token_env" not in found  # a mapping or a list is ignored
    assert found["harness.delivery"] == "fetched"  # harness.repository set, no delivery key
    config.write_text("forge:\n  platform: gitlab\n  type: gitlab\n")
    found = relay.lenient_settings(tmp_path)
    assert found["forge.type"] == "gitlab" and "forge.platform" not in found
    workflow.unlink()
    assert relay.lenient_settings(tmp_path)["harness.delivery"] == "vendored"
    big = tmp_path / "big.yaml"
    big.write_text("forge:\n  base_branch: x\n" + "# " + "x" * (1024 * 1024) + "\n")
    config.unlink()
    config.symlink_to(big)
    assert relay.lenient_settings(tmp_path) == {}  # a symlink is not read
    config.unlink()
    config.write_text(big.read_text())
    assert relay.lenient_settings(tmp_path) == {}  # nor a file over 1 MB


def test_the_relay_forge_is_built_from_forge_keys_only(working, monkeypatch):
    working.write(".l4/config.yaml", CONFIG + "ci:\n  platform: gitlab\nforge_unknown: 1\n")
    seen = []

    def build(cfg, environ, **kwargs):
        seen.append((cfg, environ))
        return FakeForge()

    monkeypatch.setattr(relay, "make_forge", build)
    monkeypatch.setattr(pin_guard, "harness_commit", lambda: RUNNING)
    assert working.run("doctor", "--ci") == 0
    from l4.forge.base import forge_platform

    cfg, environ = seen[0]
    assert cfg.forge.base_branch == BASE and cfg.ci.platform == "auto"
    assert forge_platform(cfg, environ) == "github"


# --- the early stop and the relay ----------------------------------------------------------------------------------


def test_a_scheduled_run_on_the_default_branch_relays(working, forge, capsys):  # SCN-IMP-350
    assert working.run("doctor", "--ci") == 0
    lines = [line for line in capsys.readouterr().err.splitlines() if line.startswith("::")]
    assert len(lines) == 2 and lines[0].startswith("::warning::") and lines[1] == NOTICE
    assert RUNNING in lines[0] and PINNED in lines[0]
    assert forge.calls == [(BASE, "900")]
    assert working.run("run") == 0
    assert working.outcome()["relay"] == "dispatched" and working.outcome()["exit_code"] == 0
    assert forge.calls == [(BASE, "900")]  # one dispatch for the job


def test_an_active_run_on_the_base_is_not_doubled(working, forge, capsys):  # SCN-IMP-351
    forge.answer = "already_running"
    assert working.run("doctor", "--ci") == 0
    assert f"l4: not relayed: a run of l4.yml is already queued or running on {BASE}" in capsys.readouterr().err
    assert working.run("run") == 0 and working.outcome()["relay"] == "already_running"


def test_a_mismatch_on_the_base_does_not_relay(working, forge, capsys):  # SCN-IMP-352
    assert working.run("run", GITHUB_REF_NAME=BASE) == 0
    err = capsys.readouterr().err
    assert "::warning::" in err and "relayed" not in err
    assert forge.calls == [] and working.outcome()["relay"] == "on_base"


def test_on_the_base_a_schema_error_stays_exit_2(working, forge, capsys):  # SCN-IMP-381
    working.write(".l4/config.yaml", CONFIG + "bogus_key: 1\n")
    assert working.run("doctor", "--ci", GITHUB_REF_NAME=BASE) == 2
    assert forge.calls == [] and "relayed" not in capsys.readouterr().err


def test_no_work_is_not_relayed(world, forge, capsys):  # SCN-IMP-353
    assert world.run("doctor", "--ci") == 0
    assert (
        f"l4: not relayed: {BASE} has no active or waiting plan, no unit branch and no unit folder"
        in capsys.readouterr().err
    )
    assert forge.calls == []
    assert world.run("run") == 0 and world.outcome()["relay"] == "no_work"


@pytest.mark.parametrize("ledger", [ACTIVE, WAITING])
def test_an_active_plan_and_a_waiting_plan_are_work(world, forge, ledger):
    world.plan(ledger)
    assert relay.relay_to_base(world.repo, world.env, relay.lenient_settings(world.repo)) == "dispatched"
    assert forge.calls == [(BASE, "900")]


def test_a_stopped_plan_is_not_work(world, forge):
    world.plan(STOPPED)
    assert relay.relay_to_base(world.repo, world.env, relay.lenient_settings(world.repo)) == "no_work"
    assert forge.calls == []


@pytest.mark.parametrize("files", [{"ledger.jsonl": "this is not a plan event\n"}, {"other.txt": "no ledger"}])
def test_an_unreadable_plan_ref_is_work(world, forge, files):  # SCN-IMP-354
    push_ref(world.tmp_path, world.raw, world.origin, "refs/l4/plans/p1", files)
    assert relay.relay_to_base(world.repo, world.env, relay.lenient_settings(world.repo)) == "dispatched"
    assert forge.calls == [(BASE, "900")]


def test_a_unit_branch_or_a_unit_folder_is_work(world, forge):  # SCN-IMP-371
    settings = relay.lenient_settings(world.repo)
    world.write("openspec/changes/archive/old/tasks.md")
    assert relay.relay_to_base(world.repo, world.env, settings) == "no_work"  # the archive alone is not work
    world.unit_branch()
    assert relay.relay_to_base(world.repo, world.env, settings) == "dispatched"
    world.raw(world.repo, "update-ref", "-d", "refs/remotes/origin/l4/openspec/add-x")
    assert relay.relay_to_base(world.repo, world.env, settings) == "no_work"
    world.write("openspec/changes/add-x/tasks.md")
    assert relay.relay_to_base(world.repo, world.env, settings) == "dispatched"
    (world.repo / "openspec/changes/add-x/tasks.md").unlink()
    world.write(".kiro/specs/feature/tasks.md")
    assert relay.relay_to_base(world.repo, world.env, settings) == "dispatched"
    assert len(forge.calls) == 3


@pytest.mark.parametrize("answer", ["refused", ForgeUnavailable("L4_FORGE_TOKEN is not set")])
def test_a_refused_token_names_the_command(working, forge, capsys, monkeypatch, answer):  # SCN-IMP-355
    if isinstance(answer, Exception):  # no token at all: make_forge raises

        def no_token(cfg, environ, **kwargs):
            raise answer

        monkeypatch.setattr(relay, "make_forge", no_token)
    else:
        forge.answer = answer
    assert working.run("doctor", "--ci") == 0
    err = capsys.readouterr().err
    assert f"l4: not relayed: the token may not start a run on {BASE}; start one with: {HOW}" in err
    assert working.run("run") == 0 and working.outcome()["relay"] == "refused"


def test_a_failure_of_the_forge_is_a_line_not_a_failed_job(working, forge, capsys):
    forge.answer = RuntimeError("boom\nsecond line")
    assert working.run("doctor", "--ci") == 0
    err = capsys.readouterr().err
    assert "l4: not relayed: boom" in err and "second line" not in err
    assert working.run("run") == 0 and working.outcome()["relay"] == "failed"


def test_outside_github_nothing_is_relayed(working, forge, monkeypatch):  # SCN-IMP-356
    env = {key: value for key, value in working.env.items() if not key.startswith("GITHUB_")}
    env["GITLAB_CI"] = "true"
    assert relay.early_pin_stop(working.repo, env, command="run") is None
    assert forge.calls == []
    monkeypatch.setattr(orchestrator, "preflight_run_config", lambda *a, **k: (_ for _ in ()).throw(KeyError("past")))
    with pytest.raises(KeyError):
        orchestrator.run_command(_app(working, env))
    assert forge.calls == []


def _app(world: World, env: dict[str, str]):
    from l4.context import AppContext
    from l4.redact import Redactor

    return AppContext(
        repo=world.repo, config_path=None, log_format="human", verbosity=0, run_id="r-20261020T1000Z-0001",
        environ=env, redactor=Redactor({}),
    )  # fmt: skip


def test_a_config_key_the_harness_does_not_know_does_not_defeat_the_relay(working, forge, capsys):  # SCN-IMP-369
    working.write(".l4/config.yaml", CONFIG + "bogus_key: 1\n")
    codes = [working.run("doctor", "--ci"), working.run("plan", "--sweep"), working.run("run"), working.run("status")]
    assert codes == [0, 0, 0, 0]
    err = capsys.readouterr().err
    assert err.count("::warning::") == 4 and err.count("::notice::") == 1
    assert forge.calls == [(BASE, "900")]
    assert "CFG-" not in err  # doctor ran none of its checks


def test_the_status_step_of_a_stopped_job_is_not_red(working, forge, capsys):  # SCN-IMP-382
    working.write(".l4/config.yaml", CONFIG + "bogus_key: 1\n")
    assert working.run("status") == 0
    err = capsys.readouterr().err
    assert err.startswith("::warning::") and "relayed" not in err
    assert forge.calls == []


def test_one_relay_per_job(working, forge, capsys):  # SCN-IMP-370
    assert working.run("doctor", "--ci") == 0
    marker = Path(working.env["RUNNER_TEMP"]) / "l4-relay.json"
    assert json.loads(marker.read_text()) == {"run_id": "900", "run_attempt": "1", "job": "l4", "answer": "dispatched"}
    capsys.readouterr()
    assert working.run("plan", "--sweep") == 0 and working.run("run") == 0
    err = capsys.readouterr().err
    assert err.count("l4: relayed earlier in this job (dispatched)") == 2
    assert forge.calls == [(BASE, "900")]
    assert working.run("doctor", "--ci", GITHUB_RUN_ID="901") == 0  # another run: the marker is not its own
    assert forge.calls[-1] == (BASE, "901")
    working.env.pop("RUNNER_TEMP")  # without RUNNER_TEMP the marker is in the checkout's output folder
    assert working.run("doctor", "--ci", GITHUB_RUN_ID="902") == 0
    assert json.loads((working.repo / ".l4-out/relay.json").read_text())["run_id"] == "902"
    assert working.run("run", GITHUB_RUN_ID="902") == 0 and forge.calls[-1] == (BASE, "902") and len(forge.calls) == 3


@pytest.mark.parametrize(
    "stale", [{"run_id": "1"}, {"run_attempt": "2"}, {"job": "other"}], ids=["run_id", "run_attempt", "job"]
)
def test_a_marker_of_another_run_attempt_or_job_is_ignored(working, forge, stale):  # SCN-IMP-370, last clause
    marker = Path(working.env["RUNNER_TEMP"]) / "l4-relay.json"
    marker.write_text(json.dumps({"run_id": "900", "run_attempt": "1", "job": "l4", "answer": "dispatched", **stale}))
    assert working.run("doctor", "--ci") == 0
    assert forge.calls == [(BASE, "900")]
    assert json.loads(marker.read_text())["run_id"] == "900"  # rewritten for this job
    assert json.loads(marker.read_text())["answer"] == "dispatched"


def test_the_marker_survives_a_bad_file(working, forge):
    (Path(working.env["RUNNER_TEMP"]) / "l4-relay.json").write_text("not json")
    assert working.run("doctor", "--ci") == 0
    assert forge.calls == [(BASE, "900")]


def test_the_outcome_has_a_relay_key_only_when_there_is_one():
    from l4.outcome import Outcome, write_outcome
    from l4.redact import Redactor

    def dump(**extra) -> dict:
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            outcome = Outcome(run_id="r", harness_version="0", exit_code=0, **extra)
            return json.loads(write_outcome(outcome, Path(folder), Redactor({})).read_text())

    assert "relay" not in dump()
    assert dump(relay="dispatched")["relay"] == "dispatched"
    assert re.fullmatch(r"[a-z_]+", dump(relay="no_work")["relay"])
