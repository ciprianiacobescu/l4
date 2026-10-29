"""Paths named in free text: a token of a text that is a repository-relative path, and the ones a glob list matches
(L4-IMP-015, L4-DLG-023, L4-YOLO-092). Neutral: the delegate's reply check, the unfreeze rules and the intake of
forbidden paths all read text this way, and none of them may import another's package for it."""

import re
from collections.abc import Sequence

from l4.security.protected import glob_match


def names_path(text: str, path: str, *, dot_slash: bool = False) -> bool:
    """`path` as a token of `text`: a repository-relative path, optionally followed by `:<line>` (or a line range) or
    by sentence punctuation. A longer path (`x.pyc`, `x.py.bak`, `dir/x.py`) is another token. `dot_slash`: one `./`
    that starts the token may come before the path (`./x.py`); the `./` of `../x.py` does not."""
    if path not in text:
        return False
    lead = r"(?:\./)?" if dot_slash else ""
    pattern = rf"(?<![\w./-]){lead}{re.escape(path)}(?::\d+(?:[-:]\d+)?)?(?![\w/-]|\.\w)"
    return re.search(pattern, text) is not None


_PATH_TOKEN = re.compile(r"(?<![\w./-])[\w.][\w./-]*")


def named_paths(text: str, globs: Sequence[str]) -> list[str]:
    """The paths `text` names (a path as written, `names_path` of L4-IMP-015: "the conftest" alone names none) that one
    of `globs` matches, in the order they appear."""
    found: list[str] = []
    for token in _PATH_TOKEN.findall(text):
        path = token.rstrip(".,;:)").removeprefix("./")
        pathlike = "/" in path or "." in path.strip(".")
        hit = pathlike and any(glob_match(g, path) for g in globs) and names_path(text, path, dot_slash=True)
        if hit and path not in found:
            found.append(path)
    return found
