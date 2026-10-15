"""review-resolution 3.1 (L4-YOLO-028, SCN-YOLO-67, the file part): the run writes `.l4/review-accepted.json`."""

import json
from pathlib import Path

import pytest

from l4 import orchestrator
from l4.orchestrator import ACCEPTED_FILE, write_accepted_carrier
from l4.vcs.git import Git
from l4.yolo.cycle import PlanStep
from l4.yolo.digest import is_excluded, unit_digest

from ..implementer.conftest import green_step, red_step
from .conftest import BRANCH, UNIT, UNIT_DIR, new_origin_main

ITEM = {
    "subject": f"openspec:{UNIT.split(':')[-1]}",
    "reason": "the rounding is the bank's",
    "by": "ada",
    "actor": "human",
    "findings": [
        {"id": "F-aaaaaa", "criterion": "pricing > Codes > Known", "severity": "major", "text": "no rounding rule"},
        {"id": "F-bbbbbb", "criterion": "pricing > Codes > Unknown", "severity": "minor", "text": "no empty-code case"},
    ],
}


def test_the_payload_has_sorted_keys_a_final_newline_and_the_schema(tmp_path: Path):
    assert write_accepted_carrier(tmp_path, "p1", (ITEM,)) is True
    raw = (tmp_path / ACCEPTED_FILE).read_bytes()
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    data = json.loads(raw)
    assert data == {"schema": "l4/review-accepted@1", "plan": "p1", "items": [ITEM]}
    assert raw.decode() == json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def test_unchanged_bytes_are_not_written_again(tmp_path: Path):
    write_accepted_carrier(tmp_path, "p1", (ITEM,))
    path = tmp_path / ACCEPTED_FILE
    before = path.stat().st_mtime_ns
    assert write_accepted_carrier(tmp_path, "p1", (ITEM,)) is False
    assert path.stat().st_mtime_ns == before


def test_no_items_and_no_file_writes_nothing(tmp_path: Path):
    assert write_accepted_carrier(tmp_path, "p1", ()) is False
    assert not (tmp_path / ".l4").exists()


def test_a_later_activation_without_items_rewrites_an_existing_file_as_empty(tmp_path: Path):
    write_accepted_carrier(tmp_path, "p1", (ITEM,))
    assert write_accepted_carrier(tmp_path, "p1", ()) is True
    assert json.loads((tmp_path / ACCEPTED_FILE).read_text())["items"] == []
    assert write_accepted_carrier(tmp_path, "p1", ()) is False  # and that is stable


def test_a_missing_file_is_written_again_as_after_a_restart(tmp_path: Path):
    write_accepted_carrier(tmp_path, "p1", (ITEM,))
    (tmp_path / ACCEPTED_FILE).unlink()  # `l4 restart` drops the unit's .l4 folder
    assert write_accepted_carrier(tmp_path, "p1", (ITEM,)) is True


def test_a_symlink_in_its_place_is_replaced_not_followed(tmp_path: Path):
    target = tmp_path / "elsewhere.txt"
    target.write_text("keep")
    (tmp_path / ".l4").mkdir()
    (tmp_path / ACCEPTED_FILE).symlink_to(target)
    assert write_accepted_carrier(tmp_path, "p1", (ITEM,)) is True
    assert target.read_text() == "keep" and not (tmp_path / ACCEPTED_FILE).is_symlink()


@pytest.fixture
def plan_step(monkeypatch: pytest.MonkeyPatch):
    def install(accepted: dict) -> None:
        step = PlanStep(allow=None, plan_id="p1", accepted=accepted)
        monkeypatch.setattr(orchestrator, "yolo_step", lambda *a, **k: step)

    return install


def test_the_run_commits_the_file_with_its_first_commit_and_the_digest_ignores_it(run_l4, tdd_repo, raw, plan_step):
    assert is_excluded(("openspec", ".l4", "review-accepted.json")) and is_excluded((".l4", "review-accepted.json"))
    new_origin_main(tdd_repo, raw, {f"{UNIT_DIR}/tasks.md": "- [ ] 1.1 Add `apply_discount`\n"})
    plan_step({UNIT: (ITEM,)})
    run = run_l4([red_step(), green_step()])
    assert run.code == 0
    data = json.loads(run.pushed(f"{UNIT_DIR}/.l4/review-accepted.json"))
    assert data["plan"] == "p1" and data["items"] == [ITEM]
    first = run.raw(tdd_repo.origin, "log", "--reverse", "--format=%H", f"main..{BRANCH}").split()[0]
    assert ".l4/review-accepted.json" in run.raw(tdd_repo.origin, "show", "--name-only", "--format=", first)
    folder = Git(tdd_repo.origin)
    digest = unit_digest(folder, BRANCH, UNIT_DIR)
    run.raw(tdd_repo.origin, "update-ref", "refs/tmp/with", BRANCH)
    assert unit_digest(folder, "refs/tmp/with", UNIT_DIR) == digest  # same tree; the file is outside the digest


def test_a_second_run_writes_no_commit_for_the_file(run_l4, tdd_repo, raw, plan_step):
    new_origin_main(tdd_repo, raw, {f"{UNIT_DIR}/tasks.md": "- [ ] 1.1 Add `apply_discount`\n"})
    plan_step({UNIT: (ITEM,)})
    run_l4([red_step(), green_step()])
    second = run_l4([])
    assert second.code == 0
    path = f"{UNIT_DIR}/.l4/review-accepted.json"
    touching = raw(tdd_repo.origin, "log", "--format=%H", f"main..{BRANCH}", "--", path)
    assert len(touching.split()) == 1


def test_a_unit_outside_the_plan_items_gets_no_file(run_l4, tdd_repo, raw, plan_step):
    new_origin_main(tdd_repo, raw, {f"{UNIT_DIR}/tasks.md": "- [ ] 1.1 Add `apply_discount`\n"})
    plan_step({"openspec:other": (ITEM,)})
    run = run_l4([red_step(), green_step()])
    assert run.code == 0
    listing = run.raw(tdd_repo.origin, "ls-tree", "--name-only", BRANCH, f"{UNIT_DIR}/.l4/")
    assert "review-accepted.json" not in listing
