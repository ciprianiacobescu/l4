"""A spec edit reopens the Kiro tasks that cite a changed criterion (L4-OPS-015, design D14).

`reopen_for_changed_requirements` compares the acceptance criteria of `requirements.md` at the harness's last commit
with the worktree's (whitespace normalised, by number: `l4.specs.criteria.changed_requirements`), sets the done tasks
that cite a changed number back to `[ ]` with their parents (`KiroProvider.reopen`), records `tasks.reopened{tasks,
requirements}` first (a kill after the commit cannot lose the record) and commits tasks.md and the run's ledger in one
harness commit `chore(<name>): reopen tasks <keys> for changed requirements <ids> [skip ci]`. An OpenSpec unit reopens
nothing: its changed scenarios are judged by the verifier.
"""

import logging

from l4.services import Services
from l4.specs.base import Framework
from l4.specs.criteria import changed_requirements
from l4.state.ledger import ledger_path
from l4.vcs.trailers import CommitTrailers

log = logging.getLogger("l4.reopen")


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
    s.ledger.append("tasks.reopened", tasks=keys, requirements=list(changed))
    paths = [s.ref.path / "tasks.md", ledger_path(s.ref.path, s.app.run_id)]
    s.git.run("add", "--", *(p.resolve().relative_to(root).as_posix() for p in paths if p.exists()))
    trailers = CommitTrailers(unit=s.ref.id, run_id=s.app.run_id, iteration=max(iteration, 1), phase=phase)
    what = f"reopen tasks {', '.join(keys)} for changed requirements {', '.join(changed)}"
    subject = f"chore({s.ref.name}): {what} [skip ci]"
    s.git.commit(subject, trailers)
    log.info("%s: reopened %s for changed requirements %s", s.ref.id, ", ".join(keys), ", ".join(changed))
    return keys
