"""L4-IMP-100 (SCN-IMP-541..546): a green attempt that passed every test and failed only a static gate that passed at
its base is kept in memory and is the start of the next attempt of the task, once."""

import hashlib
import json
from dataclasses import replace

import pytest

from l4.agents.base import LimitSignal
from l4.agents.fake import Step
from l4.implementer import held_patch, tdd
from l4.implementer.held import HeldCheck
from l4.implementer.held_patch import NearPass, Refused, expected_state, step_patch
from l4.implementer.loop import run_task
from l4.implementer.result import parse_result
from l4.implementer.tdd import RoleLimit, run_green, run_red
from l4.implementer.workbench import PreviousAttempt
from l4.specs.base import Task
from l4.vcs.git import GitError

from .conftest import IMPL, RUN_ID, green_step, red_step, result

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 3, 3)
LINT_IMPL = "sh -c 'if grep -q LINTBAD src/pytdd/pricing.py; then echo E501 line too long; exit 1; fi'"
TYPE_IMPL = "sh -c 'if grep -q TYPEBAD src/pytdd/pricing.py; then echo TS2698 type error; exit 1; fi'"
PRICING = "src/pytdd/pricing.py"
TWO = {"roles": {"implementer": ["impl", "impl-b"]}, "profiles": {"impl-b": {"adapter": "fake", "vendor": "otherco"}}}


def lint_bad(marker: str = "LINTBAD") -> Step:
    """A green step whose tests pass and whose lint (or type) gate fails: the marker is what the gate looks for."""
    return Step(writes={PRICING: IMPL + f"\n# {marker}\n"}, structured=result("green"))


def fixed() -> Step:
    """The step after a near pass: it only takes the marker away."""
    return Step(writes={PRICING: IMPL}, structured=result("green"))


def tree(bench) -> str:
    return (bench.wb.worktree / PRICING).read_text()


def watching(seen: list[str], step: Step) -> Step:
    """`step`, recording what its work tree holds when it starts."""

    def on_start(request) -> None:
        seen.append((request.cwd / PRICING).read_text())

    return replace(step, on_start=on_start)


