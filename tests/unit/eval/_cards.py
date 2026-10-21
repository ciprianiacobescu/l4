"""A small scorecard for the render and compare tests."""

from typing import Any

from l4.eval.scorecard import build_scorecard, cell_result

ENV: dict[str, Any] = {
    "started_at": "2026-10-07T10:00:00Z",
    "harness": {"commit": "d475e6b0000000000000000000000000000000aa", "dirty": False, "source": "git"},
    "templates": {"implementer/red": {"version": 5, "sha256": "r" * 64}, "judge": {"version": 6, "sha256": "j" * 64}},
    "templates_lock_sha256": "l" * 64,
    "cli_versions": {"p1": {"adapter": "opencode", "version": "1.4.2", "unrecorded": False},
                     "j1": {"adapter": "claude-code", "version": "2.1.288", "unrecorded": False}},
    "profiles": {"p1": {"adapter": "opencode", "model": "opencode/big-pickle", "vendor": "acme"},
                 "j1": {"adapter": "claude-code", "vendor": "anthropic"}},
    "seed_set_sha256": "s" * 64, "k": 1, "cell_timeout_s": 3000.0,
    "machine": {"platform": "Linux-6.8-x86_64", "cpus": 8, "runner": True}, "python": "3.12.12",
}  # fmt: skip
SEEDS = {"sha256": "s" * 64, "units": ["add-late-fee", "add-reorder-quantity", "add-shelf-code", "add-tip-amount"]}


def impl(profile: str, unit: str, status: str, k: int = 0, wall: float = 10.0, **extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "role": "implementer", "profile": profile, "unit": unit, "k": k, "status": status, "wall_s": wall,
        "attempts": {"red": 1, "green": 1}, "verdict": "PASS", "returncode": 0,
    }  # fmt: skip
    if status == "invalid":
        base.update(invalid_reason="rate_limited", attempts=None, verdict=None,
                    errors=[{"kind": "rate_limit", "detail": "429"}])  # fmt: skip
    base.update(extra)
    return cell_result(base)


def judge(profile: str, unit: str, status: str, k: int = 0, wall: float = 5.0, **extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "role": "judge", "profile": profile, "unit": unit, "k": k, "status": status, "wall_s": wall,
        "verdict": "PASS", "expected_verdict": "PASS", "agreement": status == "pass", "findings": 0,
        "cost_usd": 0.0625, "returncode": 0,
    }  # fmt: skip
    base.update(extra)
    return cell_result(base)


def default_cells() -> list[dict[str, Any]]:
    return [
        impl("p1", "add-shelf-code", "pass", wall=107.0),
        impl("p1", "add-tip-amount", "pass", wall=143.0),
        impl(
            "p1",
            "add-reorder-quantity",
            "fail",
            wall=900.0,
            halted_at="green",
            attempts={"red": 1, "green": 3},
            verdict=None,
            errors=[{"kind": "schema", "detail": "result invalid: $.status: not one of the allowed values"}],
        ),  # fmt: skip
        impl("p1", "add-late-fee", "invalid"),
        judge(
            "j1",
            "add-late-fee",
            "pass",
            verdict="NEEDS_HUMAN",
            expected_verdict="NEEDS_HUMAN",
            findings=2,
            worst_severity="major",
        ),  # fmt: skip
        judge("j1", "add-shelf-code", "pass"),
        judge("j1", "add-tip-amount", "fail", verdict="NEEDS_HUMAN", findings=1, worst_severity="minor"),
    ]


def sample_card(cells: list[dict[str, Any]] | None = None, **env: Any) -> dict[str, Any]:
    return build_scorecard(default_cells() if cells is None else cells, {**ENV, **env}, SEEDS)
