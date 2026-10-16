"""The text block of a task (unfreeze-and-answer design D3, requirement L4-IMP-014).

`Task` holds only the title, so the text of a task is read from the file: its checkbox line and every line below it up
to the next task line (the provider's own task regex) or a heading. This is the span that Kiro's `_links_below` reads.
The marker is read as `[ ]` as the plan digest reads it, so a ticked task has the text of an unticked one; line ends
are `\\n` and a BOM is dropped.
"""

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
