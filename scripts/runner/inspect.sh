#!/usr/bin/env bash
# inspect.sh — READ-ONLY inventory of a shell-executor GitLab runner host for the L4 harness.
# Changes nothing. Prints no secret values (only presence of credential files and env var NAMES).
#
# Run on the runner host as a sudo-capable admin user:
#   bash inspect.sh                       # locally on the host
#   scripts/runner/mk-ssh.sh --script scripts/runner/inspect.sh     # from a workstation via the Mintkey bastion
#
# Output: "KEY | value" lines grouped in sections, so two runs can be diffed.
set -u
RUNNER_USER=${RUNNER_USER:-gitlab-runner}
SUDO=""
if sudo -n true 2>/dev/null; then SUDO="sudo -n"; fi
sec() { printf '\n=== %s\n' "$1"; }
kv() { printf '%-28s | %s\n' "$1" "$2"; }
as_runner() {  # run a command as the runner user with a login-like environment (the shell executor uses `bash --login`)
  if [ -n "$SUDO" ]; then $SUDO -u "$RUNNER_USER" -H bash -lc "$1" 2>&1; else echo "(no passwordless sudo — cannot inspect as $RUNNER_USER)"; fi
}

sec "host"
kv admin_user "$(id -un) ($(id -Gn | tr ' ' ','))"
kv passwordless_sudo "$([ -n "$SUDO" ] && echo yes || echo no)"
kv hostname "$(hostname)"
kv os "$(. /etc/os-release; echo "$PRETTY_NAME")"
kv kernel "$(uname -r) $(uname -m)"
kv cpus "$(nproc)"
kv mem_mb "$(free -m | awk '/^Mem:/{print $2" total, "$7" available"}')"
kv disk_root "$(df -h / | awk 'NR==2{print $4" free of "$2}')"
kv userns_clone "$(cat /proc/sys/kernel/unprivileged_userns_clone 2>/dev/null || echo n/a)"
kv max_user_namespaces "$(cat /proc/sys/user/max_user_namespaces 2>/dev/null || echo n/a)"
kv apparmor_restrict_userns "$(sysctl -n kernel.apparmor_restrict_unprivileged_userns 2>/dev/null || echo n/a)"

sec "gitlab-runner service"
kv runner_binary "$(command -v gitlab-runner || echo MISSING)"
kv runner_version "$(gitlab-runner --version 2>/dev/null | awk '/^Version/{print $2}')"
kv runner_service "$(systemctl is-active gitlab-runner 2>/dev/null)"
kv runner_user_exists "$(id "$RUNNER_USER" >/dev/null 2>&1 && echo yes || echo no)"
kv runner_user_home "$(getent passwd "$RUNNER_USER" | cut -d: -f6)"
kv runner_user_shell "$(getent passwd "$RUNNER_USER" | cut -d: -f7)"
kv runner_user_groups "$(id -Gn "$RUNNER_USER" 2>/dev/null | tr ' ' ',')"
if [ -n "$SUDO" ]; then
  CFG=/etc/gitlab-runner/config.toml
  kv config_concurrent "$($SUDO awk -F= '/^concurrent/{gsub(/ /,"",$2);print $2}' $CFG 2>/dev/null)"
  kv config_executors "$($SUDO grep -E '^\s*executor' $CFG 2>/dev/null | awk -F'"' '{print $2}' | sort | uniq -c | tr '\n' ' ')"
  kv config_runner_names "$($SUDO grep -E '^\s*name' $CFG 2>/dev/null | awk -F'"' '{print $2}' | tr '\n' ' ')"
  kv config_builds_dir "$($SUDO grep -E '^\s*builds_dir' $CFG 2>/dev/null | awk -F'"' '{print $2}' | tr '\n' ' ')"
  kv config_shell "$($SUDO grep -E '^\s*shell' $CFG 2>/dev/null | awk -F'"' '{print $2}' | tr '\n' ' ')"
fi

