"""The delegate hint (delegate-answers 26.1; L4-DLG-021; SCN-DLG-71 to 73, SCN-DLG-111)."""

import pytest

from l4.config.schema import DelegateCfg
from l4.delegate.hint import HINT_TEMPLATE, delegate_hint, hint_text
from l4.delegate.scope import PlansView
from l4.delegate.settings import DelegateSettings

from .test_scope import plan_file, state

A = "openspec:a"
OFF = DelegateSettings(DelegateCfg(enabled=False, scope="yolo"))
OFF_ALL = DelegateSettings(DelegateCfg(enabled=False, scope="all"))
ON = DelegateSettings(DelegateCfg(enabled=True, scope="yolo"))


def plan_view(status="waiting"):
    return PlansView((plan_file("p1", [A]),), {"p1": state("p1", status, A)}, "main", ())


def test_the_hint_while_off_in_scope():  # SCN-DLG-71
    hint = delegate_hint(OFF, A, plan_view(), "awaiting_human", ["technical"])
    assert hint == hint_text("main")
    assert hint == (
        "Hint: the delegate can answer these questions in CI: set delegate.enabled: true and roles.delegate in "
        ".l4/config.yaml on main (docs/runbook.md 7.1, the delegate)."
    )
    assert delegate_hint(OFF, A, plan_view("active"), "fixing", ["verdict"]) == hint  # a waiting fix unit too


def test_no_hint_while_on():  # SCN-DLG-72
    assert delegate_hint(ON, A, plan_view(), "awaiting_human", ["technical"]) is None


def test_no_hint_out_of_scope():  # SCN-DLG-73
    assert delegate_hint(OFF, A, PlansView(target="main"), "awaiting_human", ["technical"]) is None  # scope: yolo
    assert delegate_hint(OFF_ALL, A, PlansView(target="main"), "awaiting_human", ["technical"]) == hint_text("main")
    held = PlansView((plan_file("p1", [A]),), {"p1": state("p1", "stopped", A)}, "main", ())
    assert delegate_hint(OFF, A, held, "awaiting_human", ["technical"]) is None


def test_no_hint_for_kinds_it_does_not_answer():
    settings = DelegateSettings(DelegateCfg(enabled=False, kinds=["technical"]))
    assert delegate_hint(settings, A, plan_view(), "awaiting_human", ["product"]) is None
    assert delegate_hint(settings, A, plan_view(), "awaiting_human", []) is None
    assert delegate_hint(OFF, A, plan_view(), "implementing", ["technical"]) is None


def test_scope_is_read_with_enabled_true():
    cfg = OFF.delegate
    assert not cfg.enabled
    delegate_hint(OFF, A, plan_view(), "awaiting_human", ["technical"])
    assert not cfg.enabled  # in_scope ran on a copy


def test_the_hint_is_one_line():
    assert "\n" not in hint_text("main") and HINT_TEMPLATE.startswith("Hint: ")


def test_no_hint_when_the_base_config_cannot_be_read():  # SCN-DLG-111
    assert delegate_hint(None, A, plan_view(), "awaiting_human", ["technical"]) is None


@pytest.mark.parametrize("base", ["main", "release/1"])
def test_the_base_is_named(base):
    assert f"on {base} (" in hint_text(base)
