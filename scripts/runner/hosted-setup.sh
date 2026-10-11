#!/usr/bin/env bash
# hosted-setup.sh — SPIKE (branch spike/hosted-agent-setup): the "auto setup step" a CI job runs BEFORE `.l4/bin/l4`,
# because the shim cannot start without uv. Enabled by L4_SELF_PROVISION=true (or 1); anything else is a no-op.
# Output: one line per step "[HSU-nn] STATUS title — detail". It never logs in anywhere and never reads or prints
# credential values. bubblewrap: user-space copy first (apt-get download + dpkg -x), then the preinstalled one; sudo steps
# run only as a "root fallback" on a disposable runner with passwordless sudo.
#   L4_PROVISION_ROOT=0   skip the root steps even when they are possible
# Exit: 0, or 2 when uv could not be installed.
set -uo pipefail

UV_VERSION=${UV_VERSION:-0.12.22}   # same pin as prereqs.sh and src/l4/provision/catalog.py

line() { printf '[%s] %s %s — %s\n' "$1" "$2" "$3" "$4"; }
now() { date +%s; }

case "$(printf '%s' "${L4_SELF_PROVISION:-}" | tr '[:upper:]' '[:lower:]')" in
  true|1) ;;
  *) line HSU-00 SKIP "hosted setup" "L4_SELF_PROVISION is not true"; exit 0;;
esac
T0=$(now)
export PATH="$HOME/.local/bin:$PATH"

SUDO_OK=no; sudo -n true >/dev/null 2>&1 && SUDO_OK=yes
if [ "$(id -u)" -eq 0 ]; then SUDO_OK=root; fi
sysctl_val() { sysctl -n "$1" 2>/dev/null || echo "n/a"; }
ver() { "$@" 2>&1 | head -1 | tr -d '\r' || true; }
have() { command -v "$1" >/dev/null 2>&1; }
vof() { if have "$1"; then ver "$@" --version; else echo "absent"; fi; }

# HSU-01 facts
line HSU-01 INFO "runner facts" "RUNNER_ENVIRONMENT=${RUNNER_ENVIRONMENT:-unset} CI_DISPOSABLE_ENVIRONMENT=${CI_DISPOSABLE_ENVIRONMENT:-unset} ImageOS=${ImageOS:-unset} ImageVersion=${ImageVersion:-unset} kernel=$(uname -r) user=$(id -un) sudo_n=$SUDO_OK git=\"$(vof git)\" python3=\"$(vof python3)\" node=\"$(vof node)\" uv_on_path=$(have uv && echo yes || echo no) unzip_on_path=$(have unzip && echo yes || echo no) bwrap_on_path=$(have bwrap && echo yes || echo no) apparmor_restrict_unprivileged_userns=$(sysctl_val kernel.apparmor_restrict_unprivileged_userns) unprivileged_userns_clone=$(sysctl_val kernel.unprivileged_userns_clone)"

# HSU-02 uv
if have uv; then
  line HSU-02 OK "uv" "already present: $(uv --version 2>&1 | head -1) at $(command -v uv)"
else
  t=$(now)
  if curl -fsSL "https://astral.sh/uv/$UV_VERSION/install.sh" | UV_NO_MODIFY_PATH=1 sh >/tmp/hsu-uv-install.log 2>&1 && have uv; then
    line HSU-02 FIXED "uv" "installed $(uv --version 2>&1 | head -1) into ~/.local/bin in $(( $(now) - t )) s"
  else
    line HSU-02 FAILED "uv" "installer failed: $(tail -2 /tmp/hsu-uv-install.log | tr '\n' ' ')"
    line HSU-99 FAILED "summary" "uv missing, the .l4/bin/l4 shim cannot start; total $(( $(now) - T0 )) s"
    exit 2
  fi
fi
if [ -n "${GITHUB_PATH:-}" ]; then echo "$HOME/.local/bin" >> "$GITHUB_PATH"; fi

