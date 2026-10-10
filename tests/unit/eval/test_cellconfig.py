import pytest
import yaml

from l4.config.schema import L4Config
from l4.eval.cellconfig import REFERENCE_PROFILE, precheck, render_config
from l4.exitcodes import ExitCode, L4Exit

BASE = {
    "profiles": {
        "p-free": {"adapter": "opencode", "model": "opencode/big-pickle", "vendor": "undisclosed-big-pickle"},
        "p-other": {"adapter": "opencode", "model": "opencode/mimo", "vendor": "xiaomi"},
        "claude-code": {"adapter": "claude-code", "vendor": "anthropic", "auth": "subscription"},
        "codex": {"adapter": "codex", "auth": "subscription"},
        "p-novendor": {"adapter": "opencode", "model": "opencode/x"},
        "fallback": {"adapter": "opencode", "model": "opencode/y", "vendor": "zzz"},
    },
    "roles": {"implementer": ["p-free", "fallback"], "judges": ["claude-code", "fallback"], "clarifier": ["codex"]},
}
REF_IMPL = {"adapter": "command", "vendor": "eval-reference", "options": {"argv": ["python3", "{prompt_file}"]}}


def test_an_implementer_cell_has_exactly_one_implementer_and_the_reference_judge() -> None:
    cfg = render_config(BASE, "implementer", "p-free", ref_judge="claude-code")
    assert cfg["roles"]["implementer"] == ["p-free"]
    assert cfg["roles"]["judges"] == ["claude-code"]
    assert cfg["roles"]["clarifier"] == [] and cfg["roles"]["s1_judge"] == [] and cfg["roles"]["verifier_agent"] == []
    L4Config.model_validate(cfg)


def test_a_judge_cell_has_exactly_one_judge_and_the_replay_implementer() -> None:
    cfg = render_config(BASE, "judge", "claude-code", ref_impl=REF_IMPL)
    assert cfg["roles"]["judges"] == ["claude-code"]
    assert cfg["roles"]["implementer"] == [REFERENCE_PROFILE]
    assert cfg["profiles"][REFERENCE_PROFILE]["vendor"] == "eval-reference"
    L4Config.model_validate(cfg)


def test_the_scratch_values_of_the_free_run() -> None:
    cfg = render_config(BASE, "implementer", "p-free", ref_judge="claude-code")
    assert cfg["forge"]["type"] == "local" and cfg["ci"]["platform"] == "local"
    assert cfg["verifier"]["s1"]["enabled"] is False
    assert cfg["verifier"]["max_fix_rounds"] == 0
    assert cfg["clarifier"]["s1_standin"] == "none"
    assert cfg["gates"]["setup"] == ["uv sync --frozen --offline"]
    assert "pytest" in cfg["gates"]["test"]["command"]


def test_no_fallback_profile_reaches_the_cell() -> None:
    for cfg in (
        render_config(BASE, "implementer", "p-free", ref_judge="claude-code"),
        render_config(BASE, "judge", "claude-code", ref_impl=REF_IMPL),
    ):
        assert "fallback" not in cfg["profiles"]
        assert len(cfg["profiles"]) == 2  # only the two profiles of the cell are carried
        assert all(len(cfg["roles"][r]) <= 1 for r in cfg["roles"])


def test_the_rendered_config_does_not_alter_the_input() -> None:
    before = yaml.safe_dump(BASE)
    render_config(BASE, "implementer", "p-free", ref_judge="claude-code")
    assert yaml.safe_dump(BASE) == before


def test_a_missing_profile_is_a_usage_error_naming_it() -> None:
    with pytest.raises(L4Exit, match="ghost") as info:
        render_config(BASE, "implementer", "ghost", ref_judge="claude-code")
    assert info.value.code == ExitCode.USAGE_ERROR
    with pytest.raises(L4Exit, match="nobody"):
        render_config(BASE, "implementer", "p-free", ref_judge="nobody")
    with pytest.raises(L4Exit, match="ghost"):
        render_config(BASE, "judge", "ghost", ref_impl=REF_IMPL)


def test_a_judge_cell_needs_the_replay_profile_and_an_implementer_cell_a_judge() -> None:
    with pytest.raises(L4Exit):
        render_config(BASE, "judge", "claude-code")
    with pytest.raises(L4Exit):
        render_config(BASE, "implementer", "p-free")


# --- line 6: the pre-check
def test_the_same_vendor_is_vetoed_before_anything_starts() -> None:
    assert precheck(BASE, "implementer", "p-free", ref_judge="p-free") == "vendor_veto"
    assert precheck(BASE, "implementer", "claude-code", ref_judge="claude-code") == "vendor_veto"


def test_a_different_vendor_passes() -> None:
    assert precheck(BASE, "implementer", "p-free", ref_judge="claude-code") is None
    assert precheck(BASE, "implementer", "codex", ref_judge="claude-code") is None  # the tool says openai


def test_an_undeclared_vendor_is_unknown() -> None:
    assert precheck(BASE, "implementer", "p-novendor", ref_judge="claude-code") == "vendor_unknown"
    assert precheck(BASE, "implementer", "p-free", ref_judge="p-novendor") == "vendor_unknown"
    assert precheck(BASE, "judge", "p-novendor", ref_impl=REF_IMPL) == "vendor_unknown"


def test_the_reference_profile_never_vetoes_a_judge() -> None:
    for name in ("p-free", "claude-code", "p-other"):
        assert precheck(BASE, "judge", name, ref_impl=REF_IMPL) is None
    assert REF_IMPL["vendor"] == "eval-reference"
    assert precheck(BASE, "judge", "p-free", ref_impl={**REF_IMPL, "vendor": "undisclosed-big-pickle"}) == "vendor_veto"


def test_the_shared_uv_cache_is_an_absolute_sandbox_cache() -> None:
    cfg = render_config(BASE, "implementer", "p-free", ref_judge="claude-code", uv_cache="/var/cache/l4/eval/uv")
    assert cfg["sandbox"]["caches"]["uv"] == {"path": "/var/cache/l4/eval/uv", "env": "UV_CACHE_DIR"}
    L4Config.model_validate(cfg)
    assert "sandbox" not in render_config(BASE, "implementer", "p-free", ref_judge="claude-code")


def test_the_availability_section_of_the_config_is_kept() -> None:
    """A slow local model needs the operator's `availability.probe_timeout` (magnitude-qwen's hello took 75 s, over the
    60 s default): without it every cell of that profile would be `invalid` as unavailable, a measurement of the
    probe and not of the model. Only `availability` and `sandbox` of `--config` reach the cell."""
    base = {**BASE, "availability": {"probe_timeout": "150s"}, "forge": {"type": "gitlab"}}
    base["ci"] = {"platform": "gitlab"}
    cfg = render_config(base, "implementer", "p-free", ref_judge="claude-code")
    assert cfg["availability"] == {"probe_timeout": "150s"}
    assert cfg["forge"] == {"type": "local"} and cfg["ci"] == {"platform": "local"}
    assert L4Config.model_validate(cfg).availability.probe_timeout == "150s"
    base["availability"]["probe_timeout"] = "1s"
    assert cfg["availability"] == {"probe_timeout": "150s"}  # a copy, not the operator's mapping
    assert "availability" not in render_config(BASE, "implementer", "p-free", ref_judge="claude-code")
