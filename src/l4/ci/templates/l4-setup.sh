#!/usr/bin/env bash
# .l4/bin/l4-setup: the setup step a CI job runs BEFORE `.l4/bin/l4`, because the shim cannot start without uv
# (L4-PRV-020..022). Written by `l4 init` and `l4 upgrade`; the pinned uv version is filled in from the harness catalog.
# Switch: L4_SELF_PROVISION=true, or auto on a runner that is not disposable (the shell cannot read ci.self_provision
# from the config, so false, unset and any other value change nothing). Output: one line per step,
# "[HSU-nn] STATUS title — detail". It never logs in anywhere and never reads or prints a credential value.
#   L4_PROVISION_ROOT=0   never run the one root command, even on a disposable runner
# The only root command is `sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`, only on a disposable runner
# (RUNNER_ENVIRONMENT=github-hosted or CI_DISPOSABLE_ENVIRONMENT=true) and only when the user-space bwrap fails its self-test.
# Exit: 0, or 2 when uv could not be installed.
# shellcheck disable=SC2088  # a "~" inside a message is meant literally
set -uo pipefail

UV_VERSION=@@UV_VERSION@@
SYSCTL_KEY=kernel.apparmor_restrict_unprivileged_userns

line() { printf '[%s] %s %s — %s\n' "$1" "$2" "$3" "$4"; }
now() { date +%s; }
have() { command -v "$1" >/dev/null 2>&1; }

# ---- HSU-00 the switch ----
raw=${L4_SELF_PROVISION:-}
flag=$(printf '%s' "$raw" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')
disposable=no
if [ "${RUNNER_ENVIRONMENT:-}" = github-hosted ] || [ "${CI_DISPOSABLE_ENVIRONMENT:-}" = true ]; then disposable=yes; fi
note="the shell cannot read ci.self_provision from the config, so only true or auto act"
case "$flag" in
  true) ;;
  auto)
    if [ "$disposable" = yes ]; then
      line HSU-00 SKIP "hosted setup" "L4_SELF_PROVISION=auto on a disposable runner means off; set it to true to run"
      exit 0
    fi
    ;;
  false) line HSU-00 SKIP "hosted setup" "L4_SELF_PROVISION=false; $note"; exit 0 ;;
  "") line HSU-00 SKIP "hosted setup" "L4_SELF_PROVISION is not set; $note"; exit 0 ;;
  *)
    shown=$(printf '%s' "$raw" | tr -cd '[:print:]' | cut -c1-40)
    line HSU-00 SKIP "hosted setup" "L4_SELF_PROVISION=$shown is not true, false or auto; $note"
    exit 0
    ;;
esac

T0=$(now)
LOG=$(mktemp -d)
trap 'rm -rf "$LOG"' EXIT
export PATH="$HOME/.local/bin:$PATH"
L4H=${L4_HOME:-$HOME/.local/share/l4}
US="$L4H/bwrap/usr/bin/bwrap"
LINK="$HOME/.local/bin/bwrap"

sysctl_val() {
  local v
  v=$(sysctl -n "$SYSCTL_KEY" 2>/dev/null) || v=$(cat "/proc/sys/${SYSCTL_KEY//.//}" 2>/dev/null) || v=n/a
  printf '%s' "$v"
}

# ---- HSU-01 facts (no root command, not even `sudo -n true`) ----
line HSU-01 INFO "runner facts" "RUNNER_ENVIRONMENT=${RUNNER_ENVIRONMENT:-unset} CI_DISPOSABLE_ENVIRONMENT=${CI_DISPOSABLE_ENVIRONMENT:-unset} ImageOS=${ImageOS:-unset} kernel=$(uname -r) user=$(id -un) uv_on_path=$(have uv && echo yes || echo no) bwrap_on_path=$(have bwrap && echo yes || echo no) $SYSCTL_KEY=$(sysctl_val)"

# ---- HSU-02 uv ----
if have uv; then
  line HSU-02 OK "uv" "already present: $(uv --version 2>&1 | head -1) at $(command -v uv)"
else
  t=$(now)
  if curl -fsSL "https://astral.sh/uv/$UV_VERSION/install.sh" | UV_NO_MODIFY_PATH=1 sh >"$LOG/uv.log" 2>&1 && have uv; then
    line HSU-02 FIXED "uv" "installed $(uv --version 2>&1 | head -1) (pin $UV_VERSION) into ~/.local/bin in $(($(now) - t)) s"
  else
    line HSU-02 FAILED "uv" "installer failed: $(tail -2 "$LOG/uv.log" | tr '\n' ' ')"
    line HSU-99 FAILED "summary" "uv missing, the .l4/bin/l4 shim cannot start; total $(($(now) - T0)) s"
    exit 2
  fi
fi

# ---- HSU-03 later steps of the job find ~/.local/bin ----
if [ -n "${GITHUB_PATH:-}" ]; then
  if grep -qxF "$HOME/.local/bin" "$GITHUB_PATH" 2>/dev/null; then
    line HSU-03 OK "GITHUB_PATH" "~/.local/bin already listed"
  else
    echo "$HOME/.local/bin" >>"$GITHUB_PATH"
    line HSU-03 FIXED "GITHUB_PATH" "appended ~/.local/bin"
  fi
