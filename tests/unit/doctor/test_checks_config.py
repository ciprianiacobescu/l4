"""CFG-005 (M1.8, A6): an explicitly set list that drops a default says which, and points to the `extra_` key."""

from l4.config import defaults as d
from l4.config.schema import L4Config
from l4.doctor import checks_config as cc


def config(**sections) -> L4Config:
    return L4Config.model_validate(sections)


def test_cfg005_names_dropped_defaults(make_ctx):
    ctx, _ = make_ctx(cfg=config(tdd={"test_support_globs": ["**/conftest.py"]}, odd={"forbidden_paths": ["infra/**"]}))
    result = cc._cfg_005(ctx)
    assert result.status == "fail"
    assert "tdd.test_support_globs" in result.message and "**/fixtures/**" in result.message
    assert "odd.forbidden_paths" in result.message and ".github/workflows/**" in result.message
    assert "tdd.extra_test_support_globs" in (result.fix_hint or "")
    assert "odd.extra_forbidden_paths" in (result.fix_hint or "")
    assert "**/conftest.py" not in result.message  # what was kept is not listed as dropped


def test_cfg005_passes_with_extra_keys(make_ctx):
    ctx, _ = make_ctx(cfg=config(tdd={"extra_test_support_globs": ["x/**"]}, odd={"extra_forbidden_paths": ["y/**"]}))
    assert cc._cfg_005(ctx).status == "pass"


def test_cfg005_passes_when_the_explicit_list_keeps_every_default(make_ctx):
    ctx, _ = make_ctx(cfg=config(tdd={"test_support_globs": [*d.TEST_SUPPORT_GLOBS, "x/**"]}))
    assert cc._cfg_005(ctx).status == "pass"


def test_cfg005_passes_on_a_default_config(make_ctx):
    ctx, _ = make_ctx()
    assert cc._cfg_005(ctx).status == "pass"


def test_cfg005_is_a_warning_in_the_config_scope():
    from l4.doctor.registry import REGISTRY

    check = next(c for c in REGISTRY.checks() if c.id == "CFG-005")
    assert check.severity == "warn" and {"ci", "local", "config"} <= check.scopes
