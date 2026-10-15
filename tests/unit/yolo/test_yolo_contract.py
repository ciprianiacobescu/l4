"""review-resolution 0.1: the contract (config, model fields, stubs, CLI rows) with no behaviour."""

import inspect

import pytest
from pydantic import ValidationError

from l4.cli import main
from l4.config.schema import L4Config, YoloReviewCfg
from l4.exitcodes import ExitCode
from l4.yolo import commands, findings, judge_sandbox, review_worktree, worktree
from l4.yolo.cycle import PlanStep
from l4.yolo.model import Verdict
from l4.yolo.state import fold_plan

from .yolo_cmd_world import world  # noqa: F401
from .yolo_ledger_world import ev


def test_review_configuration_defaults():
    cfg = L4Config().yolo.review
    assert isinstance(cfg, YoloReviewCfg)
    assert (cfg.max_file_chars, cfg.max_folder_chars, cfg.max_dependency_chars) == (20_000, 80_000, 20_000)
    assert (cfg.accept_after_rounds, cfg.accept_by_agents) == (2, False)
    assert L4Config.model_validate({"yolo": {"review": {"accept_by_agents": True}}}).yolo.review.accept_by_agents


@pytest.mark.parametrize(
    "bad",
    [{"accept_after_rounds": 0}, {"max_file_chars": 999}, {"max_folder_chars": 999}, {"max_dependency_chars": -1}],
)
def test_review_configuration_rejects_out_of_range(bad):
    with pytest.raises(ValidationError):
        L4Config.model_validate({"yolo": {"review": bad}})


def test_review_configuration_rejects_unknown_keys():
    with pytest.raises(ValidationError):
        L4Config.model_validate({"yolo": {"review": {"nope": 1}}})


def test_the_new_model_fields_default_to_nothing():
    v = Verdict("READY")
    assert v.material is None and v.reused_from is None
    s = fold_plan("p1", [])
    assert s.accepted == {} and s.activated_accepted == {}
    assert PlanStep(allow=None).accepted == {}


def test_an_old_ledger_folds_as_before():
    events = [
        ev("plan.admitted", plan_digest="d1", order=["openspec:a"], merge="auto"),
        ev(
            "plan.reviewed",
            plan_digest="d1",
            units={"openspec:a": {"verdict": "READY", "digest": "da", "findings": []}},
        ),
        ev("plan.activated", plan_digest="d1", digests={"openspec:a": "da"}, limits={"max_runs": 5}, by="me"),
    ]
    s = fold_plan("p1", events)
    assert s.status == "active" and s.review == {"openspec:a": "READY"} and s.activated_by == "me"
    assert s.accepted == {} and s.activated_accepted == {}


def test_the_new_modules_are_stubs():
    calls = [
        (findings.finding_id, ("u", {})),
        (findings.findings_sha, ([],)),
        (worktree.snapshot, (None, [])),
        (worktree.clean, (None, [])),
        (judge_sandbox.choose, (None, {}, None)),
    ]
    for fn, args in calls:
        kwargs = {"adapter": "x", "in_ci": False} if fn is judge_sandbox.choose else {}
        with pytest.raises(NotImplementedError):
            fn(*args, **kwargs)
    with pytest.raises(NotImplementedError):
        review_worktree.run_review_worktree(None, plan="p1", fresh=(), record=False, no_run=False)
    with pytest.raises(NotImplementedError):
        commands.run_findings(None, plan="p1", subject=None, show_all=False, as_json=False)
    with pytest.raises(NotImplementedError):
        commands.run_accept(None, plan="p1", subject="s", reason="r", withdraw=False, yes=False)
    assert judge_sandbox.TOOL_LESS_ADAPTERS == ("claude-code", "opencode", "fake")
    assert "app" in inspect.signature(review_worktree.run_review_worktree).parameters


def test_yolo_help_lists_findings_and_accept(capsys):
    assert main(["yolo", "--help"], environ={}) == 0
    out = capsys.readouterr().out
    assert "findings" in out and "accept" in out


def test_review_help_lists_the_new_flags(capsys):
    assert main(["yolo", "review", "--help"], environ={}) == 0
    out = capsys.readouterr().out
    for flag in ("--worktree", "--record", "--fresh"):
        assert flag in out


def test_findings_and_accept_help(capsys):
    assert main(["yolo", "findings", "--help"], environ={}) == 0
    out = capsys.readouterr().out
    assert "--all" in out and "--json" in out
    assert main(["yolo", "accept", "--help"], environ={}) == 0
    out = capsys.readouterr().out
    assert "--reason" in out and "--withdraw" in out and "--yes" in out


def test_accept_requires_a_reason(capsys):
    assert main(["yolo", "accept", "p1", "openspec:a"], environ={}) != 0


@pytest.mark.parametrize("flags", [["--record"], ["--fresh", "openspec:a"]])
def test_record_and_fresh_need_worktree(world, flags):  # noqa: F811
    assert world.l4("review", "p1", *flags) == 2


def test_worktree_delegates_to_run_review_worktree(world, monkeypatch):  # noqa: F811
    seen = {}

    def fake(app, *, plan, fresh, record, no_run):
        seen.update(plan=plan, fresh=fresh, record=record, no_run=no_run)
        return ExitCode.OK

    monkeypatch.setattr("l4.yolo.review_worktree.run_review_worktree", fake)
    assert world.l4("review", "p1", "--worktree", "--record", "--fresh", "a", "--fresh", "b", "--no-run") == 0
    assert seen == {"plan": "p1", "fresh": ("a", "b"), "record": True, "no_run": True}
