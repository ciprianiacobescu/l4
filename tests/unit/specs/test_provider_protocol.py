import dataclasses
from pathlib import Path

import pytest

from l4.specs.base import (
    PROVIDER_MEMBERS,
    Framework,
    ProviderContractError,
    ProviderRegistry,
    SpecProvider,
    Task,
    UnitRef,
    UnknownUnit,
)


class _Complete:
    framework = Framework.KIRO

    def list_units(self):
        return []  # noqa: E704

    def unit_dir(self, unit):
        return Path()  # noqa: E704

    def load(self, unit): ...  # noqa: E704
    def tasks(self, unit):
        return []  # noqa: E704

    def criteria(self, unit):
        return []  # noqa: E704

    def set_marker(self, unit, task_key, marker): ...  # noqa: E704
    def validate(self, unit, strict=True): ...  # noqa: E704
    def done_gate(self, unit): ...  # noqa: E704


class _NoDoneGate(_Complete):
    done_gate = None  # type: ignore[assignment]


def _without(name: str):
    attrs = {k: v for k, v in vars(_Complete).items() if k != name and not k.startswith("__")}
    return type("Incomplete", (), attrs)()


def test_register_rejects_provider_without_done_gate():
    registry = ProviderRegistry()
    with pytest.raises(ProviderContractError, match="done_gate"):
        registry.register(_without("done_gate"))
    assert registry.providers() == []


def test_members_tuple_covers_every_protocol_method():
    methods = {n for n in dir(SpecProvider) if not n.startswith("_")}
    assert methods <= set(PROVIDER_MEMBERS)
    assert "framework" in PROVIDER_MEMBERS


def test_register_get_and_for_unit(tmp_path):
    registry = ProviderRegistry()
    provider = _Complete()
    registry.register(provider)
    assert registry.get(Framework.KIRO) is provider
    assert registry.for_unit(UnitRef(Framework.KIRO, "x", tmp_path)) is provider
    with pytest.raises(UnknownUnit):
        registry.get(Framework.OPENSPEC)


def test_task_new_fields_default_to_neutral():
    task = Task("1", "1", "t", False, " ", 0, 1, 3)
    assert (task.optional, task.wave, task.links) == (False, None, ())
    assert dataclasses.replace(task, wave=2).wave == 2
