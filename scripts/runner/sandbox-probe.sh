#!/usr/bin/env bash
# sandbox-probe.sh — does an agent CLI work INSIDE the L4 agent sandbox (bubblewrap) on this host, run as the runner
# user? Answers the M0 question "nested sandbox or sandbox.mode none" with evidence (SPEC L4-SEC-005, decision Q6).
#
# For each CLI: build a scratch uv project + git repo (stands in for the unit worktree), run `uv sync` OUTSIDE the
# sandbox (the harness installs dependencies before agent steps — the sandbox may have no package-index access), then
# run the agent inside
#   bwrap --ro-bind / / --dev /dev --proc /proc --tmpfs /tmp --unshare-pid --unshare-ipc --share-net --die-with-parent
#         --bind <worktree> <worktree> --bind <the CLI's own state dirs> ...      (everything else read-only)
# asking it to implement one function and run the tests with .venv/bin/python -m pytest. One line per CLI:
#   SANDBOX <cli> | PASS|FAIL | <seconds>s | exit=<agent exit> edit=<yes|no> tests=<pass|fail> testdiff=<none|stat> | <tail>
#
#   scripts/runner/mk-ssh.sh --script scripts/runner/sandbox-probe.sh       # CLIS="claude codex opencode" by default
#   CLIS=codex SANDBOX=none bash sandbox-probe.sh                           # same task without bwrap, for comparison
#   CLIS="codex claude" SANDBOX=m0 bash sandbox-probe.sh                    # the production M0 agent profile, see below
#
# SANDBOX=m0 builds EXACTLY the argv that l4.sandbox.bwrap.BwrapSandbox.build_argv builds for an agent (the functions
# between the "m0-profile" markers, environment included; tests/unit/sandbox/test_probe_parity.py diffs the two): the proven base plus
# --proc /proc, --dev /dev, a tmpfs over every OTHER adapter's login, the main repository's .git read-only (the work
# runs in a `git worktree`, as in production), a tmpfs over each existing repo guidance dir of the worktree (HB-X1, after every bind), --clearenv and the allow-listed environment. It also runs the isolation
# canaries inside that sandbox (no inherited env, no ancestor /proc/*/environ, no other login, .git not writable, no docker/containerd/dbus socket reachable, DNS resolves: HB-1) and
# runs codex as the implementer (`exec --json -s workspace-write --ignore-user-config --ignore-rules
# -c project_doc_max_bytes=0 --output-schema S -o R -`, prompt on stdin), claude as the judge (`-p --output-format json --json-schema S --safe-mode
# --strict-mcp-config --tools "" --no-session-persistence`, prompt on stdin) and opencode as the implementer
# (`run --pure --format json -m opencode/big-pickle --dir <worktree>`, an empty XDG_CONFIG_HOME in the private dir,
# the OPENCODE_DISABLE_* switches and OPENCODE_CONFIG_CONTENT, as l4.agents.opencode builds them; prompt on stdin).
set -u
RUNNER_USER=${RUNNER_USER:-gitlab-runner}
CLIS=${CLIS:-"claude codex opencode"}
SANDBOX=${SANDBOX:-bwrap}
TIMEOUT=${TIMEOUT:-300}
RHOME=$(getent passwd "$RUNNER_USER" | cut -d: -f6)
INNER=$(mktemp /tmp/l4-sbx-inner-XXXX.sh); chmod 644 "$INNER"; trap 'rm -f "$INNER"' EXIT

