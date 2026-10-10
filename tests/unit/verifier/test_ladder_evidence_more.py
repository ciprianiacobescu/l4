# ruff: noqa: F811
"""Join lines 12 to 14, the parts that need no `l4 run`: the env the ladder hands the test gate, the sandbox mounts,
the Evidence section after a resume, a fix unit's inherited scope, and S1 shadow rows that decide nothing."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from l4.config.schema import L4Config
from l4.gates.coverage import cov_env, merge_pytest_env, plugin_dir
from l4.gates.trace import trace_env
from l4.s1.records import AnswerRecord
from l4.s1.shadow import ShadowRun
from l4.sandbox.bwrap import BwrapSandbox
from l4.sandbox.env import build_gate_env
from l4.specs.base import Framework, UnitRef
from l4.vcs.git import Git
from l4.vcs.trailers import CommitTrailers
from l4.verifier import ladder
from l4.verifier.types import Verdict, VerifyResult

from ..evidence._multi import RUN_ID, build_repo
from .test_ladder_evidence import (  # noqa: F401  (fixtures and scripts)
    CID,
    STOCK,
    UNIT_DIR,
    evidence,
    green,
    judge,
    multi,
    red,
    report,
    run_multi,
)


@pytest.mark.parametrize("coverage", ["warn", "off"])
def test_step3_hands_the_gate_the_coverage_env_unless_diff_coverage_is_off(run_multi, monkeypatch, coverage):
    seen: list = []
    real = ladder.run_test_gate

    def spy(wb, must_contain, *, extra_env=None):
        seen.append(extra_env)
        return real(wb, must_contain, extra_env=extra_env)

    monkeypatch.setattr(ladder, "run_test_gate", spy)
    assert run_multi([red(), green(), judge()], coverage=coverage).code == 0
    [env] = seen
    if coverage == "off":
        assert env is None
        return
    assert env["PYTEST_ADDOPTS"] == "-p l4_cov" and env["PYTHONPATH"] == str(plugin_dir())
    rc = Path(env["L4_COV_RC"])
    assert rc.parts[-3:-1] == (".l4-out", "cov") and env["L4_COV_NONCE"]  # under the worktree: writable in the sandbox
    assert "source =\n    src/shop" in rc.read_text() or "src/shop" in rc.read_text()


def test_the_gate_sandbox_sees_the_plugin_and_can_write_the_coverage_directory(make_bench):
    wb = make_bench([]).wb
    cov_dir = wb.worktree / ".l4-out" / "cov"
    spec = wb.gate_spec(network=False)
    extra = merge_pytest_env(trace_env(), cov_env(cov_dir, ["src/pytdd"]))
    env = build_gate_env(wb.host_env, spec, extra=extra)
    argv = BwrapSandbox("bwrap").build_argv(["pytest"], spec, env)
    assert argv[argv.index("--ro-bind") : argv.index("--ro-bind") + 3] == [
        "--ro-bind",
        "/",
        "/",
    ]  # the plugin is readable
    writable = [argv[i + 1] for i, a in enumerate(argv) if a == "--bind"]
    assert str(wb.worktree) in writable and cov_dir.is_relative_to(wb.worktree)
    hidden = [Path(argv[i + 1]) for i, a in enumerate(argv) if a == "--tmpfs" and argv[i + 1] != "/tmp"]
    assert not any(plugin_dir().is_relative_to(h) for h in hidden)
    i = argv.index("PYTEST_ADDOPTS")
    assert argv[i - 1] == "--setenv" and argv[i + 1] == "-p l4_trace -p l4_cov"


def test_the_evidence_section_is_rebuilt_from_verdict_json_alone(run_multi):
    from l4.evidence.report import render_evidence_json

    run = run_multi([red(), green(), judge()])
    ev = json.loads(run.pushed(f"{UNIT_DIR}/.l4/evidence/round-1/verdict.json"))["evidence"]
    assert "\n".join(render_evidence_json(ev)) in report(run)
    assert report(run).count("## Evidence") == 1


@pytest.mark.parametrize("p", [0.0, 1.0])
def test_shadow_rows_are_recorded_and_whatever_the_engines_say_the_verdict_is_the_same(run_multi, monkeypatch, p):
    def fake_shadow(cfg, items, **kwargs):
        answers = [
            AnswerRecord(i.item_key, "remote", "s1", "fake", {q: {"kind": "noul", "p_true": p} for q in i.expected}, 1)
            for i in items
        ]
        return ShadowRun(list(items), [i.item_key for i in items], answers, [])

    monkeypatch.setattr(ladder, "run_shadow", fake_shadow)
    profile = {"backend": "system-one", "engine": "remote", "base_url": "http://s1.test"}
    run = run_multi(
        [red(), green(), judge()],
        edit=lambda body: body["profiles"].update(s1=profile) or body["verifier"].update(s1={"shadow": ["s1"]}),
    )
    assert run.code == 0 and run.outcome["units"][0]["verdict"] == "PASS"
    rows = [json.loads(line) for line in (run.tdd.cache / "s1-calibration.jsonl").read_text().splitlines()]
    kinds = {r["kind"] for r in rows if "kind" in r}
    assert kinds == {"item", "answer"} and any(r.get("question_set") == "l4/tests-ok@2" for r in rows)
    keys = evidence(run)["items"]
    assert keys and set(keys.values()) <= {r["item_key"] for r in rows if r.get("kind") == "item"}


@pytest.mark.parametrize("p", [0.0, 1.0])
@pytest.mark.parametrize(
    "case,scope,code,hold",
    [("scope", "warn", 11, "scope"), ("coverage", "warn", 11, "coverage"), ("scope", "fail", 10, None)],
)
def test_shadow_answers_change_no_hold_and_no_fail(run_multi, monkeypatch, p, case, scope, code, hold):
    """Join review: the engines' answers (all true, all false) leave a held unit held with the same hold, and a failing
    unit failing."""
    from .test_ladder_evidence import EXTRA_FUNCTION, GREEN

    def fake_shadow(cfg, items, **kwargs):
        answers = [
            AnswerRecord(i.item_key, "remote", "s1", "fake", {q: {"kind": "noul", "p_true": p} for q in i.expected}, 1)
            for i in items
        ]
        return ShadowRun(list(items), [i.item_key for i in items], answers, [])

    monkeypatch.setattr(ladder, "run_shadow", fake_shadow)
    profile = {"backend": "system-one", "engine": "remote", "base_url": "http://s1.test"}
    extra = STOCK if case == "scope" else {"src/shop/cart.py": GREEN + EXTRA_FUNCTION}
    run = run_multi(
        [red(), green(extra), judge()], scope=scope,
        edit=lambda body: body["profiles"].update(s1=profile) or body["verifier"].update(s1={"shadow": ["s1"]}),
    )  # fmt: skip
    ev = evidence(run)
    assert run.code == code and ev["items"]
    assert [h["kind"] for h in ev["holds"]] == ([hold] if hold else [])


# -- (v) a fix unit that names nothing is held to its parent's scope

FIX = "openspec/changes/cart-totals-fix-1"
MARKER = '{"schema": "l4/fix-unit@1", "parent": "openspec:cart-totals", "round": 1, "findings": ["F-1"], "chores": []}'


def test_v_a_fix_unit_that_names_nothing_is_out_of_scope_through_its_parents_scope(tmp_path, git_environ):
    repo = tmp_path / "repo"
    git, units = build_repo(repo, git=Git(repo, environ=git_environ), units=5)
    for name, text in {
        "proposal.md": "## Why\n\nReview findings.\n\n## What Changes\n\n- Fixes.\n\n"
        "## Impact\n\nThe code and the tests of `cart-totals`.\n",
        "tasks.md": "## 1. Fix\n\n- [ ] 1.1 Fix the findings\n",
        ".l4/fix.json": MARKER,
    }.items():
        (repo / FIX / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / FIX / name).write_text(text)
    git.run("add", "-A")
    base = git.commit(
        "docs(cart-totals): fix unit 1 [skip ci]", CommitTrailers("openspec:cart-totals", RUN_ID, 1, "fixing")
    )
    for rel, text in STOCK.items():
        (repo / rel).write_text(text)
    git.run("add", "-A")
    head = git.commit("fix: stock", CommitTrailers("openspec:cart-totals", RUN_ID, 1, "fixing"))
    ref = UnitRef(Framework.OPENSPEC, "cart-totals-fix-1", repo / FIX)

    def scope(policy: str):
        cfg = L4Config.model_validate({"sdd": {"scope_check": policy}})
        wb = SimpleNamespace(ref=ref, git=git, cfg=cfg, worktree=repo)
        result = VerifyResult(ref.id, 1, Verdict.NEEDS_HUMAN, base, head)
        run = ladder._Run(result)
        ladder._scope_step(SimpleNamespace(wb=wb), run, base)
        return run

    warn = scope("warn")
    labels = {f.path: f.label for f in warn.scope.outcome.files}
    assert labels["src/inventory/stock.py"] == "out_of_scope"  # the fix unit's own proposal names nothing
    assert warn.result.holds == [
        "scope: `src/inventory/stock.py` changes module `inventory`, which the spec does not name"
    ]
    failing = scope("fail")
    assert [f.title for f in failing.result.findings] == ["change outside the feature: src/inventory/stock.py"]
    assert failing.result.holds == []


# -- the coverage directory is repository-controlled ground: a planted link is never followed (join review)


@pytest.mark.parametrize("mode", ["off", "warn"])
@pytest.mark.parametrize("link", [".l4-out", ".l4-out/cov"])
def test_a_symlinked_coverage_directory_is_neither_cleared_nor_written_through(tmp_path, mode, link):
    worktree, outside = tmp_path / "wt", tmp_path / "outside"
    (outside / "cov").mkdir(parents=True)
    (outside / "cov" / "precious.txt").write_text("keep")
    (worktree / ".l4-out").mkdir(parents=True)
    if link == ".l4-out":
        (worktree / ".l4-out").rmdir()
        (worktree / ".l4-out").symlink_to(outside)
    else:
        (worktree / ".l4-out" / "cov").symlink_to(outside / "cov")
    cfg = L4Config.model_validate({"verifier": {"evidence": {"diff_coverage": {"mode": mode}}}})
    ref = UnitRef(Framework.OPENSPEC, "cart-totals", worktree / "openspec" / "changes" / "cart-totals")
    vc = SimpleNamespace(wb=SimpleNamespace(worktree=worktree, cfg=cfg, ref=ref))
    extra, cov_dir = ladder._coverage_env(vc, "base")
    assert extra is None and cov_dir is None
    assert sorted(p.name for p in (outside / "cov").iterdir()) == ["precious.txt"]


def test_the_ladder_reports_coverage_not_measured_when_the_directory_is_a_link(run_multi, monkeypatch, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    real = ladder._coverage_env

    def planted(vc, base_sha):
        cov = vc.wb.worktree / ".l4-out" / "cov"
        cov.parent.mkdir(parents=True, exist_ok=True)
        if not cov.is_symlink():
            cov.symlink_to(outside)
        return real(vc, base_sha)

    monkeypatch.setattr(ladder, "_coverage_env", planted)
    run = run_multi([red(), green(), judge()], coverage="fail")
    assert list(outside.iterdir()) == []  # no rc file, no nonce, no coverage data out of the checkout
    dc = evidence(run)["diff_coverage"]
    assert dc["status"] == "not_run" and "symlink" in dc["reason"]
    assert run.code == 11  # under `fail` coverage that was not measured is a hold, never a pass
