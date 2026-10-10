#!/usr/bin/env bash
# tracejob.sh <job-id> <logfile>: poll a job of project 118 every 20 s; append each new key trace line to <logfile>
export L4GL_ENV=/tmp/l4gl-wdl.env
MK=/Users/USER/src/l4/scripts/dev/mk-gitlab-api.sh
J=$1; L=$2; seen=0; T=$(mktemp)
while :; do
  st=$($MK GET "projects/118/jobs/$J" 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin)["status"])' 2>/dev/null || echo unknown)
  $MK GET "projects/118/jobs/$J/trace" 2>/dev/null | sed 's/\x1b\[[0-9;]*[a-zA-Z]//g; s/\r$//' > "$T" || true
  n=$(wc -l < "$T")
  if [ "$n" -gt "$seen" ]; then
    tail -n +"$((seen + 1))" "$T" | grep -E "\[l4\]|Job succeeded|Job failed|ERROR|Traceback|exit_code" | cut -c1-330 >> "$L"
    seen=$n
  fi
  case "$st" in success|failed|canceled|skipped) echo "$(date -u +%FT%TZ) JOB $J $st" >> "$L"; break;; esac
  sleep 20
done
rm -f "$T"
