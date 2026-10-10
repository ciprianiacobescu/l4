"""The sticky section for a unit that waits for a human (SPEC L4-CLR-004, L4-CLR-005; design D8).

The clarifier makes no forge call: `build_sticky_section` returns markdown, and the `mirror` hook puts it into the one
`<!-- l4:sticky -->` note of the merge request. Everything that comes from the repository or a model (titles) is
one line, without a mention, a link or markup that could ping people or hide text.
M1: the configured `forge.notify_mentions` of L4-CLR-004 (clarification-loop 1.15 mentions)
"""

import re
from collections.abc import Sequence

from l4.clarifier.ports import QuestionView

UNAVAILABLE_SENTENCE = "The clarifier was unavailable; no suggestions were written."
MAX_TITLE_CHARS = 120
_MARKUP = str.maketrans({"`": "'", "[": "(", "]": ")", "<": "‹", ">": "›", "@": "@\N{ZERO WIDTH SPACE}"})
_LINE_BREAKS = re.compile(r"\s+")


def _title(text: str) -> str:
    one = "".join(ch for ch in _LINE_BREAKS.sub(" ", text) if ch.isprintable()).strip()
    return one.translate(_MARKUP)[:MAX_TITLE_CHARS]


def build_sticky_section(
    questions: Sequence[QuestionView],
    *,
    path: str,
    branch: str,
    link: str | None,
    clarifier_unavailable: bool = False,
    invalid: Sequence[str] = (),
    drafts: Sequence[str] = (),
    unreadable: Sequence[str] = (),
) -> str:
    """The open questions (id, kind, title), where to answer them, and the sentences a human needs: the clarifier was
    unavailable or gave invalid output, and an answer whose Status is still `open` is a draft."""
    lines = ["### Waiting for you: a human answer", ""]
    lines += [f"- {q.id} ({q.kind.value if q.kind else 'unlabelled'}): {_title(q.title)}" for q in questions]
    lines += [f"- {qid} (unreadable): its section cannot be read, so every pending task is held" for qid in unreadable]
    where = f"[`{path}`]({link})" if link else f"`{path}`"
    lines += [
        "",
        f"Answer in {where} on branch `{branch}`: write under `### Answer`, set Status to `answered` (or `accepted` "
        "to take the clarifier's suggestion), then commit and push.",
    ]
    notes = []
    if clarifier_unavailable or invalid:  # L4-CLR-005: output that stays invalid counts as unavailable
        notes.append(UNAVAILABLE_SENTENCE)
    notes += [f"The clarifier produced invalid output for {qid}; no suggestion was written." for qid in invalid]
    notes += [
        f"{qid} has an answer but its Status is still `open`: set it to `answered` to submit it." for qid in drafts
    ]
    return "\n".join([*lines, *([""] + notes if notes else [])])
