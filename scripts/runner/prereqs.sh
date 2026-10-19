#!/usr/bin/env bash
# prereqs.sh — reproducible prerequisites for a GitLab *shell-executor* runner host that runs the L4 harness.
#
#   bash prereqs.sh --check            # default: changes nothing; exit 1 if any required step is not satisfied
#   bash prereqs.sh --apply            # idempotent: fixes/installs what is missing, then re-checks
#   bash prereqs.sh --apply --with-serena --with-playwright --with-laya   # optional extras
#   bash prereqs.sh --apply --adopt-logins-from admin            # move Claude/Codex logins made as another user
#
# Remotely through the Mintkey SSH bastion (see docs/runner/README.md):
#   scripts/runner/mk-ssh.sh --script scripts/runner/prereqs.sh -- --apply
#
# Run it as an admin user with (passwordless) sudo on the runner host. System changes use sudo; every per-user tool
# is installed AS the runner user into its home (~/.local/bin, ~/.local/share/l4), never system-wide.
# It never authenticates any agent CLI and never reads credential contents: PRQ-12 reports presence only and prints
# the human steps. Every step prints one line: "[PRQ-nn] <STATUS> <title> — <detail>" with STATUS in
# OK | MISSING | FIXED | FAILED | WARN | SKIP | INFO.
#
# Pinned versions (override with env vars). Verified current on 2026-10-03 against the npm/PyPI registries.
set -uo pipefail

RUNNER_USER=${RUNNER_USER:-gitlab-runner}
UV_VERSION=${UV_VERSION:-0.12.22}
PYTHON_VERSION=${PYTHON_VERSION:-3.12}
NODE_MIN=${NODE_MIN:-20.19.0}             # OpenSpec 1.14.0 engines requirement
NODE_VERSION=${NODE_VERSION:-22.23.0}     # installed user-locally only when node is missing or older than NODE_MIN
OPENSPEC_VERSION=${OPENSPEC_VERSION:-1.14.0}
CLAUDE_VERSION=${CLAUDE_VERSION:-2.1.288}
CODEX_VERSION=${CODEX_VERSION:-0.160.0}
OPENCODE_VERSION=${OPENCODE_VERSION:-1.18.34}
SERENA_VERSION=${SERENA_VERSION:-1.7.0}
PLAYWRIGHT_VERSION=${PLAYWRIGHT_VERSION:-1.63.0}
KIRO_VERSION=${KIRO_VERSION:-2.28.0}       # floor, not an exact pin: the installer has no version argument (it installs `latest`)
# The Laya pin and checkpoint are those of l4.provision.catalog (a drift test compares them); `l4 doctor --ci --fix`
# installs the same Laya for a `laya-local` profile, so a runner provisioned here downloads nothing again.
LAYA_VERSION=${LAYA_VERSION:-0.3.24}
LAYA_CHECKPOINT=${LAYA_CHECKPOINT:-typed-decisions}   # subfolder of convaiinnovations/laya that PRQ-18 prefetches
LAYA_REVISION=${LAYA_REVISION:-7b928d828b7b0e022f929d9bd2e44165aa270148}   # the commit it is fetched at, never a branch
GIT_MIN=${GIT_MIN:-2.34.0}
APT_PACKAGES=${APT_PACKAGES:-"bubblewrap git curl jq ca-certificates xz-utils unzip"}

MODE=check; WITH_SERENA=0; WITH_PLAYWRIGHT=0; WITH_LAYA=0; WITH_KIRO=1; ADOPT_FROM=""
while [ $# -gt 0 ]; do
  a=$1; shift
  case "$a" in
    --adopt-logins-from) ADOPT_FROM=${1:?--adopt-logins-from needs a user}; shift;;
    --check) MODE=check;; --apply) MODE=apply;;
    --with-serena) WITH_SERENA=1;; --with-playwright) WITH_PLAYWRIGHT=1;; --with-laya) WITH_LAYA=1;; --without-kiro) WITH_KIRO=0;;
    -h|--help) sed -n '2,20p' "$0"; exit 0;;
    *) echo "unknown argument: $a" >&2; exit 2;;
  esac
done

