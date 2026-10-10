import sys
import types

import pytest

from l4.buildinfo import harness_commit


def test_a_checkout_has_no_commit_file_so_the_commit_is_unknown(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(sys.modules, "l4._commit", None)  # an import of None raises ImportError
    assert harness_commit() is None


def test_the_vendored_commit_file_names_the_running_commit(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(sys.modules, "l4._commit", types.SimpleNamespace(COMMIT="3b9a802" + "0" * 33))
    assert harness_commit() == "3b9a802" + "0" * 33
