from l4.vcs.trailers import CommitTrailers, render


def test_render_follows_the_spec_order_with_step_last():
    t = CommitTrailers(
        unit="openspec:a", run_id="r-1", iteration=2, phase="implementing", task="1.1", tdd="red",
        agent="codex/m", fallback_from="x", step="1.1/red/1",
    )  # fmt: skip
    assert [k for k, _ in render(t)] == [
        "L4-Unit", "L4-Run", "L4-Iteration", "L4-Phase", "L4-Task", "L4-TDD", "L4-Agent", "L4-Fallback-From", "L4-Step",
    ]  # fmt: skip
    minimal = CommitTrailers(unit="openspec:a", run_id="r-1", iteration=2, phase="implementing")
    assert render(minimal) == [
        ("L4-Unit", "openspec:a"), ("L4-Run", "r-1"), ("L4-Iteration", "2"), ("L4-Phase", "implementing")
    ]  # fmt: skip
