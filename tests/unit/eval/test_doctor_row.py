"""L4-EVAL-026: `l4 doctor` reminds, as a warning, that a template changed since the last eval baseline."""

import json
from pathlib import Path

from l4 import templatelock
from l4.doctor.registry import REGISTRY, exit_code, load_check_modules, run_checks
from l4.eval.scorecard import canonical_json

from ._cards import sample_card


def baseline(repo: Path, name: str, started: str, templates: dict) -> None:
    card = sample_card(started_at=started, templates=templates)
    path = repo / "docs" / "eval" / name / "scorecard.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(card))


def current() -> dict:
    return json.loads(json.dumps(templatelock.current()))


def row(make_ctx):
    load_check_modules()
    ctx, _ = make_ctx()
    return ctx, next(c for c in REGISTRY.checks() if c.id == "EVAL-001")


def test_the_row_is_a_registered_warning(make_ctx) -> None:
    _, check = row(make_ctx)
    assert check.severity == "warn" and "template" in check.title.lower()


def test_no_baseline_directory_skips(make_ctx) -> None:
    ctx, check = row(make_ctx)
    assert check.run(ctx).status == "skip"


def test_a_baseline_with_the_current_templates_passes(make_ctx) -> None:
    ctx, check = row(make_ctx)
    baseline(ctx.repo, "2026-10-07", "2026-10-07T10:00:00Z", current())
    result = check.run(ctx)
    assert result.status == "pass" and "up to date" in result.message


def test_a_changed_template_warns_and_names_the_command(make_ctx) -> None:
    ctx, check = row(make_ctx)
    old = current()
    old["implementer/red"] = {"version": 1, "sha256": "0" * 64}
    baseline(ctx.repo, "2026-10-07", "2026-10-07T10:00:00Z", old)
    result = check.run(ctx)
    assert result.status == "fail" and "a template changed since the last eval baseline" in result.message
    assert "implementer/red" in result.message and result.fix_hint == "l4 eval --compare"


def test_a_body_changed_without_a_version_bump_also_warns(make_ctx) -> None:
    ctx, check = row(make_ctx)
    old = current()
    old["judge"] = {**old["judge"], "sha256": "f" * 64}
    baseline(ctx.repo, "2026-10-07", "2026-10-07T10:00:00Z", old)
    assert check.run(ctx).status == "fail"


def test_only_the_newest_baseline_counts(make_ctx) -> None:
    ctx, check = row(make_ctx)
    stale = current()
    stale["judge"] = {"version": 1, "sha256": "0" * 64}
    baseline(ctx.repo, "2026-10-01", "2026-10-01T10:00:00Z", stale)
    baseline(ctx.repo, "2026-10-07", "2026-10-07T10:00:00Z", current())
    assert check.run(ctx).status == "pass"


def test_an_unreadable_baseline_is_skipped_not_a_crash(make_ctx) -> None:
    ctx, check = row(make_ctx)
    path = ctx.repo / "docs" / "eval" / "x" / "scorecard.json"
    path.parent.mkdir(parents=True)
    path.write_text("{nope")
    assert check.run(ctx).status == "skip"


def test_a_reminder_never_turns_doctor_red(make_ctx) -> None:
    ctx, _ = row(make_ctx)
    old = current()
    old["judge"] = {"version": 1, "sha256": "0" * 64}
    baseline(ctx.repo, "2026-10-07", "2026-10-07T10:00:00Z", old)
    outcomes = run_checks(ctx, only={"EVAL-001"})
    assert [o.status for o in outcomes] == ["fail"] and outcomes[0].severity == "warn"
    assert exit_code(outcomes).value == 0


def test_baselines_live_under_docs_eval_not_docs_live(make_ctx) -> None:
    """Baselines are committed under `docs/eval/<run>/` (next to its README: how to run, how to compare, the first
    baseline); `docs/live/` holds the evidence of live runs only, and a scorecard there is not a baseline."""
    ctx, check = row(make_ctx)
    old = current()
    old["judge"] = {"version": 1, "sha256": "0" * 64}
    path = ctx.repo / "docs" / "live" / "eval" / "2026-10-07" / "scorecard.json"
    path.parent.mkdir(parents=True)
    path.write_text(canonical_json(sample_card(started_at="2026-10-07T10:00:00Z", templates=old)))
    result = check.run(ctx)
    assert result.status == "skip" and "docs/eval/" in result.message