# ---- sandbox (bubblewrap): user-space first, preinstalled second, sudo only as a measured last resort ----
L4H=${L4_HOME:-$HOME/.local/share/l4}
bwrap_test() {   # $1 binary  $2 label  -> prints one result line, returns 0 on pass
  local out rc
  out=$("$1" --ro-bind / / --dev /dev --proc /proc --unshare-user --unshare-pid --die-with-parent true 2>&1); rc=$?
  if [ $rc -eq 0 ]; then line HSU-04 INFO "$2" "PASS ($1: $("$1" --version 2>&1 | head -1))"; return 0; fi
  line HSU-04 INFO "$2" "FAIL rc=$rc ($1): $(printf '%s' "$out" | head -1)"; return 1
}
SANDBOX_VIA=none

# (d) context: is there an AppArmor profile that names bwrap?
AAP=$(ls /etc/apparmor.d 2>/dev/null | grep -i bwrap | tr '\n' ' ')
line HSU-03 INFO "apparmor bwrap profile" "files in /etc/apparmor.d matching bwrap: ${AAP:-none}; $(grep -rl 'bwrap' /etc/apparmor.d 2>/dev/null | head -3 | tr '\n' ' ')"

# (b) preinstalled /usr/bin/bwrap
PRE=fail
if [ -x /usr/bin/bwrap ]; then bwrap_test /usr/bin/bwrap "preinstalled bwrap (/usr/bin/bwrap)" && PRE=pass
else line HSU-04 INFO "preinstalled bwrap (/usr/bin/bwrap)" "ABSENT"; PRE=absent; fi

# (a) user-space bwrap: apt-get download (no root) + dpkg -x into $L4_HOME/bwrap, linked from ~/.local/bin
US=fail
if have apt-get && have dpkg; then
  t=$(now); W=$(mktemp -d); BDIR="$L4H/bwrap"
  if ( cd "$W" && apt-get download bubblewrap >"$W/dl.log" 2>&1 ) && DEB=$(ls "$W"/bubblewrap_*.deb 2>/dev/null | head -1) && [ -n "$DEB" ] \
     && rm -rf "$BDIR" && mkdir -p "$BDIR" "$HOME/.local/bin" && dpkg -x "$DEB" "$BDIR" 2>"$W/x.log" && [ -x "$BDIR/usr/bin/bwrap" ]; then
    ln -sf "$BDIR/usr/bin/bwrap" "$HOME/.local/bin/bwrap"; hash -r
    line HSU-05 FIXED "user-space bwrap install" "$(basename "$DEB") extracted to $BDIR in $(( $(now) - t )) s, linked from ~/.local/bin/bwrap"
    if bwrap_test "$BDIR/usr/bin/bwrap" "user-space bwrap"; then US=pass; else rm -f "$HOME/.local/bin/bwrap"; fi
  else
    line HSU-05 FAILED "user-space bwrap install" "apt-get download/dpkg -x failed: $(tail -1 "$W/dl.log" 2>/dev/null) $(tail -1 "$W/x.log" 2>/dev/null)"
  fi
else
  line HSU-05 SKIP "user-space bwrap install" "apt-get or dpkg not available"
fi
line HSU-06 INFO "bwrap summary before any root step" "user-space bwrap: $US; preinstalled /usr/bin/bwrap: $PRE"
[ "$US" = pass ] && SANDBOX_VIA=user-space
[ "$SANDBOX_VIA" = none ] && [ "$PRE" = pass ] && SANDBOX_VIA=preinstalled

# (c) root fallback: disposable runner + passwordless sudo + not opted out, only when neither worked
if [ "$SANDBOX_VIA" != none ]; then
  line HSU-07 SKIP "root fallback" "not needed, sandbox works via $SANDBOX_VIA bwrap"
