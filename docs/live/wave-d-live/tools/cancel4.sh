#!/usr/bin/env bash
# cancel4.sh <job-id> <outdir>: wait until the l4 job has pushed the unit branch once and started the next agent step,
# then cancel the job and delete the unit branch through the API, and take read-only runner snapshots at +30/+60/+150 s.
set -uo pipefail
export L4GL_ENV=/tmp/l4gl-wdl.env
MK=/Users/USER/src/l4/scripts/dev/mk-gitlab-api.sh
SSH=/Users/USER/src/l4/scripts/runner/mk-ssh.sh
HERE=$(cd "$(dirname "$0")" && pwd)
J=$1; O=$2; mkdir -p "$O"
BR=l4/openspec/add-three-for-two; BRE=l4%2Fopenspec%2Fadd-three-for-two
TL=$O/timeline.txt; T=$O/trace-before-cancel.txt
ts() { python3 -c 'import datetime;print(datetime.datetime.now(datetime.UTC).isoformat(timespec="milliseconds").replace("+00:00","Z"))'; }
note() { echo "$(ts) $*" >> "$TL"; }
jobst() { $MK GET "projects/118/jobs/$J" 2>/dev/null | python3 -c 'import sys,json;j=json.load(sys.stdin);print(j["status"], j.get("started_at"), j.get("finished_at"), j.get("duration"))' 2>/dev/null || echo "unknown"; }
note "watching job $J"
pushed=0
while :; do
  $MK GET "projects/118/jobs/$J/trace" 2>/dev/null | sed 's/\x1b\[[0-9;]*[a-zA-Z]//g; s/\r$//' > "$T.tmp" && mv "$T.tmp" "$T"
  if [ $pushed -eq 0 ] && grep -q "pushed $BR" "$T"; then pushed=1; note "trace shows the first push: $(grep -m1 "pushed $BR" "$T" | cut -c1-200)"; fi
  if [ $pushed -eq 1 ] && awk '/pushed l4\/openspec\/add-three-for-two/{p=1} p && /lint-baseline pass/{f=1} END{exit !f}' "$T"; then
    note "trace shows the next step's lint-baseline after the push (the green agent starts): $(grep 'lint-baseline pass' "$T" | tail -1 | cut -c1-160)"; break
  fi
  st=$(jobst); case "$st" in success*|failed*|canceled*|skipped*) note "job ended before the trigger: $st"; exit 1;; esac
  sleep 3
done
sleep 6
note "CANCEL POST projects/118/jobs/$J/cancel"
$MK POST "projects/118/jobs/$J/cancel" 2>>"$O/api-errors.txt" | python3 -c 'import sys,json;j=json.load(sys.stdin);print("cancel response:", j["id"], j["status"])' >> "$TL" 2>&1
note "DELETE projects/118/repository/branches/$BRE"
if $MK DELETE "projects/118/repository/branches/$BRE" >/dev/null 2>>"$O/api-errors.txt"; then note "delete: ok (2xx)"; else note "delete: FAILED"; fi
$MK GET "projects/118/repository/branches/$BRE" >/dev/null 2>&1 && note "branch GET after delete: still exists" || note "branch GET after delete: absent (404)"
note "job status right after: $(jobst)"
CT=$(date +%s)
snap() {  # snap <label> <at-seconds-after-cancel>
  local now; now=$(date +%s); [ $(( CT + $2 - now )) -gt 0 ] && sleep $(( CT + $2 - now ))
  note "runner snapshot $1 starts"
  timeout 120 "$SSH" --script "$HERE/runner-snap.sh" -- openspec/add-three-for-two > "$O/runner-$1.txt" 2>&1
  note "runner snapshot $1 done"
}
( snap plus30 30 ) &
( snap plus60 60 ) &
( snap plus150 150 ) &
for i in $(seq 1 40); do
  st=$(jobst); note "job status: $st"
  case "$st" in canceled*|success*|failed*) break;; esac
  sleep 5
done
wait
$MK GET "projects/118/repository/branches/$BRE" >/dev/null 2>&1 && note "branch GET at end: EXISTS" || note "branch GET at end: absent (404)"
$MK GET "projects/118/jobs/$J/trace" 2>/dev/null | sed 's/\x1b\[[0-9;]*[a-zA-Z]//g; s/\r$//' > "$O/trace-final.txt"
$MK GET "projects/118/jobs/$J" > "$O/job-$J.json" 2>/dev/null
note "done"
