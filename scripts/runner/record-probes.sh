#!/usr/bin/env bash
# record-probes.sh — record what the runner's agent CLIs answer to the zero-cost availability probes (M1.2 G14).
# Run as the runner user would (bash --login, fresh environment, empty scratch dir). Nothing here spends a model
# request. Every value is masked by shape before it is printed, and only the kept fields are printed:
#   e-mail addresses -> <email>; JSON keys email, chatgptAccountId, accountId, session_id are dropped.
#
#   scripts/runner/mk-ssh.sh --script scripts/runner/record-probes.sh \
#     | python3 scripts/runner/split_recordings.py tests/fixtures/recorded
#
# Output is a stream of "=== FILE <tool>/<version>/<name>" sections that split_recordings.py writes as files.
set -u
RUNNER_USER=${RUNNER_USER:-gitlab-runner}
TIMEOUT=${TIMEOUT:-60}
SUDO=""
[ "$(id -un)" = "$RUNNER_USER" ] || SUDO="sudo -n -u $RUNNER_USER -H env -i HOME=$(getent passwd "$RUNNER_USER" | cut -d: -f6) TERM=dumb"
run() { $SUDO bash --login -c "$1" 2>&1; }
mask() { sed -E 's/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/<email>/g'; }
section() { printf '=== FILE %s\n' "$1"; }

version() { run "$1 --version" | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1; }
KIRO_V=$(version kiro-cli); CLAUDE_V=$(version claude); CODEX_V=$(version codex); OPENCODE_V=$(version opencode)

section "kiro-cli/$KIRO_V/runner-version.stdout.txt"
run "kiro-cli --version" | mask

# logged out: exit code, stdout and stderr, each on its own so a parser test can feed them back
out=$(run "d=\$(mktemp -d) && cd \$d && timeout $TIMEOUT kiro-cli whoami --format json </dev/null 2>/tmp/l4-kiro-whoami.err; echo \"__EXIT=\$?\"")
section "kiro-cli/$KIRO_V/runner-whoami.exit.txt"
printf '%s\n' "$out" | sed -n 's/^__EXIT=//p' | tail -1
section "kiro-cli/$KIRO_V/runner-whoami.stdout.txt"
printf '%s\n' "$out" | grep -v '^__EXIT=' | mask
section "kiro-cli/$KIRO_V/runner-whoami.stderr.txt"
run "cat /tmp/l4-kiro-whoami.err; rm -f /tmp/l4-kiro-whoami.err" | mask

section "claude-code/$CLAUDE_V/runner-usage-pro.json"
run "d=\$(mktemp -d) && cd \$d && TZ=UTC timeout $TIMEOUT claude -p --safe-mode --no-session-persistence --output-format json '/usage' </dev/null" \
  | python3 -c '
import json, re, sys
raw = sys.stdin.read()
try:
    doc = json.loads(raw)
except ValueError:
    print(json.dumps({"unparseable": True, "head": re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "<email>", raw[:300])}))
    sys.exit(0)
keep = {k: doc.get(k) for k in ("is_error", "subtype", "api_error_status", "result") if k in doc}
if isinstance(keep.get("result"), str):
    keep["result"] = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "<email>", keep["result"])
print(json.dumps(keep, indent=1, ensure_ascii=False))
'

section "codex/$CODEX_V/runner-app-server.json"
run "d=\$(mktemp -d) && cd \$d && timeout $TIMEOUT python3 -c '
import json, subprocess, sys, time
DROP = {\"email\", \"chatgptAccountId\", \"accountId\", \"id\", \"title\", \"description\"}
def clean(v, top=True):
    if isinstance(v, dict):
        return {k: (\"<redacted>\" if k in {\"id\"} and not top else clean(x, False)) for k, x in v.items() if k not in DROP - {\"id\"}}
    if isinstance(v, list):
        return [clean(x, False) for x in v]
    return v
p = subprocess.Popen([\"codex\", \"app-server\"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
msgs = [
    {\"method\": \"initialize\", \"id\": 1, \"params\": {\"clientInfo\": {\"name\": \"l4-probe\", \"version\": \"0.0.1\"}}},
    {\"method\": \"initialized\"},
    {\"method\": \"account/read\", \"id\": 2, \"params\": {\"refreshToken\": False}},
    {\"method\": \"account/rateLimits/read\", \"id\": 3},
]
for m in msgs:
    p.stdin.write(json.dumps(m) + \"\\n\")
p.stdin.flush()
got, deadline, t0 = {}, time.time() + 30, time.time()
while len(got) < 3 and time.time() < deadline:
    line = p.stdout.readline()
    if not line:
        break
    try:
        d = json.loads(line)
    except ValueError:
        continue
    if isinstance(d, dict) and \"id\" in d and (\"result\" in d or \"error\" in d):
        got[d[\"id\"]] = d
p.stdin.close()
p.terminate()
names = {1: \"initialize\", 2: \"account_read\", 3: \"rate_limits_read\"}
out = {\"timings\": {\"total_s\": round(time.time() - t0, 3)}}
for i, n in names.items():
    d = got.get(i)
    if d is None:
        out[n] = None
    elif \"result\" in d and n == \"initialize\":
        out[n] = {\"id\": i, \"result\": {k: d[\"result\"].get(k) for k in (\"platformFamily\", \"platformOs\")}}
    else:
        out[n] = clean(d)
print(json.dumps(out, indent=1))
'" | mask

section "opencode/$OPENCODE_V/runner-version.stdout.txt"
run "opencode --version" | mask
