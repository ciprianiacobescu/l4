"""adoption-lessons 7.3 (L4-ADO-019, design D9): Laya in provisioning. Nothing is downloaded: the runner and the fetcher
are fakes, and a fake `laya-serve` is a script whose interpreter prints the version."""

import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from l4.config.schema import L4Config
from l4.doctor.context import CmdResult
from l4.provision.catalog import LAYA_CHECKPOINT, LAYA_VERSION, required_tools
from l4.provision.install import install_planned
from l4.provision.runner import Paths, plan_fixes

from ._install_helpers import FakeFetcher

PREREQS = Path(__file__).resolve().parents[3] / "scripts" / "runner" / "prereqs.sh"
LAYA = {"backend": "system-one", "engine": "laya-local"}
JEV = {"backend": "system-one", "engine": "jev", "base_url": "https://api.typesafe.ai", "api_key_env": "K"}
SECRETS = {"L4_FORGE_TOKEN": "glpat-fake", "OPENAI_API_KEY": "sk-fake"}


def cfg(roles: dict | None = None, shadow: list[str] | None = None, **profiles) -> L4Config:
    document: dict = {"profiles": profiles, "roles": roles or {}}
    if shadow is not None:
        document["verifier"] = {"s1": {"shadow": shadow}}
    return L4Config.model_validate(document)


def names(config: L4Config) -> list[str]:
    return [t.name for t in required_tools(config, openspec_active=False)]


def test_the_pin_and_the_checkpoint_live_in_the_catalog_and_prereqs_sh_agrees():
    text = PREREQS.read_text()
    assert re.search(rf"^LAYA_VERSION=\$\{{LAYA_VERSION:-{re.escape(LAYA_VERSION)}\}}", text, re.M)
    assert re.search(rf"^LAYA_CHECKPOINT=\$\{{LAYA_CHECKPOINT:-{re.escape(LAYA_CHECKPOINT)}\}}", text, re.M)
    assert (LAYA_VERSION, LAYA_CHECKPOINT) == ("0.3.24", "typed-decisions")


def test_the_laya_spec_only_with_a_laya_local_profile_in_a_system_one_list():
    """SCN-ADO-53: none without a profile, with another engine, or with the profile in no System One list."""
    assert "laya" not in names(cfg())
    assert "laya" not in names(cfg({"s1_judge": ["jev"]}, jev=JEV))
    assert "laya" not in names(cfg({}, laya=LAYA))  # defined, used nowhere
    assert "laya" in names(cfg({"s1_judge": ["laya"]}, laya=LAYA))
    assert "laya" in names(cfg({}, shadow=["laya"], laya=LAYA))
    [spec] = [
        t for t in required_tools(cfg({"s1_judge": ["laya"]}, laya=LAYA), openspec_active=False) if t.name == "laya"
    ]
    assert (spec.binary, spec.version) == ("laya-serve", LAYA_VERSION)


class LayaRunner:
    """Plays `uv tool install` (it writes a fake `laya-serve` whose interpreter prints the version) and the checkpoint
    fetch (it writes the checkpoint file under the HF_HOME it was given); answers `uv --version`."""

    def __init__(self, paths: Paths, installs: str = LAYA_VERSION) -> None:
        self.paths, self.installs = paths, installs
        self.calls: list[tuple[str, ...]] = []
        self.envs: list[Mapping[str, str]] = []

    def __call__(self, argv: Sequence[str], cwd: Path, env: Mapping[str, str], timeout: float) -> CmdResult:
        self.calls.append(tuple(argv))
        self.envs.append(dict(env))
        if Path(argv[0]).name == "uv" and argv[1:3] == ["tool", "install"]:
            tool_bin = Path(env["UV_TOOL_BIN_DIR"])
            fake_laya(tool_bin, self.installs, name="laya-serve", python=Path(env["UV_TOOL_DIR"]) / "laya/bin/python")
            return CmdResult(0, "", "")
        if "-c" in argv and "snapshot_download" in argv[-1]:
            put_checkpoint(Path(env["HF_HOME"]))
            return CmdResult(0, "", "")
        if argv[-1] == "--version":
            return CmdResult(0, "uv 0.12.22\n", "")
        return CmdResult(127, "", "")


def fake_laya(directory: Path, version: str, *, name: str = "laya-serve", python: Path | None = None) -> Path:
    """A `laya-serve` console script that names an interpreter, which prints `version` for any `-c`."""
    interpreter = python or directory.parent / f"python-{version}"
    interpreter.parent.mkdir(parents=True, exist_ok=True)
    interpreter.write_text(f"#!/bin/sh\necho {version}\n")
    interpreter.chmod(0o755)
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / name
    script.write_text(f"#!{interpreter}\n")
    script.chmod(0o755)
    return script


def put_checkpoint(hf_home: Path) -> Path:
    target = hf_home / "hub/models--convaiinnovations--laya/snapshots/abc" / LAYA_CHECKPOINT / "model.safetensors"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"w")
    return target


def config() -> L4Config:
    return cfg({"s1_judge": ["laya"]}, laya=LAYA)


def run_install(paths, env, runner, fetcher=None):
    return {
        a.tool: a
        for a in install_planned(
            config(), paths, {**env, **SECRETS}, "linux-x64", openspec_active=False,
            fetcher=fetcher or FakeFetcher(), run=runner,
        )
    }  # fmt: skip


