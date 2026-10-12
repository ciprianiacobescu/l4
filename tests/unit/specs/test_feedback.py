"""human-feedback 1.1: `feedback.md` (SPEC 6.3, L4-FBK-001, L4-FBK-002): the grammar, the owners, ids never reused,
tolerant statuses, validity by kind, span-scoped harness edits and the content hash."""

import json
from pathlib import Path

import pytest

from l4.redact import Redactor
from l4.specs.feedback import (
    FEEDBACK_FILENAME,
    FeedbackFile,
    FeedbackKind,
    FeedbackStatus,
    NewFeedback,
    Place,
    Quote,
    append_item,
    content_sha256,
    next_id,
    problems,
)

REDACTOR = Redactor({})
BY = "CiprianSpot, 2026-10-12T15:04:00Z"


def new(kind: str = "refactor", **kw) -> NewFeedback:
    kw.setdefault("title", "Extract the rounding")
    kw.setdefault("text", "Move the rounding into a helper.")
    if kind in ("refactor", "duplication", "config"):
        kw.setdefault("places", (Place("src/inventory/reorder.py", 7, 9),))
    if kind == "config":
        kw.setdefault("env", "PACK_ROUNDING")
    if kind == "behaviour":
        kw.setdefault("when", "PACK_ROUNDING is `down`")
        kw.setdefault("then", "reorder_quantity rounds down")
    return NewFeedback(FeedbackKind(kind), by=BY, **kw)


def add(unit: Path, kind: str = "refactor", **kw) -> str:
    return append_item(unit, "add-reorder", new(kind, **kw), redactor=REDACTOR)


def read(unit: Path) -> bytes:
    return (unit / FEEDBACK_FILENAME).read_bytes()


def item(data: bytes, fid: str = "FB-001"):
    return FeedbackFile.parse(data).get(fid)


def test_the_file_is_created_with_the_header_and_the_index(tmp_path: Path):
    """SCN-FBK-01: the grammar of the documentation example, written by the command."""
    assert add(tmp_path, "config", places=(Place("src/inventory/reorder.py", 7, 9),),
               code=(Quote("src/inventory/reorder.py:7-9", "python", "    packs = -(-short // pack_size)"),),
               lesson=True) == "FB-001"  # fmt: skip
    text = read(tmp_path).decode()
    assert text.startswith("# Feedback \N{EM DASH} add-reorder\n\n<!-- l4:feedback v1\n")
    assert "`l4 feedback add`" in text and "`draft` items wait" in text
    assert "<!-- l4:feedback-index:start -->\n| ID | Status | Kind | Where | Feedback |\n" in text
    assert "| FB-001 | submitted | config | src/inventory/reorder.py:7 | Extract the rounding |\n" in text
    for line in (
        "## FB-001: Extract the rounding", "- **Status:** submitted", "- **Kind:** config",
        "- **Where:** `src/inventory/reorder.py:7-9`", "- **Env:** `PACK_ROUNDING`", "- **Lesson:** yes",
        f"- **By:** {BY}", "### Code\n```python\n    packs = -(-short // pack_size)\n```", "### Feedback",
        "### Outcome\n<!-- written by the harness -->",
    ):  # fmt: skip
        assert line in text
    got = item(read(tmp_path))
    assert (got.status, got.kind, got.env, got.lesson, got.by) == (
        FeedbackStatus.SUBMITTED, FeedbackKind.CONFIG, "PACK_ROUNDING", True, BY,
    )  # fmt: skip
    assert got.places == (Place("src/inventory/reorder.py", 7, 9),)
    assert got.code == "    packs = -(-short // pack_size)" and got.text == "Move the rounding into a helper."
    assert problems(got) == ()


def test_draft_when_and_then_and_several_places_round_trip(tmp_path: Path):
    add(tmp_path, "behaviour", draft=True, places=(Place("a.py", 1, 1), Place("b.py", None, None), Place("c.py", 3, 5)))
    got = item(read(tmp_path))
    assert got.status is FeedbackStatus.DRAFT
    assert got.places == (Place("a.py", 1, 1), Place("b.py", None, None), Place("c.py", 3, 5))
    assert [p.label for p in got.places] == ["a.py:1", "b.py", "c.py:3-5"]
    assert (got.when, got.then) == ("PACK_ROUNDING is `down`", "reorder_quantity rounds down")


