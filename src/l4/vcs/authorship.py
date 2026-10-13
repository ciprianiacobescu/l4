"""Who made a commit: the harness's own commits are bot name, bot e-mail and a non-empty `L4-Run` trailer (L4-ARC-008
(d)); every other commit is foreign. Two rules read it: `is_harness` (the author) for per-commit attribution of a change
(M1.9 G3), and `is_harness_strict` (author and committer) for the review re-entry (M1.9 G1). The hand-off commit H is
the newest strictly-harness commit on the first-parent chain of the unit branch that carries `L4-Phase: verified`
and the hand-off subject.

This lives in the `vcs` layer so that the planner and the state fold can use it (the verifier package imports both).
"""

from l4.vcs.git import BOT_IDENTITY, Git

HANDOFF_SUBJECT = "docs({name}): hand off to review"  # never carries `[skip ci]` (L4-ARC-008)

_SEP, _END = "\x01", "\x02"
_RUN, _PHASE = (f"%(trailers:key={key},valueonly,separator=%x2c)" for key in ("L4-Run", "L4-Phase"))
_FORMAT = _SEP.join(["%H", "%an", "%ae", "%s", _RUN, _PHASE, "%cn", "%ce"]) + _END

SHA, AUTHOR, EMAIL, SUBJECT, RUN, PHASE, COMMITTER, COMMITTER_EMAIL = range(8)  # fields of a record


def commit_records(git: Git, *args: str) -> list[list[str]]:
    """`git log <args>` as records `[sha, author name, author e-mail, subject, L4-Run, L4-Phase,
    committer name, committer e-mail]`, newest first."""
    out = git.run("log", f"--format={_FORMAT}", *args, check=False).stdout
    return [r.strip("\n").split(_SEP) for r in out.split(_END) if r.strip("\n")]


def is_harness(record: list[str]) -> bool:
    """The author rule (bot author and an `L4-Run` trailer): who *wrote* the change. Per-commit attribution of a
    forbidden-path change (M1.9 G3) keeps it, so a person who rebases an agent's commit (committer = the person, author
    kept) cannot turn the agent's change into a human's."""
    return record[AUTHOR] == BOT_IDENTITY.name and record[EMAIL] == BOT_IDENTITY.email and bool(record[RUN].strip())


def is_harness_strict(record: list[str]) -> bool:
    """The strict rule for the review re-entry (M1.9 G1): author AND committer are the bot and an `L4-Run` trailer is
    present. An amended, rebased or cherry-picked commit keeps the author and the trailers but its committer is the
    person who did it, so it is not the harness's. A forge's squash commit (a project bot account, no trailers) is
    foreign under both rules."""
    return (
        is_harness(record)
        and len(record) > COMMITTER_EMAIL
        and record[COMMITTER] == BOT_IDENTITY.name
        and record[COMMITTER_EMAIL] == BOT_IDENTITY.email
    )


def handoff_commit(git: Git, head: str, name: str, scan: int = 500) -> str | None:
    """The sha of the unit's hand-off commit H reachable from `head`, or None (none made, or beyond `scan` commits)."""
    subject = HANDOFF_SUBJECT.format(name=name)
    for record in commit_records(git, "--first-parent", f"--max-count={scan}", head):
        if is_harness_strict(record) and record[SUBJECT] == subject and record[PHASE].strip() == "verified":
            return record[SHA]
    return None
