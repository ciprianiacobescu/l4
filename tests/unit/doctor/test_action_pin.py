"""Doctor's pin check in action mode (adoption-kit L4-ACT-004, SCN-ACT-09): CFG-006 reads the workflow's `uses:` and
`commit`; CFG-007 says whether an `l4` is on PATH when there is no `.l4/bin/l4`."""

from pathlib import Path

import pytest

from l4.ci.github import ActionPin, render_github_action_ci
from l4.config.schema import L4Config
from l4.doctor import checks_config as cc
from l4.doctor.registry import REGISTRY

SHA = "a" * 40
OTHER = "b" * 40
WORKFLOW = ".github/workflows/l4.yml"
ACTION = ".github/actions/l4/action.yml"


def action_cfg(**harness) -> L4Config:
    return L4Config.model_validate({"harness": {"delivery": "action", **harness}})


def write(repo: Path, text: str, name: str = WORKFLOW) -> None:
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(text)


def rendered(pin: ActionPin) -> str:
    return render_github_action_ci(L4Config(), pin)


def test_a_sha_pin_passes(make_ctx):
    ctx, _ = make_ctx(cfg=action_cfg())
    write(ctx.repo, rendered(ActionPin("o/harness", SHA, "v0.3.0")))
    result = cc._cfg_006(ctx)
    assert result.status == "pass" and SHA[:12] in result.message


@pytest.mark.parametrize("pin", ["v0", "main", "abc123", "A" * 40, SHA[:39]])
def test_a_tag_or_short_sha_fails_and_names_the_value(make_ctx, pin):
    ctx, _ = make_ctx(cfg=action_cfg())
    write(ctx.repo, rendered(ActionPin("o/harness", SHA)).replace(f"@{SHA}", f"@{pin}"))
    result = cc._cfg_006(ctx)
    assert result.status == "fail" and pin in result.message and "40" in result.message
    assert result.fix_hint and "--harness-ref" in result.fix_hint


def test_drifting_uses_and_commit_fail_naming_both(make_ctx):
    """SCN-ACT-09: source repository through a published action: the two shas must be one."""
    ctx, _ = make_ctx(cfg=action_cfg())
    text = rendered(ActionPin("o/harness", SHA)).replace(
        f"@{SHA}\n        with:\n",
        f'@{SHA}\n        with:\n          source: repository\n          commit: "{OTHER}"\n',
        1,
    )
    write(ctx.repo, text)
    result = cc._cfg_006(ctx)
    assert result.status == "fail" and SHA in result.message and OTHER in result.message


def test_matching_uses_and_commit_pass(make_ctx):
    ctx, _ = make_ctx(cfg=action_cfg())
    text = rendered(ActionPin("o/harness", SHA)).replace(
        f"@{SHA}\n        with:\n",
        f'@{SHA}\n        with:\n          source: repository\n          commit: "{SHA}"\n',
        1,
    )
    write(ctx.repo, text)
    assert cc._cfg_006(ctx).status == "pass"


def test_copy_form_the_commit_input_is_the_pin(make_ctx):
    ctx, _ = make_ctx(cfg=action_cfg())
    write(ctx.repo, rendered(ActionPin("o/harness", SHA, copy=True)))
    write(ctx.repo, "name: L4 harness\n", ACTION)
    result = cc._cfg_006(ctx)
    assert result.status == "pass" and SHA[:12] in result.message


def test_copy_form_a_non_sha_commit_fails_naming_it(make_ctx):
    ctx, _ = make_ctx(cfg=action_cfg())
    write(ctx.repo, rendered(ActionPin("o/harness", SHA, copy=True)).replace(SHA, "v0.3.0"))
    write(ctx.repo, "name: L4 harness\n", ACTION)
    result = cc._cfg_006(ctx)
    assert result.status == "fail" and "v0.3.0" in result.message


def test_copy_form_without_the_action_file_fails(make_ctx):
    ctx, _ = make_ctx(cfg=action_cfg())
    write(ctx.repo, rendered(ActionPin("o/harness", SHA, copy=True)))
    result = cc._cfg_006(ctx)
    assert result.status == "fail" and ACTION in result.message


def test_no_workflow_or_no_action_step_fails(make_ctx):
    ctx, _ = make_ctx(cfg=action_cfg())
    assert cc._cfg_006(ctx).status == "fail"  # no file
    write(ctx.repo, "name: l4\njobs:\n  l4:\n    steps:\n      - run: echo\n")
    result = cc._cfg_006(ctx)
    assert result.status == "fail" and ".github/actions/l4" in result.message
    write(ctx.repo, "name: [\n")
    assert cc._cfg_006(ctx).status == "fail"


@pytest.mark.parametrize("cfg", [L4Config(), L4Config.model_validate({"harness": {"delivery": "vendored"}})])
def test_other_deliveries_skip_the_pin_check(make_ctx, cfg):
    ctx, _ = make_ctx(cfg=cfg)
    assert cc._cfg_006(ctx).status == "skip" and cc._cfg_007(ctx).status == "skip"