if [ "$(id -u)" -eq 0 ]; then SUDO=""; elif sudo -n true 2>/dev/null; then SUDO="sudo -n"; else
  echo "prereqs.sh needs root or passwordless sudo (system steps and running as $RUNNER_USER)" >&2; exit 2; fi
RHOME=$(getent passwd "$RUNNER_USER" | cut -d: -f6)
[ -n "$RHOME" ] || { echo "runner user '$RUNNER_USER' does not exist — install and register gitlab-runner first" >&2; exit 2; }
L4_HOME="$RHOME/.local/share/l4"
# Where the harness's gate sandbox mounts Chromium read-only: $L4_CACHE/shared/ms-playwright (defaults.CACHES), and
# $L4_CACHE defaults to ~/.cache/l4 (L4-CFG-005). M15-G2(e) shows whether a job resolves it differently.
PW_PATH=${PW_PATH:-$RHOME/.cache/l4/shared/ms-playwright}

# Run a command as the runner user in the same kind of shell the shell executor uses (bash --login, fresh env).
as_runner() { $SUDO -u "$RUNNER_USER" -H env -i HOME="$RHOME" USER="$RUNNER_USER" LOGNAME="$RUNNER_USER" \
              TERM=dumb bash --login -c "cd ~ && { $1; }"; }   # cd ~: tools like uv read config from the cwd
ver_ge() { [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -1)" = "$2" ]; }   # ver_ge A B  ⇔  A >= B

FAILS=0; MISSING=0; WARNS=0
report() { printf '[%s] %-7s %s — %s\n' "$1" "$2" "$3" "$4";
  case "$2" in FAILED) FAILS=$((FAILS+1));; MISSING) MISSING=$((MISSING+1));; WARN) WARNS=$((WARNS+1));; esac; }

# step ID TITLE CHECK_FN APPLY_FN — CHECK_FN sets DETAIL and returns 0 when satisfied.
step() {
  local id=$1 title=$2 check=$3 apply=$4
  DETAIL=""
  if $check; then report "$id" OK "$title" "$DETAIL"; return; fi
  if [ "$MODE" = check ] || [ -z "$apply" ]; then report "$id" MISSING "$title" "$DETAIL"; return; fi
  local before=$DETAIL
  if $apply >/tmp/l4-prereqs-$id.log 2>&1 && $check; then report "$id" FIXED "$title" "$before → $DETAIL"
  else report "$id" FAILED "$title" "$DETAIL (apply log: /tmp/l4-prereqs-$id.log: $(tail -3 /tmp/l4-prereqs-$id.log | tr '\n' ' '))"; fi
}

echo "L4 runner prerequisites — mode=$MODE host=$(hostname) runner_user=$RUNNER_USER date=$(date -u +%FT%TZ)"

# PRQ-01 — The shell executor starts every job with `bash --login` as the runner user. Ubuntu's default
# ~/.bash_logout runs `clear_console -q` when SHLVL=1; without a console it fails, and GitLab reports
# "ERROR: Job failed: prepare environment: exit status 1" before any script runs (observed: dummy-agentic job 5415).
check_logout() {
  if $SUDO test -f "$RHOME/.bash_logout" && $SUDO grep -q '^[^#]*clear_console' "$RHOME/.bash_logout"; then
    DETAIL="$RHOME/.bash_logout runs clear_console"; return 1; fi
  local rc; as_runner 'exit 0' </dev/null >/dev/null 2>&1; rc=$?
  DETAIL="bash --login as $RUNNER_USER exits $rc"; [ "$rc" -eq 0 ]
}
apply_logout() { $SUDO mv "$RHOME/.bash_logout" "$RHOME/.bash_logout.disabled-by-l4"; }
step PRQ-01 "login shell exits cleanly (no clear_console in .bash_logout)" check_logout apply_logout

# PRQ-02 — System packages (the only root-level installs). bubblewrap is the L4 sandbox (decision Q6).
check_apt() { local miss=""; for p in $APT_PACKAGES; do dpkg -s "$p" >/dev/null 2>&1 || miss="$miss $p"; done
  DETAIL="${miss:+missing:$miss}"; DETAIL=${DETAIL:-"installed: $APT_PACKAGES"}; [ -z "$miss" ]; }
