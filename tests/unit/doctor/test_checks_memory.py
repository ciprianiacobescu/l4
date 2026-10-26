from pathlib import Path

from l4.config.defaults import LAYA_VERSION, PLAYWRIGHT_VERSION
from l4.config.schema import L4Config, Profile
from l4.doctor import checks_memory as cm
from l4.llm.system_one import LAYA_REPO
from l4.memory.lessons import Lesson, LessonsFile, lesson_id, render_lessons

LESSONS = ".serena/memories/harness/lessons.md"


def config(**sections) -> L4Config:
    return L4Config.model_validate(sections)


def put_lessons(repo: Path, text: str) -> None:
    path = repo / LESSONS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_all_four_checks_are_registered_warnings():
    from l4.doctor.registry import REGISTRY, load_check_modules

    load_check_modules()
    found = {c.id: c for c in REGISTRY.checks() if c.id in ("MEM-001", "ENV-006", "ENV-007", "ENV-008")}
    assert set(found) == {"MEM-001", "ENV-006", "ENV-007", "ENV-008"}
    assert {c.severity for c in found.values()} == {"warn"}


def test_mem_001_reports_lint_problems(make_ctx):
    ctx, _ = make_ctx()
    assert cm._mem_001(ctx).status == "pass" and "no " in cm._mem_001(ctx).message  # no file: nothing to lint
    good = Lesson(lesson_id("k"), "T", "k")
    put_lessons(ctx.repo, render_lessons(LessonsFile([good])))
    assert cm._mem_001(ctx).status == "pass" and "1 lessons" in cm._mem_001(ctx).message
    bad = Lesson("L-deadbeef", "T", "other-key")  # id is not the hash of the key
    put_lessons(ctx.repo, render_lessons(LessonsFile([good, bad])))
    result = cm._mem_001(ctx)
    assert result.status == "fail" and "L-deadbeef" in result.message and result.fix_hint == "l4 lessons lint"
    put_lessons(ctx.repo, "<!-- l4:lessons v9 -->\n")
    assert cm._mem_001(ctx).status == "fail"


def test_mem_001_skips_when_memory_is_off(make_ctx):
    ctx, _ = make_ctx(cfg=config(memory={"enabled": False}))
    assert cm._mem_001(ctx).status == "skip"


def laya_cfg(engine: str = "laya-local") -> L4Config:
    return config(
        profiles={"laya": Profile(backend="system-one", engine=engine, model="typed-decisions")},
        roles={"s1_judge": ["laya"]},
    )


def cache_checkpoint(home: Path) -> None:
    snap = home / ".cache" / "huggingface" / "hub" / f"models--{LAYA_REPO.replace('/', '--')}" / "snapshots" / "abc"
    (snap / "typed-decisions").mkdir(parents=True)
    (snap / "typed-decisions" / "model.safetensors").write_bytes(b"x")


