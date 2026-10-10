"""Which harness commit is running. `l4 init --vendor` writes `l4/_commit.py` into the vendored copy; a checkout or an
installed wheel has none, so the commit is unknown (None) there."""

from importlib import import_module


def harness_commit() -> str | None:
    try:
        commit = import_module("l4._commit").COMMIT
    except (ImportError, AttributeError):
        return None
    return commit if isinstance(commit, str) else None
