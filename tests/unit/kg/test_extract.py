"""`kg.extract`: the records of `collect` as nodes and edges (L4-KG-005, L4-KG-011, SCN-KG-10, SCN-KG-11, SCN-KG-12,
SCN-KG-13, SCN-KG-14, SCN-KG-15, SCN-KG-22 index part)."""

import json
import re

import pytest

from l4.kg import extract as extract_module
from l4.kg.extract import Extracted, extract, slug
from l4.kg.model import Edge, jsonl_bytes
from l4.kg.sources import collect
from l4.memory.curate import UI_GAP_KEY, UI_GAP_TITLE
from l4.redact import Redactor


def build(kg_repo, redactor: Redactor | None = None, *, git: bool = True) -> Extracted:
    found = collect(kg_repo.recording_git(), kg_repo.cfg)
    return extract(found, redactor or Redactor({}), git=kg_repo.recording_git() if git else None)


def edges(out: Extracted, type: str) -> list[Edge]:
    return sorted((e for e in out.edges if e.type == type), key=lambda e: (e.from_id, e.to_id, e.src))


def nodes_of(out: Extracted, type: str) -> set[str]:
    return {n.id for n in out.nodes if n.type == type}


def attrs_of(out: Extracted, node_id: str) -> dict:
    return dict(next(n for n in out.nodes if n.id == node_id).attrs)


REASON = "no new test traces C-e25f06d8: x"


def two_runs(kg_repo, *extra):
    return [kg_repo.run(("task.red_ok", {"task": "1.1"}), *extra)]


# --- 4.1: ledger edges ---------------------------------------------------------------------------------------------


def ledger_unit(kg_repo, **kw):
    restart = kg_repo.restart_event("openspec:a", 1, reason="stuck")
    run = kg_repo.run(
        ("availability.selected", {"role": "implementer", "selected": "codex-fast"}),
        ("prompt.rendered", {"role": "red", "task": "1.1", "lessons": ["L-09421538", "L-0000aaaa"]}),
        (
            "task.attempt_failed",
            {
                "task": "1.1",
                "phase": "red",
                "attempt": 1,
                "reason": "no new test traces C-e25f06d8: tag your test with the criterion id",
            },
        ),
        ("question.raised", {"id": "Q-001", "kind": "product", "source": "intake_open_questions", "title": "Which?"}),
        ("question.answered", {"id": "Q-001", "by": "human"}),
        ("phase.changed", {"from": "implementing", "to": "escalated", "reason": "same_failure", "detail": "x failed"}),
        ("unit.retried", {"reason": "spec edited", "by": "push"}),
        restart,
        ("verify.verdict", {"round": 1, "verdict": "FAIL"}),
        ("guard.test_tamper", {"path": "tests/a.py", "phase": "single"}),
        ("guard.secret", {"path": ".env", "kind": "token"}),
        ("gate.hung", {"task": "1.1", "tests": [], "attempt": 1}),
    )
    kg_repo.unit("openspec:a", where="branch", runs=[run], **kw)


def test_ledger_events_become_edges(kg_repo):
    ledger_unit(kg_repo)
    out = build(kg_repo)
    run = next(iter(nodes_of(out, "run")))
    assert run.startswith("r-")
    assert nodes_of(out, "unit") == {"openspec:a"}
    assert nodes_of(out, "attempt") >= {"openspec:a@0", "openspec:a@1"}
    assert [(e.from_id, e.to_id) for e in edges(out, "HAS_ATTEMPT")] == [("openspec:a", "openspec:a@0")]
    assert [(e.from_id, e.to_id) for e in edges(out, "HAS_RUN")] == [("openspec:a@0", run)]
    assert {"start", "end", "exit_code"} <= set(attrs_of(out, run))

    (used,) = edges(out, "USED_PROFILE")
    assert (used.from_id, used.to_id, dict(used.attrs)) == (run, "profile:codex-fast", {"role": "implementer"})

    injected = edges(out, "INJECTED")
    assert [(e.to_id, e.attrs["task"], e.attrs["role"]) for e in injected] == [
        ("L-0000aaaa", "1.1", "red"), ("L-09421538", "1.1", "red"),
    ]  # fmt: skip
    assert nodes_of(out, "lesson") == {"L-0000aaaa", "L-09421538"}

    (failed,) = edges(out, "ATTEMPT_FAILED")
    assert failed.to_id == "failure:no new test traces <criterion>"
    assert (failed.attrs["task"], failed.attrs["phase"], failed.attrs["attempt"]) == ("1.1", "red", 1)
    assert failed.attrs["seq"] > injected[0].attrs["seq"]

    (asked,) = edges(out, "ASKED")
    assert asked.to_id == "openspec:a#Q-001"
    assert dict(asked.attrs) == {"kind": "product", "source": "intake_open_questions", "answered_by": "human"}
    assert "Which?" not in jsonl_bytes([*out.nodes, *out.edges]).decode()  # question text is never stored

    (stopped,) = edges(out, "STOPPED")
    assert (stopped.to_id, dict(stopped.attrs)) == ("stop:same_failure", {"phase": "escalated", "detail": "x failed"})
    (retried,) = edges(out, "RETRIED")
    assert (retried.to_id, retried.attrs["reason"]) == ("openspec:a@0", "spec edited")
    (restarted,) = edges(out, "RESTARTED")
    assert (restarted.to_id, dict(restarted.attrs)) == ("openspec:a@1", {"attempt": 1, "reason": "stuck"})
    (verdict,) = edges(out, "VERDICT")
    assert (verdict.to_id, verdict.attrs["verdict"]) == ("openspec:a@0#round-1", "FAIL")