def ledger(bench) -> list[dict]:
    lines = (bench.wb.ref.path / ".l4" / "ledger" / f"{RUN_ID}.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines]


def failed_green(bench) -> list[dict]:
    return [e for e in bench.events("task.attempt_failed") if e["phase"] == "green"]


# --- 1. the near pass is kept (D1, D2) -------------------------------------------------------------------------


def test_a_green_step_that_passes_every_test_and_fails_only_lint_is_a_near_pass(make_bench):
    bench = make_bench([red_step(), lint_bad()], lint=[LINT_IMPL], typecheck=[TYPE_IMPL])
    red = run_red(bench.wb, TASK, attempt=1)
    assert red.status == "ok", red.reason
    base = bench.wb.head()
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and "lint gate" in green.reason, green.reason
    near = green.near_pass
    assert near is not None
    assert (near.task, near.attempt, near.profile, near.gates) == ("1.1", 1, "impl", ("lint",))
    assert near.patch and near.patch_sha256 == hashlib.sha256(near.patch).hexdigest()
    assert near.files == (PRICING,) and b"LINTBAD" in near.patch
    assert "LINTBAD" not in repr(near)  # the patch bytes are in no log line that prints the dataclass
    assert bench.wb.head() == base and bench.wb.is_clean()  # back at the red commit
    assert "LINTBAD" not in tree(bench)


def test_the_near_pass_names_each_failed_gate_once_in_order(make_bench):
    both = Step(writes={PRICING: IMPL + "\n# LINTBAD\n# TYPEBAD\n"}, structured=result("green"))
    bench = make_bench([red_step(), both], lint=[LINT_IMPL], typecheck=[TYPE_IMPL])
    red = run_red(bench.wb, TASK, attempt=1)
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.near_pass is not None and green.near_pass.gates == ("lint", "typecheck")


def wrong() -> Step:
    """Real wrong code that also trips the lint gate: its diff is not empty, and a test of the gate run fails."""
    return Step(writes={PRICING: IMPL.replace("100 -", "99 -") + "\n# LINTBAD\n"}, structured=result("green"))


def test_scn_imp_543_a_failed_test_is_no_near_pass(make_bench):
    bench = make_bench([red_step(), wrong()], lint=[LINT_IMPL])
    red = run_red(bench.wb, TASK, attempt=1)
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and green.reason.startswith("red tests still failing"), green.reason
    assert green.near_pass is None and bench.wb.is_clean()


def test_scn_imp_543_a_link_out_of_the_work_tree_is_no_near_pass(make_bench, monkeypatch):
    bench = make_bench([red_step(), lint_bad()], lint=[LINT_IMPL])
    red = run_red(bench.wb, TASK, attempt=1)
    monkeypatch.setattr(tdd, "outside_links_reason", lambda wb, base, phase: "a link points outside the worktree")
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and "lint gate" in green.reason
    assert green.near_pass is None and bench.wb.is_clean()


def test_scn_imp_543_a_stuck_replay_restore_is_no_near_pass(make_bench, monkeypatch):
    bench = make_bench([red_step(), lint_bad()], lint=[LINT_IMPL])
    red = run_red(bench.wb, TASK, attempt=1)
    monkeypatch.setattr(tdd, "restore_replay", lambda wb, where: "the replayed step could not be put back")
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and green.near_pass is None


def test_a_replayed_green_step_is_never_a_near_pass(make_bench, monkeypatch):
    bench = make_bench([red_step()], lint=[LINT_IMPL])
    red = run_red(bench.wb, TASK, attempt=1)

    def replay(wb, role, task, attempt, found):  # what `replay_step` leaves: the step applied, the accept noted
        (wb.worktree / PRICING).write_text(IMPL + "\n# LINTBAD\n")
        wb.replay_question = "Q-001"
        wb.replay_expected = expected_state(wb, step_patch(wb))  # the guard keeps the step as it was saved
        wb.replay_links = {}
        return tdd.StepOutcome("ok", parse_result(result("green")))

    monkeypatch.setattr(tdd, "find_replay", lambda wb, role, task, *, attempt: None if role == "red" else object())
    monkeypatch.setattr(tdd, "replay_step", replay)
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and "lint gate" in green.reason, green.reason
    assert green.near_pass is None and bench.wb.is_clean()


# --- 2. it is applied once to the next attempt (D3, D4, D5) ----------------------------------------------------


def test_scn_imp_541_the_next_attempt_starts_from_a_near_pass(make_bench):
    seen: list[str] = []
    bench = make_bench([red_step(), lint_bad(), watching(seen, fixed())], lint=[LINT_IMPL])
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "done", outcome.reason
    assert len(seen) == 1 and "LINTBAD" in seen[0] and "apply_discount" in seen[0]  # attempt 1's code was there
    [failed] = failed_green(bench)
    assert failed["near_pass"] is True and failed["attempt"] == 1
    [applied] = bench.events("task.near_pass_applied")
    got = (applied["task"], applied["attempt"], applied["from_attempt"], applied["from_profile"])
    assert got == ("1.1", 2, 1, "impl")
    assert applied["files"] == [PRICING] and len(applied["patch_sha256"]) == 64
    assert "LINTBAD" not in str(applied)  # the patch bytes are in no record
    types = [e["type"] for e in ledger(bench)]
    starts = [i for i, e in enumerate(ledger(bench)) if e["type"] == "step.started" and e.get("phase") == "green"]
    assert types.index("task.near_pass_applied") < starts[1]
    prompt = bench.adapter.requests[2].prompt  # red, green 1, green 2
    block = prompt.split('<l4:data kind="near-pass"', 1)[1].split("</l4:data>", 1)[0]
    assert "Attempt 1" in block and "profile impl" in block and "lint" in block
    assert "their output is under the previous failure" in block and "E501 line too long" in prompt
    assert "were discarded" not in prompt
    assert "near-pass" not in bench.adapter.requests[1].prompt  # attempt 1 had no carry


def test_the_failed_attempt_of_a_task_without_a_near_pass_has_no_near_pass_field(make_bench):
    bench = make_bench([red_step(), wrong(), green_step()], lint=[LINT_IMPL])
    assert run_task(bench.wb, TASK).status == "done"
    [failed] = failed_green(bench)
    assert "near_pass" not in failed
    assert bench.events("task.near_pass_applied") == [] and bench.events("task.near_pass_dropped") == []


def test_scn_imp_542_an_escalation_keeps_the_near_pass(make_bench):
    from l4.implementer.workbench import PreviousAttempt

    from .test_escalation import Hook

    class Moving(Hook):
        def __call__(self, wb, request):  # as the orchestrator's `_escalate`: the block of the profile moved to
            fresh = super().__call__(wb, request)
            fresh.previous_attempt = PreviousAttempt(
                request.profile, None, request.task, why="escalation", phase=request.phase, failures=request.failures
            )
            return fresh

    seen: list[str] = []
    bench = make_bench(
        [red_step(), lint_bad(), watching(seen, fixed())], lint=[LINT_IMPL], implementer={"escalate_after": 1}, **TWO
    )
    hook = Moving()
    outcome = run_task(bench.wb, TASK, escalate=hook)
    assert outcome.status == "done", outcome.reason
    assert [r.phase for r in hook.requests] == ["green"]
    assert len(seen) == 1 and "LINTBAD" in seen[0]
    [applied] = bench.events("task.near_pass_applied")
    assert (applied["attempt"], applied["from_attempt"], applied["from_profile"]) == (2, 1, "impl")
    prompt = bench.adapter.requests[2].prompt
    assert "(see the near pass block)" in prompt and "from attempt 1 are in the checkout" in prompt
    assert "were discarded" not in prompt


def test_scn_imp_544_a_near_pass_is_applied_once(make_bench):
    seen: list[str] = []
    wrong = Step(writes={PRICING: IMPL.replace("100 -", "99 -") + "\n# WRONG\n"}, structured=result("green"))
    steps = [red_step(), lint_bad(), watching(seen, wrong), watching(seen, fixed())]
    bench = make_bench(steps, lint=[LINT_IMPL])
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "done", outcome.reason
    assert "LINTBAD" in seen[0]  # attempt 2 started from attempt 1's changes
    assert "LINTBAD" not in seen[1] and "WRONG" not in seen[1]  # attempt 3 starts at the red commit
    assert [e["attempt"] for e in bench.events("task.near_pass_applied")] == [2]
    assert "near-pass" not in bench.adapter.requests[3].prompt


def test_scn_imp_544_a_second_near_pass_replaces_the_first(make_bench):
    seen: list[str] = []
    steps = [red_step(), lint_bad(), watching(seen, lint_bad("LINTBAD\n# SECOND")), watching(seen, fixed())]
    bench = make_bench(steps, lint=[LINT_IMPL], implementer={"max_task_attempts": 4})
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "done", outcome.reason
    assert "SECOND" not in seen[0] and "SECOND" in seen[1]  # attempt 3 starts from attempt 2's changes
    applied = bench.events("task.near_pass_applied")
    assert [(e["attempt"], e["from_attempt"]) for e in applied] == [(2, 1), (3, 2)]


def test_scn_imp_546_a_patch_that_does_not_apply_is_dropped(make_bench, monkeypatch):
    seen: list[str] = []
    bench = make_bench([red_step(), lint_bad(), watching(seen, fixed())], lint=[LINT_IMPL])
    real = bench.wb.git.run_input_bytes

    def refuse(*args, **kwargs):
        if "apply" in args:
            raise GitError(["git", "apply"], 1, "error: patch failed: src/pytdd/pricing.py:1\nsecond line")
        return real(*args, **kwargs)

    monkeypatch.setattr(bench.wb.git, "run_input_bytes", refuse)
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "done", outcome.reason
    assert "LINTBAD" not in seen[0]  # it started from the red commit
    assert bench.events("task.near_pass_applied") == []
    [dropped] = bench.events("task.near_pass_dropped")
    assert (dropped["task"], dropped["attempt"], dropped["from_attempt"]) == ("1.1", 2, 1)
    assert "patch failed" in dropped["reason"] and "\n" not in dropped["reason"]
    assert "near-pass" not in bench.adapter.requests[2].prompt


def test_scn_imp_546_a_found_replay_drops_the_near_pass(make_bench, monkeypatch):
    bench = make_bench([red_step(), lint_bad(), lint_bad()], lint=[LINT_IMPL])
    calls: list[int] = []

    def found(wb, role, task, *, attempt):
        calls.append(attempt)
        return object() if role == "green" and attempt == 2 else None

    monkeypatch.setattr(tdd, "find_replay", found)
    monkeypatch.setattr(
        tdd, "replay_step", lambda wb, role, task, attempt, replay: tdd.StepOutcome("failed", reason="replayed")
    )
    outcome = run_task(bench.wb, TASK, escalate=None)
    assert calls[:3] == [1, 1, 2]  # red 1, green 1, green 2
    [dropped] = bench.events("task.near_pass_dropped")
    assert (dropped["attempt"], dropped["from_attempt"], dropped["reason"]) == (2, 1, "replay")
    assert bench.events("task.near_pass_applied") == []
    assert outcome.status == "halt"


# --- 3. the halt names the near pass (D6) ----------------------------------------------------------------------


def test_scn_imp_545_the_halt_names_the_nearest_attempt(make_bench):
    timeout = Step(status="timeout")
    bench = make_bench([red_step(), lint_bad(), timeout, timeout], lint=[LINT_IMPL])
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "halt"
    nearest = "; nearest: attempt 1 (impl) passed every test and failed only its lint or type gates"
    # the orchestrator's `_halt` cuts the reason at 300 characters: the nearest clause comes before the last failure
    assert outcome.reason.startswith(f"task 1.1: max_task_attempts (3) reached in green{nearest}; last failure: ")
    assert outcome.reason.index("; last failure:") < 300
    assert "last failure: the agent step reached its time limit" in outcome.reason
    [tripped] = bench.events("breaker.tripped")
    assert tripped["near_pass"] == {"attempt": 1, "profile": "impl"}


def test_a_halt_without_a_near_pass_has_today_s_reason(make_bench):
    bad = wrong()
    bench = make_bench([red_step(), bad, bad, bad], lint=[LINT_IMPL])
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "halt" and "nearest" not in outcome.reason
    [tripped] = bench.events("breaker.tripped")
    assert "near_pass" not in tripped


def test_scn_imp_545_the_newest_of_two_near_passes_is_named(make_bench):
    timeout = Step(status="timeout")
    bench = make_bench([red_step(), lint_bad(), lint_bad("LINTBAD\n# SECOND"), timeout], lint=[LINT_IMPL])
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "halt"
    assert "; nearest: attempt 2 (impl) passed every test" in outcome.reason, outcome.reason
    [tripped] = bench.events("breaker.tripped")
    assert tripped["near_pass"] == {"attempt": 2, "profile": "impl"}


# --- 4. what is not a near pass ----------------------------------------------------------------------------------


def test_a_refused_write_with_a_failed_static_gate_is_no_near_pass(make_bench, monkeypatch):
    bench = make_bench([red_step(), lint_bad()], lint=[LINT_IMPL])
    red = run_red(bench.wb, TASK, attempt=1)
    monkeypatch.setattr(tdd, "stop_on_unsafe", lambda wb: "a write of the harness was refused: a planted link")
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and "refused" in green.reason
    assert green.near_pass is None and bench.wb.is_clean()


def test_an_empty_patch_is_no_near_pass(make_bench, monkeypatch):
    bench = make_bench([red_step(), lint_bad()], lint=[LINT_IMPL])
    red = run_red(bench.wb, TASK, attempt=1)
    monkeypatch.setattr(tdd, "step_patch", lambda wb: b"")
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and "lint gate" in green.reason
    assert green.near_pass is None and bench.wb.is_clean()


def test_a_git_error_while_taking_the_patch_is_no_near_pass_and_the_changes_are_still_discarded(
    make_bench, monkeypatch
):
    bench = make_bench([red_step(), lint_bad()], lint=[LINT_IMPL])
    red = run_red(bench.wb, TASK, attempt=1)
    base = bench.wb.head()
    real = bench.wb.git.run_bytes

    def broken(*args, **kwargs):
        if "--cached" in args and "--binary" in args:  # the diff of `step_patch`
            raise GitError(["git", "diff"], 128, "fatal: unable to read tree")
        return real(*args, **kwargs)

    monkeypatch.setattr(bench.wb.git, "run_bytes", broken)
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and "lint gate" in green.reason
    assert green.near_pass is None
    assert bench.wb.head() == base and bench.wb.is_clean() and "LINTBAD" not in tree(bench)


def test_a_secret_shaped_file_that_a_gate_wrote_is_no_near_pass(make_bench):
    token = "mk_" + "agent_" + "FAKE" + "Q7w8E9r0T1y2U3i4O5p6"  # built from parts: this file holds no token shape
    writer = (
        "sh -c 'if grep -q LINTBAD src/pytdd/pricing.py; then "
        f'echo "SECRET = \\"{token}\\"" > src/pytdd/leak.py; echo E501 line too long; exit 1; fi\''
    )
    bench = make_bench([red_step(), lint_bad()], lint=[writer])
    red = run_red(bench.wb, TASK, attempt=1)
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and "lint gate" in green.reason, green.reason
    assert green.near_pass is None and bench.wb.is_clean()
    assert not (bench.wb.worktree / "src/pytdd/leak.py").exists()
    assert token not in "".join(p.read_text() for p in (bench.wb.ref.path / ".l4" / "ledger").glob("*.jsonl"))


# --- 5. what the next attempt starts from (D2, D4) -------------------------------------------------------------


def test_the_applied_event_lists_at_most_fifty_files(make_bench):
    many = {f"src/pytdd/gen{n:02d}.py": f"VALUE = {n}\n" for n in range(60)}
    big = Step(writes={PRICING: IMPL + "\n# LINTBAD\n", **many}, structured=result("green"))
    bench = make_bench([red_step(), big, fixed()], lint=[LINT_IMPL])
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "done", outcome.reason
    [applied] = bench.events("task.near_pass_applied")
    assert len(applied["files"]) == 50 and applied["files"] == sorted(applied["files"])


def test_a_carry_with_a_new_a_deleted_and_a_binary_file_comes_back_exactly(make_bench):
    binary = "\x00\x01PNG\x02\x00é\x03"
    legacy = "src/pytdd/legacy.py"
    first = replace(red_step(), writes={**red_step().writes, legacy: "OLD = 1\n"})
    bad = Step(
        writes={PRICING: IMPL + "\n# LINTBAD\n", "src/pytdd/fresh.py": "FRESH = 2\n", "assets/logo.bin": binary},
        deletes=(legacy,), structured=result("green"),
    )  # fmt: skip
    snapshots: list[dict] = []

    def on_start(request) -> None:
        root = request.cwd
        snapshots.append({
            "fresh": (root / "src/pytdd/fresh.py").read_bytes(), "binary": (root / "assets/logo.bin").read_bytes(),
            "legacy": (root / legacy).exists(), "priced": "LINTBAD" in (root / PRICING).read_text(),
            "staged": bench.wb.git.run("diff", "--cached", "--name-only").stdout,
            "status": bench.wb.git.run("status", "--porcelain", "--untracked-files=all").stdout,
        })  # fmt: skip

    bench = make_bench([first, bad, replace(fixed(), on_start=on_start)], lint=[LINT_IMPL])
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "done", outcome.reason
    [snap] = snapshots
    assert snap["fresh"] == b"FRESH = 2\n" and snap["binary"] == binary.encode()
    assert snap["legacy"] is False and snap["priced"] is True
    assert snap["staged"] == ""  # the index is not left staged
    changed = {line[3:] for line in snap["status"].splitlines()}
    assert {PRICING, "src/pytdd/fresh.py", "assets/logo.bin", legacy} <= changed


def test_capture_takes_a_step_with_a_binary_file_as_the_old_code_did(make_bench):
    bench = make_bench([])
    wb = bench.wb
    (wb.worktree / "assets").mkdir()
    (wb.worktree / "assets/logo.bin").write_bytes(bytes(range(256)) * 3)
    (wb.worktree / "src/pytdd/fresh.py").write_text("FRESH = 2\n")
    (wb.worktree / PRICING).write_text(IMPL + "\n# CHANGED\n")
    (wb.worktree / "tests/test_pricing.py").unlink()
    config = (*wb.exclude_config, ("core.autocrlf", "false"), ("core.safecrlf", "false"))
    wb.git.run("add", "-A", config=config)  # what `capture` did itself before `step_patch`
    old = wb.git.run_bytes(
        *held_patch.GIT_PLAIN, "diff", "--cached", "--binary", *held_patch.DIFF_FLAGS, "HEAD", "--", ".",
        f":(exclude){wb.ledger_rel}",
    )  # fmt: skip
    wb.git.run("reset", "-q")
    assert b"GIT binary patch" in old
    held = held_patch.capture(wb, HeldCheck("1.1", "green", "tests", (), (), "why"), None)
    assert held.patch == old and held_patch.step_patch(wb) == old
    assert wb.git.run("diff", "--cached", "--name-only").stdout == ""


# --- 6. the order inside `agent_step` ---------------------------------------------------------------------------


def test_the_near_pass_is_applied_after_the_grant_and_inside_the_guarded_block(make_bench, monkeypatch):
    bench = make_bench([red_step(), lint_bad()], lint=[LINT_IMPL])
    red = run_red(bench.wb, TASK, attempt=1)
    near = run_green(bench.wb, TASK, red, attempt=1).near_pass
    assert near is not None and bench.wb.is_clean()
    order: list[str] = []
    for name in ("config_grant", "apply_near_pass", "revert_protected"):
        real = getattr(tdd, name)

        def spy(*args, _real=real, _name=name, **kwargs):
            order.append(_name)
            return _real(*args, **kwargs)

        monkeypatch.setattr(tdd, name, spy)

    def boom(*args, **kwargs):
        order.append("prompt")
        raise RuntimeError("the prompt could not be built")

    monkeypatch.setattr(tdd, "_prompt", boom)
    with pytest.raises(RuntimeError, match="prompt could not"):
        tdd.agent_step(bench.wb, "green", TASK, 2, None, carry=near)
    # the grant first, then the carry, and the guards run although the step failed after the carry was applied
    assert order == ["config_grant", "apply_near_pass", "prompt", "revert_protected"]


# --- 7. a refused replay --------------------------------------------------------------------------------------


def test_scn_imp_546_a_refused_replay_drops_the_near_pass_too(make_bench, monkeypatch):
    bench = make_bench([red_step(), lint_bad()], lint=[LINT_IMPL])
    red = run_red(bench.wb, TASK, attempt=1)
    near = run_green(bench.wb, TASK, red, attempt=1).near_pass
    assert near is not None
    refused = Refused(HeldCheck("1.1", "green", "tests", (), (), "why"))
    monkeypatch.setattr(tdd, "find_replay", lambda wb, role, task, *, attempt: refused)
    step = tdd.step_or_replay(bench.wb, "green", TASK, 2, None, carry=near)
    assert step.kind == "held"
    [dropped] = bench.events("task.near_pass_dropped")
    assert (dropped["attempt"], dropped["from_attempt"], dropped["reason"]) == (2, 1, "replay")
    assert bench.events("task.near_pass_applied") == [] and bench.wb.is_clean()


# --- 1. the previous-attempt block names the right agent -------------------------------------------------------------


def a_carry(profile: str = "impl") -> NearPass:
    return NearPass("1.1", 2, profile, b"patch", "0" * 64, (PRICING,), ("lint",))


@pytest.mark.parametrize("kind", ["usage_limit", "rate_limit", "silent"])
def test_a_limit_or_silent_block_always_says_the_changes_were_discarded(make_bench, kind):
    bench = make_bench([])
    bench.wb.previous_attempt = PreviousAttempt("impl", kind, "1.1")
    for carried in (None, a_carry("impl"), a_carry("impl-b")):
        [(_, block)] = tdd._previous_attempt_block(bench.wb, TASK, "green", carried)
        assert "Its uncommitted changes were discarded" in block and "in the checkout" not in block


def test_an_escalation_block_names_the_checkout_only_for_the_profile_whose_changes_are_in_it(make_bench):
    bench = make_bench([])
    bench.wb.previous_attempt = PreviousAttempt(
        "impl", None, "1.1", why="escalation", phase="green", failures=(("impl", "x"),)
    )
    [(_, same)] = tdd._previous_attempt_block(bench.wb, TASK, "green", a_carry("impl"))
    assert "Its uncommitted changes from attempt 2 are in the checkout (see the near pass block)" in same
    [(_, other)] = tdd._previous_attempt_block(bench.wb, TASK, "green", a_carry("impl-b"))
    [(_, none)] = tdd._previous_attempt_block(bench.wb, TASK, "green", None)
    assert "Its uncommitted changes were discarded" in other and "in the checkout" not in other
    assert other == none  # the original text, byte for byte


def test_a_later_attempt_does_not_say_that_another_profiles_changes_are_in_the_checkout(make_bench):
    """`previous_attempt` outlives the attempt that set it: impl failed green 1 (an escalation block), impl-b's green 2
    is a near pass, and green 3's block still describes impl, whose changes were discarded."""
    from .test_escalation import Hook

    class Moving(Hook):
        def __call__(self, wb, request):
            fresh = super().__call__(wb, request)
            fresh.previous_attempt = PreviousAttempt(
                request.profile, None, request.task, why="escalation", phase=request.phase, failures=request.failures
            )
            return fresh

    wrong_code = replace(wrong(), writes={PRICING: IMPL.replace("100 -", "99 -")})
    steps = [red_step(), wrong_code, lint_bad(), fixed()]
    bench = make_bench(steps, lint=[LINT_IMPL], implementer={"escalate_after": 1}, **TWO)
    outcome = run_task(bench.wb, TASK, escalate=Moving())
    assert outcome.status == "done", outcome.reason
    assert [e["profile"] for e in failed_green(bench)] == ["impl", "impl-b"]
    prompt = bench.adapter.requests[3].prompt  # red, green 1 (impl), green 2 (impl-b), green 3
    assert "Its uncommitted changes were discarded" in prompt
    assert "are in the checkout" not in prompt.split('kind="previous-attempt"', 1)[1].split("</l4:data>", 1)[0]
    block = prompt.split('<l4:data kind="near-pass"', 1)[1].split("</l4:data>", 1)[0]
    assert "Attempt 2" in block and "profile impl-b" in block  # the near pass block still names its own writer


# --- 2. a limit after a carry was applied (D7) -----------------------------------------------------------------


def quota(**over) -> Step:
    limit = LimitSignal("fake", None, "usage_limit", None, "test", "You have hit your usage limit")
    return Step(status="quota", limit=limit, **over)


def test_a_limit_hands_the_carry_it_started_from_to_the_next_run_of_the_task(make_bench):
    seen: list[str] = []
    bench = make_bench([red_step(), lint_bad(), quota(), watching(seen, fixed())], lint=[LINT_IMPL])
    with pytest.raises(RoleLimit) as caught:
        run_task(bench.wb, TASK)
    carry = caught.value.carry
    assert carry is not None and (carry.attempt, carry.profile) == (1, "impl")
    bench.wb.discard_changes()  # what the orchestrator's fallback does before the next profile
    outcome = run_task(bench.wb, TASK, carry=carry)
    assert outcome.status == "done", outcome.reason
    assert "LINTBAD" in seen[0]  # the next profile's attempt starts from attempt 1's changes
    applied = bench.events("task.near_pass_applied")
    assert [(e["attempt"], e["from_attempt"], e["from_profile"]) for e in applied] == [(2, 1, "impl")] * 2
    # the new `_run_task` has no previous failure to show: the block says to run the gates instead
    block = bench.adapter.requests[3].prompt.split('<l4:data kind="near-pass"', 1)[1].split("</l4:data>", 1)[0]
    assert "this prompt does not hold their output: run them to read what they report" in block
    assert "under the previous failure" not in block


def test_a_limit_after_a_patch_that_did_not_apply_hands_on_no_carry(make_bench, monkeypatch):
    """The limited attempt did not start from the near pass: the next profile is not handed it to drop again."""
    bench = make_bench([red_step(), lint_bad(), quota()], lint=[LINT_IMPL])
    real = bench.wb.git.run_input_bytes

    def refuse(*args, **kwargs):
        if "apply" in args:
            raise GitError(["git", "apply"], 1, "error: patch failed: src/pytdd/pricing.py:1")
        return real(*args, **kwargs)

    monkeypatch.setattr(bench.wb.git, "run_input_bytes", refuse)
    with pytest.raises(RoleLimit) as caught:
        run_task(bench.wb, TASK)
    assert caught.value.carry is None
    assert len(bench.events("task.near_pass_dropped")) == 1


def test_a_limit_with_no_carry_hands_on_none(make_bench):
    bench = make_bench([red_step(), quota()])
    with pytest.raises(RoleLimit) as caught:
        run_task(bench.wb, TASK)
    assert caught.value.carry is None


def test_a_limit_of_a_red_step_has_no_carry_too(make_bench):
    bench = make_bench([quota()])  # `_run_task` never sets it here: the fallbacks read the default
    with pytest.raises(RoleLimit) as caught:
        run_task(bench.wb, TASK)
    assert caught.value.carry is None


def test_a_carry_is_not_applied_to_a_task_that_starts_its_red_step_again(make_bench):
    bench = make_bench([red_step(), green_step()])  # no red commit: its patch would be against another commit
    assert run_task(bench.wb, TASK, carry=a_carry()).status == "done"
    assert bench.events("task.near_pass_applied") == [] and bench.events("task.near_pass_dropped") == []


def test_a_halt_after_a_limit_restart_still_names_the_nearest_attempt(make_bench):
    timeout = Step(status="timeout")
    bench = make_bench([red_step(), lint_bad(), quota(), timeout, timeout], lint=[LINT_IMPL])
    with pytest.raises(RoleLimit) as caught:
        run_task(bench.wb, TASK)
    bench.wb.discard_changes()
    outcome = run_task(bench.wb, TASK, carry=caught.value.carry)  # a new `_run_task`: no local remembers attempt 1
    assert outcome.status == "halt"
    assert "; nearest: attempt 1 (impl) passed every test and failed only its lint or type gates; last failure:" in (
        outcome.reason
    )
    [tripped] = bench.events("breaker.tripped")
    assert tripped["near_pass"] == {"attempt": 1, "profile": "impl"}
