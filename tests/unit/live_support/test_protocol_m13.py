from ...live.protocol_m13 import branch_of_step_1, handed_off, of_type, parent_events, tdd_of, unit_checkpoints

UNIT = "openspec:add-shipping-fee"


def commit(title: str, **trailers: str) -> dict:
    body = "\n".join(f"{k.replace('_', '-')}: {v}" for k, v in trailers.items())
    return {"id": title[:8], "title": title, "message": f"{title}\n\n{body}\n" if body else f"{title}\n"}


# The unit branch lists main's history too: add-discount-codes was merged into main with its own task 1.1 red and green
# (live M1.3 retry, job 5480), and the operator's harness upgrade on main carries `[skip ci]` but no L4-Unit.
HISTORY = [
    commit("chore(add-shipping-fee): ledger [skip ci]", L4_Unit=UNIT, L4_Phase="awaiting_human"),
    commit("feat(add-shipping-fee): 1.1 Add shipping [skip ci]", L4_Unit=UNIT, L4_Task="1.1", L4_TDD="green"),
    commit("test(add-shipping-fee): red for 1.1 [skip ci]", L4_Unit=UNIT, L4_Task="1.1", L4_TDD="red"),
    commit(
        "test(add-shipping-fee-fix-1): 1.1 already satisfied [skip ci]",
        L4_Unit=f"{UNIT}-fix-1",
        L4_Task="1.1",
        L4_TDD="already-satisfied",
    ),
    commit("Upgrade the vendored L4 harness to f0f6524 (M1.3 live-fixes) [skip ci]"),
    commit(
        "feat(add-discount-codes): 1.1 Add codes", L4_Unit="openspec:add-discount-codes", L4_Task="1.1", L4_TDD="green"
    ),
    commit("test(add-discount-codes): red for 1.1", L4_Unit="openspec:add-discount-codes", L4_Task="1.1", L4_TDD="red"),
]


def test_tdd_of_reads_only_the_commits_of_the_unit_and_task():
    assert tdd_of(HISTORY, UNIT, "1.1") == ["green", "red"]
    assert tdd_of(HISTORY, f"{UNIT}-fix-1", "1.1") == ["already-satisfied"]


def test_the_checkpoints_are_the_harness_skip_ci_commits_of_the_unit_and_its_fix_units_only():
    titles = [c["title"] for c in unit_checkpoints(HISTORY, UNIT)]
    assert titles == [HISTORY[0]["title"], HISTORY[1]["title"], HISTORY[2]["title"], HISTORY[3]["title"]]


def test_of_type_filters_on_a_field_named_kind():
    events = [{"type": "question.raised", "kind": "verdict", "id": "Q-001"}, {"type": "question.raised", "kind": "x"}]
    assert of_type(events, "question.raised", kind="verdict") == [events[0]]


def test_a_unit_is_handed_off_once_a_phase_change_reaches_in_review_or_the_hand_off_commit_exists():
    labels_only = [{"type": "pr.updated", "labels": ["l4:awaiting_human"]}]
    assert not handed_off(labels_only, HISTORY, "add-shipping-fee")
    assert handed_off(labels_only + [{"type": "phase.changed", "from": "verified", "to": "in_review"}], [], "x")
    # the run that hands off writes its tail (with the `in_review` change) to the lock ref, which the API cannot read
    hand_off = commit("docs(add-shipping-fee): hand off to review", L4_Unit=UNIT, L4_Phase="verified")
    assert handed_off(labels_only, [hand_off, *HISTORY], "add-shipping-fee")


def test_the_parents_events_leave_out_those_of_its_fix_units():
    # a fix unit's task 1.1 writes `task.red_ok{task: "1.1", fix_unit: ...}` into the parent's ledger (live job 5482)
    events = [
        {"type": "task.red_ok", "task": "1.1", "criteria": {"C-1": {}, "C-2": {}}},
        {"type": "task.red_ok", "task": "1.1", "fix_unit": "add-shipping-fee-fix-1", "criteria": {"C-3": {}}},
    ]
    assert parent_events(events) == [events[0]]


def test_branch_of_step_1_is_read_from_the_round_1_verdict():
    def verdict(round_no: int, value: str) -> dict:
        return {"type": "verify.verdict", "round": round_no, "verdict": value}

    assert branch_of_step_1([]) is None
    assert branch_of_step_1([verdict(1, "PASS"), verdict(2, "PASS")]) == "1A"
    # 1B: round 1 NEEDS_HUMAN, then the answers spawn the fix unit too, so `fix.spawned` alone does not tell 1A from 1B
    later = [verdict(1, "NEEDS_HUMAN"), verdict(2, "FAIL"), {"type": "fix.spawned"}, verdict(3, "PASS")]
    assert branch_of_step_1(later) == "1B"
    assert branch_of_step_1([verdict(1, "FAIL")]) is None