# --- m0-profile begin (keep in step with src/l4/sandbox/bwrap.py; one token per output line) ---
m0_cred_paths() {  # adapter -> its login paths (SPEC sandbox.credential_paths defaults)
  case "$1" in
    codex) echo "$HOME/.codex";;
    claude-code) echo "$HOME/.claude"; echo "$HOME/.claude.json";;
    opencode) echo "$HOME/.local/share/opencode"; echo "$HOME/.config/opencode"; echo "$HOME/.cache/opencode";;
    kiro-cli) echo "$HOME/.kiro"; echo "$HOME/.aws/sso/cache"; echo "$HOME/.local/share/kiro-cli"; echo "$HOME/Library/Application Support/kiro-cli";;
  esac
}
m0_hide() {  # a directory is covered by a tmpfs, a file by /dev/null, a missing path is skipped
  if [ -d "$1" ]; then printf '%s\n' --tmpfs "$1"
  elif [ -e "$1" ]; then printf '%s\n' --ro-bind /dev/null "$1"; fi
}
m0_guidance() {  # worktree -> a tmpfs over each EXISTING repo guidance dir (HB-X1; l4.sandbox.base.GUIDANCE_DIRS); a missing
  # one is skipped (bwrap cannot mkdir under a read-only root), so is a symlink (bwrap resolves it: `.claude -> /etc`)
  local rel
  for rel in .claude .agents .codex .opencode .hermes .kiro/steering .kiro/agents .kiro/settings .kiro/hooks .kiro/prompts; do
    if [ -d "$1/$rel" ] && [ ! -L "$1/$rel" ]; then printf '%s\n' --tmpfs "$1/$rel"; fi
  done
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
m0_argv() {  # adapter worktree git-common-dir private-dir [cache:DIR|rocache:DIR|hide:DIR|chdir:DIR...] NAME=VALUE... -- command...
  local adapter=$1 wt=$2 gd=$3 tmp=$4 other p cwd=$2
  local -a caches=() hides=()
  shift 4
  while [ "$#" -gt 0 ]; do
    case "$1" in
      cache:*) caches+=(--bind "${1#cache:}" "${1#cache:}");;
      rocache:*) caches+=(--ro-bind "${1#rocache:}" "${1#rocache:}");;
      hide:*) hides+=("${1#hide:}");;  # the CI runner's <CI_PROJECT_DIR>.tmp: l4.sandbox.base.runner_tmp_paths
      chdir:*) cwd=${1#chdir:};;  # a tool-less call starts in an empty dir of the private dir, not in the worktree
      *) break;;
    esac
    shift
  done
  printf '%s\n' bwrap --ro-bind / / --dev /dev --proc /proc --tmpfs /tmp
  m0_masks
  printf '%s\n' --unshare-pid --unshare-ipc --share-net --die-with-parent
  for other in codex claude-code opencode kiro-cli; do
    [ "$other" = "$adapter" ] && continue
    m0_cred_paths "$other" | while IFS= read -r p; do m0_hide "$p"; done
  done
  for p in ${hides[@]+"${hides[@]}"}; do m0_hide "$p"; done
  m0_cred_paths "$adapter" | while IFS= read -r p; do if [ -e "$p" ]; then printf '%s\n' --bind "$p" "$p"; fi; done
  printf '%s\n' --bind "$wt" "$wt" --bind "$tmp" "$tmp" \
    ${caches[@]+"${caches[@]}"} --ro-bind "$gd" "$gd"
  m0_guidance "$wt"  # after every bind: a later bind at or above the worktree would put the host dirs back
  printf '%s\n' --clearenv
  while [ "$#" -gt 0 ] && [ "$1" != -- ]; do printf '%s\n' --setenv "${1%%=*}" "${1#*=}"; shift; done
  shift
  printf '%s\n' --chdir "$cwd" -- "$@"
}
# --- m0-profile end ---

declare -f m0_cred_paths m0_hide m0_guidance m0_norm m0_link_end m0_masks m0_env m0_argv > "$INNER"
cat >> "$INNER" <<'INNER_EOF'
#!/usr/bin/env bash
# runs as the runner user in a login shell; $1 = cli, $2 = sandbox mode, $3 = timeout
cli=$1; mode=$2; tmo=$3
TASK='In this repository, edit src/calc/__init__.py so that add(a, b) returns a + b (it currently raises NotImplementedError). Then run the tests with exactly: .venv/bin/python -m pytest -q . Do not modify tests. Reply with DONE when finished.'
cd ~ || exit 9
W=$(mktemp -d ~/.l4-sbx-XXXX); cd "$W" || exit 9
mkdir -p src/calc tests
cat > pyproject.toml <<'P'
[project]
name = "calc"
version = "0"
requires-python = ">=3.11"
[dependency-groups]
dev = ["pytest"]
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
[tool.hatch.build.targets.wheel]
packages = ["src/calc"]
P
printf 'def add(a, b):\n    raise NotImplementedError\n' > src/calc/__init__.py
printf 'from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n' > tests/test_calc.py
git init -q && git -c user.email=l4@local -c user.name=l4 add -A && git -c user.email=l4@local -c user.name=l4 commit -qm init
R=$W   # where the agent works: the repository itself, or in m0 mode a worktree of it (as in production)
if [ "$mode" = m0 ]; then
  R=$(mktemp -d ~/.l4-sbx-wt-XXXX); rmdir "$R"
  git worktree add -q "$R" -b l4-probe || { echo "__SETUP=git worktree add failed"; exit 9; }
  RES=$W/.l4-res; mkdir -p "$RES"
