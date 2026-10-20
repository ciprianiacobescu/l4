#!/usr/bin/env python3
"""Print one version's CHANGELOG section for the GitHub release notes (L4-ACT-006).

    python scripts/dev/release_notes.py --version X.Y.Z [--changelog CHANGELOG.md]

The section is the body under the heading `## X.Y.Z (YYYY-MM-DD)`, up to the next `## ` heading or the end of the
file, without leading or trailing blank lines. It is printed and the exit code is 0. When the file is missing, the
version has no dated heading, or the body is empty, one `error:` line names the cause and the fix on standard error
and the exit code is 1.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


class NotesError(Exception):
    pass


def section(text: str, version: str) -> str:
    """The body of the dated `## version (date)` section of `text`."""
    lines = text.splitlines()
    prefix = f"## {version} ("
    start = next((i for i, line in enumerate(lines) if line.startswith(prefix)), None)
    if start is None:
        raise NotesError(
            f"CHANGELOG.md has no `## {version} (` heading; "
            f"add a `## {version} (YYYY-MM-DD)` section to CHANGELOG.md and tag again"
        )
    heading = lines[start].rstrip()
    if not re.fullmatch(re.escape(prefix) + r"\d{4}-\d{2}-\d{2}\)", heading):
        raise NotesError(
            f"the heading `{heading}` is not dated; date the section: `## {version} (YYYY-MM-DD)` and tag again"
        )
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    body = "\n".join(lines[start + 1 : end]).strip("\n")
    if not body.strip():
        raise NotesError(f"the section `{heading}` is empty; write what changed under it in CHANGELOG.md and tag again")
    return body + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", required=True)
    parser.add_argument("--changelog", default="CHANGELOG.md")
    args = parser.parse_args(argv)
    try:
        path = Path(args.changelog)
        if not path.is_file():
            raise NotesError(
                f"{args.changelog} is missing; add CHANGELOG.md with a `## {args.version} (YYYY-MM-DD)` section"
            )
        sys.stdout.write(section(path.read_text(encoding="utf-8"), args.version))
    except NotesError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
