"""Who answered a question (L4-QMD-009, design D11): one function for every writer of an actor.

1. Status `answered-by-clarifier`: the clarifier.
2. The ledger records the delegate's answer (`question.answered{by: delegate}` or `delegate.result{status: answered}`)
   with the current answer digest: the delegate.
3. Else the newest commit (at most `MAX_COMMITS` back) that touched `questions.md`, has the subject of `l4 questions`
   for this id (`answer Q-NNN (` or `accept Q-NNN (`) and whose `questions.md` gives the question the current digest:
   its `By:` line decides (`(person)` a person, `(agent: X)` an agent, anything else, a `delegate` line that no ledger
   record backs included, an agent).
4. Else (a hand edit, or a later hand edit that changed the answer) a person.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from l4.exitcodes import L4Exit
from l4.specs.questions import (
    QUESTIONS_FILENAME,
    Question,
    QuestionsFile,
    QuestionStatus,
    answer_sha256,
)
from l4.state.ledger import LedgerEvent
from l4.vcs.git import Git

MAX_COMMITS = 200
_BY = re.compile(r"(?m)^By: .*\((?:(?P<person>person)|agent: (?P<marker>[^()\n]*))\)[ \t]*$")
_SEP = "\x1e"  # between commits
_FIELD = "\x1f"  # between the sha, the subject and the body of a commit


@dataclass(frozen=True)
class Actor:
    by: Literal["human", "agent", "clarifier", "delegate"]
    marker: str | None = None  # an agent: the marker of its environment (CLAUDECODE, ...)
    profile: str | None = None  # the delegate: the profile, the model and the CLI that answered
    model: str | None = None
    cli: str | None = None

    def fields(self) -> dict[str, str]:
        """The keys a ledger event adds to `by`: only those set."""
        out = {"marker": self.marker, "profile": self.profile, "model": self.model, "cli": self.cli}
        return {k: v for k, v in out.items() if v}


def _ledger_delegate(
    events: Sequence[LedgerEvent], qid: str, digest: str | None, fix_unit: str | None = None
) -> Actor | None:
    for event in reversed(events):
        data = event.data
        if digest is None or data.get("answer_sha256") != digest:
            continue
        if data.get("fix_unit") != fix_unit:  # a fix unit numbers its questions from Q-001 in its own file
            continue
        if (
            event.type == "question.answered"
            and data.get("by") == "delegate"
            and data.get("id") == qid
            or event.type == "delegate.result"
            and data.get("status") == "answered"
            and data.get("id") == qid
        ):
            pass
        else:
            continue
        profile, model, cli = data.get("profile"), data.get("model"), data.get("cli")
        return Actor(
            "delegate",
            profile=profile if isinstance(profile, str) else None,
            model=model if isinstance(model, str) else None,
            cli=cli if isinstance(cli, str) else None,
        )
    return None


def _git_actor(git: Git, question: Question, digest: str) -> Actor | None:
    """The `By:` line of the newest `l4 questions` commit of this question whose file gives it `digest`."""
    try:
        done = git.run(
            "log", "-n", str(MAX_COMMITS), f"--format={_SEP}%H{_FIELD}%s{_FIELD}%b", "--", QUESTIONS_FILENAME,
            check=False, timeout=30,
        )  # fmt: skip
    except (L4Exit, OSError):
        return None
    if done.returncode != 0:
        return None
    subjects = (f"answer {question.id} (", f"accept {question.id} (")
    for chunk in done.stdout.split(_SEP):
        sha, _, rest = chunk.strip().partition(_FIELD)
        subject, _, body = rest.partition(_FIELD)
        if not sha or not subject.startswith(subjects):
            continue
        try:
            shown = git.run_bytes("show", f"{sha}:./{QUESTIONS_FILENAME}", check=False, timeout=30)
        except (L4Exit, OSError):
            continue
        then = QuestionsFile.parse(shown).get(question.id)
        if then is None or answer_sha256(then) != digest:
            continue
        found = _BY.search(body)
        if found is not None and found.group("person"):
            return Actor("human")
        if found is not None:
            return Actor("agent", marker=(found.group("marker") or "").strip() or None)
        return Actor("agent")
    return None


def answer_actor(
    git: Git, unit_dir: Path, question: Question, events: Sequence[LedgerEvent], *, fix_unit: str | None = None
) -> Actor:
    """The actor of the current answer of `question` (see the module doc). `fix_unit`: the question is one of that fix
    unit's, whose records are in the parent's ledger (`events`) under the same name; else only a record of the unit's
    own questions counts."""
    if question.status is QuestionStatus.ANSWERED_BY_CLARIFIER:
        return Actor("clarifier")
    digest = answer_sha256(question)
    delegate = _ledger_delegate(events, question.id, digest, fix_unit)
    if delegate is not None:
        return delegate
    if digest is not None:
        by_commit = _git_actor(git, question, digest)
        if by_commit is not None:
            return by_commit
    return Actor("human")
