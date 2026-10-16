"""The text block of a task (unfreeze-and-answer design D3, requirement L4-IMP-014).

`Task` holds only the title, so the text of a task is read from the file: its checkbox line and every line below it up
to the next task line (the provider's own task regex) or a heading. This is the span that Kiro's `_links_below` reads.
The marker is read as `[ ]` as the plan digest reads it, so a ticked task has the text of an unticked one; line ends
are `\\n` and a BOM is dropped.
"""

import re

from l4.specs.base import Framework, Task
from l4.specs.kiro import KIRO_TASK_RE
from l4.specs.markers import split_lines
from l4.specs.openspec import OPENSPEC_TASK_RE
from l4.yolo.digest import _MARKER


def task_text(data: bytes, task: Task, framework: Framework) -> str:
    """The checkbox line of `task` (by `task.line`) and the lines after it, each ended by `\\n`."""
    task_re = OPENSPEC_TASK_RE if framework is Framework.OPENSPEC else KIRO_TASK_RE
    lines = split_lines(data)
    if not 1 <= task.line <= len(lines):
        raise ValueError(f"task line {task.line} is not in a file of {len(lines)} lines")
    first = lines[task.line - 1].text.removeprefix("﻿")
    block = [_MARKER.sub(rb"\1 \2", first.encode("utf-8", "surrogateescape")).decode("utf-8", "surrogateescape")]
    for line in lines[task.line :]:
        text = line.text.removeprefix("﻿")
        if task_re.match(text) or text.startswith("#"):
            break
        block.append(text)
    return "".join(f"{text}\n" for text in block)


_HEADING = re.compile(r"(#{1,4})[ \t]+\S")
_FENCE = re.compile(r"\s{0,3}(```|~~~)")


def _enclosing_headings(data: bytes, line: int) -> list[str]:
    """The heading lines (`#`..`####`) above 1-based `line` that enclose it: the closest heading above, then the
    closest one of each lower level above that, outermost first. A `#` line inside a code fence is no heading."""
    stack: list[tuple[int, str]] = []
    fence: str | None = None
    for item in split_lines(data)[: line - 1]:
        text = item.text.removeprefix("\ufeff")
        if m := _FENCE.match(text):
            fence = None if fence == m.group(1) else (fence or m.group(1))
            continue
        if fence is None and (h := _HEADING.match(text)):
            level = len(h.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, text))
    return [text for _, text in stack]


def task_context(data: bytes, task: Task, framework: Framework) -> str:
    """What the named-file rule reads for a task (L4-IMP-014): the Markdown headings that enclose the task in the same
    file, outermost first and each ended by `\\n`, then `task_text`. A heading is part of the same reviewed file as the
    task line, so it has the same trust source."""
    headings = "".join(f"{text}\n" for text in _enclosing_headings(data, task.line))
    return headings + task_text(data, task, framework)
