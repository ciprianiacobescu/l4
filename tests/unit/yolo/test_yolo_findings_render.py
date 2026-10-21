"""Findings: the text and the JSON of `l4 yolo findings`, and `most_severe` (review-resolution 1.7, design D1)."""

import json
import re
from dataclasses import replace

from l4.yolo import findings as fnd
from l4.yolo.accept import Refusal

from .yolo_ledger_world import ev

T = {"criterion": "testability", "severity": "major", "text": "no tolerance for the time bound"}
F = {"criterion": "failure_cases", "severity": "major", "text": "no case for invalid input"}
I = {"criterion": "interfaces", "severity": "major", "text": "the helper signature is open"}  # noqa: E741
X = {"criterion": "outcome", "severity": "minor", "text": "a nit"}
B = {"criterion": "feasibility", "severity": "blocking", "text": "needs a secret"}


def reviewed(at, units=None, batches=None, version=4, **extra):
    data = {"plan_digest": "p", "prompt_version": version, "units": units or {}, "batches": batches or {}, **extra}
    return replace(ev("plan.reviewed", **data), at=at)


def entry(verdict="NEEDS_REVISION", digest="d1", findings=(), **more):
    return {"verdict": verdict, "digest": digest, "findings": [dict(f) for f in findings], **more}


UNITS = {
    "openspec:a": fnd.UnitInfo(folder="openspec/changes/a", batch="b1", depends_on=()),
    "openspec:b": fnd.UnitInfo(folder="openspec/changes/b", batch="b1", depends_on=()),
}


def render(events, *, show_all=False, **kw):
    latest = [e for e in events if e.type == "plan.reviewed"][-1].data
    return fnd.render(
        "p1", "staging", latest, lambda s: fnd.history(events, s, 4), show_all=show_all, units=UNITS, **kw
    )


def one(findings, verdict="NEEDS_REVISION", **more):
    return [reviewed("2026-10-14T10:00:00Z", {"openspec:a": entry(verdict, findings=findings, material="k1", **more)})]


def test_scn_yolo_43_each_major_finding_comes_with_how_to_resolve_it():
    lines = render(one([T, X]))
    assert lines[0] == "openspec:a: NEEDS_REVISION"
    assert re.fullmatch(r"  F-[0-9a-f]{6} \[major/testability\] no tolerance for the time bound", lines[1]), lines[1]
    assert lines[1].startswith(f"  {fnd.finding_id('openspec:a', T)} ")
    assert lines[2].startswith(
        "    Resolve: Give the scenario concrete inputs and outputs in openspec/changes/a/specs/*/spec.md"
    )
    assert "  1 minor finding (--all shows it)" in lines
    assert not any("a nit" in line for line in lines)


def test_blocking_comes_before_major_and_the_judges_order_holds_within_a_severity():
    lines = render(one([F, X, T, B]))
    ids = [line.split()[0] for line in lines if line.startswith("  F-")]
    assert ids == [fnd.finding_id("openspec:a", f) for f in (B, F, T)]


def test_minor_findings_are_counted_in_the_plural():
    assert "  2 minor findings (--all shows them)" in render(one([T, X, {**X, "text": "other"}]))


def test_a_ready_subject_is_not_shown_without_all():
    events = [
        reviewed(
            "2026-10-14T10:00:00Z",
            {
                "openspec:a": entry("READY", material="k1", findings=[X]),
                "openspec:b": entry(findings=[F], material="k2"),
            },
        )
    ]
    lines = render(events)
    assert not any(line.startswith("openspec:a") for line in lines) and lines[0] == "openspec:b: NEEDS_REVISION"
    lines = render(events, show_all=True)
    assert "openspec:a: READY" in lines and "openspec:b: NEEDS_REVISION" in lines


def test_all_shows_minor_findings_assumptions_and_missing():
    lines = render(one([T, X], assumptions=["the clock is injected"], missing=["the retry limit"]), show_all=True)
    assert any("[minor/outcome] a nit" in line for line in lines)
    assert not any("--all shows" in line for line in lines)
    assert "  assumption: the clock is injected" in lines and "  missing: the retry limit" in lines
    quiet = render(one([T], assumptions=["the clock is injected"], missing=["the retry limit"]))
    assert not any("assumption" in line or "missing:" in line for line in quiet)


