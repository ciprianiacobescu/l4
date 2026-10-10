#!/usr/bin/env bash
# mk-gitlab-api.sh <METHOD> <api-path> [curl args...] — GitLab REST API through the Mintkey proxy (service slug $MINTKEY_GITLAB_SLUG, default example-gitlab).
# Environment: MINTKEY_GITLAB_SLUG (the GitLab service slug), MINTKEY_API, MINTKEY_PROXY, L4GL_ENV, L4GL_RETRIES, L4GL_RETRY_WAIT.
# The service id and the brokered JWT are cached together in $L4GL_ENV (default /tmp/l4gl.env, mode 600, ~10 min) and
# the JWT is never printed; rm it when done. `list_services` runs only when a new token is minted.
# The upstream body is always printed. A status of 400 or more exits 22 with `HTTP <code> <METHOD> <path>` on stderr.
# Retries (M1.11 W11, live wave A: Mintkey answers an intermittent 502 "vault error" and a token can lapse; M1.13 W-C6:
# wave C saw it answer 502 more than once in a row):
#   - a 502 of the proxy is tried again up to $L4GL_RETRIES times (default 3), after $L4GL_RETRY_WAIT seconds (default 2)
#     times the number of the try; L4GL_RETRIES=0 keeps one try;
#   - a 401 of the proxy drops the cache, lists the services and requests a token again, then tries once more;
#   - a Mintkey tools call (list_services, request_token) is tried again on a 502 (as often as above) and once on a 401.
# A failure that survives the retries exits 22 with its status; a failing tools call stops the script before anything is
# parsed as JSON.
set -euo pipefail
ENVF=${L4GL_ENV:-/tmp/l4gl.env}
MKAPI=${MINTKEY_API:-http://localhost:8082}
MKPROXY=${MINTKEY_PROXY:-http://localhost:8000}
SLUG=${MINTKEY_GITLAB_SLUG:-example-gitlab}
WAIT=${L4GL_RETRY_WAIT:-2}
RETRIES=${L4GL_RETRIES:-3}
AUTH=$(python3 -c 'import json,os;print(json.load(open(os.path.expanduser("~/.claude.json")))["mcpServers"]["mintkey"]["headers"]["Authorization"])')
BODY=$(mktemp); trap 'rm -f "$BODY"' EXIT

# tools <name> [curl args...]: a Mintkey tools call, the body on stdout; a 502 is tried again $RETRIES times, a 401 once
tools() {
  local name=$1 code tries=0 expired=0
  shift
  while :; do
    code=$(curl -sS -o "$BODY" -w '%{http_code}' -H "Authorization: $AUTH" "$@" "$MKAPI/v1/tools/$name")
    if [ "$code" = 502 ] && [ "$tries" -lt "$RETRIES" ]; then tries=$((tries + 1)); sleep $((WAIT * tries)); continue; fi
    if [ "$code" = 401 ] && [ "$expired" -eq 0 ]; then expired=1; sleep "$WAIT"; continue; fi
    break
  done
  if [ "$code" -ge 400 ]; then echo "curl: (22) The requested URL returned error: $code" >&2; return 22; fi
  cat "$BODY"
}

# mint: the service id and a new token, cached together
mint() {
  local listed r
  listed=$(tools list_services)
  SVC=$(echo "$listed" | python3 -c 'import sys,json;print([s["id"] for s in json.load(sys.stdin)["services"] if s["slug"]==sys.argv[1]][0])' "$SLUG")
  r=$(tools request_token -X POST -H "Content-Type: application/json" -d "{\"service_id\":\"$SVC\",\"action\":\"call\"}")
  JWT=$(echo "$r" | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])'); EXP=$(echo "$r" | python3 -c 'import sys,json;print(json.load(sys.stdin)["expires_at"])')
  umask 077; printf 'SVC=%s\nJWT=%s\nEXP=%s\n' "$SVC" "$JWT" "$EXP" > "$ENVF"
}

now=$(date +%s)
SVC=""; JWT=""; EXP=0
if [ -f "$ENVF" ]; then . "$ENVF"; fi
if [ -z "${SVC:-}" ] || [ -z "${JWT:-}" ] || [ "$now" -ge "$(( ${EXP:-0} - 60 ))" ]; then mint; fi
M=$1; P=$2; shift 2
tries=0; refreshed=0
while :; do
  CODE=$(curl -sS -o "$BODY" -w '%{http_code}' -X "$M" -H "Authorization: Bearer $JWT" "$MKPROXY/v1/call/$SVC/$P" "$@")
  if [ "$CODE" = 502 ] && [ "$tries" -lt "$RETRIES" ]; then tries=$((tries + 1)); sleep $((WAIT * tries)); continue; fi
  if [ "$CODE" = 401 ] && [ "$refreshed" -eq 0 ]; then refreshed=1; rm -f "$ENVF"; mint; continue; fi
  break
done
cat "$BODY"
if [ "$CODE" -ge 400 ]; then
  echo "HTTP $CODE $M $P" >&2
  exit 22
fi
