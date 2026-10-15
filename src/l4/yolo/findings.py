"""Findings of a readiness review: identifiers, history, resolution lines and rendering (review-resolution design
D1, section 8). Pure functions over ledger events; no git, no network. Contract only: the bodies come in wave 1."""

from collections.abc import Mapping, Sequence
from typing import Any


def finding_id(subject: str, finding: Mapping[str, str]) -> str:
    """`F-` and the first six hex digits of sha256 of `subject NUL criterion NUL severity NUL text`."""
    raise NotImplementedError


def findings_sha(findings: Sequence[Mapping[str, Any]]) -> str:
    """The first 16 hex digits of sha256 of the findings as canonical JSON."""
    raise NotImplementedError
