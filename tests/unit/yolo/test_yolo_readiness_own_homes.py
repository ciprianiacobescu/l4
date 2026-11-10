"""L4-OCV-018 (SCN-OCV-41): the readiness review's agent spec sets `hide_own_homes` like `Workbench.agent_spec`."""

import pytest

from l4.agents.factory import Selected
from l4.config.schema import Profile
from l4.sandbox.none import NoSandbox
from l4.yolo.readiness import _Calls

from .yolo_review_world import World, make_cfg


def v2(model: str, **extra) -> Profile:
    return Profile(adapter="opencode", model=model, vendor="unknown", options={"cli_major": 2}, **extra)


@pytest.mark.parametrize(
    ("profile", "hidden"),
    [
        (v2("opencode-go/deepseek-v4.1-flash", auth="api_key"), True),
        (v2("opencode/big-pickle"), True),
        (v2("openrouter/openai/gpt-5.4-mini"), False),
        (v2("opencode-go/deepseek-v4.1-flash"), False),
        (
            Profile(adapter="opencode", model="opencode-go/deepseek-v4.1-flash", vendor="deepseek", auth="api_key"),
            False,
        ),
    ],
    ids=["v2-api-key", "v2-free", "v2-openrouter", "v2-stored-login", "v1-api-key"],
)
def test_the_readiness_spec_hides_the_own_homes_only_for_a_profile_without_a_stored_login(tmp_path, profile, hidden):
    world = World(tmp_path)
    world.commit({"README.md": "x\n"})
    selected = Selected("p", profile, impl=object())  # type: ignore[arg-type]
    calls = _Calls(world.app, make_cfg(), world.git, "p1", selected, NoSandbox(allow_none=True))
    assert calls.spec.hide_own_homes is hidden
