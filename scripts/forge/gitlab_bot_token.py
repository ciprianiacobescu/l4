"""Create (or verify) the harness bot token of a GitLab project and store it as a masked CI/CD variable.

SUPERSEDED by `l4 setup gitlab` (M1.8): the same token and variable, plus the secrets, the schedule and the runner
check, idempotent, with `--rotate [--revoke-old]`. This script stays until that command has had live use.

The L4 harness pushes unit branches and opens merge requests with a *project access token* (GitLab 17.5 CE cannot
push with CI_JOB_TOKEN). This script makes that setup reproducible and idempotent:

  1. look for an active project access token with --name; create one if missing (or if --rotate);
  2. store its value in the project CI/CD variable --variable (masked, not protected, raw) scoped to the CI/CD
     environment --environment-scope (default "l4", the environment of the harness job in the CI template): a variable
     with scope "*" reaches every job of the project, the project's own `test` job included, and that job runs code
     the harness's agents wrote (docs/research/08, HB-2). A leftover unscoped variable of the same name is reported,
     never deleted: that is the maintainer's call;
  3. verify the new token by calling GET /projects/:id with it against --verify-base (the real GitLab API).

GitLab's variables API returns the VALUE next to the scope, so no check of the scope can be made without reading the
value; the doctor therefore has none (see docs/runner/README.md "CI/CD variable scope").

The token value is held in memory only: it goes from the create response straight into the variable request and the
verification call. It is never printed, logged or written to disk. Without --rotate an existing token is kept, and
the variable is only checked for presence.

Usage (stdlib only, Python >= 3.9):
  # direct, with a maintainer/owner token of your own in $GITLAB_TOKEN
  python3 scripts/forge/gitlab_bot_token.py --api-base https://gitlab.example.com/api/v4 \
      --auth-env GITLAB_TOKEN --auth-scheme private-token --project 118
  # through the Mintkey proxy (a brokered JWT in $MK_JWT): see scripts/forge/mk-gitlab-bot-token.sh
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

LEVELS = {"guest": 10, "reporter": 20, "developer": 30, "maintainer": 40}


class Api:
    def __init__(self, base: str, header: tuple[str, str]) -> None:
        self.base = base.rstrip("/")
        self.header = header

    def call(self, method: str, path: str, body: dict | None = None) -> object:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"{self.base}/{path}", data=data, method=method)
        req.add_header(*self.header)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:  # report status + message, never request headers
            detail = e.read().decode(errors="replace")[:300]
            raise SystemExit(f"{method} {path} -> HTTP {e.code}: {detail}") from None
        return json.loads(raw) if raw else None


def variable_path(pid: str, key: str, scope: str) -> str:
    """One variable of the project; the same key may exist once per environment scope, so the scope selects it."""
    return f"projects/{pid}/variables/{urllib.parse.quote(key, safe='')}?filter[environment_scope]={urllib.parse.quote(scope, safe='')}"


def has_variable(variables: list[dict], key: str, scope: str) -> bool:
    return any(v["key"] == key and v.get("environment_scope", "*") == scope for v in variables)


def unscoped_warning(variables: list[dict], key: str, scope: str) -> str | None:
    if scope != "*" and has_variable(variables, key, "*"):
        return (f"WARN an unscoped variable {key} (scope *) still exists: every job of the project can read it. "
                f"Delete it once the scoped one is verified (not deleted here)")
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api-base", required=True, help="GitLab API base (…/api/v4) or a proxy base in front of it")
    ap.add_argument("--auth-env", required=True, help="name of the env var holding the admin/maintainer credential")
    ap.add_argument("--auth-scheme", choices=["private-token", "bearer"], default="private-token")
    ap.add_argument("--verify-base", help="real GitLab API base used to verify the new token (default: --api-base)")
    ap.add_argument("--project", required=True, help="project id or URL-encoded path")
    ap.add_argument("--name", default="l4-bot")
    ap.add_argument("--scopes", default="api,write_repository")
    ap.add_argument("--access-level", default="developer", choices=sorted(LEVELS))
    ap.add_argument("--days", type=int, default=365, help="lifetime; GitLab caps it at 365 days by default")
    ap.add_argument("--variable", default="L4_FORGE_TOKEN")
    ap.add_argument("--environment-scope", default="l4",
                    help='CI/CD environment the variable is limited to (default "l4"); "*" makes it visible to every job')
    ap.add_argument("--rotate", action="store_true", help="revoke-free rotation: create a new token and overwrite the variable")
    a = ap.parse_args()

    cred = os.environ.get(a.auth_env)
    if not cred:
        raise SystemExit(f"env var {a.auth_env} is empty")
    header = ("PRIVATE-TOKEN", cred) if a.auth_scheme == "private-token" else ("Authorization", f"Bearer {cred}")
    api = Api(a.api_base, header)
    pid = urllib.parse.quote(str(a.project), safe="")

    tokens = api.call("GET", f"projects/{pid}/access_tokens")
    active = [t for t in tokens if t["name"] == a.name and t.get("active") and not t.get("revoked")]
    scope = a.environment_scope
    variables = api.call("GET", f"projects/{pid}/variables?per_page=100")  # the list carries values: never printed

    if active and has_variable(variables, a.variable, scope) and not a.rotate:
        t = active[0]
        v = next(v for v in variables if v["key"] == a.variable and v.get("environment_scope", "*") == scope)
        print(f"OK   token '{t['name']}' id={t['id']} scopes={t['scopes']} level={t['access_level']} "
              f"expires={t['expires_at']} (kept); variable {a.variable} present, environment scope {scope}, "
              f"masked={v['masked']} protected={v['protected']}")
        if warning := unscoped_warning(variables, a.variable, scope):
            print(warning)
        return 0

    expires = (dt.date.today() + dt.timedelta(days=a.days)).isoformat()
    created = api.call("POST", f"projects/{pid}/access_tokens", {
        "name": a.name, "scopes": a.scopes.split(","), "access_level": LEVELS[a.access_level],
        "expires_at": expires,
    })
    secret = created.pop("token")
    print(f"NEW  token '{created['name']}' id={created['id']} scopes={created['scopes']} "
          f"level={created['access_level']} expires={created['expires_at']} bot_user_id={created['user_id']}")

    body = {"value": secret, "masked": True, "protected": False, "raw": True, "environment_scope": scope,
            "description": f"L4 harness bot token ({a.name}), created {dt.date.today().isoformat()}"}
    if has_variable(variables, a.variable, scope):
        api.call("PUT", variable_path(pid, a.variable, scope), body)
        print(f"SET  variable {a.variable} updated (masked, not protected, raw, environment scope {scope})")
    else:
        api.call("POST", f"projects/{pid}/variables", {"key": a.variable, **body})
        print(f"SET  variable {a.variable} created (masked, not protected, raw, environment scope {scope})")
    if warning := unscoped_warning(variables, a.variable, scope):
        print(warning)

    verify = Api(a.verify_base or a.api_base, ("PRIVATE-TOKEN", secret))
    proj = verify.call("GET", f"projects/{pid}")
    del secret
    print(f"OK   new token can read project '{proj['path_with_namespace']}' as the bot user")
    return 0


if __name__ == "__main__":
    sys.exit(main())
