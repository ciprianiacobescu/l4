"""The schema is checked against SPEC 3.2 itself: the reference block in docs/SPEC.md is the oracle."""

import copy
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from l4.config.schema import L4Config, Profile, duration_seconds

SPEC = Path(__file__).resolve().parents[3] / "docs" / "SPEC.md"
# Sections the schema models; the rest are accepted as opaque mappings (see schema.OPAQUE_SECTIONS).
MODELLED_DEFAULTS = (
    "spec", "sdd", "tdd", "odd", "gates", "sandbox", "availability", "implementer", "clarifier",
    "verifier", "forge", "locks", "ci", "budgets", "observability",
)  # fmt: skip
NOT_YET_MODELLED: set[tuple[str, str]] = set()  # `ci.self_provision` arrived with M1.4 (runner-provisioning 1.2)
# keys SPEC 3.2 does not have: forge.gitlab (M0, C2)
ADDED_BEYOND_SPEC = {("forge", "gitlab")}


def reference_config() -> dict[str, Any]:
    text = SPEC.read_text(encoding="utf-8")
    start = text.index("### 3.2 Reference configuration")
    block = re.search(r"```yaml\n(.*?)\n```", text[start:], re.S)
    assert block, "SPEC 3.2 yaml block not found"
    return yaml.safe_load(block.group(1))


def test_version_only_file_yields_full_defaults():
    ref = reference_config()
    cfg = L4Config.model_validate({"version": 1}).model_dump(mode="json")
    for section in MODELLED_DEFAULTS:
        expected = copy.deepcopy(ref[section])
        for sec, key in NOT_YET_MODELLED:
            if sec == section:
                expected.pop(key)
        if section == "sandbox":
            for cache in expected["caches"].values():
                cache.setdefault("read_only", False)
            expected["credential_paths"]["opencode"].append("~/.cache/opencode")  # M1.2 G17; SPEC 3.2 owes the entry
        actual = {k: v for k, v in cfg[section].items() if (section, k) not in ADDED_BEYOND_SPEC}
        assert actual == expected, section
    assert cfg["forge"]["gitlab"] == {"api_url": None, "project": None}
    assert cfg["harness"] == {"version": None, "commit": None, "repository": None, "delivery": None}
    assert cfg["profiles"] == {}
    assert cfg["roles"]["implementer"] == [] and cfg["roles"]["judges"] == []
    assert L4Config().model_dump() == L4Config.model_validate({"version": 1}).model_dump()


def test_reference_config_validates_with_placeholder_commit():
    ref = reference_config()
    ref["harness"]["commit"] = "0" * 40
    cfg = L4Config.model_validate(ref)
    assert cfg.roles.implementer == ["codex-sol", "claude-sonnet", "opencode-or"]
    assert cfg.profiles["judge-opus"].api_key_env == "ANTHROPIC_API_KEY"
    assert cfg.clarifier.s1_router is True and cfg.clarifier.s1_standin == "none"


def test_version_2_is_rejected():
    with pytest.raises(ValidationError):
        L4Config.model_validate({"version": 2})


@pytest.mark.parametrize(
    "bad",
    [
        {"verifer": {}},
        {"tdd": {"mod": "strict"}},
        {"gates": {"test": {"comand": "x"}}},
        {"profiles": {"p": {"modell": "x"}}},
        {"harness": {"commit": "xyz"}},
        {"gates": {"timeout": "30 minutes"}},
        {"ci": {"time_budget": "soon"}},
        {"spec": {"frameworks": ["openspec", "svn"]}},
        {"clarifier": {"s1_standin": "boolean"}},
        {"clarifier": {"min_confidence": "low"}},
        {"clarifier": {"max_open_questions": 0}},
        {"clarifier": {"auto_accept_kinds": ["verdict"]}},
        {"clarifier": {"autoaccept": True}},
    ],
)
def test_unknown_keys_and_bad_values_are_rejected(bad):
    with pytest.raises(ValidationError):
        L4Config.model_validate(bad)


def test_profile_accepts_both_adapter_and_backend():
    # CFG-002 (doctor, exit 3) reports this state; the loader must not (exit 2)
    p = Profile.model_validate({"adapter": "codex", "backend": "openai-chat", "api_key_env": "X"})
    assert p.adapter == "codex" and p.backend == "openai-chat"


def test_time_budget_accepts_auto_or_duration():
    assert L4Config.model_validate({"ci": {"time_budget": "auto"}}).ci.time_budget == "auto"
    assert L4Config.model_validate({"ci": {"time_budget": "90m"}}).ci.time_budget == "90m"


def test_duration_to_seconds():
    assert duration_seconds("45s") == 45
    assert duration_seconds("30m") == 1800
    assert duration_seconds("24h") == 86400
    with pytest.raises(ValueError):
        duration_seconds("1d")


def test_a_credential_paths_override_for_one_adapter_keeps_the_other_adapters_hidden_paths():
    """SEC-005: dropping a default entry would let that adapter's login be read by another adapter's agent."""
    from l4.config import defaults as d

    cfg = L4Config.model_validate({"sandbox": {"credential_paths": {"codex": ["~/elsewhere/codex"]}}})
    paths = cfg.sandbox.credential_paths
    assert paths["codex"] == ["~/elsewhere/codex"]
    for adapter, default in d.CREDENTIAL_PATHS.items():
        if adapter != "codex":
            assert paths[adapter] == list(default)
    extra = L4Config.model_validate({"sandbox": {"credential_paths": {"newtool": ["/opt/newtool"]}}})
    assert set(extra.sandbox.credential_paths) == set(d.CREDENTIAL_PATHS) | {"newtool"}
    assert L4Config().sandbox.credential_paths == {k: list(v) for k, v in d.CREDENTIAL_PATHS.items()}


