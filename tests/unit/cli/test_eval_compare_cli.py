"""L4-EVAL-024: `l4 eval --compare` reads two scorecards, prints the deltas and exits 0, 15 or 2."""

import json
from pathlib import Path

import pytest

from l4.cli import main
from l4.eval.run import Deps, run_eval
from l4.eval.scorecard import canonical_json
from l4.exitcodes import ExitCode

from ..eval._cards import impl, judge, sample_card

UNITS = ["add-reorder-quantity", "add-shelf-code", "add-tip-amount"]


def write(path: Path, card: dict) -> Path:
    path.write_text(canonical_json(card), encoding="utf-8")
    return path


def good(profile: str = "p") -> list[dict]:
    return [impl(profile, u, "pass") for u in UNITS]


def bad(profile: str = "p") -> list[dict]:
    return [impl(profile, UNITS[0], "pass"), impl(profile, UNITS[1], "fail"), impl(profile, UNITS[2], "fail")]


def cli(*args: str, repo: Path) -> int:
    return main(["eval", "--repo", str(repo), *args], environ={"HOME": str(repo)})


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "repo").mkdir()
    return tmp_path / "repo"


def test_nothing_regressed_exits_0_and_prints_the_deltas(tmp_path: Path, repo: Path, capsys) -> None:
    old, new = write(tmp_path / "old.json", sample_card(good())), write(tmp_path / "new.json", sample_card(good()))
    assert cli("--compare", str(old), "--new", str(new), repo=repo) == 0
    out = capsys.readouterr().out
    assert out.startswith("# l4 eval comparison\n") and "| implementer | p | ok |" in out
    assert "No environment change." in out


def test_a_regressed_profile_exits_15(tmp_path: Path, repo: Path, capsys) -> None:
    old, new = write(tmp_path / "old.json", sample_card(good())), write(tmp_path / "new.json", sample_card(bad()))
    assert cli("--compare", str(old), "--new", str(new), repo=repo) == 15
    assert "regressed" in capsys.readouterr().out


def test_a_newly_missed_defect_exits_15_at_any_threshold(tmp_path: Path, repo: Path, capsys) -> None:
    held = judge("j", "add-late-fee", "pass", verdict="NEEDS_HUMAN", expected_verdict="NEEDS_HUMAN")
    missed = judge(
        "j", "add-late-fee", "fail", verdict="PASS", expected_verdict="NEEDS_HUMAN", agreement=False, missed_defect=True
    )
    rest = [judge("j", u, "pass") for u in UNITS]
    old, new = (
        write(tmp_path / "o.json", sample_card([held, *rest])),
        write(tmp_path / "n.json", sample_card([missed, *rest])),
    )
    assert cli("--compare", str(old), "--new", str(new), "--max-drop", "1.0", repo=repo) == 15
    assert "missed the designed defect" in capsys.readouterr().out


def test_json_prints_the_machine_form(tmp_path: Path, repo: Path, capsys) -> None:
    old, new = write(tmp_path / "old.json", sample_card(good())), write(tmp_path / "new.json", sample_card(bad()))
    assert cli("--compare", str(old), "--new", str(new), "--json", repo=repo) == 15
    doc = json.loads(capsys.readouterr().out)
    assert doc["regressed"] is True and doc["exit_code"] == 15 and doc["max_drop"] == 0.2
    assert doc["rows"][0]["profile"] == "p" and doc["rows"][0]["status"] == "regressed"
    assert doc["env_diff"] == [] and doc["missed_defects"] == []


def test_a_missing_or_invalid_file_exits_2(tmp_path: Path, repo: Path, capsys) -> None:
    ok = write(tmp_path / "ok.json", sample_card(good()))
    assert cli("--compare", str(tmp_path / "nope.json"), "--new", str(ok), repo=repo) == 2
    assert cli("--compare", str(ok), "--new", str(tmp_path / "nope.json"), repo=repo) == 2
    junk = tmp_path / "junk.json"
    junk.write_text("{not json")
    assert cli("--compare", str(junk), "--new", str(ok), repo=repo) == 2
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"schema": "l4/outcome@1"}))
    assert cli("--compare", str(wrong), "--new", str(ok), repo=repo) == 2
    err = capsys.readouterr().err
    assert "nope.json" in err and "scorecard" in err


def test_a_changed_seed_set_exits_2_unless_allowed(tmp_path: Path, repo: Path, capsys) -> None:
    other = sample_card(good())
    other["seeds"] = {**other["seeds"], "sha256": "0" * 64}
    old, new = write(tmp_path / "old.json", sample_card(good())), write(tmp_path / "new.json", other)
    assert cli("--compare", str(old), "--new", str(new), repo=repo) == 2
    assert "the scorecards measure different seed sets" in capsys.readouterr().err
    assert cli("--compare", str(old), "--new", str(new), "--allow-seed-change", repo=repo) == 0


def test_with_new_no_agent_runs(tmp_path: Path, make_app) -> None:
    old, new = write(tmp_path / "old.json", sample_card(good())), write(tmp_path / "new.json", sample_card(good()))

    def boom(*args, **kwargs):
        raise AssertionError("an agent run was started")

    code = run_eval(make_app(), deps=Deps(runner=boom), compare=old, new=new, max_drop=0.2)
    assert code == ExitCode.OK


