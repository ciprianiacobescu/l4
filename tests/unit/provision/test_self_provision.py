import logging

import pytest

from l4.config.schema import L4Config
from l4.provision.runner import resolve_self_provision


def cfg(value: bool | str) -> L4Config:
    return L4Config.model_validate({"ci": {"self_provision": value}})


def test_unknown_override_value_warns_and_config_applies(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.WARNING, logger="l4.provision"):
        assert resolve_self_provision(cfg(False), {"L4_SELF_PROVISION": "yes"}) is False
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and r.name == "l4.provision"]
    assert len(warnings) == 1
    assert "L4_SELF_PROVISION" in warnings[0].getMessage() and "yes" in warnings[0].getMessage()


def test_known_empty_and_unset_values_do_not_warn(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.WARNING, logger="l4.provision"):
        for value in ("true", " FALSE ", "Auto", ""):
            resolve_self_provision(cfg(True), {"L4_SELF_PROVISION": value})
        resolve_self_provision(cfg(True), {})
    assert caplog.records == []
