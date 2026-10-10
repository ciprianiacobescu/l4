#!/usr/bin/env bash
# kiro-state.sh — read-only: kiro-cli version, login (account type only, never the e-mail) and /usage of the runner user
set -uo pipefail
U=${1:-gitlab-runner}
H=$(getent passwd "$U" | cut -d: -f6)
run() { sudo -n -u "$U" -H env -i HOME="$H" USER="$U" LOGNAME="$U" PATH="$H/.local/bin:/usr/local/bin:/usr/bin:/bin" bash -c "$1" </dev/null; }
echo "user: $U"
echo "date: $(date -u +%FT%TZ)"
echo "version: $(run 'kiro-cli --version 2>/dev/null | tail -1')"
echo "binary: $(run 'readlink -f "$(command -v kiro-cli)"')"
w=$(run 'kiro-cli whoami --format json 2>/dev/null'); rc=$?
echo "whoami exit: $rc"
printf '%s' "$w" | python3 -c 'import sys,json
try:
    d=json.loads(sys.stdin.read() or "null")
except ValueError:
    d=None
print("whoami accountType:", (d or {}).get("accountType") if isinstance(d, dict) else None)'
if [ "${2:-}" = usage ]; then
  echo "--- /usage"
  run 'cd /tmp && timeout 120 kiro-cli chat --no-interactive --trust-tools=read "/usage" 2>&1' | sed 's/\x1b\[[0-9;]*[a-zA-Z]//g' | grep -v '@' | grep -iE "usage|credits|plan|reset" 
fi
