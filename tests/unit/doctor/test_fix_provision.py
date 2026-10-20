"""`l4 doctor --ci` holds an agent CLI to its exact pin: the switch reaches the install and the survey (L4-PRV-043)."""

import dataclasses

import pytest

from l4.cli import main
from l4.doctor import checks_provision


@pytest.fixture
def seen(monkeypatch):
    calls = {"install": [], "plan": []}
    monkeypatch.setattr(
        checks_provision, "install_planned", lambda *a, **kw: calls["install"].append(kw["replace_present"]) or []
    )
    monkeypatch.setattr(
        checks_provision, "plan_fixes", lambda *a, **kw: calls["plan"].append(kw["replace_present"]) or []
    )
    return calls


@pytest.mark.parametrize("ci", [True, False])
def test_ci_passes_replace_present(make_ctx, seen, ci):
    ctx, _ = make_ctx()
    ctx = dataclasses.replace(ctx, ci=ci)
    checks_provision.fix_provision(ctx)
    assert seen["install"] == [ci]


@pytest.mark.parametrize("ci", [True, False])
def test_the_survey_matches(make_ctx, seen, ci):
    ctx, _ = make_ctx()
    checks_provision.survey_provision(dataclasses.replace(ctx, ci=ci))
    assert seen["plan"] == [ci]


def test_the_context_defaults_to_not_ci(make_ctx):
    assert make_ctx()[0].ci is False


@pytest.mark.parametrize(("flags", "ci"), [(["--ci"], True), ([], False)])
def test_doctor_sets_ci_from_its_flag(tmp_path, monkeypatch, seen, flags, ci):
    repo = tmp_path / "repo"
    (repo / ".l4").mkdir(parents=True)
    (repo / ".l4" / "config.yaml").write_text("version: 1\n")
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path / "home"), "L4_CACHE": str(tmp_path / "cache")}
    main(["doctor", "--fix", *flags, "--repo", str(repo)], environ=env)
    assert seen["install"] and set(seen["install"]) == {ci}
