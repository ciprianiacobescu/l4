#!/usr/bin/env bash
# hosted-setup.sh — SPIKE (branch spike/hosted-agent-setup): the "auto setup step" a CI job runs BEFORE `.l4/bin/l4`,
# because the shim cannot start without uv. Enabled by L4_SELF_PROVISION=true (or 1); anything else is a no-op.
# Output: one line per step "[HSU-nn] STATUS title — detail". It never logs in anywhere and never reads or prints
# credential values. Root steps (bubblewrap) run only on a disposable runner with passwordless sudo.
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

# bwrap test exactly as the harness's sandbox needs it
bwrap_test() {   # $1 label
  local out rc
  if ! have bwrap; then line HSU-03 INFO "bwrap test ($1)" "FAIL bwrap not on PATH"; return 1; fi
  out=$(bwrap --ro-bind / / --dev /dev --proc /proc --unshare-user --unshare-pid --die-with-parent true 2>&1); rc=$?
  if [ $rc -eq 0 ]; then line HSU-03 INFO "bwrap test ($1)" "PASS ($(bwrap --version 2>&1 | head -1))"; return 0; fi
  line HSU-03 INFO "bwrap test ($1)" "FAIL rc=$rc: $(printf '%s' "$out" | head -1)"; return 1
}

# root steps: disposable runner + passwordless sudo + not opted out
DISPOSABLE=no
{ [ "${RUNNER_ENVIRONMENT:-}" = github-hosted ] || [ "${CI_DISPOSABLE_ENVIRONMENT:-}" = true ]; } && DISPOSABLE=yes
if [ "$DISPOSABLE" != yes ]; then
  line HSU-04 SKIP "root steps" "runner is not disposable (RUNNER_ENVIRONMENT and CI_DISPOSABLE_ENVIRONMENT say so)"
  bwrap_test "no root steps"
elif [ "$SUDO_OK" = no ]; then
  line HSU-04 SKIP "root steps" "sudo -n true does not work"
  bwrap_test "no root steps"
elif [ "${L4_PROVISION_ROOT:-}" = 0 ]; then
  line HSU-04 SKIP "root steps" "L4_PROVISION_ROOT=0"
  bwrap_test "no root steps"
else
  SUDO="sudo -n"; [ "$SUDO_OK" = root ] && SUDO=""
  bwrap_test "before" && OK=1 || OK=0
  if [ $OK -eq 0 ] && ! have bwrap; then
    t=$(now)
    if $SUDO apt-get install -y bubblewrap >/tmp/hsu-apt.log 2>&1; then
      line HSU-05 FIXED "apt-get install bubblewrap" "installed in $(( $(now) - t )) s (no apt-get update needed)"
    else
      line HSU-05 INFO "apt-get install bubblewrap" "first attempt failed: $(tail -1 /tmp/hsu-apt.log); running apt-get update"
      $SUDO apt-get update >>/tmp/hsu-apt.log 2>&1
      if $SUDO apt-get install -y bubblewrap >>/tmp/hsu-apt.log 2>&1; then
        line HSU-05 FIXED "apt-get install bubblewrap" "installed after apt-get update in $(( $(now) - t )) s"
      else
        line HSU-05 FAILED "apt-get install bubblewrap" "$(tail -2 /tmp/hsu-apt.log | tr '\n' ' ')"
      fi
    fi
    hash -r
  fi
  bwrap_test "after install step" && OK=1 || OK=0
  AA=$(sysctl_val kernel.apparmor_restrict_unprivileged_userns)
  if [ $OK -eq 0 ] && [ "$AA" = 1 ]; then
    if $SUDO sysctl -w kernel.apparmor_restrict_unprivileged_userns=0 >/tmp/hsu-sysctl.log 2>&1; then
      line HSU-06 FIXED "apparmor userns sysctl" "set kernel.apparmor_restrict_unprivileged_userns=0 (was 1; now $(sysctl_val kernel.apparmor_restrict_unprivileged_userns))"
    else
      line HSU-06 FAILED "apparmor userns sysctl" "$(tail -1 /tmp/hsu-sysctl.log)"
    fi
    bwrap_test "after sysctl" && OK=1 || OK=0
  elif [ $OK -eq 0 ]; then
    line HSU-06 SKIP "apparmor userns sysctl" "sysctl value is $AA, not 1"
  fi
  line HSU-07 INFO "bwrap final" "$([ $OK -eq 1 ] && echo works || echo 'does not work') for user $(id -un)"
fi

line HSU-99 OK "summary" "uv=$(uv --version 2>&1 | head -1) bwrap=$(have bwrap && echo present || echo absent) total $(( $(now) - T0 )) s"
exit 0
