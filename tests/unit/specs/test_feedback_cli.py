"""human-feedback 1.2: `l4 feedback add|list|show|submit|withdraw` (L4-FBK-003): the unit, `--at`, the kind rules,
what is printed and what is written."""

import io
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from l4.cli import main
from l4.specs.feedback import FeedbackFile, FeedbackStatus

UNIT = "add-reorder-quantity"
FOLDER = f"openspec/changes/{UNIT}"
FILE = f"{FOLDER}/feedback.md"
SOURCE = "src/inventory/reorder.py"
LINES = [f"line {n}" for n in range(1, 21)]


class Ctx:
    def __init__(self, repo: Path, environ: dict[str, str], raw: Callable[..., str], capsys) -> None:
        self.repo, self.environ, self.raw, self.capsys = repo, environ, raw, capsys

    def run(self, *words: str, expect: int = 0) -> str:
        code = main(["feedback", *words, "--repo", str(self.repo)], environ=self.environ)
        out, err = self.capsys.readouterr()
        assert code == expect, (out, err)
        self.err = err
        return out

    @property
    def feedback(self) -> Path:
        return self.repo / FILE

    def written(self) -> list[str]:
        return [line[3:] for line in self.raw(self.repo, "status", "--porcelain", "-uall").splitlines()]


@pytest.fixture
def ctx(make_repo, raw, git_environ, capsys) -> Ctx:
    repo = make_repo("repo")
    (repo / "src" / "inventory").mkdir(parents=True)
    (repo / SOURCE).write_text("\n".join(LINES) + "\n")
    (repo / FOLDER).mkdir(parents=True)
    (repo / FOLDER / "proposal.md").write_text("## Why\nx\n")
    (repo / ".l4").mkdir()
    (repo / ".l4" / "config.yaml").write_text("version: 1\n")
    raw(repo, "config", "user.name", "CiprianSpot")
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "unit")
    raw(repo, "checkout", "-q", "-b", f"l4/openspec/{UNIT}")
    return Ctx(repo, git_environ, raw, capsys)


def test_add_on_a_unit_branch(ctx: Ctx):
    """SCN-FBK-05: add on a unit branch."""
    out = ctx.run(
        "add", "--kind", "refactor", "--at", f"{SOURCE}:4-9", "--text", "extract the rounding into a helper"
    )  # fmt: skip
    assert out.splitlines() == [
        "FB-001 submitted",
        FILE,
        f"git add {FILE}",
        f'git commit -m "feedback({UNIT}): FB-001 extract the rounding into a helper"',
        "git push",
    ]
    assert ctx.written() == [FILE]
    file = FeedbackFile.load(ctx.repo / FOLDER)
    item = file.get("FB-001")
    assert item.status is FeedbackStatus.SUBMITTED and item.title == "extract the rounding into a helper"
    assert item.code == "\n".join(LINES[3:9]) and f"- **Where:** `{SOURCE}:4-9`" in file.data.decode()
    assert re.fullmatch(r"CiprianSpot, \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", item.by)
    assert "```text" not in file.data.decode() and "```\n" in file.data.decode()


def test_unit_flag_and_no_unit(ctx: Ctx):
    ctx.raw(ctx.repo, "checkout", "-q", "main")
    ctx.run("add", "--kind", "tests", "--text", "more", expect=2)
    assert f"openspec:{UNIT}" in ctx.err and not ctx.feedback.exists()
    ctx.run("add", "--kind", "tests", "--text", "more", "--unit", f"openspec:{UNIT}")
    assert ctx.feedback.exists()
    ctx.run("add", "--kind", "tests", "--text", "more", "--unit", "openspec:nope", expect=2)
    ctx.run("add", "--kind", "tests", "--text", "more", "--unit", "bogus", expect=2)


def test_a_branch_that_is_not_a_unit_branch_is_no_unit(ctx: Ctx):
    ctx.raw(ctx.repo, "checkout", "-q", "-b", "feature/x")
    ctx.run("add", "--kind", "tests", "--text", "more", expect=2)


def test_a_refused_item_writes_nothing(ctx: Ctx):
    """SCN-FBK-06: a behaviour item without --when and --then."""
    ctx.run("add", "--kind", "behaviour", "--text", "round down", expect=2)
    assert "--when" in ctx.err and "--then" in ctx.err
    assert ctx.written() == []