fi
cd "$R" || exit 9
uv sync -q || { echo "__SETUP=uv sync failed"; exit 9; }
M0_CANARY=; M0_RESULT=n/a
case "$cli" in
  claude)   binds=(--bind "$HOME/.claude" "$HOME/.claude" --bind "$HOME/.claude.json" "$HOME/.claude.json")
            run=(claude -p "$TASK" --model haiku --max-turns 12 --output-format json --permission-mode acceptEdits
                 --allowedTools "Read,Edit,Write,Bash(.venv/bin/python -m pytest:*)" --strict-mcp-config);;
  codex)    binds=(--bind "$HOME/.codex" "$HOME/.codex")
            run=(codex exec --json --ignore-user-config --ignore-rules -s workspace-write "$TASK");;
  opencode) mkdir -p "$W/.l4-xdg"
            binds=(--bind "$HOME/.local/share/opencode" "$HOME/.local/share/opencode" --bind "$HOME/.cache" "$HOME/.cache")
            export XDG_CONFIG_HOME="$W/.l4-xdg" OPENCODE_CONFIG_CONTENT='{"permission":{"edit":"allow","bash":"allow"}}'
            run=(opencode run -m opencode/big-pickle "$TASK");;
esac
if [ "$mode" = m0 ]; then
  case "$cli" in
    claude) m0_adapter=claude-code
            m0_run=(claude -p --model haiku --output-format json --safe-mode --strict-mcp-config --tools ""
                    --no-session-persistence --max-turns 3
                    --json-schema '{"type":"object","required":["ok"],"properties":{"ok":{"enum":["L4-OK"]}}}')
            m0_prompt='Return the JSON object with ok set to L4-OK.';;
    codex)  m0_adapter=codex
            printf '%s' '{"type":"object","required":["summary"],"properties":{"summary":{"type":"string"}},"additionalProperties":false}' > "$RES/schema.json"
            m0_run=(codex exec --json -s workspace-write --ignore-user-config --ignore-rules -c project_doc_max_bytes=0
                    --output-schema "$RES/schema.json" -o "$RES/result.json" -)
            m0_prompt=$TASK;;
    opencode) m0_adapter=opencode
            mkdir -p "$RES/opencode-config"
            m0_run=(opencode run --pure --format json -m opencode/big-pickle --dir "$R" --title "l4 probe")
            m0_prompt=$TASK;;
  esac
  # the four per-unit read-write cache mounts of the production agent step (sandbox.caches defaults)
  cache_args=(); extra=()
  for pair in uv:UV_CACHE_DIR pip:PIP_CACHE_DIR npm:npm_config_cache go:GOMODCACHE; do
    mkdir -p "$W/.l4-cache/${pair%%:*}"
    cache_args+=("cache:$W/.l4-cache/${pair%%:*}"); extra+=("${pair#*:}=$W/.l4-cache/${pair%%:*}")
  done
  case "${CI_PROJECT_DIR:-}" in /*) cache_args+=("hide:${CI_PROJECT_DIR%/}.tmp");; esac  # runner_tmp_paths
  [ "$cli" = claude ] && extra+=("CLAUDE_CODE_MAX_RETRIES=1")
  if [ "$cli" = opencode ]; then
    extra+=("XDG_CONFIG_HOME=$RES/opencode-config" OPENCODE_DISABLE_PROJECT_CONFIG=1 OPENCODE_DISABLE_CLAUDE_CODE=1
            OPENCODE_DISABLE_EXTERNAL_SKILLS=1 OPENCODE_DISABLE_AUTOUPDATE=1
            "OPENCODE_CONFIG_CONTENT={\"snapshot\":false,\"share\":\"disabled\",\"autoupdate\":false,\"permission\":{\"edit\":\"allow\",\"read\":\"allow\",\"glob\":\"allow\",\"grep\":\"allow\",\"list\":\"allow\",\"bash\":{\"*\":\"allow\"},\"external_directory\":{\"*\":\"deny\",\"$RES/**\":\"allow\",\"$RES/*\":\"allow\"},\"webfetch\":\"deny\",\"websearch\":\"deny\",\"question\":\"deny\",\"doom_loop\":\"deny\"}}")
  fi
  envp=(); while IFS= read -r line; do envp+=("$line"); done < <(m0_env "$RES" ${extra[@]+"${extra[@]}"})
  m0_argv_array() {  # command... -> M0_ARGV: the production agent argv around it
    local line; M0_ARGV=()
    while IFS= read -r line; do M0_ARGV+=("$line"); done < <(m0_argv "$m0_adapter" "$R" "$W/.git" "$RES" "${cache_args[@]}" "${envp[@]}" -- "$@")
  }
  canary="canary-$RANDOM$RANDOM"; export L4_PROBE_CANARY=$canary
  others=()
  for o in codex claude-code opencode kiro-cli; do
    [ "$o" = "$m0_adapter" ] && continue
    while IFS= read -r p; do others+=("$p"); done < <(m0_cred_paths "$o")
  done
  # a file, not `sh -c`: the argv travels one token per line, so no argument may contain a newline
  cat > "$RES/canary.sh" <<'CANARY_EOF'
canary=$1; gd=$2; dns=$3; wt=$4; shift 4; bad=""
[ -z "${L4_PROBE_CANARY:-}" ] || bad="$bad env-leak"
if cat /proc/[0-9]*/environ 2>/dev/null | tr '\0' '\n' | grep -q "^L4_PROBE_CANARY=$canary"; then bad="$bad proc-environ"; fi
for p in "$@"; do
  if [ -d "$p" ] && [ -n "$(ls -A "$p" 2>/dev/null)" ]; then bad="$bad login:$p"; fi
  if [ -f "$p" ] && [ -s "$p" ]; then bad="$bad login:$p"; fi
