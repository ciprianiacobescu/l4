#!/usr/bin/env bash
# hello.sh — the "say hello" availability probe (SPEC L4-AVL-001 step `hello`) for each agent CLI, run as the runner
# user exactly as a CI job would (bash --login, fresh environment, empty scratch dir). Prints one line per probe:
#   HELLO <cli> <model> | PASS|FAIL | <seconds>s | <normalised reply or error excerpt>
# A probe passes when the reply, trimmed of whitespace and one layer of quotes/backticks, is exactly L4-OK.
#
#   bash hello.sh                                   # on the runner host (needs sudo to switch to the runner user)
#   scripts/runner/mk-ssh.sh --script scripts/runner/hello.sh
#   PROBES="claude:haiku opencode:opencode/big-pickle" bash hello.sh
set -u
RUNNER_USER=${RUNNER_USER:-gitlab-runner}
PROBES=${PROBES:-"claude:haiku codex:default opencode:opencode/big-pickle"}
TIMEOUT=${TIMEOUT:-120}
SUDO=""; [ "$(id -un)" = "$RUNNER_USER" ] || SUDO="sudo -n -u $RUNNER_USER -H env -i HOME=$(getent passwd "$RUNNER_USER" | cut -d: -f6) TERM=dumb"
PROMPT='Reply with exactly L4-OK and nothing else.'
run() { $SUDO bash --login -c "$1" 2>&1; }
for p in $PROBES; do
  cli=${p%%:*}; model=${p#*:}
  case "$cli" in
    claude)   m=""; [ "$model" = default ] || m="--model $model"
              cmd="claude -p '$PROMPT' $m --max-turns 1 --output-format json --strict-mcp-config";;
    codex)    m=""; [ "$model" = default ] || m="-m $model"
              cmd="codex exec --skip-git-repo-check --ignore-user-config -s read-only $m --json '$PROMPT'";;
    opencode) cmd="opencode run -m $model '$PROMPT'";;
    kiro-cli) m=""; [ "$model" = default ] || m="--model $model"
              cmd="kiro-cli chat --no-interactive $m '$PROMPT'";;
    *) echo "HELLO $cli $model | SKIP | unknown cli"; continue;;
  esac
  start=$(date +%s.%N)
  out=$(run "d=\$(mktemp -d) && cd \$d && timeout $TIMEOUT $cmd; echo \"__EXIT=\$?\"")
  secs=$(LC_ALL=C awk -v s="$start" -v e="$(date +%s.%N)" 'BEGIN{printf "%.1f", e-s}')
  code=$(echo "$out" | sed -n 's/^__EXIT=//p' | tail -1)
  # extract the model's final text per CLI output format
  case "$cli" in
    claude) reply=$(echo "$out" | grep -v '^__EXIT=' | python3 -c 'import sys,json
try: print(json.loads(sys.stdin.read()).get("result") or "")
except Exception as e: print("unparseable")' 2>/dev/null);;
    codex)  reply=$(echo "$out" | grep -v '^__EXIT=' | python3 -c 'import sys,json
t=""
for l in sys.stdin:
    try: e=json.loads(l)
    except Exception: continue
    it=e.get("item") or {}
    if e.get("type")=="item.completed" and it.get("type")=="agent_message": t=it.get("text","")
print(t)' 2>/dev/null);;
    *)      reply=$(echo "$out" | grep -v '^__EXIT=' | sed -e 's/\x1b\[[0-9;]*m//g' | grep -v '^\s*$' | tail -1);;
  esac
  norm=$(printf '%s' "$reply" | tr -d '\r' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^[`"'"'"']\(.*\)[`"'"'"']$/\1/')
  if [ "$code" = 0 ] && [ "$norm" = "L4-OK" ]; then st=PASS; else st=FAIL; fi
  detail=$norm; [ "$st" = FAIL ] && detail="exit=$code reply=$(printf '%s' "${norm:-$(echo "$out" | grep -v '^__EXIT=' | tail -3 | tr '\n' ' ')}" | cut -c1-200)"
  echo "HELLO $cli $model | $st | ${secs}s | $detail"
done
