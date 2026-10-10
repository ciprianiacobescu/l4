"""`tasks.md` merged when a base merge conflicts in it (state-vcs-locks 4.4, 4.5).

The harness is the only writer of the checkboxes, so the two sides may differ in them and nothing else. Both sides are
compared with every marker blanked: when they are byte-identical the result is the unit branch's bytes, with a task
marked done when either side has it done (a one-byte splice, as in `markers.py`; the other marker states `[~]` and
`[-]` of a Kiro file keep the unit branch's byte). Any other difference is `Escalate`.
"""

import re

from l4.specs.base import Framework
from l4.vcs.merge import Escalate

_LEAD = rb"(?:\xef\xbb\xbf)?[ \t\xc2\xa0]*(?:[-*+]|[0-9]{1,9}[.)])[ \t]*\["
_OPENSPEC = re.compile(rb"^(" + _LEAD + rb")([ xX])(\])")
_KIRO = re.compile(rb"^(" + _LEAD + rb")([ xX\-~])(\])")
_DONE = frozenset(b"xX")


def merge_task_markers(ours: bytes, theirs: bytes, framework: Framework) -> bytes:
    pattern = _KIRO if framework is Framework.KIRO else _OPENSPEC
    mine, other = ours.split(b"\n"), theirs.split(b"\n")
    if len(mine) != len(other):
        raise Escalate("tasks.md differs in more than checkboxes (line count)")
    out: list[bytes] = []
    for number, (a, b) in enumerate(zip(mine, other, strict=True), 1):
        ma, mb = pattern.match(a), pattern.match(b)
        if ma is None or mb is None:
            if a != b:
                raise Escalate(f"tasks.md differs in more than checkboxes (line {number})")
            out.append(a)
            continue
        if a[: ma.end(1)] + a[ma.end(2) :] != b[: mb.end(1)] + b[mb.end(2) :]:
            raise Escalate(f"tasks.md differs in more than checkboxes (line {number})")
        marker = a[ma.start(2) : ma.end(2)]
        if marker[0] not in _DONE and b[mb.start(2)] in _DONE:
            marker = b[mb.start(2) : mb.end(2)]
        out.append(a[: ma.start(2)] + marker + a[ma.end(2) :])
    return b"\n".join(out)
