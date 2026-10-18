"""`delegate:` and `roles.delegate` (delegate-answers 1.1; L4-DLG-001, L4-DLG-009, L4-AVL-010; D1, D2, D10)."""

import subprocess
from pathlib import Path

import pytest

from l4.agents.base import ProbeCtx
from l4.agents.factory import Factory
from l4.availability.errors import REQUIRED_ROLES, RoleUnavailable
from l4.config.loader import ConfigSchemaError, load_config_text
from l4.config.schema import L4Config, RolesCfg
from l4.delegate.settings import delegate_settings
from l4.vcs.git import Git

KINDS = ["technical", "product", "ambiguous", "harness", "verdict"]


def test_delegate_defaults():
    cfg = L4Config()
    d = cfg.delegate
    assert d.enabled is False and d.scope == "yolo" and d.kinds == KINDS
    assert d.independence == "model" and d.unfreeze is False
    assert (d.max_attempts_per_question, d.max_answers_per_task, d.max_questions_per_run) == (2, 3, 5)
    assert (d.max_cost_usd_per_answer, d.max_cost_usd_per_unit, d.plan_cost_share) == (3.0, 15.0, 0.25)
    assert d.timeout == "15m"
    assert cfg.roles.delegate == []


SECRET = "zz-bad-value-zz"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("scope", SECRET),
        ("kinds", [SECRET]),
        ("independence", SECRET),
        ("plan_cost_share", 0),
        ("plan_cost_share", 1.5),
        ("max_cost_usd_per_answer", -1),
        ("max_cost_usd_per_unit", -2),
        ("timeout", "30s"),
        ("max_attempts_per_question", 0),
        ("max_answers_per_task", 0),
        ("max_questions_per_run", 0),
        ("enabled", "yes"),
    ],
)
def test_delegate_rejects_bad_values(key, value):
    text = "delegate:\n  " + key + ": " + repr(value) + "\n"
    with pytest.raises(ConfigSchemaError) as err:
        load_config_text(text)
    rendered = str(err.value) + repr(err.value.issues)
    assert "delegate" in rendered and key in rendered
    assert SECRET not in rendered


def test_delegate_accepts_a_full_section():
    text = (
        "delegate:\n  enabled: true\n  scope: all\n  kinds: [technical, verdict]\n  independence: profile\n"
        "  unfreeze: true\n  timeout: 1m\n  plan_cost_share: 1\n  max_cost_usd_per_answer: 2.5\n"
    )
    d = load_config_text(text).delegate
    assert d.enabled and d.scope == "all" and d.kinds == ["technical", "verdict"]
    assert d.independence == "profile" and d.unfreeze and d.timeout == "1m" and d.plan_cost_share == 1


def test_delegate_is_an_optional_role(tmp_path: Path):
    assert "delegate" in RolesCfg.model_fields and "delegate" not in REQUIRED_ROLES
    ctx = ProbeCtx(environ={"PATH": "/usr/bin"}, cwd=tmp_path, run=lambda *a: None)
    with pytest.raises(RoleUnavailable) as err:
        Factory(L4Config(), ctx).for_role("delegate", "openspec:add-x")
    assert "no profile is configured for it under roles" in str(err.value)


def _repo(tmp_path: Path, config: str | None) -> tuple[Git, Path]:
    root = tmp_path / "r"
    root.mkdir()
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        "HOME": str(tmp_path),
        "GIT_CONFIG_GLOBAL": "/dev/null",
    }

    def sh(*args: str) -> None:
        subprocess.run(["git", *args], cwd=root, env=env, check=True, capture_output=True)

    sh("init", "--quiet", "-b", "main")
    sh("config", "user.email", "t@example.com")
    sh("config", "user.name", "t")
    (root / "x").write_text("x")
    if config is not None:
        (root / ".l4").mkdir()
        (root / ".l4" / "config.yaml").write_text(config)
    sh("add", "-A")
    sh("commit", "--quiet", "-m", "c")
    sh("update-ref", "refs/remotes/origin/main", "HEAD")
    return Git(root, environ=env), root


def test_delegate_settings_come_from_the_base(tmp_path: Path):
    base = (
        "profiles:\n"
        "  delegate-opus: {adapter: claude-code, model: claude-opus-5-5, auth: subscription, vendor: anthropic}\n"
        "roles:\n  delegate: [delegate-opus]\ndelegate:\n  enabled: true\n  scope: all\n  max_answers_per_task: 4\n"
    )
    git, root = _repo(tmp_path, base)
    # a value committed only on a unit branch (and an uncommitted edit) is not seen (SCN-DLG-02)
    git.run("checkout", "--quiet", "-b", "unit")
    (root / ".l4" / "config.yaml").write_text("delegate:\n  enabled: false\n")
    git.run("commit", "--quiet", "-am", "unit")
    got = delegate_settings(git, "main")
    assert got.delegate.enabled is True and got.delegate.scope == "all" and got.delegate.max_answers_per_task == 4
    assert got.chain == ["delegate-opus"]
    assert "delegate-opus" in got.profiles


@pytest.mark.parametrize("config", [None, "delegate: [\n", "delegate:\n  scope: nowhere\n", "- a list\n"])
def test_an_absent_or_invalid_file_gives_the_defaults(tmp_path: Path, config):
    git, _ = _repo(tmp_path, config)
    got = delegate_settings(git, "main")
    assert got.delegate == L4Config().delegate and got.delegate.enabled is False and got.chain == []


def test_an_unknown_base_gives_the_defaults(tmp_path: Path):
    git, _ = _repo(tmp_path, "delegate:\n  enabled: true\n")
    assert delegate_settings(git, "nope").delegate.enabled is False
