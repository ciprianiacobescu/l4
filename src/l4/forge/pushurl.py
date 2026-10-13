"""Where the harness pushes (SPEC 16.3), and the runner rule that makes the origin URL the wrong place.

gitlab-runner (shell executor) includes `<CI_PROJECT_DIR>.tmp/.gitlab-runner.ext.conf` from the checkout's
`.git/config`.
That file holds `url.https://gitlab-ci-token:<JOB_TOKEN>@<host>.insteadOf = https://<host>`, so every URL that
starts with `https://<host>` carries the JOB token, which git prefers over any credential helper. The job token
cannot push (live job 5420: "You are not allowed to push code to this project"). A push URL with a user name,
`https://oauth2@<host>/<project>.git`, does not start with that prefix, so it is never rewritten and the helper
(password from `L4_FORGE_TOKEN`) is asked. The URL carries no secret; it is passed per command as
`-c remote.origin.pushurl=...`, so pushing to `origin` keeps `refs/remotes/origin/*` current and nothing reaches
`.git/config`.
"""

from collections.abc import Mapping
from pathlib import Path
from urllib.parse import quote, urlsplit

from l4.config.schema import L4Config

PUSH_USER = "oauth2"
RUNNER_EXT_CONF = ".gitlab-runner.ext.conf"
_API_SUFFIX = "/api/v4"


def _project_segments(project: str) -> list[str] | None:
    segments = project.strip().strip("/").removesuffix(".git").split("/")
    if not all(segments) or any(s in (".", "..") or any(c in s for c in "?#\\@:") for s in segments):
        return None
    return segments


def _build(server: str, project: str) -> str | None:
    parts = urlsplit(server.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.query or parts.fragment:
        return None
    segments = _project_segments(project)
    if segments is None or not any(c.isalpha() for c in project):  # a bare numeric id is not a path
        return None
    host = parts.netloc.rpartition("@")[2]  # userinfo of the server URL is never carried over
    root = parts.path.rstrip("/")
    return f"{parts.scheme}://{PUSH_USER}@{host}{root}/{'/'.join(quote(s, safe='') for s in segments)}.git"


def push_url(cfg: L4Config, environ: Mapping[str, str]) -> str | None:
    """`https://oauth2@<host>[:port][/root]/<group>/<project>.git`, or None when the project's path is unknown.

    In CI: `CI_SERVER_URL` + `CI_PROJECT_PATH`; a gap there, and every run outside CI, falls back to
    `forge.gitlab.api_url` (without its `/api/v4`) + `forge.gitlab.project` (a numeric id has no path: None)."""
    if environ.get("GITLAB_CI") == "true" and environ.get("CI_SERVER_URL") and environ.get("CI_PROJECT_PATH"):
        return _build(environ["CI_SERVER_URL"], environ["CI_PROJECT_PATH"])
    api, project = cfg.forge.gitlab.api_url, cfg.forge.gitlab.project
    if not api or not project:
        return None
    base = api.strip().rstrip("/")
    return _build(base.removesuffix(_API_SUFFIX), project)


def runner_ext_conf(environ: Mapping[str, str]) -> Path | None:
    project_dir = environ.get("CI_PROJECT_DIR")
    if environ.get("GITLAB_CI") != "true" or not project_dir:
        return None
    return Path(f"{project_dir.rstrip('/')}.tmp") / RUNNER_EXT_CONF


def runner_rewrites_urls(environ: Mapping[str, str]) -> bool:
    """True when the runner's include file exists and holds an `insteadOf` rule. Only the fact is returned: the
    file's lines carry the job token and are never put in a message."""
    path = runner_ext_conf(environ)
    try:
        return path is not None and any("insteadof" in line.lower() for line in path.read_text("utf-8").splitlines())
    except OSError:
        return False
