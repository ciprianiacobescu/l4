"""Findings: identifiers, the history of a subject, the round diff and the rounds not READY (review-resolution 1.5)."""

import hashlib
import json
from dataclasses import replace

from l4.yolo import findings as fnd

from .yolo_ledger_world import ev

T = {"criterion": "testability", "severity": "major", "text": "no tolerance for the time bound"}
F = {"criterion": "failure_cases", "severity": "major", "text": "no case for invalid input"}
I = {"criterion": "interfaces", "severity": "major", "text": "the helper signature is open"}  # noqa: E741
N = {"criterion": "outcome", "severity": "minor", "text": "a nit"}


def reviewed(at, units=None, batches=None, version=4, **extra):
    return replace(
        ev("plan.reviewed", plan_digest="p", prompt_version=version, units=units or {}, batches=batches or {}, **extra),
        at=at,
    )


def entry(verdict="NEEDS_REVISION", digest="d1", findings=(), **more):
    return {"verdict": verdict, "digest": digest, "findings": [dict(f) for f in findings], **more}


# --- identifiers ------------------------------------------------------------------------------------------------------


def test_finding_id_is_the_hash_of_subject_criterion_severity_text():
    want = hashlib.sha256(b"openspec:a\0testability\0major\0no tolerance for the time bound").hexdigest()[:6]
    assert fnd.finding_id("openspec:a", T) == f"F-{want}"
    assert fnd.finding_id("openspec:b", T) != fnd.finding_id("openspec:a", T)
    assert fnd.finding_id("openspec:a", {**T, "text": "other"}) != fnd.finding_id("openspec:a", T)


