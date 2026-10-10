import pytest

from l4.versions import parse_version, version_at_least


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("codex-cli 0.160.0", (0, 160, 0)),
        ("2.1.288 (Claude Code)", (2, 1, 288)),
        ("opencode 1.18.34", (1, 18, 34)),
        ("v22.23.0", (22, 23, 0)),
        ("kiro-cli 2.27.1", (2, 27, 1)),
        ("git version 2.34", (2, 34, 0)),
        ("ubuntu22.04 tool 1.2.3", (1, 2, 3)),
        ("１.２.３", None),
        ("garbage", None),
        ("", None),
    ],
)
def test_parse_version_from_cli_output(text, expected):
    assert parse_version(text) == expected


def test_version_at_least_boundaries():
    assert version_at_least("2.34.0", "2.34") is True
    assert version_at_least("2.33.9", "2.34") is False
    assert version_at_least("v22.23.0", "22.23.1") is False
    assert version_at_least("1.0.0", "0.160.0") is True
    assert version_at_least("garbage", "1.0") is None
    assert version_at_least("1.0", "garbage") is None


def test_parse_version_is_bounded_on_long_digit_runs():
    import time

    start = time.monotonic()
    assert parse_version("1" * 20000) is None
    assert time.monotonic() - start < 0.5
