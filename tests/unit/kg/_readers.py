"""Helpers for the tests of `kg.report`, `kg.why` and `kg.propose`: the fixture repository to the index and back.

`index(kg_repo)` runs the real `collect` and `extract` over the fixture, with a read-only recording `Git`, and returns
the pieces the three readers take (nodes, edges, the skips and the base). Nothing is mocked below the readers.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path

from l4.kg.extract import Extracted, extract
from l4.kg.sources import Collected, collect
from l4.redact import Redactor


@dataclass
class Index:
    collected: Collected
    extracted: Extracted

    @property
    def nodes(self):
        return self.extracted.nodes

    @property
    def edges(self):
        return self.extracted.edges

    def context(self) -> dict:
        """The keywords `report.render` takes besides the nodes and the edges."""
        return {
            "base_ref": self.collected.base_ref,
            "base_sha": self.collected.base_sha,
            "base_date": self.collected.base_date,
            "skipped": self.extracted.skipped,
            "warnings": self.extracted.warnings,
        }


def index(kg_repo, redactor: Redactor | None = None) -> Index:
    found = collect(kg_repo.recording_git(), kg_repo.cfg)
    return Index(found, extract(found, redactor or Redactor({}), git=kg_repo.recording_git()))


def section(text: str, title: str) -> str:
    """The lines of one `## <title>` section of a report, without the heading, up to the next heading."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("## " + title))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return "\n".join(lines[start + 1 : end]).strip("\n")


_ID_LIKE = (
    re.compile(r"\b[rFLCQ]-[0-9A-Za-z-]+"),  # run, finding, lesson, criterion, question ids
    re.compile(r"@\d+"),
    re.compile(r"round-\d+"),
    re.compile(r"\b[0-9a-f]{7,}\b"),  # a commit
    re.compile(r"\d{4}-\d{2}-\d{2}(?:T[0-9:.]+(?:Z|[+-]\d{2}:\d{2})?)?"),  # a date or a time stamp
    re.compile(r"\bSCN-KG-\d+|\bL4-KG-\d+"),
)


def digit_lines_without_n(text: str) -> list[str]:
    """The lines with a digit outside an id, a commit or a date that do not name their `n = ` (SCN-KG-18)."""
    bad = []
    for line in text.splitlines():
        bare = line
        for pattern in _ID_LIKE:
            bare = pattern.sub("", bare)
        if re.search(r"\d", bare) and "n = " not in line:
            bad.append(line)
    return bad


def assert_snapshot(path: Path, text: str) -> None:
    """`text` equals the file. With `L4_UPDATE_SNAPSHOTS=1` the file is written first (review the diff, then commit)."""
    if os.environ.get("L4_UPDATE_SNAPSHOTS"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert text == path.read_text(encoding="utf-8")
