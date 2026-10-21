"""run-continuation 6.3 (L4-IMP-074): the base's own run names a default-branch copy of the workflow that is behind.
A bare `origin` holds `main` (the default branch, with its copy of `l4.yml`) and `staging` (the base)."""

import json
from pathlib import Path

import pytest

from l4 import orchestrator
from l4.ci import pin_guard
from l4.ci.github import WORKFLOW_RELPATH, ActionPin, render_github_action_ci
from l4.ci.relay import default_copy_warning, parse_release
from l4.config.loader import load_config
from l4.config.schema import L4Config
from l4.context import AppContext
from l4.redact import Redactor

OLD = "a" * 40
NEW = "b" * 40
CONFIG = "version: 1\nharness:\n  delivery: action\nforge:\n  base_branch: staging\n"
COPY_STEP = "copy .github/workflows/l4.yml to main once (or promote staging)"


def workflow(pin: str, ref: str | None = None, copy: bool = False) -> str:
    return render_github_action_ci(L4Config(), ActionPin("o/harness", pin, ref, copy=copy))


class World:
    def __init__(self, tmp_path: Path, raw, git_environ: dict[str, str]) -> None:
        self.tmp_path, self.raw = tmp_path, raw
        origin = tmp_path / "origin.git"
        raw(tmp_path, "init", "-q", "--bare", str(origin))
        self.main = tmp_path / "main-clone"  # where `main`'s copy of the workflow is edited
        self.main.mkdir()
        raw(self.main, "init", "-q")
        raw(self.main, "checkout", "-q", "-b", "main")
        raw(self.main, "remote", "add", "origin", str(origin))
        self.set_default_copy(workflow(OLD, "v0.4.18"))
        self.repo = tmp_path / "repo"
        self.repo.mkdir()
        raw(self.repo, "init", "-q")
        raw(self.repo, "remote", "add", "origin", str(origin))
        raw(self.repo, "fetch", "-q", "origin")
        raw(self.repo, "checkout", "-q", "-b", "staging", "origin/main")
        (self.repo / ".l4").mkdir()
        (self.repo / ".l4/config.yaml").write_text(CONFIG)
        (self.repo / WORKFLOW_RELPATH).write_text(workflow(NEW, "v0.4.19"))
        raw(self.repo, "add", "-A")
        raw(self.repo, "commit", "-q", "-m", "base")
        payload = tmp_path / "event.json"
        payload.write_text(json.dumps({"repository": {"default_branch": "main"}}))
        self.env = {
            **git_environ, "GITHUB_ACTIONS": "true", "GITHUB_REF_NAME": "staging", "GITHUB_REF_TYPE": "branch",
            "L4_BASE_BRANCH": "staging", "GITHUB_EVENT_PATH": str(payload),
        }  # fmt: skip

    def set_default_copy(self, text: str | None) -> None:
        """`main`'s copy of the workflow (None: `main` has no workflow), pushed and fetched."""
        path = self.main / WORKFLOW_RELPATH
        path.parent.mkdir(parents=True, exist_ok=True)
        if text is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(text)
        (self.main / "README.md").write_text(f"{text}\n")
        self.raw(self.main, "add", "-A")
        self.raw(self.main, "commit", "-q", "--allow-empty", "-m", "main copy")
        self.raw(self.main, "push", "-q", "-f", "origin", "main")
        if hasattr(self, "repo"):
            self.raw(self.repo, "fetch", "-q", "origin")

    def warning(self, **env: str) -> str | None:
        return default_copy_warning(load_config(self.repo), self.repo, {**self.env, **env})


@pytest.fixture
def world(tmp_path, raw, git_environ) -> World:
    return World(tmp_path, raw, git_environ)


def test_an_older_default_copy_is_named(world):  # SCN-IMP-375
    text = world.warning()
    assert text is not None and text.startswith("::warning::") and text.count("::warning::") == 1
    assert "main" in text and OLD[:7] in text and NEW[:7] in text and "v0.4.18" in text
    assert "its scheduled runs cannot relay to staging" in text and COPY_STEP in text