apply_apt() { $SUDO env DEBIAN_FRONTEND=noninteractive apt-get update -q && \
              $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -q $APT_PACKAGES; }
step PRQ-02 "system packages" check_apt apply_apt

# PRQ-03 — git version used by the harness (worktrees, push --atomic, commit --trailer need >= 2.32).
check_git() { local v; v=$(git --version 2>/dev/null | awk '{print $3}'); DETAIL="git ${v:-none} (need >= $GIT_MIN)"; [ -n "$v" ] && ver_ge "$v" "$GIT_MIN"; }
step PRQ-03 "git version" check_git ""

# PRQ-04 — bubblewrap can create an unprivileged sandbox as the runner user (user namespaces allowed).
check_bwrap() { local out; out=$(as_runner 'bwrap --ro-bind / / --dev /dev --proc /proc --unshare-all --die-with-parent true && echo BWRAP_OK' 2>&1 </dev/null)
  DETAIL="bwrap $(bwrap --version 2>/dev/null | awk '{print $2}') as $RUNNER_USER: $(echo "$out" | tail -1)"; echo "$out" | grep -q BWRAP_OK; }
step PRQ-04 "bubblewrap sandbox works for the runner user" check_bwrap ""

# PRQ-05 — uv (pinned) in the runner user's ~/.local/bin; Ubuntu's ~/.profile puts it on PATH for login shells.
check_uv() { local v; v=$(as_runner 'uv --version' 2>/dev/null </dev/null | awk '{print $2}'); DETAIL="uv ${v:-missing} (pinned $UV_VERSION)"; [ "$v" = "$UV_VERSION" ]; }
apply_uv() { as_runner "curl -LsSf https://astral.sh/uv/$UV_VERSION/install.sh | env UV_NO_MODIFY_PATH=1 sh" </dev/null; }
step PRQ-05 "uv $UV_VERSION for $RUNNER_USER" check_uv apply_uv

# PRQ-06 — A uv-managed CPython for the harness (Ubuntu 22.04 ships 3.10; the harness needs >= 3.11).
check_py() { local v; v=$(as_runner "uv python find $PYTHON_VERSION 2>/dev/null" </dev/null); DETAIL="python $PYTHON_VERSION: ${v:-not installed}"; [ -n "$v" ]; }
apply_py() { as_runner "uv python install $PYTHON_VERSION" </dev/null; }
step PRQ-06 "Python $PYTHON_VERSION (uv-managed)" check_py apply_py

