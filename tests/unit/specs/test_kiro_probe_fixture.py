from pathlib import Path

from l4.specs.base import Framework, UnitRef
from l4.specs.kiro import KiroProvider

from .._kiro_probe import LONG_DESIGN_CHARS, PROBE, PROBE_IDS, UNIT_REL, long_design, probe_tree


def _provider(root: Path) -> tuple[KiroProvider, UnitRef]:
    provider = KiroProvider(root)
    (unit,) = provider.list_units()
    return provider, unit


def test_the_fixture_gives_the_probe_ids_and_the_leaf_links(tmp_path):
    provider, unit = _provider(probe_tree(tmp_path))
    assert {c.alias.removeprefix("Req "): c.id for c in provider.criteria(unit)} == PROBE_IDS
    (leaf,) = provider.tasks(unit)
    assert leaf.links == ("1.1", "1.2")
    assert unit.framework is Framework.KIRO


def test_the_long_design_is_the_probe_size_and_keeps_the_preamble(tmp_path):
    root = probe_tree(tmp_path, long=True)
    text = (root / UNIT_REL / "design.md").read_text(encoding="utf-8")
    assert len(text) == LONG_DESIGN_CHARS == len(long_design()) == 125_492
    assert text.startswith("# Design\nDESIGN-MARKER")
    assert text.endswith("error handling. ")
    assert text.count("\n## Component ") == 1100


def test_the_fixture_files_have_the_probe_sizes():
    sizes = {p.name: p.stat().st_size for p in (PROBE / ".kiro").rglob("*.md")}
    assert sizes == {"requirements.md": 409, "tasks.md": 190, "design.md": 112, "tech.md": 103}
