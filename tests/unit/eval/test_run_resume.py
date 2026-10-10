"""L4-EVAL-015: a 429 stops a profile for the rest of the run, and --resume skips what is already measured."""

import json
from pathlib import Path

from l4.eval.run import Deps
from l4.eval.seeds import seed_set_sha256

from ._fakerun import ScriptedRunner
from ._go import go
from ._ledgers import ev, green_ledger

LIMIT = [ev("availability.limit", tool="opencode", kind="rate_limit", source="s", excerpt="429")]


def results(out: Path) -> dict[str, dict]:
    return {p.parent.name: json.loads(p.read_text()) for p in sorted((out / "cells").glob("*/result.json"))}


def test_a_rate_limit_blocks_the_profile_for_the_rest_of_the_run(make_app, seeds_root: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"

    def behaviour(role, profile, unit):
        if profile == "p1":
            return LIMIT, None, 12, "Upstream request failed: Endpoint is unavailable"
        return green_ledger(), None, 0, "ok"

    scripted = ScriptedRunner(behaviour)
    go(
        make_app(), seeds_root, impl=("p1", "p2"), ref_judge="j1", out=out, dry_run=False, deps=Deps(runner=scripted)
    )  # fmt: skip
    ran = [(c["profile"], c["unit"]) for c in scripted.calls]
    assert ran == [
        ("p1", "add-reorder-quantity"),
        *[("p2", u) for u in ("add-reorder-quantity", "add-shelf-code", "add-tip-amount")],
    ]
    done = results(out)
    first = done["implementer-p1-add-reorder-quantity-k0"]
    assert first["status"] == "invalid" and first["invalid_reason"] == "rate_limited"
    for unit in ("add-shelf-code", "add-tip-amount"):
        skipped = done[f"implementer-p1-{unit}-k0"]
        assert skipped["status"] == "invalid" and skipped["invalid_reason"] == "skipped_after_rate_limit"
        assert skipped["errors"] == []
    assert all(
        done[f"implementer-p2-{u}-k0"]["status"] == "pass"
        for u in ("add-reorder-quantity", "add-shelf-code", "add-tip-amount")
    )


def test_the_block_holds_across_roles(make_app, seeds_root: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    scripted = ScriptedRunner(
        lambda role, profile, unit: (LIMIT, None, 12, "") if profile == "j2" else (green_ledger(), None, 0, "")
    )
    go(make_app(), seeds_root, judge=("j2",), out=out, dry_run=False, deps=Deps(runner=scripted))
    assert len(scripted.calls) == 1
    assert len(results(out)) == 4


def test_a_failure_that_is_not_a_limit_does_not_block(make_app, seeds_root: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    scripted = ScriptedRunner(
        lambda role, profile, unit: ([ev("breaker.tripped", reason="baseline_failed", detail="x")], None, 13, "")
    )
    go(make_app(), seeds_root, impl=("p1",), ref_judge="j1", out=out, dry_run=False, deps=Deps(runner=scripted))
    assert len(scripted.calls) == 3


def test_resume_skips_the_cells_that_have_a_result_for_this_seed_set(
    make_app, seeds_root: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    first = ScriptedRunner()
    go(
        make_app(),
        seeds_root,
        impl=("p1",),
        ref_judge="j1",
        units=("add-shelf-code",),
        out=out,
        dry_run=False,
        deps=Deps(runner=first),
    )
    second = ScriptedRunner()
    go(
        make_app(),
        seeds_root,
        impl=("p1",),
        ref_judge="j1",
        out=out,
        dry_run=False,
        resume=True,
        deps=Deps(runner=second),
    )
    assert [c["unit"] for c in second.calls] == ["add-reorder-quantity", "add-tip-amount"]
    assert len(results(out)) == 3


def test_without_resume_every_cell_runs_again(make_app, seeds_root: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    for _ in range(2):
        again = ScriptedRunner()
        go(
            make_app(),
            seeds_root,
            impl=("p1",),
            ref_judge="j1",
            units=("add-shelf-code",),
            out=out,
            dry_run=False,
            deps=Deps(runner=again),
        )
        assert len(again.calls) == 1


def test_a_result_of_another_seed_set_is_run_again(make_app, seeds_root: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    go(
        make_app(),
        seeds_root,
        impl=("p1",),
        ref_judge="j1",
        units=("add-shelf-code",),
        out=out,
        dry_run=False,
        deps=Deps(runner=ScriptedRunner()),
    )
    path = out / "cells" / "implementer-p1-add-shelf-code-k0" / "result.json"
    doc = json.loads(path.read_text())
    assert doc["seed_set_sha256"] == seed_set_sha256(seeds_root)
    path.write_text(json.dumps({**doc, "seed_set_sha256": "0" * 64}))
    again = ScriptedRunner()
    go(
        make_app(),
        seeds_root,
        impl=("p1",),
        ref_judge="j1",
        units=("add-shelf-code",),
        out=out,
        dry_run=False,
        resume=True,
        deps=Deps(runner=again),
    )
    assert len(again.calls) == 1


def test_a_corrupt_result_is_run_again(make_app, seeds_root: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    go(
        make_app(),
        seeds_root,
        impl=("p1",),
        ref_judge="j1",
        units=("add-shelf-code",),
        out=out,
        dry_run=False,
        deps=Deps(runner=ScriptedRunner()),
    )
    (out / "cells" / "implementer-p1-add-shelf-code-k0" / "result.json").write_text("{not json")
    again = ScriptedRunner()
    go(
        make_app(),
        seeds_root,
        impl=("p1",),
        ref_judge="j1",
        units=("add-shelf-code",),
        out=out,
        dry_run=False,
        resume=True,
        deps=Deps(runner=again),
    )
    assert len(again.calls) == 1


# --- review of M1.14: --resume runs again what was not measured, and never mixes environments
def test_resume_runs_again_the_cells_a_rate_limit_left_unmeasured(make_app, seeds_root: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    limited = ScriptedRunner(lambda role, profile, unit: (LIMIT, None, 12, ""))
    go(make_app(), seeds_root, impl=("p1",), ref_judge="j1", out=out, dry_run=False, deps=Deps(runner=limited))
    assert len(limited.calls) == 1  # the other two were skipped after the 429
    later = ScriptedRunner()  # the limit has reset
    go(
        make_app(), seeds_root, impl=("p1",), ref_judge="j1", out=out, dry_run=False, resume=True,
        deps=Deps(runner=later),
    )  # fmt: skip
    assert len(later.calls) == 3
    assert all(r["status"] == "pass" for r in results(out).values())
    card = json.loads((out / "scorecard.json").read_text())
    assert [c["status"] for c in card["cells"]] == ["pass"] * 3 and card["complete"] is True


def test_resume_after_a_busy_stop_runs_the_busy_cell(make_app, seeds_root: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    clock = {"now": 0.0}

    def tick(seconds: float) -> None:
        clock["now"] += seconds

    busy = Deps(runner=ScriptedRunner(), idle=lambda argv: 1, sleep=tick, clock=lambda: clock["now"])
    code = go(
        make_app(), seeds_root, impl=("p1",), ref_judge="j1", units=("add-shelf-code",), out=out, dry_run=False,
        idle_check="idle", idle_wait="1m", deps=busy,
    )  # fmt: skip
    assert code == 12 and results(out)["implementer-p1-add-shelf-code-k0"]["invalid_reason"] == "runner_busy"
    quiet = ScriptedRunner()
    code = go(
        make_app(), seeds_root, impl=("p1",), ref_judge="j1", units=("add-shelf-code",), out=out, dry_run=False,
        idle_check="idle", resume=True, deps=Deps(runner=quiet, idle=lambda argv: 0),
    )  # fmt: skip
    assert code == 0 and len(quiet.calls) == 1  # "resume with --resume" now does what it says
    assert results(out)["implementer-p1-add-shelf-code-k0"]["status"] == "pass"


def test_resume_does_not_reuse_a_cell_measured_in_another_environment(
    make_app, seeds_root: Path, tmp_path: Path
) -> None:
    """A CLI pin bump (or a template, harness or profile change) between the two runs: a reused cell would sit in a
    scorecard whose environment record is not the one it was measured in."""
    out = tmp_path / "out"
    kw = dict(impl=("p1",), ref_judge="j1", units=("add-shelf-code",), out=out, dry_run=False)
    go(make_app(), seeds_root, **kw, deps=Deps(runner=ScriptedRunner(), version_of=lambda a: "1.0.0"))
    same = ScriptedRunner()
    go(make_app(), seeds_root, **kw, resume=True, deps=Deps(runner=same, version_of=lambda a: "1.0.0"))
    assert same.calls == []
    bumped = ScriptedRunner()
    go(make_app(), seeds_root, **kw, resume=True, deps=Deps(runner=bumped, version_of=lambda a: "1.1.0"))
    assert len(bumped.calls) == 1


def test_resume_does_not_reuse_a_cell_measured_with_another_uv_or_probe_timeout(
    make_app, seeds_root: Path, tmp_path: Path
) -> None:
    """uv, OpenSpec and the kept `availability` section change what a cell does: they are in the environment record,
    so a cell measured under other ones runs again."""
    out = tmp_path / "out"
    kw = dict(impl=("p1",), ref_judge="j1", units=("add-shelf-code",), out=out, dry_run=False)
    uv1 = lambda environ: {"uv": "0.12.22", "openspec": "1.14.0"}  # noqa: E731
    go(make_app(), seeds_root, **kw, deps=Deps(runner=ScriptedRunner(), tools=uv1))
    card = json.loads((out / "scorecard.json").read_text())
    assert card["env"]["tools"] == {"uv": "0.12.22", "openspec": "1.14.0"}
    same = ScriptedRunner()
    go(make_app(), seeds_root, **kw, resume=True, deps=Deps(runner=same, tools=uv1))
    assert same.calls == []
    bumped = ScriptedRunner()
    uv2 = lambda environ: {"uv": "0.13.0", "openspec": "1.14.0"}  # noqa: E731
    go(make_app(), seeds_root, **kw, resume=True, deps=Deps(runner=bumped, tools=uv2))
    assert len(bumped.calls) == 1


def test_an_unavailable_reference_judge_stops_the_implementer_cells_not_the_profile(
    make_app, seeds_root: Path, tmp_path: Path
) -> None:
    """Live 2026-10-08: the fixed judge was not logged in. Every implementer cell would end the same way after the
    implementer's whole red and green, so the rest are skipped with their own reason; the implementer profile is not
    blocked (it did nothing wrong) and the judge cells, whose reference is the replay, still run."""
    out = tmp_path / "out"
    gone = ev("availability.unavailable", role="judges", required=True, retry_after="x",
              skipped=[{"profile": "j1", "step": "auth", "reason": "not logged in"}])  # fmt: skip

    def behaviour(role, profile, unit):
        if role == "implementer":
            return [*green_ledger()[:-2], gone], None, 12, ""
        return green_ledger(), None, 0, "ok"

    scripted = ScriptedRunner(behaviour)
    go(make_app(), seeds_root, impl=("p1", "p2"), judge=("j2",), ref_judge="j1", out=out, dry_run=False,
       deps=Deps(runner=scripted))  # fmt: skip
    ran = [(c["role"], c["profile"]) for c in scripted.calls]
    assert ran == [("implementer", "p1"), *[("judge", "j2")] * 4]
    done = results(out)
    assert done["implementer-p1-add-reorder-quantity-k0"]["invalid_reason"] == "reference_unavailable"
    skipped = [
        r for k, r in done.items() if k.startswith("implementer-") and k != "implementer-p1-add-reorder-quantity-k0"
    ]
    assert len(skipped) == 5 and {r["invalid_reason"] for r in skipped} == {"skipped_reference_unavailable"}
