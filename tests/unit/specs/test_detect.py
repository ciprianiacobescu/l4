import socket
import subprocess
from pathlib import Path

import pytest

from l4.config.schema import L4Config
from l4.exitcodes import ExitCode
from l4.specs.base import Framework, NoFrameworkError
from l4.specs.detect import collect_units, detect_frameworks, require_framework
from l4.specs.kiro import KiroProvider
from l4.specs.openspec import OpenSpecProvider


def put(repo: Path, rel: str, text: str = "x") -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def cfg(**spec) -> L4Config:
    return L4Config.model_validate({"spec": spec} if spec else {})


@pytest.mark.parametrize(
    "rel", ["openspec/config.yaml", "openspec/config.yml", "openspec/specs/a.md", "openspec/changes/a/x.md"]
)
def test_openspec_signals(tmp_path, rel):
    put(tmp_path, rel)
    found = detect_frameworks(tmp_path)
    assert found.frameworks == (Framework.OPENSPEC,)
    assert not found.legacy_openspec


def test_openspec_and_legacy_signals(tmp_path):
    put(tmp_path, "openspec/project.md")
    put(tmp_path, "openspec/changes/x/tasks.md")
    legacy = detect_frameworks(tmp_path)
    assert legacy.frameworks == ()
    assert legacy.legacy_openspec
    put(tmp_path, "openspec/config.yaml")
    modern = detect_frameworks(tmp_path)
    assert modern.frameworks == (Framework.OPENSPEC,)
    assert not modern.legacy_openspec


@pytest.mark.parametrize("name", ["requirements.md", "bugfix.md", "design.md", "tasks.md"])
def test_kiro_signals(tmp_path, name):
    put(tmp_path, f".kiro/specs/user-auth/{name}")
    assert detect_frameworks(tmp_path).frameworks == (Framework.KIRO,)


def test_weak_signals_do_not_detect_frameworks(tmp_path):
    put(tmp_path, ".kiro/prompts/opsx-apply.md")
    put(tmp_path, ".kiro/skills/openspec/SKILL.md")
    put(tmp_path, ".kiro/specs/empty/.config.kiro")
    put(tmp_path, "specs/notes.md")
    put(tmp_path, ".specify/readme.md")
    found = detect_frameworks(tmp_path)
    assert found.frameworks == ()
    assert not found.speckit
    assert not found.legacy_openspec


def test_speckit_is_reported_never_active(tmp_path):
    put(tmp_path, ".specify/memory/constitution.md")
    put(tmp_path, "specs/001-x/tasks.md")
    found = detect_frameworks(tmp_path)
    assert found.speckit
    assert found.frameworks == ()
    assert detect_frameworks(tmp_path).speckit  # stable


@pytest.mark.parametrize("rel", [".specify/init-options.json", ".specify/templates/a.md"])
def test_speckit_other_signals(tmp_path, rel):
    put(tmp_path, rel)
    assert detect_frameworks(tmp_path).speckit


def test_symlinked_roots_are_not_signals(tmp_path):
    outside = tmp_path / "outside"
    put(outside, "changes/a/x.md")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "openspec").symlink_to(outside)
    (repo / ".kiro").symlink_to(outside)
    assert detect_frameworks(repo).frameworks == ()


def test_detection_is_filesystem_only(tmp_path, monkeypatch):
    put(tmp_path, "openspec/config.yaml")
    put(tmp_path, ".kiro/specs/a/tasks.md")
    put(tmp_path, ".specify/memory/constitution.md")

    def boom(*_a, **_k):
        raise AssertionError("detection started a process or opened a socket")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    found = detect_frameworks(tmp_path)
    assert found.frameworks == (Framework.OPENSPEC, Framework.KIRO)


def test_custom_roots_follow_config(tmp_path):
    put(tmp_path, "docs/os/changes/a/x.md")
    put(tmp_path, "kiro-specs/a/tasks.md")
    found = detect_frameworks(tmp_path, openspec_root="docs/os", kiro_root="kiro-specs")
    assert found.frameworks == (Framework.OPENSPEC, Framework.KIRO)


def test_require_framework_exit_14(tmp_path):
    put(tmp_path, "specs/notes.md")
    with pytest.raises(NoFrameworkError, match="l4 init") as err:
        require_framework(cfg(), tmp_path)
    assert err.value.code is ExitCode.REJECTED
    require_framework(L4Config.model_validate({"sdd": {"enforce": False}}), tmp_path)  # no enforce: no exit
    put(tmp_path, ".kiro/specs/a/tasks.md")
    require_framework(cfg(), tmp_path)


def test_require_framework_legacy_openspec_is_unsupported(tmp_path):
    put(tmp_path, "openspec/project.md")
    put(tmp_path, "openspec/changes/x/tasks.md")
    with pytest.raises(NoFrameworkError, match="migrat"):
        require_framework(cfg(), tmp_path)


def test_require_framework_honours_an_explicit_framework_list(tmp_path):
    put(tmp_path, ".kiro/specs/a/tasks.md")
    require_framework(cfg(frameworks=["openspec"]), tmp_path)  # a named framework is active even without files
    with pytest.raises(NoFrameworkError):
        require_framework(cfg(), tmp_path / "empty")


def test_mixed_repository_lists_both_and_speckit_is_inert(tmp_path):
    put(tmp_path, "openspec/config.yaml")
    put(tmp_path, "openspec/changes/add-a/tasks.md", "- [ ] 1.1 a\n")
    put(tmp_path, ".kiro/specs/feat-b/tasks.md", "- [ ] 1. b\n")
    put(tmp_path, ".specify/memory/constitution.md")
    put(tmp_path, "specs/001-x/tasks.md")
    providers = [OpenSpecProvider(tmp_path, {}), KiroProvider(tmp_path)]
    assert [u.id for u in collect_units(providers)] == ["openspec:add-a", "kiro:feat-b"]
    assert detect_frameworks(tmp_path).speckit