def test_findings_sha_is_canonical_json():
    a = [{"criterion": "x", "severity": "major", "text": "t"}]
    b = [{"text": "t", "severity": "major", "criterion": "x"}]
    want = hashlib.sha256(json.dumps(a, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]
    assert fnd.findings_sha(a) == fnd.findings_sha(b) == want and len(want) == 16
    assert fnd.findings_sha([]) != fnd.findings_sha(a)


# --- prior_entries ----------------------------------------------------------------------------------------------------


def test_prior_entries_keeps_the_newest_entry_per_material_key():
    events = [
        reviewed("2026-10-14T10:00:00Z", {"u": entry(digest="d1", findings=[T], material="k1")}),
        reviewed("2026-10-14T11:00:00Z", {"u": entry(digest="d2", findings=[F], material="k1")}),
        reviewed("2026-10-14T12:00:00Z", {"u": entry(digest="d3", findings=[I], material="k2")}),
    ]
    prior = fnd.prior_entries(events, 4)
    assert set(prior) == {"k1", "k2"}
    assert prior["k1"]["findings"] == [F] and prior["k1"]["at"] == "2026-10-14T11:00:00Z"
    assert prior["k2"]["verdict"] == "NEEDS_REVISION"


def test_prior_entries_ignores_other_prompt_versions_and_entries_without_material():
    events = [
        reviewed("2026-10-14T10:00:00Z", {"u": entry(material="k1")}, version=3),
        reviewed("2026-10-14T11:00:00Z", {"u": entry()}),
    ]
    assert fnd.prior_entries(events, 4) == {}


def test_prior_entries_never_returns_a_review_that_did_not_happen():
    for criterion in ("schema", "unit_missing", "completeness"):
        bad = {"criterion": criterion, "severity": "blocking", "text": "x"}
        events = [reviewed("2026-10-14T10:00:00Z", {"u": entry("BLOCKED", findings=[bad], material="k1")})]
        assert fnd.prior_entries(events, 4) == {}
    good = reviewed("2026-10-14T10:00:00Z", {"u": entry(findings=[T], material="k1")})
    bad = reviewed(
        "2026-10-14T11:00:00Z",
        {"u": entry("BLOCKED", findings=[{"criterion": "schema", "severity": "blocking", "text": "x"}], material="k1")},
    )
    assert fnd.prior_entries([good, bad], 4)["k1"]["at"] == "2026-10-14T10:00:00Z"  # the older real judgement stands


def test_prior_entries_of_a_reused_entry_point_at_the_original_judgement():
    events = [
        reviewed("2026-10-14T10:00:00Z", {"u": entry(material="k1")}),
        reviewed("2026-10-14T11:00:00Z", {"u": entry(material="k1", reused_from="2026-10-14T10:00:00Z")}),
    ]
    assert fnd.prior_entries(events, 4)["k1"]["at"] == "2026-10-14T10:00:00Z"


def test_prior_entries_reads_batches_under_their_own_name():
    events = [reviewed("2026-10-14T10:00:00Z", batches={"b1": entry(material="kb")})]
    assert set(fnd.prior_entries(events, 4)) == {"kb"}


# --- history ----------------------------------------------------------------------------------------------------------


def test_history_is_oldest_first_with_at_source_and_material():
    events = [
        reviewed("2026-10-14T10:00:00Z", {"u": entry(digest="d1", material="k1")}, source="local"),
        ev("plan.activated", plan_digest="p"),
        reviewed("2026-10-14T11:00:00Z", {"u": entry(digest="d2", material="k2"), "w": entry(material="kw")}),
        reviewed("2026-10-14T12:00:00Z", {"u": entry(digest="d2", material="k2", reused_from="2026-10-14T11:00:00Z")}),
    ]
    hist = fnd.history(events, "u", 4)
    assert [(h["at"], h["source"], h["material"]) for h in hist] == [
        ("2026-10-14T10:00:00Z", "local", "k1"),
        ("2026-10-14T11:00:00Z", "ci", "k2"),
        ("2026-10-14T12:00:00Z", "ci", "k2"),
    ]
    assert hist[2]["reused_from"] == "2026-10-14T11:00:00Z" and hist[0]["verdict"] == "NEEDS_REVISION"


def test_history_of_old_events_without_material_uses_the_unit_digest():
    events = [reviewed("2026-10-14T10:00:00Z", {"u": entry(digest="dig9")})]
    assert fnd.history(events, "u", 4)[0]["material"] == "dig9"


def test_history_of_a_batch_without_material_uses_the_event_time():
    events = [
        reviewed("2026-10-14T10:00:00Z", batches={"b1": entry()}),
        reviewed("2026-10-14T11:00:00Z", batches={"b1": entry(material="kb")}),
    ]
    hist = fnd.history(events, "batch:b1", 4)
    assert [h["material"] for h in hist] == ["2026-10-14T10:00:00Z", "kb"]
    assert fnd.history(events, "b1", 4) == []  # a unit named b1 is not the batch


def test_history_skips_other_prompt_versions():
    events = [reviewed("2026-10-14T10:00:00Z", {"u": entry(material="k1")}, version=3)]
    assert fnd.history(events, "u", 4) == []


def test_judged_drops_the_reused_entries_and_keeps_one_per_key():
    events = [
        reviewed("2026-10-14T10:00:00Z", {"u": entry(material="k1")}),
        reviewed("2026-10-14T11:00:00Z", {"u": entry(material="k1", reused_from="2026-10-14T10:00:00Z")}),
        reviewed("2026-10-14T12:00:00Z", {"u": entry(material="k2")}),
        reviewed("2026-10-14T13:00:00Z", {"u": entry(material="k1")}),  # re-asked (--fresh)
    ]
    judged = fnd.judged(fnd.history(events, "u", 4))
    assert [(j["material"], j["at"]) for j in judged] == [
        ("k2", "2026-10-14T12:00:00Z"),
        ("k1", "2026-10-14T13:00:00Z"),
    ]


# --- diff and persistent ----------------------------------------------------------------------------------------------


def test_diff_counts_new_repeated_and_gone():
    d = fnd.diff([T, F], [T, I])
    assert (len(d.new), len(d.repeated), len(d.gone)) == (1, 1, 1)
    assert d.new[0]["criterion"] == "interfaces" and d.gone[0]["criterion"] == "failure_cases"
    assert d.repeated[0]["criterion"] == "testability"


def test_diff_repeated_needs_the_same_criterion_severity_and_text():
    reworded = {**T, "text": "the time bound has no tolerance"}
    d = fnd.diff([T], [reworded])
    assert (len(d.new), len(d.repeated), len(d.gone)) == (1, 0, 1)
    assert fnd.diff([T], [{**T, "severity": "minor"}]).repeated == ()


def test_diff_by_criterion_counts_per_criterion_and_severity():
    reworded = {**T, "text": "the time bound has no tolerance"}
    d = fnd.diff([T, F], [reworded, I, N])
    assert d.by_criterion[("testability", "major")] == (1, 1)  # reworded: before 1, now 1
    assert d.by_criterion[("failure_cases", "major")] == (1, 0)
    assert d.by_criterion[("interfaces", "major")] == (0, 1)
    assert d.by_criterion[("outcome", "minor")] == (0, 1)


def test_diff_with_nothing_before_is_all_new():
    d = fnd.diff([], [T])
    assert (len(d.new), len(d.repeated), len(d.gone)) == (1, 0, 0)


def test_persistent_is_a_criterion_major_in_every_not_ready_judgement_at_least_twice():
    events = [
        reviewed("2026-10-14T10:00:00Z", {"u": entry(digest="d1", findings=[T, F], material="k1")}),
        reviewed("2026-10-14T11:00:00Z", {"u": entry(digest="d2", findings=[T, I], material="k2")}),
    ]
    assert fnd.persistent(fnd.judged(fnd.history(events, "u", 4))) == {"testability": 2}


def test_persistent_needs_two_judgements_and_ignores_minor_and_ready():
    one = [reviewed("2026-10-14T10:00:00Z", {"u": entry(findings=[T], material="k1")})]
    assert fnd.persistent(fnd.judged(fnd.history(one, "u", 4))) == {}
    minor_t = {**T, "severity": "minor"}
    events = [
        reviewed("2026-10-14T10:00:00Z", {"u": entry(findings=[T], material="k1")}),
        reviewed("2026-10-14T11:00:00Z", {"u": entry("READY", findings=[], material="k2")}),
        reviewed("2026-10-14T12:00:00Z", {"u": entry(findings=[T, N], material="k3")}),
        reviewed("2026-10-14T13:00:00Z", {"u": entry(findings=[minor_t], material="k4")}),
    ]
    assert fnd.persistent(fnd.judged(fnd.history(events, "u", 4))) == {}
    events = events[:3]
    assert fnd.persistent(fnd.judged(fnd.history(events, "u", 4))) == {
        "testability": 2
    }  # READY in between is not a judgement against


# --- rounds_not_ready -------------------------------------------------------------------------------------------------


def test_a_reused_entry_does_not_count_as_a_round():
    events = [
        reviewed("2026-10-14T10:00:00Z", {"u": entry(digest="d1", findings=[T], material="k1")}),
        reviewed(
            "2026-10-14T11:00:00Z",
            {"u": entry(digest="d1", findings=[T], material="k1", reused_from="2026-10-14T10:00:00Z")},
        ),
    ]
    assert fnd.rounds_not_ready(events, "u") == 1


def test_a_prerequisite_only_change_does_not_count_as_a_round():
    events = [
        reviewed("2026-10-14T10:00:00Z", {"u": entry(digest="d1", findings=[T], material="k1")}),
        reviewed(
            "2026-10-14T11:00:00Z", {"u": entry(digest="d1", findings=[T], material="k2")}
        ),  # the prerequisite changed
    ]
    assert fnd.rounds_not_ready(events, "u") == 1


def test_rounds_count_distinct_versions_across_prompt_versions():
    events = [
        reviewed("2026-10-14T10:00:00Z", {"u": entry(digest="d1", findings=[T], material="k1")}, version=3),
        reviewed("2026-10-14T11:00:00Z", {"u": entry(digest="d2", findings=[T], material="k2")}, version=4),
    ]
    assert fnd.rounds_not_ready(events, "u") == 2


def test_ready_judgements_and_reviews_that_did_not_happen_are_not_rounds():
    bad = {"criterion": "schema", "severity": "blocking", "text": "x"}
    events = [
        reviewed("2026-10-14T10:00:00Z", {"u": entry("READY", digest="d1")}),
        reviewed("2026-10-14T11:00:00Z", {"u": entry("BLOCKED", digest="d2", findings=[bad])}),
        reviewed("2026-10-14T12:00:00Z", {"u": entry("NEEDS_REVISION", digest="d3", findings=[T])}),
        reviewed(
            "2026-10-14T13:00:00Z", {"u": entry("BLOCKED", digest="d4", findings=[{**T, "severity": "blocking"}])}
        ),
    ]
    assert fnd.rounds_not_ready(events, "u") == 2  # d3 and d4; the harness BLOCKED d2 never happened


def test_old_events_without_material_still_count_by_digest():
    events = [
        reviewed("2026-10-14T10:00:00Z", {"u": entry(digest="d1", findings=[T])}, version=2),
        reviewed("2026-10-14T11:00:00Z", {"u": entry(digest="d2", findings=[T])}, version=2),
        reviewed("2026-10-14T12:00:00Z", {"u": entry(digest="d2", findings=[T])}, version=2),
    ]
    assert fnd.rounds_not_ready(events, "u") == 2


def test_a_batch_version_is_the_digests_of_its_units():
    events = [
        reviewed("2026-10-14T10:00:00Z", batches={"b1": entry(digests={"a": "da1", "b": "db1"}, findings=[T])}),
        reviewed(
            "2026-10-14T11:00:00Z", batches={"b1": entry(digests={"b": "db1", "a": "da1"}, findings=[T])}
        ),  # same versions
        reviewed("2026-10-14T12:00:00Z", batches={"b1": entry(digests={"a": "da2", "b": "db1"}, findings=[T])}),
    ]
    assert fnd.rounds_not_ready(events, "batch:b1") == 2


def test_an_old_batch_entry_uses_the_unit_digests_of_its_event():
    units1 = {"a": entry("READY", digest="da1"), "b": entry("READY", digest="db1")}
    units2 = {"a": entry("READY", digest="da2"), "b": entry("READY", digest="db1")}
    events = [
        reviewed("2026-10-14T10:00:00Z", units1, {"b1": entry(findings=[T])}),
        reviewed("2026-10-14T11:00:00Z", units1, {"b1": entry(findings=[T])}),
        reviewed("2026-10-14T12:00:00Z", units2, {"b1": entry(findings=[T])}),
    ]
    assert fnd.rounds_not_ready(events, "batch:b1") == 2


def test_rounds_of_a_subject_with_no_review_is_zero():
    assert fnd.rounds_not_ready([], "u") == 0
    assert fnd.rounds_not_ready([ev("plan.activated")], "u") == 0
