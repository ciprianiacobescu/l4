"""`harness.delivery: vendored | fetched | action` (adoption-kit L4-ACT-004, task 2.1)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from l4.config.schema import L4Config, effective_delivery

SHA = "0123456789abcdef0123456789abcdef01234567"
URL = "https://github.com/o/harness.git"


def harness(**values) -> L4Config:
    return L4Config.model_validate({"harness": values})


def test_unset_delivery_is_none_in_the_model():
    assert L4Config().harness.delivery is None


def test_action_needs_no_commit_and_no_repository():
    assert harness(delivery="action").harness.commit is None


def test_fetched_still_needs_its_commit_when_a_repository_is_set():
    with pytest.raises(ValidationError, match="harness.commit"):
        harness(delivery="fetched", repository=URL)


def test_an_explicit_fetched_needs_a_repository():
    with pytest.raises(ValidationError, match="harness.repository"):
        harness(delivery="fetched", commit=SHA)


def test_an_unknown_delivery_is_refused():
    with pytest.raises(ValidationError):
        harness(delivery="docker")


def test_vendored_with_a_repository_contradicts_itself():
    with pytest.raises(ValidationError, match="vendored"):
        harness(delivery="vendored", repository=URL, commit=SHA)


def test_old_config_with_a_repository_is_fetched():
    assert effective_delivery(harness(repository=URL, commit=SHA)) == "fetched"


def test_old_config_with_a_vendor_directory_is_vendored(tmp_path: Path):
    (tmp_path / ".l4" / "vendor").mkdir(parents=True)
    assert effective_delivery(harness(commit=SHA)) == "vendored"


def test_old_config_with_neither_is_vendored():
    assert effective_delivery(L4Config()) == "vendored"


def test_a_repository_wins_over_a_vendor_directory_left_behind(tmp_path: Path):
    (tmp_path / ".l4" / "vendor").mkdir(parents=True)
    assert effective_delivery(harness(repository=URL, commit=SHA)) == "fetched"


def test_an_explicit_value_wins_over_the_derivation(tmp_path: Path):
    (tmp_path / ".l4" / "vendor").mkdir(parents=True)
    assert effective_delivery(harness(delivery="action")) == "action"
