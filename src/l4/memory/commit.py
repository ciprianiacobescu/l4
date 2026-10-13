"""Memory changes are their own commit (SPEC L4-MEM-005): `chore(memory): <detail> [skip ci]` with `L4-Phase: lessons`,
so they are visible at the merge gate and the verifier's subject-sha rule can ignore them."""

from collections.abc import Sequence

from l4.implementer.workbench import clip_subject
from l4.vcs.git import BOT_IDENTITY, Git, Identity
from l4.vcs.trailers import CommitTrailers


def commit_memory_change(
    git: Git,
    paths: Sequence[str],
    *,
    unit: str,
    run_id: str,
    iteration: int,
    detail: str,
    identity: Identity = BOT_IDENTITY,
) -> str | None:
    """Stage `paths` and commit them; the new sha, or None when their bytes are unchanged. It refuses (ValueError,
    nothing committed) when anything else is already staged: the commit must hold the memory change and nothing more."""
    if not paths:
        return None
    git.run("add", "--", *paths)
    staged = git.run("diff", "--cached", "--name-only", "-z").stdout.split("\0")
    wanted = set(paths)
    extra = sorted(name for name in staged if name and name not in wanted)
    if extra:
        git.run("reset", "--quiet", "--", *paths)
        raise ValueError(f"other changes are staged, not committing the memory change: {', '.join(extra[:5])}")
    if not any(staged):
        return None
    trailers = CommitTrailers(unit=unit, run_id=run_id, iteration=iteration, phase="lessons")
    return git.commit(clip_subject(f"chore(memory): {detail} [skip ci]"), trailers, identity)
