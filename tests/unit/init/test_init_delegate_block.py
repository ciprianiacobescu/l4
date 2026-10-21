"""`l4 init` writes the delegate as a commented-out block (delegate-answers 26.2; L4-DLG-022; SCN-DLG-75)."""

import re

import yaml

from l4.config.schema import L4Config
from l4.init.init import loaded_config, render_config


def uncomment(text: str) -> str:
    """The instruction as the file words it, literally: remove the leading "# " of every line that begins with a
    single "#". No line is exempt, so the header and the TODO lines of the file must not begin with a single "#"."""
    out = []
    for line in text.splitlines():
        if re.match(r"# ", line):
            line = line[2:]
        out.append(line)
    return "\n".join(out) + "\n"


class UniqueKeys(yaml.SafeLoader):
    pass


def _construct(loader: UniqueKeys, node: yaml.MappingNode) -> dict:
    seen: set[object] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node)
        assert key not in seen, f"duplicate key {key!r}"
        seen.add(key)
    return loader.construct_mapping(node)


UniqueKeys.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct)


def test_the_config_holds_the_commented_delegate_block():  # SCN-DLG-75
    text = render_config("a" * 40)
    assert loaded_config(text).delegate.enabled is False  # before: loads with the delegate off
    assert "\ndelegate:" not in text and "# delegate:\n#   enabled: true" in text
    assert "#     model: gpt-6.1-sol" in text and "#     model: claude-opus-5-5" in text
    assert "delegate-sonnet: {adapter: claude-code, model: claude-sonnet-5" in text
    assert "#   delegate: [delegate-sonnet]" in text
    assert "scope: yolo" in text


def test_uncommented_as_it_says_it_loads():
    for s1 in ("laya", "jev", "none"):
        text = uncomment(render_config("a" * 40, s1=s1))
        doc = yaml.load(text, Loader=UniqueKeys)  # raises on a second `delegate:`, `profiles:` or `roles:`
        assert doc["delegate"]["enabled"] is True
        assert doc["profiles"]["codex"]["model"] == "gpt-6.1-sol"
        assert doc["profiles"]["claude-code"]["model"] == "claude-opus-5-5"
        assert doc["profiles"]["delegate-sonnet"]["model"] == "claude-sonnet-5"
        assert doc["roles"]["delegate"] == ["delegate-sonnet"]
        assert doc["roles"]["implementer"] == ["codex"] and doc["roles"]["judges"] == ["claude-code"]
        cfg = loaded_config(text)
        assert isinstance(cfg, L4Config) and cfg.delegate.enabled and cfg.roles.delegate == ["delegate-sonnet"]


def test_prose_lines_begin_with_two_hashes():
    lines = render_config("a" * 40).splitlines()
    tail = lines[lines.index("# delegate:") - 5 : lines.index("# delegate:")]
    assert all(line.startswith("##") for line in tail)


def test_the_block_names_the_runbook_and_the_model_rule():
    text = render_config("a" * 40)
    assert "docs/runbook.md 7.1" in text and "independence: model" in text and "free-tier" in text
