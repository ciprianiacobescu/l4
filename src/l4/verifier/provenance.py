"""Who wrote a fix unit: only the harness's own commits may introduce or change `<changes>/<parent>-fix-<n>/`.

An agent that plants a fix folder (with a `.l4/fix.json` marker) would otherwise get its tasks run TDD-exempt. Agent
steps cannot write there (the family namespace is protected) and cannot commit; this is the second line: a marker is
trusted only when the commit that introduced it is the harness's `docs(<parent>): fix unit <n> [skip ci]` commit
(author = the bot identity, an `L4-Run` trailer), and the marker has not changed since.
"""

from pathlib import PurePosixPath

from l4.implementer.workbench import clip_subject
from l4.vcs.authorship import commit_records, is_harness
from l4.vcs.git import Git


def introduction_problem(git: Git, fix_rel: str, parent_name: str, ordinal: int) -> str | None:
    """Why the fix unit at `fix_rel` (repository-relative) cannot be trusted, or None when the harness introduced it."""
    marker = str(PurePosixPath(fix_rel) / ".l4" / "fix.json")
    spec = f":(literal){marker}"
    added = commit_records(git, "--diff-filter=A", "--reverse", "HEAD", "--", spec)
    if not added:
        return "its marker is not committed on this branch"
    first = added[0]
    if not is_harness(first):
        return f"its marker was introduced by commit {first[0][:10]}, which is not a harness commit"
    expected = clip_subject(f"docs({parent_name}): fix unit {ordinal} [skip ci]")
    if first[3] != expected:
        return f"its marker was introduced by commit {first[0][:10]} with subject {first[3]!r}, not {expected!r}"
    before = git.run("rev-parse", f"{first[0]}:{marker}", check=False).stdout.strip()
    now = git.run("rev-parse", f"HEAD:{marker}", check=False).stdout.strip()
    if not before or before != now:
        return "its marker changed after the harness wrote it"
    return None


def foreign_commits(git: Git, base: str, head: str, rel_dir: str) -> list[str]:
    """Commits in `base..head` that touch `rel_dir` and are not the harness's (bot author, `L4-Run` trailer). The
    fix unit's `questions.md` is where a human answers, so a human commit that touches only it is not foreign."""
    answers = f":(exclude,literal){PurePosixPath(rel_dir) / 'questions.md'}"
    return [
        r[0] for r in commit_records(git, f"{base}..{head}", "--", f":(literal){rel_dir}", answers) if not is_harness(r)
    ]


def foreign_memory_commits(git: Git, base: str, head: str, rel_dir: str) -> list[str]:
    """Commits in `base..head` that touch the harness's memory directory and are not its `L4-Phase: lessons` commits:
    what an agent planted there is a model's text, which may only reach a lesson through the inbox (L4-MEM-002)."""
    return [
        r[0]
        for r in commit_records(git, f"{base}..{head}", "--", f":(literal){rel_dir}")
        if not (is_harness(r) and len(r) > 5 and r[5].strip() == "lessons")
    ]
