#!/usr/bin/env bash
# mk-gitlab-bot-token.sh — run gitlab_bot_token.py through the Mintkey GitLab proxy (service slug $MINTKEY_GITLAB_SLUG, default example-gitlab).
# Environment: MINTKEY_GITLAB_SLUG (the GitLab service slug), GITLAB_API (the real GitLab API base, where the new token is
# verified), MINTKEY_API, MINTKEY_PROXY, MINTKEY_AGENT_KEY (default: ~/.claude.json).
# SUPERSEDED by scripts/forge/mk-l4-setup-gitlab.sh, which runs `l4 setup gitlab` (M1.8); this one stays for now.
# The brokered JWT is fetched into this process's environment only (never printed, never written to disk).
#   scripts/forge/mk-gitlab-bot-token.sh --project 118 [--rotate] [other gitlab_bot_token.py options]
set -euo pipefail
API=${MINTKEY_API:-http://localhost:8082}; PROXY=${MINTKEY_PROXY:-http://localhost:8000}
SLUG=${MINTKEY_GITLAB_SLUG:-example-gitlab}; VERIFY_BASE=${GITLAB_API:-https://gitlab.example.com/api/v4}
KEY=${MINTKEY_AGENT_KEY:-$(python3 -c 'import json,os;print(json.load(open(os.path.expanduser("~/.claude.json")))["mcpServers"]["mintkey"]["headers"]["Authorization"].split()[-1])')}
SVC=$(curl -fsS -H "Authorization: Bearer $KEY" "$API/v1/tools/list_services" | python3 -c 'import sys,json;print([s["id"] for s in json.load(sys.stdin)["services"] if s["slug"]==sys.argv[1]][0])' "$SLUG")
export MK_JWT=$(curl -fsS -X POST -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' -d "{\"service_id\":\"$SVC\",\"action\":\"call\"}" "$API/v1/tools/request_token" | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
exec python3 "$(dirname "$0")/gitlab_bot_token.py" --api-base "$PROXY/v1/call/$SVC" --auth-env MK_JWT --auth-scheme bearer --verify-base "$VERIFY_BASE" "$@"
