"""`.github/dependabot.yml` for `l4 init --dependabot` (adoption-kit L4-ACT-004, D4): the `github-actions` ecosystem,
weekly, so that Dependabot proposes the moves of the pinned `uses:` lines. An existing file is merged into, never
replaced: the entry is appended to the `updates` list as text, so every other byte stays; a form that cannot be edited
that way is refused with the snippet (the same stance as `.gitlab-ci.yml` in `l4.init.ciedit`)."""

import re
from dataclasses import dataclass
from typing import Any, Literal

import yaml

DEPENDABOT_RELPATH = ".github/dependabot.yml"
ECOSYSTEM = "github-actions"
_UPDATES = re.compile(r"^updates:[ \t]*(#.*)?$")
_ITEM = re.compile(r"^([ \t]*)- ")
_TOP_LEVEL = re.compile(r"^[^\s#-]")  # a key at column 0; a list item at column 0 belongs to `updates`


@dataclass(frozen=True)
class DependabotEdit:
    action: Literal["create", "merge", "noop", "refuse"]
    text: str = ""
    reason: str = ""
    snippet: str = ""


def _entry(indent: str, eol: str) -> str:
    lines = [
        f'{indent}- package-ecosystem: "{ECOSYSTEM}"',
        f'{indent}  directory: "/"',
        f"{indent}  schedule:",
        f'{indent}    interval: "weekly"',
    ]
    return eol.join(lines) + eol


SNIPPET = _entry("  ", "\n")


def _refuse(reason: str) -> DependabotEdit:
    return DependabotEdit("refuse", reason=reason, snippet=SNIPPET)


def merge_dependabot(existing: str | None) -> DependabotEdit:
    if existing is None:
        return DependabotEdit("create", f"version: 2\nupdates:\n{SNIPPET}")
    try:
        document: Any = yaml.safe_load(existing)
    except yaml.YAMLError:
        return _refuse("it is not valid YAML")
    if not isinstance(document, dict):
        return _refuse("it is not a mapping")
    updates = document.get("updates")
    if updates is not None and not isinstance(updates, list):
        return _refuse("`updates` is not a list")
    if any(isinstance(u, dict) and u.get("package-ecosystem") == ECOSYSTEM for u in updates or []):
        return DependabotEdit("noop")
    eol = "\r\n" if "\r\n" in existing else "\n"
    lines = existing.splitlines(keepends=True)
    key = next((i for i, ln in enumerate(lines) if _UPDATES.match(ln.rstrip("\r\n"))), None)
    if key is None:
        if updates is not None:
            return _refuse("`updates` is not a plain `updates:` line")
        lead = "" if existing.endswith("\n") or not existing else eol
        return _checked(existing, existing + lead + f"updates:{eol}" + _entry("  ", eol), updates)
    if not updates:
        return _refuse("`updates` is empty or written inline")
    end = len(lines)
    for i in range(key + 1, len(lines)):
        if _TOP_LEVEL.match(lines[i]):
            end = i
            break
    last = max(i for i in range(key + 1, end) if lines[i].strip() and not lines[i].lstrip().startswith("#"))
    first_item = next((m for ln in lines[key + 1 : end] if (m := _ITEM.match(ln))), None)
    indent = first_item.group(1) if first_item else "  "
    entry = _entry(indent, eol)
    block = lines[last] if lines[last].endswith(("\n", "\r")) else lines[last] + eol
    merged = "".join(lines[:last]) + block + entry + "".join(lines[last + 1 :])
    return _checked(existing, merged, updates)


def _checked(old: str, new: str, updates: list[Any] | None) -> DependabotEdit:
    """The merged text must read back as the old document plus one entry, or it is not written."""
    try:
        document = yaml.safe_load(new)
    except yaml.YAMLError:
        return _refuse("the entry could not be added without breaking it")
    merged = document.get("updates") if isinstance(document, dict) else None
    if (
        not isinstance(merged, list)
        or merged[:-1] != (updates or [])
        or merged[-1].get("package-ecosystem") != ECOSYSTEM
    ):
        return _refuse("the entry could not be added without changing the other entries")
    return DependabotEdit("merge", new)
