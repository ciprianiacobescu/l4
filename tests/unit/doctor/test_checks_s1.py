"""S1-001, S1-002 and COV-001 (M1.6 plan line 39): all warnings, each with the reason it gives."""

import httpx
import pytest

from l4.config.schema import L4Config, Profile
from l4.doctor import checks_s1 as c
from l4.doctor.context import CmdResult
from l4.doctor.registry import REGISTRY, load_check_modules

from ..llm.test_system_one_checkpoint import make_checkpoint


def config(**sections) -> L4Config:
    return L4Config.model_validate(sections)


def test_three_checks_are_registered_warnings():
    load_check_modules()
    found = {x.id: x for x in REGISTRY.checks() if x.id in ("S1-001", "S1-002", "COV-001")}
    assert set(found) == {"S1-001", "S1-002", "COV-001"}
    assert {x.severity for x in found.values()} == {"warn"}


def test_s1_001_every_shadow_profile_must_probe_usable(make_ctx, monkeypatch):
    shadow = {
        "up": Profile(backend="system-one", engine="remote", base_url="http://up.test"),
        "down": Profile(backend="system-one", engine="remote", base_url="http://down.test"),
        "jev": Profile(backend="system-one", engine="jev", api_key_env="JEV_KEY"),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "down.test":
            raise httpx.ConnectError("refused")
        return httpx.Response(200)

    monkeypatch.setattr(c, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    ctx, _ = make_ctx(cfg=config(profiles=shadow, verifier={"s1": {"shadow": ["up"]}}))
    assert c._s1_001(ctx).status == "pass" and "up" in c._s1_001(ctx).message
    ctx, _ = make_ctx(cfg=config(profiles=shadow, verifier={"s1": {"shadow": ["up", "down", "jev"]}}))
    result = c._s1_001(ctx)
    assert result.status == "fail" and "down:" in result.message and "jev:" in result.message
    assert "JEV_KEY" in result.message and "up:" not in result.message
    ctx, _ = make_ctx(cfg=config(profiles=shadow))
    assert c._s1_001(ctx).status == "skip"  # nothing is shadowed
    ctx, _ = make_ctx(cfg=config(profiles=shadow, verifier={"s1": {"enabled": False, "shadow": ["down"]}}))
    assert c._s1_001(ctx).status == "skip"


def test_s1_002_a_configured_checkpoint_must_be_gated_and_intact(make_ctx, tmp_path):
    cache = tmp_path / "cache"
    good = make_checkpoint(cache, "good")
    failed = make_checkpoint(cache, "failed", gated=False)
    profiles = {
        n: Profile(backend="system-one", engine="laya-local", model=str(p))
        for n, p in (("good", good), ("failed", failed))
    }
    env = {"L4_CACHE": str(cache)}
    ctx, _ = make_ctx(cfg=config(profiles=profiles, roles={"s1_judge": ["good"]}), **env)
    assert c._s1_002(ctx).status == "pass" and "good" in c._s1_002(ctx).message
    ctx, _ = make_ctx(cfg=config(profiles=profiles, verifier={"s1": {"shadow": ["good", "failed"]}}), **env)
    result = c._s1_002(ctx)
    assert result.status == "fail" and "failed:" in result.message
    assert "not passed the laya-evals gate" in result.message and "good:" not in result.message
    (good / "model.safetensors").write_bytes(b"swapped")  # a file changed after the gate
    ctx, _ = make_ctx(cfg=config(profiles=profiles, roles={"s1_judge": ["good"]}), **env)
    assert "good:" in c._s1_002(ctx).message and "sha256" in c._s1_002(ctx).message
    ctx, _ = make_ctx(cfg=config(profiles={"laya": Profile(backend="system-one", engine="laya-local")}), **env)
    assert c._s1_002(ctx).status == "skip"  # no path form configured


def test_cov_001_coverage_must_import_in_the_project_environment(make_ctx):
    ctx, fake = make_ctx(cfg=config(verifier={"evidence": {"diff_coverage": {"mode": "off"}}}))
    assert c._cov_001(ctx).status == "skip"
    ctx, fake = make_ctx(cfg=config(gates={"test": {"command": ".venv/bin/python -m pytest -q"}}))
    py = ctx.repo / ".venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text("")
    calls: list[tuple[str, ...]] = []

    def run(argv, timeout=10.0, env=None):
        calls.append(tuple(argv))
        return CmdResult(0, "", "")

    ctx = type(ctx)(ctx.repo, ctx.cfg, ctx.env, ctx.which, run, ctx.python_version)
    assert c._cov_001(ctx).status == "pass" and calls == [(str(py), "-c", "import coverage")]
    ctx = type(ctx)(ctx.repo, ctx.cfg, ctx.env, ctx.which, lambda *a, **k: CmdResult(1, "", "No module"), (3, 12, 1))
    result = c._cov_001(ctx)
    assert result.status == "fail" and "coverage" in result.message and result.fix_hint
    py.unlink()
    bare, _ = make_ctx()
    assert c._cov_001(bare).status == "skip" and "interpreter" in c._cov_001(bare).message


def test_cov_001_in_ci_says_gates_setup_has_not_run_yet_and_where_the_check_happens(make_ctx):
    """Live M1.6: the CI doctor runs before the job's `gates.setup` creates `.venv`, so the check cannot look yet. The
    skip says why and that the run checks again right after setup (the `doctor.check` event)."""
    gates = {"setup": ["uv sync --frozen"], "test": {"command": ".venv/bin/python -m pytest"}}
    ctx, _ = make_ctx(cfg=config(gates=gates))
    result = c._cov_001(ctx)
    assert result.status == "skip" and "gates.setup" in result.message and "after" in result.message
    bare, _ = make_ctx()  # no setup configured: nothing will create an interpreter
    assert "gates.setup" not in c._cov_001(bare).message and "interpreter" in c._cov_001(bare).message


def ollama_world(version="0.40.0", tags=("tev1:latest",), down=False):
    def handler(request: httpx.Request) -> httpx.Response:
        if down:
            raise httpx.ConnectError("no route")
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": version})
        return httpx.Response(200, json={"models": [{"name": n} for n in tags]})

    return lambda: httpx.Client(transport=httpx.MockTransport(handler))


MAC = {"backend": "system-one", "engine": "ollama", "model": "tev1", "base_url": "http://mac.test:11434"}


def test_env_013_is_a_registered_warning():
    load_check_modules()
    found = {x.id: x for x in REGISTRY.checks()}
    assert found["ENV-013"].severity == "warn"


def test_env_013_skips_without_an_ollama_profile(make_ctx):
    ctx, _ = make_ctx(
        cfg=config(
            profiles={"r": {"backend": "system-one", "engine": "remote", "base_url": "http://x"}},
            roles={"s1_judge": ["r"]},
        )
    )
    assert c._env_013(ctx).status == "skip"


def test_env_013_passes_for_a_reachable_host_with_the_model(make_ctx, monkeypatch):
    monkeypatch.setattr(c, "_client", ollama_world())
    ctx, _ = make_ctx(cfg=config(profiles={"mac": MAC}, roles={"s1_judge": ["mac"]}))
    result = c._env_013(ctx)
    assert result.status == "pass" and "mac" in result.message and "tev1" in result.message


def test_env_013_covers_shadow_profiles_and_names_the_remedy(make_ctx, monkeypatch):
    monkeypatch.setattr(c, "_client", ollama_world(tags=("gpt-oss:20b",)))
    ctx, _ = make_ctx(cfg=config(profiles={"mac": MAC}, verifier={"s1": {"shadow": ["mac"]}}))
    result = c._env_013(ctx)
    assert result.status == "fail" and "mac:" in result.message and "ollama pull tev1" in result.message


def test_env_013_a_down_mac_is_a_warning_with_the_fallback_noted(make_ctx, monkeypatch):
    monkeypatch.setattr(c, "_client", ollama_world(down=True))
    ctx, _ = make_ctx(cfg=config(profiles={"mac": MAC}, roles={"s1_judge": ["mac"]}))
    result = c._env_013(ctx)
    assert result.status == "fail" and "unreachable" in result.message and "next S1 profile" in result.message


def test_env_013_skips_when_s1_is_off(make_ctx):
    off = config(profiles={"mac": MAC}, roles={"s1_judge": ["mac"]}, verifier={"s1": {"enabled": False}})
    ctx, _ = make_ctx(cfg=off)
    assert c._env_013(ctx).status == "skip"


@pytest.mark.parametrize("command", ["npm test", "npx vitest run", "dotnet test"])
def test_cov_001_skips_a_project_whose_test_gate_is_not_python(make_ctx, command):
    """SCN-VER-59: `gates.setup` will never create an interpreter for it, so the skip must not promise one."""
    ctx, _ = make_ctx(cfg=config(gates={"setup": ["npm ci"], "test": {"command": command}}))
    result = c._cov_001(ctx)
    assert result.status == "skip" and result.message == "no python test gate: diff coverage does not apply"


@pytest.mark.parametrize("command", ["uv run pytest -q", "python -m pytest", "tox -e py"])
def test_cov_001_keeps_its_message_for_python_gates(make_ctx, command):
    ctx, _ = make_ctx(cfg=config(gates={"setup": ["uv sync"], "test": {"command": command}}))
    assert "gates.setup creates it" in c._cov_001(ctx).message


def test_cov_001_checks_a_project_interpreter_whatever_runs_the_tests(make_ctx):
    """`make test` names no Python, but a `.venv` in the repository is still checked for coverage.py."""
    ctx, fake = make_ctx(cfg=config(gates={"test": {"command": "make test"}}))
    py = ctx.repo / ".venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text("")
    fake.tools["python"] = ""
    result = c._cov_001(ctx)
    assert result.status == "pass" and fake.calls[-1] == (str(py), "-c", "import coverage")


# --- S1-003: the engine that would serve step 8, and whether it starts (adoption-lessons 6.3, L4-ADO-015) -------------

import dataclasses  # noqa: E402
import stat  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

from ..llm.test_system_one import FAKE_SERVE  # noqa: E402

LAYA = {"laya": {"backend": "system-one", "engine": "laya-local"}}
JEV = {"jev": {"backend": "system-one", "engine": "jev", "api_key_env": "TYPESAFE_API_KEY"}}


def laya_world(tmp_path: Path, mode: str = "serve") -> tuple[dict[str, str], Path]:
    """A fake `laya-serve` on PATH (a Python script that answers /health) and the checkpoint in the HF cache."""
    bin_dir, home, state = tmp_path / "laya-bin", tmp_path / "laya-home", tmp_path / "laya-state"
    for folder in (bin_dir, state):
        folder.mkdir(exist_ok=True)
    exe = bin_dir / "laya-serve"
    exe.write_text(FAKE_SERVE.format(python=sys.executable, state=str(state), mode=mode))
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    snap = home / ".cache/huggingface/hub/models--convaiinnovations--laya/snapshots/abc123/typed-decisions"
    snap.mkdir(parents=True, exist_ok=True)
    (snap / "model.safetensors").write_bytes(b"x")
    return {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(home)}, state


def test_s1_003_is_a_registered_warning_in_the_repository_scopes():
    load_check_modules()
    found = next(x for x in REGISTRY.checks() if x.id == "S1-003")
    assert found.severity == "warn" and {"ci", "local", "config"} <= found.scopes


def test_s1_003_skips_without_a_judge_profile_or_with_s1_off(make_ctx):
    ctx, _ = make_ctx(cfg=config(profiles=LAYA))
    assert c._s1_003(ctx).status == "skip"
    ctx, _ = make_ctx(cfg=config(profiles=LAYA, roles={"s1_judge": ["laya"]}, verifier={"s1": {"enabled": False}}))
    assert c._s1_003(ctx).status == "skip"


def test_s1_003_laya_not_installed_names_the_consequence_and_the_fix(make_ctx, tmp_path):
    ctx, _ = make_ctx(cfg=config(profiles=LAYA, roles={"s1_judge": ["laya"]}), PATH=str(tmp_path / "empty"))
    result = c._s1_003(ctx)
    assert result.status == "fail" and "laya: laya-serve is not on PATH" in result.message
    assert (
        "auto-accepts no answer" in result.message and "every implementer question goes to a person" in result.message
    )
    assert "engine: laya-local" in (result.fix_hint or "") and "TYPESAFE_API_KEY" in (result.fix_hint or "")
    assert "l4 doctor --ci --fix" in (result.fix_hint or "")


def test_s1_003_a_lan_engine_is_unreachable_from_a_hosted_runner(make_ctx):
    mac = {"backend": "system-one", "engine": "ollama", "model": "tev1", "base_url": "http://mac.test:11434"}
    ctx, _ = make_ctx(cfg=config(profiles={"ollama-tev1": mac}, roles={"s1_judge": ["ollama-tev1"]}),
                      RUNNER_ENVIRONMENT="github-hosted")  # fmt: skip
    result = c._s1_003(ctx)
    assert result.status == "fail" and "on the local network" in result.message
    assert "unreachable from a GitHub-hosted runner" in result.message


def test_s1_003_adoption_starts_laya_once_stops_it_and_reports_the_seconds(make_ctx, tmp_path):
    env, state = laya_world(tmp_path)
    ctx, _ = make_ctx(cfg=config(profiles=LAYA, roles={"s1_judge": ["laya"]}), **env)
    result = c._s1_003(dataclasses.replace(ctx, adoption=True))
    assert result.status == "pass", result.message
    assert "laya-local" in result.message and "typed-decisions" in result.message and "ready in " in result.message
    pid = int((state / "pid").read_text())
    with pytest.raises(ProcessLookupError):
        for _ in range(100):  # the stop is synchronous; allow the OS a moment to reap
            import os
            import time

            os.kill(pid, 0)
            time.sleep(0.05)


def test_s1_003_ci_checks_the_install_and_starts_nothing(make_ctx, tmp_path):
    env, state = laya_world(tmp_path)
    ctx, _ = make_ctx(cfg=config(profiles=LAYA, roles={"s1_judge": ["laya"]}), **env)
    result = c._s1_003(ctx)  # adoption is off: `l4 doctor --ci`
    assert result.status == "pass" and "laya-local" in result.message and "installed" in result.message
    assert "ready in" not in result.message and not (state / "pid").exists()


def test_s1_003_a_server_that_cannot_start_is_a_warning_with_its_reason(make_ctx, tmp_path):
    env, _ = laya_world(tmp_path, mode="crash")
    ctx, _ = make_ctx(cfg=config(profiles=LAYA, roles={"s1_judge": ["laya"]}), **env)
    result = c._s1_003(dataclasses.replace(ctx, adoption=True))
    assert result.status == "fail" and "exited with code 3" in result.message


def test_s1_003_the_first_profile_that_would_open_serves(make_ctx, tmp_path):
    env, _ = laya_world(tmp_path)
    ctx, _ = make_ctx(cfg=config(profiles={**JEV, **LAYA}, roles={"s1_judge": ["jev", "laya"]}), **env)
    result = c._s1_003(ctx)
    assert (
        result.status == "pass"
        and "laya-local" in result.message
        and "jev: the variable TYPESAFE_API_KEY is not set" in result.message
    )
    ctx, _ = make_ctx(cfg=config(profiles={**JEV, **LAYA}, roles={"s1_judge": ["jev", "laya"]}),
                      TYPESAFE_API_KEY="k", **env)  # fmt: skip
    assert "jev" in c._s1_003(ctx).message


def test_adoption_flag_reaches_the_context_of_doctor_adoption(make_ctx):
    from l4.doctor.context import system_context

    ctx = system_context(Path("."), L4Config(), {"PATH": "/usr/bin"})
    assert ctx.adoption is False
