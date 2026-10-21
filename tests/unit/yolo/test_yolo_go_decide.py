"""`l4 yolo go` (L4-YOLO-080, -083 to -086): the pure decision, one rule per test in the order of design D5 to D8."""

from l4.yolo.go import Active, Do, Facts, Flags, GoStop, Stop, decide

PERSON = ("person", None)
AGENT = ("agent", "CLAUDECODE")
OPEN = "acceptance is a person's decision"


def flags(**over) -> Flags:
    base = {
        "reason": "R", "accept_findings": False, "force": False, "yes": False, "as_json": False, "no_push": False,
        "local": False, "wait": "30m", "wait_s": 1800,
    }  # fmt: skip
    base.update(over)
    return Flags(**base)


def facts(**over) -> Facts:
    """A person, a new plan, admitted, a current review and nothing to accept."""
    base = {
        "plan": "p1", "actor": PERSON, "flags": flags(), "status": "new", "review_kind": "current",
    }  # fmt: skip
    flag_over = {k: over.pop(k) for k in list(over) if k in Flags.__dataclass_fields__ and k != "reason"}
    base.update(over)
    if flag_over:
        base["flags"] = flags(**flag_over)
    return Facts(**base)


# --- D5: the plan's state, then admission -----------------------------------------------------------------------------


def test_active_and_waiting_are_active_before_admission():
    broken = {"admission": ("cycle: a -> b -> a",), "plan_valid": False, "plan_found": False}
    active = decide(
        facts(status="active", activated_by="alex@example.com", activated_at="2026-10-14T10:00:00Z", **broken)
    )
    assert active == Active("active since 2026-10-14T10:00:00Z by alex@example.com", "l4 yolo status p1")
    waiting = decide(facts(status="waiting", stop_reason="run_not_started", **broken))
    assert waiting == Active("waiting: run_not_started", "l4 yolo status p1")


def test_completed_is_active_with_the_report():
    assert decide(facts(status="completed")) == Active("completed", "l4 yolo report p1")


def test_cancelled_and_other_stops_are_plan_state():
    text = "none: the plan is cancelled"
    assert decide(facts(status="cancelled", status_next=text)) == Stop(
        GoStop.PLAN_STATE, "check", "stopped", text, "l4 yolo status p1"
    )
    for reason in ("limit_runs", "unit_halted"):
        stop = decide(facts(status="stopped", stop_reason=reason, status_next="l4 yolo resume p1 --reason TEXT"))
        assert isinstance(stop, Stop) and stop.code == GoStop.PLAN_STATE and stop.step == "check"
        assert stop.detail == "l4 yolo resume p1 --reason TEXT" and stop.next_command == "l4 yolo status p1"
    changed = decide(facts(status="stopped", stop_reason="inputs_changed"))
    assert not isinstance(changed, Stop)  # a review can still be made: the way on is a new review


def test_a_rejected_unit_with_an_unchanged_spec_is_plan_state():
    same = decide(facts(status="stopped", stop_reason="unit_rejected", rejected_unchanged=True, status_next="fix it"))
    assert isinstance(same, Stop) and same.code == GoStop.PLAN_STATE and same.detail == "fix it"
    fixed = decide(facts(status="stopped", stop_reason="unit_rejected", rejected_unchanged=False))
    assert not isinstance(fixed, Stop)


def test_no_file_an_invalid_file_and_findings_are_not_admitted():
    for over in (
        {"plan_found": False, "admission": ("check: no plan file .l4/plans/p1.json on origin/main",)},
        {"plan_valid": False, "admission": ("schema: not a plan",)},
        {"admission": ("cycle: a -> b -> a",)},
    ):
        stop = decide(facts(**over))
        assert stop == Stop(
            GoStop.NOT_ADMITTED, "check", "stopped", "\n".join(over["admission"]), "l4 yolo check p1 --worktree"
        )


# --- D6: the review ------------------------------------------------------------------------------------------------


def test_covered_skips_the_review():
    action = decide(facts(review_kind="none", covered=True))
    assert action == Do("activate")


def test_force_without_a_current_review_force_accepts():
    assert decide(facts(review_kind="none", force=True)) == Do("force_accept")
    assert decide(facts(review_kind="stale", force=True)) == Do("force_accept")
    assert decide(facts(review_kind="none", force=True, covered=True)) == Do("activate")
    assert decide(facts(review_kind="current", force=True)) == Do("activate")  # READY: nothing to force
    with_problem = decide(facts(review_kind="current", force=True, problems=("openspec:b: NEEDS_REVISION: x",)))
    assert with_problem == Do("force_accept")


def test_local_reviews_here():
    assert decide(facts(review_kind="none", local=True)) == Do("review_local")
    assert decide(facts(review_kind="stale", local=True)) == Do("review_local")
    assert decide(facts(review_kind="current", local=True)) == Do("activate")


def test_ci_is_asked_then_pending_after_the_wait():
    assert decide(facts(review_kind="none")) == Do("review_ci")
    assert decide(facts(review_kind="stale")) == Do("review_ci")
    pending = decide(facts(review_kind="none", asked=True, waited_out=True, review_detail="CI was asked (started)"))
    assert pending == Stop(
        GoStop.REVIEW_PENDING, "review", "pending",
        "CI was asked (started); no review recorded within 30m", "l4 yolo go p1 --reason R",
    )  # fmt: skip
    short = decide(facts(review_kind="none", asked=True, waited_out=True, wait="1m", wait_s=60))
    assert isinstance(short, Stop) and short.next_command == "l4 yolo go p1 --reason R --wait 1m"
    assert short.detail == "no review recorded within 1m"
    assert decide(facts(review_kind="none", asked=True)) == Do("review_ci")  # not waited out: the wait goes on


