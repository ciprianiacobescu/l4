# ruff: noqa: F811
"""`l4 yolo go` findings and acceptance (L4-YOLO-085; SCN-YOLO-222 to -226): the subjects that are not READY stop the
run, `--accept-findings` accepts them by the rules of `l4 yolo accept` (all or nothing), `--force` is a person's force
acceptance."""

from .yolo_actor import agent, person  # noqa: F401
from .yolo_cmd_world import A, B, forge, world  # noqa: F401
from .yolo_review_events import FAILURES, TESTABILITY, entry, review, two_rounds

REASON = "keep the thresholds"


def committed(world) -> None:
    world.push_plan()
    world.pull()


def both_not_ready(world, *, b_verdict="NEEDS_REVISION") -> None:
    """A and B judged not READY on two versions (the first under a made-up digest), A on `testability`, B on
    `failure_cases` (or BLOCKED)."""
    b_findings = [FAILURES] if b_verdict == "NEEDS_REVISION" else []
    for at, digest, material in (("2026-10-14T10:00:00Z", "old", "m1"), ("2026-10-14T11:00:00Z", None, "m2")):
        rows = {
            A: entry(world, A, "NEEDS_REVISION", [TESTABILITY], f"a-{material}", digest),
            B: entry(world, B, b_verdict, b_findings, f"b-{material}", digest),
        }
        world.seed("p1", review(world, at, rows))


def kinds(world, kind):
    return [e for e in world.events() if e.type == kind]


def next_lines(out: str) -> list[str]:
    return [line for line in out.splitlines() if line.startswith("Next:")]


def test_a_subject_not_ready_stops_at_findings(world, forge, person, capsys):
    """SCN-YOLO-222."""
    committed(world)
    two_rounds(world, [TESTABILITY], unit=B)
    before = world.store().read().head
    assert world.l4("go", "p1", "--reason", "R") == 26
    out = capsys.readouterr().out
    assert f"findings: stopped: {B}: NEEDS_REVISION: testability: no scenario gives an input and an output" in out
    assert next_lines(out) == ["Next: l4 yolo go p1 --reason R --accept-findings"]
    assert "accept:" not in out and "activate:" not in out and "--force" not in out
    assert world.store().read().head == before and person == []


def test_a_blocked_subject_stops_at_findings_and_names_force(world, forge, person, capsys):
    committed(world)
    two_rounds(world, [], unit=B, verdict="BLOCKED")
    assert world.l4("go", "p1", "--reason", "R") == 26
    out = capsys.readouterr().out
    assert next_lines(out) == ["Next: l4 yolo findings p1"]
    assert 'when no model can judge it, a person may run: l4 yolo go p1 --reason "..." --force' in out


def test_accept_findings_accepts_each_subject_and_activates(world, forge, person, monkeypatch, capsys):
    """SCN-YOLO-223."""
    committed(world)
    both_not_ready(world)
    order: list[tuple[str, str]] = []

    def prompt(text, **kwargs):
        order.append(("before", capsys.readouterr().out))  # what was printed since the previous prompt
        order.append(("prompt", text))
        return "p1"

    monkeypatch.setattr("l4.yolo.commands.click.prompt", prompt)
    assert world.l4("go", "p1", "--reason", REASON, "--accept-findings") == 0
    first, _, second, _ = order
    assert "[major/testability]" in first[1] and "[major/failure_cases]" not in first[1]  # A's findings, A's prompt
    assert "[major/failure_cases]" in second[1] and "[major/testability]" not in second[1]  # then B's, B's prompt
    accepted = kinds(world, "plan.accepted")
    assert [(e.data["subject"], e.data["actor"], e.data["reason"], e.data["confirmed"]) for e in accepted] == [
        (A, "person", REASON, "typed"), (B, "person", REASON, "typed"),
    ]  # fmt: skip
    (activated,) = kinds(world, "plan.activated")
    assert sorted(activated.data["accepted"]) == sorted([A, B]) and activated.data["reason"] == REASON
    out = capsys.readouterr().out
    assert "accept: done: accepted 2 subject(s)" in out and "activate: done" in out
    assert next_lines(out) == ["Next: l4 yolo status p1"]


def test_accept_findings_with_yes_asks_nothing(world, forge, person, capsys):
    committed(world)
    both_not_ready(world)
    assert world.l4("go", "p1", "--reason", REASON, "--accept-findings", "--yes") == 0
    assert person == []
    assert {e.data["confirmed"] for e in kinds(world, "plan.accepted")} == {"--yes"}
    assert len(kinds(world, "plan.activated")) == 1


def test_one_subject_that_cannot_be_accepted_means_none_is(world, forge, person, capsys):
    """SCN-YOLO-224."""
    committed(world)
    both_not_ready(world, b_verdict="BLOCKED")
    assert world.l4("go", "p1", "--reason", REASON, "--accept-findings", "--yes") == 26
    out = capsys.readouterr().out
    assert f"{B}: {B} is BLOCKED" in out and next_lines(out) == ["Next: l4 yolo findings p1"]
    assert kinds(world, "plan.accepted") == [] and kinds(world, "plan.activated") == []
    assert person == []


def test_a_wrong_answer_stops_with_29(world, forge, person, monkeypatch, capsys):
    committed(world)
    both_not_ready(world)
    answers = iter(["p1", "yes"])
    monkeypatch.setattr("l4.yolo.commands.click.prompt", lambda *a, **k: next(answers))
    assert world.l4("go", "p1", "--reason", REASON, "--accept-findings") == 29
    out = capsys.readouterr().out
    assert "accept: stopped: accept: the plan id was not typed: nothing was recorded" in out
    assert next_lines(out) == [f"Next: l4 yolo go p1 --reason '{REASON}' --accept-findings"]
    assert [e.data["subject"] for e in kinds(world, "plan.accepted")] == [A]  # A's acceptance stays and holds
    assert kinds(world, "plan.activated") == []
