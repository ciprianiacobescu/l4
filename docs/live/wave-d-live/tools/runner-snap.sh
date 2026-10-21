#!/usr/bin/env bash
# runner-snap.sh <framework>/<unit> [change-subdir]: READ-ONLY snapshot on the runner (run through mk-ssh.sh --script).
# Prints the gitlab-runner process tree, the builds dir's l4 logs and outcome, the unit worktree's ledger tails and
# the lease files. Writes nothing; never prints the environment of a process.
set -u
U=${1:-}
echo "=== now $(date -u +%FT%TZ)"
echo "=== processes of gitlab-runner (and the runner service)"
ps -eo pid,ppid,pgid,sid,user,etime,lstart,cmd --sort=start_time | awk 'NR==1 || $5=="gitlab-+" || $5=="gitlab-runner" || /gitlab-runner run/' | grep -v "awk \|ps -eo" | cut -c1-260
B=/home/gitlab-runner/builds/XXXXXXXXX/0/example-group/dummy-agentic
echo "=== builds dir .l4-out"
sudo -n ls -la "$B/.l4-out" "$B/.l4-out/logs" 2>&1 | head -20
sudo -n cat "$B/.l4-out/outcome.json" 2>&1 | head -40
for f in $(sudo -n ls -t "$B/.l4-out/logs/" 2>/dev/null | head -3); do
  echo "--- log $f (cancel/lock/exit lines)"
  sudo -n grep -E '"(cancel|lock|exit|run)|cancel|lock\.|stopping the run|session check|exit 16|run finished' "$B/.l4-out/logs/$f" | tail -25 | cut -c1-400
done
if [ -n "$U" ]; then
  W=/home/gitlab-runner/.cache/l4/worktrees/$U
  echo "=== worktree $W"
  sudo -n git -c safe.directory='*' -C "$W" log --oneline -6 2>&1 | head -8
  sudo -n git -c safe.directory='*' -C "$W" --no-optional-locks status --short 2>&1 | head -10
  for f in $(sudo -n find "$W" -path '*/.l4/ledger*' -name '*.jsonl' -newermt '-3 hours' 2>/dev/null); do
    echo "--- ledger $f (last 8 events)"
    sudo -n tail -8 "$f" | cut -c1-300
  done
fi
echo "=== lease files"
sudo -n find /home/gitlab-runner/.cache/l4/locks -type f -newermt '-3 hours' -printf '%TY-%Tm-%TdT%TH:%TM:%TS %s %p\n' 2>/dev/null | sort | tail -10
for f in $(sudo -n find /home/gitlab-runner/.cache/l4/locks -type f -newermt '-3 hours' 2>/dev/null); do echo "--- $f: $(sudo -n cat "$f" | head -c 400)"; done
