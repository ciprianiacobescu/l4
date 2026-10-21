#!/bin/bash
# mk-setup.sh > setup-remote.sh: the one-shot runner setup of the eval (files via base64, owned by gitlab-runner).
# Needs next to this script: harness.bundle (git bundle create docs/eval/tools/harness.bundle main) and profiles.yaml
# (the project config, e.g. dummy-agentic's .l4/config.yaml). The hold file starts present: hold-monitor.sh removes it.
SP=$(cd "$(dirname "$0")" && pwd)
W=${L4_EVAL_W:-/home/gitlab-runner/l4-eval-20261008}
put() { echo "base64 -d <<'B64EOF' | sudo -n -u gitlab-runner tee $W/$2 >/dev/null"; base64 -i "$1"; echo "B64EOF"; }
echo 'set -eu'
echo "sudo -n -u gitlab-runner -H bash -c 'mkdir -p $W/cache $W/out && chmod 700 $W && touch $W/HOLD'"
put "$SP/harness.bundle" harness.bundle
put "$SP/profiles.yaml" profiles.yaml
put "$SP/launch.sh" launch.sh
echo "sudo -n -u gitlab-runner chmod 700 $W/launch.sh"
cat <<EOF
sudo -n -u gitlab-runner -H bash -lc 'cd $W && rm -rf harness && git clone -q -b main harness.bundle harness && cd harness && git log --oneline -1 && uv sync --frozen -q 2>&1 | tail -3 && .venv/bin/python -m l4 --version; git status --porcelain --untracked-files=no | wc -l'
EOF