def test_the_installer_argv_the_directories_and_the_checkpoint_home(paths, env, install_fake):
    install_fake("uv")
    runner = LayaRunner(paths)
    fetcher = FakeFetcher()
    actions = run_install(paths, env, runner, fetcher)
    assert actions["laya"].status == "applied" and actions["laya"].message == f"laya {LAYA_VERSION}"
    [(argv, clean)] = [(c, e) for c, e in zip(runner.calls, runner.envs, strict=True) if c[1:3] == ("tool", "install")]
    assert argv[3:] == ("--torch-backend", "cpu", f"laya[serve]=={LAYA_VERSION}")
    assert clean["UV_TOOL_DIR"] == str(paths.l4_home / "laya") and clean["UV_TOOL_BIN_DIR"] == str(
        paths.l4_home / "laya/bin"
    )
    assert "uv/tools" not in clean["UV_TOOL_DIR"]  # not the harness's own uv tool directory
    assert not set(SECRETS) & set(clean)
    [fetch_env] = [e for c, e in zip(runner.calls, runner.envs, strict=True) if "snapshot_download" in c[-1]]
    assert fetch_env["HF_HOME"] == str(paths.l4_cache / "laya/hf")
    assert (paths.local_bin / "laya-serve").resolve() == (paths.l4_home / "laya/bin/laya-serve").resolve()
    assert fetcher.calls == []


def test_a_present_install_in_the_default_hf_cache_is_kept_as_it_is(paths, env, install_fake):
    """SCN-ADO-54: laya-serve on PATH at the pin and the checkpoint in the default Hugging Face cache."""
    install_fake("uv")
    fake_laya(paths.local_bin, LAYA_VERSION)
    put_checkpoint(paths.home / ".cache/huggingface")
    runner = LayaRunner(paths)
    actions = run_install(paths, env, runner)
    assert actions["laya"].status == "already present"
    assert not any(c[1:3] == ("tool", "install") or "snapshot_download" in c[-1] for c in runner.calls)
    assert not (paths.l4_home / "laya").exists() and not (paths.l4_cache / "laya").exists()


def test_a_present_install_with_the_checkpoint_in_the_l4_cache_is_kept_too(paths, env, install_fake):
    install_fake("uv")
    fake_laya(paths.local_bin, LAYA_VERSION)
    put_checkpoint(paths.l4_cache / "laya/hf")
    runner = LayaRunner(paths)
    assert run_install(paths, env, runner)["laya"].status == "already present"
    assert not any(c[1:3] == ("tool", "install") for c in runner.calls)


def test_only_the_checkpoint_is_fetched_when_laya_is_present_without_it(paths, env, install_fake):
    install_fake("uv")
    fake_laya(paths.local_bin, LAYA_VERSION)
    runner = LayaRunner(paths)
    actions = run_install(paths, env, runner)
    assert actions["laya"].status == "applied"
    assert not any(c[1:3] == ("tool", "install") for c in runner.calls)
    assert any("snapshot_download" in c[-1] for c in runner.calls)


def test_another_version_is_replaced_and_the_checkpoint_kept(paths, env, install_fake):
    install_fake("uv")
    fake_laya(paths.local_bin, "0.3.20")
    put_checkpoint(paths.home / ".cache/huggingface")
    runner = LayaRunner(paths)
    actions = run_install(paths, env, runner)
    assert actions["laya"].status == "applied"
    assert any(c[1:3] == ("tool", "install") for c in runner.calls)
    assert not any("snapshot_download" in c[-1] for c in runner.calls)


def test_a_failed_install_is_failed_with_the_manual_command(paths, env, install_fake):
    install_fake("uv")

    def broken(argv, cwd, env_, timeout):
        return CmdResult(0, "uv 0.12.22\n", "") if argv[-1] == "--version" else CmdResult(1, "", "boom")

    actions = run_install(paths, env, broken)
    assert actions["laya"].status == "failed" and "run manually: " in actions["laya"].message


def test_plan_fixes_plans_nothing_without_a_profile_and_keeps_a_complete_install(paths, env, install_fake):
    install_fake("uv")
    runner = LayaRunner(paths)
    plan = plan_fixes(cfg(), paths, env, "linux-x64", openspec_active=False, run=runner)
    assert "laya" not in [a.tool for a in plan]
    fake_laya(paths.local_bin, LAYA_VERSION)
    put_checkpoint(paths.l4_cache / "laya/hf")
    plan = plan_fixes(config(), paths, env, "linux-x64", openspec_active=False, run=runner)
    assert {a.tool: a.status for a in plan}["laya"] == "already present"


def test_the_backend_finds_the_checkpoint_the_provisioner_fetched(tmp_path):
    """Design D9 step 4: with no HF_HOME and the checkpoint only in the l4 cache, the server is pointed at it."""
    from l4.llm.system_one import laya_hf_environ

    environ = {"HOME": str(tmp_path / "h"), "L4_CACHE": str(tmp_path / "c")}
    assert laya_hf_environ(environ, LAYA_CHECKPOINT) == environ
    put_checkpoint(tmp_path / "c/laya/hf")
    assert laya_hf_environ(environ, LAYA_CHECKPOINT)["HF_HOME"] == str(tmp_path / "c/laya/hf")
    put_checkpoint(tmp_path / "h/.cache/huggingface")  # the default cache wins when it has the checkpoint
    assert "HF_HOME" not in laya_hf_environ(environ, LAYA_CHECKPOINT)
    explicit = {**environ, "HF_HOME": str(tmp_path / "x")}
    assert laya_hf_environ(explicit, LAYA_CHECKPOINT) == explicit
