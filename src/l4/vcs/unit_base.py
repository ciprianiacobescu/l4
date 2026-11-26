"""Where a unit branch left the base branch, read the one way (L4-VER-096, L4-VER-009): the verifier's step 0
(`preconditions`), the red step (`discrimination.unit_base`) and the family's reading of a merged parent's criteria
(`fixloop.family_of`) all call this, so that the three never disagree about the commit a baseline is read at."""

from l4.vcs.git import Git


def merge_base_with_head(git: Git, base_sha: str, head: str = "HEAD") -> str | None:
    """The merge base of `base_sha` and `head`, or None when git cannot say."""
    done = git.run("merge-base", base_sha, head, check=False)
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else None


def unit_base_commit(git: Git, base_branch: str, head: str = "HEAD", *, local_fallback: bool = True) -> str | None:
    """The merge base of `refs/remotes/origin/<base_branch>` and `head`; with `local_fallback`, when that remote ref is
    not there or has no merge base, the one of the local `<base_branch>`. None when no ref gives one."""
    refs = [f"refs/remotes/origin/{base_branch}", *([base_branch] if local_fallback else [])]
    for ref in refs:
        sha = git.rev_parse(ref)
        if sha is None:
            continue
        if (found := merge_base_with_head(git, sha, head)) is not None:
            return found
    return None
