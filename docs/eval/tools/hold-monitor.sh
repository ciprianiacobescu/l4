#!/bin/bash
# hold-monitor.sh: every 60 s ask l4_idle.py (pending/running jobs of 118 and 119, the quiet window after a push) and
# mirror its answer into the runner's hold file: busy -> HOLD exists (eval-quiet.sh then says busy), idle -> removed.
# "unknown" (exit 2: the API did not answer) keeps the last state. Logs to $L4_EVAL_STATE/hold-monitor.log; touch
# STOP-MONITOR there to end it.
H=/Users/USER/src/l4
SP=${L4_EVAL_STATE:-${TMPDIR:-/tmp}/l4-eval}; mkdir -p "$SP"
W=${L4_EVAL_W:-/home/gitlab-runner/l4-eval-20261008}
state=unset
while [ ! -f "$SP/STOP-MONITOR" ]; do
  verdict=$(cd $H && timeout 120 uv run --no-project python scripts/dev/l4_idle.py 2>&1); rc=$?
  want=$state
  [ $rc -eq 0 ] && want=idle
  [ $rc -eq 1 ] && want=busy
  if [ "$want" != "$state" ]; then
    if [ "$want" = busy ]; then cmd="sudo -n -u gitlab-runner touch $W/HOLD"; else cmd="sudo -n -u gitlab-runner rm -f $W/HOLD"; fi
    if RSSH_TIMEOUT=120 $H/docs/live/free/tools/rssh.sh -- "$cmd" >/dev/null 2>&1; then
      echo "$(date -u +%FT%TZ) $want ($verdict)" >> "$SP/hold-monitor.log"; state=$want
    else
      echo "$(date -u +%FT%TZ) failed to set $want" >> "$SP/hold-monitor.log"
    fi
  fi
  sleep 60
done
echo "$(date -u +%FT%TZ) monitor stop" >> "$SP/hold-monitor.log"
