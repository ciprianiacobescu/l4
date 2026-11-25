"""Step 3's evidence with the skipped-test hold (skipped-test-hold D2, L4-VER-092): one `Hold(kind="skipped")` per
file, listed after step 1's holds and before the coverage ones, and kept out of `later_holds`."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from l4.config.schema import L4Config
from l4.evidence.collect import collect_evidence
from l4.gates.junit import TestCase, TestReport
from l4.specs.base import Framework, UnitRef
from l4.vcs.git import Git
from l4.verifier.types import Severity
from l4.verifier.verdicts import hold_id

IDENT = ("-c", "user.name=l4-bot", "-c", "user.email=l4-bot@users.noreply.invalid")
SKIPIF = "@pytest.mark.skipif(os.getenv('X') != 'true', reason='stack')"
SOURCE = (
    "import os\n\nimport pytest\n\n\n{mark}\ndef test_a():\n    assert {n}\n\n\n"
    "{skipif}\ndef test_b():\n    assert {n}\n"
)
TEXT = (
    "skipped: existing tests in `tests/test_live.py` are skipped, and this unit did not add or change a skip that "
    "can affect them (2 tests)"
)
IDS = ("tests.test_live::test_a", "tests.test_live::test_b")


@dataclass
class Bench:
    git: Git
    cfg: L4Config
    worktree: Path


def _commit(git: Git, msg: str) -> str:
    git.run("add", "-A")
    git.run(*IDENT, "commit", "-qm", msg, "--trailer", "L4-Run: r-1")
    return git.rev_parse("HEAD")


def _evidence(tmp: Path, base_mark: str, head_mark: str, *, mode: str = "off", extra: dict[str, str] | None = None):
    tmp.mkdir(parents=True)
    git = Git(tmp)
    git.run("init", "--quiet")
    files = {"specs/u/proposal.md": "Change `tests/test_live.py`.\n"}
    files["tests/test_live.py"] = SOURCE.format(mark=base_mark, skipif=SKIPIF, n=1)
    for rel, text in files.items():
        (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp / rel).write_text(text)
    base = _commit(git, "base")
    (tmp / "tests/test_live.py").write_text(SOURCE.format(mark=head_mark, skipif=SKIPIF, n=2))
    for rel, text in (extra or {}).items():
        (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp / rel).write_text(text)
    head = _commit(git, "head")
    report = TestReport({i: TestCase(i, "skipped") for i in IDS})
    cfg = L4Config.model_validate(
        {"sdd": {"scope_check": "fail"}, "verifier": {"evidence": {"diff_coverage": {"mode": mode}}}}
    )
    ref = UnitRef(Framework.OPENSPEC, "u", tmp / "specs" / "u")
    ev = collect_evidence(Bench(git, cfg, tmp), base, head, report, None, ref, gate_passed=True)
    return ev, git, head


def test_a_skip_that_predates_the_unit_is_one_hold_per_file(tmp_path: Path):  # SCN-VER-372, SCN-VER-379
    ev, git, head = _evidence(tmp_path / "r", SKIPIF, SKIPIF)
    assert ev.ran is not None and ev.ran.findings == []
    assert ev.ran.summary.skipped_predating == IDS
    assert ev.holds == [TEXT]
    (hold,) = ev.hold_records
    assert (hold.id, hold.kind, hold.subjects) == (hold_id(TEXT), "skipped", ("tests/test_live.py",))
    assert ev.ran_holds == 1 and ev.later_holds == []  # diff coverage is off: the hold is in no later step
    assert ev.to_json()["holds"][0]["kind"] == "skipped"
    assert ev.to_json()["tests_ran"]["summary"]["skipped_predating"] == list(IDS)


def test_the_hold_view_binds_the_head_blob_and_the_skipped_ids(tmp_path: Path):  # SCN-VER-383
    ev, git, head = _evidence(tmp_path / "r", SKIPIF, SKIPIF)
    blob = git.run("rev-parse", f"{head}:tests/test_live.py").stdout.strip()
    sha = hashlib.sha256(f"{TEXT}\0{blob}\0{chr(0).join(IDS)}".encode()).hexdigest()
    assert ev.hold_views == {TEXT: {"sha": sha, "paths": list(IDS)}}
    other, _, _ = _evidence(tmp_path / "s", SKIPIF, SKIPIF)
    assert other.hold_views == ev.hold_views  # the same content binds the same way


def test_a_skip_the_unit_added_stays_a_finding_and_makes_no_hold(tmp_path: Path):  # SCN-VER-373
    ev, _, _ = _evidence(tmp_path / "r", "", "@pytest.mark.skip")
    assert ev.ran is not None
    assert [f.severity for f in ev.ran.findings] == [Severity.MAJOR]
    assert "tests.test_live::test_a" in ev.ran.findings[0].detail and "test_b" not in ev.ran.findings[0].detail
    assert ev.ran.summary.skipped_predating == ("tests.test_live::test_b",)
    assert [h.kind for h in ev.hold_records] == ["skipped"]  # test_b's file hold, test_a is in the finding


def test_the_holds_keep_their_order_and_later_holds_leaves_the_skipped_one_out(tmp_path: Path):
    # a file out of the spec's scope raises step 1's hold; the skipped hold follows it; `later_holds` has neither
    ev, _, _ = _evidence(tmp_path / "r", SKIPIF, SKIPIF, extra={"src/other/mod.py": "x = 1\n"})
    kinds = [h.kind for h in ev.hold_records]
    assert kinds == ["scope", "skipped"] and ev.scope_holds == 1 and ev.ran_holds == 1
    assert ev.later_holds == []
    assert json.loads(json.dumps(ev.to_json()))["holds"][-1]["text"] == TEXT
