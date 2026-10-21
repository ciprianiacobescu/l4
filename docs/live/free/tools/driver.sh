#!/usr/bin/env bash
# driver.sh — free-model measurement on the runner, as gitlab-runner, outside CI (forge/ci local).
# Reads $W/queue.txt lines: LABEL KIND UNIT IMPL JUDGES CLARIFIER VAGENT CLAR_ON GENTESTS
#   KIND impl  : fresh origin copy, `l4 run --unit openspec:UNIT` (red/green, gates, claude-code judge)
#   KIND judge : fresh origin copy (the unit branch sits at its green commit), `l4 run --unit` (verify only)
# Each run waits until no CI job runs on this runner, records CI overlap, and stops the queue on a 429/rate limit.
# Writes $W/runs/LABEL/{cfg.yaml,run.log,status.txt,meta.txt,ci-overlap.txt}; $W/STOP halts after the current run.
set -u
W=${W:-/home/gitlab-runner/l4-free-20261006}
cd "$W" || exit 2
export L4_CACHE="$W/cache"  # own runner cache: the default one keys worktrees by unit name across repositories
log() { echo "$(date -u +%FT%TZ) $*" >> "$W/driver.log"; }
ci_busy() {  # a CI job is running when the gitlab-runner service has a job child (shell executor)
  local svc
  svc=$(pgrep -o -f 'gitlab-runner run' 2>/dev/null) || return 1
  pgrep -P "$svc" >/dev/null 2>&1
}
wait_idle() {
  local waited=0
  while ci_busy; do
    [ $waited -eq 0 ] && log "waiting: a CI job runs on this runner"
    sleep 20; waited=$((waited + 20))
    [ -f "$W/STOP" ] && return 1
  done
  [ $waited -gt 0 ] && log "idle after ${waited}s"
  return 0
}
log "driver start pid $$"
while read -r LABEL KIND UNIT IMPL JUDGES CLAR VAGENT CLAR_ON GENTESTS; do
  case "$LABEL" in ''|\#*) continue;; esac
  R="$W/runs/$LABEL"
  if [ -f "$R/meta.txt" ] && grep -q '^END' "$R/meta.txt"; then continue; fi
  [ -f "$W/STOP" ] && { log "STOP file present, not starting $LABEL"; break; }
  if [ -f "$W/blocked-models" ] && grep -q -x -E "$IMPL|$JUDGES" "$W/blocked-models"; then log "skip $LABEL: model blocked after a 429"; continue; fi
  wait_idle || break
  rm -rf "$R" "$L4_CACHE/worktrees/openspec/$UNIT" "$L4_CACHE/units/openspec/$UNIT"; mkdir -p "$R"
  cp -a "$W/origin-seed.git" "$R/origin.git"
  git clone -q "$R/origin.git" "$R/repo"
  [ "$VAGENT" = "-" ] && VAGENT=""
  [ "$CLAR" = "-" ] && CLAR=""
  sed -e "s/@IMPL@/$IMPL/; s/@JUDGES@/$JUDGES/; s/@CLARIFIER@/$CLAR/; s/@VAGENT@/$VAGENT/; s/@CLARIFIER_ON@/$CLAR_ON/; s/@GENTESTS@/$GENTESTS/" \
    "$W/cfg.tmpl.yaml" > "$R/cfg.yaml"
  { echo "LABEL=$LABEL KIND=$KIND UNIT=$UNIT IMPL=$IMPL JUDGES=$JUDGES CLAR=$CLAR VAGENT=$VAGENT CLAR_ON=$CLAR_ON GENTESTS=$GENTESTS"
    echo "START $(date -u +%FT%TZ)"
    echo "origin main $(git -C "$R/origin.git" rev-parse main) unit branch $(git -C "$R/origin.git" rev-parse --verify -q "l4/openspec/$UNIT" || echo none)"; } > "$R/meta.txt"
  ( while sleep 30; do ci_busy && echo "$(date -u +%FT%TZ) CI job running"; done ) > "$R/ci-overlap.txt" 2>&1 &
  MON=$!
  log "start $LABEL ($KIND $UNIT impl=$IMPL judges=$JUDGES)"
  s=$(date +%s)
  ( cd "$R/repo" && timeout 50m .l4/bin/l4 run --config "$R/cfg.yaml" --unit "openspec:$UNIT" ) > "$R/run.log" 2>&1
  rc=$?
  e=$(date +%s)
  kill "$MON" 2>/dev/null; wait "$MON" 2>/dev/null
  ( cd "$R/repo" && timeout 5m .l4/bin/l4 status --config "$R/cfg.yaml" ) > "$R/status.txt" 2>&1
  git -C "$R/origin.git" log --format='%h %an | %s' "main..l4/openspec/$UNIT" > "$R/branch-log.txt" 2>&1
  echo "END rc=$rc secs=$((e - s)) at $(date -u +%FT%TZ)" >> "$R/meta.txt"
  log "end $LABEL rc=$rc secs=$((e - s))"
  grep -r -h -o -i -E '.{0,120}(rate.?limit(ed)?|too many requests|status[^0-9a-z]{0,6}429|\[429\]|HTTP 429|FreeTierError).{0,120}' \
    "$R/run.log" "$R/repo/.l4-out" 2>/dev/null | head -20 > "$R/ratelimit.txt"
  if [ -s "$R/ratelimit.txt" ]; then  # the free model of this run (implementer, else judge) gets no more calls
    M=$IMPL; case "$M" in f-*) ;; *) M=$JUDGES;; esac
    echo "$M" >> "$W/blocked-models"
    log "RATE-LIMIT or free-tier error seen in $LABEL: $M blocked for the rest of the queue"
    if [ "$(sort -u "$W/blocked-models" | wc -l)" -ge 2 ]; then
      log "a second model hit a rate limit: stopping the queue"; touch "$W/STOP"; break
    fi
  fi
done < "$W/queue.txt"
log "driver exit"
