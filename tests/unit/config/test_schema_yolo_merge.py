"""`yolo.merge` (squash-and-delete L4-YOLO-032, L4-YOLO-033): the method and the branch deletion."""

import pytest
from pydantic import ValidationError

from l4.config.schema import L4Config


def test_defaults_squash_and_delete_branches():
    merge = L4Config().yolo.merge
    assert merge.method == "squash"
    assert merge.delete_branches is True


def test_fast_forward_and_keeping_branches_are_accepted():
    cfg = L4Config.model_validate({"yolo": {"merge": {"method": "fast-forward", "delete_branches": False}}})
    assert cfg.yolo.merge.method == "fast-forward"
    assert cfg.yolo.merge.delete_branches is False


@pytest.mark.parametrize("method", ["rebase", "merge", "Squash", ""])
def test_unknown_method_is_refused(method):
    with pytest.raises(ValidationError, match="method"):
        L4Config.model_validate({"yolo": {"merge": {"method": method}}})


def test_unknown_key_and_wrong_type_are_refused():
    with pytest.raises(ValidationError, match="delete_branch"):
        L4Config.model_validate({"yolo": {"merge": {"delete_branch": True}}})
    with pytest.raises(ValidationError):
        L4Config.model_validate({"yolo": {"merge": {"delete_branches": "maybe"}}})


def test_require_ci_defaults_to_false_and_accepts_both_values():
    """L4-YOLO-043: a hand-off commit that no CI ran on merges unless the repository asks to wait for one."""
    assert L4Config().yolo.merge.require_ci is False
    on = L4Config.model_validate({"yolo": {"merge": {"require_ci": True}}})
    off = L4Config.model_validate({"yolo": {"merge": {"require_ci": False}}})
    assert on.yolo.merge.require_ci is True and off.yolo.merge.require_ci is False


def test_require_ci_refuses_a_value_that_is_not_a_boolean():
    with pytest.raises(ValidationError, match="require_ci"):
        L4Config.model_validate({"yolo": {"merge": {"require_ci": "maybe"}}})
