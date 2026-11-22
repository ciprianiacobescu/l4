"""L4-YOLO-101: the `plan entry` block of the readiness material shows every object with `id`, then `depends_on`, then
the other keys in sorted order, so a judge reads a unit's prerequisites under its own id. The readiness prompt version
is 5."""

import json
import re

import pytest

from l4.agents.fake import FakeAdapter, Step
from l4.yolo.model import UnitInfo, load_plan
from l4.yolo.readiness import PROMPT_VERSION, _entry, _ordered, review_plan_costed

from .yolo_review_world import SPEC_A, SPEC_B, World, make_cfg

A, B, C = "openspec:a", "openspec:b", "openspec:c"
ROOT = "openspec/changes"


def ok():
    return Step(structured={"verdict": "READY", "findings": [], "assumptions": [], "missing": []})


def entry_blocks(prompt: str) -> list[str]:
    """The text of every `plan entry` data block of a prompt."""
    return re.findall(r'<l4:data source="plan entry">\n(.*?)\n</l4:data>', prompt, flags=re.S)


PLAN = load_plan(
    json.dumps(
        {
            "schema": "l4/delivery-plan@1",
            "plan_id": "p1",
            "target": "main",
            "merge": "human",
            "batches": [
                {
                    "id": "b1",
                    "units": [
                        {"id": A, "depends_on": []},
                        {"id": B, "depends_on": [A]},
                        {"id": C, "depends_on": [B], "acceptance_profile": "none"},
                    ],
                }
            ],
        }
    )
)

BATCH_ENTRY = """{
  "id": "b1",
  "depends_on": [],
  "acceptance_profile": "none",
  "units": [
    {
      "id": "openspec:a",
      "depends_on": [],
      "acceptance_profile": "all"
    },
    {
      "id": "openspec:b",
      "depends_on": [
        "openspec:a"
      ],
      "acceptance_profile": "all"
    },
    {
      "id": "openspec:c",
      "depends_on": [
        "openspec:b"
      ],
      "acceptance_profile": "none"
    }
  ]
}"""

UNIT_B_ENTRY = """{
  "id": "openspec:b",
  "depends_on": [
    "openspec:a"
  ],
  "acceptance_profile": "all"
}"""


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    files = {}
    for name, spec in (("a", SPEC_A), ("b", SPEC_B), ("c", SPEC_B)):
        files[f"{ROOT}/{name}/proposal.md"] = f"Why: {name.upper()}-PROPOSAL.\n"
        files[f"{ROOT}/{name}/specs/x/spec.md"] = spec
        files[f"{ROOT}/{name}/design.md"] = f"{name.upper()}-DESIGN\n" + "x" * 3000 + "\n"
    w.rev = w.commit(files)
    w.units = {u: UnitInfo(u, f"{ROOT}/{u.split(':')[1]}") for u in (A, B, C)}
    return w


def run(world, answers, bound=None):
    review = {} if bound is None else {"max_batch_chars": bound}
    cfg = make_cfg(yolo={"review": review})
    fake = FakeAdapter([ok() for _ in range(answers)])
    result, _ = review_plan_costed(
        world.app, cfg, PLAN, world.units, git=world.git, rev=world.rev, adapters={"fake": fake}
    )
    return fake, result


def test_scn_yolo_283_a_batch_entry_shows_each_units_id_before_its_list(world):
    fake, _ = run(world, 4)
    prompts = [r.prompt for r in fake.requests]
    unit_b = next(p for p in prompts if "subject" in p and entry_blocks(p) == [UNIT_B_ENTRY])
    assert entry_blocks(unit_b) == [UNIT_B_ENTRY]
    batch = prompts[-1]
    assert entry_blocks(batch) == [BATCH_ENTRY]
    text = entry_blocks(batch)[0]
    assert text.index('"id": "openspec:b"') < text.index('"openspec:a"\n') < text.index('"id": "openspec:c"')
    assert PROMPT_VERSION == 5


def test_scn_yolo_283_the_review_records_prompt_version_5(world):
    _, result = run(world, 4)
    assert PROMPT_VERSION == 5
    assert result.units[A].material and result.batches["b1"].material


def test_scn_yolo_283_every_part_of_a_batch_shows_the_same_order(world):
    fake, _ = run(world, 7, bound=1000)
    parts = [r.prompt for r in fake.requests if "read in part" in r.prompt]
    assert len(parts) == 4
    for prompt in parts:
        blocks = entry_blocks(prompt)
        assert blocks, prompt
        assert all(b.startswith('{\n  "id": "b1",\n  "depends_on": [],') for b in blocks)
        assert '"id": "openspec:a",\n      "depends_on": [],' in blocks[0]


def test_the_entry_is_the_ordered_model_dump():
    assert _entry(PLAN.units()[1]) == UNIT_B_ENTRY
    assert _entry(PLAN.batches[0]) == BATCH_ENTRY


def test_ordered_puts_id_then_depends_on_then_the_rest_sorted():
    value = {
        "zeta": 1,
        "alpha": {"depends_on": [1], "b": 2, "a": 3},
        "depends_on": ["x"],
        "id": "i",
        "items": [{"z": 1, "id": 2}],
    }
    ordered = _ordered(value)
    assert list(ordered) == ["id", "depends_on", "alpha", "items", "zeta"]
    assert list(ordered["alpha"]) == ["depends_on", "a", "b"]  # no id: depends_on first
    assert list(ordered["items"][0]) == ["id", "z"]
    assert _ordered([3, 1, 2]) == [3, 1, 2]  # a list keeps its order
    assert _ordered("text") == "text"
