#!/usr/bin/env bash
# probe_t1.sh <data-dir> <checkpoint-dir> [--train]   (M16-G16; run from anywhere, uses the scripts/s1 environment)
#
# Probe T1: how a checkpoint saved by the vendored script is loaded, evaluated and served by laya 0.3.24.
#   a) the vendored script imports under the pinned laya
#   b) laya.load(<dir>) loads it and answers
#   c) LAYA_MODELS=<dir> laya-serve            (does serve take a path?)
#   d) private HF_HOME overlay, HF_HUB_OFFLINE=1, laya-serve answers /health with the overlay's revision
#   e) laya-evals run --model <dir>            (does the CLI take a path?)
#   f) with --train: a tiny training run, wall time, peak memory (max RSS) and disk
# Prints one line per probe, "ok" or "no: <why>". Writes only under a temp directory.
set -uo pipefail
DATA=${1:?data dir}; CKPT=$(cd "${2:?checkpoint dir}" && pwd); TRAIN=${3:-}
HERE=$(cd "$(dirname "$0")" && pwd)
RUN=(uv run --project "$HERE" --quiet)
TMP=$(mktemp -d); trap 'rm -rf "$TMP"; [ -n "${SERVE_PID:-}" ] && kill "$SERVE_PID" 2>/dev/null' EXIT
echo "probe T1 $(date -u +%FT%TZ) on $(uname -sm); laya $("${RUN[@]}" python -c 'import laya,importlib.metadata as m;print(m.version("laya"))' 2>/dev/null)"

if "${RUN[@]}" python - <<PY >"$TMP/a" 2>&1
import sys; sys.path.insert(0, "$HERE/vendor")
import laya_finetune_mps  # noqa: F401  (imports laya.common/agent names at module level)
from laya.common import build_model, build_sequence, proper_reward, render_options, QTYPES
from laya.agent import _fix_tokenizer_config
PY
then echo "a) vendored script imports under the pinned laya: ok"; else echo "a) no: $(tail -1 "$TMP/a")"; fi

"${RUN[@]}" python - <<PY >"$TMP/b" 2>&1
import json, laya
a = laya.load("$CKPT", device="cpu")
row = json.loads(open("$DATA/test.jsonl").readline())
out = a.predict(row["state"], row["questions"])
print("answers", len(out["answers"]), "state_tokens", out["usage"]["state_tokens"], "input_tokens", out["usage"]["input_tokens"])
PY
if [ $? = 0 ]; then echo "b) laya.load(<dir>) answers (max_len 1024 checkpoint): ok ($(tail -1 "$TMP/b"))"; else echo "b) no: $(tail -1 "$TMP/b")"; fi

PORT=$((20000 + RANDOM % 20000))
serve_env=(env -i PATH="$HERE/.venv/bin:/usr/bin:/bin" HOME="$HOME" LAYA_HOST=127.0.0.1 LAYA_PORT=$PORT LAYA_PRELOAD=1 LAYA_DEVICE=cpu HF_HUB_OFFLINE=1)
"${serve_env[@]}" LAYA_MODELS="$CKPT" "$HERE/.venv/bin/laya-serve" >"$TMP/c" 2>&1 &
SERVE_PID=$!; sleep 15
if curl -fs "127.0.0.1:$PORT/health" >/dev/null 2>&1; then echo "c) LAYA_MODELS=<dir> laya-serve: ok"; else echo "c) no: $(grep -E 'Error' "$TMP/c" | tail -1 | cut -c1-160)"; fi
kill "$SERVE_PID" 2>/dev/null; wait "$SERVE_PID" 2>/dev/null; SERVE_PID=""

HUB=$TMP/hf/hub/models--convaiinnovations--laya
mkdir -p "$HUB/snapshots/probe-t1" "$HUB/refs"; printf probe-t1 >"$HUB/refs/main"
ln -s "$CKPT" "$HUB/snapshots/probe-t1/typed-decisions"
"${serve_env[@]}" HF_HOME="$TMP/hf" LAYA_MODELS=typed-decisions "$HERE/.venv/bin/laya-serve" >"$TMP/d" 2>&1 &
SERVE_PID=$!
for _ in $(seq 1 45); do HEALTH=$(curl -fs "127.0.0.1:$PORT/health" 2>/dev/null) && break; sleep 2; done
if [ -n "${HEALTH:-}" ]; then echo "d) HF_HOME overlay + HF_HUB_OFFLINE=1 laya-serve: ok ($HEALTH)" | cut -c1-200; else echo "d) no: $(tail -1 "$TMP/d" | cut -c1-160)"; fi
kill "$SERVE_PID" 2>/dev/null; wait "$SERVE_PID" 2>/dev/null; SERVE_PID=""

if "${RUN[@]}" laya-evals run "$DATA/test.jsonl" --model "$CKPT" --device cpu >"$TMP/e" 2>&1; then echo "e) laya-evals run --model <dir>: ok"
else echo "e) no: $(tail -1 "$TMP/e" | cut -c1-160)"; fi

if [ "$TRAIN" = "--train" ]; then
  START=$(date +%s)
  /usr/bin/time -l "${RUN[@]}" python "$HERE/laya_tune.py" train --data "$DATA" --base "${BASE:?set BASE=typed-decisions@<rev>}" \
    --out "$TMP/tiny" --cache "${BASE_CACHE:-$TMP/base}" --epochs 1 --max-rows 12 >"$TMP/f" 2>&1
  echo "f) tiny training run (12 rows, 1 epoch): exit $? in $(( $(date +%s) - START )) s, $(grep 'maximum resident' "$TMP/f" | awk '{printf "%.1f GB", $1/1e9}') peak RSS, checkpoint $(du -sh "$TMP/tiny" | cut -f1)"
fi
