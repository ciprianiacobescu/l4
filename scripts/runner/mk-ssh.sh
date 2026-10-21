#!/usr/bin/env bash
# mk-ssh.sh — run a command on a host reached through the Mintkey SSH bastion.
#
#   scripts/runner/mk-ssh.sh [--service SLUG] -- '<remote command>'
#   scripts/runner/mk-ssh.sh [--service SLUG] --script FILE [-- args...]   # pipes FILE to `bash -s` remotely
#
# How it works (Mintkey agent_connection_guide): request a short-lived JWT for the service (action "call"),
# then SSH to the bastion with user = the agent id (the JWT `sub`) and password = the JWT. The bastion fetches the
# stored credential and routes to the real host. The JWT is held only in this process's environment (via sshpass -e)
# and is never printed or written to disk.
#
# Environment:
#   MINTKEY_SSH_SLUG default ssh-runner                       (the SSH service slug; --service overrides it)
#   MINTKEY_API      default http://localhost:8082           (Mintkey MCP/REST endpoint)
#   MINTKEY_BASTION  default localhost:2222                   (Mintkey SSH bastion host:port)
#   MINTKEY_AGENT_KEY  the mk_agent_… bearer; if unset it is read from ~/.claude.json (mcpServers.mintkey.headers)
# Requires: curl, python3, sshpass.
set -euo pipefail
SLUG=${MINTKEY_SSH_SLUG:-ssh-runner}; SCRIPT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --service) SLUG=$2; shift 2;;
    --script) SCRIPT=$2; shift 2;;
    --) shift; break;;
    *) break;;
  esac
done
API=${MINTKEY_API:-http://localhost:8082}
BASTION=${MINTKEY_BASTION:-localhost:2222}
if [ -z "${MINTKEY_AGENT_KEY:-}" ]; then
  MINTKEY_AGENT_KEY=$(python3 -c 'import json,os;print(json.load(open(os.path.expanduser("~/.claude.json")))["mcpServers"]["mintkey"]["headers"]["Authorization"].split()[-1])')
fi
AUTH="Authorization: Bearer $MINTKEY_AGENT_KEY"
SVC=$(curl -fsS -H "$AUTH" "$API/v1/tools/list_services" \
  | python3 -c 'import sys,json; s=[x["id"] for x in json.load(sys.stdin)["services"] if x["slug"]==sys.argv[1]]; print(s[0] if s else "")' "$SLUG")
[ -n "$SVC" ] || { echo "mk-ssh: service '$SLUG' not granted to this agent" >&2; exit 2; }
TOKJSON=$(curl -fsS -X POST -H "$AUTH" -H 'Content-Type: application/json' \
  -d "{\"service_id\":\"$SVC\",\"action\":\"call\"}" "$API/v1/tools/request_token")
export SSHPASS=$(printf '%s' "$TOKJSON" | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
AGENT=$(printf '%s' "$SSHPASS" | python3 -c 'import sys,json,base64; p=sys.stdin.read().split(".")[1]; p+="="*(-len(p)%4); print(json.loads(base64.urlsafe_b64decode(p))["sub"])')
HOST=${BASTION%:*}; PORT=${BASTION##*:}
SSHOPTS=(-p "$PORT" -o PreferredAuthentications=password -o PubkeyAuthentication=no
         -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$HOME/.ssh/known_hosts_mintkey" -o LogLevel=ERROR)
if [ -n "$SCRIPT" ]; then
  sshpass -e ssh "${SSHOPTS[@]}" "$AGENT@$HOST" "bash -s -- $*" < "$SCRIPT"
else
  sshpass -e ssh "${SSHOPTS[@]}" "$AGENT@$HOST" "$*"
fi