elif [ "${RUNNER_ENVIRONMENT:-}" != github-hosted ] && [ "${CI_DISPOSABLE_ENVIRONMENT:-}" != true ]; then
  line HSU-07 SKIP "root fallback" "runner is not disposable (RUNNER_ENVIRONMENT/CI_DISPOSABLE_ENVIRONMENT)"
elif [ "$SUDO_OK" = no ]; then
  line HSU-07 SKIP "root fallback" "sudo -n true does not work"
elif [ "${L4_PROVISION_ROOT:-}" = 0 ]; then
  line HSU-07 SKIP "root fallback" "L4_PROVISION_ROOT=0"
else
  SUDO="sudo -n"; [ "$SUDO_OK" = root ] && SUDO=""
  if [ ! -x /usr/bin/bwrap ]; then
    t=$(now)
    if $SUDO apt-get install -y bubblewrap >/tmp/hsu-apt.log 2>&1; then
      line HSU-07 FIXED "root fallback: apt-get install bubblewrap" "installed in $(( $(now) - t )) s (no apt-get update needed)"
    else
      line HSU-07 INFO "root fallback: apt-get install bubblewrap" "first attempt failed: $(tail -1 /tmp/hsu-apt.log); running apt-get update"
      $SUDO apt-get update >>/tmp/hsu-apt.log 2>&1
      if $SUDO apt-get install -y bubblewrap >>/tmp/hsu-apt.log 2>&1; then
        line HSU-07 FIXED "root fallback: apt-get install bubblewrap" "installed after apt-get update in $(( $(now) - t )) s"
      else
        line HSU-07 FAILED "root fallback: apt-get install bubblewrap" "$(tail -2 /tmp/hsu-apt.log | tr '\n' ' ')"
      fi
    fi
    hash -r
  fi
  [ -x /usr/bin/bwrap ] && bwrap_test /usr/bin/bwrap "root fallback: bwrap after apt install" && SANDBOX_VIA=root-apt
  AA=$(sysctl_val kernel.apparmor_restrict_unprivileged_userns)
  if [ "$SANDBOX_VIA" = none ] && [ "$AA" = 1 ]; then
    if $SUDO sysctl -w kernel.apparmor_restrict_unprivileged_userns=0 >/tmp/hsu-sysctl.log 2>&1; then
      line HSU-08 FIXED "root fallback: apparmor userns sysctl" "set kernel.apparmor_restrict_unprivileged_userns=0 (was 1; now $(sysctl_val kernel.apparmor_restrict_unprivileged_userns))"
    else
      line HSU-08 FAILED "root fallback: apparmor userns sysctl" "$(tail -1 /tmp/hsu-sysctl.log)"
    fi
    # the user-space binary first (its ~/.local/bin link was removed when it failed): does the sysctl alone suffice?
    if [ -x "$L4H/bwrap/usr/bin/bwrap" ] && bwrap_test "$L4H/bwrap/usr/bin/bwrap" "root fallback: user-space bwrap after sysctl"; then
      ln -sf "$L4H/bwrap/usr/bin/bwrap" "$HOME/.local/bin/bwrap"; hash -r; SANDBOX_VIA=user-space-after-sysctl
    elif [ -x /usr/bin/bwrap ] && bwrap_test /usr/bin/bwrap "root fallback: /usr/bin/bwrap after sysctl"; then
      SANDBOX_VIA=root-sysctl
    fi
  elif [ "$SANDBOX_VIA" = none ]; then
    line HSU-08 SKIP "root fallback: apparmor userns sysctl" "sysctl value is $AA, not 1"
  fi
fi
line HSU-09 INFO "bwrap final" "sandbox usable by $(id -un): $([ "$SANDBOX_VIA" = none ] && echo NO || echo "yes, via $SANDBOX_VIA")"

line HSU-99 OK "summary" "uv=$(uv --version 2>&1 | head -1) bwrap=$(have bwrap && echo present || echo absent) total $(( $(now) - T0 )) s"
exit 0
