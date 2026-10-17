"""Pre-push secret scan (SPEC L4-SEC-007, HB-4): every commit about to leave the machine is read for secrets with the
harness's own redactor (the configured secret values and the token shapes of `l4.redact`), so a key an agent wrote
into a file never reaches the forge. No external scanner is needed (gitleaks is not on the runner). A hit names the
path and the kind, never the value. Limits: it is a verbatim, line-based safety net for accidental leaks; a secret split
across lines or files, encoded, or in a binary file is not caught."""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from l4.redact import Redactor
from l4.vcs.git import Git

_FILE = re.compile(r'^\+\+\+ (?:"?b/(.*?)"?|/dev/null)$')


@dataclass(frozen=True)
class SecretHit:
    path: str
    kind: str


def outgoing_secrets(git: Git, redactor: Redactor, *, exclude: Sequence[str], head: str = "HEAD") -> list[SecretHit]:
    """The secrets in the lines that commits `head` has and every ref in `exclude` has not. `exclude` are the remote
    refs the forge already holds (the unit branch and the base branch: what was merged in from the base is not ours);
    a ref that does not exist is skipped. Every outgoing commit is read, not only the net diff: a push sends the
    objects of a commit whose secret a later commit removed. Only added lines count."""
    known = [ref for ref in exclude if git.rev_parse(ref) is not None]
    out = git.run(
        "log", "-p", "-U0", "--no-merges", "--no-color", "--no-ext-diff", "--no-textconv", "--format=", head,
        *(f"^{ref}" for ref in known), "--",
    ).stdout  # fmt: skip
    added: dict[str, list[str]] = {}
    _collect_added(out, added)
    return _hits(redactor, added)


MAX_FILE_BYTES = 2_000_000  # a new file larger than this is not read by the step check (the push scan still is)


def worktree_secrets(git: Git, redactor: Redactor, paths: Sequence[str]) -> list[SecretHit]:
    """The secrets in the lines that the worktree adds to `HEAD` in `paths` (L4-SEC-008): the added lines of a tracked
    file (`git diff HEAD`), every line of a new one. An implementer step is checked so before any gate or commit, so a
    test fixture that spells a token whole fails the attempt with a retry instead of halting the unit at the push.
    A deleted file, a symlink, a directory, a binary file (a NUL byte) and a new file over `MAX_FILE_BYTES` add
    nothing."""
    added: dict[str, list[str]] = {}
    tracked = [p for p in paths if git.run("cat-file", "-e", f"HEAD:{p}", check=False).returncode == 0]
    if tracked:
        out = git.run(
            "diff", "-U0", "--no-color", "--no-ext-diff", "--no-textconv", "--no-renames", "HEAD", "--", *tracked,
            check=False,
        ).stdout  # fmt: skip
        _collect_added(out, added)
    for path in paths:
        target = git.repo / path
        if path in tracked or target.is_symlink() or not target.is_file() or target.stat().st_size > MAX_FILE_BYTES:
            continue
        data = target.read_bytes()
        if b"\0" not in data:
            added.setdefault(path, []).extend(data.decode("utf-8", errors="replace").splitlines())
    return _hits(redactor, {p: added[p] for p in paths if p in added})


def _collect_added(diff: str, added: dict[str, list[str]]) -> None:
    """The `+` lines of a `-U0` patch, by the path of their `+++ b/` header (none for a deleted file)."""
    path: str | None = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            match = _FILE.match(line)
            path = match.group(1) if match and match.group(1) is not None else None
        elif line.startswith("+") and path is not None:
            added.setdefault(path, []).append(line[1:])


def _hits(redactor: Redactor, added: dict[str, list[str]]) -> list[SecretHit]:
    hits: list[SecretHit] = []
    for name, lines in added.items():
        for kind in dict.fromkeys(redactor.kinds_in("\n".join(lines))):
            hits.append(SecretHit(name, kind))
    return hits


def step_secret_reason(hits: Sequence[SecretHit]) -> str:
    """Why an implementer attempt that wrote a token shape failed (L4-SEC-008): the paths and kinds, never a value,
    and how to write such a test value so that the next attempt passes."""
    shown = ", ".join(f"{h.path} ({h.kind})" for h in hits[:MAX_NAMED])
    more = f" (+{len(hits) - MAX_NAMED} more)" if len(hits) > MAX_NAMED else ""
    return (
        f"the change holds text shaped like a secret: {shown}{more}. Nothing of this attempt is kept. Never write a "
        "secret value. A test that needs a value shaped like a token builds it at run time from parts, with the prefix "
        'split (for example "mk_" + "agent_" + "A" * 24), so that no file holds the whole shape: the harness refuses '
        "to push one"
    )


class SecretInPush(Exception):
    """The outgoing commits hold a secret: nothing is pushed. `reason` names paths and kinds, never a value."""

    def __init__(self, hits: Sequence[SecretHit]) -> None:
        self.hits = list(hits)
        shown = ", ".join(f"{h.path} ({h.kind})" for h in self.hits[:MAX_NAMED])
        more = f" (+{len(self.hits) - MAX_NAMED} more)" if len(self.hits) > MAX_NAMED else ""
        self.reason = f"secret in the outgoing commits, push blocked: {shown}{more}"
        super().__init__(self.reason)


MAX_NAMED = 3
