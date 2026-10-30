"""L4-ADO-007: a single OpenSpec unit is validated strictly before any agent runs (SCN-ADO-20, -21, -22)."""

import logging

from l4.agents.fake import Step
from l4.specs.base import OpenSpecCommandError
from l4.specs.openspec import ARCHIVE_REFUSAL, OpenSpecCli, intake_hint

from ..implementer.conftest import blocked_step, green_step, red_step
from ..specs.fixcli import patch_openspec
from .conftest import UNIT_DIR, new_origin_main

SPEC = f"{UNIT_DIR}/specs/pricing/spec.md"
MISSING = f"{ARCHIVE_REFUSAL} dreaming: target spec does not exist; only ADDED requirements are allowed."
NO_PURPOSE = (
    "## ADDED Requirements\n\n### Requirement: Discount codes\nSAVE10 is a known code.\n\n"
    '#### Scenario: Known code\n- **WHEN** `apply_discount(50.0, "SAVE10")` is called\n- **THEN** it returns `45.0`\n'
)


def test_a_strict_validation_error_rejects_the_unit_with_the_hint_before_any_agent(run_l4, monkeypatch):  # SCN-ADO-20
    patch_openspec(monkeypatch, valid=False, message=MISSING)
    run = run_l4([red_step(), green_step()])
    assert run.code == 14 and run.adapter.requests == []
    (event,) = run.local_events("unit.rejected")
    reasons = "\n".join(event["reasons"])
    assert MISSING in reasons and intake_hint(MISSING, "main") in reasons
    assert run.local_events("task.started") == []


def test_every_reason_is_recorded_and_the_purpose_is_one_of_them(run_l4, monkeypatch, tdd_repo, raw):
    patch_openspec(monkeypatch, valid=False, message="MODIFIED omits scenario(s): one. Copy the omitted scenarios")
    new_origin_main(tdd_repo, raw, {SPEC: NO_PURPOSE})
    run = run_l4([Step()])
    assert run.code == 14 and run.adapter.requests == []
    (event,) = run.local_events("unit.rejected")
    assert len(event["reasons"]) == 2
    assert "Copy the omitted scenarios" in event["reasons"][0] and "Purpose" in event["reasons"][1]


def test_a_new_capability_without_a_purpose_is_rejected(run_l4, monkeypatch, tdd_repo, raw):  # SCN-ADO-21
    patch_openspec(monkeypatch)
    new_origin_main(tdd_repo, raw, {SPEC: NO_PURPOSE})
    run = run_l4([red_step(), green_step()])
    assert run.code == 14 and run.adapter.requests == []
    (event,) = run.local_events("unit.rejected")
    assert len(event["reasons"]) == 1 and "Purpose" in event["reasons"][0] and "pricing" in event["reasons"][0]


def test_a_valid_change_starts_as_before(run_l4, monkeypatch):  # SCN-ADO-22
    patch_openspec(monkeypatch)
    run = run_l4([red_step(), green_step()])
    assert run.code == 0 and run.local_events("unit.rejected") == []
    assert run.local_events("task.started")


def test_a_unit_already_awaiting_a_person_is_not_rejected_by_the_new_check(run_l4, monkeypatch, tdd_repo, raw):
    first = run_l4([blocked_step()])
    assert first.code == 11
    patch_openspec(monkeypatch, valid=False, message=MISSING)  # the spec went invalid while the unit waited
    new_origin_main(tdd_repo, raw, {SPEC: NO_PURPOSE})
    again = run_l4([red_step(), green_step()])
    assert again.code != 14 and again.local_events("unit.rejected") == []


def test_a_validation_that_raises_is_a_recorded_rejection_not_a_crash(run_l4, monkeypatch):
    def boom(self, *args):
        raise OpenSpecCommandError("`openspec validate x`: the CLI died")

    monkeypatch.setattr(OpenSpecCli, "run_json", boom)
    run = run_l4([red_step(), green_step()])
    assert run.code == 14 and run.adapter.requests == []
    (event,) = run.local_events("unit.rejected")
    assert "the CLI died" in "\n".join(event["reasons"])


MIGRATION = "app/migrations/0001_initial.py"
FORBIDDEN_TASK = f"\n- [ ] 9.1 Create `{MIGRATION}` for the new table\n"


def with_forbidden_task(tdd_repo) -> dict[str, str]:
    return {f"{UNIT_DIR}/tasks.md": (tdd_repo.repo / UNIT_DIR / "tasks.md").read_text() + FORBIDDEN_TASK}


def test_a_task_that_names_a_forbidden_file_rejects_the_unit_before_any_agent(run_l4, monkeypatch, tdd_repo, raw):
    patch_openspec(monkeypatch)  # SCN-YOLO-251
    new_origin_main(tdd_repo, raw, with_forbidden_task(tdd_repo))
    run = run_l4([red_step(), green_step()])
    assert run.code == 14 and run.adapter.requests == []
    (event,) = run.local_events("unit.rejected")
    (reason,) = event["reasons"]
    assert reason.startswith(f"forbidden_path: task 9.1 names {MIGRATION}, which odd.forbidden_paths rule ")
    assert "**/migrations/**" in reason and "have a person commit" in reason
    assert run.local_events("task.started") == []