@pytest.mark.parametrize(
    "section",
    [
        {"sandbox": {"credential_paths": {"codex": ["relative/dir"]}}},
        {"sandbox": {"credential_paths": {"codex": ["~other/.codex"]}}},
        {"sandbox": {"caches": {"x": {"path": "$L4_CACHE/../escape", "env": "X"}}}},
        {"sandbox": {"caches": {"x": {"path": "relative/cache", "env": "X"}}}},
        {"gates": {"test": {"command": "pytest", "reports": ["/abs/junit.xml"]}}},
        {"gates": {"test": {"command": "pytest", "reports": ["../junit.xml"]}}},
        {"gates": {"e2e": {"reports": [""]}}},
    ],
)
def test_path_values_that_can_never_work_are_usage_errors_at_load_time(section, tmp_path):
    from l4.config.loader import ConfigSchemaError, load_config

    (tmp_path / ".l4").mkdir()
    (tmp_path / ".l4" / "config.yaml").write_text(yaml.safe_dump({"version": 1, **section}))
    with pytest.raises(ConfigSchemaError) as err:
        load_config(tmp_path)
    assert err.value.code == 2
    assert "relative/dir" not in str(err.value) and "escape" not in str(err.value)  # value-free


@pytest.mark.parametrize(
    "bad",
    [
        {"spec": {"openspec": {"package": "https://evil.example/x.tgz"}}},
        {"spec": {"openspec": {"package": "git+ssh://git@host/x.git"}}},
        {"spec": {"openspec": {"package": "--registry=http://evil"}}},
        {"spec": {"openspec": {"package": "@scope/pkg@latest"}}},
        {"spec": {"openspec": {"version": "latest"}}},
        {"spec": {"openspec": {"version": "1.2.3 --ignore-scripts=false"}}},
        {"profiles": {"p": {"adapter": "claude-code", "min_version": "file:../x"}}},
        {"profiles": {"p": {"adapter": "claude-code", "min_version": ">=2.1"}}},
    ],
)
def test_installer_arguments_cannot_name_a_url_a_git_spec_or_a_flag(bad):
    with pytest.raises(ValidationError):
        L4Config.model_validate(bad)


def test_installer_arguments_accept_a_scoped_package_and_a_semver():
    cfg = L4Config.model_validate(
        {
            "spec": {"openspec": {"package": "@fission-ai/openspec", "version": "1.14.0"}},
            "profiles": {"p": {"adapter": "claude-code", "min_version": "2.1.0-beta.1"}},
        }
    )
    assert cfg.spec.openspec.version == "1.14.0" and cfg.profiles["p"].min_version == "2.1.0-beta.1"


def test_extra_keys_append_to_the_defaults():
    """A6 (M1.8): a project adds a test-support glob without restating (and so dropping) the defaults."""
    base = L4Config.model_validate({"version": 1})
    cfg = L4Config.model_validate(
        {
            "version": 1,
            "tdd": {"extra_test_support_globs": ["**/factories/**"], "extra_test_globs": ["spec/**"]},
            "odd": {"extra_forbidden_paths": ["secrets/**"]},
        }
    )
    assert cfg.tdd.test_support_globs == [*base.tdd.test_support_globs, "**/factories/**"]
    assert cfg.tdd.test_globs == [*base.tdd.test_globs, "spec/**"]
    assert cfg.odd.forbidden_paths == [*base.odd.forbidden_paths, "secrets/**"]


def test_explicit_list_plus_extra_keeps_both_once():
    cfg = L4Config.model_validate(
        {
            "version": 1,
            "tdd": {"test_support_globs": ["**/conftest.py"], "extra_test_support_globs": ["**/conftest.py", "x/**"]},
        }
    )
    assert cfg.tdd.test_support_globs == ["**/conftest.py", "x/**"]
    assert "test_support_globs" in cfg.tdd.model_fields_set  # the doctor can tell it was set on purpose


def test_extra_keys_default_to_nothing_and_do_not_change_the_defaults():
    cfg = L4Config.model_validate({"version": 1})
    assert cfg.tdd.extra_test_globs == [] and cfg.tdd.extra_test_support_globs == []
    assert cfg.odd.extra_forbidden_paths == []


def test_redact_forge_urls_defaults_on():
    """P5: committed history cannot be taken back, so the forge host stays out of it unless the owner says otherwise."""
    from l4.config.schema import L4Config

    assert L4Config.model_validate({}).observability.redact_forge_urls is True
    off = L4Config.model_validate({"observability": {"redact_forge_urls": False}})
    assert off.observability.redact_forge_urls is False


def test_yolo_hold_defaults_to_nothing_and_takes_ids_and_patterns():
    assert L4Config().yolo.hold == []
    cfg = L4Config.model_validate({"yolo": {"hold": ["openspec:a", "kiro:*"]}})
    assert cfg.yolo.hold == ["openspec:a", "kiro:*"]


def test_yolo_hold_rejects_an_empty_entry():
    with pytest.raises(ValidationError):
        L4Config.model_validate({"yolo": {"hold": ["openspec:a", ""]}})