def test_a_newer_release_says_they_relay(world):
    world.set_default_copy(workflow(OLD, "v0.4.19"))
    text = world.warning()
    assert text is not None and "v0.4.19" in text and "its scheduled runs relay to staging" in text
    assert "cannot relay" not in text and COPY_STEP in text


def test_an_unknown_release_uses_the_conditional_wording(world):  # SCN-IMP-383
    for text in (workflow(OLD, copy=True), workflow(OLD), workflow(OLD, "main")):
        world.set_default_copy(text)
        warning = world.warning()
        assert warning is not None
        assert "if that copy is older than 0.4.19, its scheduled runs cannot relay" in warning
        assert "(v" not in warning and COPY_STEP in warning


def test_releases_compare_as_numbers():
    assert parse_release("# v0.4.9") == (0, 4, 9) and parse_release("# v0.4.9") < (0, 4, 19)
    assert parse_release("# v0.4.19") == (0, 4, 19) and parse_release("# v1.0.0") > (0, 4, 19)
    assert parse_release("# main") is None and parse_release("") is None and parse_release("# 0.4.9") is None


def test_a_numeric_compare_says_cannot_relay(world):  # SCN-IMP-383, the second case
    world.set_default_copy(workflow(OLD, "v0.4.9"))
    warning = world.warning()
    assert warning is not None and "v0.4.9" in warning and "being older than 0.4.19" in warning
    assert "its scheduled runs cannot relay to staging" in warning


def test_a_default_branch_without_the_workflow_is_named(world):  # SCN-IMP-383, last case
    world.set_default_copy(None)
    warning = world.warning()
    assert warning is not None and warning.startswith("::warning::the default branch main has no")
    assert ".github/workflows/l4.yml" in warning and "no scheduled run starts there" in warning
    assert COPY_STEP in warning


def test_no_warning_for_the_same_pin_an_unknown_default_or_another_delivery(world, tmp_path):  # SCN-IMP-376
    world.set_default_copy(workflow(NEW, "v0.4.19"))
    assert world.warning() is None  # the same pin
    world.set_default_copy(workflow(OLD, "v0.4.18"))
    assert world.warning() is not None
    (tmp_path / "event.json").write_text(json.dumps({"repository": {}}))
    assert world.warning() is None  # the payload names no default branch
    (tmp_path / "event.json").write_text(json.dumps({"repository": {"default_branch": "staging"}}))
    assert world.warning() is None  # the base is the default branch
    (tmp_path / "event.json").write_text(json.dumps({"repository": {"default_branch": "gone"}}))
    assert world.warning() is None  # a default branch this checkout has no ref for
    (tmp_path / "event.json").write_text("not json")
    assert world.warning() is None
    assert world.warning(GITHUB_EVENT_PATH=str(tmp_path / "missing.json")) is None
    (tmp_path / "event.json").write_text(json.dumps({"repository": {"default_branch": "main"}}))
    assert world.warning() is not None
    (world.repo / ".l4/config.yaml").write_text(
        "version: 1\nharness:\n  delivery: vendored\nforge:\n  base_branch: staging\n"
    )
    assert world.warning() is None  # another delivery
    (world.repo / ".l4/config.yaml").write_text(CONFIG)
    assert world.warning(GITHUB_ACTIONS="false") is None
    assert world.warning(GITHUB_REF_NAME="main") is None  # not the base's own run


def test_run_prints_it_once_on_the_base(world, monkeypatch, capsys):
    monkeypatch.setattr(pin_guard, "harness_commit", lambda: NEW)
    reached = RuntimeError("past the warning")
    monkeypatch.setattr(orchestrator, "preflight_run_config", lambda *a, **k: (_ for _ in ()).throw(reached))
    app = AppContext(
        repo=world.repo, config_path=None, log_format="human", verbosity=0, run_id="r-20261020T1000Z-0001",
        environ=world.env, redactor=Redactor({}),
    )  # fmt: skip
    with pytest.raises(RuntimeError, match="past the warning"):
        orchestrator.run_command(app)
    err = capsys.readouterr().err
    assert err.count("::warning::the default branch main's copy") == 1 and "v0.4.18" in err
