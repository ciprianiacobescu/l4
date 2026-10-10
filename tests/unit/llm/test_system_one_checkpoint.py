"""A tuned Laya checkpoint as a System-One profile (M16-G20, plan D10): only a gated, intact directory under
`$L4_CACHE/s1/checkpoints/` is served, through a private Hugging Face home whose `typed-decisions` is that directory
(probe T1: `laya-serve` takes registry names only, so the path itself cannot be served)."""

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

from l4.agents.factory import RoleUnavailable
from l4.config.schema import L4Config
from l4.exitcodes import ExitCode
from l4.llm.s1_checkpoint import (
    GATE_NOT_PASSED,
    CheckpointGateFailed,
    checkpoint_identity,
    checkpoint_problem,
)
from l4.llm.system_one import open_s1_profile
from l4.redact import Redactor


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_gate_document(ckpt: Path, *, passed: bool, flag: bool | None = None) -> None:
    """The gate document laya_tune.py `record_gate` writes, and the record bound to it by sha256. `flag` is the
    boolean in l4-train.json when it should differ from the document's."""
    record = json.loads((ckpt / "l4-train.json").read_text())
    document = {"schema": "l4/s1-gate@1", "passed": passed, "checkpoint_sha256": record["files"]["model.safetensors"]}
    (ckpt / "gate.json").write_text(json.dumps(document))
    record["gate"] = {
        "ran": True,
        "passed": passed if flag is None else flag,
        "document_sha256": sha(ckpt / "gate.json"),
    }
    (ckpt / "l4-train.json").write_text(json.dumps(record))


def make_checkpoint(cache: Path, name: str = "ck1", *, gated: bool = True) -> Path:
    ckpt = cache / "s1" / "checkpoints" / name
    ckpt.mkdir(parents=True)
    (ckpt / "model.safetensors").write_bytes(b"weights")
    (ckpt / "rl_agent_config.json").write_text('{"temperature": [1, 1, 1]}')
    (ckpt / "tokenizer").mkdir()
    (ckpt / "tokenizer" / "tokenizer_config.json").write_text("{}")
    record = {
        "files": {
            n: sha(ckpt / n) for n in ("model.safetensors", "rl_agent_config.json", "tokenizer/tokenizer_config.json")
        },
        "gate": {"ran": True, "passed": gated},
    }
    (ckpt / "l4-train.json").write_text(json.dumps(record))
    write_gate_document(ckpt, passed=gated)
    return ckpt