def test_blame_edges_of_events(kg_repo):
    """4.4 in the graph: the table's value for every kind of record, from the run or the record."""
    ledger_unit(kg_repo)
    out = build(kg_repo)
    by_of = {e.attrs["of"]: e.to_id for e in edges(out, "CLASSIFIED") if "seq" in e.attrs}
    assert by_of == {
        "task.attempt_failed": "blame:agent", "stop": "blame:unknown", "guard.test_tamper": "blame:agent",
        "guard.secret": "blame:security", "gate.hung": "blame:environment",
    }  # fmt: skip
    (question,) = [e for e in edges(out, "CLASSIFIED") if e.attrs["of"] == "question"]
    assert (question.from_id, question.to_id) == ("openspec:a#Q-001", "blame:spec")
    tamper = next(e for e in edges(out, "CLASSIFIED") if e.attrs["of"] == "guard.test_tamper")
    assert tamper.attrs["rule"] == "frozen test"  # propose pattern (c) counts the rule name


def test_classified_shares_the_src_of_the_edge_it_classifies(kg_repo):
    ledger_unit(kg_repo)
    out = build(kg_repo)
    failed = edges(out, "ATTEMPT_FAILED")[0]
    classified = next(e for e in edges(out, "CLASSIFIED") if e.attrs["of"] == "task.attempt_failed")
    assert (classified.src, classified.ts) == (failed.src, failed.ts)


def test_a_restart_keeps_the_old_attempt_as_its_own_node(kg_repo):
    """SCN-KG-07 in the graph: attempt 1 and attempt 0 have their own runs."""
    old = kg_repo.run(("task.attempt_failed", {"task": "1.1", "phase": "red", "attempt": 1, "reason": "boom: x"}))
    new = kg_repo.run(kg_repo.restart_event("openspec:a", 1))
    kg_repo.unit("openspec:a", where="attempt:1", runs=[old])
    kg_repo.unit("openspec:a", where="branch", runs=[new])
    out = build(kg_repo)
    has_run = {(e.from_id): e.to_id for e in edges(out, "HAS_RUN")}
    assert set(has_run) == {"openspec:a@0", "openspec:a@1"}
    assert has_run["openspec:a@0"] != has_run["openspec:a@1"]
    assert [(e.from_id, e.to_id) for e in edges(out, "RESTARTED")] == [(has_run["openspec:a@0"], "openspec:a@1")]
    (failed,) = edges(out, "ATTEMPT_FAILED")
    assert failed.from_id == has_run["openspec:a@1"]


# --- 4.2: verdict edges --------------------------------------------------------------------------------------------


def cart_verdicts(kg_repo, title="UI criterion without an end-to-end test", alias="cart › Cart › Shows count", **kw):
    crit = kg_repo.criterion(alias)
    finding = kg_repo.finding(title, criterion=crit.id, **kw)
    gate = kg_repo.gate("lint")
    return (
        [
            kg_repo.verdict(
                1,
                "FAIL",
                findings=[finding],
                criteria=[crit],
                gates=[gate, kg_repo.gate("unit", status="pass")],
                judge_profile="judge-a",
                implementer_profiles=["impl-a"],
            )
        ],
        finding,
        crit,
    )


