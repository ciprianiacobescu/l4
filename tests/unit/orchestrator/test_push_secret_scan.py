"""HB-4: a push of the unit branch is preceded by a secret scan of the outgoing commits; a hit blocks the push, is
recorded as `guard.secret {path, kind}` (never the value) and halts the unit (exit 13)."""

import json

from l4.vcs.git import Git

from ..implementer.conftest import IMPL, green_step, red_step
from .conftest import BRANCH

SECRET = "sk-ant-api03-" + "Zq9Xw8Vu7Ts6Rp5On4Ml3Kj2"


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
    assert len(pushes) == 1  # the clean red checkpoint went out; the green commit and the ledger did not
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
