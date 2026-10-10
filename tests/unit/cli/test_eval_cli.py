"""L4-EVAL-014: `l4 eval` parses its options (the handler's own checks are tests/unit/eval/test_run_*.py)."""

from pathlib import Path

from l4 import commands
from l4.cli import main
from l4.exitcodes import ExitCode


def _run(install_handler, repo: Path, tmp_path: Path, *args: str):
    calls = install_handler("eval", lambda app, **kw: ExitCode.OK)
    code = main(["eval", "--config", str(tmp_path / "p.yaml"), "--repo", str(repo), *args], environ={})
    return code, calls


def test_eval_is_a_registered_command() -> None:
    assert commands.HANDLERS["eval"] == "l4.eval.run:run_eval"
    assert "eval" in commands.OWNING_CHANGE


def test_impl_and_judge_repeat(install_handler, repo: Path, tmp_path: Path) -> None:
    code, calls = _run(
        install_handler, repo, tmp_path,
        "--impl", "p1", "--impl", "p2", "--judge", "j1", "--judge", "j2", "--ref-judge", "r",
        "--out", str(tmp_path / "o"),
    )  # fmt: skip
    assert code == 0
    kw = calls[0]["kwargs"]
    assert kw["impl"] == ("p1", "p2") and kw["judge"] == ("j1", "j2") and kw["ref_judge"] == "r"
    assert kw["out"] == tmp_path / "o"


def test_the_documented_options_and_their_defaults(install_handler, repo: Path, tmp_path: Path) -> None:
    code, calls = _run(
        install_handler, repo, tmp_path,
        "--judge", "j", "--unit", "add-late-fee", "--unit", "add-shelf-code", "--k", "3", "--cell-timeout", "20m",
        "--runner", "--dry-run", "--resume", "--idle-check", "python3 idle.py", "--idle-wait", "10m",
    )  # fmt: skip
    kw = calls[0]["kwargs"]
    assert code == 0
    assert kw["units"] == ("add-late-fee", "add-shelf-code") and kw["k"] == 3 and kw["cell_timeout"] == "20m"
    assert kw["runner"] and kw["dry_run"] and kw["resume"]
    assert kw["idle_check"] == "python3 idle.py" and kw["idle_wait"] == "10m"
    code, calls = _run(install_handler, repo, tmp_path, "--judge", "j")
    kw = calls[0]["kwargs"]
    assert kw["k"] == 1 and kw["cell_timeout"] == "50m" and kw["idle_wait"] == "30m" and kw["units"] == ()
    assert kw["impl"] == () and not kw["runner"] and not kw["dry_run"] and not kw["resume"] and kw["out"] is None


def test_the_compare_options(install_handler, repo: Path, tmp_path: Path) -> None:
    code, calls = _run(
        install_handler, repo, tmp_path,
        "--compare", str(tmp_path / "old.json"), "--new", str(tmp_path / "new.json"), "--json", "--max-drop", "0.1",
        "--allow-seed-change", "--require-all", "--baseline-dir", str(tmp_path / "b"),
    )  # fmt: skip
    kw = calls[0]["kwargs"]
    assert code == 0
    assert kw["compare"] == tmp_path / "old.json" and kw["new"] == tmp_path / "new.json"
    assert kw["as_json"] and kw["max_drop"] == 0.1 and kw["allow_seed_change"] and kw["require_all"]
    assert kw["baseline_dir"] == tmp_path / "b"
    kw = _run(install_handler, repo, tmp_path, "--compare", "x.json")[1][0]["kwargs"]
    assert kw["max_drop"] == 0.2 and not kw["allow_seed_change"] and not kw["require_all"]


def test_warm_cache_and_seeds(install_handler, repo: Path, tmp_path: Path) -> None:
    kw = _run(install_handler, repo, tmp_path, "--warm-cache", "--seeds", str(tmp_path))[1][0]["kwargs"]
    assert kw["warm_cache"] is True and kw["seeds"] == tmp_path


def test_a_missing_handler_module_is_still_a_clean_usage_error(monkeypatch, capsys, repo: Path) -> None:
    monkeypatch.setitem(commands.HANDLERS, "eval", "l4_no_such_pkg.run:run_eval")
    assert main(["eval", "--repo", str(repo)], environ={}) == 2
    assert "eval: not yet implemented" in capsys.readouterr().err