def test_without_new_the_run_is_made_and_then_compared(tmp_path: Path, make_app, seeds_root: Path) -> None:
    from ..eval._fakerun import ScriptedRunner
    from ..eval._go import go

    app = make_app()
    first = tmp_path / "base"
    go(app, seeds_root, impl=("p1",), ref_judge="j1", units=("add-shelf-code",), out=first, dry_run=False,
       deps=Deps(runner=ScriptedRunner(), version_of=lambda a: "1"))  # fmt: skip
    again = tmp_path / "again"
    scripted = ScriptedRunner()
    code = go(
        app, seeds_root, impl=("p1",), ref_judge="j1", units=("add-shelf-code",), out=again, dry_run=False,
        compare=first / "scorecard.json", deps=Deps(runner=scripted, version_of=lambda a: "1"),
    )  # fmt: skip
    assert code == ExitCode.OK and len(scripted.calls) == 1
    assert (again / "comparison.md").read_text().startswith("# l4 eval comparison")


def test_a_run_that_then_regresses_exits_15(tmp_path: Path, make_app, seeds_root: Path) -> None:
    from ..eval._fakerun import ScriptedRunner
    from ..eval._go import go
    from ..eval._ledgers import ev, failed, step

    app = make_app()
    first = tmp_path / "base"
    go(app, seeds_root, impl=("p1",), ref_judge="j1", units=("add-shelf-code",), out=first, dry_run=False,
       deps=Deps(runner=ScriptedRunner(), version_of=lambda a: "1"))  # fmt: skip
    halted = [  # the model ran red and failed it: a failure of the profile (a halt before any step is invalid)
        ev("task.started", task="1.1", title="t"), *step("red", 1, "failed"), failed("red", 1, "gate test failed"),
        ev("breaker.tripped", reason="max_task_attempts", task="1.1", phase="red", attempts=1, last_failure="x"),
    ]  # fmt: skip
    failing = ScriptedRunner(lambda role, profile, unit: (halted, None, 13, ""))
    code = go(
        app, seeds_root, impl=("p1",), ref_judge="j1", units=("add-shelf-code",), out=tmp_path / "again", dry_run=False,
        compare=first / "scorecard.json", deps=Deps(runner=failing, version_of=lambda a: "1"),
    )  # fmt: skip
    assert code == ExitCode.REGRESSION


def test_compare_opens_no_socket(tmp_path: Path, repo: Path, no_sockets) -> None:
    old, new = write(tmp_path / "old.json", sample_card(good())), write(tmp_path / "new.json", sample_card(bad()))
    assert cli("--compare", str(old), "--new", str(new), repo=repo) == 15 and no_sockets == []


# --- line 31: a profile the new run did not evaluate
def test_a_profile_missing_from_the_new_run_is_gone_and_does_not_fail(tmp_path: Path, repo: Path, capsys) -> None:
    old = write(tmp_path / "old.json", sample_card([*good("a"), *good("b")]))
    new = write(tmp_path / "new.json", sample_card(good("a")))
    assert cli("--compare", str(old), "--new", str(new), repo=repo) == 0
    assert "| implementer | b | gone |" in capsys.readouterr().out


def test_require_all_makes_gone_a_failure(tmp_path: Path, repo: Path, capsys) -> None:
    old = write(tmp_path / "old.json", sample_card([*good("a"), *good("b")]))
    new = write(tmp_path / "new.json", sample_card(good("a")))
    assert cli("--compare", str(old), "--new", str(new), "--require-all", repo=repo) == 15
    assert "gone" in capsys.readouterr().out


def test_scorecards_that_share_no_rated_cell_do_not_pass_the_gate(tmp_path: Path, repo: Path, capsys) -> None:
    """Every cell of the new run was invalid (a 429 on every profile, or a broken harness): nothing was compared,
    so the gate refuses (exit 2) instead of passing; the report is still printed."""
    invalid = [impl("p", u, "invalid") for u in UNITS]
    old, new = write(tmp_path / "o.json", sample_card(good())), write(tmp_path / "n.json", sample_card(invalid))
    assert cli("--compare", str(old), "--new", str(new), repo=repo) == 2
    captured = capsys.readouterr()
    assert "| implementer | p | unrated |" in captured.out
    assert "Gate (--max-drop 0.2): passed" not in captured.out
    assert "Gate (--max-drop 0.2): nothing compared" in captured.out
    assert "nothing was compared" in captured.err
    renamed = write(tmp_path / "r.json", sample_card(good("q")))  # only new and gone rows
    assert cli("--compare", str(old), "--new", str(renamed), repo=repo) == 2
    assert cli("--compare", str(old), "--new", str(renamed), "--require-all", repo=repo) == 15


def test_max_drop_outside_0_to_1_is_a_usage_error(tmp_path: Path, repo: Path) -> None:
    old, new = write(tmp_path / "o.json", sample_card(good())), write(tmp_path / "n.json", sample_card(good()))
    for value in ("-0.1", "1.5", "nan", "inf"):
        assert cli("--compare", str(old), "--new", str(new), "--max-drop", value, repo=repo) == 2, value
    for value in ("0", "1.0"):
        assert cli("--compare", str(old), "--new", str(new), "--max-drop", value, repo=repo) == 0, value
