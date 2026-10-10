"""bootstrap-core 1.4 delta (M1.5 line 3): `memory` is a typed section; an unknown `memory.*` key is a load error."""

import re
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from l4.config import defaults as d
from l4.config.loader import ConfigSchemaError, load_config
from l4.config.schema import OPAQUE_SECTIONS, L4Config, MemoryCfg, SerenaCfg

SPEC = Path(__file__).resolve().parents[3] / "docs" / "SPEC.md"


def reference_config() -> dict:
    text = SPEC.read_text(encoding="utf-8")
    block = re.search(r"```yaml\n(.*?)\n```", text[text.index("### 3.2 Reference configuration") :], re.S)
    assert block, "SPEC 3.2 yaml block not found"
    return yaml.safe_load(block.group(1))


def test_spec_memory_example_loads_and_matches_the_defaults():
    ref = reference_config()["memory"]
    cfg = L4Config.model_validate({"memory": ref}).memory
    assert cfg.model_dump() == ref
    assert L4Config().memory == MemoryCfg()
    assert cfg.lessons_file == d.LESSONS_FILE
    assert (cfg.max_lessons, cfg.max_bytes) == (d.MAX_LESSONS, d.MAX_LESSON_BYTES)
    assert cfg.serena == SerenaCfg(enabled=True, version=d.SERENA_VERSION, context="auto")


def test_memory_is_no_longer_opaque():
    assert OPAQUE_SECTIONS == ("archive",)


@pytest.mark.parametrize(
    "bad",
    [
        {"memory": {"lessons": "x"}},
        {"memory": {"serena": {"vesrion": "1.7.0"}}},
        {"memory": {"max_lessons": 0}},
        {"memory": {"serena": {"context": "vscode"}}},
    ],
)
def test_unknown_memory_keys_and_bad_values_are_rejected(bad):
    with pytest.raises(ValidationError):
        L4Config.model_validate(bad)


def test_the_loader_reports_an_unknown_memory_key_as_a_schema_error(tmp_path):
    (tmp_path / ".l4").mkdir()
    (tmp_path / ".l4" / "config.yaml").write_text(yaml.safe_dump({"version": 1, "memory": {"nope": 1}}))
    with pytest.raises(ConfigSchemaError):
        load_config(tmp_path)
