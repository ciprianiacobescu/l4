import json
import sys
import types
from importlib.metadata import PackageNotFoundError

import pytest

from l4.buildinfo import harness_commit


def test_a_checkout_has_no_commit_file_so_the_commit_is_unknown(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("L4_HARNESS_COMMIT", raising=False)
    monkeypatch.setitem(sys.modules, "l4._commit", None)  # an import of None raises ImportError
    assert harness_commit() is None


def test_the_vendored_commit_file_names_the_running_commit(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(sys.modules, "l4._commit", types.SimpleNamespace(COMMIT="3b9a802" + "0" * 33))
    assert harness_commit() == "3b9a802" + "0" * 33


COMMIT = "c0ffee0123456789c0ffee0123456789c0ffee01"


class FakeDistribution:
    def __init__(self, direct_url: str | None):
        self._direct_url = direct_url

    def read_text(self, filename: str) -> str | None:
        assert filename == "direct_url.json"
        return self._direct_url


def installed(monkeypatch: pytest.MonkeyPatch, direct_url: str | None):
    """No vendored commit file, the harness installed as `direct_url` says (an editable-less `uvx --from git+...`)."""
    monkeypatch.setitem(sys.modules, "l4._commit", None)
    monkeypatch.delenv("L4_HARNESS_COMMIT", raising=False)

    def distribution(name: str):
        assert name == "l4harness"
        return FakeDistribution(direct_url)

    monkeypatch.setattr("l4.buildinfo.distribution", distribution)


def test_commit_from_direct_url(monkeypatch: pytest.MonkeyPatch):
    """SCN-GHP-16: a harness fetched by uvx names its commit through the installed distribution."""
    url = {"url": "https://github.com/o/harness.git", "vcs_info": {"vcs": "git", "commit_id": COMMIT}}
    installed(monkeypatch, json.dumps(url))
    assert harness_commit() == COMMIT


@pytest.mark.parametrize(
    "direct_url",
    [
        None,
        "not json",
        "[]",
        json.dumps({"url": "file:///x", "dir_info": {"editable": True}}),
        json.dumps({"vcs_info": {"commit_id": "main"}}),
        json.dumps({"vcs_info": {"commit_id": COMMIT.upper()}}),
        json.dumps({"vcs_info": {"commit_id": COMMIT[:12]}}),
        json.dumps({"vcs_info": ["x"]}),
    ],
    ids=["absent", "garbage", "list", "dir_info", "not-hex", "upper", "short", "vcs_info-list"],
)
def test_direct_url_without_a_full_commit_is_unknown(monkeypatch: pytest.MonkeyPatch, direct_url):
    installed(monkeypatch, direct_url)
    assert harness_commit() is None


def test_a_missing_distribution_is_unknown(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(sys.modules, "l4._commit", None)
    monkeypatch.delenv("L4_HARNESS_COMMIT", raising=False)

    def distribution(name: str):
        raise PackageNotFoundError(name)

    monkeypatch.setattr("l4.buildinfo.distribution", distribution)
    assert harness_commit() is None


def test_the_vendored_commit_wins_over_direct_url(monkeypatch: pytest.MonkeyPatch):
    installed(monkeypatch, json.dumps({"vcs_info": {"commit_id": COMMIT}}))
    monkeypatch.setitem(sys.modules, "l4._commit", types.SimpleNamespace(COMMIT="1" * 40))
    assert harness_commit() == "1" * 40


def test_the_action_exports_the_commit_when_direct_url_has_none(monkeypatch: pytest.MonkeyPatch):
    """A harness installed from a local copy (the setup action) has no commit in direct_url.json."""
    installed(monkeypatch, json.dumps({"url": "file:///x", "dir_info": {}}))
    monkeypatch.setenv("L4_HARNESS_COMMIT", COMMIT)
    assert harness_commit() == COMMIT


@pytest.mark.parametrize("value", ["", "main", COMMIT.upper(), COMMIT[:12]], ids=["empty", "ref", "upper", "short"])
def test_a_malformed_exported_commit_is_ignored(monkeypatch: pytest.MonkeyPatch, value):
    installed(monkeypatch, None)
    monkeypatch.setenv("L4_HARNESS_COMMIT", value)
    assert harness_commit() is None


def test_direct_url_wins_over_the_exported_commit(monkeypatch: pytest.MonkeyPatch):
    installed(monkeypatch, json.dumps({"vcs_info": {"commit_id": COMMIT}}))
    monkeypatch.setenv("L4_HARNESS_COMMIT", "1" * 40)
    assert harness_commit() == COMMIT
