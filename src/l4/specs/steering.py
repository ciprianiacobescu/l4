"""Kiro steering and an OpenSpec unit's project context, as data for the implementer's prompt (L4-KSP-010, L4-KSP-011).

The harness reads `.kiro/steering/*.md` on the host, before any sandbox starts, and decides each file by its Kiro front
matter: no front matter or `inclusion: always` (always), `fileMatch` (a pattern matches a path of the task), `manual`
(the task, the requirements or the design names it as `#<file>`) and `auto` (included when the budget has room, after
the others; the task's reference puts it among the referenced ones). `~/.kiro/steering` is the runner's home and is
never read. Every decision is a `SteeringDecision`, and the prompt records the whole list.
"""

import os
import re
import stat
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from l4.fsutil import MAX_SOURCE_BYTES, UnsafeFile, read_regular_prefix, reject_symlinks
from l4.security.protected import glob_match

STEERING_DIR = ".kiro/steering"
INCLUSIONS = {"always": "always", "filematch": "fileMatch", "manual": "manual", "auto": "auto"}
ALWAYS, FILE_MATCH, REFERENCED, AUTO = 0, 1, 2, 3  # the order the budget meets them in


class BadFrontMatter(ValueError):
    """The front matter is not YAML, not a mapping, or names an inclusion Kiro does not have."""


@dataclass(frozen=True)
class SteeringDecision:
    """Whether a steering file (or the OpenSpec context) reaches the prompt, and why. `bucket` is its place in the
    budget order and is not recorded."""

    path: str
    inclusion: str
    included: bool
    why: str
    bucket: int = ALWAYS

    def as_dict(self) -> dict[str, Any]:
        return {"path": self.path, "inclusion": self.inclusion, "included": self.included, "why": self.why}


@dataclass(frozen=True)
class SteeringFile:
    """One file of `.kiro/steering` as it was read. `inclusion` is `none` when the file is not usable: `reason` then
    says why (`symlink`, `not_regular`, `bad_front_matter`). `reason == "oversize"` means `body` is the first
    `MAX_SOURCE_BYTES` of a larger file."""

    path: str
    inclusion: str
    patterns: tuple[str, ...]
    name: str
    body: str
    total_bytes: int
    reason: str = ""


def parse_front_matter(text: str) -> tuple[Mapping[str, Any], str]:
    """(the front matter's mapping, the body). The front matter is YAML between a first line `---` and a later line
    `---`; without both there is none (an empty mapping, the whole text). Raises `BadFrontMatter`."""
    text = text.removeprefix("﻿")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        return {}, text
    end = next((i for i in range(1, len(lines)) if lines[i].rstrip("\r\n") == "---"), None)
    if end is None:
        return {}, text
    try:
        meta = yaml.safe_load("".join(lines[1:end]))
    except yaml.YAMLError:
        raise BadFrontMatter("the front matter is not YAML") from None
    if meta is None:
        meta = {}
    if not isinstance(meta, dict):
        raise BadFrontMatter("the front matter is not a mapping")
    return meta, "".join(lines[end + 1 :])


def _inclusion(meta: Mapping[str, Any]) -> tuple[str, tuple[str, ...]]:
    value = meta.get("inclusion")
    if value is None:
        return "always", ()
    if not isinstance(value, str) or value.strip().lower() not in INCLUSIONS:
        raise BadFrontMatter("unknown inclusion")
    inclusion = INCLUSIONS[value.strip().lower()]
    if inclusion != "fileMatch":
        return inclusion, ()
    pattern = meta.get("fileMatchPattern")
    patterns = (pattern,) if isinstance(pattern, str) else tuple(pattern) if isinstance(pattern, list) else ()
    if not patterns or not all(isinstance(p, str) and p.strip() for p in patterns):
        raise BadFrontMatter("fileMatch needs a fileMatchPattern")
    return inclusion, tuple(p.strip() for p in patterns)


def _read_file(path: Path, rel: str) -> SteeringFile:
    if not _SAFE_NAME.fullmatch(path.name):  # the name is the source of a data block: it must not forge structure
        return SteeringFile(
            f"{STEERING_DIR}/{re.sub(r'[^A-Za-z0-9._ -]', '?', path.name)}", "none", (), "", "", 0, "bad_name"
        )
    try:
        info = os.lstat(path)
        if stat.S_ISLNK(info.st_mode):
            return SteeringFile(rel, "none", (), "", "", 0, "symlink")
        if not stat.S_ISREG(info.st_mode):
            return SteeringFile(rel, "none", (), "", "", 0, "not_regular")
        data, size = read_regular_prefix(path, MAX_SOURCE_BYTES)
    except (UnsafeFile, OSError):
        return SteeringFile(rel, "none", (), "", "", 0, "not_regular")
    text = data.decode("utf-8", errors="replace")
    try:
        meta, body = parse_front_matter(text)
        inclusion, patterns = _inclusion(meta)
    except BadFrontMatter:
        return SteeringFile(rel, "none", (), "", "", size, "bad_front_matter")
    name = meta.get("name")
    return SteeringFile(
        rel, inclusion, patterns, name.strip() if isinstance(name, str) else "", body, size,
        "oversize" if size > MAX_SOURCE_BYTES else "",
    )  # fmt: skip


