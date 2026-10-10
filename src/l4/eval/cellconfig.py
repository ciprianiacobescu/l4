"""The scratch config of one eval cell (L4-EVAL-004): one profile per role and no fallback, so a 429 is an error in the
scorecard and not a silent switch to another model (plan D3).

The values are the ones the 2026-10-06 free run set by hand (docs/live/free/README.md): local forge and CI, System One
off, no fix rounds, no clarifier, and the gates of the base seed project.
"""

import copy
from collections.abc import Mapping
from typing import Any, Literal

from l4.config.schema import TOOL_VENDORS
from l4.exitcodes import ExitCode, L4Exit

Role = Literal["implementer", "judge"]
REFERENCE_PROFILE = "eval-reference"
REFERENCE_VENDOR = "eval-reference"

# the gates of the base seed project: `uv sync --frozen --offline` so a cell never reaches an index (L4-EVAL-018)
SETUP_COMMAND = "uv sync --frozen --offline"
TEST_COMMAND = ".venv/bin/python -m pytest -p no:cacheprovider -o junit_family=xunit1 --junitxml=.l4-out/junit.xml"
# the sections of `--config` a cell keeps besides `profiles`: the sandbox, and the availability ladder (a slow local
# model needs the operator's `probe_timeout`, or every cell of it is `invalid` as unavailable)
KEPT_SECTIONS = ("sandbox", "availability")


def _usage(message: str) -> L4Exit:
    return L4Exit(ExitCode.USAGE_ERROR, message)


def _profile(base_cfg: Mapping[str, Any], name: str) -> dict[str, Any]:
    profiles = base_cfg.get("profiles") or {}
    if name not in profiles:
        raise _usage(f"profile {name!r} is not in --config")
    return copy.deepcopy(dict(profiles[name]))


def _vendor(profile: Mapping[str, Any]) -> str | None:
    declared = profile.get("vendor")
    if isinstance(declared, str) and declared.strip():
        return declared.strip().lower()
    return TOOL_VENDORS.get(str(profile.get("adapter") or ""))


def _cell_profiles(
    base_cfg: Mapping[str, Any], role: Role, profile: str, ref_judge: str | None, ref_impl: Mapping[str, Any] | None
) -> tuple[str, dict[str, Any], str, dict[str, Any]]:
    """(implementer name, its profile, judge name, its profile) of a cell."""
    if role == "implementer":
        if not ref_judge:
            raise _usage("an implementer cell needs a reference judge (--ref-judge)")
        return profile, _profile(base_cfg, profile), ref_judge, _profile(base_cfg, ref_judge)
    if ref_impl is None:
        raise _usage("a judge cell needs the reference implementation profile")
    return REFERENCE_PROFILE, copy.deepcopy(dict(ref_impl)), profile, _profile(base_cfg, profile)


def precheck(
    base_cfg: Mapping[str, Any], role: Role, profile: str, *, ref_judge: str | None = None,
    ref_impl: Mapping[str, Any] | None = None,
) -> str | None:  # fmt: skip
    """None when the cell may start, else the `invalid` reason: `vendor_veto` (the implementer's vendor is the judge's:
    the harness would refuse the verdict) or `vendor_unknown` (a vendor nobody declared). No agent call is made."""
    _, impl, _, judge = _cell_profiles(base_cfg, role, profile, ref_judge, ref_impl)
    impl_vendor, judge_vendor = _vendor(impl), _vendor(judge)
    if impl_vendor is None or judge_vendor is None:
        return "vendor_unknown"
    if impl_vendor == judge_vendor:
        return "vendor_veto"
    return None


def render_config(
    base_cfg: Mapping[str, Any], role: Role, profile: str, *, ref_judge: str | None = None,
    ref_impl: Mapping[str, Any] | None = None, uv_cache: str | None = None,
) -> dict[str, Any]:  # fmt: skip
    """The cell's `.l4/config.yaml` as a mapping. `base_cfg` is the operator's `--config` (profiles, and the sandbox
    and availability sections when it has them); nothing else of it enters the cell. `uv_cache` is the cell's uv
    cache path: the private copy of the warmed cache inside the cell's own `L4_CACHE` (`$L4_CACHE/eval-uv`,
    `cellrun.seed_uv_cache`), because `l4 run`'s preflight refuses a cache path outside that root."""
    impl_name, impl, judge_name, judge = _cell_profiles(base_cfg, role, profile, ref_judge, ref_impl)
    cfg: dict[str, Any] = {
        "version": 1,
        "spec": {"frameworks": "auto"},
        "gates": {
            "setup": [SETUP_COMMAND],
            "test": {"command": TEST_COMMAND},
            "network": "allow",
        },
        "profiles": {impl_name: impl, judge_name: judge},
        "roles": {
            "implementer": [impl_name], "judges": [judge_name], "clarifier": [], "s1_judge": [], "verifier_agent": [],
        },
        "clarifier": {"enabled": False, "s1_standin": "none"},
        "sdd": {"scope_check": "warn"},
        "forge": {"type": "local"},
        "ci": {"platform": "local"},
        "verifier": {
            "fix_minor_findings": False, "max_fix_rounds": 0, "audit_sample_ratio": 0, "generate_missing_tests": False,
            "playwright": {"enabled": False},
            "s1": {"enabled": False, "shadow": []},
        },
        "memory": {"enabled": False, "serena": {"enabled": False}},
    }  # fmt: skip
    for section in KEPT_SECTIONS:  # how profiles are probed and confined: the operator's, not the model's
        if isinstance(base_cfg.get(section), Mapping):
            cfg[section] = copy.deepcopy(dict(base_cfg[section]))
    if uv_cache is not None:
        cfg.setdefault("sandbox", {}).setdefault("caches", {})["uv"] = {"path": uv_cache, "env": "UV_CACHE_DIR"}
    return cfg
