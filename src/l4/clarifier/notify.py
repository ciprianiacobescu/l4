"""The sticky section for a unit that waits for a human (SPEC L4-CLR-004, L4-CLR-005; design D8).

The clarifier makes no forge call: `build_sticky_section` returns markdown, and the `mirror` hook puts it into the one
`<!-- l4:sticky -->` note of the merge request. Everything that comes from the repository or a model (titles) is
one line, without a mention, a link or markup that could ping people or hide text.
M1: the configured `forge.notify_mentions` of L4-CLR-004 (clarification-loop 1.15 mentions)
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from l4.clarifier.ports import QuestionView
from l4.specs.questions import QuestionKind, QuestionStatus, harness_decision

UNAVAILABLE_SENTENCE = "The clarifier was unavailable; no suggestions were written."
MAX_TITLE_CHARS = 120
_MARKUP = str.maketrans({"`": "'", "[": "(", "]": ")", "<": "‹", ">": "›", "@": "@\N{ZERO WIDTH SPACE}"})
_LINE_BREAKS = re.compile(r"\s+")


def sticky_line(text: str, limit: int = MAX_TITLE_CHARS) -> str:
    """Repository or model text as one line of a note: no line break, no mention, link or markup, cut at `limit`."""
    one = "".join(ch for ch in _LINE_BREAKS.sub(" ", text) if ch.isprintable()).strip()
    return one.translate(_MARKUP)[:limit]


def _title(text: str) -> str:
    return sticky_line(text)


@dataclass(frozen=True)
class DelegateEscalation:
    """A question the delegate left to a person: its key, kind and title, and the delegate's reason (L4-DLG-008)."""

    key: str
    kind: str | None
    title: str
    reason: str


@dataclass(frozen=True)
class DelegateAnswer:
    """A question the delegate answered: who it was (the model, and the CLI that served it) (L4-CLR-004)."""

    key: str
    kind: str | None
    title: str
    model: str
    cli: str


def _item(key: str, kind: str | None, title: str) -> str:
    shown = _title(title)
    return f"- {sticky_line(key)} ({sticky_line(kind) if kind else 'unlabelled'}){': ' + shown if shown else ''}"


def needs_person_section(items: Sequence[DelegateEscalation]) -> str:
    """`Needs a person (the delegate escalated)`: each escalated open question with the delegate's reason, one line
    each, as safe as every title ('' when none)."""
    if not items:
        return ""
    lines = [_item(i.key, i.kind, i.title) + (f": {sticky_line(i.reason, 300)}" if i.reason else "") for i in items]
    return "\n".join(["### Needs a person (the delegate escalated)", "", *lines])


def answered_by_delegate_section(items: Sequence[DelegateAnswer]) -> str:
    """`Answered by the delegate`: the questions it answered, with the model and the CLI ('' when none)."""
    if not items:
        return ""
    lines = [f"{_item(i.key, i.kind, i.title)} ({sticky_line(i.model)} via {sticky_line(i.cli)})" for i in items]
    return "\n".join(["### Answered by the delegate", "", *lines])


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
    notes += [  # a harness answer is `accept` or `retry` (L4-QMD-004): anything else was not read
        f"{q.id} has an answer that does not start with `accept` or `retry`: it was not read. Please answer again."
        for q in questions
        if q.kind is QuestionKind.HARNESS and q.status is QuestionStatus.ANSWERED
        and harness_decision(q.answer_text) is None
    ]  # fmt: skip
    return "\n".join([*lines, *([""] + notes if notes else [])])
