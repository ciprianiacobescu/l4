#!/bin/bash
# peek.sh RUN: the eval log tail, the cells with a result, and whether the eval process lives
H=/Users/USER/src/l4
W=${L4_EVAL_W:-/home/gitlab-runner/l4-eval-20261008}; R=$1
RSSH_TIMEOUT=120 $H/docs/live/free/tools/rssh.sh -- "sudo -n -u gitlab-runner -H bash -c 'tail -5 $W/out/$R.log; ls $W/out/$R/cells 2>/dev/null; for f in $W/out/$R/cells/*/result.json; do [ -f \$f ] && python3 -c \"import json,sys; d=json.load(open(sys.argv[1])); print(d[\\\"cell_key\\\"], d[\\\"status\\\"], d.get(\\\"invalid_reason\\\"), d.get(\\\"verdict\\\"), d.get(\\\"attempts\\\"), d.get(\\\"halted_at\\\"), round(d[\\\"wall_s\\\"]), [e[\\\"kind\\\"] for e in d[\\\"errors\\\"]])\" \$f; done; ls -la $W/HOLD 2>/dev/null; pgrep -u gitlab-runner -f \"l4 eval\" | head -3'"
