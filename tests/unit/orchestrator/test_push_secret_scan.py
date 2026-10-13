"""HB-4: a push of the unit branch is preceded by a secret scan of the outgoing commits; a hit blocks the push, is
recorded as `guard.secret {path, kind}` (never the value) and halts the unit (exit 13)."""

import json

from l4.state.fold import fold
from l4.state.ledger import TS_FORMAT, LedgerEvent
from l4.vcs.git import Git
from l4.vcs.names import UnitNames

from ..implementer.conftest import IMPL, TESTS, green_step, red_step
from .conftest import BRANCH, UNIT

SECRET = "sk-ant-api03-" + "Zq9Xw8Vu7Ts6Rp5On4Ml3Kj2"


def fold_events(rows: list[dict]):
    """The fold of ledger lines as dicts (`Run.branch_ledger()`)."""
    from datetime import UTC, datetime

    events = [
        LedgerEvent(
            datetime.strptime(r["ts"], TS_FORMAT).replace(tzinfo=UTC), r["run_id"], r["unit"], r["seq"], r["type"],
            {k: v for k, v in r.items() if k not in ("ts", "run_id", "unit", "seq", "type")},
        )
        for r in rows
    ]  # fmt: skip
    return fold(events, UNIT)


def planted_green():
    step = green_step()
    step.writes = {"src/pytdd/pricing.py": IMPL + f'\nAPI_KEY = "{SECRET}"\n'}
    return step


def test_a_committed_secret_blocks_the_push_and_halts_the_unit(run_l4, monkeypatch, capsys):
    pushes: list[list[str]] = []
    real = Git.push_branch

    def spy(self, remote, branch, *, config=()):
        pushes.append([branch])
        return real(self, remote, branch, config=config)

    monkeypatch.setattr(Git, "push_branch", spy)
    run = run_l4([red_step(), planted_green()])
    err = capsys.readouterr().err
    assert run.code == 13
    assert len(pushes) == 2  # the clean red checkpoint, then the ledger alone (L4-OPS-009); never the green commit
    assert SECRET not in run.raw(run.tdd.origin, "log", "-p", "--all")  # the forge never saw the key
    [event] = run.local_events("guard.secret")
    assert (event["path"], event["kind"]) == ("src/pytdd/pricing.py", "anthropic-key")
    assert set(event) - {"ts", "run_id", "unit", "seq", "type"} == {"path", "kind"}
    outcome = run.outcome
    assert outcome["units"][0]["exit_reason"].startswith("secret in the outgoing commits")
    assert "src/pytdd/pricing.py" in outcome["units"][0]["exit_reason"]
    # the value is nowhere: not in the console, the outcome, the ledger or any log of the run
    events = run.local_events("guard.secret") + run.local_events("breaker.tripped")
    haystack = [err, json.dumps(outcome), json.dumps(events)]
    for log in (run.tdd.repo / ".l4-out").rglob("*"):
        if log.is_file():
            haystack.append(log.read_text(errors="replace"))
    assert not [text for text in haystack if SECRET in text or SECRET[13:] in text]
    assert run.local_events("breaker.tripped")[-1]["reason"] == "secret_in_push"
    assert outcome["units"][0]["phase_after"] == "halted"  # via the lifecycle's breaker edge, not the exit code only
    assert [e["trigger"] for e in run.local_events("phase.changed")][-1] == "breaker_or_budget"


def test_a_clean_run_still_pushes(run_l4):
    run = run_l4([red_step(), green_step()])
    assert run.code == 0 and run.local_events("guard.secret") == []
    assert run.raw(run.tdd.origin, "for-each-ref", f"refs/heads/{BRANCH}").strip() != ""


def test_the_halt_discards_the_secret_commits_and_pushes_the_ledger_alone(run_l4):
    """L4-OPS-009, SCN-OPS-15: the unpushed commits are discarded (hard reset to `origin/<branch>`), the unit takes the
    halted edge, and the ledger is the only thing that goes out. A halt that was never pushed could not be resumed."""
    run = run_l4([red_step(), planted_green()])
    assert run.code == 13
    subjects = run.subjects()
    assert [s.split("(")[0] for s in subjects] == ["test", "chore"]  # the red checkpoint and the ledger; no `feat`
    assert "feat" not in " ".join(subjects) and SECRET not in run.raw(run.tdd.origin, "log", "-p", "--all")
    assert SECRET not in run.pushed("src/pytdd/pricing.py")
    ledger = run.branch_ledger()  # what the forge holds: the events survived the reset
    changed = [e for e in ledger if e["type"] == "phase.changed"]
    assert (changed[-1]["to"], changed[-1]["reason"], changed[-1]["trigger"]) == (
        "halted", "secret_in_push", "breaker_or_budget",
    )  # fmt: skip
    assert "secret in the outgoing commits" in changed[-1]["detail"]
    assert [e["type"] for e in ledger].count("guard.secret") == 1 and ledger[-1]["type"] == "run.finished"
    state = fold_events(ledger)
    assert (state.phase, state.halt_reason) == ("halted", "secret_in_push")
    # the worktree itself holds no secret commit either
    names = UnitNames.for_unit(UNIT, branch_prefix="l4/", cache=run.tdd.cache)
    assert SECRET not in run.raw(names.worktree, "log", "-p", "--all")


def test_a_secret_in_the_first_commits_leaves_only_the_ledger_on_the_new_branch(run_l4):
    """No `origin/<branch>` yet: the reset goes to the commit the run started the branch from."""
    leaking = red_step()
    leaking.writes = {**leaking.writes, "tests/test_discount.py": TESTS + f'\nAPI_KEY = "{SECRET}"\n'}
    run = run_l4([leaking])
    assert run.code == 13
    assert [s.split("(")[0] for s in run.subjects()] == ["chore"]  # exactly one commit above the base: the ledger
    assert SECRET not in run.raw(run.tdd.origin, "log", "-p", "--all")
    assert run.raw(run.tdd.origin, "diff", "--name-only", f"main..{BRANCH}").split() == [
        p for p in run.raw(run.tdd.origin, "diff", "--name-only", f"main..{BRANCH}").split() if "/.l4/ledger/" in p
    ]
    state = fold_events(run.branch_ledger())
    assert (state.phase, state.halt_reason) == ("halted", "secret_in_push")
