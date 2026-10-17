from pathlib import Path

from l4.config.schema import L4Config
from l4.doctor import checks_spec as spec
from l4.doctor.registry import REGISTRY, load_check_modules

REQUIREMENTS = "### Requirement 1: A\n\n#### Acceptance Criteria\n\n1. WHEN a, THE System SHALL b.\n"


def kiro(repo: Path, name: str, tasks: str, requirements: str | None = REQUIREMENTS) -> None:
    directory = repo / ".kiro" / "specs" / name
    directory.mkdir(parents=True)
    (directory / "tasks.md").write_text(tasks)
    (directory / "design.md").write_text("# Design\n")
    if requirements is not None:
        (directory / "requirements.md").write_text(requirements)


GOOD = "- [ ] 1. A\n  - [ ] 1.1 do it\n    - _Requirements: 1.1_\n"
NO_LINK = "- [ ] 1. A\n  - [ ] 1.1 do it\n  - [ ] 1.2 [docs] write it up\n"


def test_the_checks_are_registered_by_the_check_modules():
    load_check_modules()
    ids = {c.id: c for c in REGISTRY.checks()}
    assert {"SPEC-001", "SPEC-002", "SPEC-004"} <= set(ids)
    assert ids["SPEC-001"].severity == "error" and not ids["SPEC-001"].unit_aware
    assert ids["SPEC-002"].unit_aware and ids["SPEC-004"].unit_aware
    assert ids["SPEC-004"].severity == "warn"


def test_spec_001_needs_a_framework(make_ctx):
    ctx, _ = make_ctx()
    result = spec.SPEC_001.run(ctx)
    assert result.status == "fail" and "no spec framework" in result.message
    kiro(ctx.repo, "greet", GOOD)
    result = spec.SPEC_001.run(ctx)
    assert result.status == "pass" and "kiro" in result.message


def test_spec_001_reports_legacy_openspec_as_an_error_and_spec_kit_as_information(make_ctx):
    ctx, _ = make_ctx()
    (ctx.repo / "openspec" / "changes" / "x").mkdir(parents=True)
    (ctx.repo / "openspec" / "project.md").write_text("# old\n")
    kiro(ctx.repo, "greet", GOOD)
    (ctx.repo / ".specify" / "memory").mkdir(parents=True)
    (ctx.repo / ".specify" / "memory" / "constitution.md").write_text("# c\n")
    result = spec.SPEC_001.run(ctx)
    assert result.status == "fail" and "OpenSpec < 1.0 layout; run the OpenSpec migration" in result.message
    assert "Spec Kit: detected, not driven" in result.message


def test_spec_kit_alone_is_not_a_framework(make_ctx):
    ctx, _ = make_ctx()
    (ctx.repo / ".specify" / "templates").mkdir(parents=True)
    result = spec.SPEC_001.run(ctx)
    assert result.status == "fail" and "Spec Kit: detected, not driven" in result.message


def test_spec_002_validates_kiro_units_and_follows_unit(make_ctx):
    ctx, _ = make_ctx()
    kiro(ctx.repo, "good", GOOD)
    kiro(ctx.repo, "broken", GOOD, requirements=None)
    result = spec.SPEC_002.run(ctx)
    assert result.status == "fail" and "kiro:broken" in result.message and "kiro:good" not in result.message
    only_good = spec.SPEC_002.run(_with_unit(ctx, "kiro:good"))
    assert only_good.status == "pass"
    openspec_unit = spec.SPEC_002.run(_with_unit(ctx, "openspec:x"))
    assert openspec_unit.status == "skip"


def test_spec_002_skips_without_a_kiro_unit(make_ctx):
    ctx, _ = make_ctx()
    assert spec.SPEC_002.run(ctx).status == "skip"


def test_spec_004_names_leaves_without_requirements_but_not_exempt_ones(make_ctx):
    ctx, _ = make_ctx()
    kiro(ctx.repo, "linked", GOOD)
    kiro(ctx.repo, "loose", NO_LINK)
    result = spec.SPEC_004.run(ctx)
    assert result.status == "fail"
    assert "kiro:loose: 1.1" in result.message and "1.2" not in result.message and "kiro:linked" not in result.message
    assert spec.SPEC_004.run(_with_unit(ctx, "kiro:linked")).status == "pass"


def test_spec_004_follows_the_configured_root(make_ctx):
    cfg = L4Config.model_validate({"spec": {"kiro": {"root": "kiro-specs"}}})
    ctx, _ = make_ctx(cfg=cfg)
    directory = ctx.repo / "kiro-specs" / "x"
    directory.mkdir(parents=True)
    (directory / "tasks.md").write_text(NO_LINK)
    assert spec.SPEC_004.run(ctx).status == "fail"


def _with_unit(ctx, unit):
    import dataclasses

    return dataclasses.replace(ctx, unit=unit)


def test_spec_002_reads_dotted_criteria_and_names_the_expected_form_when_none_are_read(make_ctx):
    ctx, _ = make_ctx()
    dotted = "### Requirement 1\n\n#### Acceptance Criteria\n\n1.1. WHEN a, THEN b.\n"
    kiro(ctx.repo, "dotted", GOOD, requirements=dotted)
    assert spec.SPEC_002.run(ctx).status == "pass"
    ctx2, _ = make_ctx()
    kiro(ctx2.repo, "prose", GOOD, requirements="### Requirement 1\n\nWHEN a, THEN b.\n")
    result = spec.SPEC_002.run(ctx2)
    assert result.status == "fail"
    assert "no acceptance criteria were read from requirements.md" in result.message
    assert "`#### Acceptance Criteria`" in result.message and "1.1. WHEN" in result.message


def test_spec_002_names_the_expected_form_for_a_cited_requirement_with_no_criterion_read(make_ctx):
    ctx, _ = make_ctx()
    two = REQUIREMENTS + "\n### Requirement 2: B\n\n#### Acceptance Criteria\n\nWHEN c, THE System SHALL d.\n"
    tasks = "- [ ] 1. A\n  - [ ] 1.1 do it\n    - _Requirements: 1.1_\n  - [ ] 1.2 more\n    - _Requirements: 2.1_\n"
    kiro(ctx.repo, "half", tasks, requirements=two)
    result = spec.SPEC_002.run(ctx)
    assert result.status == "fail"
    assert "cites _Requirements: 2.1_, which no criterion has" in result.message
    assert "no acceptance criterion was read under Requirement 2" in result.message and "1.1. WHEN" in result.message
    assert "_Requirements: 1.1_" not in result.message  # requirement 1 is read: no hint, no error


def test_spec_004_lists_pending_leaves_only_not_finished_history(make_ctx):
    """L4-KSP-006: a done leaf without a link is history, so SPEC-004 does not list it."""
    ctx, _ = make_ctx()
    kiro(ctx.repo, "hist", "- [x] 1.1 done long ago\n- [ ] 1.2 pending\n")
    result = spec.SPEC_004.run(ctx)
    assert result.status == "fail" and "kiro:hist: 1.2" in result.message and "1.1" not in result.message
