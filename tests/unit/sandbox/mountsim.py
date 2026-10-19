"""A model of what a bwrap argv shows at a path, for tests that have no bwrap: the mounts apply in argv order, a
`--tmpfs X` hides X's whole subtree, a bind of a real source onto D shows D's subtree again, `--ro-bind /dev/null F`
hides the file F, and the last mount that covers a path decides (the same rule bwrap applies)."""

from collections.abc import Sequence
from pathlib import Path

TWO = {"--bind", "--ro-bind", "--ro-bind-try", "--setenv"}
ONE = {"--tmpfs", "--dev", "--proc", "--chdir"}


def _covers(dst: str, path: str) -> bool:
    return path == dst or path.startswith(dst.rstrip("/") + "/")


def mounts(argv: Sequence[str]) -> list[tuple[str, str, str | None]]:
    """(flag, destination, source) of every mount flag before `--clearenv`."""
    out: list[tuple[str, str, str | None]] = []
    i = 1
    while i < len(argv) and argv[i] != "--clearenv":
        flag = argv[i]
        if flag in TWO:
            out.append((flag, argv[i + 2], argv[i + 1]))
            i += 3
        elif flag in ONE:
            out.append((flag, argv[i + 1], None))
            i += 2
        else:
            i += 1
    return out


def visible(argv: Sequence[str], path: Path | str) -> bool:
    """Whether the host file at `path` can be read inside the sandbox."""
    target = str(path)
    state = False
    for flag, dst, src in mounts(argv):
        if not _covers(dst, target):
            continue
        if flag == "--tmpfs":
            state = False
        elif flag in {"--bind", "--ro-bind", "--ro-bind-try"}:
            state = src != "/dev/null"
    return state
