"""A spec edit reopens the Kiro tasks that cite a changed criterion (L4-OPS-015, design D14).

`reopen_for_changed_requirements` compares the acceptance criteria of `requirements.md` at the harness's last commit
with the worktree's (whitespace normalised, by number: `l4.specs.criteria.changed_requirements`), sets the done tasks
that cite a changed number back to `[ ]` with their parents (`KiroProvider.reopen`), records `tasks.reopened{tasks,
requirements, stale_criteria, changes}` first (a kill after the commit cannot lose the record) and commits tasks.md and
the run's ledger in one harness commit `chore(<name>): reopen tasks <keys> for changed requirements <ids> [skip ci]`.
An OpenSpec unit reopens nothing: its changed scenarios are judged by the verifier.

`stale_criteria` are the ids the changed criteria had in the old text (`kiro_requirement_ids`, the id function of the
traces) that no criterion of the new text has: a test that traces one was written for the old text and may be replaced
by the reopened task's red step (`pending_stale`, design D14 "Stale tests"). `changes` carries each one's old and new
text for the red prompt.
"""

import logging
from collections.abc import Sequence
from typing import Any

from l4.services import Services
from l4.specs.base import Framework
from l4.specs.criteria import changed_requirements, kiro_requirement_ids, kiro_requirement_texts
from l4.state.ledger import LedgerEvent, ledger_path
from l4.vcs.trailers import CommitTrailers

log = logging.getLogger("l4.reopen")
MAX_TEXT = 400  # characters of a criterion's old or new text in the event (and so in the prompt)


def stale_changes(
    unit_name: str, before: str | None, after: str | None, changed: Sequence[str]
) -> list[dict[str, Any]]:
    """One entry per changed criterion that had an id in the old text which the new text no longer has (L4-OPS-015):
    `{requirement, old_id, old_text, new_id, new_text}`, `new_id` and `new_text` None when the criterion was removed.
    An id the new text still has (two criteria swapped places) is not stale: its tests still trace a criterion."""
    old_ids, new_ids = kiro_requirement_ids(unit_name, before), kiro_requirement_ids(unit_name, after)
    old_text, new_text = kiro_requirement_texts(before), kiro_requirement_texts(after)
    current = set(new_ids.values())
    return [
        {
            "requirement": label, "old_id": old_ids[label], "old_text": old_text[label][:MAX_TEXT],
            "new_id": new_ids.get(label), "new_text": new_text[label][:MAX_TEXT] if label in new_text else None,
        }
        for label in changed
        if label in old_ids and old_ids[label] not in current
    ]  # fmt: skip


def is_reopened(events: Sequence[LedgerEvent], task: str) -> bool:
    """Whether `tasks.reopened` names `task` and no `task.done` of it has followed (a fix unit's events are another
    unit's): the task is back in its red step for an edited spec (L4-OPS-015)."""
    reopened = False
    for event in events:
        if event.data.get("fix_unit"):
            continue
        if event.type == "tasks.reopened" and task in (event.data.get("tasks") or []):
            reopened = True
        elif event.type == "task.done" and event.data.get("task") == task:
            reopened = False
    return reopened


def pending_stale(events: Sequence[LedgerEvent], task: str) -> list[dict[str, Any]]:
    """The stale-criterion entries (`stale_changes`) the ledger holds for `task`: every `tasks.reopened` that names
    it, until a `task.done` of it (a fix unit's events are another unit's). The reopened task keeps them while it is
    open, so a second attempt, a resumed run and a second reopening see the same set."""
    pending: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.data.get("fix_unit"):
            continue
        if event.type == "tasks.reopened" and task in (event.data.get("tasks") or []):
            for entry in event.data.get("changes") or []:
                if isinstance(entry, dict) and isinstance(entry.get("old_id"), str):
                    pending[entry["old_id"]] = entry
        elif event.type == "task.done" and event.data.get("task") == task:
            pending.clear()
    return list(pending.values())


def reopen_for_changed_requirements(services: Services, base: str, *, phase: str, iteration: int) -> list[str]:
    """The keys of the tasks reopened (none for an OpenSpec unit, for a criterion nobody cites, or when only the
    layout of the text changed). `base` is the harness's last commit."""
    s = services
    if s.ref.framework is not Framework.KIRO or not hasattr(s.provider, "reopen"):
        return []
    root = s.worktree.resolve()
    unit_rel = s.ref.path.resolve().relative_to(root).as_posix()
    shown = s.git.run("show", f"{base}:{unit_rel}/requirements.md", check=False)
    before = shown.stdout if shown.returncode == 0 else None
    file = s.ref.path / "requirements.md"
    after = file.read_text(encoding="utf-8", errors="replace") if file.is_file() else None
    changed = changed_requirements(before, after)
    if not changed:
        return []
    keys = s.provider.reopen(s.ref, changed)  # type: ignore[attr-defined]
    if not keys:
        return []
    stale = stale_changes(s.ref.path.name, before, after, changed)
    s.ledger.append(
        "tasks.reopened", tasks=keys, requirements=list(changed),
        stale_criteria=[c["old_id"] for c in stale], changes=stale,
    )  # fmt: skip
    paths = [s.ref.path / "tasks.md", ledger_path(s.ref.path, s.app.run_id)]
    s.git.run("add", "--", *(p.resolve().relative_to(root).as_posix() for p in paths if p.exists()))
    trailers = CommitTrailers(unit=s.ref.id, run_id=s.app.run_id, iteration=max(iteration, 1), phase=phase)
    what = f"reopen tasks {', '.join(keys)} for changed requirements {', '.join(changed)}"
    subject = f"chore({s.ref.name}): {what} [skip ci]"
    s.git.commit(subject, trailers)
    log.info("%s: reopened %s for changed requirements %s", s.ref.id, ", ".join(keys), ", ".join(changed))
    return keys
