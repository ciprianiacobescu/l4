import hashlib
import json
import os
import subprocess
from pathlib import Path

from ._tune import S1

SCRIPT = S1 / "deploy_checkpoint.sh"


def checkpoint(cache: Path, name: str, *, gated: bool) -> tuple[Path, str]:
    ckpt = cache / "s1" / "checkpoints" / name
    (ckpt / "encoder").mkdir(parents=True)
    (ckpt / "model.safetensors").write_bytes(b"weights")
    (ckpt / "rl_agent_config.json").write_text("{}")
    digest = hashlib.sha256(b"weights").hexdigest()
    document = json.dumps({"schema": "l4/s1-gate@1", "passed": gated, "checkpoint_sha256": digest})
    (ckpt / "gate.json").write_text(document)
    record = {
        "files": {"model.safetensors": digest, "rl_agent_config.json": hashlib.sha256(b"{}").hexdigest()},
        "gate": {"ran": True, "passed": gated, "document_sha256": hashlib.sha256(document.encode()).hexdigest()},
    }
    (ckpt / "l4-train.json").write_text(json.dumps(record))
    return ckpt, digest


def run(cache: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {"PATH": os.environ["PATH"], "HOME": str(cache / "home"), "L4_CACHE": str(cache)}
    return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, check=False)


def test_dry_run_plan_and_refuses_ungated(tmp_path: Path):
    cache = tmp_path / "cache"
    ckpt, digest = checkpoint(cache, "ck-2026-10-04", gated=True)
    done = run(cache, "ck-2026-10-04", "--dry-run")
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == [
        "checkpoint ck-2026-10-04: gate passed, sha256 intact",
        "dry run: nothing is copied",
        f"1. tar -C {ckpt} -cf - model.safetensors rl_agent_config.json gate.json l4-train.json",
        "2. scripts/runner/mk-ssh.sh -- 'mkdir -p ~gitlab-runner/.cache/l4/s1/checkpoints/ck-2026-10-04 && "
        "tar -x -C ~gitlab-runner/.cache/l4/s1/checkpoints/ck-2026-10-04'",
        "3. scripts/runner/mk-ssh.sh -- 'sha256sum ~gitlab-runner/.cache/l4/s1/checkpoints/ck-2026-10-04/"
        f"model.safetensors' must print {digest}",
        "profiles:",
        "  laya-tuned:",
        "    backend: system-one",
        "    engine: laya-local",
        "    model: /home/gitlab-runner/.cache/l4/s1/checkpoints/ck-2026-10-04",
    ]
    flipped, _ = checkpoint(cache, "flipped", gated=False)  # gate.json says failed; the record's flag is flipped
    record = json.loads((flipped / "l4-train.json").read_text())
    record["gate"]["passed"] = True
    (flipped / "l4-train.json").write_text(json.dumps(record))
    refused = run(cache, "flipped", "--dry-run")
    assert refused.returncode == 2 and "gate.json" in refused.stderr and refused.stdout == ""
    edited, _ = checkpoint(cache, "edited", gated=False)  # both flipped, the recorded sha256 not recomputed
    record = json.loads((edited / "l4-train.json").read_text())
    record["gate"]["passed"] = True
    (edited / "l4-train.json").write_text(json.dumps(record))
    (edited / "gate.json").write_text(json.dumps({"passed": True}))
    assert "gate.json does not match" in run(cache, "edited", "--dry-run").stderr
    ungated, _ = checkpoint(cache, "bad", gated=False)
    refused = run(cache, "bad", "--dry-run")
    assert refused.returncode == 2 and "gate" in refused.stderr and refused.stdout == ""
    (ckpt / "model.safetensors").write_bytes(b"tampered")
    assert run(cache, "ck-2026-10-04", "--dry-run").returncode == 2
    (ckpt / "model.safetensors").write_bytes(b"weights")
    (ckpt / "tokenizer").mkdir()
    (ckpt / "tokenizer" / "tokenizer_config.json").write_text('{"x":1}')  # swapped after the gate, never recorded
    unrecorded = run(cache, "ck-2026-10-04", "--dry-run")
    assert unrecorded.returncode == 2 and "not in l4-train.json" in unrecorded.stderr and unrecorded.stdout == ""
    record = json.loads((ckpt / "l4-train.json").read_text())
    record["files"]["tokenizer/tokenizer_config.json"] = hashlib.sha256(b'{"x":1}').hexdigest()
    (ckpt / "l4-train.json").write_text(json.dumps(record))
    recorded = run(cache, "ck-2026-10-04", "--dry-run")
    assert (
        recorded.returncode == 0
        and "model.safetensors rl_agent_config.json tokenizer/tokenizer_config.json" in recorded.stdout
    )
    record["files"]["tokenizer/tokenizer_config.json"] = "0" * 64
    (ckpt / "l4-train.json").write_text(json.dumps(record))
    assert "does not match" in run(cache, "ck-2026-10-04", "--dry-run").stderr
    for hostile in ("../x", "a;touch pwned", "a b", "$(id)", "a`id`", "a&b", ".hidden", "a|b", "a\nb"):
        refused = run(cache, hostile, "--dry-run")
        assert refused.returncode == 2 and refused.stdout == "", hostile
    assert ungated.is_dir()
