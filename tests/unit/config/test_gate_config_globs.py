"""The defaults of `tdd.gate_config_globs` and `tdd.runner_config_files`, and `tdd.extra_gate_config_globs`
(L4-IMP-040, design D6): `extra_*` keys add to whatever the list holds (L4-CFG-001)."""

import pytest
from pydantic import ValidationError

from l4.config.schema import L4Config

NEW_GATE_GLOBS = [
    "pyrightconfig.json", "pylintrc", ".eslintignore", ".prettierrc*", ".prettierignore", "biome.json", "biome.jsonc",
]  # fmt: skip


def test_the_new_gate_globs_and_coveragerc_are_defaults():
    tdd = L4Config.model_validate({"version": 1}).tdd
    assert all(glob in tdd.gate_config_globs for glob in NEW_GATE_GLOBS)
    assert ".coveragerc" in tdd.runner_config_files
    assert "mypy.ini" in tdd.gate_config_globs  # the old entries stay


def test_extra_gate_config_globs_default_to_nothing():
    assert L4Config.model_validate({"version": 1}).tdd.extra_gate_config_globs == []


def test_extra_gate_config_globs_are_appended_once_after_the_defaults():
    base = L4Config.model_validate({"version": 1}).tdd
    cfg = L4Config.model_validate({"version": 1, "tdd": {"extra_gate_config_globs": ["lint/**", "mypy.ini"]}}).tdd
    assert cfg.gate_config_globs == [*base.gate_config_globs, "lint/**"]


def test_extra_gate_config_globs_are_appended_after_a_set_list_too():
    cfg = L4Config.model_validate(
        {"version": 1, "tdd": {"gate_config_globs": ["mypy.ini"], "extra_gate_config_globs": ["mypy.ini", "x/**"]}}
    ).tdd
    assert cfg.gate_config_globs == ["mypy.ini", "x/**"]
    assert "gate_config_globs" in cfg.model_fields_set  # the doctor can tell it was set on purpose


def test_an_unknown_tdd_key_is_still_refused():
    with pytest.raises(ValidationError):
        L4Config.model_validate({"version": 1, "tdd": {"extra_gate_config_glob": ["x"]}})
