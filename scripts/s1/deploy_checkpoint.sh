#!/usr/bin/env bash
# deploy_checkpoint.sh <id> [--dry-run]
#
# Copies a GATED checkpoint from $L4_CACHE/s1/checkpoints/<id> on this Mac to the runner through the Mintkey SSH
# bastion (scripts/runner/mk-ssh.sh), then re-checks the sha256 of model.safetensors there. It refuses a checkpoint
# whose l4-train.json says the gate did not pass, whose gate.json is not the document the record names (the flag is
# bound to it by sha256, so a boolean flipped by hand is refused), whose files no longer match their recorded sha256,
# or that holds a file the record does not list. It copies exactly the recorded files, gate.json and the record.
set -euo pipefail

ID="" DRY=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY=1 ;;
    -*) echo "usage: deploy_checkpoint.sh <id> [--dry-run]" >&2; exit 2 ;;
    *) ID=$arg ;;
  esac
done
# the id goes into a command line that runs on the runner: letters, digits, dot, dash and underscore only
if ! [[ "$ID" =~ ^[A-Za-z0-9_-][A-Za-z0-9._-]*$ ]]; then
  echo "usage: deploy_checkpoint.sh <id> [--dry-run]  (id: [A-Za-z0-9._-]+, a name under s1/checkpoints)" >&2; exit 2
fi

CACHE=${L4_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/l4}
SRC=$CACHE/s1/checkpoints/$ID
REMOTE_REL=.cache/l4/s1/checkpoints/$ID
HERE=$(cd "$(dirname "$0")" && pwd)

PLAN=$(python3 - "$SRC" <<'PY'
import hashlib, json, re, sys
from pathlib import Path

src = Path(sys.argv[1])
try:
    record = json.loads((src / "l4-train.json").read_text())
except (OSError, ValueError):
    sys.exit("l4-train.json is missing or unreadable")
gate = record.get("gate") or {}
if not (gate.get("ran") and gate.get("passed") is True):
    sys.exit("the checkpoint has not passed the laya-evals gate")
files = record.get("files") or {}
doc = src / "gate.json"
if not gate.get("document_sha256") or doc.is_symlink() or not doc.is_file():
    sys.exit("gate.json is missing or l4-train.json records no sha256 for it: gate the checkpoint again")
if hashlib.sha256(doc.read_bytes()).hexdigest() != gate["document_sha256"]:
    sys.exit("gate.json does not match the sha256 in l4-train.json")
try:
    gate_doc = json.loads(doc.read_text())
except ValueError:
    sys.exit("gate.json is unreadable")
if not isinstance(gate_doc, dict) or gate_doc.get("passed") is not True:
    sys.exit("the checkpoint has not passed the laya-evals gate (gate.json says so)")
if gate_doc.get("checkpoint_sha256") != files.get("model.safetensors"):
    sys.exit("gate.json gated another checkpoint")
if "model.safetensors" not in files or "rl_agent_config.json" not in files:
    sys.exit("l4-train.json records no sha256 for the weights or the config")
safe = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]*(/[A-Za-z0-9_][A-Za-z0-9._-]*)*$")
for name, want in sorted(files.items()):
    target = src / name
    if not safe.match(name) or target.is_symlink() or not target.is_file():
        sys.exit(f"{name} is not a plain file of the checkpoint")
    if hashlib.sha256(target.read_bytes()).hexdigest() != want:
        sys.exit(f"{name} does not match the sha256 in l4-train.json")
on_disk = {p.relative_to(src).as_posix() for p in src.rglob("*") if p.is_file() or p.is_symlink()}
extra = sorted(on_disk - set(files) - {"l4-train.json", "gate.json"})
if extra:
    sys.exit(f"{extra[0]} is in the checkpoint but not in l4-train.json")
print(files["model.safetensors"])
print(" ".join([*sorted(files), "gate.json", "l4-train.json"]))
PY
) || { echo "deploy_checkpoint: refusing $ID" >&2; exit 2; }
DIGEST=$(printf '%s\n' "$PLAN" | sed -n 1p)
FILES=$(printf '%s\n' "$PLAN" | sed -n 2p)

echo "checkpoint $ID: gate passed, sha256 intact"
if [ "$DRY" = 1 ]; then
  echo "dry run: nothing is copied"
  echo "1. tar -C $SRC -cf - $FILES"
  echo "2. scripts/runner/mk-ssh.sh -- 'mkdir -p ~gitlab-runner/$REMOTE_REL && tar -x -C ~gitlab-runner/$REMOTE_REL'"
  echo "3. scripts/runner/mk-ssh.sh -- 'sha256sum ~gitlab-runner/$REMOTE_REL/model.safetensors' must print $DIGEST"
else
  # shellcheck disable=SC2086
  tar -C "$SRC" -cf - $FILES | "$HERE/../runner/mk-ssh.sh" -- "mkdir -p ~gitlab-runner/$REMOTE_REL && tar -x -C ~gitlab-runner/$REMOTE_REL"
  REMOTE=$("$HERE/../runner/mk-ssh.sh" -- "sha256sum ~gitlab-runner/$REMOTE_REL/model.safetensors" | awk '{print $1}')
  [ "$REMOTE" = "$DIGEST" ] || { echo "deploy_checkpoint: sha256 on the runner differs ($REMOTE)" >&2; exit 1; }
  echo "runner sha256 matches"
fi
cat <<YML
profiles:
  laya-tuned:
    backend: system-one
    engine: laya-local
    model: /home/gitlab-runner/$REMOTE_REL
YML
