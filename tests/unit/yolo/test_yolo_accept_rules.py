"""`l4 yolo accept` rules at function level: the actor, the target's configuration, the refusals and when an
acceptance holds (review-resolution D7; L4-YOLO-027, SCN-YOLO-63..66)."""

import logging

import pytest

from l4.config.schema import YoloReviewCfg
from l4.vcs.git import Git
from l4.yolo import accept, findings
from l4.yolo.accept import Refusal, actor, check, holds, target_config
from l4.yolo.model import PlanState

from .yolo_ledger_world import _env, sh

SUBJECT = "openspec:a"
PERSON = ("person", None)
AGENT = ("agent", "CLAUDECODE")


def f(severity="major", criterion="testability", text="t"):
    return {"criterion": criterion, "severity": severity, "text": text}


def entry(verdict="NEEDS_REVISION", findings=None, digest="d1", **extra):
    return {"verdict": verdict, "findings": findings if findings is not None else [f()], "digest": digest, **extra}


def two_rounds():
    return [entry(digest="d1"), entry(digest="d2")]


def state(status="reviewed", **extra):
    return PlanState(plan_id="p1", status=status, **extra)


def run_check(*, st=None, history=None, latest=None, cfg=None, who=PERSON, subject=SUBJECT):
    return check(
        st or state(),
        two_rounds() if history is None else history,
        subject,
        latest or entry(digest="d2"),
        cfg or YoloReviewCfg(),
        who,
    )


# --- actor -------------------------------------------------------------------------------------------------


def test_a_terminal_without_a_marker_is_a_person():
    assert actor({}, True) == ("person", None)
    assert actor({"PATH": "/usr/bin", "HOME": "/h"}, True) == ("person", None)


def test_no_terminal_and_no_marker_is_an_agent_without_a_marker():
    assert actor({}, False) == ("agent", None)


