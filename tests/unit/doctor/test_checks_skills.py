"""SKL-003 (L4-SKL-003, SCN-SKL-08): an installed l4 skill older than the running l4 is a warning."""

import json
from pathlib import Path

from l4 import __version__
from l4.doctor import checks_skills
from l4.doctor.registry import REGISTRY


def install(path: Path, version: str) -> None:
    path.mkdir(parents=True)
    (path / ".l4-skill.json").write_text(json.dumps({"name": "l4", "version": version, "files": {}}))


def test_it_is_a_registered_warning():
    assert checks_skills.SKL_003.severity == "warn"
    assert any(c.id == "SKL-003" for c in REGISTRY.checks())


def test_no_installed_copy_is_a_skip(make_ctx):
    ctx, _ = make_ctx()
    assert checks_skills._skl_003(ctx).status == "skip"


def test_scn_skl_08_an_old_copy_warns_with_the_fix(make_ctx, tmp_path):
    ctx, _ = make_ctx()
    target = tmp_path / "home" / ".claude" / "skills" / "l4"
    install(target, "0.0.1")
    result = checks_skills._skl_003(ctx)
    assert result.status == "fail"
    assert str(target) in result.message and "0.0.1" in result.message and __version__ in result.message
    assert result.fix_hint is not None and "l4 skills install" in result.fix_hint


def test_a_current_copy_passes(make_ctx, tmp_path):
    ctx, _ = make_ctx()
    install(tmp_path / "home" / ".kiro" / "skills" / "l4", __version__)
    assert checks_skills._skl_003(ctx).status == "pass"


def test_a_newer_copy_passes(make_ctx, tmp_path):
    ctx, _ = make_ctx()
    install(tmp_path / "home" / ".kiro" / "skills" / "l4", "99.0.0")
    assert checks_skills._skl_003(ctx).status == "pass"


def test_a_project_copy_in_a_repository_counts(make_ctx):
    ctx, _ = make_ctx()
    (ctx.repo / ".git").mkdir()
    install(ctx.repo / ".agents" / "skills" / "l4", "0.0.1")
    result = checks_skills._skl_003(ctx)
    assert result.status == "fail" and ".agents/skills/l4" in result.message


def test_a_project_copy_outside_a_repository_is_not_looked_for(make_ctx):
    ctx, _ = make_ctx()
    install(ctx.repo / ".agents" / "skills" / "l4", "0.0.1")  # no .git: not a repository
    assert checks_skills._skl_003(ctx).status == "skip"