def test_the_forbidden_path_reason_comes_with_the_validation_errors(run_l4, monkeypatch, tdd_repo, raw):
    patch_openspec(monkeypatch, valid=False, message=MISSING)
    new_origin_main(tdd_repo, raw, with_forbidden_task(tdd_repo))
    run = run_l4([Step()])
    (event,) = run.local_events("unit.rejected")
    assert len(event["reasons"]) == 2
    assert MISSING in event["reasons"][0] and event["reasons"][1].startswith("forbidden_path: task 9.1 names")


def test_a_unit_already_implementing_is_not_rejected_for_a_forbidden_path(run_l4, monkeypatch, tdd_repo, raw):
    first = run_l4([blocked_step()])
    assert first.code == 11  # SCN-YOLO-251: the unit is awaiting a person, not in an intake phase
    patch_openspec(monkeypatch)
    new_origin_main(tdd_repo, raw, with_forbidden_task(tdd_repo))
    again = run_l4([red_step(), green_step()])
    assert again.code != 14 and again.local_events("unit.rejected") == []


def fake_orchestrator(tmp_path, phase, tasks=f"- [ ] 9.1 Create `{MIGRATION}`\n", git=None):
    from types import SimpleNamespace

    from l4.config.defaults import FORBIDDEN_PATHS, SCOPE_EXEMPT, TEST_GLOBS, TEST_SUPPORT_GLOBS
    from l4.specs.base import Framework, UnitRef

    folder = tmp_path / "openspec" / "changes" / "x"
    folder.mkdir(parents=True)
    (folder / "tasks.md").write_text(tasks)
    ref = UnitRef(Framework.OPENSPEC, "x", folder)
    services = SimpleNamespace(ref=ref, worktree=tmp_path, git=git)
    return SimpleNamespace(
        services=services,
        state=SimpleNamespace(phase=phase),
        cfg=SimpleNamespace(
            odd=SimpleNamespace(forbidden_paths=FORBIDDEN_PATHS),
            tdd=SimpleNamespace(test_globs=TEST_GLOBS, test_support_globs=TEST_SUPPORT_GLOBS),
            verifier=SimpleNamespace(evidence=SimpleNamespace(scope_exempt=SCOPE_EXEMPT)),
        ),
    )


def forbidden_reasons(fake):
    from l4.orchestrator import Orchestrator

    return Orchestrator._forbidden_reasons(fake)


def test_only_the_phases_before_implementing_are_checked(tmp_path):  # SCN-YOLO-251
    from l4.state.lifecycle import Phase

    git = _TrackedNothing()
    for phase in (None, Phase.INTAKE, Phase.READY):
        assert len(forbidden_reasons(fake_orchestrator(tmp_path / str(phase), phase, git=git))) == 1, phase
    for phase in (Phase.IMPLEMENTING, Phase.AWAITING_HUMAN, Phase.CLARIFYING, Phase.VERIFYING, Phase.FIXING):
        assert forbidden_reasons(fake_orchestrator(tmp_path / str(phase), phase, git=git)) == [], phase


class _TrackedNothing:
    """A `Git` whose HEAD tracks no file at all."""

    def run_bytes(self, *args, **kwargs):
        return b""


def test_an_untracked_file_in_the_unit_worktree_does_not_count_as_existing(tmp_path):
    (tmp_path / "app" / "migrations").mkdir(parents=True)
    (tmp_path / MIGRATION).write_text("# untracked\n")
    fake = fake_orchestrator(tmp_path, None, git=_TrackedNothing())
    (reason,) = forbidden_reasons(fake)
    assert reason.startswith(f"forbidden_path: task 9.1 names {MIGRATION},")


def test_a_file_tracked_at_head_is_a_warning_not_a_reason(tmp_path):
    class Tracked:
        def run_bytes(self, *args, **kwargs):
            return MIGRATION.encode() + b"\0"

    assert forbidden_reasons(fake_orchestrator(tmp_path, None, git=Tracked())) == []


DOCS_TASK = "\n- [ ] 9.1 Write the client fixtures `docs/waitlist/fixtures/*.json`\n"


def test_a_docs_task_under_a_test_glob_logs_a_warning_and_the_unit_starts(  # SCN-YOLO-260
    run_l4, monkeypatch, tdd_repo, raw, capsys
):
    patch_openspec(monkeypatch)
    new_origin_main(
        tdd_repo, raw, {f"{UNIT_DIR}/tasks.md": (tdd_repo.repo / UNIT_DIR / "tasks.md").read_text() + DOCS_TASK}
    )
    run = run_l4([red_step(), green_step()])
    assert run.code != 14 and run.local_events("unit.rejected") == []
    err = capsys.readouterr().err  # the run's console log
    assert "test_path: openspec:add-discount-codes: task 9.1 names docs/waitlist/fixtures/," in err


def test_only_the_phases_before_implementing_log_the_test_path_warning(tmp_path, caplog):
    from l4.orchestrator import Orchestrator
    from l4.state.lifecycle import Phase

    caplog.set_level(logging.WARNING, logger="l4")
    tasks = "- [ ] 9.1 Write `docs/waitlist/fixtures/a.json`\n"
    fake = fake_orchestrator(tmp_path / "a", Phase.INTAKE, tasks=tasks)
    Orchestrator._warn_test_paths(fake)
    assert "test_path: " in caplog.text
    caplog.clear()
    Orchestrator._warn_test_paths(fake_orchestrator(tmp_path / "b", Phase.IMPLEMENTING, tasks=tasks))
    assert caplog.text == ""