@pytest.mark.parametrize(
    "marker", ["CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "AI_AGENT", "CODEX_SANDBOX", "L4_RESULT_PATH"]
)
def test_each_marker_makes_an_agent_and_is_named(marker):
    assert actor({marker: "1"}, False) == ("agent", marker)


@pytest.mark.parametrize("marker", ["CLAUDECODE", "AI_AGENT", "L4_RESULT_PATH"])
def test_a_terminal_with_a_marker_is_an_agent(marker):
    assert actor({marker: "1"}, True) == ("agent", marker)


def test_the_first_marker_found_in_the_documented_order_is_named():
    environ = {"L4_RESULT_PATH": "/x", "AI_AGENT": "x", "CLAUDECODE": "1"}
    assert actor(environ, True) == ("agent", "CLAUDECODE")
    assert actor({"L4_RESULT_PATH": "/x", "CODEX_SANDBOX": "seatbelt"}, False) == ("agent", "CODEX_SANDBOX")


def test_an_empty_marker_is_not_set():
    assert actor({"CLAUDECODE": ""}, True) == ("person", None)


def test_stdout_is_not_a_parameter_so_a_piped_output_with_a_terminal_stdin_is_a_person():
    # `l4 yolo accept ... | tee log`: only stdin is looked at (memory/promote.py:58 does the same)
    assert actor({}, True) == ("person", None)


# --- the refusals, one by one ------------------------------------------------------------------------------


def test_an_acceptable_subject_is_not_refused_for_a_person():
    assert run_check() is None


def test_the_refusal_carries_a_message_and_a_fix():
    r = run_check(history=[entry()])
    assert isinstance(r, Refusal) and r.message and r.fix


@pytest.mark.parametrize("status", ["new", "refused", "admitted", "reviewed"])
def test_a_plan_before_activation_can_be_accepted_on(status):
    assert run_check(st=state(status)) is None


@pytest.mark.parametrize("reason", ["inputs_changed", "unit_rejected"])
def test_a_plan_stopped_for_inputs_or_a_rejected_unit_can_be_accepted_on(reason):
    assert run_check(st=state("stopped", stop_reason=reason)) is None


@pytest.mark.parametrize(
    "st",
    [
        state("active"),
        state("waiting"),
        state("completed"),
        state("cancelled"),
        state("stopped", stop_reason="deadline"),
        state("stopped", stop_reason=None),
    ],
)
def test_an_active_waiting_final_or_otherwise_stopped_plan_is_refused(st):
    r = run_check(st=st)
    assert r is not None and "p1" in r.message and st.status in r.message


def test_blocked_is_refused_with_the_fix_the_spec():
    r = run_check(latest=entry("BLOCKED", digest="d2"))
    assert r is not None and "BLOCKED" in r.message and r.fix.startswith("fix the spec")


def test_a_harness_blocked_means_no_review_happened():
    for criterion in ("schema", "unit_missing", "completeness"):
        r = run_check(latest=entry("BLOCKED", [f("blocking", criterion)], digest="d2"))
        assert r is not None and "BLOCKED" in r.message
        assert "review" in r.fix and not r.fix.startswith("fix the spec")


def test_a_blocking_finding_is_refused_with_the_fix_the_spec():
    r = run_check(latest=entry(findings=[f("major"), f("blocking", "interfaces", "no names")], digest="d2"))
    assert r is not None and "blocking" in r.message and "interfaces" in r.message and r.fix.startswith("fix the spec")


def test_a_material_finding_is_refused_with_the_size_limit_fix():
    cut = f("blocking", "material", "material_cut: specs/x.md has 30000 characters")
    r = run_check(latest=entry(findings=[f(), cut], digest="d2"))
    assert r is not None and "material" in r.message
    assert r.fix.startswith("shorten the file or raise yolo.review.max_file_chars")


def test_a_material_finding_of_any_severity_is_refused():
    r = run_check(latest=entry(findings=[f("major", "material", "cut")], digest="d2"))
    assert r is not None and r.fix.startswith("shorten the file")


def test_ready_has_nothing_to_accept():
    r = run_check(latest=entry("READY", [f("minor")], digest="d2"))
    assert r is not None and "nothing to accept" in r.message


def test_one_version_is_not_enough_scn_63():
    r = run_check(history=[entry(digest="d1"), entry(digest="d1")])  # judged twice, one version of the text
    assert r is not None
    assert r.message == "openspec:a was judged not READY on 1 version; 2 are needed (yolo.review.accept_after_rounds)"
    assert "accept_after_rounds" in r.fix


def test_no_version_judged_is_zero_versions_plural():
    r = run_check(history=[])
    assert r is not None and "on 0 versions; 2 are needed" in r.message


def test_a_ready_version_does_not_count():
    r = run_check(history=[entry("READY", [], digest="d1"), entry(digest="d2")])
    assert r is not None and "on 1 version;" in r.message


def test_rounds_follow_the_configured_threshold():
    one = [entry(digest="d2")]
    assert run_check(history=one, cfg=YoloReviewCfg(accept_after_rounds=1)) is None
    r = run_check(history=two_rounds(), cfg=YoloReviewCfg(accept_after_rounds=3))
    assert r is not None and "3 are needed" in r.message


def test_a_batch_version_is_the_list_of_its_units_digests():
    batch = [entry(digest=None, digests={"a": "1", "b": "2"}), entry(digest=None, digests={"a": "1", "b": "3"})]
    batch = [{k: v for k, v in e.items() if k != "digest"} for e in batch]
    assert run_check(subject="batch:b1", history=batch, latest=batch[1]) is None
    same = [batch[0], dict(batch[0])]
    r = run_check(subject="batch:b1", history=same, latest=same[1])
    assert r is not None and "on 1 version;" in r.message


def test_an_entry_without_a_digest_falls_back_to_its_material_key():
    old = [entry(digest=None, material="m1"), entry(digest=None, material="m2")]
    old = [{k: v for k, v in e.items() if k != "digest"} for e in old]
    assert run_check(history=old, latest=old[1]) is None


def test_an_agent_is_refused_unless_the_target_allows_it_scn_65():
    r = run_check(who=AGENT)
    assert r is not None and r.message == "acceptance is a person's decision"
    assert "l4 yolo accept p1 openspec:a" in r.fix and "accept_by_agents" in r.fix
    assert run_check(who=AGENT, cfg=YoloReviewCfg(accept_by_agents=True)) is None
    assert run_check(who=("agent", None)) is not None


def test_a_person_is_not_refused_when_agents_are_not_allowed():
    assert run_check(who=PERSON, cfg=YoloReviewCfg(accept_by_agents=False)) is None


def test_the_order_of_the_checks():
    cut = f("blocking", "material", "cut")
    everything = entry("BLOCKED", [f("blocking", "interfaces"), cut], digest="d2")
    st = state("active")

    def msg(**kw):
        r = run_check(**kw)
        assert r is not None
        return r.message

    base = {"st": st, "latest": everything, "history": [], "who": AGENT}
    assert "is active" in msg(**base)  # plan status first
    base["st"] = state()
    assert "BLOCKED" in msg(**base)  # then the verdict
    base["latest"] = entry(findings=[f("blocking", "interfaces"), cut], digest="d2")
    assert "blocking" in msg(**base) and "material" not in msg(**base).replace("blocking", "")  # then blocking
    base["latest"] = entry(findings=[cut], digest="d2")
    assert "material" in msg(**base)  # then material
    base["latest"] = entry("READY", [], digest="d2")
    assert "nothing to accept" in msg(**base)  # then READY
    base["latest"] = entry(digest="d2")
    assert "version" in msg(**base)  # then the rounds
    base["history"] = two_rounds()
    assert msg(**base) == "acceptance is a person's decision"  # the agent last


def test_a_withdrawal_is_never_refused_for_the_actor():
    for who in (PERSON, AGENT, ("agent", None)):
        for st in (state("active"), state("completed"), state("reviewed")):
            assert check(st, [], SUBJECT, entry("READY", [], digest="d"), YoloReviewCfg(), who, withdraw=True) is None


def test_a_plain_actor_name_is_understood_too():
    assert run_check(who="person") is None
    assert run_check(who="agent") is not None


# --- holds -------------------------------------------------------------------------------------------------


def accepted(material="m1", sha="h1"):
    return {"material": material, "findings_sha": sha, "by": "me"}


def review(**entries):
    return {"units": {k: v for k, v in entries.items() if not k.startswith("batch_")},
            "batches": {k[6:]: v for k, v in entries.items() if k.startswith("batch_")}}  # fmt: skip


def test_an_acceptance_holds_while_material_and_findings_hash_are_unchanged_scn_66():
    st = state(accepted={SUBJECT: accepted()})
    same = {"openspec:a": entry(material="m1", findings_sha="h1")}
    assert holds(st, review(**{SUBJECT: same["openspec:a"]})) == {SUBJECT: True}


def test_a_changed_material_or_findings_hash_voids_it():
    st = state(accepted={SUBJECT: accepted()})
    assert holds(st, review(**{SUBJECT: entry(material="m2", findings_sha="h1")})) == {SUBJECT: False}
    assert holds(st, review(**{SUBJECT: entry(material="m1", findings_sha="h2")})) == {SUBJECT: False}


def test_a_subject_missing_from_the_review_or_without_a_key_does_not_hold():
    st = state(accepted={SUBJECT: accepted(), "batch:b1": accepted()})
    got = holds(st, review(**{SUBJECT: entry()}))  # an old entry without `material`
    assert got == {SUBJECT: False, "batch:b1": False}


def test_a_batch_is_looked_up_under_batches_and_a_flat_mapping_is_understood():
    st = state(accepted={"batch:b1": accepted()})
    e = entry(material="m1", findings_sha="h1")
    assert holds(st, {"units": {}, "batches": {"b1": e}}) == {"batch:b1": True}
    assert holds(st, {"batch:b1": e}) == {"batch:b1": True}


def test_without_an_acceptance_the_answer_is_empty():
    assert holds(state(), review()) == {}


def test_the_findings_hash_is_computed_from_the_findings_when_the_entry_has_none(monkeypatch):
    seen = []
    monkeypatch.setattr(findings, "findings_sha", lambda fs: seen.append(fs) or "h1")
    st = state(accepted={SUBJECT: accepted()})
    got = holds(st, review(**{SUBJECT: entry(material="m1", findings=[f()])}))
    assert got == {SUBJECT: True} and seen == [[f()]]


# --- target_config -----------------------------------------------------------------------------------------


def repo(tmp_path, config: str | None):
    root = tmp_path / "r"
    root.mkdir()
    sh(root, "init", "--quiet", "-b", "main")
    sh(root, "config", "user.email", "t@example.com")
    sh(root, "config", "user.name", "t")
    if config is not None:
        (root / ".l4").mkdir()
        (root / ".l4" / "config.yaml").write_text(config)
    else:
        (root / "x").write_text("x")
    sh(root, "add", "-A")
    sh(root, "commit", "--quiet", "-m", "c")
    return Git(root, environ=_env())


def test_the_config_is_read_at_the_ref_not_the_working_tree(tmp_path):
    git = repo(tmp_path, "yolo:\n  review:\n    accept_by_agents: true\n    accept_after_rounds: 3\n")
    (tmp_path / "r" / ".l4" / "config.yaml").write_text("yolo:\n  review:\n    accept_by_agents: false\n")
    cfg = target_config(git, "HEAD")
    assert cfg.accept_by_agents is True and cfg.accept_after_rounds == 3


def test_an_absent_file_gives_the_defaults(tmp_path):
    assert target_config(repo(tmp_path, None), "HEAD") == YoloReviewCfg()


def test_an_unknown_ref_gives_the_defaults(tmp_path):
    assert target_config(repo(tmp_path, None), "origin/nope") == YoloReviewCfg()


def test_a_file_without_a_yolo_section_gives_the_defaults(tmp_path):
    assert target_config(repo(tmp_path, "gates: {}\n"), "HEAD") == YoloReviewCfg()


@pytest.mark.parametrize(
    "bad", ["yolo: [", "yolo:\n  review:\n    accept_after_rounds: 0\n", "- a list\n", "nonsense_key: 1\n"]
)
def test_an_invalid_file_gives_the_defaults_and_a_log_line(tmp_path, caplog, bad):
    with caplog.at_level(logging.WARNING, logger="l4.yolo.accept"):
        cfg = target_config(repo(tmp_path, bad), "HEAD")
    assert cfg == YoloReviewCfg() and cfg.accept_by_agents is False
    assert any("config" in r.getMessage() for r in caplog.records)


def test_a_missing_file_logs_at_most_a_debug_line(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="l4.yolo.accept"):
        target_config(repo(tmp_path, None), "HEAD")
    assert not caplog.records


def test_the_module_exposes_the_contract():
    assert {"actor", "target_config", "check", "holds", "Refusal"} <= set(dir(accept))