@pytest.mark.parametrize(
    ("words", "needle"),
    [
        (("--kind", "refactor"), "--at"),
        (("--kind", "duplication"), "--at"),
        (("--kind", "config", "--at", f"{SOURCE}:7"), "--env"),
        (("--kind", "config", "--env", "lower", "--at", f"{SOURCE}:7"), "--env must match"),
        (("--kind", "config", "--at", f"{SOURCE}:7", "--env", "X", "--when", "w"), "go together"),
        (("--kind", "tests", "--env", "X"), "refuses --env"),
        (("--kind", "tests", "--when", "w", "--then", "t"), "refuses --when"),
        (("--kind", "behaviour", "--when", "w", "--then", "t", "--env", "X"), "refuses --env"),
        (("--kind", "tests", "--at", f"{SOURCE}:1", "--at", "a", "--at", "b", "--at", "c", "--at", "d", "--at", "e"),
         "at most 5"),
    ],
)  # fmt: skip
def test_kind_rules_are_checked_before_writing(ctx: Ctx, words: tuple[str, ...], needle: str):
    ctx.run("add", *words, "--text", "x", expect=2)
    assert needle in ctx.err
    assert ctx.written() == []


@pytest.mark.parametrize(
    "at",
    [
        ".l4/config.yaml", "src/.l4/ledger/x.jsonl", f"{FOLDER}/proposal.md", "openspec/specs/x.md", ".git/config",
        "src/inventory/missing.py", f"{SOURCE}:40", f"{SOURCE}:0", f"{SOURCE}:9-4", f"{SOURCE}:15-21",
        "../outside.py", "/etc/passwd", "src/inventory", "src/../../x",
    ],
)  # fmt: skip
def test_a_place_outside_the_code_is_refused(ctx: Ctx, at: str):
    """SCN-FBK-07: a place outside the code, a missing file or a missing line."""
    ctx.run("add", "--kind", "refactor", "--at", at, "--text", "x", expect=2)
    assert ctx.written() == []


def test_a_symlink_place_is_refused(ctx: Ctx):
    outside = ctx.repo.parent / "secret.txt"
    outside.write_text("top secret\n")
    (ctx.repo / "src" / "link.py").symlink_to(outside)
    ctx.run("add", "--kind", "refactor", "--at", "src/link.py:1", "--text", "x", expect=2)
    assert not ctx.feedback.exists()


def test_the_kiro_spec_root_is_refused_too(ctx: Ctx):
    (ctx.repo / ".kiro" / "specs" / "u").mkdir(parents=True)
    (ctx.repo / ".kiro" / "specs" / "u" / "tasks.md").write_text("- [ ] 1 x\n")
    ctx.run("add", "--kind", "refactor", "--at", ".kiro/specs/u/tasks.md:1", "--text", "x", expect=2)


def test_quote_limits_and_redaction(ctx: Ctx):
    secret = "ghp_" + "A1b2C3d4E5" * 3
    body = [f"token = '{secret}'" if n == 3 else f"row {n} " + "x" * 10 for n in range(1, 61)]
    (ctx.repo / "big.py").write_text("\n".join(body) + "\n")
    ctx.run("add", "--kind", "refactor", "--at", "big.py:1-60", "--text", "x")
    data = ctx.feedback.read_text()
    assert secret not in data
    code = FeedbackFile.parse(data).get("FB-001").code
    assert code.count("\n") == 40 and code.splitlines()[-1] == "\N{HORIZONTAL ELLIPSIS}"
    assert "- **Where:** `big.py:1-60`" in data
    (ctx.repo / "wide.py").write_text(("y" * 900 + "\n") * 10)
    ctx.run("add", "--kind", "refactor", "--at", "wide.py:1-10", "--text", "x")
    code = FeedbackFile.parse(ctx.feedback.read_text()).get("FB-002").code
    assert len(code.encode()) <= 4100 and code.endswith("\N{HORIZONTAL ELLIPSIS}")


