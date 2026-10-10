import pytest

from l4.config.loader import load_config
from l4.specs.base import Framework, UnknownUnit
from l4.specs.providers import provider_for_unit, providers_for


def repo_with(tmp_path, *, openspec: bool, kiro: bool, config: str = ""):
    if openspec:
        (tmp_path / "openspec" / "changes" / "add-x").mkdir(parents=True)
        (tmp_path / "openspec" / "changes" / "add-x" / "tasks.md").write_text("- [ ] 1.1 a\n")
    if kiro:
        (tmp_path / ".kiro" / "specs" / "greet").mkdir(parents=True)
        (tmp_path / ".kiro" / "specs" / "greet" / "tasks.md").write_text("- [ ] 1. a\n")
    if config:
        (tmp_path / ".l4").mkdir()
        (tmp_path / ".l4" / "config.yaml").write_text(f"version: 1\n{config}")
    return tmp_path


def frameworks(repo) -> list[Framework]:
    return [p.framework for p in providers_for(load_config(repo), repo, {})]


def test_auto_returns_what_detection_finds(tmp_path):
    assert frameworks(repo_with(tmp_path, openspec=True, kiro=True)) == [Framework.OPENSPEC, Framework.KIRO]


def test_a_kiro_only_repository_has_no_openspec_provider(tmp_path):
    assert frameworks(repo_with(tmp_path, openspec=False, kiro=True)) == [Framework.KIRO]


def test_an_empty_repository_has_no_provider(tmp_path):
    assert frameworks(tmp_path) == []


def test_a_list_names_the_frameworks_even_without_files(tmp_path):
    repo = repo_with(tmp_path, openspec=False, kiro=False, config="spec:\n  frameworks: [kiro]\n")
    assert frameworks(repo) == [Framework.KIRO]


def test_the_provider_of_a_unit_is_chosen_by_its_id(tmp_path):
    repo = repo_with(tmp_path, openspec=True, kiro=True)
    providers = providers_for(load_config(repo), repo, {})
    assert provider_for_unit(providers, "kiro:greet").framework is Framework.KIRO
    assert provider_for_unit(providers, "openspec:add-x").framework is Framework.OPENSPEC
    with pytest.raises(UnknownUnit):
        provider_for_unit(providers[:1], "kiro:greet")
