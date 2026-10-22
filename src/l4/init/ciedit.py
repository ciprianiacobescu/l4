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

After an edit of an existing file, when none of its jobs would run in a normal stage on the harness's pipelines
(L4-INS-009), the job `l4-pipeline-anchor` is appended: GitLab refuses a pipeline whose jobs are all in `.pre` or
`.post`.

The property: the parsed document after the edit is the one before with the include extended, the jobs keep their
order. The edit checks it itself (`_parses_back`) and refuses whatever does not hold it (a `%YAML` directive, a flow
mapping at the top, a repeated `include:` key), so a form the textual edit gets wrong is never written. CRLF files
stay CRLF; a byte-order mark stays first.
"""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

import yaml

from l4.ci.gitlab_jobs import _Loader, parse_gitlab_ci
from l4.ci.gitlab_rules import ANCHOR_JOB, empty_pipeline_findings
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
    anchor: bool = False  # the job `l4-pipeline-anchor` was appended to `text`


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


_ANCHOR_COMMENT = (
    "# Added by `l4 init`: GitLab refuses a pipeline whose jobs are all in .pre or .post, "
    "and the l4 job is in .post. This",
    "# job gives the harness's own pipelines (schedule, api, trigger, web) a job in a normal stage; it only echoes.",
)
_REGEX_SPECIAL = frozenset("\\.^$*+?()[]{}|/-")


def _escaped(prefix: str) -> str:
    """`forge.branch_prefix` as the literal start of a regular expression (`/` escaped too: the pattern sits in /…/)."""
    return "".join("\\" + c if c in _REGEX_SPECIAL else c for c in prefix)


def _anchor_stage(document: Mapping[str, Any]) -> str | None:
    """`test` when the file has no `stages:` or its list holds `test`, else its first stage that is not `.pre` or
    `.post`; None when there is none (the job could not be placed)."""
    stages = document.get("stages")
    if not isinstance(stages, list) or "test" in stages:
        return "test"
    return next((s for s in stages if isinstance(s, str) and s not in (".pre", ".post")), None)


def _anchor_block(stage: str, runner_tags: Sequence[str], branch_prefix: str, eol: str) -> str:
    lines = ["", *_ANCHOR_COMMENT, f"{ANCHOR_JOB}:", f"  stage: {stage}"]
    if runner_tags:
        lines.append(f"  tags: [{', '.join(runner_tags)}]")
    lines += [
        "  script:",
        '    - echo "L4 pipeline ($CI_PIPELINE_SOURCE on $CI_COMMIT_REF_NAME)"',
        "  rules:",
        "    - if: '$CI_PIPELINE_SOURCE =~ /^(schedule|api|trigger|web)$/'",
        f"    - if: '$CI_PIPELINE_SOURCE == \"push\" && $CI_COMMIT_BRANCH =~ /^{_escaped(branch_prefix)}/'",
    ]
    return eol.join(lines) + eol


def _anchored_parses_back(before: str, after: str) -> bool:
    """The parsed `after` is the parsed `before` plus the anchor job as its last key."""
    try:
        old = yaml.load(before, Loader=_Loader)  # noqa: S506  (a SafeLoader subclass)
        new = yaml.load(after, Loader=_Loader)  # noqa: S506
    except yaml.YAMLError:
        return False
    if not isinstance(old, dict) or not isinstance(new, dict) or list(new)[-1:] != [ANCHOR_JOB]:
        return False
    rest = {k: v for k, v in new.items() if k != ANCHOR_JOB}
    return rest == old and list(rest) == list(old) and isinstance(new[ANCHOR_JOB], dict)


def _with_anchor(
    edit: CiEdit,
    runner_tags: Sequence[str],
    base_branch: str,
    branch_prefix: str,
    load: Callable[[str], str | None] | None,
) -> CiEdit:
    """Append `l4-pipeline-anchor` when, after the include edit, a harness pipeline would hold no project job in a
    normal stage (nothing unknown either) and no job of that name exists. Never refuses: no anchor is the fallback."""
    assert edit.text is not None
    bom = _BOM if edit.text.startswith(_BOM) else ""
    body = edit.text.removeprefix(bom)

    def read(path: str) -> str | None:
        if path == TEMPLATE_RELPATH:
            return ""  # the harness's own file, written by this very init: only the `l4` job
        return load(path) if load is not None else None

    found = parse_gitlab_ci(body, read)
    if found.job(ANCHOR_JOB) is not None or ANCHOR_JOB in found.raw:
        return edit
    if not any(f.kind == "pipeline" for f in empty_pipeline_findings(found, base_branch, base_branch, branch_prefix)):
        return edit
    document = yaml.load(body, Loader=_Loader)  # noqa: S506  (parsed before, once more here)
    stage = _anchor_stage(document if isinstance(document, dict) else {})
    if stage is None:
        return edit
    eol = "\r\n" if "\r\n" in body else "\n"
    lead = "" if body.endswith("\n") else eol
    anchored = body + lead + _anchor_block(stage, runner_tags, branch_prefix, eol)
    if not _anchored_parses_back(body, anchored):
        return edit
    return replace(edit, text=bom + anchored, warnings=_warnings(anchored), anchor=True)


def merge_include(
    text: str | None,
    runner_tags: Sequence[str],
    gates: Mapping[str, Any],
    *,
    base_branch: str = "main",
    branch_prefix: str = "l4/",
    load: Callable[[str], str | None] | None = None,
) -> CiEdit:
    if text is None:
        return CiEdit("create", _created(runner_tags, gates))
    bom = _BOM if text.startswith(_BOM) else ""
    edit = _edit(text.removeprefix(bom))
    if edit.text is None:
        return edit
    new = bom + edit.text
    if not _parses_back(text, new):
        return _refuse(_NOT_PARSED_BACK)
    return _with_anchor(replace(edit, text=new), runner_tags, base_branch, branch_prefix, load)


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