def test_languages_and_multiple_places(ctx: Ctx):
    (ctx.repo / "a.ts").write_text("let a = 1\n")
    (ctx.repo / "b.unknown").write_text("b\n")
    ctx.run("add", "--kind", "duplication", "--at", "a.ts:1", "--at", "b.unknown", "--at", f"{SOURCE}:2", "--text", "x")
    data = ctx.feedback.read_text()
    assert "```typescript\nlet a = 1\n```" in data and "`b.unknown`" not in data.split("### Code")[1].split("###")[0]
    item = FeedbackFile.parse(data).get("FB-001")
    assert [p.label for p in item.places] == ["a.ts:1", "b.unknown", f"{SOURCE}:2"]


def test_text_from_stdin_title_draft_lesson_and_by(ctx: Ctx, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("A very long first line " + "w" * 100 + "\nsecond line\n"))
    out = ctx.run("add", "--kind", "tests", "--text", "-", "--draft", "--lesson")
    assert out.splitlines()[0] == "FB-001 draft"
    item = FeedbackFile.load(ctx.repo / FOLDER).get("FB-001")
    assert item.status is FeedbackStatus.DRAFT and item.lesson
    assert item.text == "A very long first line " + "w" * 100 + "\nsecond line"
    assert item.title == ("A very long first line " + "w" * 100)[:72]
    ctx.run("add", "--kind", "tests", "--text", "x", "--title", "Own title")
    assert FeedbackFile.load(ctx.repo / FOLDER).get("FB-002").title == "Own title"


def test_by_falls_back_to_unknown(ctx: Ctx, tmp_path: Path):
    """No user.name anywhere: the repository's is unset and the global and system configs the command sees are
    empty, whatever the machine (or the test session) provides."""
    ctx.raw(ctx.repo, "config", "--unset", "user.name")
    empty = tmp_path / "empty-gitconfig"
    empty.write_text("")
    ctx.environ["GIT_CONFIG_GLOBAL"] = str(empty)
    ctx.environ["GIT_CONFIG_NOSYSTEM"] = "1"
    ctx.run("add", "--kind", "tests", "--text", "x")
    assert FeedbackFile.load(ctx.repo / FOLDER).get("FB-001").by.startswith("unknown, ")


def test_empty_text_is_refused(ctx: Ctx):
    ctx.run("add", "--kind", "tests", "--text", "   ", expect=2)
    assert ctx.written() == []


def test_the_commit_line_is_safe_to_paste(ctx: Ctx):
    out = ctx.run("add", "--kind", "tests", "--text", 'use "$HOME" and `ls`')
    commit = [line for line in out.splitlines() if line.startswith("git commit")][0]
    assert commit == f"git commit -m 'feedback({UNIT}): FB-001 use \"$HOME\" and `ls`'"


def test_config_and_behaviour_items_are_valid_in_the_file(ctx: Ctx):
    ctx.run("add", "--kind", "config", "--at", f"{SOURCE}:7-9", "--env", "PACK_ROUNDING", "--text", "read it")
    ctx.run("add", "--kind", "behaviour", "--when", "PACK_ROUNDING is `down`", "--then", "rounds down", "--text", "x")
    file = FeedbackFile.load(ctx.repo / FOLDER)
    assert file.get("FB-001").env == "PACK_ROUNDING"
    assert (file.get("FB-002").when, file.get("FB-002").then) == ("PACK_ROUNDING is `down`", "rounds down")


def test_list_show_and_json(ctx: Ctx):
    assert ctx.run("list") == "no feedback\n"
    ctx.run("add", "--kind", "refactor", "--at", f"{SOURCE}:4-9", "--text", "extract it")
    ctx.run("add", "--kind", "tests", "--text", "more tests", "--draft")
    out = ctx.run("list")
    assert f"FB-001  submitted  refactor  {SOURCE}:4  extract it" in out and "FB-002  draft  tests" in out
    data = json.loads(ctx.run("list", "--json"))
    assert data["schema"] == "l4/feedback@1" and data["unit"] == f"openspec:{UNIT}"
    first = data["items"][0]
    assert first["id"] == "FB-001" and first["status"] == "submitted" and first["problems"] == []
    assert first["places"] == [{"path": SOURCE, "start": 4, "end": 9}] and len(first["content_sha256"]) == 64
    shown = json.loads(ctx.run("show", "FB-002", "--json"))
    assert shown["schema"] == "l4/feedback@1" and shown["item"]["id"] == "FB-002" and "items" not in shown
    text = ctx.run("show", "fb-1")
    assert "## FB-001: extract it" in text and "line 4" in text
    ctx.run("show", "FB-009", expect=2)


