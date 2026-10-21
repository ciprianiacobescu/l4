"""L4-EVAL-025: --baseline-dir picks the newest committed scorecard that measured the same seed set."""

import json
from pathlib import Path

import pytest

from l4.eval.compare import find_baseline
from l4.eval.run import Deps, run_eval
from l4.eval.scorecard import canonical_json
from l4.exitcodes import ExitCode, L4Exit

from ._cards import impl, sample_card


def put(directory: Path, name: str, started: str, seed: str = "s" * 64, **cells) -> Path:
    card = sample_card([impl("p", "add-shelf-code", "pass")], started_at=started)
    card["seeds"] = {**card["seeds"], "sha256": seed}
    path = directory / name / "scorecard.json"
    path.parent.mkdir(parents=True)
    path.write_text(canonical_json(card))
    return path


def test_the_newest_matching_scorecard_wins(tmp_path: Path) -> None:
    put(tmp_path, "2026-10-01", "2026-10-01T10:00:00Z")
    newest = put(tmp_path, "2026-10-05", "2026-10-05T10:00:00Z")
    put(tmp_path, "2026-10-06-other", "2026-10-06T10:00:00Z", seed="o" * 64)
    assert find_baseline(tmp_path, "s" * 64) == newest


def test_none_matching_is_none(tmp_path: Path) -> None:
    put(tmp_path, "a", "2026-10-01T10:00:00Z", seed="o" * 64)
    assert find_baseline(tmp_path, "s" * 64) is None
    assert find_baseline(tmp_path / "missing", "s" * 64) is None


def test_unreadable_files_are_skipped(tmp_path: Path) -> None:
    good = put(tmp_path, "good", "2026-10-01T10:00:00Z")
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "scorecard.json").write_text("{nope")
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "scorecard.json").write_text(json.dumps({"schema": "x"}))
    assert find_baseline(tmp_path, "s" * 64) == good


def test_run_eval_uses_the_baseline_dir(make_app, tmp_path: Path, capsys) -> None:
    base = tmp_path / "docs"
    put(base, "2026-10-05", "2026-10-05T10:00:00Z")
    new = tmp_path / "new.json"
    new.write_text(canonical_json(sample_card([impl("p", "add-shelf-code", "pass")])))
    code = run_eval(make_app(), deps=Deps(), baseline_dir=base, new=new, max_drop=0.2)
    assert code == ExitCode.OK and "# l4 eval comparison" in capsys.readouterr().out


def test_no_baseline_for_the_seed_set_is_a_usage_error_with_the_fix(make_app, tmp_path: Path) -> None:
    base = tmp_path / "docs"
    put(base, "old", "2026-10-05T10:00:00Z", seed="o" * 64)
    new = tmp_path / "new.json"
    new.write_text(canonical_json(sample_card([impl("p", "add-shelf-code", "pass")])))
    with pytest.raises(L4Exit) as info:
        run_eval(make_app(), deps=Deps(), baseline_dir=base, new=new, max_drop=0.2)
    assert info.value.code == ExitCode.USAGE_ERROR
    assert str(info.value) == ("no baseline for this seed set: run `l4 eval ... --out <dir>` and commit the scorecard")


def test_an_explicit_path_wins_over_the_baseline_dir(make_app, tmp_path: Path, capsys) -> None:
    explicit = tmp_path / "explicit.json"
    explicit.write_text(canonical_json(sample_card([impl("p", "add-shelf-code", "fail")])))
    put(tmp_path / "docs", "x", "2026-10-05T10:00:00Z")
    new = tmp_path / "new.json"
    new.write_text(canonical_json(sample_card([impl("p", "add-shelf-code", "pass")])))
    code = run_eval(make_app(), deps=Deps(), compare=explicit, baseline_dir=tmp_path / "docs", new=new, max_drop=0.2)
    assert code == ExitCode.OK
    assert "improved" in capsys.readouterr().out  # against the explicit (failing) file, not the passing baseline


# --- review of M1.14: a scorecard is never its own baseline
def test_the_new_scorecard_inside_the_baseline_dir_is_not_its_own_baseline(make_app, tmp_path: Path, capsys) -> None:
    base = tmp_path / "docs" / "live" / "eval"
    old = sample_card([impl("p", "add-shelf-code", "fail")], started_at="2026-10-05T10:00:00Z")
    (base / "2026-10-05").mkdir(parents=True)
    (base / "2026-10-05" / "scorecard.json").write_text(canonical_json(old))
    new_card = sample_card([impl("p", "add-shelf-code", "pass")], started_at="2026-10-07T10:00:00Z")
    new = base / "2026-10-07" / "scorecard.json"  # `--out docs/eval/<date>`, the natural place
    new.parent.mkdir()
    new.write_text(canonical_json(new_card))
    copy = base / "copy" / "scorecard.json"  # the same run copied in before the gate
    copy.parent.mkdir()
    copy.write_text(canonical_json(new_card))
    assert find_baseline(base, "s" * 64, exclude=new, before="2026-10-07T10:00:00Z") == base / "2026-10-05" / (
        "scorecard.json"
    )
    code = run_eval(make_app(), deps=Deps(), baseline_dir=base, new=new, max_drop=0.2)
    assert code == ExitCode.OK and "improved" in capsys.readouterr().out  # against 10-05, not itself


def test_an_incomplete_baseline_is_skipped(tmp_path: Path) -> None:
    good = put(tmp_path, "complete", "2026-10-01T10:00:00Z")
    partial = put(tmp_path, "partial", "2026-10-05T10:00:00Z")
    doc = json.loads(partial.read_text())
    partial.write_text(canonical_json({**doc, "complete": False}))
    assert find_baseline(tmp_path, "s" * 64) == good
