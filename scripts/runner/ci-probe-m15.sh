#!/usr/bin/env bash
# ci-probe-m15.sh — M15-G2 (spikes 2.2, reduced): what do Playwright, Serena and Laya cost and need INSIDE the L4
# sandbox on this runner? Run from a CI job (tags: [agentic]) on the throwaway branch `probe/m15` of the dummy repo,
# as the runner user, with nothing else running on the runner (part c measures memory).
#
#   (a) a stdlib HTTP server and a pytest-playwright smoke test in ONE gate spawn (`--unshare-net`), the exact argv
#       BwrapSandbox.build_argv builds for kind=gate, once without and once with `--tmpfs /dev/shm`   -> decision P1
#   (b) `serena start-mcp-server --context codex ...` inside the agent argv: MCP initialize seconds, memory
#   (c) `laya-serve` with the typed-decisions checkpoint: load seconds, peak memory, p50 of 5 noul calls, byte-identical
#       answers, and the token count of a state of N approx-tokens (chars / 4) with Laya's tokenizer   -> P2, P3
#   (d) TCP connects from the runner to the maintainer's Mac (192.0.2.10): is a Laya port reachable?   -> P2
#   (e) `cache_root` as this job resolves it: L4_CACHE / XDG_CACHE_HOME set or not, and whether the PRQ-14 browser
#       directory is the one the gate's read-only `playwright` mount names
#
# Every line that carries a result starts with "RESULT ". The script never prints the environment and never reads
# a credential. Exit 0 when every measurement ran (a measured FAIL is a result, not a script error).
set -u
set +x

HOME_DIR=${HOME:?}
PARTS=${PARTS:-"e a b c d"}   # a subset for a re-run; the job runs all of them
MAC_HOST=${MAC_HOST:-192.0.2.10}
MAC_PORTS=${MAC_PORTS:-"8000 8765 22"}
PW_VERSION=${PW_VERSION:-1.63.0}
PYTEST_PW_VERSION=${PYTEST_PW_VERSION:-0.9.0}
LAYA_THREADS_N=${LAYA_THREADS_N:-2}
T=$(mktemp -d "$HOME_DIR/.l4-m15-probe-XXXXXX"); chmod 700 "$T"
trap 'rm -rf "$T"' EXIT
fail=0
wants() { case " $PARTS " in *" $1 "*) return 0;; esac; return 1; }
say() { printf '%s\n' "$*"; }
section() { printf '\n=== %s\n' "$*"; }

# --- the probe's measuring tool: tree RSS sampling, an MCP initialize client, a laya-serve client --------------------
cat > "$T/tool.py" <<'PY_EOF'
"""probe tool: `rss OUT TIMEOUT CMD...` | `mcp OUT TIMEOUT CMD...` | `laya OUT TIMEOUT PORT MODEL CMD...` (stdlib only)."""
import hashlib
import json
import os
import queue
import resource
import statistics
import subprocess
import sys
import threading
import time
import urllib.request

PAGE_KB = os.sysconf("SC_PAGE_SIZE") // 1024


def table():
    rows = {}
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/stat") as handle:
                raw = handle.read()
        except OSError:
            continue
        head, _, tail = raw.rpartition(")")
        fields = tail.split()
        rows[int(name)] = (int(fields[1]), int(fields[21]) * PAGE_KB, head.partition("(")[2])
    return rows


class Sampler(threading.Thread):
    """Peak of the summed RSS of a process and all its descendants, and the process names seen."""

    def __init__(self, root):
        super().__init__(daemon=True)
        self.root, self.peak, self.names, self.stop = root, 0, set(), threading.Event()

    def run(self):
        while not self.stop.is_set():
            rows = table()
            kids = {}
            for pid, (ppid, _, _) in rows.items():
                kids.setdefault(ppid, []).append(pid)
            todo, total = [self.root], 0
            while todo:
                pid = todo.pop()
                if pid in rows:
                    total += rows[pid][1]
                    self.names.add(rows[pid][2])
                    todo.extend(kids.get(pid, []))
            self.peak = max(self.peak, total)
            time.sleep(0.1)


