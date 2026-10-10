import json

from ._tune import S1, load

tune = load("laya_tune")


def test_policy_valid_and_engine_free():
    text = (S1 / "gates.json").read_text()
    policy = json.loads(text)
    assert set(policy) == {"version", "rules"} and policy["version"] == 1
    for rule in policy["rules"]:
        assert set(rule) == {"slice", "metric", "min_count", "min"}
        assert rule["min_count"] == 30
        (dimension,) = rule["slice"]
        assert dimension == "qid"
    for engine in ("jev", "laya", "typed-decisions", "english"):
        assert engine not in text.lower()
    assert tune.policy_qids(policy) == sorted({r["slice"]["qid"] for r in policy["rules"]})


def test_improvement_rule_is_noul_accuracy_by_at_least_five_points():
    assert tune.improves(0.70, 0.76) is True
    assert tune.improves(0.70, 0.74) is False
    assert tune.improves(None, 0.9) is False
