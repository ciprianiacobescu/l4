#!/usr/bin/env bash
# eval-quiet.sh — the `l4 eval --idle-check` of a run on l4-runner (as gitlab-runner, outside CI).
#
#   exit 0: quiet, a cell may start; exit 1: busy.
#
# Busy when a CI job runs on this runner (the shell executor's job is a child of `gitlab-runner run`, as in
# docs/live/free/tools/driver.sh) or when the hold file exists. `scripts/dev/l4_idle.py` (pending jobs of 118 and 119,
# the quiet window after a push) needs Mintkey and runs on the maintainer's Mac: a loop there creates the hold file
# while it says busy and removes it when it says idle (docs/eval/README.md). The sample-consumer lanes have
# priority: a cell never starts while one of their jobs runs or waits.
HOLD=${L4_EVAL_HOLD:-$HOME/l4-eval/HOLD}
[ -e "$HOLD" ] && exit 1
svc=$(pgrep -o -f 'gitlab-runner run' 2>/dev/null) || exit 0
pgrep -P "$svc" >/dev/null 2>&1 && exit 1
exit 0