def test_a_code_fence_is_longer_than_any_backtick_run_in_the_code(tmp_path: Path):
    code = "```\n## FB-009: not a heading\n```\n````"
    add(tmp_path, places=(Place("a.md", 1, 4),), code=(Quote("a.md:1-4", "", code),))
    add(tmp_path, "tests", text="second")
    data = read(tmp_path)
    assert b"`````\n```\n## FB-009" in data  # a five-backtick fence around a four-backtick run
    file = FeedbackFile.parse(data)
    assert [i.id for i in file.items] == ["FB-001", "FB-002"]
    assert file.get("FB-001").code == code and file.get("FB-002").text == "second"


def test_tolerant_statuses_and_kinds(tmp_path: Path):
    """SCN-FBK-04: statuses and kinds read case-insensitively; an unknown status reads as draft."""
    add(tmp_path)
    data = read(tmp_path)
    for written, status in (
        ("SUBMITTED", FeedbackStatus.SUBMITTED), ("`Withdrawn`", FeedbackStatus.WITHDRAWN),
        ("Taken", FeedbackStatus.TAKEN), ("addressed in round 2", FeedbackStatus.ADDRESSED),
        ("maybe later", FeedbackStatus.DRAFT), ("", FeedbackStatus.DRAFT),
    ):  # fmt: skip
        edited = data.replace(b"- **Status:** submitted", f"- **Status:** {written}".rstrip().encode())
        assert item(edited).status is status, written
    assert item(data.replace(b"**Kind:** refactor", b"**Kind:** Refactor")).kind is FeedbackKind.REFACTOR
    unknown = item(data.replace(b"**Kind:** refactor", b"**Kind:** other"))
    assert unknown.kind is None and unknown.kind_text == "other" and problems(unknown) == ("unknown Kind `other`",)


def test_a_draft_is_not_submitted(tmp_path: Path):
    """SCN-FBK-04: a valid draft stays a draft; nothing in the parse promotes it."""
    add(tmp_path, draft=True)
    got = item(read(tmp_path))
    assert got.status is FeedbackStatus.DRAFT and problems(got) == ()


@pytest.mark.parametrize(
    ("kind", "kw", "expected"),
    [
        ("refactor", {"places": ()}, ("refactor needs Where",)),
        ("duplication", {"places": ()}, ("duplication needs Where",)),
        ("refactor", {"env": "X"}, ("refactor refuses Env",)),
        ("tests", {"env": "X"}, ("tests refuses Env",)),
        ("tests", {"when": "w", "then": "t"}, ("tests refuses When", "tests refuses Then")),
        ("config", {"env": None}, ("config needs Env",)),
        ("config", {"places": ()}, ("config needs Where",)),
        ("config", {"env": "pack_rounding"}, ("Env must match ^[A-Z_][A-Z0-9_]*$",)),
        ("config", {"when": "only when"}, ("When and Then go together",)),
        ("config", {"when": "w", "then": "t"}, ()),
        ("behaviour", {"when": None, "then": None}, ("behaviour needs When and Then",)),
        ("behaviour", {"then": None}, ("behaviour needs When and Then",)),
        ("behaviour", {"env": "X"}, ("behaviour refuses Env",)),
        ("tests", {"text": ""}, ("needs Feedback text",)),
        ("tests", {}, ()),
    ],
)
def test_validity_by_kind(tmp_path: Path, kind: str, kw: dict, expected: tuple[str, ...]):
    """SCN-FBK-03: the table of L4-FBK-002, read back from a file the way the verifier will read it."""
    base = new(kind)
    values = {f: getattr(base, f) for f in ("places", "env", "when", "then", "text")} | kw
    path = tmp_path / FEEDBACK_FILENAME
    fid = append_item(
        tmp_path, "u", NewFeedback(base.kind, base.title, by=BY, **values), redactor=REDACTOR, validate=False
    )
    assert fid == "FB-001"
    assert problems(item(path.read_bytes())) == expected


