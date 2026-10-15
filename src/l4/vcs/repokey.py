"""The repository key (SPEC L4-WTR-001, L4-LCK-001, L4-CFG-005): one short name for one project on a runner.

Worktrees and lock files live under `$L4_CACHE/<kind>/<key>/...`, so two projects that share a change name on one runner
never meet at a path, while the jobs of one project (whose build directories differ) share both. The key therefore
comes from the project's `origin` URL, never from a local path.
"""

import hashlib
import re
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

from l4.vcs.errors import GitError
from l4.vcs.git import Git

_SCP = re.compile(r"^(?:[^@/\s]+@)?(?P<host>[^:/\s]+):(?P<path>(?!//).*)$")
_SLUG_MAX = 24
_HASH_LEN = 10


def normalize_remote(url: str, *, base: Path | None = None) -> str:
    """`<host>/<path>` of a remote URL: userinfo and port, the scheme, a trailing `/` and `.git` removed, the host
    lowercased. `https://tok:X@h/g/p.git`, `git@h:g/p.git` and `https://h/g/p` are all `h/g/p`. A local path (no
    host) is its absolute path without the leading `/`, relative ones resolved against `base`."""
    text = url.strip()
    if "://" in text:
        parts = urlsplit(text)
        host, path = (parts.hostname or "").lower(), parts.path
    elif (scp := _SCP.match(text)) is not None and not text.startswith(("/", ".")):
        host, path = scp.group("host").lower(), scp.group("path")
    else:
        host, path = "", text
        if base is not None and not Path(text).is_absolute():
            path = str(base / text)
        path = str(Path(path).resolve()) if host == "" and base is not None else path
    path = path.strip("/")
    path = path.removesuffix(".git").strip("/")
    return f"{host}/{path}" if host else path


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:_SLUG_MAX].strip("-")
    return slug or "repo"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:_HASH_LEN]


def key_of_remote(url: str, *, base: Path | None = None) -> str:
    """`<slug of the last path segment>-<hash of host/path>`, e.g. `l4-yolo-dummy-3f9a1c2b0d`."""
    normal = normalize_remote(url, base=base)
    return f"{_slug(normal.rsplit('/', 1)[-1])}-{_digest(normal)}"


def key_of_common_dir(common: Path, environ: Mapping[str, str]) -> str:
    """The key of the repository whose git common dir is `common`: from its `origin` URL, else (no remote) from the
    resolved common dir itself. The config file is read directly, so this works for a dir that is not a checkout."""
    common = common.resolve()
    url = _origin_of(common, environ)
    if url:
        return key_of_remote(url, base=common.parent)
    home = common.parent if common.name == ".git" else common
    return f"{_slug(home.name.removesuffix('.git'))}-{_digest(str(common))}"


def _origin_of(common: Path, environ: Mapping[str, str]) -> str | None:
    config = common / "config"
    if not config.is_file():
        return None
    try:
        done = Git(common, environ=environ).run(
            "config", "--file", str(config), "--get", "remote.origin.url", check=False
        )
    except (GitError, OSError):
        return None
    return done.stdout.strip() or None


def repository_key(repo: Path, environ: Mapping[str, str]) -> str:
    """The key of the repository checked out at `repo` (any clone or worktree of it): stable across clones and build
    directories of one project, different between projects."""
    out = Git(repo, environ=environ).run("rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    return key_of_common_dir(Path(out), environ)
