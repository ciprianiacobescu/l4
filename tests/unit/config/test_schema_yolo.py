"""`yolo.profiles` (yolo-mode L4-YOLO-009): gate kinds validated, `all` and `none` reserved."""

import pytest
from pydantic import ValidationError

from l4.config.schema import L4Config


def test_default_has_no_profiles():
    assert L4Config().yolo.profiles == {}


def test_profiles_of_gate_kinds_and_extras():
    cfg = L4Config.model_validate(
        {"yolo": {"profiles": {"fast": ["lint", "typecheck"], "full": ["test", "e2e", "extra:perf"]}}}
    )
    assert cfg.yolo.profiles["full"] == ["test", "e2e", "extra:perf"]


@pytest.mark.parametrize("name", ["all", "none"])
def test_reserved_names_are_refused(name):
    with pytest.raises(ValidationError, match="reserved"):
        L4Config.model_validate({"yolo": {"profiles": {name: ["lint"]}}})


@pytest.mark.parametrize("kind", ["deploy", "extra:", "extra", "Test", ""])
def test_unknown_gate_kinds_are_refused(kind):
    with pytest.raises(ValidationError, match="gate kind"):
        L4Config.model_validate({"yolo": {"profiles": {"p": [kind]}}})


def test_unknown_key_and_wrong_types_are_refused():
    with pytest.raises(ValidationError):
        L4Config.model_validate({"yolo": {"profile": {}}})
    with pytest.raises(ValidationError):
        L4Config.model_validate({"yolo": {"profiles": {"p": "lint"}}})
