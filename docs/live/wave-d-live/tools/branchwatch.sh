#!/usr/bin/env bash
# branchwatch.sh <out>: every 30 s, does l4/openspec/add-three-for-two exist (and its head, author, message), and which is
# the newest l4 job of project 118; stops once an l4 job newer than 6273 has finished.
export L4GL_ENV=/tmp/l4gl-wdl.env
MK=/Users/USER/src/l4/scripts/dev/mk-gitlab-api.sh
O=$1
while :; do
  now=$(date -u +%FT%TZ)
  b=$($MK GET "projects/118/repository/branches/l4%2Fopenspec%2Fadd-three-for-two" 2>/dev/null | python3 -c 'import sys,json;b=json.load(sys.stdin);c=b["commit"];print("EXISTS head",c["id"][:10],c["author_name"],c["created_at"],c["title"][:80])' 2>/dev/null || echo "absent")
  j=$($MK GET "projects/118/jobs?scope[]=running&scope[]=pending&scope[]=success&scope[]=failed&scope[]=canceled&per_page=10" 2>/dev/null | python3 -c 'import sys,json;js=[x for x in json.load(sys.stdin) if x["name"]=="l4"];x=max(js,key=lambda x:x["id"]);print(x["id"],x["status"],x["pipeline"]["source"],x.get("started_at"),x.get("finished_at"))' 2>/dev/null || echo "jobs ?")
  echo "$now branch: $b | newest l4 job: $j" >> "$O"
  set -- $j
  if [ "${1:-0}" -gt 6273 ] 2>/dev/null && case "${2:-}" in success|failed|canceled) true;; *) false;; esac; then echo "$now next l4 job $1 ended: $2" >> "$O"; break; fi
  sleep 30
done
