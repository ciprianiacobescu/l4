"""The `.gitlab-ci.yml` edit of `l4 init` (forge-and-ci 1.22, M1.8 A1; SCN-INS-12 narrowed).

`merge_include` returns the new text of the file, never a rewrite of it: the include is inserted as text and every other
byte stays. The forms it can edit safely are the ones below; anything else is refused with the snippet to add by hand
(a flow list, a scalar or a mapping `include:` would need a re-serialisation that loses comments and order).

* no file: a new one with the include and a `test` job (stage `test`, the runner tags, the proposed gates) whose first
  line ends the job on a `schedule` pipeline. GitLab creates no pipeline whose only jobs are in `.pre` or `.post`, and
  the harness job `l4` is in `.post`: without a job of its own the sweep's scheduled pipeline would not exist;
* a file without a top-level `include:`: the snippet after the leading comment block (and a `---` marker);
* a file with a block-list `include:`: one `- local:` item before the first item, at the list's own indentation;
* the include already there: nothing.

The property: the parsed document after the edit is the one before with the include extended, the jobs keep their
order. The edit checks it itself (`_parses_back`) and refuses whatever does not hold it (a `%YAML` directive, a flow
mapping at the top, a repeated `include:` key), so a form the textual edit gets wrong is never written. CRLF files
stay CRLF; a byte-order mark stays first.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

import yaml

from l4.ci.gitlab_jobs import _Loader, parse_gitlab_ci
from l4.ci.render import INCLUDE_SNIPPET, TEMPLATE_RELPATH

Action = Literal["create", "insert-include", "extend-include", "noop", "refuse"]
_INCLUDE_KEY = re.compile(r"^include:\s*(?:#.*)?$")
_ITEM = re.compile(r"^(\s*)-\s")
_SCHEDULE_EXIT = '[ "$CI_PIPELINE_SOURCE" != "schedule" ] || { echo "l4 sweep pipeline: nothing to test"; exit 0; }'
_NO_PIPELINE = (
    "none of the jobs in this file is outside the stages .pre and .post, and the harness job `l4` is in .post: "
    "GitLab creates no pipeline whose jobs are all in those stages, so `l4` would never run; add a normal job"
)


@dataclass(frozen=True)
class CiEdit:
    action: Action
    text: str | None = None  # the whole new file; None when nothing is to be written
    reason: str = ""  # why it was refused
    snippet: str = INCLUDE_SNIPPET  # what to add by hand when refused
    warnings: tuple[str, ...] = ()


def _includes_template(items: Sequence[Any]) -> bool:
    for item in items:
        local = item if isinstance(item, str) else item.get("local") if isinstance(item, dict) else None
        if isinstance(local, str) and local.lstrip("/") == TEMPLATE_RELPATH:
            return True
    return False


def _test_job(runner_tags: Sequence[str], gates: Mapping[str, Any]) -> dict[str, Any]:
    script = [_SCHEDULE_EXIT, *gates.get("setup", []), gates.get("test", {}).get("command", "")]
    return {"test": {"stage": "test", "tags": list(runner_tags), "script": [line for line in script if line]}}


def _created(runner_tags: Sequence[str], gates: Mapping[str, Any]) -> str:
    header = (
        "# Written by `l4 init`: the include of the L4 harness job and a `test` job that runs the gates.\n"
        "# Keep your own jobs here; the `test` job is yours to change.\n"
    )
    job = yaml.safe_dump(_test_job(runner_tags, gates), sort_keys=False, default_flow_style=False, width=10_000)
    return header + INCLUDE_SNIPPET + "\n" + job


def _warnings(text: str) -> tuple[str, ...]:
    """The jobs of the file itself (not the include): one in a normal stage is what makes GitLab create a pipeline."""
    found = parse_gitlab_ci(text, lambda path: None)
    own = [j for j in found.jobs if not j.trigger]
    if any((j.stage or "test") not in (".pre", ".post") for j in own):
        return ()
    return (_NO_PIPELINE,)


def _refuse(reason: str) -> CiEdit:
    return CiEdit("refuse", reason=reason)


def _after_leading_comments(lines: list[str]) -> int:
    """The index of the line the snippet goes before: past the comment block, blank lines and a `---` marker."""
    index = 0
    while index < len(lines) and (not lines[index].strip() or lines[index].lstrip().startswith("#")):
        index += 1
    if index < len(lines) and lines[index].rstrip() == "---":
        index += 1
    return index


_NOT_PARSED_BACK = (
    "the edited file would not parse back to the same pipeline with the include added (a `%YAML` directive, a flow "
    "mapping at the top or a repeated `include:` key)"
)
_BOM = "\ufeff"


def _parses_back(before: str, after: str) -> bool:
    """The parsed `after` is the parsed `before` with the template's include first in its include list: every other
    key equal and in the same order."""
    try:
        old = yaml.load(before, Loader=_Loader)  # noqa: S506  (a SafeLoader subclass)
        new = yaml.load(after, Loader=_Loader)  # noqa: S506
    except yaml.YAMLError:
        return False
    old = {} if old is None else old
    if not isinstance(old, dict) or not isinstance(new, dict):
        return False
    old_include, new_include = old.get("include", []), new.get("include")
    if not isinstance(old_include, list) or new_include != [{"local": TEMPLATE_RELPATH}, *old_include]:
        return False
    rest_old = {k: v for k, v in old.items() if k != "include"}
    rest_new = {k: v for k, v in new.items() if k != "include"}
    return rest_old == rest_new and list(rest_old) == list(rest_new)


def merge_include(text: str | None, runner_tags: Sequence[str], gates: Mapping[str, Any]) -> CiEdit:
    if text is None:
        return CiEdit("create", _created(runner_tags, gates))
    bom = _BOM if text.startswith(_BOM) else ""
    edit = _edit(text.removeprefix(bom))
    if edit.text is None:
        return edit
    new = bom + edit.text
    if not _parses_back(text, new):
        return _refuse(_NOT_PARSED_BACK)
    return replace(edit, text=new)


def _edit(text: str) -> CiEdit:
    try:
        document = yaml.load(text, Loader=_Loader)  # noqa: S506  (a SafeLoader subclass)
    except yaml.YAMLError:
        return _refuse("it is not valid YAML")
    if document is None:
        document = {}
    if not isinstance(document, dict):
        return _refuse("its top level is not a mapping")
    eol = "\r\n" if "\r\n" in text else "\n"
    lines = text.replace("\r\n", "\n").split("\n")  # a trailing "" stands for the final newline
    if "include" not in document:
        at = _after_leading_comments(lines)
        snippet = INCLUDE_SNIPPET.rstrip("\n").split("\n")
        spacer = [""] if at < len(lines) and lines[at].strip() else []
        merged = [*lines[:at], *snippet, *spacer, *lines[at:]]
        if at >= len(lines) or (at == len(lines) - 1 and lines[at] == ""):
            merged = [*lines[:at], *snippet, ""]
        new = eol.join(merged)
        return CiEdit("insert-include", new, warnings=_warnings(new))
    include = document["include"]
    if not isinstance(include, list):
        return _refuse("its `include:` is a single entry or a mapping, which init does not rewrite")
    if _includes_template(include):
        return CiEdit("noop")
    start = next((i for i, line in enumerate(lines) if _INCLUDE_KEY.match(line)), None)
    if start is None:
        return _refuse("its `include:` is not a plain top-level block list (a flow list or a quoted key)")
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        found = _ITEM.match(line)
        if found is None:
            return _refuse("its `include:` is not a block list")
        merged = [*lines[:index], f"{found.group(1)}- local: {TEMPLATE_RELPATH}", *lines[index:]]
        new = eol.join(merged)
        return CiEdit("extend-include", new, warnings=_warnings(new))
    return _refuse("its `include:` list has no entries to place the new one before")