def test_verdict_json_edges(kg_repo):
    verdicts, finding, crit = cart_verdicts(kg_repo)
    kg_repo.unit("openspec:a", where="base", verdicts=verdicts)
    out = build(kg_repo)
    rnd = "openspec:a@0#round-1"
    assert nodes_of(out, "round") == {rnd}
    (has_round,) = edges(out, "HAS_ROUND")
    assert (has_round.from_id, has_round.to_id) == ("openspec:a@0", rnd)
    assert has_round.attrs["verdict"] == "FAIL"
    assert (has_round.attrs["judge"], has_round.attrs["implementer"]) == ("judge-a", ["impl-a"])
    assert has_round.attrs["files_unknown"] is True  # the fixture's shas are not commits
    assert out.skipped["files_unknown"] == 1

    (raised,) = edges(out, "RAISED")
    assert (raised.from_id, raised.to_id) == (rnd, finding.id)
    assert dict(raised.attrs) == {"severity": "major", "source": "deterministic", "spec_gap": False}
    assert attrs_of(out, finding.id) == {"title": finding.title}
    (about,) = edges(out, "ABOUT")
    assert (about.from_id, about.to_id) == (finding.id, f"openspec:a#{crit.id}")
    (keyed,) = edges(out, "KEYED")
    assert keyed.to_id == "recurrence:ui criterion without an end-to-end test | cart › shows count"
    (cap,) = edges(out, "IN_CAPABILITY")
    assert (cap.from_id, cap.to_id) == (f"openspec:a#{crit.id}", "cap:cart")
    (gate,) = edges(out, "GATE_FAILED")
    assert (gate.from_id, gate.to_id) == (rnd, "gate:lint")


def test_a_kiro_unit_is_its_own_capability_and_has_an_empty_criterion_part(kg_repo):
    crit = kg_repo.criterion("Req 1.1")
    finding = kg_repo.finding("Missing test", criterion=crit.id)
    kg_repo.unit("kiro:k", where="base", verdicts=[kg_repo.verdict(1, findings=[finding], criteria=[crit])])
    out = build(kg_repo)
    assert [e.to_id for e in edges(out, "IN_CAPABILITY")] == ["cap:k"]
    assert [e.to_id for e in edges(out, "KEYED")] == ["recurrence:missing test | "]


def test_the_same_mistake_in_two_units_is_one_key_and_other_scenarios_are_not(kg_repo):
    """SCN-KG-12 and SCN-KG-13: the key drops the capability part, keeps the scenario."""
    for unit, capability, scenario in (
        ("a", "cart", "Shows count"),
        ("b", "basket", "Shows count"),
        ("c", "x", "Clears"),
    ):
        verdicts, *_ = cart_verdicts(kg_repo, alias=f"{capability} › Cart › {scenario}")
        kg_repo.unit(f"openspec:{unit}", where="base", verdicts=verdicts, capability=capability)
    out = build(kg_repo)
    keyed = {e.from_id: e.to_id for e in edges(out, "KEYED")}
    keys = sorted(set(keyed.values()))
    assert len(keys) == 2
    counts = sorted(sum(1 for t in keyed.values() if t == key) for key in keys)
    assert counts == [1, 2]
    assert nodes_of(out, "capability") == {"cap:cart", "cap:basket", "cap:x"}


def test_blame_of_findings_and_rounds(kg_repo):
    """SCN-KG-14, SCN-KG-15."""
    crit = kg_repo.criterion("cart › Cart › Shows count")
    gap = kg_repo.finding("Unclear behaviour", criterion=crit.id, spec_gap=True, source="judge")
    judge = kg_repo.finding("Edge case not handled", source="judge")
    kg_repo.unit(
        "openspec:a", where="base", verdicts=[kg_repo.verdict(1, "NEEDS_HUMAN", findings=[gap, judge], criteria=[crit])]
    )
    out = build(kg_repo)
    blame = {e.from_id: e.to_id for e in edges(out, "CLASSIFIED")}
    assert blame[gap.id] == "blame:spec"
    assert blame[judge.id] == "blame:unknown"
    assert blame["openspec:a@0#round-1"] == "blame:spec"


def test_changed_files_of_a_round_when_both_commits_are_local(kg_repo):
    base = kg_repo.commit("main", {"src/a.py": "1\n"}, "base")
    head = kg_repo.commit("work", {"src/b.py": "2\n", "src/web/c.py": "3\n"}, "head")
    raw = json.dumps({
        "schema": "l4/verdict@1", "round": 1, "verdict": "FAIL", "base_sha": base, "head_sha": head,
        "findings": [], "criteria": [], "gates": [], "profiles": {"judge": "j", "implementer": []},
    }).encode()  # fmt: skip
    kg_repo.unit("openspec:a", where="base", verdicts=[kg_repo.verdict(1, raw=raw)])
    out = build(kg_repo)
    (has_round,) = edges(out, "HAS_ROUND")
    assert has_round.attrs["files"] == ["src/b.py", "src/web/c.py"]
    assert "files_unknown" not in has_round.attrs
    assert "files_unknown" not in out.skipped