def test_a_local_l4_on_path_is_reported(make_ctx):
    ctx, _ = make_ctx(tools={"l4": "l4 0.1.0"}, cfg=action_cfg())
    result = cc._cfg_007(ctx)
    assert result.status == "pass" and "/fake/bin/l4" in result.message


def test_no_local_l4_says_how_to_install_one(make_ctx):
    ctx, _ = make_ctx(tools={"git": "git version 2.43.0"}, cfg=action_cfg())
    result = cc._cfg_007(ctx)
    assert result.status == "fail" and "uv tool install" in (result.fix_hint or "")


def test_a_shim_in_the_repository_means_the_question_does_not_arise(make_ctx):
    ctx, _ = make_ctx(tools={}, cfg=action_cfg())
    (ctx.repo / ".l4/bin").mkdir(parents=True)
    (ctx.repo / ".l4/bin/l4").write_text("#!/bin/sh\n")
    assert cc._cfg_007(ctx).status == "skip"


def test_registration_ids_severities_and_scopes():
    by_id = {c.id: c for c in REGISTRY.checks()}
    assert by_id["CFG-006"].severity == "error" and by_id["CFG-007"].severity == "info"
    assert {"ci", "local", "config"} <= by_id["CFG-006"].scopes
    assert {"ci", "local", "config"} <= by_id["CFG-007"].scopes


# --- adoption-lessons 1.4 (L4-ADO-005): the running harness is the pin of the base's workflow ---


@pytest.fixture
def running(monkeypatch):
    def set_commit(commit: str | None) -> None:
        monkeypatch.setattr(cc, "harness_commit", lambda: commit)

    return set_commit


CI_ENV = {"GITHUB_ACTIONS": "true"}


def test_an_old_pin_is_a_warning_naming_both_commits_and_the_fix(make_ctx, running):  # SCN-ADO-13
    ctx, _ = make_ctx(cfg=action_cfg(), **CI_ENV)
    write(ctx.repo, rendered(ActionPin("o/harness", OTHER)))  # the base pins B
    running(SHA)  # the job installed A
    result = cc._cfg_008(ctx)
    assert result.status == "fail"
    assert SHA in result.message and OTHER in result.message
    assert ".github/workflows/l4.yml" in (result.fix_hint or "") and "default branch" in (result.fix_hint or "")
    check = {c.id: c for c in REGISTRY.checks()}["CFG-008"]
    assert check.severity == "warn" and check.scopes == frozenset({"ci"})  # a warning never fails the job


def test_the_copy_form_compares_the_commit_input(make_ctx, running):
    ctx, _ = make_ctx(cfg=action_cfg(), **CI_ENV)
    write(ctx.repo, rendered(ActionPin("o/harness", OTHER, copy=True)))
    running(SHA)
    result = cc._cfg_008(ctx)
    assert result.status == "fail" and OTHER in result.message


def test_the_same_pin_passes(make_ctx, running):  # SCN-ADO-14
    ctx, _ = make_ctx(cfg=action_cfg(), **CI_ENV)
    write(ctx.repo, rendered(ActionPin("o/harness", SHA)))
    running(SHA)
    assert cc._cfg_008(ctx).status == "pass"


def test_no_check_outside_ci(make_ctx, running):  # SCN-ADO-15
    ctx, _ = make_ctx(cfg=action_cfg())
    write(ctx.repo, rendered(ActionPin("o/harness", OTHER)))
    running(SHA)
    result = cc._cfg_008(ctx)
    assert result.status == "skip" and "CI jobs only" in result.message


def test_other_deliveries_and_an_unknown_running_commit_skip(make_ctx, running):
    ctx, _ = make_ctx(cfg=L4Config(), **CI_ENV)
    running(SHA)
    assert cc._cfg_008(ctx).status == "skip"
    ctx, _ = make_ctx(cfg=action_cfg(), **CI_ENV)
    write(ctx.repo, rendered(ActionPin("o/harness", OTHER)))
    running(None)
    assert cc._cfg_008(ctx).status == "skip"


def test_a_workflow_that_cannot_be_read_or_has_no_step_is_left_to_cfg_006(make_ctx, running):
    ctx, _ = make_ctx(cfg=action_cfg(), **CI_ENV)
    running(SHA)
    assert cc._cfg_008(ctx).status == "skip"  # no file
    write(ctx.repo, "name: l4\njobs:\n  l4:\n    steps:\n      - run: echo\n")
    assert cc._cfg_008(ctx).status == "skip"


def test_cfg_010_shows_the_test_awareness_allow_list(make_ctx):  # SCN-VER-129
    empty, _ = make_ctx(cfg=L4Config())
    assert cc._cfg_010(empty).status == "pass" and "empty" in cc._cfg_010(empty).message
    listed, _ = make_ctx(cfg=L4Config.model_validate({"verifier": {"test_awareness_allow": ["tools/**", "src/x.py"]}}))
    result = cc._cfg_010(listed)
    assert result.status == "pass" and "tools/**" in result.message and "src/x.py" in result.message
    check = {c.id: c for c in REGISTRY.checks()}["CFG-010"]
    assert check.severity == "info" and {"ci", "local", "config"} <= check.scopes