def finish(proc):
    sampler_stop = getattr(proc, "sampler", None)
    if sampler_stop:
        sampler_stop.stop.set()
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, 15)
            proc.wait(15)
        except (subprocess.TimeoutExpired, ProcessLookupError):
            try:
                os.killpg(proc.pid, 9)
            except ProcessLookupError:
                pass
            proc.wait()


def summary(proc, sampler, started):
    kb = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    names = ",".join(sorted(sampler.names))[:160]
    return f"secs={time.time() - started:.1f} child_maxrss_kb={kb} tree_peak_kb={sampler.peak} procs={names}"


def start(cmd, out, stdin=subprocess.DEVNULL, stdout=None):
    sink = open(out, "wb")
    proc = subprocess.Popen(cmd, stdin=stdin, stdout=stdout or sink, stderr=sink, start_new_session=True)
    proc.sampler = Sampler(proc.pid)
    proc.sampler.start()
    return proc


def run_rss(out, timeout, cmd):
    started = time.time()
    proc = start(cmd, out)
    try:
        proc.wait(timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        timed_out = True
    finish(proc)
    print(f"__RSS exit={proc.returncode} timeout={'yes' if timed_out else 'no'} {summary(proc, proc.sampler, started)}")


def run_mcp(out, timeout, cmd):
    started = time.time()
    proc = start(cmd, out, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    lines = queue.Queue()
    threading.Thread(target=lambda: [lines.put(line) for line in proc.stdout], daemon=True).start()

    def send(message):
        proc.stdin.write((json.dumps(message) + "\n").encode())
        proc.stdin.flush()

    def wait_for(want, limit):
        end = time.time() + limit
        while time.time() < end:
            try:
                message = json.loads(lines.get(timeout=0.2))
            except queue.Empty:
                continue
            except ValueError:
                continue
            if isinstance(message, dict) and message.get("id") == want:
                return message
        return None

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "l4-probe", "version": "0"}}})
    reply = wait_for(1, timeout)
    handshake = time.time() - started
    tools = []
    if reply:
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        listed = wait_for(2, 60)
        tools = [tool.get("name", "") for tool in ((listed or {}).get("result") or {}).get("tools", [])]
    symbols = "not_run"
    if "get_symbols_overview" in tools:  # the first symbolic call starts the language server (Pyright via uvx)
        began = time.time()
        send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
              "params": {"name": "get_symbols_overview", "arguments": {"relative_path": "calc.py"}}})
        called = wait_for(3, 180)
        failed = called is None or "error" in called or (called.get("result") or {}).get("isError")
        symbols = f"{'FAILED' if failed else 'ok'}_in_{time.time() - began:.1f}s"
        if failed:
            text = json.dumps(called)[:300] if called else "no reply"
            symbols += "(" + text.replace(" ", "_") + ")"
    info = ((reply or {}).get("result") or {}).get("serverInfo") or {}
    finish(proc)
    memory = [name for name in tools if "memor" in name]
    print(f"__MCP initialize={'ok' if reply else 'NO_REPLY'} initialize_s={handshake:.1f} server={info.get('name')} "
          f"server_version={info.get('version')} tools={len(tools)} memory_tools={len(memory)} symbols_overview={symbols} {summary(proc, proc.sampler, started)}")


