import hashlib
import json

import pytest

from l4.fsutil import UnsafeFile
from l4.state.idempotency import TRAILER_DIGITS, spec_files_hash, step_key, trailer_value

BASE = dict(
    unit="openspec:add-login", step="green", task="2.1", base_sha="a" * 40, spec_hash="b" * 64,
    template_version="contract@1+green@1", profile="claude-sonnet",
)  # fmt: skip


def test_every_input_changes_the_key():
    key = step_key(**BASE)
    assert key == step_key(**BASE) and len(key) == 64
    variants = {
        "unit": "kiro:add-login", "step": "red", "task": "2.2", "base_sha": "c" * 40, "spec_hash": "d" * 64,
        "template_version": "contract@2+green@1", "profile": "codex-sol",
    }  # fmt: skip
    keys = {step_key(**{**BASE, name: value}) for name, value in variants.items()}
    assert len(keys | {key}) == len(variants) + 1  # seven inputs, seven different keys, none equal to the original


def test_the_key_is_the_sha256_of_the_canonical_array():
    expected = json.dumps(list(BASE.values()), separators=(",", ":"))
    assert step_key(**BASE) == hashlib.sha256(expected.encode()).hexdigest()


def test_a_missing_task_is_null_and_inputs_cannot_shift_into_each_other():
    assert step_key(**{**BASE, "task": None}) != step_key(**{**BASE, "task": "None"})
    assert step_key(**{**BASE, "unit": "ab", "step": "c"}) != step_key(**{**BASE, "unit": "a", "step": "bc"})
    assert (
        step_key(**{**BASE, "task": None})
        == hashlib.sha256(
            json.dumps([BASE["unit"], "green", None, *list(BASE.values())[3:]], separators=(",", ":")).encode()
        ).hexdigest()
    )


def test_the_trailer_is_the_first_twelve_digits():
    key = step_key(**BASE)
    assert trailer_value(key) == key[:12] and TRAILER_DIGITS == 12


def test_spec_files_hash_covers_names_and_bytes(tmp_path):
    (tmp_path / "tasks.md").write_bytes(b"- [ ] 1.1 a\n")
    (tmp_path / "proposal.md").write_bytes(b"why\n")
    names = ["tasks.md", "proposal.md"]
    first = spec_files_hash(tmp_path, names)
    assert first == spec_files_hash(tmp_path, reversed(names)) == spec_files_hash(tmp_path, [*names, "tasks.md"])
    (tmp_path / "tasks.md").write_bytes(b"- [x] 1.1 a\n")
    assert spec_files_hash(tmp_path, names) != first  # one marker byte changes it
    (tmp_path / "tasks.md").write_bytes(b"- [ ] 1.1 a\n")
    assert spec_files_hash(tmp_path, names) == first
    (tmp_path / "other.md").write_bytes(b"- [ ] 1.1 a\n")
    assert spec_files_hash(tmp_path, ["other.md", "proposal.md"]) != first  # the same bytes under another name


def test_absent_and_empty_files_differ_and_paths_do_not_matter(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.md").write_bytes(b"")
    absent = spec_files_hash(tmp_path / "a", ["y.md"])
    empty = spec_files_hash(tmp_path / "a", ["x.md"])
    assert absent != empty != spec_files_hash(tmp_path / "a", ["x.md", "y.md"])
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "x.md").write_bytes(b"")
    assert spec_files_hash(tmp_path / "b", ["x.md"]) == empty  # another directory, same names and bytes


def test_a_symlink_is_refused(tmp_path):
    (tmp_path / "real.md").write_text("x")
    (tmp_path / "link.md").symlink_to(tmp_path / "real.md")
    with pytest.raises(UnsafeFile):
        spec_files_hash(tmp_path, ["link.md"])
