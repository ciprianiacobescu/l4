import json

import pytest

from l4.s1 import export

from ._tune import load

tune = load("laya_tune")

NOUL = {"type": "noul", "instructions": "q", "criteria": {"true": "t", "false": "f"}}
CHOICE = {"type": "choice", "instructions": "q", "criteria": {"a": "x", "b": "y", "c": "z"}}
SCORE = {"type": "score", "instructions": "q", "criteria": ["l0", "l1", "l2", "l3"]}


def test_gold_from_expected_and_refuses_bad_manifest(tmp_path):
    assert tune.gold_probabilities(NOUL, True) == {"probabilities": {"true": 1.0, "false": 0.0}}
    assert tune.gold_probabilities(NOUL, False) == {"probabilities": {"true": 0.0, "false": 1.0}}
    assert tune.gold_probabilities(CHOICE, "b") == {"probabilities": {"a": 0.0, "b": 1.0, "c": 0.0}}
    assert tune.gold_probabilities(SCORE, 2) == {"probabilities": {"0": 0.0, "1": 0.0, "2": 1.0, "3": 0.0}}
    with pytest.raises(ValueError):
        tune.gold_probabilities(CHOICE, "nope")
    with pytest.raises(ValueError):
        tune.gold_probabilities(SCORE, 9)

    manifest = {"counts": {"label_source": {"deterministic:scope": 3, "human:audit": 1}}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    assert tune.check_manifest(tmp_path)["counts"]["label_source"]["human:audit"] == 1
    for bad in ("s1:jev", "judge:claude", "jev", "deterministic:scope-x"):
        manifest["counts"]["label_source"][bad] = 1
        (tmp_path / "manifest.json").write_text(json.dumps(manifest))
        with pytest.raises(ValueError, match="label source"):
            tune.check_manifest(tmp_path)
        del manifest["counts"]["label_source"][bad]
    (tmp_path / "manifest.json").unlink()
    with pytest.raises(ValueError, match="manifest"):
        tune.check_manifest(tmp_path)


def test_allow_list_is_the_harness_allow_list():
    assert tuple(tune.ALLOWED_SOURCES) == export.ALLOWED_SOURCES


def test_base_spec_needs_a_pinned_revision():
    assert tune.parse_base("typed-decisions@" + "a" * 40) == ("typed-decisions", "a" * 40)
    for bad in ("typed-decisions", "typed-decisions@main", "gpt@" + "a" * 40, "@" + "a" * 40):
        with pytest.raises(ValueError):
            tune.parse_base(bad)