def post(port, body):
    request = urllib.request.Request(f"http://127.0.0.1:{port}/v1/systemone", json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
    began = time.time()
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()
    return data, time.time() - began


def run_laya(out, timeout, port, model, cmd):
    started = time.time()
    proc = start(cmd, out)
    ready = None
    while time.time() - started < timeout and proc.poll() is None:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                if response.status == 200:
                    ready = time.time() - started
                    break
        except OSError:
            time.sleep(0.5)
    if ready is None:
        finish(proc)
        print(f"__LAYA ready=no exit={proc.returncode} {summary(proc, proc.sampler, started)}")
        return
    body = {"state": "Scenario: an empty email is rejected with 'Email is required'. Test output: 3 passed, 0 failed.",
            "model": model,
            "questions": {"c1": {"type": "noul", "instructions": "Does this evidence show that the criterion is satisfied?"}}}
    hashes, times, answer, served = [], [], None, None
    error = ""
    try:
        for _ in range(5):
            data, took = post(port, body)
            hashes.append(hashlib.sha256(data).hexdigest()[:12])
            times.append(took * 1000)
            parsed = json.loads(data)
            answer, served = parsed["answers"]["c1"].get("noul"), parsed.get("model")
    except Exception as exc:  # a measurement, not a crash: report it
        error = f"{type(exc).__name__}"
    finish(proc)
    p50 = statistics.median(times) if times else -1
    print(f"__LAYA ready=yes load_s={ready:.1f} calls={len(times)} p50_ms={p50:.0f} identical={'yes' if len(set(hashes)) == 1 and hashes else 'no'} "
          f"hash={hashes[0] if hashes else '-'} noul={answer} served_model={served} error={error or '-'} {summary(proc, proc.sampler, started)}")


if __name__ == "__main__":
    mode, out, limit = sys.argv[1], sys.argv[2], float(sys.argv[3])
    if mode == "rss":
        run_rss(out, limit, sys.argv[4:])
    elif mode == "mcp":
        run_mcp(out, limit, sys.argv[4:])
    elif mode == "laya":
        run_laya(out, limit, sys.argv[4], sys.argv[5], sys.argv[6:])
PY_EOF

# --- the tokenizer count of part (c), run with the Python of the laya tool ------------------------------------------
cat > "$T/tokens.py" <<'PY_EOF'
import glob
import json
import os
import sys

from transformers import AutoTokenizer

pattern = os.path.expanduser("~/.cache/huggingface/hub/models--convaiinnovations--laya/snapshots/*/typed-decisions/tokenizer")
paths = sorted(glob.glob(pattern))
if not paths:
    print("__TOK error=no typed-decisions tokenizer in the Hugging Face cache")
    sys.exit(0)
tok = AutoTokenizer.from_pretrained(paths[0])
PROSE = ("Scenario: a customer with a discount code of ten percent sees the subtotal reduced by that amount before "
         "tax is added. The page shows the item count in the header and the subtotal under the list of items. ")
JSONISH = json.dumps({"answer": "the badge shows the item count", "cited_text": "def total(items):\n    return sum(i.price * i.qty for i in items)\n"})
CODE = "def test_subtotal(page):\n    page.goto(base)\n    assert page.get_by_test_id('subtotal').inner_text() == '$10.00'\n"
WINDOW = int(os.environ.get("LAYA_WINDOW", "463"))


def tokens(unit, approx):
    text = (unit * (approx * 4 // len(unit) + 1))[: approx * 4]
    return len(tok.encode(text, add_special_tokens=False))


rows = []
for name, unit in (("prose", PROSE), ("json", JSONISH), ("code", CODE)):
    best = 0
    for approx in range(50, 700, 10):
        if tokens(unit, approx) <= WINDOW:
            best = approx
    rows.append((name, best, tokens(unit, 450)))
    print(f"__TOK text={name} approx450_tokens={tokens(unit, 450)} largest_approx_within_{WINDOW}={best}")
print(f"__TOK budget_P3={min(r[1] for r in rows)} window={WINDOW} tokenizer={os.path.basename(os.path.dirname(paths[0]))}")
PY_EOF

# --- the sandbox argv (a) and (b) run in --------------------------------------------------------------------------
# --- m0-profile begin (the agent and gate profile of l4.sandbox.bwrap.BwrapSandbox.build_argv; one token per output line;
#     tests/unit/runner/test_probe_m15_parity.py diffs it against the Python; M0_NET=unshare is the gate kind) ---
m0_cred_paths() {  # adapter -> its login paths (SPEC sandbox.credential_paths defaults)
  case "$1" in
    codex) echo "$HOME/.codex";;
    claude-code) echo "$HOME/.claude"; echo "$HOME/.claude.json";;
    opencode) echo "$HOME/.local/share/opencode"; echo "$HOME/.config/opencode";;
    kiro-cli) echo "$HOME/.kiro"; echo "$HOME/.aws/sso/cache"; echo "$HOME/.local/share/kiro-cli"; echo "$HOME/Library/Application Support/kiro-cli";;
  esac
}
m0_hide() {  # a directory is covered by a tmpfs, a file by /dev/null, a missing path is skipped
  if [ -d "$1" ]; then printf '%s\n' --tmpfs "$1"
  elif [ -e "$1" ]; then printf '%s\n' --ro-bind /dev/null "$1"; fi
}
m0_norm() {  # absolute path -> the same path without `.`, `..` and empty parts (posixpath.normpath)
  local IFS=/ part out=
  local -a stack=()
  set -f
  for part in $1; do
    case $part in
      ''|.) ;;
      ..) if [ "${#stack[@]}" -gt 0 ]; then unset 'stack[${#stack[@]}-1]'; fi;;
      *) stack+=("$part");;
    esac
  done
  set +f
  for part in ${stack[@]+"${stack[@]}"}; do out=$out/$part; done
  printf '%s\n' "${out:-/}"
}
m0_link_end() {  # absolute path -> where its symlink chain ends (l4.sandbox.bwrap._link_end); L4_HOST_ROOT is for tests
  local root=${L4_HOST_ROOT:-} p=$1 n=0 t
  while [ -L "$root$p" ] && [ "$n" -lt 8 ]; do
    t=$(readlink "$root$p")
    case $t in /*) p=$t;; *) p=$(dirname "$p")/$t;; esac
    p=$(m0_norm "$p"); n=$((n + 1))
  done
  printf '%s\n' "$p"
}
m0_masks() {  # HB-1: /run (and /var/run) is a tmpfs, so a container daemon's socket is unreachable; only the file
  # /etc/resolv.conf points to is put back (read-only), never /run/user/<uid>  (l4.sandbox.bwrap.daemon_socket_masks)
  local root=${L4_HOST_ROOT:-} resolver var_run
  if [ -d "$root/run" ] && [ ! -L "$root/run" ]; then
    printf '%s\n' --tmpfs /run
    resolver=$(m0_link_end /etc/resolv.conf)
    case $resolver in /run/user|/run/user/*) ;; /run/?*) printf '%s\n' --ro-bind-try "$resolver" "$resolver";; esac
  fi
  var_run=$(m0_link_end /var/run)
  case $var_run in
    /run|/run/*|/) ;;
    *) if [ -d "$root$var_run" ]; then printf '%s\n' --tmpfs "$var_run"; fi;;
  esac
}
m0_env() {  # private-dir [NAME=VALUE...] -> NAME=VALUE lines: l4.sandbox.env.build_agent_env, same names, same order
  local tmp=$1 entry name path=
  shift
  for entry in $(printf '%s' "$PATH" | tr ':' ' '); do case "$entry" in /*) path=${path:+$path:}$entry;; esac; done
  printf '%s\n' "PATH=$path" "HOME=$HOME" "USER=${USER:-${LOGNAME:-l4}}" "LANG=${LANG:-C.UTF-8}" "TMPDIR=$tmp" \
    "PYTHONDONTWRITEBYTECODE=1"
  for name in LC_ALL LC_CTYPE TZ TERM HTTP_PROXY HTTPS_PROXY NO_PROXY http_proxy https_proxy no_proxy; do
    [ -n "${!name:-}" ] && printf '%s\n' "$name=${!name}"
  done
  printf '%s\n' "L4_RESULT_PATH=$tmp/result.json" "$@"
}
m0_gate_env() {  # private-dir [NAME=VALUE...] -> l4.sandbox.env.build_gate_env: the base, then the cache variables
  local tmp=$1 arg   # (and UV_LINK_MODE=copy when a uv cache is mounted: the cache and the worktree are separate binds;
  shift              # and npm_config_store_dir, read by pnpm 9 and 10, beside pnpm 11's pnpm_config_store_dir)
  m0_env "$tmp" | grep -v '^L4_RESULT_PATH='
  printf '%s\n' "$@"
  for arg in "$@"; do case $arg in UV_CACHE_DIR=*) printf '%s\n' "UV_LINK_MODE=copy";; esac; done
  for arg in "$@"; do case $arg in pnpm_config_store_dir=*) printf '%s\n' "npm_config_store_dir=${arg#*=}";; esac; done
}
m0_argv() {  # adapter(or empty for a gate) worktree git-common-dir private-dir [cache:DIR|rocache:DIR|hide:DIR|extra:FLAG...] NAME=VALUE... -- command...
  local adapter=$1 wt=$2 gd=$3 tmp=$4 other p
  local -a caches=() hides=()
  shift 4
  while [ "$#" -gt 0 ]; do
    case "$1" in
      cache:*) caches+=(--bind "${1#cache:}" "${1#cache:}");;
      rocache:*) caches+=(--ro-bind "${1#rocache:}" "${1#rocache:}");;
      hide:*) hides+=("${1#hide:}");;  # the CI runner's <CI_PROJECT_DIR>.tmp: l4.sandbox.base.runner_tmp_paths
      *) break;;
    esac
    shift
  done
  printf '%s\n' bwrap --ro-bind / / --dev /dev --proc /proc --tmpfs /tmp
  m0_masks
  printf '%s\n' --unshare-pid --unshare-ipc "--${M0_NET:-share}-net" --die-with-parent
  for other in codex claude-code opencode kiro-cli; do
    [ "$other" = "$adapter" ] && continue
    m0_cred_paths "$other" | while IFS= read -r p; do m0_hide "$p"; done
  done
  for p in ${hides[@]+"${hides[@]}"}; do m0_hide "$p"; done
  [ -n "$adapter" ] && m0_cred_paths "$adapter" | while IFS= read -r p; do if [ -e "$p" ]; then printf '%s\n' --bind "$p" "$p"; fi; done
  printf '%s\n' --bind "$wt" "$wt" --bind "$tmp" "$tmp" \
    ${caches[@]+"${caches[@]}"} --ro-bind "$gd" "$gd" --clearenv
  while [ "$#" -gt 0 ] && [ "$1" != -- ]; do printf '%s\n' --setenv "${1%%=*}" "${1#*=}"; shift; done
  shift
  printf '%s\n' --chdir "$wt" -- "$@"
}
# --- m0-profile end ---

argv_to_array() {  # BW <- the lines on stdin (what m0_argv prints, one token per line); call as `argv_to_array < <(m0_argv ...)`
  local line; BW=()
  while IFS= read -r line; do BW+=("$line"); done
}

# ---------------------------------------------------------------------------------------------------------------
section "host"
say "date $(date -u +%FT%TZ) host $(hostname) user $(id -un) cpus $(nproc)"
say "bwrap $(bwrap --version 2>&1 | head -1) | uv $(uv --version 2>&1) | serena $(serena --version 2>&1 | head -1)"
say "$(free -m | sed -n '1,2p')"
say "heaviest processes now (name, RSS kB): $(ps -eo rss=,comm= --sort=-rss | head -5 | tr -s ' ' | tr '\n' ';')"
say "load: $(cut -d' ' -f1-3 /proc/loadavg)"

# --- (e) cache_root ------------------------------------------------------------------------------------------------
wants e && {
section "(e) cache_root as this job resolves it"
if [ -n "${L4_CACHE:-}" ]; then CACHE_ROOT=$L4_CACHE; src=L4_CACHE
elif [ -n "${XDG_CACHE_HOME:-}" ]; then CACHE_ROOT=$XDG_CACHE_HOME/l4; src=XDG_CACHE_HOME
else CACHE_ROOT=$HOME_DIR/.cache/l4; src=HOME; fi
PW_DIR=$CACHE_ROOT/shared/ms-playwright
say "L4_CACHE=$([ -n "${L4_CACHE:-}" ] && echo set || echo unset) XDG_CACHE_HOME=$([ -n "${XDG_CACHE_HOME:-}" ] && echo set || echo unset) PLAYWRIGHT_BROWSERS_PATH=$([ -n "${PLAYWRIGHT_BROWSERS_PATH:-}" ] && echo set || echo unset)"
if [ -d "$PW_DIR" ] && ls "$PW_DIR" | grep -q '^chromium'; then pw=present; else pw=ABSENT; fi
say "RESULT (e): cache_root=$CACHE_ROOT (from $src) gate_playwright_mount=$PW_DIR browsers=$pw prq14_path=$HOME_DIR/.cache/l4/shared/ms-playwright same=$([ "$PW_DIR" = "$HOME_DIR/.cache/l4/shared/ms-playwright" ] && echo yes || echo NO)"
[ "$pw" = present ] || fail=1
}

# --- a worktree of a scratch repository, for (a) and (b) ---------------------------------------------------------
P=$T/gate
if wants a || wants b; then
  mkdir -p "$P/repo" "$P/gate-tmp" "$P/uv" "$P/pip" "$P/npm" "$P/go"
  ( cd "$P/repo" && git init -q && git -c user.email=l4@local -c user.name=l4 commit -q --allow-empty -m init \
    && git worktree add -q "$P/wt" -b probe-wt ) || { say "RESULT: SETUP FAILED (git worktree)"; fail=1; }
fi

# --- (a) Playwright in the gate argv --------------------------------------------------------------------------------
wants a && {
section "(a) pytest-playwright in one gate spawn (--unshare-net), without and with --tmpfs /dev/shm"
if [ -d "$P/wt" ]; then
  mkdir -p "$P/wt/site" "$P/wt/e2e" "$P/wt/.l4-out"
  printf '<!doctype html><title>m15 probe</title><h1 data-testid="x">ok</h1>\n' > "$P/wt/site/index.html"
  cat > "$P/wt/e2e/test_probe.py" <<'T_EOF'
import os


def test_title(page):
    page.goto(os.environ["L4_E2E_BASE_URL"] + "/")
    assert page.title() == "m15 probe"
    assert page.get_by_test_id("x").inner_text() == "ok"
T_EOF
  cat > "$P/wt/launch.sh" <<'L_EOF'
#!/bin/sh
# one gate spawn: the server and the tests share this network namespace's loopback
python3 -m http.server 18765 --bind 127.0.0.1 --directory site >/dev/null 2>&1 &
server=$!
i=0
while [ $i -lt 50 ]; do
  python3 -c 'import socket; socket.create_connection(("127.0.0.1", 18765), 1)' 2>/dev/null && break
  i=$((i + 1)); sleep 0.2
done
L4_E2E_BASE_URL=http://127.0.0.1:18765 .venv/bin/python -m pytest -q e2e --junitxml=.l4-out/junit-e2e.xml -p no:cacheprovider
code=$?
kill $server 2>/dev/null
exit $code
L_EOF
  chmod +x "$P/wt/launch.sh"
  if ( cd "$P/wt" && uv venv -q .venv && uv pip install -q --python .venv/bin/python "playwright==$PW_VERSION" "pytest-playwright==$PYTEST_PW_VERSION" ) >"$T/a-setup.log" 2>&1; then
    say "setup: venv with playwright $PW_VERSION, pytest-playwright $PYTEST_PW_VERSION"
    # the gate environment: build_gate_env = base + one variable per cache mount (the playwright one is read-only)
    run_variant() {  # label extra-bwrap-flags...
      local label=$1; shift
      rm -f "$P/wt/.l4-out/junit-e2e.xml"
      local -a envp=()
      while IFS= read -r line; do envp+=("$line"); done < <(M0_NET=unshare m0_gate_env "$P/gate-tmp" \
        "UV_CACHE_DIR=$P/uv" "PIP_CACHE_DIR=$P/pip" "npm_config_cache=$P/npm" "GOMODCACHE=$P/go" "PLAYWRIGHT_BROWSERS_PATH=$PW_DIR")
      argv_to_array < <(M0_NET=unshare m0_argv "" "$P/wt" "$P/repo/.git" "$P/gate-tmp" "cache:$P/uv" "cache:$P/pip" \
        "cache:$P/npm" "cache:$P/go" "rocache:$PW_DIR" ${CI_PROJECT_DIR:+"hide:${CI_PROJECT_DIR%/}.tmp"} "${envp[@]}" -- ./launch.sh)
      local -a argv=(); local n
      for n in "${BW[@]}"; do  # extra flags go with the base flags, after `--dev /dev` (which would cover an earlier /dev/shm)
        if [ "$n" = --die-with-parent ]; then argv+=("$@"); fi
        argv+=("$n")
      done
      local out="$T/a-$label.out" line rc
      python3 "$T/tool.py" rss "$out" 240 env -i PATH="$PATH" "${argv[@]}" | tee "$T/a-$label.rss" >/dev/null
      rc=$(sed -n 's/^__RSS exit=\([0-9-]*\).*/\1/p' "$T/a-$label.rss")
      local verdict=FAIL
      [ "$rc" = 0 ] && grep -q 'testcase' "$P/wt/.l4-out/junit-e2e.xml" 2>/dev/null && verdict=PASS
      say "RESULT (a) $label: $verdict | $(sed 's/^__RSS //' "$T/a-$label.rss")"
      if [ "$verdict" = FAIL ]; then say "  --- last lines of the gate output ($label)"; tail -n 15 "$out" | cut -c1-240 | sed 's/^/  | /'; fi
      [ "$verdict" = PASS ]
    }
    run_variant no-shm-tmpfs; a1=$?
    run_variant with-shm-tmpfs --tmpfs /dev/shm; a2=$?
    if [ $a1 -eq 0 ]; then say "RESULT P1: Chromium works in the gate argv without --tmpfs /dev/shm -> do NOT change bwrap.base_flags"
    elif [ $a2 -eq 0 ]; then say "RESULT P1: fails without, passes with --tmpfs /dev/shm -> add it to the gate kind"
    else say "RESULT P1: fails in both variants -> see the output above; Chromium in the gate sandbox needs another change"; fail=1; fi
  else
    say "RESULT (a): SETUP FAILED (uv venv / pip install)"; tail -n 8 "$T/a-setup.log" | sed 's/^/  | /'; fail=1
  fi
