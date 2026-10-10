"""The forge's address in committed files (L4-OBS-002, M1.9 P5).

A merge request URL in a ledger line or in `verification.md` names the project owner's forge host, and committed
history cannot be taken back. With `observability.redact_forge_urls` (on by default) everything the harness commits
carries `<forge>` in place of `scheme://host[:port]` of the forge's hosts, and the harness rebuilds a link from the
run's own environment when it needs one: the console trace, the JSONL mirror in `.l4-out/logs`, `outcome.json` and
`l4 status` show the real address. Comparisons between a recorded URL and a live one use `canonical`, so a ledger that
holds the old full form and one that holds the placeholder match the same merge request. Past commits are not rewritten.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from l4.config.schema import L4Config
from l4.exitcodes import L4Exit
from l4.forge.base import GITHUB_HOSTS, parse_remote_url
from l4.vcs.git import Git

if TYPE_CHECKING:
    from l4.context import AppContext

PLACEHOLDER = "<forge>"
_AFTER_PLACEHOLDER = r"(?![A-Za-z0-9_-]|\.[A-Za-z0-9])"  # the placeholder ends where a host name would not go on
_ORIGIN_VARIABLES = ("CI_SERVER_URL", "CI_API_V4_URL", "GITHUB_SERVER_URL", "GITHUB_API_URL")


def _origin(url: str | None) -> str | None:
    """`scheme://host[:port]` of an http(s) URL, without userinfo; None for anything else."""
    parts = urlsplit((url or "").strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{parts.hostname.lower()}{port}"


@dataclass(frozen=True)
class ForgeUrls:
    hosts: frozenset[str]  # `scheme://host[:port]` of every address that is the forge's
    web_base: str | None  # what `<forge>` stands for when a link is rebuilt; None when it is not known

    def scrub(self, text: str) -> str:
        """`text` with every forge origin replaced by the placeholder (a longer origin first). The scheme may be
        http or https, and credentials before the host (`https://__token__:****@host`, as pip and git print a
        link) go with it: a job log's tail is committed too."""
        for origin in sorted(self.hosts, key=len, reverse=True):
            parts = urlsplit(origin)
            port = f":{parts.port}" if parts.port else ""
            host = re.escape(f"{parts.hostname}{port}")
            text = re.sub(rf"https?://(?:[^\s/?#@]+@)?{host}{_AFTER_PLACEHOLDER}", PLACEHOLDER, text, flags=re.I)
        return text

    def expand(self, text: str) -> str:
        """The placeholder replaced by the web base, when it is known."""
        if self.web_base is None:
            return text
        return re.sub(re.escape(PLACEHOLDER) + r"(?![A-Za-z0-9_.-])", lambda _: self.web_base or "", text)

    def canonical(self, url: str) -> str:
        """One form for the old full URL and the placeholder form of the same address."""
        return self.scrub(url)


def _hosts(origins: Iterable[str | None]) -> frozenset[str]:
    return frozenset(o for o in origins if o)


def forge_urls(cfg: L4Config, environ: Mapping[str, str], origin_url: str | None = None) -> ForgeUrls:
    """The forge's hosts from the CI variables, `forge.gitlab.api_url` and the `origin` remote. Switched off with
    `observability.redact_forge_urls: false`: no host, so nothing is scrubbed."""
    if not cfg.observability.redact_forge_urls:
        return ForgeUrls(frozenset(), None)
    candidates = [_origin(environ.get(name)) for name in _ORIGIN_VARIABLES]
    candidates.append(_origin(cfg.forge.gitlab.api_url))
    remote = _origin(origin_url)
    if remote is None and (parsed := parse_remote_url(origin_url or "")) is not None:
        remote = f"https://{parsed.host}"  # an ssh or scp-style remote: its web address is https on the same host
    candidates.append(remote)
    web = (
        _origin(environ.get("CI_SERVER_URL")) or _origin(environ.get("GITHUB_SERVER_URL"))
        or _origin(cfg.forge.gitlab.api_url) or _origin(environ.get("CI_API_V4_URL")) or remote
    )  # fmt: skip
    if web is not None and urlsplit(web).hostname == "api.github.com":
        web = "https://github.com"  # the API host of github.com is not where its pages are
    github_api = _origin(environ.get("GITHUB_API_URL"))
    if web is None and github_api is not None:
        web = "https://github.com" if urlsplit(github_api).hostname == "api.github.com" else github_api
    if remote is not None and urlsplit(remote).hostname in GITHUB_HOSTS:
        web = web or "https://github.com"
    return ForgeUrls(_hosts(candidates), web)


def origin_url(repo: Path, environ: Mapping[str, str]) -> str | None:
    """The `origin` remote's URL of `repo`, or None (no remote, no git)."""
    try:
        done = Git(repo, environ=environ).run("config", "--get", "remote.origin.url", check=False)
    except (L4Exit, OSError):
        return None
    return done.stdout.strip() or None


def app_forge_urls(app: "AppContext", cfg: L4Config) -> ForgeUrls:
    """The forge's addresses for this run, built once and kept on the run's redactor (every sink already holds it)."""
    held = app.redactor.forge_urls
    if held is None:
        held = app.redactor.forge_urls = forge_urls(cfg, app.environ, origin_url(app.repo, app.environ))
    return held  # type: ignore[no-any-return]
