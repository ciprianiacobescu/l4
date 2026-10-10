import json
import os
import random
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from l4.exitcodes import ExitCode
from l4.outcome import Outcome, UnitOutcome, new_run_id, write_outcome
from l4.redact import Redactor

TOKEN = "ghp_" + "a1B2c3D4e5" * 3


def unit(**over):
    base = {
        "unit": "openspec:add-login", "phase_before": "implementing", "phase_after": "awaiting_human",
        "tasks": {"done": 4, "total": 7}, "open_questions": ["Q-002"], "verdict": None,
        "profiles": {"implementer": "claude-sonnet"}, "cost_usd": 1.84, "iteration": 3,
        "pr_url": None, "retry_after": None, "continuation": "not_needed", "exit_reason": None,
    }  # fmt: skip
    return {**base, **over}


def outcome(**over):
    base = {"run_id": "r-20261003T1312Z-7f3a", "harness_version": "0.1.0", "exit_code": 11, "units": [unit()]}
    return {**base, **over}


def test_outcome_schema_rejects_bad_continuation_and_exit_code():
    Outcome.model_validate(outcome())
    with pytest.raises(ValidationError, match="continuation"):
        Outcome.model_validate(outcome(units=[unit(continuation="maybe")]))
    with pytest.raises(ValidationError, match="exit_code"):
        Outcome.model_validate(outcome(exit_code=7))
    with pytest.raises(ValidationError):
        Outcome.model_validate(outcome(units=[unit(surprise=1)]))


def test_dump_matches_spec_shape():
    dumped = Outcome.model_validate(outcome()).model_dump(mode="json", by_alias=True)
    assert dumped["schema"] == "l4/outcome@1"
    assert dumped["exit_code"] == 11 and isinstance(dumped["exit_code"], int)
    assert set(dumped) == {"schema", "run_id", "harness_version", "harness_commit", "exit_code", "units"}
    assert set(dumped["units"][0]) == set(unit())


def test_new_run_id_format():
    now = datetime(2026, 10, 3, 13, 12, 59, tzinfo=UTC)
    run_id = new_run_id(now, random.Random(7))
    assert run_id.startswith("r-20261003T1312Z-") and len(run_id.split("-")[-1]) == 4
    assert new_run_id(now, random.Random(7)) == run_id
    assert new_run_id().startswith("r-")


def test_write_outcome_is_atomic_and_redacted(tmp_path: Path, monkeypatch):
    out_dir = tmp_path / ".l4-out"
    model = Outcome.model_validate(outcome(units=[unit(profiles={"implementer": f"leak {TOKEN}"})]))
    path = write_outcome(model, out_dir, Redactor({}))
    assert path == out_dir / "outcome.json"
    text = path.read_text(encoding="utf-8")
    assert TOKEN not in text
    assert json.loads(text)["schema"] == "l4/outcome@1"
    assert sorted(p.name for p in out_dir.iterdir()) == [".gitignore", "outcome.json"]  # no temp file left behind

    # a failure between write and rename leaves the old file whole and no temp file behind
    before = path.read_text(encoding="utf-8")

    def broken_replace(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", broken_replace)
    with pytest.raises(OSError):
        write_outcome(Outcome.model_validate(outcome(exit_code=1)), out_dir, Redactor({}))
    assert path.read_text(encoding="utf-8") == before
    assert sorted(p.name for p in out_dir.iterdir()) == [".gitignore", "outcome.json"]  # no temp file left behind


def test_exit_code_enum_is_accepted_directly():
    assert Outcome.model_validate(outcome(exit_code=ExitCode.HALTED)).exit_code == 13


def test_unit_outcome_defaults_are_complete():
    u = UnitOutcome(unit="openspec:x", phase_before="a", phase_after="b")
    assert u.tasks.total == 0 and u.continuation == "not_needed" and u.open_questions == []


def test_write_outcome_refuses_a_symlinked_output_directory(tmp_path: Path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    link = tmp_path / ".l4-out"
    link.symlink_to(elsewhere)
    with pytest.raises(OSError, match="symlink"):
        write_outcome(Outcome.model_validate(outcome()), link, Redactor({}))
    assert list(elsewhere.iterdir()) == []


def test_plan_before_init_leaves_git_status_clean(make_repo, raw, git_environ):
    """A8 (M1.8): a repository that has no `.gitignore` entry for `.l4-out/` yet (init has not run) stays clean: the
    directory ignores itself, from the moment the CLI creates it."""
    from l4.cli import main

    repo = make_repo()
    main(["plan", "--repo", str(repo)], environ=git_environ)
    assert (repo / ".l4-out" / "outcome.json").is_file()  # the command did write there
    assert (repo / ".l4-out" / ".gitignore").read_text() == "*\n"
    assert raw(repo, "status", "--porcelain", "--untracked-files=all") == ""


def test_seal_out_dir_is_idempotent_keeps_a_human_gitignore_and_never_raises(tmp_path):
    from l4.fsutil import seal_out_dir

    out = tmp_path / ".l4-out"
    seal_out_dir(out)
    seal_out_dir(out)
    assert (out / ".gitignore").read_text() == "*\n"
    (out / ".gitignore").write_text("# mine\n")
    seal_out_dir(out)
    assert (out / ".gitignore").read_text() == "# mine\n"  # not overwritten
    linked = tmp_path / "linked"
    linked.symlink_to(tmp_path / "elsewhere")
    seal_out_dir(linked)  # a symlink is never followed, and nothing raises
    assert not (tmp_path / "elsewhere").exists()
    (tmp_path / "file").write_text("x")
    seal_out_dir(tmp_path / "file" / "sub")  # an OSError is ignored


def test_write_outcome_seals_its_directory_too(tmp_path):
    out = tmp_path / ".l4-out"
    write_outcome(Outcome.model_validate(outcome()), out, Redactor({}))
    assert (out / ".gitignore").read_text() == "*\n"
