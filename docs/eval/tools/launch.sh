#!/bin/bash
# launch.sh OUT [l4 eval args...] — start `l4 eval` detached, as gitlab-runner. The first line of stdin is the
# magnitude key (may be empty); it goes into the eval process's environment only and is never printed or stored.
set -u
W=/home/gitlab-runner/l4-eval-20261008
IFS= read -r MAGNITUDE_API_KEY || true
export MAGNITUDE_API_KEY
export L4_CACHE=$W/cache
export L4_EVAL_HOLD=$W/HOLD
OUT=$1; shift
mkdir -p "$(dirname "$OUT")"
cd $W/harness || exit 2
setsid nohup .venv/bin/python -m l4 eval --config $W/profiles.yaml --out "$OUT" --runner \
  --idle-check "$W/harness/scripts/runner/eval-quiet.sh" --idle-wait 8h "$@" > "$OUT.log" 2>&1 < /dev/null &
echo "started pid $! out $OUT"
