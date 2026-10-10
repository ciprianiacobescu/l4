#!/usr/bin/env bash
# watchjob.sh <job-id> <outdir>: poll a job of project 118 until it ends; save the ANSI-stripped trace, job json, artefacts
set -uo pipefail
export L4GL_ENV=/tmp/l4gl-wdl.env
MK=/Users/USER/src/l4/scripts/dev/mk-gitlab-api.sh
J=$1; O=$2; mkdir -p "$O"
while :; do
  st=$($MK GET "projects/118/jobs/$J" 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin)["status"])' 2>/dev/null || echo unknown)
  case "$st" in success|failed|canceled|skipped) break;; esac
  sleep 30
done
sleep 5
$MK GET "projects/118/jobs/$J" > "$O/job-$J.json" 2>/dev/null
$MK GET "projects/118/jobs/$J/trace" 2>/dev/null | sed 's/\x1b\[[0-9;]*[a-zA-Z]//g; s/\r$//' > "$O/job-$J.log"
$MK GET "projects/118/jobs/$J/artifacts" > "$O/job-$J-artifacts.zip" 2>/dev/null || echo "no artefacts"
echo "job $J $st $(python3 -c 'import json,sys;j=json.load(open(sys.argv[1]));print(j.get("duration"), j.get("started_at"), j.get("finished_at"))' "$O/job-$J.json")"