def test_without_a_git_handle_no_round_has_files(kg_repo):
    verdicts, *_ = cart_verdicts(kg_repo)
    kg_repo.unit("openspec:a", where="base", verdicts=verdicts)
    out = build(kg_repo, git=False)
    assert edges(out, "HAS_ROUND")[0].attrs["files_unknown"] is True


# --- SCN-KG-10: every src resolves ---------------------------------------------------------------------------------


def resolve(kg_repo, src: str):
    where, _, tail = src.partition("#")
    sha, _, path = where.partition(":")
    kg_repo.git.run("cat-file", "-e", f"{sha}:{path}")
    return kg_repo.git.run_bytes("cat-file", "blob", f"{sha}:{path}"), tail


def test_every_src_resolves_and_holds_what_the_edge_states(kg_repo):
    verdicts, finding, _ = cart_verdicts(kg_repo)
    kg_repo.unit("openspec:a", where="archive", runs=two_runs(kg_repo), verdicts=verdicts)
    ledger_unit(kg_repo)
    out = build(kg_repo)
    checked = 0
    for edge in out.edges:
        if edge.type == "HAS_ATTEMPT" and not edge.src.split(":", 1)[1]:
            continue
        blob, tail = resolve(kg_repo, edge.src)
        if tail.startswith("/"):
            value = json.loads(blob)
            for part in tail[1:].split("/"):
                value = value[int(part)] if isinstance(value, list) else value[part]
            assert value is not None
            if edge.type == "RAISED":
                assert value["id"] == edge.to_id
            if edge.type == "KEYED":
                assert value == finding.title
        else:
            line = next(json.loads(x) for x in blob.decode().splitlines() if json.loads(x)["seq"] == int(tail))
            assert line["ts"].startswith("20")
            assert edge.ts == line["ts"]
            assert re.fullmatch(r"r-\d{8}T\d{4}Z-[0-9a-f]{4}", line["run_id"])
        checked += 1
    assert checked > 10


# --- 4.3: the lesson link ------------------------------------------------------------------------------------------


def test_lesson_links_by_dedupe_key_only(kg_repo):
    """SCN-KG-11: a Source line naming a finding is no link; a rule key and a kg key are."""
    verdicts, finding, crit = cart_verdicts(kg_repo, title=UI_GAP_TITLE)
    kg_repo.unit("openspec:a", where="base", verdicts=verdicts, runs=[
        kg_repo.run(("task.attempt_failed", {"task": "1.1", "phase": "red", "attempt": 1, "reason": REASON}))
    ])  # fmt: skip
    rule = kg_repo.lesson("UI needs e2e", UI_GAP_KEY, source=f"verifier finding {finding.id} (openspec:a round 1)")
    manual = kg_repo.lesson(
        "Hand written", "hand-written", source=f"verifier finding {finding.id} (openspec:a round 1)"
    )
    proposed_a = kg_repo.lesson("Red failure", "kg-a-no-new-test-traces-criterion")
    proposed_b = kg_repo.lesson(
        "Finding", "kg-b-" + slug("ui criterion without an end-to-end test | cart › shows count")
    )
    gone = kg_repo.lesson("Other", "kg-a-nothing-like-it")
    kg_repo.lessons(rule, manual, proposed_a, proposed_b, gone)
    out = build(kg_repo)
    links = {}
    for e in edges(out, "KEYED"):
        if e.from_id.startswith("L-"):
            links.setdefault(e.from_id, set()).add(e.to_id)
    key = "recurrence:ui criterion without an end-to-end test | cart › shows count"
    assert links == {
        rule.id: {key},
        proposed_a.id: {"failure:no new test traces <criterion>"},
        proposed_b.id: {key},
    }
    assert manual.id not in links and gone.id not in links
    assert finding.id not in {e.to_id for e in edges(out, "KEYED") if e.from_id.startswith("L-")}
    assert attrs_of(out, rule.id)["dedupe_key"] == UI_GAP_KEY


def test_a_rule_lesson_with_no_finding_seen_links_to_the_bare_key(kg_repo):
    kg_repo.lessons(kg_repo.lesson("UI needs e2e", UI_GAP_KEY))
    out = build(kg_repo)
    (link,) = [e for e in edges(out, "KEYED") if e.from_id.startswith("L-")]
    assert link.to_id == "recurrence:ui criterion without an end-to-end test | "
    assert link.to_id in nodes_of(out, "recurrence_key")