def read_steering(root: Path) -> tuple[list[SteeringFile], list[SteeringDecision]]:
    """The direct `*.md` children of `root/.kiro/steering`, sorted by name, and the decisions that are not about one
    file (a linked directory reads nothing). `root` is the worktree of a run, the checkout in a dry run or doctor."""
    try:
        reject_symlinks(root, ".kiro", "steering")
    except UnsafeFile:
        return [], [SteeringDecision(STEERING_DIR, "none", False, "symlink")]
    directory = root / ".kiro" / "steering"
    try:
        names = sorted(e.name for e in os.scandir(directory) if e.name.endswith(".md"))
    except OSError:  # no steering folder (or it is not a directory)
        return [], []
    return [_read_file(directory / name, f"{STEERING_DIR}/{name}") for name in names], []


_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._ -]*\.md")


def _stem(path: str) -> str:
    return PurePosixPath(path).name.removesuffix(".md")


def _hash_reference(name: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![\w#/\[])#{re.escape(name)}(?![\w-])")


def is_referenced(file: SteeringFile, text: str) -> bool:
    """`#<file name>` as a token, `#[[file:.kiro/steering/<file>]]`, the path `.kiro/steering/<file>`, and for `auto`
    `#<name>` of its front matter, in `text`. Not `#money` inside `#moneyx` or `docs/#money`."""
    stem = _stem(file.path)
    if _hash_reference(stem).search(text) or file.path in text:
        return True
    if re.search(rf"#\[\[file:\s*{re.escape(file.path)}\s*\]\]", text):
        return True
    return file.inclusion == "auto" and bool(file.name) and _hash_reference(file.name).search(text) is not None


def _matched(file: SteeringFile, paths: Sequence[str]) -> str | None:
    """The first of `paths` that one of the file's patterns matches. A pattern without `/` is matched against the file
    name too [U: how Kiro matches such a pattern is not verified; a test pins this rule]."""
    for path in paths:
        name = PurePosixPath(path).name
        for pattern in file.patterns:
            if glob_match(pattern, path) or ("/" not in pattern and glob_match(pattern, name)):
                return path
    return None


def decide_steering(files: Sequence[SteeringFile], paths: Sequence[str], references: str) -> list[SteeringDecision]:
    """One decision per file, in the order given. `paths` are the repository paths of the task (those its block and the
    design's named sections name, and the files the unit branch changed so far); `references` is the text that may name
    a manual or auto file: the task block, `requirements.md`, `bugfix.md` and `design.md`."""
    decisions = []
    for file in files:
        if file.reason in ("symlink", "not_regular", "bad_front_matter", "bad_name"):
            decisions.append(SteeringDecision(file.path, "none", False, file.reason))
        elif file.inclusion == "always":
            decisions.append(SteeringDecision(file.path, "always", True, "always", ALWAYS))
        elif file.inclusion == "fileMatch":
            hit = _matched(file, paths)
            why = f"matched {hit}" if hit else "no_match"
            decisions.append(SteeringDecision(file.path, "fileMatch", hit is not None, why, FILE_MATCH))
        elif is_referenced(file, references):
            decisions.append(SteeringDecision(file.path, file.inclusion, True, "referenced", REFERENCED))
        elif file.inclusion == "auto":
            decisions.append(SteeringDecision(file.path, "auto", True, "auto", AUTO))  # when the budget has room
        else:
            decisions.append(SteeringDecision(file.path, "manual", False, "not_referenced", REFERENCED))
    return decisions


def references_text(texts: Iterable[str]) -> str:
    return "\n".join(texts)


CONTEXT_FILES = ("config.yaml", "config.yml")


def openspec_context(root: Path, openspec_root: str) -> tuple[str | None, SteeringDecision | None]:
    """The `context` string of `<openspec_root>/config.yaml` (or `.yml`) and the decision about it. Its `rules` are
    rules for writing specs and tasks, never shown. No file, or no `context`: nothing and no decision. A file that is
    a link, does not parse, or whose `context` is not a string adds nothing and records why."""
    for name in CONTEXT_FILES:
        rel = f"{openspec_root}/{name}"
        path = root / openspec_root / name
        try:
            reject_symlinks(root, *Path(openspec_root).parts, name)
            data, _ = read_regular_prefix(path, MAX_SOURCE_BYTES)
        except FileNotFoundError:
            continue
        except (UnsafeFile, OSError):
            return None, SteeringDecision(f"{rel}#context", "context", False, "symlink")
        label = f"{rel}#context"
        try:
            config = yaml.safe_load(data.decode("utf-8", errors="replace"))
        except yaml.YAMLError:
            return None, SteeringDecision(label, "context", False, "bad_front_matter")
        if not isinstance(config, dict) or "context" not in config:
            return None, None if isinstance(config, dict) or config is None else SteeringDecision(
                label, "context", False, "bad_front_matter"
            )
        context = config["context"]
        if not isinstance(context, str):
            return None, SteeringDecision(label, "context", False, "bad_front_matter")
        if not context.strip():
            return None, None
        return context, SteeringDecision(label, "context", True, "context", REFERENCED)
    return None, None
