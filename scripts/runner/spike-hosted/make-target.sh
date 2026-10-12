#!/usr/bin/env bash
# make-target.sh HARNESS_DIR TARGET_DIR — SPIKE: build a throwaway Python target project and adopt the harness
# (vendored from HARNESS_DIR, which must be a clean git checkout) with four CLIs in a role chain, so that
# `l4 doctor --ci --fix` has all of opencode, claude-code, codex and kiro-cli to provision.
set -euo pipefail
H=$(cd "${1:?usage: make-target.sh HARNESS_DIR TARGET_DIR}" && pwd)
T=${2:?usage: make-target.sh HARNESS_DIR TARGET_DIR}
mkdir -p "$T"; T=$(cd "$T" && pwd)
[ -z "$(ls -A "$T")" ] || { echo "target $T is not empty" >&2; exit 2; }
cd "$T"

mkdir calc tests
printf 'def add(a, b):\n    return a + b\n' > calc/__init__.py
printf 'from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n' > tests/test_calc.py
cat > pyproject.toml <<'EOF'
[project]
name = "calc"
version = "0.1.0"
requires-python = ">=3.10"

[project.optional-dependencies]
dev = ["pytest"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
EOF
uv lock
git init -q -b main
G="git -c user.name=spike -c user.email=spike@example.invalid"
git add -A && $G commit -qm "calc: add"

uv run --frozen --project "$H" l4 init --vendor --ci github --harness "$H"

# Replace the profiles/roles init wrote: four CLIs, each in a chain (provisioning installs only CLIs a chain uses).
python3 - <<'EOF'
s = open(".l4/config.yaml").read()
head = s[: s.index("profiles:")]
open(".l4/config.yaml", "w").write(head + """profiles:
  oc-free:
    adapter: opencode
    model: opencode/mimo-v2.6-flash-free
    vendor: xiaomi
  claude-code:
    adapter: claude-code
    vendor: anthropic
    auth: subscription      # CLAUDE_CODE_OAUTH_TOKEN
  codex:
    adapter: codex
    vendor: openai
    auth: api_key           # CODEX_API_KEY
  kiro:
    adapter: kiro-cli
    vendor: anthropic
    auth: api_key           # KIRO_API_KEY
roles:
  implementer: [oc-free, kiro, codex, claude-code]
  judges: [claude-code, codex]
forge:
  type: github
ci:
  platform: github
""")
EOF
uv run --frozen --project "$H" l4 doctor --adoption --no-gates --repo "$T"
git add -A && $G commit -qm "adopt the L4 harness (spike)"
echo "target ready: $T"