def test_a_refusal_after_the_ask_is_not_admitted():
    stop = decide(facts(review_kind="none", asked=True, refused_after_ask=True, review_detail="open_questions: B asks"))
    assert stop == Stop(
        GoStop.NOT_ADMITTED, "review", "stopped", "open_questions: B asks", "l4 yolo check p1 --worktree"
    )


# --- D7: findings and acceptance -----------------------------------------------------------------------------------

B_LINE = "openspec:add-b: NEEDS_REVISION: testability: no scenario"


def test_problems_without_a_flag_stop_at_findings():
    stop = decide(
        facts(problems=(B_LINE,), refusals={"openspec:add-b": None}, person_refusals={"openspec:add-b": None})
    )
    assert stop == Stop(GoStop.FINDINGS, "findings", "stopped", B_LINE, "l4 yolo go p1 --reason R --accept-findings")
    agent = decide(
        facts(
            actor=AGENT, problems=(B_LINE,), refusals={"openspec:add-b": None}, person_refusals={"openspec:add-b": None}
        )
    )
    assert isinstance(agent, Stop) and agent.next_command == "l4 yolo go p1 --reason R --accept-findings --yes"
    refused = decide(
        facts(
            problems=(B_LINE,), refusals={"openspec:add-b": "x was judged not READY on 1 version"}, person_refusals={}
        )
    )
    assert isinstance(refused, Stop) and refused.next_command == "l4 yolo findings p1"
    assert "--force" not in refused.detail  # only a BLOCKED subject
    blocked = decide(
        facts(
            problems=("openspec:add-b: BLOCKED: no judge",),
            refusals={"openspec:add-b": "BLOCKED"},
            blocked=("openspec:add-b",),
        )
    )
    assert isinstance(blocked, Stop) and blocked.next_command == "l4 yolo findings p1"
    assert 'a person may run: l4 yolo go p1 --reason "..." --force' in blocked.detail
    agent_blocked = decide(
        facts(
            actor=AGENT,
            problems=("openspec:add-b: BLOCKED: no judge",),
            refusals={"openspec:add-b": "BLOCKED"},
            blocked=("openspec:add-b",),
        )
    )
    assert isinstance(agent_blocked, Stop) and "--force" not in agent_blocked.detail


def test_accept_findings_is_all_or_nothing():
    a, b = "openspec:add-greeting", "openspec:add-b"
    lines = (f"{a}: NEEDS_REVISION: x", f"{b}: NEEDS_REVISION: y")
    both = {a: None, b: None}
    # nothing refuses: every subject, in plan order
    assert decide(facts(accept_findings=True, problems=lines, refusals=both, person_refusals=both)) == Do(
        "accept", (a, b)
    )
    # one needs a person and the other is refused by a rule: nothing is recorded, findings
    rule = {a: None, b: "openspec:add-b was judged not READY on 1 version; 2 are needed\nFix: review again"}
    stop = decide(facts(accept_findings=True, problems=lines, refusals=rule, person_refusals=rule))
    assert isinstance(stop, Stop) and (stop.code, stop.step) == (GoStop.FINDINGS, "findings")
    assert "judged not READY on 1 version" in stop.detail and stop.next_command == "l4 yolo findings p1"
    # person-only refusals: a person's step
    only = {a: f"{OPEN}\nFix: a person runs", b: f"{OPEN}\nFix: a person runs"}
    person = decide(facts(actor=AGENT, accept_findings=True, problems=lines, refusals=only, person_refusals=both))
    assert person == Stop(
        GoStop.PERSON, "accept", "person", person.detail, "l4 yolo go p1 --reason R --accept-findings"
    )
    assert OPEN in person.detail
    # the person-only refusal is not enough when a person could not accept it either
    refused = decide(facts(actor=AGENT, accept_findings=True, problems=lines, refusals=only, person_refusals=rule))
    assert isinstance(refused, Stop) and refused.code == GoStop.FINDINGS
    # an agent that may accept needs --yes
    agent = decide(facts(actor=AGENT, accept_findings=True, problems=lines, refusals=both, person_refusals=both))
    assert agent == Stop(
        GoStop.NOT_CONFIRMED, "accept", "stopped", agent.detail, "l4 yolo go p1 --reason R --accept-findings --yes"
    )
    yes = decide(
        facts(actor=AGENT, accept_findings=True, yes=True, problems=lines, refusals=both, person_refusals=both)
    )
    assert yes == Do("accept", (a, b))


# --- D1, D8: who may do what ---------------------------------------------------------------------------------------


def test_an_agent_with_force_is_a_person_step_before_anything():
    stop = decide(facts(actor=AGENT, force=True, status="new", review_kind="none"))
    assert stop == Stop(GoStop.PERSON, "accept", "person", stop.detail, "l4 yolo go p1 --reason R --force")


def test_an_agent_at_the_activation_is_a_person_step_or_refused():
    stop = decide(facts(actor=AGENT, local=True, yes=True))
    assert stop == Stop(
        GoStop.PERSON, "activate", "person", "activation is a person's decision", "l4 yolo go p1 --reason R"
    )
    blocked = decide(facts(actor=AGENT, activation_blocker="plan p2 is already active on main\nFix: l4 yolo cancel p2"))
    assert isinstance(blocked, Stop) and (blocked.code, blocked.step, blocked.status) == (
        GoStop.REFUSED, "activate", "stopped",
    )  # fmt: skip
    assert "plan p2 is already active" in blocked.detail


def test_a_person_at_the_activation_activates():
    assert decide(facts()) == Do("activate")
    assert decide(facts(activation_blocker="ignored for a person: the command refuses itself")) == Do("activate")
