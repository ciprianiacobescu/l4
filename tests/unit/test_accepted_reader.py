"""`l4.accepted.read_accepted`: the one reader of `<unit folder>/.l4/review-accepted.json` (orchestrator, implementer
prompt and verifier judge share its rules)."""

import json
import logging

import pytest

from l4.accepted import ACCEPTED_SCHEMA, MAX_ACCEPTED_BYTES, read_accepted


def doc(fid: str = "F-0a1b2c") -> dict:
    return {
        "schema": ACCEPTED_SCHEMA,
        "plan": "p1",
        "items": [
            {
                "subject": "openspec:a",
                "reason": "the spec is silent on it",
                "by": "alice",
                "actor": "person",
                "findings": [{"id": fid, "criterion": "testability", "severity": "major", "text": "a"}],
            }
        ],
    }


def carry(folder, content) -> None:
    (folder / ".l4").mkdir(parents=True, exist_ok=True)
    text = content if isinstance(content, str) else json.dumps(content)
    (folder / ".l4" / "review-accepted.json").write_text(text, encoding="utf-8")


def test_a_valid_file_gives_its_items(tmp_path):
    carry(tmp_path, doc())
    (item,) = read_accepted(tmp_path)
    assert item["reason"] == "the spec is silent on it" and item["findings"][0]["id"] == "F-0a1b2c"


def test_a_finding_with_an_empty_id_makes_the_file_invalid(tmp_path, caplog):
    carry(tmp_path, doc(""))
    with caplog.at_level(logging.WARNING, logger="l4.accepted"):
        assert read_accepted(tmp_path) == ()
    assert "not in the shape" in caplog.text


@pytest.mark.parametrize("text", ["not json", "[]", '{"items": 3}', '{"items": [{"findings": [{"id": 1}]}]}', ""])
def test_a_missing_or_invalid_file_is_no_items(tmp_path, text):
    assert read_accepted(tmp_path) == ()
    carry(tmp_path, text)
    assert read_accepted(tmp_path) == ()


def test_a_symlink_or_an_oversized_file_is_no_items(tmp_path):
    (tmp_path / ".l4").mkdir()
    real = tmp_path / "real.json"
    real.write_text(json.dumps(doc()))
    (tmp_path / ".l4" / "review-accepted.json").symlink_to(real)
    assert read_accepted(tmp_path) == ()
    (tmp_path / ".l4" / "review-accepted.json").unlink()
    big = doc()
    big["items"][0]["findings"][0]["text"] = "x" * (MAX_ACCEPTED_BYTES + 1)
    carry(tmp_path, big)
    assert read_accepted(tmp_path) == ()


def test_a_symlinked_l4_folder_is_no_items(tmp_path):
    outside = tmp_path / "outside"
    (outside).mkdir()
    (outside / "review-accepted.json").write_text(json.dumps(doc()))
    unit = tmp_path / "unit"
    unit.mkdir()
    (unit / ".l4").symlink_to(outside, target_is_directory=True)
    assert read_accepted(unit) == ()


def test_a_directory_in_place_of_the_file_is_no_items(tmp_path):
    (tmp_path / ".l4" / "review-accepted.json").mkdir(parents=True)
    assert read_accepted(tmp_path) == ()