done
for g in .claude .agents; do  # HB-X1: a planted repo guidance dir is empty inside the sandbox
  if [ -n "$(ls -A "$wt/$g" 2>/dev/null)" ]; then bad="$bad guidance-visible:$g"; fi
done
if touch "$gd/l4-probe-write" 2>/dev/null; then bad="$bad git-writable"; fi
# HB-1: no container/system daemon socket is reachable (the runner user may be in group docker): a connect to the
# docker socket must fail, and /run/containerd and /run/dbus must hold nothing; DNS must still resolve (agent kind)
for s in /var/run/docker.sock /run/docker.sock /run/containerd/containerd.sock /run/podman/podman.sock /run/dbus/system_bus_socket; do
  [ -e "$s" ] && bad="$bad socket-visible:$s"
done
for d in /run/containerd /run/dbus; do
  [ -n "$(ls -A "$d" 2>/dev/null)" ] && bad="$bad run-not-empty:$d"
done
if command -v python3 >/dev/null 2>&1; then
  python3 - <<'PY' || bad="$bad docker-socket-connect"
import socket, sys
s = socket.socket(socket.AF_UNIX)
s.settimeout(3)
try:
    s.connect("/var/run/docker.sock")
    s.sendall(b"GET /_ping HTTP/1.0\r\n\r\n")
    sys.exit(1 if b"200" in s.recv(64) else 0)  # reached the daemon: the sandbox is broken
except OSError:
    sys.exit(0)  # blocked, as intended
PY
else
  bad="$bad no-python3-for-docker-check"
fi
if ! getent hosts "$dns" >/dev/null 2>&1; then bad="$bad dns-fails:$dns"; fi
echo "${bad:-ok}"
CANARY_EOF
  mkdir -p "$R/.claude/skills/l4-canary" "$R/.agents/skills/l4-canary"  # planted guidance (HB-X1); the worktree is thrown away
  echo canary > "$R/.claude/skills/l4-canary/SKILL.md"; echo canary > "$R/.agents/skills/l4-canary/SKILL.md"
  m0_argv_array sh "$RES/canary.sh" "$canary" "$W/.git" "${L4_PROBE_DNS_HOST:-pypi.org}" "$R" "${others[@]}"
  M0_CANARY=$(env -i PATH="$PATH" "${M0_ARGV[@]}" </dev/null 2>&1 | tail -1)
  unset L4_PROBE_CANARY
  m0_argv_array "${m0_run[@]}"
  printf '%s' "$m0_prompt" | timeout "$tmo" env -i PATH="$PATH" "${M0_ARGV[@]}" > "$W/.agent.out" 2>&1
  echo "__AGENT_EXIT=${PIPESTATUS[1]}"
  if [ "$cli" = codex ] || [ "$cli" = opencode ]; then
    grep -q 'return a + b' src/calc/__init__.py && echo __EDIT=yes || echo __EDIT=no
    if [ "$cli" = codex ]; then [ -s "$RES/result.json" ] && M0_RESULT=yes || M0_RESULT=no; fi
  else
    grep -q 'L4-OK' "$W/.agent.out" && echo __EDIT=n/a || echo __EDIT=no
  fi
