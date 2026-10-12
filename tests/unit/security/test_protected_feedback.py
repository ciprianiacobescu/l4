"""human-feedback 2.7 (L4-FBK-012): `feedback.md` is a protected path for every agent role; an agent that marks its own
item addressed has the file put back, and a `guard.violation` names it."""

import pytest

from l4.redact import Redactor
from l4.security.protected import ProtectedSet, revert_protected
from l4.specs.feedback import FeedbackFile, FeedbackKind, FeedbackStatus, NewFeedback, Place, append_item

BY = "CiprianSpot, 2026-10-12T15:04:00Z"


class Sink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def append(self, event_type, /, **data):
        self.events.append((event_type, data))


@pytest.mark.parametrize("unit", ["openspec/changes/add-x", ".kiro/specs/add-x"])
def test_SCN_FBK_27_an_agent_marking_its_own_item_addressed_is_put_back(unit, make_repo, git_for, raw):
    """SCN-FBK-27: the step ends, `feedback.md` is what the person wrote, and `guard.violation` names the file."""
    repo = make_repo()
    (repo / unit).mkdir(parents=True)
    new = NewFeedback(FeedbackKind.REFACTOR, "Extract", "Move it.", BY, places=(Place("src/a.py", 3, 4),))
    append_item(repo / unit, "add-x", new, redactor=Redactor({}))
    (repo / "src").mkdir()
    (repo / "src/a.py").write_text("x = 1\n")
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "base")
    base = raw(repo, "rev-parse", "HEAD").strip()
    written = (repo / unit / "feedback.md").read_bytes()

    file = FeedbackFile.load(repo / unit)
    assert file is not None
    file.set_status("FB-001", FeedbackStatus.ADDRESSED).save()  # the agent's edit
    assert (repo / unit / "feedback.md").read_bytes() != written
    (repo / "src/a.py").write_text("x = 2\n")  # its legitimate work stays

    sink = Sink()
    out = revert_protected(git_for(repo), ProtectedSet((), unit, f"{unit}/.l4/ledger/r-1.jsonl"), base, events=sink)

    assert (repo / unit / "feedback.md").read_bytes() == written
    assert (repo / "src/a.py").read_text() == "x = 2\n"
    assert [(v.path, v.action) for v in out] == [(f"{unit}/feedback.md", "restored")]
    assert [(t, d["path"]) for t, d in sink.events] == [("guard.violation", f"{unit}/feedback.md")]


def test_a_feedback_file_the_agent_creates_is_removed(make_repo, git_for, raw):
    repo = make_repo()
    unit = "openspec/changes/add-x"
    (repo / unit).mkdir(parents=True)
    (repo / unit / "tasks.md").write_text("- [ ] 1.1 a\n")
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "base")
    base = raw(repo, "rev-parse", "HEAD").strip()
    (repo / unit / "feedback.md").write_text("# planted\n")
    out = revert_protected(git_for(repo), ProtectedSet((), unit, f"{unit}/.l4/ledger/r-1.jsonl"), base)
    assert [(v.path, v.action) for v in out] == [(f"{unit}/feedback.md", "removed")]
    assert not (repo / unit / "feedback.md").exists()
