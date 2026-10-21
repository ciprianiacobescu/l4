#!/usr/bin/env bash
# mk-l4-setup-gitlab.sh — `l4 setup gitlab` through the Mintkey GitLab proxy (service slug $MINTKEY_GITLAB_SLUG, default example-gitlab).
#
# The brokered JWT is fetched into this process's environment and handed to l4 as $MK_JWT: it is never in an argv and
# never on disk, and neither is a secret fetched with --mk-secret (it goes in $L4_MK_SECRET_<NAME>). The Mintkey agent
# key goes to curl through its config on stdin, so it is not in the process list either. The script `exec`s l4: the
# exit code is l4's.
#
#   scripts/forge/mk-l4-setup-gitlab.sh --project group/name [--watch] [--rotate [--revoke-old]]
#       [--mk-secret NAME=<mintkey secret name>]... [any other `l4 setup gitlab` option]
#
# `--print-jwt` fetches one brokered JWT and prints it, to a pipe only (never to a terminal), then exits: l4 runs it as
# its `--token-command` when the forge answers 401, because the JWT lives about ten minutes and a check pipeline can
# run longer.
#
# L4_BIN (default .l4/bin/l4) is the l4 to run; MINTKEY_API, MINTKEY_PROXY, MINTKEY_GITLAB_SLUG, GITLAB_API (the real
# GitLab API base, where the new bot token is verified) and MINTKEY_AGENT_KEY (default: ~/.claude.json) override.
set -euo pipefail
SELF=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")
API=${MINTKEY_API:-http://localhost:8082}
PROXY=${MINTKEY_PROXY:-http://localhost:8000}
SLUG=${MINTKEY_GITLAB_SLUG:-example-gitlab}
VERIFY_BASE=${GITLAB_API:-https://gitlab.example.com/api/v4}
KEY=${MINTKEY_AGENT_KEY:-$(python3 -c 'import json,os;print(json.load(open(os.path.expanduser("~/.claude.json")))["mcpServers"]["mintkey"]["headers"]["Authorization"].split()[-1])')}

mk_get() {  # mk_get URL: the Mintkey agent key goes through curl's config on stdin
  curl -fsS -K - "$1" <<<"header = \"Authorization: Bearer $KEY\""
}
json_field() {  # json_field PYTHON-EXPRESSION-OF-d: read JSON from stdin
  python3 -c 'import sys,json;d=json.load(sys.stdin);print(eval(sys.argv[1]))' "$1"
}

SVC=$(mk_get "$API/v1/tools/list_services" | python3 -c 'import sys,json
slug=sys.argv[1]
found=[s["id"] for s in json.load(sys.stdin)["services"] if s["slug"]==slug]
sys.exit("no Mintkey service with the slug "+slug) if not found else print(found[0])' "$SLUG")

MK_JWT=$(curl -fsS -K - "$API/v1/tools/request_token" <<EOF2 | json_field 'd["token"]'
request = "POST"
header = "Authorization: Bearer $KEY"
header = "Content-Type: application/json"
data = "{\"service_id\":\"$SVC\",\"action\":\"call\"}"
EOF2
)
export MK_JWT

if [ "${1:-}" = "--print-jwt" ]; then
  if [ -t 1 ]; then
    echo "mk-l4-setup-gitlab.sh: refusing to print a credential to a terminal: pipe it" >&2
    exit 2
  fi
  printf '%s\n' "$MK_JWT"
  exit 0
fi

args=()
while [ $# -gt 0 ]; do
  case "$1" in
    --mk-secret)
      shift
      spec=${1:?--mk-secret needs NAME=<mintkey secret name>}
      name=${spec%%=*}
      secret_name=${spec#*=}
      var="L4_MK_SECRET_${name}"
      secret_id=$(mk_get "$API/v1/tools/secret_list?limit=200" | python3 -c 'import sys,json
want=sys.argv[1]
found=[s["secret_id"] for s in json.load(sys.stdin).get("secrets",[]) if s.get("name")==want]
sys.exit("no Mintkey secret named "+want) if not found else print(found[0])' "$secret_name")
      value=$(mk_get "$API/v1/tools/secret_get?secret_id=$secret_id" | json_field 'd["value"]')
      export "$var=$value"
      args+=(--secret "$name=$var")
      ;;
    *) args+=("$1") ;;
  esac
  shift
done

exec "${L4_BIN:-.l4/bin/l4}" setup gitlab --api-base "$PROXY/v1/call/$SVC" --auth-env MK_JWT --auth-scheme bearer \
  --verify-base "$VERIFY_BASE" --token-command "$(printf '%q' "$SELF") --print-jwt" ${args[@]+"${args[@]}"}
