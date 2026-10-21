#!/usr/bin/env bash
# tracejob.sh <job-id>: poll a job of project 118; print each new key trace line; print the final status and exit
MK=/Users/USER/src/l4/scripts/dev/mk-gitlab-api.sh
J=$1; seen=0; T=$(mktemp)
while :; do
  st=$($MK GET "projects/118/jobs/$J" 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin)["status"])' 2>/dev/null || echo unknown)
  $MK GET "projects/118/jobs/$J/trace" 2>/dev/null | sed 's/\x1b\[[0-9;]*[a-zA-Z]//g; s/\r$//' > "$T" || true
  n=$(wc -l < "$T")
  if [ "$n" -gt "$seen" ]; then
    tail -n +"$((seen + 1))" "$T" | grep -E --line-buffered "sweeper|done-gate|task [0-9.]+ (red|green)|attempt [0-9]+ failed|already|pre-satisf|halt|breaker|rate.limit|cool|throttl|verdict|independence|judges:|implementer:|MR !|run finished|Job succeeded|Job failed|ERROR|Traceback|nothing to do|exit_code|labels" | cut -c1-260
    seen=$n
  fi
  case "$st" in success|failed|canceled|skipped) echo "JOB $J $st"; break;; esac
  sleep 60
done
rm -f "$T"