def test_list_reports_the_problems_of_a_hand_written_item(ctx: Ctx):
    ctx.feedback.write_text("# F\n\n## FB-001: t\n\n- **Status:** submitted\n- **Kind:** config\n\n### Feedback\nx\n")
    assert "[invalid: config needs Where; config needs Env]" in ctx.run("list")
    data = json.loads(ctx.run("list", "--json"))
    assert data["items"][0]["problems"] == ["config needs Where", "config needs Env"]


def test_submit_and_withdraw(ctx: Ctx):
    ctx.run("add", "--kind", "tests", "--text", "more", "--draft")
    before = ctx.feedback.read_bytes()
    out = ctx.run("submit", "FB-001")
    assert out.splitlines()[:2] == ["FB-001 submitted", FILE]
    assert f'git commit -m "feedback({UNIT}): submit FB-001 more"' in out
    after = ctx.feedback.read_bytes()
    assert after == before.replace(b"- **Status:** draft", b"- **Status:** submitted").replace(
        b"| FB-001 | draft |", b"| FB-001 | submitted |"
    )
    assert ctx.run("submit", "FB-001") == "FB-001 is already submitted\n"
    out = ctx.run("withdraw", "FB-001")
    assert out.splitlines()[0] == "FB-001 withdrawn"
    assert FeedbackFile.load(ctx.repo / FOLDER).get("FB-001").status is FeedbackStatus.WITHDRAWN
    ctx.run("submit", "FB-001", expect=2)  # a withdrawn item is final: add a new one
    ctx.run("withdraw", "FB-009", expect=2)


def test_submit_refuses_an_invalid_item_and_a_missing_file(ctx: Ctx):
    ctx.run("submit", "FB-001", expect=2)
    ctx.feedback.write_text("# F\n\n## FB-001: t\n\n- **Status:** draft\n- **Kind:** config\n\n### Feedback\nx\n")
    ctx.run("submit", "FB-001", expect=2)
    assert "config needs Where" in ctx.err


def test_withdraw_a_taken_item_and_not_an_addressed_one(ctx: Ctx):
    ctx.run("add", "--kind", "tests", "--text", "more")
    file = FeedbackFile.load(ctx.repo / FOLDER).set_status("FB-001", "taken")
    file.save()
    ctx.run("withdraw", "FB-001")
    file.set_status("FB-001", "addressed").save()
    ctx.run("withdraw", "FB-001", expect=2)


def test_help_has_one_example_per_kind(ctx: Ctx):
    for words in (["feedback", "--help"], ["feedback", "add", "--help"]):
        assert main(words, environ=ctx.environ) == 0
    out = ctx.capsys.readouterr().out
    for kind in ("refactor", "duplication", "tests", "config", "behaviour"):
        assert f"--kind {kind}" in out, kind
    assert "--env PACK_ROUNDING" in out and "--when" in out and "--then" in out
    flat = " ".join(out.split())
    assert "only edit feedback.md" in flat and "only edits feedback.md" in flat and "commit and push" in flat


# --- after the merge (human-feedback 5.1, L4-FBK-010) -------------------------------------------------------------


def _ledger(folder: Path, unit: str, *phases: str, run_id: str = "r-20261003T1312Z-7f3a") -> None:
    """A ledger under `folder` whose phase changes end in the last of `phases`."""
    from l4.redact import Redactor
    from l4.state.ledger import LedgerWriter

    writer = LedgerWriter.open(folder, unit, run_id, redactor=Redactor({}))
    before = "none"
    for phase in phases:
        writer.append("phase.changed", **{"from": before, "to": phase, "trigger": "test"})
        before = phase
    writer.finish(0)


def _archive(ctx: Ctx, date: str = "2026-10-01") -> Path:
    """Move the unit's change folder to the archive, as `openspec archive` does, and leave the base checked out."""
    target = ctx.repo / "openspec" / "changes" / "archive" / f"{date}-{UNIT}"
    target.parent.mkdir(parents=True)
    ctx.raw(ctx.repo, "checkout", "-q", "main")
    ctx.raw(ctx.repo, "mv", FOLDER, str(target.relative_to(ctx.repo)))
    return target