sec "login-shell health (shell executor runs 'bash --login' as $RUNNER_USER)"
H=$(getent passwd "$RUNNER_USER" | cut -d: -f6)
for f in .bash_logout .bash_profile .bashrc .profile; do
  if [ -n "$SUDO" ]; then
    if $SUDO test -e "$H/$f"; then kv "$f" "present; clear_console lines: $($SUDO grep -c clear_console "$H/$f" 2>/dev/null)"; else kv "$f" absent; fi
  fi
done
kv login_shell_exit "$(as_runner 'true' >/dev/null; echo $?)"
kv login_logout_exit "$( [ -n "$SUDO" ] && { $SUDO -u "$RUNNER_USER" -H bash --login -c 'exit 0' </dev/null >/dev/null 2>&1; echo $?; } )"

sec "system packages / tools (PATH of $RUNNER_USER login shell)"
TOOLS="git git-lfs curl wget jq make gcc python3 pip3 uv uvx node npm npx bun bwrap docker podman claude codex opencode kiro-cli gemini playwright chromium google-chrome ollama serena gitleaks rg go cargo"
as_runner "for t in $TOOLS; do p=\$(command -v \$t 2>/dev/null); if [ -n \"\$p\" ]; then v=\$(timeout 20 \$t --version 2>&1 | head -1); printf '%-28s | %s | %s\n' \"tool:\$t\" \"\$p\" \"\$v\"; else printf '%-28s | MISSING\n' \"tool:\$t\"; fi; done"
kv bwrap_dpkg "$(dpkg -s bubblewrap 2>/dev/null | awk '/^Version/{print $2}' || true)"

sec "runner user: PATH and user-local tool dirs"
as_runner 'echo "PATH | $PATH"; for d in ~/.local/bin ~/.npm-global/bin ~/.opencode/bin ~/.bun/bin ~/.cargo/bin ~/.nvm/versions/node ~/.local/share/l4; do [ -e "$d" ] && echo "dir $d | $(ls "$d" 2>/dev/null | tr "\n" " ")"; done'

sec "runner user: credential presence (paths only — no contents)"
as_runner 'for f in ~/.claude/.credentials.json ~/.claude.json ~/.codex/auth.json ~/.codex/config.toml ~/.local/share/opencode/auth.json ~/.config/opencode/opencode.json ~/.config/opencode/opencode.jsonc ~/.local/share/kiro-cli ~/.aws/sso ~/.config/gh/hosts.yml ~/.ssh/id_ed25519 ~/.ssh/id_rsa ~/.gitconfig; do [ -e "$f" ] && echo "cred $f | PRESENT" || echo "cred $f | absent"; done'
as_runner 'timeout 20 codex login status >/dev/null 2>&1; echo "codex_login_status_exit | $?"' 2>/dev/null
as_runner 'command -v opencode >/dev/null && timeout 20 opencode auth list 2>&1 | sed -e "s/\x1b\[[0-9;]*m//g" | grep -E "●|○" | sed "s/^/opencode_auth | /"'
as_runner 'env | cut -d= -f1 | grep -Ei "key|token|secret|auth" | sort | sed "s/^/env_name | /"'

sec "egress from the host (HTTP status codes)"
for u in https://api.anthropic.com https://api.openai.com https://chatgpt.com https://openrouter.ai/api/v1/models https://registry.npmjs.org https://pypi.org/simple/ https://github.com https://astral.sh/uv/install.sh https://claude.ai/install.sh https://opencode.ai/install https://prod.download.cli.kiro.dev https://gitlab.example.com https://api.typesafe.ai; do
  kv "egress $u" "$(curl -s -o /dev/null -w '%{http_code}' -m 10 "$u")"
done

sec "local services"
kv ollama "$(curl -s -m 3 http://localhost:11434/api/tags >/dev/null && echo up || echo down)"
kv docker_daemon "$(docker info --format '{{.ServerVersion}}' 2>/dev/null || echo 'not reachable for '"$(id -un)")"
echo
echo "INSPECT DONE"
