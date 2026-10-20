"""A CI failure that no fix touched (ci-evidence D12; L4-OPS-023): the project files a branch changed since a head, and
the history of a red job across the unit's hand-offs.

The same job failing again on a later hand-off, with no commit since its earlier failure that changed a project file
(a path outside the units' folders, the spec folders, `.l4/` and `.l4-out/`; merges of the base left out), is a CI
failure the gates here do not reproduce: another fix unit would hand off the same code. Pure but for `git` reads: the
decision comes from the ledger and git, so a resumed round decides the same way.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from l4.config.schema import L4Config
from l4.evidence.scope import file_kind
from l4.forge.logexcerpt import ranked_summary_lines
from l4.state.ledger import LedgerEvent
from l4.vcs.git import Git
from l4.verifier.types import finding_id

MAX_NOTES_CHARS = 300
MAX_FAILING_CHARS = 300
_PUT_BACK_EVENTS = ("guard.test_tamper", "guard.violation")


@dataclass(frozen=True)
class CiHistory:
    """One job of the last `repository_ci_failed` edge E (head `head`) and what the unit's earlier edges say of it.

    `again_head`: the head of the newest earlier edge that lists the job (a verdict, retry or resume between the two
    does not matter), else None. `again_changed`: the project files changed from there to `head` (None when that head
    is no ancestor: the rule does not apply). `unfixed`: it failed again and nothing changed. `put_back`: the test and
    support files the fix steps put back between the two edges. `notes`: the last fix chore's notes for this job.
    `failed_step` and `failing`: E's failing step and its failing lines, for the escalation's text."""

    job: str
    head: str
    again_head: str | None
    again_changed: int | None
    unfixed: bool
    put_back: tuple[str, ...]
    notes: str | None
    failed_step: str | None
    failing: str


def _order(events: Sequence[LedgerEvent]) -> list[LedgerEvent]:
    return sorted(events, key=lambda e: (e.ts, e.run_id, e.seq))


def project_changes(git: Git, since: str, head: str, unit_dir: str, cfg: L4Config) -> tuple[str, ...] | None:
    """The project files that the commits of `git log --first-parent --no-merges <since>..<head>` changed, sorted. A
    merge of the base is no fix: what it brings in is not the unit's. None when `since` is not an ancestor of `head`
    (history rewritten, or a commit that is not here): the rule does not apply."""
    if git.run("merge-base", "--is-ancestor", since, head, check=False).returncode != 0:
        return None
    listed = git.run(
        "log", "--first-parent", "--no-merges", "--name-only", "--format=", f"{since}..{head}", check=False
    ).stdout
    paths = {line.strip() for line in listed.splitlines() if line.strip()}
    return tuple(sorted(p for p in paths if file_kind(p, unit_dir, cfg) != "exempt"))


def _jobs(edge: LedgerEvent) -> list[dict]:
    return [j for j in edge.data.get("jobs") or [] if isinstance(j, dict) and j.get("name")]


def _failing(tail: str) -> str:
    text = " | ".join(" ".join(line.split()) for line in ranked_summary_lines(tail.splitlines()))
    return text if len(text) <= MAX_FAILING_CHARS else text[: MAX_FAILING_CHARS - 3] + "..."


def _put_back(events: Sequence[LedgerEvent], after: int, before: int) -> tuple[str, ...]:
    paths = {
        str(e.data["path"])
        for e in events[after + 1 : before]
        if e.type in _PUT_BACK_EVENTS and e.data.get("phase") == "single" and isinstance(e.data.get("path"), str)
    }
    return tuple(sorted(paths))


def _notes(events: Sequence[LedgerEvent], after: int, before: int, job: str) -> str | None:
    """The notes of the last fix chore that answered the job's finding between the two edges."""
    wanted = finding_id(f"repository CI failed: {job}")
    found: str | None = None
    window = events[after + 1 : before]
    for index, event in enumerate(window):
        if event.type != "task.tdd_exempt" or wanted not in (event.data.get("findings") or []):
            continue
        task = event.data.get("task")
        for later in window[index + 1 :]:
            if later.type == "task.done" and later.data.get("task") == task:
                notes = later.data.get("notes")
                found = " ".join(notes.split())[:MAX_NOTES_CHARS] if isinstance(notes, str) and notes.strip() else found
                break
    return found


def ci_history(events: Sequence[LedgerEvent], git: Git, unit_dir: str, cfg: L4Config) -> dict[str, CiHistory]:
    """Per job of the last `repository_ci_failed` edge: see `CiHistory`. `unit_dir` is the unit's folder relative to
    the repository. Empty when the unit has no such edge."""
    ordered = _order(events)
    edges = [
        i
        for i, e in enumerate(ordered)
        if e.type == "phase.changed" and e.data.get("trigger") == "repository_ci_failed"
    ]
    if not edges:
        return {}
    last = edges[-1]
    head = str(ordered[last].data.get("head") or "")
    found: dict[str, CiHistory] = {}
    for job in _jobs(ordered[last]):
        name = str(job["name"])
        earlier = next(
            (i for i in reversed(edges[:-1]) if any(str(j["name"]) == name for j in _jobs(ordered[i]))), None
        )
        again_head: str | None = None
        changed: int | None = None
        put_back: tuple[str, ...] = ()
        notes: str | None = None
        if earlier is not None:
            again_head = str(ordered[earlier].data.get("head") or "") or None
            if again_head and head:
                paths = project_changes(git, again_head, head, unit_dir, cfg)
                changed = len(paths) if paths is not None else None
            put_back = _put_back(ordered, earlier, last)
            notes = _notes(ordered, earlier, last, name)
        step = job.get("failed_step")
        found[name] = CiHistory(
            job=name,
            head=head,
            again_head=again_head,
            again_changed=changed,
            unfixed=again_head is not None and changed == 0,
            put_back=put_back,
            notes=notes,
            failed_step=step if isinstance(step, str) and step.strip() else None,
            failing=_failing(str(job.get("tail") or "")),
        )
    return found
