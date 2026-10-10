import math

from ._tune import load

tune = load("laya_tune")


def test_wilson_lower_bound_matches_known_values():
    assert math.isclose(tune.wilson_lower(0, 0), 0.0)
    assert math.isclose(tune.wilson_lower(10, 10), 0.7225, abs_tol=1e-3)
    assert math.isclose(tune.wilson_lower(100, 100), 0.9630, abs_tol=1e-3)


def test_wilson_threshold_fit():
    # 100 rows with score 0.9 all correct, 40 rows at 0.5 half right: the lowest score whose accepted set has a lower
    # bound of 0.95 is 0.9
    samples = [(0.9, True)] * 100 + [(0.5, True)] * 20 + [(0.5, False)] * 20
    assert tune.wilson_threshold(samples) == 0.9
    # too few rows to be sure: no threshold
    assert tune.wilson_threshold([(0.9, True)] * 10) is None
    # a wrong answer at the top score blocks the 0.9 threshold
    assert tune.wilson_threshold([(0.9, True)] * 50 + [(0.9, False)] * 50) is None
    assert tune.wilson_threshold([]) is None


def test_thresholds_for_noul_have_both_sides_and_choice_only_accept():
    rows = (
        [{"qid": "q", "type": "noul", "p_true": 0.97, "truth": True}] * 100
        + [{"qid": "q", "type": "noul", "p_true": 0.03, "truth": False}] * 100
        + [{"qid": "c", "type": "choice", "confidence": 0.9, "correct": True}] * 100
    )
    out = tune.fit_thresholds(rows)
    assert out["q"] == {"type": "noul", "accept": 0.97, "reject": 0.03, "n": 200}
    assert out["c"] == {"type": "choice", "accept": 0.9, "reject": None, "n": 100}
