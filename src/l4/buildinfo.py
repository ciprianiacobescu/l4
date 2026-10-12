"""Which harness commit is running. In order: `l4 init --vendor` writes `l4/_commit.py` into the vendored copy; a
harness fetched at run time (`uvx --from git+URL@SHA`, L4-GHP-010) is installed with a `direct_url.json` whose
`vcs_info.commit_id` is that SHA; a checkout or a plain wheel has neither, so the commit is unknown (None) there."""

import json
import re
from importlib import import_module
from importlib.metadata import PackageNotFoundError, distribution

DISTRIBUTION = "l4harness"
_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


def _installed_commit() -> str | None:
    try:
        text = distribution(DISTRIBUTION).read_text("direct_url.json")
        info = json.loads(text) if text else None
    except (PackageNotFoundError, OSError, ValueError):
        return None
    vcs = info.get("vcs_info") if isinstance(info, dict) else None
    commit = vcs.get("commit_id") if isinstance(vcs, dict) else None
    return commit if isinstance(commit, str) and _FULL_SHA.match(commit) else None


def harness_commit() -> str | None:
    try:
        commit = import_module("l4._commit").COMMIT
    except (ImportError, AttributeError):
        return _installed_commit()
    return commit if isinstance(commit, str) else _installed_commit()


_GITHUB_REPO = re.compile(r"^(?:https://|ssh://git@|git@)github\.com[/:]([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?$")


def github_slug(url: str) -> str | None:
    """`owner/repo` of a github.com https or ssh URL (or the scp form), else None."""
    match = _GITHUB_REPO.match(url)
    return match.group(1) if match else None


def harness_origin() -> str | None:
    """`owner/repo` of the GitHub repository the running harness was installed from (`uv tool install git+URL`), or
    None: a checkout, a wheel or another host has no origin that a workflow's `uses:` could name."""
    try:
        text = distribution(DISTRIBUTION).read_text("direct_url.json")
        info = json.loads(text) if text else None
    except (PackageNotFoundError, OSError, ValueError):
        return None
    url = info.get("url") if isinstance(info, dict) and isinstance(info.get("vcs_info"), dict) else None
    return github_slug(url) if isinstance(url, str) else None
