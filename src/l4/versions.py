"""Version numbers as printed by agent CLIs (`codex-cli 0.160.0`, `2.1.288 (Claude Code)`, `v22.23.0`)."""

import re

_VERSION = re.compile(r"(?:(?<![\w.])|(?<=\bv))([0-9]+)\.([0-9]+)(?:\.([0-9]+))?", re.ASCII)
_MAX_TEXT = 4096  # bounds the regex scan on hostile output


def parse_version(text: str) -> tuple[int, int, int] | None:
    """The first `\\d+\\.\\d+(\\.\\d+)?` in text; a missing patch is 0; None when there is none."""
    match = _VERSION.search(text[:_MAX_TEXT])
    if match is None:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch or 0)


def major_of(text: str) -> int | None:
    """The major of the first version in text (`1.18.34` and `opencode v2.0.32` give 1 and 2); None if none."""
    found = parse_version(text)
    return None if found is None else found[0]


def version_at_least(found: str, minimum: str) -> bool | None:
    """None when either side does not parse: the caller decides what an unknown version means.

    Pre-release suffixes are ignored (`0.160.0-alpha.1` meets `0.160.0`). A caller should treat an unparsable
    `minimum` (a configuration typo such as `"2"`) as an error, not as an unknown `found`."""
    have, need = parse_version(found), parse_version(minimum)
    if have is None or need is None:
        return None
    return have >= need
