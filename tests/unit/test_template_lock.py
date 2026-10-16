"""HB-11: a prompt body that changes without a version bump fails (SPEC L4-IMP-004, L4-VER-005)."""

import json
from pathlib import Path

from l4 import templatelock

CASES = (
    "implementer/contract", "implementer/red", "implementer/green", "implementer/single", "implementer/single_tests",
    "implementer/output",
    "judge", "clarifier",
    "testwriter/audit", "testwriter/e2e",
)  # fmt: skip


def test_the_committed_lock_matches_the_templates() -> None:
    assert templatelock.problems(templatelock.read_lock(), templatelock.current()) == []


def test_every_pinned_prompt_is_in_the_lock() -> None:
    assert set(templatelock.read_lock()) == set(CASES)


def test_a_changed_body_with_the_same_version_fails_on_a_temp_copy(tmp_path: Path) -> None:
    lock = templatelock.read_lock()
    current = templatelock.current()
    copy = tmp_path / "templates.lock.json"
    copy.write_text(json.dumps(lock))
    edited = {k: dict(v) for k, v in current.items()}
    edited["implementer/red"]["sha256"] = "0" * 64  # the body changed, the version did not
    found = templatelock.problems(templatelock.read_lock(copy), edited)
    assert len(found) == 1
    assert "implementer/red" in found[0] and "bump" in found[0]


def test_a_bumped_version_without_a_regenerated_lock_fails(tmp_path: Path) -> None:
    current = templatelock.current()
    edited = {k: dict(v) for k, v in current.items()}
    edited["judge"]["version"] += 1
    edited["judge"]["sha256"] = "1" * 64
    found = templatelock.problems(templatelock.read_lock(), edited)
    assert len(found) == 1 and "judge" in found[0] and "lock" in found[0]


def test_a_new_prompt_missing_from_the_lock_fails() -> None:
    current = templatelock.current()
    lock = templatelock.read_lock()
    del lock["clarifier"]
    assert any("clarifier" in p for p in templatelock.problems(lock, current))


def test_an_edited_copy_of_a_real_template_file_is_caught(tmp_path: Path) -> None:
    source = Path(templatelock.__file__).parent / "implementer" / "templates" / "red.md"
    copy = tmp_path / "red.md"
    copy.write_text(source.read_text(encoding="utf-8") + "\nOne more rule.\n", encoding="utf-8")
    text = copy.read_text(encoding="utf-8")
    version, _, body = text.partition("\n\n")
    assert version == f"version: {templatelock.read_lock()['implementer/red']['version']}"  # not bumped
    edited = dict(templatelock.current())
    edited["implementer/red"] = {"version": edited["implementer/red"]["version"], "sha256": templatelock._sha(body)}
    assert any("bump the version" in p for p in templatelock.problems(templatelock.read_lock(), edited))