def test_scn_yolo_44_the_change_since_the_previous_judgement_is_shown():
    events = [
        reviewed("2026-10-14T10:00:00Z", {"openspec:a": entry(digest="d1", findings=[T, F], material="k1")}),
        reviewed("2026-10-14T11:00:00Z", {"openspec:a": entry(digest="d2", findings=[T, I], material="k2")}),
    ]
    lines = render(events)
    assert "  since the previous judgement: 1 new, 1 repeated, 1 gone" in lines
    assert "  persistent: testability ×2" in lines


def test_no_since_line_for_a_first_judgement_and_a_reuse_is_not_a_previous_judgement():
    assert not any("since the previous" in line or "persistent" in line for line in render(one([T])))
    events = [
        reviewed("2026-10-14T10:00:00Z", {"openspec:a": entry(findings=[T], material="k1")}),
        reviewed(
            "2026-10-14T11:00:00Z",
            {"openspec:a": entry(findings=[T], material="k1", reused_from="2026-10-14T10:00:00Z")},
        ),
    ]
    assert not any("since the previous" in line for line in render(events))


def test_the_previous_judgement_is_the_latest_one_of_other_material():
    events = [
        reviewed("2026-10-14T10:00:00Z", {"openspec:a": entry(digest="d1", findings=[F], material="k1")}),
        reviewed("2026-10-14T11:00:00Z", {"openspec:a": entry(digest="d2", findings=[T], material="k2")}),
        reviewed(
            "2026-10-14T12:00:00Z", {"openspec:a": entry(digest="d2", findings=[T, I], material="k3")}
        ),  # a prerequisite changed
    ]
    assert "  since the previous judgement: 1 new, 1 repeated, 0 gone" in render(events)


def test_a_batch_subject_is_rendered_under_its_name():
    events = [
        reviewed(
            "2026-10-14T10:00:00Z",
            batches={
                "b1": entry(
                    findings=[{"criterion": "batch_acceptance", "severity": "major", "text": "no outcome"}],
                    material="kb",
                )
            },
        )
    ]
    lines = render(events)
    assert lines[0] == "batch:b1: NEEDS_REVISION" and "give batch b1 an acceptance profile" in lines[2]


def test_the_acceptance_line_says_whether_it_holds():
    acc = {"openspec:a": {"by": "ana", "actor": "person", "reason": "keep the thresholds"}}
    lines = render(one([T]), accepted=acc, holds={"openspec:a": True})
    assert "  accepted by ana (person): keep the thresholds (holds)" in lines
    why = {"openspec:a": "other material: accepted on material m1 with findings aaaaaaaa; the latest review shows ..."}
    lines = render(one([T]), accepted=acc, holds={"openspec:a": False}, why=why)
    assert (
        "  accepted by ana (person): keep the thresholds (no longer holds: it was for other material: accepted on "
        "material m1 with findings aaaaaaaa; the latest review shows ...)" in lines
    )


def test_the_json_names_why_an_acceptance_does_not_hold():
    events = one([T])
    acc = {"openspec:a": {"by": "ana", "actor": "person", "reason": "r"}}
    latest = events[-1].data
    kw = {"accepted": acc, "units": UNITS}
    doc = fnd.render_json(
        "p1", "staging", latest, lambda s: [], holds={"openspec:a": False}, why={"openspec:a": "w"}, **kw
    )
    assert doc["subjects"][0]["accepted"]["why"] == "w" and doc["subjects"][0]["accepted"]["holds"] is False
    doc = fnd.render_json(
        "p1", "staging", latest, lambda s: [], holds={"openspec:a": True}, why={"openspec:a": "w"}, **kw
    )
    assert doc["subjects"][0]["accepted"]["why"] is None


def test_a_holding_acceptance_is_on_the_subject_line():
    """SCN-YOLO-175, the findings part."""
    acc = {"openspec:a": {"by": "ana", "actor": "person", "reason": "r"}}
    lines = render(one([T]), accepted=acc, holds={"openspec:a": True})
    assert lines[0] == "openspec:a: NEEDS_REVISION (accepted by ana: it does not stop the activation)"
    lines = render(one([T]), accepted=acc, holds={"openspec:a": False})
    assert lines[0] == "openspec:a: NEEDS_REVISION"
    assert render(one([T]))[0] == "openspec:a: NEEDS_REVISION"