def test_env_006_laya(make_ctx, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(cm, "laya_version", lambda argv0, environ: LAYA_VERSION)
    ctx, _ = make_ctx({"laya-serve": ""}, cfg=laya_cfg())
    missing = cm._env_006(ctx)
    assert missing.status == "fail" and "checkpoint" in missing.message
    cache_checkpoint(tmp_path / "home")
    assert cm._env_006(ctx).status == "pass"
    no_binary, _ = make_ctx({"git": "x"}, cfg=laya_cfg())
    assert cm._env_006(no_binary).status == "fail" and "laya-serve" in cm._env_006(no_binary).message


def test_env_006_warns_when_the_installed_laya_is_not_the_pin(make_ctx, tmp_path: Path, monkeypatch):
    cache_checkpoint(tmp_path / "home")
    ctx, _ = make_ctx({"laya-serve": ""}, cfg=laya_cfg())
    monkeypatch.setattr(cm, "laya_version", lambda argv0, environ: "0.3.26")
    drift = cm._env_006(ctx)
    assert drift.status == "fail" and "0.3.26" in drift.message and LAYA_VERSION in drift.message
    monkeypatch.setattr(cm, "laya_version", lambda argv0, environ: "")
    assert cm._env_006(ctx).status == "fail" and "version" in cm._env_006(ctx).message
    monkeypatch.setattr(cm, "laya_version", lambda argv0, environ: LAYA_VERSION)
    assert cm._env_006(ctx).status == "pass" and LAYA_VERSION in cm._env_006(ctx).message


def test_env_006_skips_when_s1_is_off_or_not_laya(make_ctx):
    off, _ = make_ctx(cfg=config(verifier={"s1": {"enabled": False}}))
    assert cm._env_006(off).status == "skip"
    jev, _ = make_ctx(cfg=laya_cfg("jev"))
    assert cm._env_006(jev).status == "skip"
    default, _ = make_ctx()
    assert cm._env_006(default).status == "skip"


def test_env_007_playwright_browsers(make_ctx, tmp_path: Path):
    cfg = config(gates={"e2e": {"command": "npx playwright test"}})
    ctx, _ = make_ctx(cfg=cfg, L4_CACHE=str(tmp_path / "cache"))
    assert cm._env_007(ctx).status == "fail"
    (tmp_path / "cache" / "shared" / "ms-playwright" / "chromium-1234").mkdir(parents=True)
    assert cm._env_007(ctx).status == "pass"
    none, _ = make_ctx()
    assert cm._env_007(none).status == "skip"
    disabled, _ = make_ctx(cfg=config(gates={"e2e": {"command": "x"}}, verifier={"playwright": {"enabled": False}}))
    assert cm._env_007(disabled).status == "skip"


def test_env_007_checks_the_chromium_revision_this_playwright_wants(make_ctx, tmp_path: Path):
    cfg = config(gates={"e2e": {"command": "npx playwright test"}})
    browsers = tmp_path / "cache" / "shared" / "ms-playwright"
    dry_run = f"Install location: {browsers}/chromium-1200\nInstall location: {browsers}/chromium_headless_shell-1200\n"
    ctx, fake = make_ctx({"uvx": dry_run.rstrip("\n")}, cfg=cfg, L4_CACHE=str(tmp_path / "cache"))
    (browsers / "chromium-1100").mkdir(parents=True)  # a browser left by an older Playwright
    stale = cm._env_007(ctx)
    assert stale.status == "fail" and "chromium-1200" in stale.message
    assert any("playwright==" + PLAYWRIGHT_VERSION in " ".join(call) for call in fake.calls)
    (browsers / "chromium-1200").mkdir()
    assert cm._env_007(ctx).status == "fail" and "chromium_headless_shell-1200" in cm._env_007(ctx).message
    (browsers / "chromium_headless_shell-1200").mkdir()
    assert cm._env_007(ctx).status == "pass"


def test_env_007_failures_name_the_doctor_fix_and_the_root_step(make_ctx, tmp_path: Path):
    """chromium-provision 1.2 (L4-ADO-020): both failures say what installs the browser and who runs the root step."""
    cfg = config(gates={"e2e": {"command": "npx playwright test"}})
    empty, _ = make_ctx(cfg=cfg, L4_CACHE=str(tmp_path / "empty"))
    stale_browsers = tmp_path / "stale" / "shared" / "ms-playwright"
    (stale_browsers / "chromium-1100").mkdir(parents=True)  # a browser left by an older Playwright
    stale, _ = make_ctx(
        {"uvx": f"Install location: {stale_browsers}/chromium-1200"}, cfg=cfg, L4_CACHE=str(tmp_path / "stale")
    )
    for ctx in (empty, stale):
        result = cm._env_007(ctx)
        hint = result.fix_hint or ""
        assert result.status == "fail"
        assert "l4 doctor --fix" in hint and "l4 doctor --ci --fix" in hint
        assert f"sudo npx -y playwright@{PLAYWRIGHT_VERSION} install-deps chromium" in hint
        assert "prereqs.sh" not in hint


def test_env_008_serena_pin(make_ctx):
    missing, _ = make_ctx({"git": "x"})
    assert cm._env_008(missing).status == "fail" and "not found" in cm._env_008(missing).message
    wrong, _ = make_ctx({"serena": "serena 1.8.0"})
    assert cm._env_008(wrong).status == "fail" and "1.8.0" in cm._env_008(wrong).message
    right, _ = make_ctx({"serena": "serena 1.7.0"})
    assert cm._env_008(right).status == "pass"
    off, _ = make_ctx(cfg=config(memory={"serena": {"enabled": False}}))
    assert cm._env_008(off).status == "skip"


def test_mem002_passes_when_nothing_is_ignored_and_skips_without_memory(make_ctx, raw, git_environ):
    ctx, _ = make_ctx(**git_environ)
    raw(ctx.repo, "init", "-q")
    assert cm._mem_002(ctx).status == "pass"
    off, _ = make_ctx(cfg=config(memory={"enabled": False}), **git_environ)
    assert cm._mem_002(off).status == "skip"


def test_mem002_carve_out_unignores_the_harness_paths(make_ctx, raw, git_environ):
    """A5 (M1.8): the carve-out the check prints is applied to the real `.gitignore`, and git then ignores neither."""
    from l4.memory.ignore import apply_carve_out, ignored_harness_paths

    ctx, _ = make_ctx(**git_environ)
    raw(ctx.repo, "init", "-q")
    (ctx.repo / ".gitignore").write_text("dist/\n.serena/\n")
    result = cm._mem_002(ctx)
    assert result.status == "fail" and "!.serena/project.yml" in result.message
    assert ".serena/memories/harness/lessons.md" in result.message and result.fix_hint
    fixed = apply_carve_out((ctx.repo / ".gitignore").read_text(), ignored_harness_paths(ctx.repo, git_environ))
    for line in ("!.serena/project.yml", "!.serena/memories/harness/"):
        assert line in result.message and line in fixed  # the printed lines are the applied ones
    (ctx.repo / ".gitignore").write_text(fixed)
    assert cm._mem_002(ctx).status == "pass"
    assert ignored_harness_paths(ctx.repo, git_environ) == []


def test_mem002_is_registered_as_a_config_warning():
    from l4.doctor.registry import REGISTRY, load_check_modules

    load_check_modules()
    check = next(c for c in REGISTRY.checks() if c.id == "MEM-002")
    assert check.severity == "warn" and {"ci", "local", "config"} <= check.scopes


def test_laya_and_serena_hints_name_the_runner_fix(make_ctx):
    """On a CI runner the fix is `l4 doctor --ci --fix` (adoption-lessons 6.3, L4-ADO-015); prereqs.sh stays."""
    ctx, _ = make_ctx(tools={}, cfg=config(profiles={"laya": Profile(backend="system-one", engine="laya-local")},
                                           roles={"s1_judge": ["laya"]}))  # fmt: skip
    for result in (cm._env_006(ctx), cm._env_008(ctx)):
        assert result.status == "fail" and "l4 doctor --ci --fix" in (result.fix_hint or "")
        assert "prereqs.sh --with-" in (result.fix_hint or "")
