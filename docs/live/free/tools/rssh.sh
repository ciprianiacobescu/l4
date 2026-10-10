#!/usr/bin/env bash
# rssh.sh <mk-ssh args...>: mk-ssh.sh with retries when the bastion fails before the command runs (auth/vault errors)
H=/Users/USER/src/l4
for i in 1 2 3 4 5 6; do
  out=$(timeout ${RSSH_TIMEOUT:-300} "$H/scripts/runner/mk-ssh.sh" "$@" 2>&1); rc=$?
  if printf '%s' "$out" | head -3 | grep -q -E 'Permission denied, please try again|failed to fetch credential|too many authentication failures|mintkey:auth_required|returned error: 401'; then
    echo "rssh: bastion error, retry $i" >&2; sleep 20; continue
  fi
  printf '%s\n' "$out"; exit $rc
done
echo "rssh: gave up" >&2; exit 99
