#!/usr/bin/env bash
# L4 spike S-RUNNER: inventory l4-runner (prints no secret values)
set +e
echo "--- identity"; whoami; id; echo "HOME=$HOME SHELL=$SHELL"; echo "PATH=$PATH"
echo "--- os"; uname -a; cat /etc/os-release | head -4; nproc; free -m; df -h "$HOME" /tmp | tail -2
echo "--- sudo"; sudo -n true 2>&1 && echo "passwordless sudo: yes" || echo "passwordless sudo: no"
echo "--- login shells"; ls -la ~ | head -40
for t in git uv uvx python3 pip3 node npm npx bun bwrap docker podman claude codex opencode kiro-cli kiro gemini playwright chromium google-chrome ollama serena jq curl make go cargo rustc java; do
  p=$(command -v $t 2>/dev/null); if [ -n "$p" ]; then v=$(timeout 15 $t --version 2>&1 | head -1); echo "TOOL $t | $p | $v"; else echo "TOOL $t | MISSING"; fi
done
echo "--- user-local bins"; ls ~/.local/bin ~/.npm-global/bin ~/.opencode/bin ~/.bun/bin ~/.cargo/bin 2>/dev/null
echo "--- nvm"; ls ~/.nvm/versions/node 2>/dev/null
echo "--- auth presence (paths only)"; for f in ~/.claude/.credentials.json ~/.claude.json ~/.codex/auth.json ~/.codex/config.toml ~/.local/share/opencode/auth.json ~/.config/opencode/opencode.json ~/.config/opencode/opencode.jsonc ~/.local/share/kiro-cli ~/.aws/sso ~/.config/gh/hosts.yml; do [ -e "$f" ] && echo "PRESENT $f" || echo "ABSENT  $f"; done
echo "--- auth status"; timeout 20 codex login status 2>&1 | head -3; timeout 20 opencode auth list 2>&1 | sed 's/sk-[A-Za-z0-9_-]*/sk-***/g' | head -20; timeout 20 kiro-cli whoami 2>&1 | head -3
echo "--- env var names with KEY/TOKEN (names only)"; env | cut -d= -f1 | grep -Ei 'key|token|secret|auth' | sort
echo "--- egress"; for u in https://api.anthropic.com https://api.openai.com https://chatgpt.com https://openrouter.ai/api/v1/models https://registry.npmjs.org https://pypi.org/simple/ https://github.com https://gitlab.example.com https://api.typesafe.ai; do echo "$u $(curl -s -o /dev/null -w '%{http_code}' -m 10 $u)"; done
echo "--- user namespaces"; cat /proc/sys/kernel/unprivileged_userns_clone 2>/dev/null; cat /proc/sys/user/max_user_namespaces 2>/dev/null; sysctl kernel.apparmor_restrict_unprivileged_userns 2>/dev/null
echo "--- ollama"; curl -s -m 5 http://localhost:11434/api/tags | head -c 600; echo
echo "--- playwright cache"; ls ~/.cache/ms-playwright 2>/dev/null
echo "--- gitlab-runner"; ps -o user,cmd -C gitlab-runner 2>/dev/null | head -3; echo "builds dir: $CI_BUILDS_DIR  project dir: $CI_PROJECT_DIR"
echo "PROBE DONE"
