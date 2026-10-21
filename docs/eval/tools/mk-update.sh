#!/bin/bash
# mk-update.sh > update-remote.sh: bring the runner's harness checkout to the bundled main (fast-forward only).
# Make the bundle first, next to this script: git bundle create docs/eval/tools/update.bundle <runner head>..main
SP=$(cd "$(dirname "$0")" && pwd)
W=${L4_EVAL_W:-/home/gitlab-runner/l4-eval-20261008}
echo 'set -eu'
echo "base64 -d <<'B64EOF' | sudo -n -u gitlab-runner tee $W/update.bundle >/dev/null"
base64 -i "$SP/update.bundle"
echo "B64EOF"
echo "sudo -n -u gitlab-runner -H bash -lc 'cd $W/harness && git fetch -q $W/update.bundle main && git merge -q --ff-only FETCH_HEAD && git log --oneline -1 && uv sync --frozen -q && git status --porcelain --untracked-files=no | wc -l'"