def test_an_injected_lesson_in_the_file_is_one_node_with_its_attrs(kg_repo):
    lesson = kg_repo.lesson("Use the helper", "use-helper", scope=("src/web/**",))
    kg_repo.lessons(lesson)
    kg_repo.unit("openspec:a", where="base", runs=[
        kg_repo.run(("prompt.rendered", {"role": "green", "task": "1.1", "lessons": [lesson.id]}))
    ])  # fmt: skip
    out = build(kg_repo)
    assert [n.id for n in out.nodes if n.type == "lesson"] == [lesson.id]
    assert attrs_of(out, lesson.id) == {
        "title": "Use the helper", "dedupe_key": "use-helper", "scope": ["src/web/**"],
        "archived": False, "reinforced": 1,
    }  # fmt: skip


# --- 4.5: redaction ------------------------------------------------------------------------------------------------


class Scrubbing:
    def scrub(self, text: str) -> str:
        return text.replace("git.example.test", "<forge>")


def test_secrets_and_the_forge_host_never_enter_the_index(kg_repo):
    """SCN-KG-22 (the index part)."""
    secret = "s3cr3t-token-value-9"
    redactor = Redactor({"FORGE_TOKEN": secret})
    redactor.forge_urls = Scrubbing()
    kg_repo.unit("openspec:a", where="branch", runs=[kg_repo.run(
        ("task.attempt_failed", {"task": "1.1", "phase": "red", "attempt": 1,
                                 "reason": f"login with {secret} failed at https://git.example.test/x"}),
        ("phase.changed", {"to": "halted", "reason": "baseline_failed", "detail": f"{secret} on git.example.test"}),
        ("question.raised", {"id": "Q-001", "kind": "product"}),
    )])  # fmt: skip
    crit = kg_repo.criterion("cart › Cart › Shows count")
    kg_repo.unit("openspec:b", where="base", verdicts=[kg_repo.verdict(1, findings=[
        kg_repo.finding(f"Leaks {secret}", criterion=crit.id)
    ], criteria=[crit])])  # fmt: skip
    out = build(kg_repo, redactor)
    text = jsonl_bytes([*out.nodes, *out.edges]).decode()
    assert secret not in text
    assert "git.example.test" not in text
    assert "[REDACTED:FORGE_TOKEN]" in text
    assert "<forge>" in text


# --- containment and determinism -----------------------------------------------------------------------------------


def test_the_same_input_gives_the_same_bytes_in_any_order(kg_repo):
    verdicts, *_ = cart_verdicts(kg_repo)
    kg_repo.unit("openspec:a", where="archive", verdicts=verdicts, runs=two_runs(kg_repo))
    ledger_unit(kg_repo)
    kg_repo.lessons(kg_repo.lesson("UI needs e2e", UI_GAP_KEY))
    found = collect(kg_repo.recording_git(), kg_repo.cfg)
    first = extract(found, Redactor({}))
    found.units.reverse()
    found.lessons.reverse()
    second = extract(found, Redactor({}))
    assert jsonl_bytes(first.nodes) == jsonl_bytes(second.nodes)
    assert jsonl_bytes(first.edges) == jsonl_bytes(second.edges)
    assert len(first.nodes) > 10


def test_an_error_in_one_unit_skips_that_unit(kg_repo, monkeypatch):
    kg_repo.unit("openspec:a", where="base", runs=two_runs(kg_repo))
    kg_repo.unit("openspec:b", where="base", runs=two_runs(kg_repo))
    real = extract_module._Extractor.record

    def broken(self, g, rec):
        if rec.unit_id == "openspec:a":
            raise KeyError("boom")
        real(self, g, rec)

    monkeypatch.setattr(extract_module._Extractor, "record", broken)
    out = build(kg_repo)
    assert nodes_of(out, "unit") == {"openspec:b"}
    assert out.skipped["error"] == 1
    assert any("openspec:a" in w for w in out.warnings)


def test_collected_skips_are_carried_and_the_input_is_unchanged(kg_repo):
    kg_repo.unit("openspec:a", where="base", runs=two_runs(kg_repo), files={
        "openspec/changes/a/.l4/evidence/round-1/verdict.json": b"not json"
    })  # fmt: skip
    found = collect(kg_repo.recording_git(), kg_repo.cfg)
    before = dict(found.skipped)
    out = extract(found, Redactor({}))
    assert found.skipped == before
    assert out.skipped == dict(sorted(before.items()))
    assert out.skipped.get("verdict_unreadable") == 1


@pytest.mark.parametrize("text", ["No new test traces!", "a/b c", "x | y › z", "  "])
def test_slug_is_lowercase_dash_separated(text):
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*|", slug(text))
