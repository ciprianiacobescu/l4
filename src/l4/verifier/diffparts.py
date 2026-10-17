"""What the judge reads of a unit's diff (L4-VER-040 to L4-VER-043): the harness's bookkeeping, named once, and the
diff in parts."""

from collections.abc import Sequence

from l4.state.review import UNIT_CHANNELS

BOOKKEEPING_GLOBS = ("**/.l4/**", ".serena/memories/harness/**")


def bookkeeping_pathspecs(unit_dirs: Sequence[str]) -> list[str]:
    """`:(glob,exclude)` for each glob, then `:(literal,exclude)<d>/<name>` for each unit folder `d` of the family and
    each file name of `l4.state.review.UNIT_CHANNELS` (every name but `.l4`, which the first glob covers)."""
    names = [n for n in UNIT_CHANNELS if n != ".l4"]
    return [f":(glob,exclude){g}" for g in BOOKKEEPING_GLOBS] + [
        f":(literal,exclude){d}/{n}" for d in unit_dirs for n in names
    ]