def test_a_reused_entry_says_when_it_was_judged():
    events = one([T], reused_from="2026-10-13T09:00:00Z")
    lines = render(events)
    assert lines[1] == "  reused: judged 2026-10-13T09:00:00Z on the same material"
    assert not any("reused:" in line for line in render(one([T])))
    doc = fnd.render_json("p1", "staging", events[-1].data, lambda s: [], units=UNITS)
    assert doc["subjects"][0]["reused_from"] == "2026-10-13T09:00:00Z"
    assert (
        fnd.render_json("p1", "staging", one([T])[-1].data, lambda s: [], units=UNITS)["subjects"][0]["reused_from"]
        is None
    )


def test_the_accept_line_appears_only_when_accept_check_would_pass():
    asked = []

    def can(subject):
        asked.append(subject)
        return None if subject == "openspec:a" else Refusal("b waits", "push more")

    events = [
        reviewed(
            "2026-10-14T10:00:00Z",
            {"openspec:a": entry(findings=[T], material="k1"), "openspec:b": entry(findings=[F], material="k2")},
        )
    ]
    lines = render(events, can_accept=can)
    assert lines.count("  accept: l4 yolo accept p1 openspec:a --reason TEXT") == 1
    assert not any("accept: l4 yolo accept p1 openspec:b" in line for line in lines)
    assert sorted(asked) == ["openspec:a", "openspec:b"]
    assert not any("accept: l4" in line for line in render(events))
    assert "  accept: not available: b waits (push more)" in lines
    assert not any("not available" in line for line in render(events))


def test_a_ready_subject_and_an_accepted_one_get_no_accept_line():
    events = [reviewed("2026-10-14T10:00:00Z", {"openspec:a": entry("READY", material="k1")})]
    assert not any("accept: l4" in line for line in render(events, show_all=True, can_accept=lambda s: None))
    acc = {"openspec:a": {"by": "ana", "actor": "person", "reason": "r"}}
    lines = render(one([T]), accepted=acc, holds={"openspec:a": True}, can_accept=lambda s: None)
    assert not any("accept: l4" in line for line in lines)


def test_only_shows_one_subject_even_when_it_is_ready():
    events = [
        reviewed(
            "2026-10-14T10:00:00Z",
            {"openspec:a": entry("READY", material="k1"), "openspec:b": entry(findings=[F], material="k2")},
        )
    ]
    lines = render(events, only="openspec:a")
    assert lines == ["openspec:a: READY"]


def test_a_nothing_to_show_review_renders_no_lines():
    events = [reviewed("2026-10-14T10:00:00Z", {"openspec:a": entry("READY", material="k1")})]
    assert render(events) == []


def test_most_severe_puts_blocking_then_major_then_minor_in_the_judges_order():
    assert fnd.most_severe([X, T, B, F]) == B
    assert fnd.most_severe([X, T, F]) == T
    assert fnd.most_severe([X]) == X
    assert fnd.most_severe([]) is None


def test_scn_yolo_45_the_line_shown_is_the_most_severe_one():
    assert fnd.most_severe([X, T])["text"] == T["text"]  # the minor X comes first in the judge's order


