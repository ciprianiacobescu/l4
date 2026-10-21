from pathlib import Path

import pytest

from l4.config.loader import ConfigSchemaError, load_config
from l4.config.schema import L4Config

EXAMPLE = """\
version: 1
sdd:
  scope_check: fail
verifier:
  evidence:
    module_roots: [src, services]
    scope_exempt: ["docs/**"]
    diff_coverage: {mode: fail, min_percent: 90, languages: [python]}
  s1:
    shadow: [jev]
    max_items: 20
profiles:
  jev: {backend: system-one, engine: jev}
"""


def write(repo: Path, text: str) -> None:
    (repo / ".l4").mkdir()
    (repo / ".l4" / "config.yaml").write_text(text, encoding="utf-8")


def test_m16_example_loads_and_unknown_evidence_key_exits_2(tmp_path: Path):
    write(tmp_path, EXAMPLE)
    cfg = load_config(tmp_path)
    ev = cfg.verifier.evidence
    assert cfg.sdd.scope_check == "fail"
    assert ev.module_roots == ["src", "services"] and ev.scope_exempt == ["docs/**"]
    assert (ev.diff_coverage.mode, ev.diff_coverage.min_percent) == ("fail", 90)
    assert cfg.verifier.s1.shadow == ["jev"] and cfg.verifier.s1.max_items == 20

    (tmp_path / ".l4" / "config.yaml").write_text("verifier:\n  evidence:\n    scope_chek: warn\n", encoding="utf-8")
    with pytest.raises(ConfigSchemaError) as err:
        load_config(tmp_path)
    assert int(err.value.code) == 2


def test_defaults_are_the_plan_values():
    cfg = L4Config()
    ev = cfg.verifier.evidence
    assert ev.module_roots == ["src", "lib", "packages", "apps"]
    assert ev.scope_exempt == ["docs/**", "**/*.md", "CHANGELOG*"]
    assert (ev.diff_coverage.mode, ev.diff_coverage.min_percent, ev.diff_coverage.languages) == ("warn", 80, ["python"])
    assert cfg.verifier.s1.shadow == [] and cfg.verifier.s1.max_items == 60


@pytest.mark.parametrize("percent", [-1, 101])
def test_min_percent_is_a_percentage(percent: int):
    with pytest.raises(ValueError):
        L4Config.model_validate({"verifier": {"evidence": {"diff_coverage": {"min_percent": percent}}}})
