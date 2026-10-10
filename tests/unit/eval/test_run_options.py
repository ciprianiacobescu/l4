"""L4-EVAL-014: what `l4 eval` refuses before anything starts (exit 2)."""

from pathlib import Path

import pytest

from l4.exitcodes import ExitCode, L4Exit

from ._go import go


def test_neither_impl_nor_judge_is_a_usage_error(make_app, seeds_root: Path) -> None:
    with pytest.raises(L4Exit, match="--impl or --judge") as info:
        go(make_app(), seeds_root)
    assert info.value.code == ExitCode.USAGE_ERROR


def test_an_implementer_cell_needs_a_reference_judge(make_app, seeds_root: Path) -> None:
    with pytest.raises(L4Exit, match="--ref-judge"):
        go(make_app(), seeds_root, impl=("p1",))
    assert go(make_app(), seeds_root, impl=("p1",), ref_judge="j1") == ExitCode.OK


def test_a_judge_alone_needs_no_reference_judge(make_app, seeds_root: Path) -> None:
    assert go(make_app(), seeds_root, judge=("j1",)) == ExitCode.OK


def test_an_unknown_unit_is_a_usage_error_naming_it(make_app, seeds_root: Path) -> None:
    with pytest.raises(L4Exit, match="add-nothing") as info:
        go(make_app(), seeds_root, judge=("j1",), units=("add-nothing",))
    assert info.value.code == ExitCode.USAGE_ERROR


def test_an_unknown_profile_is_a_usage_error_naming_it(make_app, seeds_root: Path) -> None:
    with pytest.raises(L4Exit, match="ghost"):
        go(make_app(), seeds_root, judge=("ghost",))
    with pytest.raises(L4Exit, match="ghost"):
        go(make_app(), seeds_root, impl=("p1",), ref_judge="ghost")


def test_no_config_is_a_usage_error(make_app, seeds_root: Path) -> None:
    with pytest.raises(L4Exit, match="--config"):
        go(make_app(config=None), seeds_root, judge=("j1",))


def test_a_run_needs_an_out_directory(make_app, seeds_root: Path) -> None:
    with pytest.raises(L4Exit, match="--out"):
        go(make_app(), seeds_root, judge=("j1",), dry_run=False)


def test_a_missing_seed_set_is_a_usage_error(make_app, tmp_path: Path) -> None:
    with pytest.raises(L4Exit, match="seed"):
        go(make_app(), tmp_path / "nope", judge=("j1",))


def test_a_bad_duration_is_a_usage_error(make_app, seeds_root: Path) -> None:
    with pytest.raises(L4Exit):
        go(make_app(), seeds_root, judge=("j1",), cell_timeout="soon")


def test_new_without_a_baseline_is_a_usage_error(make_app, seeds_root: Path, tmp_path: Path) -> None:
    """`--new` names the scorecard to judge; without `--compare` or `--baseline-dir` there is nothing to judge it
    against, and silently running the matrix instead (or nothing) would read as a gate that passed."""
    with pytest.raises(L4Exit, match="--new needs --compare or --baseline-dir") as info:
        go(make_app(), seeds_root, judge=("j1",), new=tmp_path / "scorecard.json")
    assert info.value.code == ExitCode.USAGE_ERROR
