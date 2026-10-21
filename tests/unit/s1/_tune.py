"""Load scripts/s1/laya_tune.py and check_vendor.py as modules (they are not part of the l4 package; no torch)."""

import importlib.util
from pathlib import Path
from types import ModuleType

S1 = Path(__file__).resolve().parents[3] / "scripts" / "s1"


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"s1_script_{name}", S1 / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