else
  if [ "$mode" = bwrap ]; then
    timeout "$tmo" bwrap --ro-bind / / --dev /dev --proc /proc --tmpfs /tmp --unshare-pid --unshare-ipc --share-net \
      --die-with-parent --bind "$W" "$W" "${binds[@]}" --chdir "$W" -- "${run[@]}" </dev/null > "$W/.agent.out" 2>&1
  else
    timeout "$tmo" "${run[@]}" </dev/null > "$W/.agent.out" 2>&1
  fi
  echo "__AGENT_EXIT=$?"
  grep -q 'return a + b' src/calc/__init__.py && echo __EDIT=yes || echo __EDIT=no
fi
.venv/bin/python -m pytest -q >/dev/null 2>&1 && echo __TESTS=pass || echo __TESTS=fail
echo "__TESTDIFF=$(git diff --stat -- tests | tail -1)"
echo "__CANARY=$M0_CANARY"
echo "__RESULT=$M0_RESULT"
echo "__TAIL=$(tail -c 400 "$W/.agent.out" | tr '\n' ' ')"
cd ~ && { git -C "$W" worktree remove --force "$R" 2>/dev/null; rm -rf "$W" "$R"; }
INNER_EOF

fail=0
for cli in $CLIS; do
  start=$(date +%s.%N)
  if [ "$(id -un)" = "$RUNNER_USER" ]; then out=$(bash --login "$INNER" "$cli" "$SANDBOX" "$TIMEOUT" 2>&1)
  else out=$(sudo -n -u "$RUNNER_USER" -H env -i HOME="$RHOME" TERM=dumb bash --login "$INNER" "$cli" "$SANDBOX" "$TIMEOUT" 2>&1); fi
  secs=$(LC_ALL=C awk -v s="$start" -v e="$(date +%s.%N)" 'BEGIN{printf "%.1f", e-s}')
  g() { echo "$out" | sed -n "s/^__$1=//p" | tail -1; }
  ex=$(g AGENT_EXIT); ed=$(g EDIT); te=$(g TESTS); td=$(g TESTDIFF); tl=$(g TAIL | cut -c1-300)
  sk=$(g SKIP); cn=$(g CANARY); rs=$(g RESULT)
  if [ -n "$sk" ]; then echo "SANDBOX $cli ($SANDBOX) | SKIP | | $sk"; continue; fi
  st=FAIL
  if [ "$SANDBOX" = m0 ]; then
    # codex (implementer): edit, tests, -o result file. opencode (implementer): edit, tests. claude (judge): replied
    # L4-OK. All: canaries clean, tests untouched
    if [ "$ex" = 0 ] && [ -z "$td" ] && [ "$cn" = ok ]; then
      if [ "$cli" = codex ] && [ "$ed" = yes ] && [ "$te" = pass ] && [ "$rs" = yes ]; then st=PASS; fi
      if [ "$cli" = opencode ] && [ "$ed" = yes ] && [ "$te" = pass ]; then st=PASS; fi
      if [ "$cli" = claude ] && [ "$ed" = n/a ]; then st=PASS; fi
    fi
    extra=" canary=${cn:-?} result=$rs"
  else
    [ "$ex" = 0 ] && [ "$ed" = yes ] && [ "$te" = pass ] && [ -z "$td" ] && st=PASS
    extra=
  fi
  [ $st = PASS ] || fail=1
  echo "SANDBOX $cli ($SANDBOX) | $st | ${secs}s | exit=$ex edit=$ed tests=$te testdiff=${td:-none}$extra | $([ $st = PASS ] || echo "$tl")"
  if [ -z "$ex" ]; then echo "$out" | tail -5 | sed 's/^/  setup: /'; fi
done
exit $fail