# PRQ-07 — Node >= NODE_MIN for OpenSpec and the npm-distributed CLIs; a pinned user-local tarball only if needed.
check_node() { local v; v=$(as_runner 'node --version' 2>/dev/null </dev/null | tr -d v); DETAIL="node ${v:-missing} (need >= $NODE_MIN)"; [ -n "$v" ] && ver_ge "$v" "$NODE_MIN"; }
apply_node() { as_runner "set -e; mkdir -p ~/.local/share/l4 ~/.local/bin; cd ~/.local/share/l4;
  curl -fsSLO https://nodejs.org/dist/v$NODE_VERSION/node-v$NODE_VERSION-linux-x64.tar.xz;
  tar -xJf node-v$NODE_VERSION-linux-x64.tar.xz; rm -f node; ln -s node-v$NODE_VERSION-linux-x64 node;
  for b in node npm npx; do ln -sf ~/.local/share/l4/node/bin/\$b ~/.local/bin/\$b; done" </dev/null; }
step PRQ-07 "Node.js >= $NODE_MIN" check_node apply_node

# PRQ-08 — OpenSpec (pinned) in the harness-owned npm prefix. Never `npx` inside a target repo (planted-package risk).
check_openspec() { local v; v=$(as_runner "$L4_HOME/npm/node_modules/.bin/openspec --version" 2>/dev/null </dev/null); DETAIL="openspec ${v:-missing} at $L4_HOME/npm (pinned $OPENSPEC_VERSION)"; [ "$v" = "$OPENSPEC_VERSION" ]; }
apply_openspec() { as_runner "mkdir -p $L4_HOME/npm && npm install --prefix $L4_HOME/npm --no-fund --no-audit --save-exact @fission-ai/openspec@$OPENSPEC_VERSION" </dev/null; }
step PRQ-08 "OpenSpec $OPENSPEC_VERSION (harness prefix)" check_openspec apply_openspec

# PRQ-09 — Claude Code (pinned) via the official native installer into ~/.local/bin.
check_claude() { local v; v=$(as_runner 'claude --version' 2>/dev/null </dev/null | awk '{print $1}'); DETAIL="claude ${v:-missing} (pinned $CLAUDE_VERSION)"; [ "$v" = "$CLAUDE_VERSION" ]; }
apply_claude() { as_runner "curl -fsSL https://claude.ai/install.sh | bash -s $CLAUDE_VERSION" </dev/null; }
step PRQ-09 "Claude Code $CLAUDE_VERSION" check_claude apply_claude

# PRQ-10 — Codex CLI (pinned) into the harness npm prefix, linked into ~/.local/bin for the human device login.
check_codex() { local v; v=$(as_runner 'codex --version' 2>/dev/null </dev/null | awk '{print $NF}'); DETAIL="codex ${v:-missing} (pinned $CODEX_VERSION)"; [ "$v" = "$CODEX_VERSION" ]; }
apply_codex() { as_runner "set -e; mkdir -p $L4_HOME/npm ~/.local/bin; npm install --prefix $L4_HOME/npm --no-fund --no-audit --save-exact @openai/codex@$CODEX_VERSION; ln -sf $L4_HOME/npm/node_modules/.bin/codex ~/.local/bin/codex" </dev/null; }
step PRQ-10 "Codex CLI $CODEX_VERSION" check_codex apply_codex

# PRQ-11 — OpenCode v1: keep an existing install if it is major 1 and at least the pinned version, else install the pin
# user-locally. `opencode --version` prints `1.18.34` (v1) or `opencode v2.0.32` (v2); v2 has the same binary name and
# rejects --pure and --dir, and `sort -V` ranks 2.0.32 above 1.18.34, so the major is compared first (L4-OCG-004).
check_opencode() { local v p; v=$(as_runner 'opencode --version' 2>/dev/null </dev/null | tail -1 | sed -E 's/^(opencode )?v?//'); p=$(as_runner 'command -v opencode' 2>/dev/null </dev/null)
  DETAIL="opencode ${v:-missing} at ${p:-none} (need 1.x >= $OPENCODE_VERSION)"; [ -n "$v" ] && [ "${v%%.*}" = 1 ] && ver_ge "$v" "$OPENCODE_VERSION"; }
apply_opencode() { as_runner "set -e; mkdir -p $L4_HOME/npm ~/.local/bin; npm install --prefix $L4_HOME/npm --no-fund --no-audit --save-exact opencode-ai@$OPENCODE_VERSION; ln -sf $L4_HOME/npm/node_modules/.bin/opencode ~/.local/bin/opencode" </dev/null; }
step PRQ-11 "OpenCode >= $OPENCODE_VERSION" check_opencode apply_opencode

# PRQ-12 — Kiro CLI via its official installer. The installer takes no version (it fetches `latest`), so KIRO_VERSION
# (2.28.0, the version on the maintainer's machine; the 2.27.1 that the runner had answered `whoami` the same way) is a
# floor: `--apply` re-runs the installer when the installed version is older, and a newer one passes.
check_kiro() { local v; v=$(as_runner 'kiro-cli --version' 2>/dev/null </dev/null | tail -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
  DETAIL="kiro-cli ${v:-missing} (pinned $KIRO_VERSION)"; [ -n "$v" ] && ver_ge "$v" "$KIRO_VERSION"; }
# An installed kiro-cli updates itself: over an existing binary the installer asks "Do you want to replace it? (y/N)" on
# /dev/tty, which a remote --apply does not have (kiro-e2e H2, 2026-10-08). The installer is only for a missing kiro-cli.
apply_kiro() {
  if as_runner 'command -v kiro-cli' </dev/null >/dev/null 2>&1; then as_runner 'kiro-cli update --non-interactive' </dev/null
  else as_runner 'curl -fsSL https://cli.kiro.dev/install | bash' </dev/null; fi
}
if [ "$WITH_KIRO" = 1 ]; then step PRQ-12 "Kiro CLI" check_kiro apply_kiro; else report PRQ-12 SKIP "Kiro CLI" "--without-kiro"; fi

# PRQ-13 — Optional: Serena MCP server (pinned, MIT line) as a uv tool, warmed so MCP clients do not time out.
# Warm = `serena --version` plus the Pyright environment (warm for the RUNNER USER only: the agent sandbox has its own
# per-unit UV_CACHE_DIR and does not see these caches until Stage C mounts a shared read-only one) that Serena 1.7.0 starts on demand with
# `uvx -p 3.13 --from pyright==<PYRIGHT_VERSION> pyright-langserver` (solidlsp/language_servers/pyright_server.py): its
# uv environment and the npm package that the `pyright` wrapper downloads on its first run live in the runner user's
# caches. The pin is read from the installed Serena, never copied here.
serena_pyright() { as_runner 'sed -n "s/^PYRIGHT_VERSION = \"\(.*\)\"/\1/p" ~/.local/share/uv/tools/serena-agent/lib/python*/site-packages/solidlsp/language_servers/pyright_server.py 2>/dev/null | head -1' </dev/null; }
check_serena() { local v pv; v=$(as_runner 'serena --version' 2>/dev/null </dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
  DETAIL="serena ${v:-missing} (pinned $SERENA_VERSION)"; [ "$v" = "$SERENA_VERSION" ] || return 1
  pv=$(serena_pyright); [ -n "$pv" ] || { DETAIL="$DETAIL; pyright pin not found in the installed serena"; return 1; }
  as_runner "uvx --offline -p 3.13 --from pyright==$pv pyright --version" >/dev/null 2>&1 </dev/null \
    && { DETAIL="$DETAIL, pyright $pv warm"; return 0; }
  DETAIL="$DETAIL, pyright $pv not warm"; return 1; }
apply_serena() { local pv
  as_runner "uv tool install --force -p 3.13 serena-agent==$SERENA_VERSION && serena --version" </dev/null || return 1
  pv=$(serena_pyright); [ -n "$pv" ] && as_runner "uvx -p 3.13 --from pyright==$pv pyright --version" </dev/null; }
if [ "$WITH_SERENA" = 1 ]; then step PRQ-13 "Serena $SERENA_VERSION" check_serena apply_serena; else report PRQ-13 SKIP "Serena" "pass --with-serena to install"; fi

# PRQ-14 — Optional: Playwright Chromium + its system libraries (root) for e2e gates. The browser goes where the gate
# sandbox mounts it ($PW_PATH, read-only), installed by the Python playwright of the same version the projects pin.
# Present = the revision directories that THIS Playwright version wants exist (a browser left by an older version
# would pass a name check and fail at launch). `--offline`: --check changes nothing; the first apply caches the wheel.
pw_dirs() { as_runner "PLAYWRIGHT_BROWSERS_PATH=$PW_PATH uvx --offline --from playwright==$PLAYWRIGHT_VERSION playwright install --dry-run chromium 2>/dev/null | sed -n 's/^ *Install location: *//p' | grep -E '/(chromium|chromium_headless_shell)-[0-9]+\$'" </dev/null; }
check_pw() { local want d missing=""
  want=$(pw_dirs); [ -n "$want" ] || { DETAIL="cannot tell the chromium revision of playwright $PLAYWRIGHT_VERSION (not cached yet?)"; return 1; }
  for d in $want; do as_runner "test -d $d" </dev/null || missing="$missing ${d##*/}"; done
  DETAIL="chromium for playwright $PLAYWRIGHT_VERSION in $PW_PATH: $([ -z "$missing" ] && echo yes || echo "missing$missing")"
  [ -z "$missing" ]; }
apply_pw() { $SUDO env PATH="$PATH" npx -y playwright@$PLAYWRIGHT_VERSION install-deps chromium && \
  as_runner "mkdir -p $PW_PATH && PLAYWRIGHT_BROWSERS_PATH=$PW_PATH uvx --from playwright==$PLAYWRIGHT_VERSION playwright install chromium" </dev/null; }
if [ "$WITH_PLAYWRIGHT" = 1 ]; then step PRQ-14 "Playwright Chromium $PLAYWRIGHT_VERSION" check_pw apply_pw; else report PRQ-14 SKIP "Playwright" "pass --with-playwright to install"; fi

# PRQ-18 — Optional: Laya (System-One judge, M1.5) as a uv tool with its serve extra, CPU torch, plus the
# $LAYA_CHECKPOINT checkpoint in the runner user's Hugging Face cache so that `laya-serve` never downloads at verify time.
LAYA_PY='~/.local/share/uv/tools/laya/bin/python'
check_laya() { local v; v=$(as_runner "$LAYA_PY -c 'import importlib.metadata as m; print(m.version(\"laya\"))'" 2>/dev/null </dev/null | tail -1)
  DETAIL="laya ${v:-missing} (pinned $LAYA_VERSION)"; [ "$v" = "$LAYA_VERSION" ] || return 1
  as_runner 'command -v laya-serve' >/dev/null 2>&1 </dev/null || { DETAIL="$DETAIL, laya-serve not on PATH"; return 1; }
  as_runner "$LAYA_PY -c 'from huggingface_hub import snapshot_download as s; s(\"convaiinnovations/laya\", allow_patterns=[\"$LAYA_CHECKPOINT/*\"], local_files_only=True)'" \
    >/dev/null 2>&1 </dev/null && { DETAIL="$DETAIL, $LAYA_CHECKPOINT checkpoint cached"; return 0; }
  DETAIL="$DETAIL, $LAYA_CHECKPOINT checkpoint not cached"; return 1; }
apply_laya() {
  as_runner "uv tool install --force --torch-backend cpu 'laya[serve]==$LAYA_VERSION'" </dev/null || return 1
  as_runner "$LAYA_PY -c 'from huggingface_hub import snapshot_download as s; s(\"convaiinnovations/laya\", revision=\"$LAYA_REVISION\", allow_patterns=[\"$LAYA_CHECKPOINT/*\"])'" </dev/null; }
if [ "$WITH_LAYA" = 1 ]; then step PRQ-18 "Laya $LAYA_VERSION + $LAYA_CHECKPOINT" check_laya apply_laya; else report PRQ-18 SKIP "Laya" "pass --with-laya to install"; fi

# PRQ-17 — Optional: adopt subscription logins that a human made as another user (e.g. the SSH admin) by MOVING the
# credential files to the runner user. Moving, not copying: two copies of one OAuth refresh token race on refresh
# and one of them stops working (SPEC L4-FAC-008). Never overwrites a login the runner user already has.
adopt_one() {  # adopt_one <label> <relative path>
  local label=$1 rel=$2 src dst
  src="$(getent passwd "$ADOPT_FROM" | cut -d: -f6)/$rel"; dst="$RHOME/$rel"
  if ! $SUDO test -e "$src"; then report PRQ-17 SKIP "adopt $label login" "no $src"; return; fi
  if $SUDO test -e "$dst"; then report PRQ-17 WARN "adopt $label login" "$dst already exists — left both untouched"; return; fi
  if [ "$MODE" = check ]; then report PRQ-17 MISSING "adopt $label login" "$src would be moved to $dst"; return; fi
  $SUDO install -d -o "$RUNNER_USER" -g "$(id -gn "$RUNNER_USER")" -m 700 "$(dirname "$dst")" && \
  $SUDO mv "$src" "$dst" && $SUDO chown "$RUNNER_USER:$(id -gn "$RUNNER_USER")" "$dst" && $SUDO chmod 600 "$dst" \
    && report PRQ-17 FIXED "adopt $label login" "moved $src → $dst (owner $RUNNER_USER, mode 600)" \
    || report PRQ-17 FAILED "adopt $label login" "could not move $src"
}
if [ -n "$ADOPT_FROM" ]; then
  adopt_one claude .claude/.credentials.json
  adopt_one codex .codex/auth.json
fi

# PRQ-15 — Agent authentication: presence only, never contents. Logins are human steps (see docs/runner/README.md).
auth_line() { as_runner "$1 >/dev/null 2>&1 && echo AUTH_OK" </dev/null 2>/dev/null | grep -q AUTH_OK && echo "$2" || echo "$3"; }
report PRQ-15 INFO "auth: claude" "$(auth_line "claude auth status | python3 -c 'import sys,json; sys.exit(0 if json.load(sys.stdin).get(\"loggedIn\") else 1)'" 'logged in (claude auth status)' 'not logged in — run as the runner user: claude, then /login; or provide CLAUDE_CODE_OAUTH_TOKEN as a masked CI variable (claude setup-token)')"
report PRQ-15 INFO "auth: codex" "$(auth_line 'codex login status' 'logged in' "not logged in — run as $RUNNER_USER: codex login --device-auth")"
# v2's `models` starts a shared per-user daemon that outlives the call, so it runs only for an OpenCode v1 (PRQ-11)
if check_opencode; then oc_free="free models (no login): $(as_runner 'opencode models 2>/dev/null | grep -c -- "-free\$\|^opencode/big-pickle\$"' 2>/dev/null </dev/null)"
else oc_free="free models: skipped (opencode at $(as_runner 'command -v opencode' 2>/dev/null </dev/null) is not OpenCode v1)"; fi
report PRQ-15 INFO "auth: opencode" "providers: $(as_runner 'python3 -c "import json,os;print(\",\".join(sorted(json.load(open(os.path.expanduser(\"~/.local/share/opencode/auth.json\"))))))"' 2>/dev/null </dev/null || echo none); $oc_free (API keys may also come from CI variables, e.g. OPENROUTER_API_KEY)"
# kiro-cli answers `whoami --format json` with a flat {"accountType", "email"} (2.27.1, 2.28.0); logged out is exit 1.
# The login is a human step and is never copied or moved: a second copy of a refresh token kills the first (L4-FAC-008).
if as_runner "kiro-cli whoami --format json | python3 -c 'import sys,json; sys.exit(0 if json.load(sys.stdin).get(\"accountType\") else 1)'" </dev/null >/dev/null 2>&1; then
  report PRQ-15 INFO "auth: kiro-cli" "logged in"
else
  report PRQ-15 WARN "auth: kiro-cli" "not logged in — a human runs: sudo -iu $RUNNER_USER, then kiro-cli login --license free --use-device-flow (never copy another user's Kiro login; or set KIRO_API_KEY, Pro tier and above)"
fi

# PRQ-16 — Capacity warnings (never changed automatically).
mem_avail=$(free -m | awk '/^Mem:/{print $7}'); mem_total=$(free -m | awk '/^Mem:/{print $2}')
MEM_CEILING_MB=${MEM_CEILING_MB:-0}   # set when the VM uses memory ballooning (e.g. 10240 on l4-runner)
if [ "$mem_total" -lt 7500 ] && [ "$MEM_CEILING_MB" -lt 7500 ]; then report PRQ-16 WARN "memory" "${mem_total} MB total, ${mem_avail} MB available — agent CLIs + test suites + browsers want >= 8 GB; keep runner concurrent=1 (set MEM_CEILING_MB if the VM balloons)"
elif [ "$mem_total" -lt 7500 ]; then report PRQ-16 OK "memory" "${mem_total} MB now, ballooning up to ${MEM_CEILING_MB} MB (MEM_CEILING_MB); keep runner concurrent=1"
else report PRQ-16 OK "memory" "${mem_total} MB total, ${mem_avail} MB available"; fi
# PRQ-19 — Container-daemon group (warn only, never changed automatically: removing the membership is the maintainer's
# decision, other jobs on this runner may use docker). The L4 sandboxes (bwrap) cover /run with a tmpfs, so the docker
# socket is not reachable from agents and gates (HB-1); jobs outside L4 and the harness process itself still reach it.
if id -nG "$RUNNER_USER" | tr ' ' '\n' | grep -qx docker; then
  report PRQ-19 WARN "docker group" "$RUNNER_USER is in the docker group: root-equivalent for any job code outside the L4 sandbox (the sandbox masks /run, so the docker socket is not reachable from agents and gates). If no job needs docker: sudo gpasswd -d $RUNNER_USER docker, then restart the gitlab-runner service (a running service keeps its groups until restarted)"
else report PRQ-19 OK "docker group" "$RUNNER_USER is not in the docker group"; fi

echo "summary: mode=$MODE missing=$MISSING failed=$FAILS warnings=$WARNS"
if [ "$FAILS" -gt 0 ]; then exit 2; fi
if [ "$MISSING" -gt 0 ]; then exit 1; fi
exit 0