def env_for(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    exe = bin_dir / "laya-serve"
    exe.write_text("#!/bin/sh\nexit 0\n")
    exe.chmod(0o755)
    return {"PATH": str(bin_dir), "HOME": str(tmp_path / "home"), "L4_CACHE": str(tmp_path / "cache")}


def cfg_for(model: str) -> L4Config:
    return L4Config.model_validate(
        {"profiles": {"tuned": {"backend": "system-one", "engine": "laya-local", "model": model}}}
    )


def open_profile(tmp_path: Path, model: str):
    return open_s1_profile(cfg_for(model), "tuned", environ=env_for(tmp_path), redactor=Redactor({}))


def test_ungated_or_tampered_checkpoint_is_unusable(tmp_path: Path):
    cache = tmp_path / "cache"
    ok = make_checkpoint(cache, "ok")
    assert open_profile(tmp_path, str(ok)) is not None

    ungated = make_checkpoint(cache, "ungated", gated=False)
    with pytest.raises(RoleUnavailable, match="gate"):
        open_profile(tmp_path, str(ungated))
    never = make_checkpoint(cache, "never")
    record = json.loads((never / "l4-train.json").read_text())
    record["gate"] = {"ran": False, "passed": False}
    (never / "l4-train.json").write_text(json.dumps(record))
    with pytest.raises(RoleUnavailable, match="not been through"):
        open_s1_profile(
            cfg_for(str(never)), "tuned", environ=env_for(tmp_path), redactor=Redactor({}), allow_failed_gate=True
        )  # a gate that never ran is refused even for scoring

    tampered = make_checkpoint(cache, "tampered")
    (tampered / "model.safetensors").write_bytes(b"other weights")
    with pytest.raises(RoleUnavailable, match="sha256"):
        open_profile(tmp_path, str(tampered))

    pickled = make_checkpoint(cache, "pickled")
    (pickled / "extra.bin").write_bytes(b"pickle")
    with pytest.raises(RoleUnavailable, match="safetensors"):
        open_profile(tmp_path, str(pickled))

    swapped = make_checkpoint(cache, "swapped")
    (swapped / "tokenizer" / "tokenizer_config.json").write_text('{"x": 1}')  # not the weights, still the model
    with pytest.raises(RoleUnavailable, match="tokenizer_config.json does not match"):
        open_profile(tmp_path, str(swapped))

    added = make_checkpoint(cache, "added")
    (added / "thresholds.json").write_text("{}")
    with pytest.raises(RoleUnavailable, match="thresholds.json is in the checkpoint but not"):
        open_profile(tmp_path, str(added))

    linked = make_checkpoint(cache, "linked")
    (linked / "alias.json").symlink_to(linked / "rl_agent_config.json")
    with pytest.raises(RoleUnavailable, match="symlink"):
        open_profile(tmp_path, str(linked))

    missing = make_checkpoint(cache, "missing")
    (missing / "l4-train.json").unlink()
    with pytest.raises(RoleUnavailable, match="l4-train.json"):
        open_profile(tmp_path, str(missing))

    outside = tmp_path / "elsewhere" / "ck"
    outside.parent.mkdir()
    outside.mkdir()
    with pytest.raises(RoleUnavailable, match="checkpoints"):
        open_profile(tmp_path, str(outside))
    link = cache / "s1" / "checkpoints" / "link"
    link.symlink_to(outside)
    with pytest.raises(RoleUnavailable, match="checkpoints"):
        open_profile(tmp_path, str(link))
    with pytest.raises(RoleUnavailable, match="checkpoints"):
        open_profile(tmp_path, str(cache / "s1" / "checkpoints" / ".." / ".." / "x"))


def test_overlay_layout_when_t1_says_overlay(tmp_path: Path):
    cache = tmp_path / "cache"
    ckpt = make_checkpoint(cache)
    backend = open_profile(tmp_path, str(ckpt))
    serve_env = backend._serve._environ  # the environment `laya_env` builds `laya-serve`'s from
    home = Path(serve_env["HF_HOME"])
    assert home.parent == cache / "s1" / "overlays" and home != Path(env_for(tmp_path)["HOME"])
    (snapshot,) = (home / "hub" / "models--convaiinnovations--laya" / "snapshots").iterdir()
    assert (snapshot / "typed-decisions").resolve() == ckpt.resolve()
    assert (home / "hub" / "models--convaiinnovations--laya" / "refs" / "main").read_text() == snapshot.name
    assert backend._serve._model == "typed-decisions"
    # reused while it is intact, and never touching the user's own Hugging Face cache
    marker = home / "marker"
    marker.write_text("kept")
    again = open_profile(tmp_path, str(ckpt))
    assert again._serve._environ["HF_HOME"] == serve_env["HF_HOME"] and marker.read_text() == "kept"
    assert not os.path.exists(tmp_path / "home")
    assert [p.name for p in home.parent.iterdir()] == [home.name]  # no half-built directory is left behind


def test_overlay_is_keyed_by_the_weights_and_repaired_when_broken(tmp_path: Path):
    cache = tmp_path / "cache"
    ckpt = make_checkpoint(cache)
    home = Path(open_profile(tmp_path, str(ckpt))._serve._environ["HF_HOME"])
    assert sha(ckpt / "model.safetensors")[:16] in home.name
    link = next(home.rglob("typed-decisions"))
    link.unlink()
    link.symlink_to(tmp_path)  # points elsewhere now: it must be rebuilt, not trusted
    shutil.rmtree(home)
    again = Path(open_profile(tmp_path, str(ckpt))._serve._environ["HF_HOME"])
    assert next(again.rglob("typed-decisions")).resolve() == ckpt.resolve()


def test_unreadable_weights_are_a_reason_not_a_crash(tmp_path: Path):
    ckpt = make_checkpoint(tmp_path / "cache")
    (ckpt / "model.safetensors").chmod(0)
    try:
        if os.access(ckpt / "model.safetensors", os.R_OK):
            pytest.skip("running as a user that can read mode 000 files")
        with pytest.raises(RoleUnavailable, match="cannot be read"):
            open_profile(tmp_path, str(ckpt))
    finally:
        (ckpt / "model.safetensors").chmod(0o644)


def test_checkpoint_identity_names_the_weights(tmp_path: Path):
    ckpt = make_checkpoint(tmp_path / "cache", "ck-id")
    ident = checkpoint_identity(str(ckpt))
    assert ident["checkpoint_id"] == "ck-id" and ident["checkpoint_sha256"] == sha(ckpt / "model.safetensors")


def open_failed(tmp_path: Path, model: str):
    return open_s1_profile(
        cfg_for(model), "tuned", environ=env_for(tmp_path), redactor=Redactor({}), allow_failed_gate=True
    )


def test_a_failed_gate_is_scorable_but_nothing_else_may_load_it(tmp_path: Path):
    failed = make_checkpoint(tmp_path / "cache", "failed", gated=False)
    assert open_failed(tmp_path, str(failed)) is not None  # `l4 s1 score` only
    with pytest.raises(CheckpointGateFailed) as caught:  # shadow, role probes, a plain open
        open_profile(tmp_path, str(failed))
    assert caught.value.code is ExitCode.USAGE_ERROR and isinstance(caught.value, RoleUnavailable)  # exit 2, not 12
    env = {"L4_CACHE": str(tmp_path / "cache")}
    assert checkpoint_problem(str(failed), env) == GATE_NOT_PASSED
    assert checkpoint_problem(str(failed), env, require_passed=False) == ""
    assert checkpoint_identity(str(failed))["gate_passed"] is False
    assert checkpoint_identity(str(make_checkpoint(tmp_path / "cache", "good")))["gate_passed"] is True


def test_the_gate_flag_is_bound_to_the_gate_document(tmp_path: Path):
    cache = tmp_path / "cache"
    env = {"L4_CACHE": str(cache)}
    flipped = make_checkpoint(cache, "flipped", gated=False)
    write_gate_document(flipped, passed=False, flag=True)  # the record says passed, the document says failed
    assert "differs from gate.json" in checkpoint_problem(str(flipped), env)
    assert "differs from gate.json" in checkpoint_problem(str(flipped), env, require_passed=False)
    with pytest.raises(RoleUnavailable, match="differs from gate.json"):
        open_profile(tmp_path, str(flipped))
    edited = make_checkpoint(cache, "edited", gated=False)
    document = json.loads((edited / "gate.json").read_text())
    (edited / "gate.json").write_text(json.dumps({**document, "passed": True}))  # the document edited instead
    assert "gate.json does not match the sha256" in checkpoint_problem(str(edited), env, require_passed=False)
    swapped = make_checkpoint(cache, "swapped-gate")  # a gate document of another checkpoint, sha256 re-recorded
    document = json.loads((swapped / "gate.json").read_text()) | {"checkpoint_sha256": "f" * 64}
    (swapped / "gate.json").write_text(json.dumps(document))
    record = json.loads((swapped / "l4-train.json").read_text())
    record["gate"]["document_sha256"] = sha(swapped / "gate.json")
    (swapped / "l4-train.json").write_text(json.dumps(record))
    assert "gated another checkpoint" in checkpoint_problem(str(swapped), env)
    legacy = make_checkpoint(cache, "legacy")
    record = json.loads((legacy / "l4-train.json").read_text())
    del record["gate"]["document_sha256"]
    (legacy / "l4-train.json").write_text(json.dumps(record))
    assert "gate the checkpoint again" in checkpoint_problem(str(legacy), env)


def role_cfg(*models: str) -> L4Config:
    profiles = {f"p{i}": {"backend": "system-one", "engine": "laya-local", "model": m} for i, m in enumerate(models)}
    return L4Config.model_validate({"profiles": profiles, "roles": {"s1_judge": list(profiles)}})


def test_a_role_chain_skips_a_failed_gate_and_exits_2_when_nothing_else_is_usable(tmp_path: Path):
    from l4.llm.system_one import open_s1_backend

    cache = tmp_path / "cache"
    failed, good = make_checkpoint(cache, "failed", gated=False), make_checkpoint(cache, "good")
    kwargs = {"environ": env_for(tmp_path), "redactor": Redactor({})}
    assert open_s1_backend(role_cfg(str(failed), str(good)), **kwargs) is not None  # the next profile serves
    with pytest.raises(CheckpointGateFailed) as caught:
        open_s1_backend(role_cfg(str(failed)), **kwargs)
    assert caught.value.code is ExitCode.USAGE_ERROR


def test_shadow_treats_a_failed_gate_as_that_engines_reason_and_never_raises(tmp_path: Path):
    from l4.s1 import questions as q
    from l4.s1.shadow import run_shadow

    from ..s1._make import make_item

    failed = make_checkpoint(tmp_path / "cache", "failed", gated=False)
    cfg = L4Config.model_validate({
        "profiles": {"tuned": {"backend": "system-one", "engine": "laya-local", "model": str(failed)}},
        "verifier": {"s1": {"shadow": ["tuned"]}},
    })  # fmt: skip
    item = make_item("c1", set_name=q.CRITERION, truth={"satisfied": True})
    run = run_shadow(cfg, [item], redactor=Redactor({}), environ=env_for(tmp_path))
    assert run.engines[0].status == "unavailable" and "laya-evals gate" in run.engines[0].reason
    assert run.items == [item]
