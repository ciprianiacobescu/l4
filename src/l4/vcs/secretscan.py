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
    path: str | None = None
    for line in out.splitlines():
        if line.startswith("+++ "):
            match = _FILE.match(line)
            path = match.group(1) if match and match.group(1) is not None else None
        elif line.startswith("+") and path is not None:
            added.setdefault(path, []).append(line[1:])
    hits: list[SecretHit] = []
    for name, lines in added.items():
        for kind in dict.fromkeys(redactor.kinds_in("\n".join(lines))):
            hits.append(SecretHit(name, kind))
    return hits


class SecretInPush(Exception):
    """The outgoing commits hold a secret: nothing is pushed. `reason` names paths and kinds, never a value."""

    def __init__(self, hits: Sequence[SecretHit]) -> None:
        self.hits = list(hits)
        shown = ", ".join(f"{h.path} ({h.kind})" for h in self.hits[:MAX_NAMED])
        more = f" (+{len(self.hits) - MAX_NAMED} more)" if len(self.hits) > MAX_NAMED else ""
        self.reason = f"secret in the outgoing commits, push blocked: {shown}{more}"
        super().__init__(self.reason)


MAX_NAMED = 3
