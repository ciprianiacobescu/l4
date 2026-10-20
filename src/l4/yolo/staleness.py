"""Why a review no longer fits what `origin/<base>` holds, and what to run (yolo-guardrails D1, D2; L4-YOLO-068).

Pure functions and small git readers. A commit sha is shown as 7 characters, a digest as 8, a count with its noun, and
a list of paths as three at most and `and <k> more`. Nothing here decides whether a review is stale
(`commands._review_view` does); it names the causes once the view says `stale`.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from l4.config.schema import L4Config
from l4.vcs.git import Git
from l4.vcs.names import unit_branch
from l4.yolo.digest import MISSING, RevisionMissing, current_unit_ref, file_digests, plan_digest
from l4.yolo.model import Plan, PlanEvent, PlanState

MAX_NAMED = 3
SHA_CHARS = 7
DIGEST_SHOWN = 8


@dataclass(frozen=True)
class Divergence:
    head: str  # full sha of HEAD
    origin: str  # full sha of origin/<base>
    ahead: int  # commits on HEAD that origin/<base> lacks
    behind: int  # commits on origin/<base> that HEAD lacks
    paths: tuple[str, ...]  # of the asked paths: those that differ between origin/<base> and HEAD, in the asked order


def _s7(sha: str | None) -> str:
    return (sha or "")[:SHA_CHARS]


def _d8(digest: str | None) -> str:
    return digest if digest in (None, MISSING) else (digest or "")[:DIGEST_SHOWN]


def _commits(n: int) -> str:
    return f"{n} commit" if n == 1 else f"{n} commits"


def named(items: Sequence[str]) -> str:
    shown = ", ".join(items[:MAX_NAMED])
    return f"{shown} and {len(items) - MAX_NAMED} more" if len(items) > MAX_NAMED else shown


def _base(target_ref: str) -> str:
    return target_ref.removeprefix("refs/remotes/origin/")


def divergence(git: Git, target_ref: str, paths: Sequence[str] = ()) -> Divergence | None:
    """None when HEAD or `target_ref` does not resolve, or when they are the same commit."""
    head, origin = git.rev_parse("HEAD"), git.rev_parse(target_ref)
    if head is None or origin is None or head == origin:
        return None
    counted = git.run("rev-list", "--left-right", "--count", f"{target_ref}...HEAD", check=False)
    try:
        behind, ahead = (int(n) for n in counted.stdout.split())
    except ValueError:
        return None
    differ = tuple(
        p for p in paths if git.run("diff", "--name-only", target_ref, "HEAD", "--", p, check=False).stdout.strip()
    )
    return Divergence(head, origin, ahead, behind, differ)


def divergence_text(d: Divergence, base: str) -> str:
    if d.ahead and d.behind:
        text = (
            f"HEAD ({_s7(d.head)}) and origin/{base} ({_s7(d.origin)}) have diverged: {_commits(d.ahead)} only on "
            f"HEAD, {d.behind} only on origin/{base}"
        )
    elif d.ahead:
        text = f"origin/{base} ({_s7(d.origin)}) is {_commits(d.ahead)} behind HEAD ({_s7(d.head)})"
    else:
        text = f"origin/{base} ({_s7(d.origin)}) is {_commits(d.behind)} ahead of HEAD ({_s7(d.head)})"
    return f"{text}; they differ in {named(d.paths)}" if d.paths else text


def divergence_verb(d: Divergence) -> str:
    if d.ahead and d.behind:
        return "pull, then push"
    return "push" if d.ahead else "pull"


def divergence_fix(d: Divergence, base: str, then: str) -> str:
    if d.ahead and d.behind:
        return f"git pull --rebase, then git push origin HEAD:{base}, then {then}"
    if d.ahead:
        return f"git push origin HEAD:{base}, then {then}"
    return f"git pull --ff-only, then {then}"


def _is_commit(git: Git, rev: str) -> bool:
    return git.run("cat-file", "-e", f"{rev}^{{commit}}", check=False).returncode == 0


def changed_files(git: Git, old_rev: str | None, new_rev: str, folder: str) -> list[str] | None:
    """The files of `folder` added, removed or changed between two revisions, as the digest reads them (harness files
    left out, task marks read as `[ ]`): repository-relative, sorted. None when `old_rev` is unknown to this clone;
    [] when the folder is missing at one side."""
    if not old_rev or not _is_commit(git, old_rev):
        return None
    try:
        before, after = file_digests(git, old_rev, folder), file_digests(git, new_rev, folder)
    except RevisionMissing:  # a missing folder is a FolderMissing
        return []
    root = folder.strip("/")
    names = sorted(rel for rel in {*before, *after} if before.get(rel) != after.get(rel))
    return [f"{root}/{rel}" if root else rel for rel in names]


def _where(git: Git, cfg: L4Config, unit: str, target_ref: str) -> tuple[str, str]:
    """(`origin/<base>` or `its branch <branch>`, the sha that ref resolves to)."""
    try:
        ref = current_unit_ref(git, cfg, unit, target_ref)
    except RevisionMissing:
        ref = target_ref
    sha = _s7(git.rev_parse(ref))
    if ref == target_ref:
        return f"origin/{_base(target_ref)}", sha
    return f"its branch {unit_branch(unit, cfg.forge.branch_prefix)}", sha


def unit_change(
    git: Git,
    cfg: L4Config,
    unit: str,
    folder: str,
    old_digest: str,
    new_digest: str,
    old_rev: str | None,
    target_ref: str,
    label: str,
) -> str:
    where, sha = _where(git, cfg, unit, target_ref)
    if new_digest == MISSING:
        return f"spec digest {_d8(old_digest)} {label}; its folder {folder} has no files on {where} ({sha})"
    text = f"spec digest {_d8(old_digest)} {label}, {_d8(new_digest)} now on {where} ({sha})"
    try:
        new_rev = current_unit_ref(git, cfg, unit, target_ref)
    except RevisionMissing:
        new_rev = target_ref
    files = changed_files(git, old_rev, new_rev, folder)
    return f"{text}; changed: {named(files)}" if files else text


def plan_change(old_digest: str | None, new_digest: str, base: str, target_sha: str, label: str) -> str:
    return f"digest {_d8(old_digest)} {label}, {_d8(new_digest)} now on origin/{base} ({_s7(target_sha)})"


def _latest_reviewed(events: Sequence[PlanEvent]) -> dict[str, Any]:
    return next((e.data for e in reversed(events) if e.type == "plan.reviewed"), {})


def unit_revs(
    git: Git, cfg: L4Config, unit_ids: Iterable[str], target_ref: str, folders: Mapping[str, str] | None = None
) -> dict[str, str]:
    """`{unit: full sha}` of the revision each unit's folder is read on now (D2). With `folders`, only the units that
    have one."""
    out: dict[str, str] = {}
    for unit in unit_ids:
        if folders is not None and unit not in folders:
            continue
        try:
            sha = git.rev_parse(current_unit_ref(git, cfg, unit, target_ref))
        except RevisionMissing:
            continue
        if sha:
            out[unit] = sha
    return out


def frozen_rev(events: Sequence[PlanEvent], unit: str, digest: str) -> str | None:
    """`unit_revs[unit]` of the latest `plan.reviewed` whose `units[unit].digest` is `digest`, else None."""
    for event in reversed(events):
        if event.type != "plan.reviewed":
            continue
        entry = (event.data.get("units") or {}).get(unit) or {}
        if entry.get("digest") == digest:
            return (event.data.get("unit_revs") or {}).get(unit)
    return None


def stale_reasons(
    git: Git,
    cfg: L4Config,
    plan: Plan,
    plan_text: str,
    plan_path: str,
    state: PlanState,
    events: Sequence[PlanEvent],
    now: Mapping[str, str],
    target_ref: str,
    folders: Mapping[str, str],
    *,
    prompt_matters: bool = True,
) -> list[str]:
    """One line per cause, in the order of D1; [] for a current review. `now` is the digest of each unit now."""
    from l4.yolo.readiness import PROMPT_VERSION  # late: the readiness module is heavy

    base = _base(target_ref)
    target_sha = git.rev_parse(target_ref) or ""
    lines: list[str] = []
    if prompt_matters and state.review_prompt_version != PROMPT_VERSION:
        lines.append(
            f"review prompt {state.review_prompt_version} at the review, {PROMPT_VERSION} in this harness: every "
            f"subject is judged again"
        )
    current = plan_digest(plan_text)
    if state.review_plan_digest != current:
        lines.append(
            f"plan file {plan_path}: "
            f"{plan_change(state.review_plan_digest, current, base, target_sha, 'at the review')}"
        )
    revs = _latest_reviewed(events).get("unit_revs") or {}
    for unit in plan.unit_ids():
        if state.review_digests.get(unit) == now.get(unit):
            continue
        old = state.review_digests.get(unit)
        if old is None:
            lines.append(f"{unit}: not judged by the review")
            continue
        new = now.get(unit, MISSING)
        change = unit_change(
            git, cfg, unit, folders.get(unit, ""), old, new, revs.get(unit), target_ref, "at the review"
        )
        lines.append(f"{unit}: {change}")
    for batch in plan.batches:
        if len(batch.units) > 1 and f"batch:{batch.id}" not in state.review:
            lines.append(f"batch:{batch.id}: not judged by the review")
    paths = [plan_path, *(f for u in plan.unit_ids() if (f := folders.get(u)))]
    d = divergence(git, target_ref, paths)
    if d is not None and d.ahead > 0 and d.paths:
        lines.append(f"local: {divergence_text(d, base)}: {divergence_verb(d)}, then review")
    return lines


__all__ = [
    "Divergence", "changed_files", "named", "divergence", "divergence_fix", "divergence_text", "divergence_verb",
    "frozen_rev", "plan_change", "stale_reasons", "unit_change", "unit_revs",
]  # fmt: skip
