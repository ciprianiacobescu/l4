"""`harness.repository`: where a fetched harness comes from (github-parity L4-GHP-010)."""

import pytest
from pydantic import ValidationError

from l4.config.schema import L4Config

SHA = "0123456789abcdef0123456789abcdef01234567"


def harness(**values) -> L4Config:
    return L4Config.model_validate({"harness": values})


@pytest.mark.parametrize(
    ("given", "kept"),
    [
        ("https://github.com/o/harness.git", "https://github.com/o/harness.git"),
        ("ssh://git@github.com/o/harness.git", "ssh://git@github.com/o/harness.git"),
        ("git@github.com:o/harness.git", "ssh://git@github.com/o/harness.git"),  # scp form, normalised for uv
    ],
)
def test_repository_forms_and_scp_is_normalised(given, kept):
    assert harness(repository=given, commit=SHA).harness.repository == kept


def test_repository_needs_a_commit():
    with pytest.raises(ValidationError, match="harness.commit"):
        harness(repository="https://github.com/o/harness.git")


@pytest.mark.parametrize(
    "bad",
    [
        "http://github.com/o/harness.git",  # plain http: the harness would be fetched unauthenticated and unverified
        "https://user:secret@github.com/o/harness.git",  # a credential in the config
        "file:///tmp/harness",
        "github.com/o/harness",
        "https://github.com/o/harness.git; rm -rf /",
    ],
)
def test_other_urls_are_refused(bad):
    with pytest.raises(ValidationError):
        harness(repository=bad, commit=SHA)


def test_unset_repository_is_the_vendored_default():
    assert L4Config().harness.repository is None