def test_a_config_item_without_env_is_invalid_in_the_file_a_person_wrote(tmp_path: Path):
    """SCN-FBK-03: a hand-written config item without an Env line."""
    (tmp_path / FEEDBACK_FILENAME).write_text(
        "# Feedback\n\n## FB-001: Hard-coded\n\n- **Status:** submitted\n- **Kind:** config\n"
        "- **Where:** `a.py:1`\n\n### Feedback\nmake it configurable\n",
        encoding="utf-8",
    )  # fmt: skip
    got = FeedbackFile.load(tmp_path).get("FB-001")
    assert got.status is FeedbackStatus.SUBMITTED and problems(got) == ("config needs Env",)


def test_the_hash_ignores_harness_edits_and_whitespace(tmp_path: Path):
    add(tmp_path, "config")
    base = content_sha256(item(read(tmp_path)))
    assert len(base) == 64
    file = FeedbackFile.load(tmp_path).set_status("FB-001", "taken").set_outcome("FB-001", "round 1", redactor=REDACTOR)
    assert content_sha256(file.get("FB-001")) == base
    spaced = read(tmp_path).replace(b"Move the rounding", b"  Move   the\n rounding ").replace(b"   \n", b"\n")
    assert content_sha256(item(spaced)) == base
    for old, changed in (
        (b"into a helper.", b"into a helper!"), (b"`PACK_ROUNDING`", b"`PACK_MODE`"), (b"7-9", b"7-10"),
        (b"**Kind:** config", b"**Kind:** refactor"),
    ):  # fmt: skip
        assert content_sha256(item(read(tmp_path).replace(old, changed))) != base, old
    # the title, the lesson line and the Status are not part of what is asked
    assert content_sha256(item(read(tmp_path).replace(b"**Lesson:** no", b"**Lesson:** yes"))) == base


HAND_WRITTEN = (
    "# Feedback \N{EM DASH} u\n\n<!-- l4:feedback v1\nhow to -->\n\n<!-- l4:feedback-index:start -->\n"
    "| ID | Status | Kind | Where | Feedback |\n|----|--------|------|-------|----------|\n"
    "| FB-001 | submitted | refactor | a.py:1 | One |\n| FB-002 | submitted | tests |  | Two |\n"
    "<!-- l4:feedback-index:end -->\n\n---\n\n## FB-001: One\n\n- **Status:** submitted\n- **Kind:** refactor\n"
    "- **Where:** `a.py:1`\n\n### Code\n```md\n## FB-077: inside a fence\n### Outcome\n```\n\n### Feedback\n"
    "first  \n```md\n## FB-078: inside a fence\n### Outcome\n```\nlast line   \n\n### Outcome\n"
    "<!-- written by the harness -->\n\n---\n\n## FB-002: Two\n\n- **Status:**   submitted  \n- **Kind:** tests\n\n"
    "### Feedback\nsecond  \n\n### Outcome\n<!-- written by the harness -->\n"
)


def test_harness_edits_change_only_their_spans(tmp_path: Path):
    """SCN-FBK-01: Status, Outcome and the index row change; every other byte stays, trailing spaces included."""
    before = HAND_WRITTEN.encode()
    parsed = FeedbackFile.parse(before)
    assert [i.id for i in parsed.items] == ["FB-001", "FB-002"]  # the headings in the fences are not items
    first = parsed.get("FB-001")
    assert first.code == "## FB-077: inside a fence\n### Outcome" and first.text.endswith("last line")
    file = parsed.set_status("FB-001", "taken")
    file = file.set_outcome("FB-001", "taken into u-fix-1 (round 1)", redactor=REDACTOR)
    after = file.data
    got = FeedbackFile.parse(after).get("FB-001")
    assert (got.status, got.outcome) == (FeedbackStatus.TAKEN, "taken into u-fix-1 (round 1)")
    status, body = first.status_value, first.outcome_block.body
    expect = before[: status.start] + b"taken" + before[status.end : body.start]
    expect += b"<!-- written by the harness -->\ntaken into u-fix-1 (round 1)\n" + before[body.end :]
    expect = expect.replace(b"| FB-001 | submitted |", b"| FB-001 | taken |")
    assert after == expect
    # FB-002, with its odd spacing and trailing blanks, is byte for byte what it was
    two_before, two_after = parsed.get("FB-002").section, FeedbackFile.parse(after).get("FB-002").section
    assert after[two_after.start : two_after.end] == before[two_before.start : two_before.end]
    assert b"- **Status:**   submitted  \n" in after


