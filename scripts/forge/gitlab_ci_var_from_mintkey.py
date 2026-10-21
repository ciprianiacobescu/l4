"""Copy one of this agent's Mintkey secrets into a masked GitLab CI/CD variable, through the Mintkey GitLab proxy.
The value goes Mintkey → memory → GitLab and is never printed or written to disk.

SUPERSEDED by `l4 setup gitlab --secret NAME=ENVVAR` (M1.8; scripts/forge/mk-l4-setup-gitlab.sh does the Mintkey side with
`--mk-secret`). This script stays until that command has had live use.

    python3 scripts/forge/gitlab_ci_var_from_mintkey.py --secret typesafe-jev-api-key --project 118 --variable TYPESAFE_API_KEY

The variable is masked, not protected (harness jobs also run on l4/** branches), raw (no $ expansion) and scoped to the
CI/CD environment --environment-scope (default "l4", the environment of the harness job in the CI template): with scope
"*" the project's own jobs would receive it too (docs/research/08, HB-2). An existing variable of that name and scope
is updated in place; a leftover unscoped one is reported, never deleted. Exit 0 = set and verified present (by key,
not value).

Environment: MINTKEY_GITLAB_SLUG (the Mintkey GitLab service slug; --slug overrides it), MINTKEY_API.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dev"))
from mintkey_secret import _agent_key, secret_value  # noqa: E402

API = os.environ.get("MINTKEY_API", "http://localhost:8082")
PROXY = os.environ.get("MINTKEY_PROXY", "http://localhost:8000")


def _json(req: urllib.request.Request) -> object:
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{req.get_method()} {req.full_url.split('/v1/call/')[-1]} -> HTTP {e.code}: "
                         f"{e.read().decode(errors='replace')[:300]}") from None
    return json.loads(raw) if raw else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--secret", required=True)
    ap.add_argument("--project", required=True)
    ap.add_argument("--variable", required=True)
    ap.add_argument("--slug", default=os.environ.get("MINTKEY_GITLAB_SLUG", "example-gitlab"),
                    help="Mintkey GitLab service slug (default $MINTKEY_GITLAB_SLUG, else example-gitlab)")
    ap.add_argument("--environment-scope", default="l4",
                    help='CI/CD environment the variable is limited to (default "l4"); "*" makes it visible to every job')
    a = ap.parse_args()
    auth = {"Authorization": f"Bearer {_agent_key()}"}
    services = _json(urllib.request.Request(f"{API}/v1/tools/list_services", headers=auth))["services"]
    svc = next(s["id"] for s in services if s["slug"] == a.slug)
    tok = _json(urllib.request.Request(f"{API}/v1/tools/request_token", method="POST",
                                       data=json.dumps({"service_id": svc, "action": "call"}).encode(),
                                       headers={**auth, "Content-Type": "application/json"}))["token"]
    gl = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    pid = urllib.parse.quote(str(a.project), safe="")
    base = f"{PROXY}/v1/call/{svc}/projects/{pid}/variables"
    scope = a.environment_scope
    quoted = urllib.parse.quote(scope, safe="")
    existing = _json(urllib.request.Request(f"{base}?per_page=100", headers=gl))  # the list carries values: not printed
    here = any(v["key"] == a.variable and v.get("environment_scope", "*") == scope for v in existing)
    body = {"value": secret_value(a.secret), "masked": True, "protected": False, "raw": True,
            "environment_scope": scope, "description": f"from Mintkey secret {a.secret}"}
    one = f"{base}/{urllib.parse.quote(a.variable, safe='')}?filter[environment_scope]={quoted}"
    if here:
        _json(urllib.request.Request(one, method="PUT", data=json.dumps(body).encode(), headers=gl))
        action = "updated"
    else:
        _json(urllib.request.Request(base, method="POST", data=json.dumps({"key": a.variable, **body}).encode(),
                                     headers=gl))
        action = "created"
    meta = _json(urllib.request.Request(one, headers=gl))
    print(f"{action} {a.variable} on project {a.project}: environment scope {meta.get('environment_scope', scope)} "
          f"masked={meta['masked']} protected={meta['protected']} raw={meta.get('raw')} (value not shown)")
    if scope != "*" and any(v["key"] == a.variable and v.get("environment_scope", "*") == "*" for v in existing):
        print(f"WARN an unscoped variable {a.variable} (scope *) still exists: every job of the project can read it. "
              f"Delete it once the scoped one is verified (not deleted here)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
