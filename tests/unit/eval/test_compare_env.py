"""L4-EVAL-023: the delta report starts with what changed in the environment; scorecards of other seeds are refused."""

import copy

import pytest

from l4.eval.compare import SeedSetChanged, compare, env_diff

from ._cards import ENV, impl, sample_card


def changed(**over):
    env = copy.deepcopy(ENV)
    for key, value in over.items():
        env[key] = value
    return env


def card(cells=None, **env):
    return sample_card(cells, **env)


def test_no_change_is_an_empty_diff() -> None:
    assert env_diff(card(), card()) == []


def test_the_harness_commit_a_template_and_a_cli_version_show() -> None:
    new_env = changed(
        harness={"commit": "e" * 40, "dirty": True, "source": "git"},
        templates={"implementer/red": {"version": 6, "sha256": "x" * 64}, "judge": {"version": 6, "sha256": "j" * 64}},
        cli_versions={"p1": {"adapter": "opencode", "version": "1.5.0", "unrecorded": True},
                      "j1": {"adapter": "claude-code", "version": "2.1.288", "unrecorded": False}},
    )  # fmt: skip
    diff = env_diff(card(), card(**new_env))
    text = "\n".join(diff)
    assert "harness commit: d475e6b00000 -> eeeeeeeeeeee" in text and "dirty" in text
    assert "template implementer/red: v5 -> v6" in text and "judge" not in text
    assert "cli p1: opencode 1.4.2 -> opencode 1.5.0" in text and "j1" not in text.replace("judge", "")


def test_a_template_whose_body_changed_without_a_version_shows_the_hash() -> None:
    new = changed(
        templates={"implementer/red": {"version": 5, "sha256": "q" * 64}, "judge": {"version": 6, "sha256": "j" * 64}}
    )
    assert any("template implementer/red: v5 body changed" in line for line in env_diff(card(), card(**new)))


def test_model_vendor_options_and_machine_show() -> None:
    new = changed(
        profiles={
            "p1": {"adapter": "opencode", "model": "opencode/other", "vendor": "acme", "options": {"r": "high"}},
            "j1": {"adapter": "claude-code", "vendor": "anthropic"},
        },
        machine={"platform": "Linux-6.9", "cpus": 8, "runner": True},
    )  # fmt: skip
    text = "\n".join(env_diff(card(), card(**new)))
    assert "profile p1 model: opencode/big-pickle -> opencode/other" in text
    assert "profile p1 options" in text
    assert "machine platform: Linux-6.8-x86_64 -> Linux-6.9" in text


def test_a_profile_added_to_the_run_shows() -> None:
    new = changed(profiles={**ENV["profiles"], "p9": {"adapter": "codex"}})
    assert any("profile p9: added" in line for line in env_diff(card(), card(**new)))


def test_a_changed_seed_set_is_refused() -> None:
    old = card()
    new = card()
    new["seeds"] = {**new["seeds"], "sha256": "0" * 64}
    with pytest.raises(SeedSetChanged, match="the scorecards measure different seed sets"):
        compare(old, new, 0.2)


def test_a_changed_scorecard_schema_is_refused() -> None:
    old, new = card(), card()
    new["schema"] = "l4/eval-scorecard@2"
    with pytest.raises(SeedSetChanged, match="different seed sets"):
        compare(old, new, 0.2)


def test_allow_seed_change_reports_deltas_and_never_regressed() -> None:
    old = card([impl("p", "add-shelf-code", "pass"), impl("p", "add-tip-amount", "pass")])
    new = card([impl("p", "add-shelf-code", "fail"), impl("p", "add-tip-amount", "fail")])
    new["seeds"] = {**new["seeds"], "sha256": "0" * 64}
    result = compare(old, new, 0.2, allow_seed_change=True)
    (row,) = [r for r in result.rows if r["profile"] == "p"]
    assert row["delta"] == -1.0 and row["status"] == "delta" and result.regressed is False
    assert result.seed_changed is True


def test_the_comparison_carries_the_environment_diff() -> None:
    new = changed(harness={"commit": "e" * 40, "dirty": False, "source": "git"})
    assert compare(card(), card(**new), 0.2).env_diff == env_diff(card(), card(**new))