def test_outcome_text_is_redacted_neutralised_and_escaped(tmp_path: Path):
    add(tmp_path)
    secret = "sk-ant-" + "a1b2c3d4" * 4
    text = f"key {secret}\n<!-- l4:feedback-index:start -->\n## FB-050: forged\n---\n### Feedback\n| a | b |"
    file = FeedbackFile.load(tmp_path).set_outcome("FB-001", text, redactor=REDACTOR)
    out = file.data.decode()
    assert secret not in out and out.count("<!-- l4:feedback-index:start -->") == 1
    parsed = FeedbackFile.parse(file.data)
    assert [i.id for i in parsed.items] == ["FB-001"]
    assert "\\## FB-050: forged" in out and "\\---" in out and "\\### Feedback" in out


def test_outcome_replaces_the_body_and_keeps_the_comment(tmp_path: Path):
    add(tmp_path)
    file = FeedbackFile.load(tmp_path).set_outcome("FB-001", "round 1", redactor=REDACTOR)
    file = file.set_outcome("FB-001", "addressed in round 2", redactor=REDACTOR)
    assert file.data.decode().count("<!-- written by the harness -->") == 1
    assert file.get("FB-001").outcome == "addressed in round 2"


def test_outcome_block_is_added_when_a_person_deleted_it(tmp_path: Path):
    add(tmp_path)
    data = read(tmp_path).replace(b"### Outcome\n<!-- written by the harness -->\n", b"")
    file = FeedbackFile.parse(data).set_outcome("FB-001", "round 1", redactor=REDACTOR)
    assert file.get("FB-001").outcome == "round 1" and b"### Outcome\n<!-- written by the harness -->" in file.data


def test_crlf_and_a_missing_final_newline_are_kept(tmp_path: Path):
    add(tmp_path)
    data = read(tmp_path).replace(b"\n", b"\r\n").rstrip()
    file = FeedbackFile.parse(data).set_status("FB-001", "addressed")
    assert file.get("FB-001").status is FeedbackStatus.ADDRESSED
    assert b"\n" not in file.data.replace(b"\r\n", b"")
    assert not file.data.endswith(b"\n")


def test_set_status_needs_a_known_item_and_status(tmp_path: Path):
    add(tmp_path)
    file = FeedbackFile.load(tmp_path)
    with pytest.raises(Exception, match="FB-009"):
        file.set_status("FB-009", "taken")
    with pytest.raises(ValueError):
        file.set_status("FB-001", "done")


def test_refresh_index_follows_a_status_a_person_changed(tmp_path: Path):
    add(tmp_path)
    data = read(tmp_path).replace(b"- **Status:** submitted", b"- **Status:** withdrawn")
    file = FeedbackFile.parse(data).refresh_index()
    assert b"| FB-001 | withdrawn |" in file.data
    assert file.refresh_index().data == file.data
    gone = FeedbackFile.parse(read(tmp_path).replace(b"<!-- l4:feedback-index:start -->\n", b"")).refresh_index()
    assert gone.index is None or b"| FB-001 |" in gone.data