fi
}

# --- (b) Serena inside the agent argv --------------------------------------------------------------------------------
wants b && {
section "(b) serena start-mcp-server --context codex inside the agent argv"
B=$T/agent; mkdir -p "$B/tmp/serena-home" "$B/uv"
if [ -d "$P/wt" ]; then
  W=$P/wt
  printf 'def add(a, b):\n    return a + b\n' > "$W/calc.py"
  printf 'base_modes:\n  - editing\nprojects: []\n' > "$B/tmp/serena-home/serena_config.yml"
  envb=(); while IFS= read -r line; do envb+=("$line"); done < <(m0_env "$B/tmp" "UV_CACHE_DIR=$B/uv" "SERENA_HOME=$B/tmp/serena-home" "UV_TOOL_DIR=$B/tmp/uv-tools" "CI=true")
  argv_to_array < <(m0_argv codex "$W" "$P/repo/.git" "$B/tmp" "cache:$B/uv" ${CI_PROJECT_DIR:+"hide:${CI_PROJECT_DIR%/}.tmp"} \
    "${envb[@]}" -- serena start-mcp-server --context codex --project "$W" --enable-web-dashboard false \
    --open-web-dashboard false --mode one-shot --mode no-onboarding)
  python3 "$T/tool.py" mcp "$B/serena.err" 120 env -i PATH="$PATH" "${BW[@]}" | tee "$T/b.out" >/dev/null
  say "RESULT (b): $(sed 's/^__MCP //' "$T/b.out")"
  grep -qi 'symbols_overview=FAILED' "$T/b.out" && { say "  --- serena stderr (errors and pyright lines)"; \
    grep -iE 'error|exception|pyright|uvx|failed' "$B/serena.err" | tail -n 14 | cut -c1-260 | sed 's/^/  | /'; }
  grep -q 'initialize=ok' "$T/b.out" || { fail=1; tail -n 15 "$B/serena.err" | cut -c1-240 | sed 's/^/  | /'; }
  say "  note: UV_CACHE_DIR is the empty per-unit cache and UV_TOOL_DIR a writable temp dir (without it uvx cannot create"
  say "        its tool environment under the read-only HOME and the language server dies). symbols_overview starts the"
  say "        language server (Pyright via uvx); pyright/node/uv in procs= show it ran, and its time includes any download."
fi
}

