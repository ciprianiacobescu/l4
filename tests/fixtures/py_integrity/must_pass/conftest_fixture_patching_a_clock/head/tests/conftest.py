import time

import pytest


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1_700_000_000.0)