def test_a_file_without_an_index_gets_one(tmp_path: Path):
    (tmp_path / FEEDBACK_FILENAME).write_text(
        "# Feedback\n\n## FB-001: t\n\n- **Status:** submitted\n- **Kind:** tests\n\n### Feedback\nmore tests\n",
        encoding="utf-8",
    )  # fmt: skip
    file = FeedbackFile.load(tmp_path).set_status("FB-001", "taken")
    assert file.index is not None and b"| FB-001 | taken | tests |  | t |" in file.data


def test_save_writes_the_bytes(tmp_path: Path):
    add(tmp_path)
    file = FeedbackFile.load(tmp_path).set_status("FB-001", "taken")
    file.save()
    assert read(tmp_path) == file.data


def test_load_of_a_missing_file_is_none(tmp_path: Path):
    assert FeedbackFile.load(tmp_path) is None


def test_the_parse_never_raises_on_garbage(tmp_path: Path):
    for junk in (
        b"",
        b"\xff\xfe\x00## FB-001: x",
        b"## FB-1:\n- **Status:\n```\n",
        b"<!-- l4:feedback-index:start -->",
    ):
        FeedbackFile.parse(junk)
    file = FeedbackFile.parse(b"## FB-003: only a heading\n```\nnever closed\n## FB-004: after\n")
    assert [i.id for i in file.items] == ["FB-003", "FB-004"]  # an unclosed fence hides nothing


def test_text_the_command_writes_cannot_forge_structure(tmp_path: Path):
    add(tmp_path, text="intro\n## FB-050: forged\n---\n### Outcome\n- **Status:** addressed\n<!-- x -->")
    add(tmp_path, "tests", text="plain")
    file = FeedbackFile.load(tmp_path)
    assert [i.id for i in file.items] == ["FB-001", "FB-002"]
    assert file.get("FB-001").status is FeedbackStatus.SUBMITTED and file.get("FB-001").outcome == ""


def test_ids_are_never_reused(tmp_path: Path):
    """SCN-FBK-02: a deleted section's id stays reserved by its index row and by the ledger."""
    add(tmp_path)
    add(tmp_path, "tests")
    add(tmp_path, "tests")
    text = read(tmp_path).decode()
    head, _, rest = text.partition("## FB-003:")
    (tmp_path / FEEDBACK_FILENAME).write_text(head.rsplit("---", 1)[0], encoding="utf-8")  # FB-003's section is gone
    assert add(tmp_path, "tests") == "FB-004"  # its index row holds the id

    lines = [ln for ln in read(tmp_path).decode().splitlines() if not ln.startswith("| FB-004")]
    (tmp_path / FEEDBACK_FILENAME).write_text("\n".join(lines), encoding="utf-8")
    ledger = tmp_path / ".l4" / "ledger"
    ledger.mkdir(parents=True)
    event = {"ts": "2026-10-12T10:00:00.000Z", "run_id": "r-1", "unit": "openspec:u", "seq": 1}
    (ledger / "r-1.jsonl").write_text(
        json.dumps(event | {"type": "feedback.taken", "id": "FB-009", "sha256": "ab"}) + "\n"
        + json.dumps(event | {"seq": 2, "type": "state.transition", "id": "FB-777"}) + "\n",
        encoding="utf-8",
    )  # fmt: skip
    assert next_id(tmp_path) == "FB-010"  # FB-004's heading is gone but FB-009 was taken; FB-777 is not feedback
    assert add(tmp_path, "tests") == "FB-010"


def test_next_id_of_a_unit_without_a_file(tmp_path: Path):
    assert next_id(tmp_path) == "FB-001"


def test_an_invalid_item_is_refused_before_anything_is_written(tmp_path: Path):
    with pytest.raises(Exception, match="behaviour needs When and Then"):
        add(tmp_path, "behaviour", when=None, then=None)
    assert not (tmp_path / FEEDBACK_FILENAME).exists()


def test_the_command_text_is_redacted_on_one_line_fields(tmp_path: Path):
    secret = "ghp_" + "A1b2C3d4E5" * 3
    add(tmp_path, title=f"use {secret}\nnow", text=f"token {secret}")
    out = read(tmp_path).decode()
    assert secret not in out
    assert item(out.encode()).title.startswith("use ")