# --- (c) laya-serve with the typed-decisions checkpoint ---------------------------------------------------------------
wants c && {
section "(c) laya-serve (typed-decisions), 5 noul calls, tokenizer budget"
LAYA_PY=$HOME_DIR/.local/share/uv/tools/laya/bin/python
LPORT=$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
say "laya $("$LAYA_PY" -c 'import importlib.metadata as m; print(m.version("laya"))' 2>&1 | tail -1), port $LPORT, threads $LAYA_THREADS_N"
say "$(free -m | sed -n '2p')"
python3 "$T/tool.py" laya "$T/laya.err" 400 "$LPORT" typed-decisions env -i HOME="$HOME_DIR" PATH="$PATH" LANG=C.UTF-8 \
  LAYA_HOST=127.0.0.1 LAYA_PORT="$LPORT" LAYA_MODELS=typed-decisions LAYA_PRELOAD=1 LAYA_DEVICE=cpu LAYA_MAX_LOADED=1 \
  LAYA_THREADS="$LAYA_THREADS_N" OMP_NUM_THREADS="$LAYA_THREADS_N" HF_HUB_OFFLINE=1 laya-serve | tee "$T/c.out" >/dev/null
say "RESULT (c): $(sed 's/^__LAYA //' "$T/c.out")"
grep -q 'ready=yes' "$T/c.out" || { fail=1; tail -n 15 "$T/laya.err" | cut -c1-240 | sed 's/^/  | /'; }
if grep -q 'ready=yes' "$T/c.out"; then
  rss=$(sed -n 's/.*tree_peak_kb=\([0-9]*\).*/\1/p' "$T/c.out")
  if [ "${rss:-0}" -le 1258291 ]; then say "RESULT P2: peak tree RSS ${rss} kB <= 1.2 GB (1258291 kB) -> Laya runs on the runner (engine laya-local)"
  else say "RESULT P2: peak tree RSS ${rss} kB > 1.2 GB (1258291 kB) -> Laya runs on the Mac (engine remote), unless (d) fails"; fi
fi
"$LAYA_PY" "$T/tokens.py" 2>&1 | grep '^__TOK' | sed 's/^__TOK /RESULT (c) tokens: /' | tee "$T/tok.out"
sed -n 's/^RESULT (c) tokens: budget_P3=\([0-9]*\).*/RESULT P3: the S1 state budget is \1 approx-tokens (chars \/ 4), the largest whose Laya token count fits the window/p' "$T/tok.out"
grep -q 'budget_P3' "$T/tok.out" || fail=1
say "$(free -m | sed -n '2p')"
}

# --- (d) the Mac ----------------------------------------------------------------------------------------------------
wants d && {
section "(d) TCP connect from the runner to $MAC_HOST"
for port in $MAC_PORTS; do
  res=$(python3 - "$MAC_HOST" "$port" <<'C_EOF'
import socket, sys, time
began = time.time()
try:
    socket.create_connection((sys.argv[1], int(sys.argv[2])), 4).close()
    print("ok")
except ConnectionRefusedError:
    print("refused (the host answers, nothing listens)")
except OSError as exc:
    print(f"unreachable ({type(exc).__name__})")
print(f"{time.time() - began:.2f}s")
C_EOF
)
  say "RESULT (d): $MAC_HOST:$port connect $(echo "$res" | head -1) in $(echo "$res" | tail -1)"
done
}

section "end"
say "$(free -m | sed -n '1,2p')"
say "VERDICT $([ "$fail" = 0 ] && echo 'all measurements ran' || echo 'at least one measurement failed (see RESULT lines)')"
exit "$fail"