def test_merged_unit_writes_to_the_archive_folder(ctx: Ctx):
    """SCN-FBK-23 (first part): on the base, add on an archived merged unit writes to the archive folder."""
    archived = _archive(ctx)
    _ledger(archived, f"openspec:{UNIT}", "in_review", "merged")
    older = ctx.repo / "openspec" / "changes" / "archive" / f"2026-09-01-{UNIT}"
    older.mkdir(parents=True)
    out = ctx.run(
        "add", "--kind", "duplication", "--at", f"{SOURCE}:4-9", "--text", "extract it", "--unit", f"openspec:{UNIT}"
    )
    rel = f"openspec/changes/archive/2026-10-01-{UNIT}/feedback.md"
    lines = out.splitlines()
    assert lines[:4] == [
        "FB-001 submitted", rel, f"git add {rel}", f'git commit -m "feedback({UNIT}): FB-001 extract it"',
    ]
    assert "git push" not in lines
    assert "main" in lines[4] and "follow-up unit" in lines[4]
    assert FeedbackFile.load(archived).get("FB-001").status is FeedbackStatus.SUBMITTED
    assert not (older / "feedback.md").exists()  # the newest match


def test_a_merged_openspec_unit_not_yet_archived_writes_to_its_change_folder(ctx: Ctx):
    ctx.raw(ctx.repo, "checkout", "-q", "main")
    _ledger(ctx.repo / FOLDER, f"openspec:{UNIT}", "in_review", "merged")
    out = ctx.run("add", "--kind", "tests", "--text", "more", "--unit", f"openspec:{UNIT}")
    assert out.splitlines()[1] == FILE and "follow-up unit" in out
    assert ctx.feedback.exists()


def test_a_merged_kiro_unit_writes_to_its_spec_folder(ctx: Ctx):
    """The folder's own ledger reads `in_review`; the merge is only in the pending ledger of the lock ref."""
    from l4.state.pending import PendingLedger
    from l4.vcs.git import Git

    spec = ctx.repo / ".kiro" / "specs" / "discounts"
    spec.mkdir(parents=True)
    (spec / "tasks.md").write_text("- [x] 1 done\n")
    ctx.raw(ctx.repo, "checkout", "-q", "main")
    _ledger(spec, "kiro:discounts", "in_review")
    scratch = ctx.repo.parent / "scratch" / "kiro-discounts"
    _ledger(scratch, "kiro:discounts", "merged", run_id="r-20261003T1320Z-aaaa")
    bare = ctx.repo.parent / "origin.git"
    ctx.raw(ctx.repo.parent, "init", "-q", "--bare", str(bare))
    ctx.raw(ctx.repo, "remote", "add", "origin", str(bare))
    git = Git(ctx.repo, environ=ctx.environ)
    run_id = "r-20261003T1320Z-aaaa"
    built = PendingLedger(git, lock_ref="refs/l4/locks/kiro/discounts", unit="kiro:discounts", run_id=run_id).build(
        next((scratch / ".l4" / "ledger").glob("*.jsonl"))
    )
    git.run("update-ref", "refs/l4/locks/kiro/discounts", built.sha)

    words = ("add", "--kind", "duplication", "--at", f"{SOURCE}:2-3", "--text", "dedupe", "--unit", "kiro:discounts")
    out = ctx.run(*words)
    assert out.splitlines()[1] == ".kiro/specs/discounts/feedback.md" and "follow-up unit" in out
    assert (spec / "feedback.md").exists()


def test_an_abandoned_unit_is_refused(ctx: Ctx):
    ctx.raw(ctx.repo, "checkout", "-q", "main")
    _ledger(ctx.repo / FOLDER, f"openspec:{UNIT}", "implementing", "abandoned")
    ctx.run("add", "--kind", "tests", "--text", "more", "--unit", f"openspec:{UNIT}", expect=2)
    assert "abandoned" in ctx.err and not ctx.feedback.exists()


def test_a_merged_unit_off_the_base_branch_is_refused(ctx: Ctx):
    _ledger(ctx.repo / FOLDER, f"openspec:{UNIT}", "in_review", "merged")  # on the unit branch
    ctx.run("add", "--kind", "tests", "--text", "more", expect=2)
    assert "check out main" in ctx.err and not ctx.feedback.exists()