fi

# ---- HSU-04 bwrap in user space ----
SELFTEST_MSG=""
selftest() {   # $1 binary; the L4-PRV-021 self-test, run as the job user
  SELFTEST_MSG=$("$1" --ro-bind / / --dev /dev --proc /proc --unshare-user --unshare-pid --die-with-parent true 2>&1)
}
link_us() { mkdir -p "$HOME/.local/bin" && ln -sf "$US" "$LINK" && hash -r; }

# a link to a binary that fails would shadow a working system bwrap
if { [ -e "$LINK" ] || [ -L "$LINK" ]; } && ! selftest "$LINK"; then
  rm -f "$LINK"
  hash -r
  line HSU-04 INFO "bwrap link" "removed ~/.local/bin/bwrap, it failed the self-test: $(printf '%s' "$SELFTEST_MSG" | head -1)"
fi

VIA=none
if [ -x "$US" ]; then
  if selftest "$US"; then
    link_us
    VIA=user-space
    line HSU-04 OK "bwrap" "already present: $US"
  else
    line HSU-04 INFO "bwrap" "cached $US fails the self-test, not downloading again: $(printf '%s' "$SELFTEST_MSG" | head -1)"
  fi
else
  other=$(command -v bwrap || true)
  if [ -n "$other" ] && selftest "$other"; then
    VIA=path
    line HSU-04 OK "bwrap" "$other passes the self-test, nothing installed"
  elif have apt-get && have dpkg; then
    t=$(now)
    W=$(mktemp -d "$LOG/deb.XXXXXX")
    if (cd "$W" && apt-get download bubblewrap >"$W/dl.log" 2>&1) && DEB=$(find "$W" -name 'bubblewrap_*.deb' | head -1) && [ -n "$DEB" ] \
      && mkdir -p "$L4H/bwrap" && dpkg -x "$DEB" "$L4H/bwrap" 2>"$W/x.log" && [ -x "$US" ]; then
      if selftest "$US"; then
        link_us
        VIA=user-space
        line HSU-04 FIXED "bwrap" "$(basename "$DEB") extracted to $L4H/bwrap in $(($(now) - t)) s, linked from ~/.local/bin/bwrap"
      else
        line HSU-04 FIXED "bwrap" "$(basename "$DEB") extracted to $L4H/bwrap but fails the self-test: $(printf '%s' "$SELFTEST_MSG" | head -1)"
      fi
    else
      line HSU-04 FAILED "bwrap" "apt-get download or dpkg -x failed: $(tail -1 "$W/dl.log" 2>/dev/null) $(tail -1 "$W/x.log" 2>/dev/null)"
    fi
  else
    line HSU-04 MANUAL "bwrap" "apt-get or dpkg is not available; install bubblewrap with your package manager"
  fi
fi

# ---- HSU-05 the one root step ----
CMD="sudo -n sysctl -w $SYSCTL_KEY=0"
skip_root() { line HSU-05 SKIP "root step" "would run: $CMD; not run: $1"; }
SETTING=$(sysctl_val)
SUDO=""
if [ "$VIA" != none ]; then
  skip_root "not needed, bwrap already works"
elif [ "$disposable" != yes ]; then
  skip_root "the runner is not disposable (neither RUNNER_ENVIRONMENT=github-hosted nor CI_DISPOSABLE_ENVIRONMENT=true)"
elif [ "${L4_PROVISION_ROOT:-}" = 0 ]; then
  skip_root "L4_PROVISION_ROOT=0"
elif [ "$SETTING" != 1 ]; then
  skip_root "$SYSCTL_KEY is $SETTING, not 1"
elif [ "$(id -u)" -ne 0 ] && ! sudo -n true >/dev/null 2>&1; then
  skip_root "no passwordless sudo and not root"
else
  if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo -n"; fi
  if $SUDO sysctl -w "$SYSCTL_KEY=0" >"$LOG/sysctl.log" 2>&1; then
    line HSU-05 FIXED "root step" "$SYSCTL_KEY set to 0 (was $SETTING; now $(sysctl_val))"
  else
    line HSU-05 FAILED "root step" "$CMD failed: $(tail -1 "$LOG/sysctl.log")"
  fi
  if [ -x "$US" ] && selftest "$US"; then
    link_us
    VIA=user-space
  else
    other=$(command -v bwrap || true)
    if [ -n "$other" ] && selftest "$other"; then VIA=path; fi
  fi
  line HSU-06 INFO "bwrap after the sysctl" "self-test $([ "$VIA" = none ] && echo "still fails: $(printf '%s' "$SELFTEST_MSG" | head -1)" || echo "passes via $VIA")"
fi

line HSU-09 INFO "bwrap final" "sandbox usable by $(id -un): $([ "$VIA" = none ] && echo NO || echo "yes, via $VIA")"
line HSU-99 OK "summary" "uv=$(uv --version 2>&1 | head -1) bwrap=$VIA total $(($(now) - T0)) s"
exit 0
