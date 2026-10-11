import pytest
from pydantic import ValidationError

from l4.config.schema import L4Config


def test_github_environment_defaults_to_l4_and_can_be_null():
    assert L4Config().ci.github_environment == "l4"
    assert L4Config.model_validate({"ci": {"github_environment": None}}).ci.github_environment is None
    assert L4Config.model_validate({"ci": {"github_environment": "pipeline.prod_1-a"}}).ci.github_environment


@pytest.mark.parametrize("bad", ["", "a b", "x\ny: z", 'q"uote', "a/b", "x" * 256])
def test_github_environment_rejects_names_github_does_not_take(bad: str):
    with pytest.raises(ValidationError):
        L4Config.model_validate({"ci": {"github_environment": bad}})