def test_the_json_has_the_same_facts():
    events = [
        reviewed("2026-10-14T10:00:00Z", {"openspec:a": entry(digest="d1", findings=[T, F], material="k1")}),
        reviewed(
            "2026-10-14T11:00:00Z",
            {"openspec:a": entry(digest="d2", findings=[T, I, X], material="k2", assumptions=["a1"], missing=["m1"])},
        ),
    ]
    acc = {"openspec:a": {"by": "ana", "actor": "person", "reason": "go"}}
    latest = events[-1].data
    doc = fnd.render_json(
        "p1",
        "staging",
        latest,
        lambda s: fnd.history(events, s, 4),
        show_all=False,
        units=UNITS,
        accepted=acc,
        holds={"openspec:a": True},
        can_accept=lambda s: None,
    )
    json.dumps(doc)  # serialisable as it is
    assert doc["schema"] == "l4/yolo-findings@1" and doc["plan"] == "p1" and doc["base"] == "staging"
    [subj] = doc["subjects"]
    assert subj["subject"] == "openspec:a" and subj["verdict"] == "NEEDS_REVISION" and subj["material"] == "k2"
    assert [f["id"] for f in subj["findings"]] == [fnd.finding_id("openspec:a", f) for f in (T, I, X)]
    assert subj["findings"][0]["resolve"].startswith("Give the scenario")
    assert subj["findings"][2]["severity"] == "minor"
    assert subj["minor"] == 1 and subj["assumptions"] == ["a1"] and subj["missing"] == ["m1"]
    assert subj["since"]["new"] == 2 and subj["since"]["repeated"] == 1 and subj["since"]["gone"] == 1
    assert {"criterion": "interfaces", "severity": "major", "before": 0, "now": 1} in subj["since"]["by_criterion"]
    assert subj["persistent"] == {"testability": 2}
    assert subj["accepted"] == {"by": "ana", "actor": "person", "reason": "go", "holds": True, "why": None}
    assert subj["accept_available"] is False  # it already holds an acceptance


def test_the_json_without_a_previous_judgement_has_no_since():
    doc = fnd.render_json(
        "p1", "staging", one([T])[0].data, lambda s: fnd.history(one([T]), s, 4), show_all=False, units=UNITS
    )
    assert doc["subjects"][0]["since"] is None and doc["subjects"][0]["accepted"] is None
    assert doc["subjects"][0]["accept_available"] is False


def test_the_json_skips_ready_subjects_unless_all():
    ev1 = [reviewed("2026-10-14T10:00:00Z", {"openspec:a": entry("READY", material="k1")})]
    h = lambda s: fnd.history(ev1, s, 4)  # noqa: E731
    assert fnd.render_json("p1", "staging", ev1[0].data, h, show_all=False, units=UNITS)["subjects"] == []
    assert len(fnd.render_json("p1", "staging", ev1[0].data, h, show_all=True, units=UNITS)["subjects"]) == 1


def test_the_json_offers_accept_when_the_check_passes():
    events = one([T])
    h = lambda s: fnd.history(events, s, 4)  # noqa: E731
    doc = fnd.render_json("p1", "staging", events[0].data, h, units=UNITS, can_accept=lambda s: None)
    assert doc["subjects"][0]["accept_available"] is True


def test_the_json_carries_the_first_refusal_of_a_not_ready_subject():
    ev = [
        reviewed(
            "2026-10-14T10:00:00Z",
            {
                "openspec:a": entry(findings=[T], material="k1"),
                "openspec:b": entry(findings=[F], material="k2"),
                "openspec:c": entry("READY", material="k3"),
            },
        )
    ]
    refused = {"openspec:b": Refusal("acceptance is a person's decision", "a person runs it")}
    doc = fnd.render_json(
        "p1",
        "staging",
        ev[0].data,
        lambda s: fnd.history(ev, s, 4),
        show_all=True,
        units=UNITS,
        can_accept=lambda s: refused.get(s),
    )
    by = {x["subject"]: x for x in doc["subjects"]}
    assert by["openspec:a"]["accept_available"] is True and by["openspec:a"]["accept_refusal"] is None
    assert by["openspec:b"]["accept_available"] is False
    assert by["openspec:b"]["accept_refusal"] == {"why": "acceptance is a person's decision", "fix": "a person runs it"}
    assert by["openspec:c"]["accept_refusal"] is None  # READY: nothing to accept, nothing refused


def test_an_accepted_subject_that_holds_has_no_refusal():
    acc = {"openspec:a": {"by": "ana", "actor": "person", "reason": "r"}}
    ev = one([T])
    doc = fnd.render_json(
        "p1",
        "staging",
        ev[0].data,
        lambda s: fnd.history(ev, s, 4),
        units=UNITS,
        accepted=acc,
        holds={"openspec:a": True},
        can_accept=lambda s: Refusal("x", "y"),
    )
    assert doc["subjects"][0]["accept_refusal"] is None
