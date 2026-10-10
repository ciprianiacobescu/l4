"""Harness paths that the repository's own `.gitignore` swallows (M1.8 A5, L4-INS-002, L4-MEM-004).

`.serena/project.yml` and `.serena/memories/harness/lessons.md` are committed files: the first makes Serena leave the
project alone, the second is the lessons file every run reads and the verifier writes. A repository that ignores
`.serena/` (Serena's own cache lives there) would never commit either, so lessons would silently stay on one machine.
Git cannot re-include a file whose parent directory is excluded, so the carve-out replaces the directory rule by
contents rules. The answer comes from `git check-ignore`, never from reading `.gitignore` ourselves.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from l4.exitcodes import L4Exit
from l4.memory.serena import SEED_PROJECT_RELPATH
from l4.vcs.git import Git, GitError

LESSONS_RELPATH = ".serena/memories/harness/lessons.md"
HARNESS_PATHS = (SEED_PROJECT_RELPATH, LESSONS_RELPATH)
CARVE_OUT = (
    ".serena/*",
    "!.serena/project.yml",
    "!.serena/memories/",
    ".serena/memories/*",
    "!.serena/memories/harness/",
)


@dataclass(frozen=True)
class IgnoredPath:
    path: str
    source: str  # the ignore file that holds the rule, as git prints it
    line: int
    pattern: str


def ignored_harness_paths(repo: Path, environ: Mapping[str, str]) -> list[IgnoredPath]:
    """The harness paths git would ignore, with the rule that does it. Empty outside a repository or without git."""
    try:
        done = Git(repo, environ=environ).run("check-ignore", "-v", "--", *HARNESS_PATHS, check=False)
    except (L4Exit, GitError):
        return []
    found: list[IgnoredPath] = []
    for row in done.stdout.splitlines():
        rule, _, path = row.partition("\t")
        source, _, rest = rule.partition(":")
        number, _, pattern = rest.partition(":")
        if not path or pattern.startswith("!") or not number.isdigit():  # a `!` rule un-ignores: not a finding
            continue
        found.append(IgnoredPath(path, source, int(number), pattern))
    return found


def carve_out_text(ignored: list[IgnoredPath]) -> str:
    """What to tell the human: which rule ignores what, and the lines that replace it."""
    rules = sorted({(i.source, i.line, i.pattern) for i in ignored})
    where = "; ".join(f"`{pattern}` ({source}:{line})" for source, line, pattern in rules)
    paths = ", ".join(i.path for i in ignored)
    lines = "\n".join(f"  {line}" for line in CARVE_OUT)
    return (
        f"{paths} would be ignored by {where}, so the lessons and the Serena seed would never be committed.\n"
        f"Replace that rule in .gitignore with:\n{lines}"
    )


def apply_carve_out(gitignore: str, ignored: list[IgnoredPath]) -> str:
    """The `.gitignore` text with the ignoring rules (those of `.gitignore` itself) replaced by the carve-out. Used by
    tests to prove the printed lines work with real git; a rule in another file is left to the human."""
    rules = {(i.line, i.pattern) for i in ignored if i.source == ".gitignore"}
    out: list[str] = []
    done = False
    for number, row in enumerate(gitignore.splitlines(), start=1):
        if (number, row.strip()) in rules:
            if not done:
                out.extend(CARVE_OUT)
                done = True
            continue
        out.append(row)
    if not done:
        out.extend(CARVE_OUT)
    return "\n".join(out) + "\n"
