"""The judge's diff in parts (L4-VER-040 to L4-VER-043): the bookkeeping list, the order and the packing of parts."""

from l4.state.review import UNIT_CHANNELS
from l4.verifier.diffparts import bookkeeping_pathspecs


def test_the_bookkeeping_pathspecs_name_the_globs_then_each_channel_file_of_each_unit_folder():
    assert bookkeeping_pathspecs(["u", "u-fix-1"]) == [
        ":(glob,exclude)**/.l4/**",
        ":(glob,exclude).serena/memories/harness/**",
        ":(literal,exclude)u/verification.md",
        ":(literal,exclude)u/questions.md",
        ":(literal,exclude)u/feedback.md",
        ":(literal,exclude)u-fix-1/verification.md",
        ":(literal,exclude)u-fix-1/questions.md",
        ":(literal,exclude)u-fix-1/feedback.md",
    ]


def test_the_file_names_come_from_the_unit_channel_list_of_the_review_module():
    names = [n for n in UNIT_CHANNELS if n != ".l4"]
    assert names == ["verification.md", "questions.md", "feedback.md"]
    assert bookkeeping_pathspecs([]) == [":(glob,exclude)**/.l4/**", ":(glob,exclude).serena/memories/harness/**"]


# ---- the parts (L4-VER-041) -------------------------------------------------------------------------------------

import subprocess  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from l4.vcs.git import Git  # noqa: E402
from l4.verifier import diffparts  # noqa: E402

dp = diffparts
from l4.verifier.diffparts import DiffEntry, group_key, judge_parts, list_entries, pack  # noqa: E402


@pytest.mark.parametrize(
    "path",
    [
        "src/app/report.py",
        "tests/unit/test_report.py",
        "pkg/report_test.go",
        "web/report.test.ts",
        "web/report.spec.ts",
        "lib/report_tests.py",
    ],
)
def test_a_test_sits_next_to_the_code_it_is_named_after(path):
    assert group_key(path) == "report"


def test_a_dunder_init_keeps_its_own_key():
    assert group_key("src/__init__.py") == "__init__"


def entry(path: str, size: int) -> DiffEntry:
    return DiffEntry((path,), "x" * size)


SIX = [
    ("src/app/export.py", 50000), ("tests/test_export.py", 30000), ("README.md", 12000),
    ("src/app/report.py", 60000), ("tests/test_report.py", 40000), ("src/app/util.py", 10000),
]  # fmt: skip


def names(part) -> list[str]:
    return [e.paths[-1] for e in part.entries]


def test_scn_ver_131_whole_files_in_key_order_fill_two_parts_and_the_order_of_the_input_does_not_matter():
    entries = [entry(p, n) for p, n in SIX]
    packed = pack(entries)
    assert [names(p) for p in packed.parts] == [
        ["src/app/export.py", "tests/test_export.py", "README.md"],
        ["src/app/report.py", "tests/test_report.py", "src/app/util.py"],
    ]
    assert [p.index for p in packed.parts] == [1, 2] and not any(p.cut for p in packed.parts)
    assert packed.unseen == () and packed.total_chars == 202000
    assert pack(list(reversed(entries))) == packed


def test_scn_ver_137_an_entry_over_the_part_size_is_a_part_of_its_own_cut_to_it(monkeypatch):
    monkeypatch.setattr(diffparts, "MAX_PART_CHARS", 1000)
    packed = pack([entry("a.py", 300), entry("data/seed.json", 2500), entry("z.py", 300)])
    assert [names(p) for p in packed.parts] == [["a.py"], ["data/seed.json"], ["z.py"]]
    big = packed.parts[1]
    assert big.cut and len(big.text) == 1000 and not packed.parts[0].cut and not packed.parts[2].cut


def test_scn_ver_135_eleven_entries_of_70000_give_eight_parts_and_three_unseen_paths_in_pack_order():
    entries = [entry(f"src/f{n:02d}.py", 70000) for n in range(11)]
    packed = pack(entries)
    assert len(packed.parts) == 8 and all(len(p.entries) == 1 for p in packed.parts)
    assert packed.unseen == ("src/f08.py", "src/f09.py", "src/f10.py")


def test_the_limits_are_read_at_call_time(monkeypatch):
    monkeypatch.setattr(diffparts, "MAX_JUDGE_PARTS", 2)
    monkeypatch.setattr(diffparts, "MAX_PART_CHARS", 100)
    packed = pack([entry(f"f{n}.py", 80) for n in range(3)])
    assert len(packed.parts) == 2 and packed.unseen == ("f2.py",)


def test_an_empty_diff_has_no_parts():
    packed = pack([])
    assert packed.parts == () and packed.unseen == () and packed.total_chars == 0


# ---- on a scratch repository -----------------------------------------------------------------------------------


def sh(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def scratch(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    sh(repo, "init", "-q", "-b", "main")
    sh(repo, "config", "user.email", "t@example.com")
    sh(repo, "config", "user.name", "t")
    sh(repo, "config", "commit.gpgsign", "false")

    def commit(files: dict[str, str | None], message: str) -> str:
        for rel, text in files.items():
            path = repo / rel
            if text is None:
                sh(repo, "rm", "-q", "-f", rel)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            sh(repo, "add", rel)
        sh(repo, "commit", "-q", "-m", message)
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
        ).stdout.strip()

    return Git(repo), commit


def test_list_entries_lists_a_rename_as_one_entry_with_both_paths(scratch):
    git, commit = scratch
    body = "".join(f"line {n}\n" for n in range(40))
    base = commit({"old_name.py": body, "keep.py": "k = 1\n"}, "base")
    sh(git.repo, "mv", "old_name.py", "new_name.py")
    head = commit({"keep.py": "k = 2\n"}, "work")
    found = list_entries(git, base, head, [])
    by_new = {e.paths[-1]: e for e in found}
    assert set(by_new) == {"new_name.py", "keep.py"}
    renamed = by_new["new_name.py"]
    assert renamed.paths == ("old_name.py", "new_name.py") and "rename from old_name.py" in renamed.text
    assert by_new["keep.py"].paths == ("keep.py",) and "+k = 2" in by_new["keep.py"].text


def test_judge_parts_applies_the_bookkeeping_pathspecs(scratch):
    git, commit = scratch
    base = commit({"README.md": "r\n"}, "base")
    head = commit(
        {
            "src/app/report.py": "REPORT = 1\n",
            "u/questions.md": "CHANNEL\n",
            "u/.l4/ledger/r1.jsonl": "{}\n",
            "docs/questions.md": "PROJECT\n",
        },
        "work",
    )
    packed = judge_parts(git, base, head, ["u"])
    shown = [p for part in packed.parts for e in part.entries for p in e.paths]
    assert sorted(shown) == ["docs/questions.md", "src/app/report.py"]


def test_scn_ver_140_a_lock_file_is_one_line_with_its_sizes_and_line_counts_and_is_never_diffed(scratch):
    git, commit = scratch
    old = "".join(f"pkg-{n} = '1.0'\n" for n in range(5))
    base = commit({"uv.lock": old, "src/app/a.py": "A = 1\n"}, "base")
    new = old + "".join(f"added-{n} = '2.0'\n" for n in range(30000))
    head = commit({"uv.lock": new, "src/app/a.py": "A = 2\n"}, "work")
    found = {e.paths[-1]: e for e in list_entries(git, base, head, [])}
    lock = found["uv.lock"]
    assert lock.lock and not found["src/app/a.py"].lock
    assert lock.text == (
        f"lock file uv.lock: {len(old)} -> {len(new)} bytes, +30000 -0 lines, 0 touch a source field, hosts: none "
        "(not diffed)\n"
    )
    assert "added-1 =" not in lock.text
    packed = judge_parts(git, base, head, [])
    assert len(packed.parts) == 1 and not packed.parts[0].cut and packed.unseen == ()


@pytest.mark.parametrize(
    "name",
    ["uv.lock", "poetry.lock", "Pipfile.lock", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "go.sum",
     "Cargo.lock", "composer.lock", "Gemfile.lock", "web/app/yarn.lock"],
)  # fmt: skip
def test_every_listed_lock_file_is_one_line_in_any_folder(scratch, name):
    git, commit = scratch
    base = commit({"README.md": "r\n"}, "base")
    head = commit({name: "a\nb\n"}, "work")
    (only,) = list_entries(git, base, head, [])
    assert only.lock and only.text == (
        f"lock file {name}: 0 -> 4 bytes, +2 -0 lines, 0 touch a source field, hosts: none (not diffed)\n"
    )


def test_scn_ver_142_a_file_named_like_a_lock_but_not_on_the_list_is_diffed(scratch):
    git, commit = scratch
    base = commit({"README.md": "r\n"}, "base")
    head = commit({"src/lock.py": "LOCK = 1\n", "docs/uv.lock.md": "notes\n", "locks/notes.txt": "n\n"}, "work")
    found = list_entries(git, base, head, [])
    assert len(found) == 3 and not any(e.lock for e in found)
    assert all("+++ b/" in e.text for e in found)


def test_scn_ver_144_a_deleted_lock_file_is_one_line_too(scratch):
    git, commit = scratch
    base = commit({"Cargo.lock": "x\ny\nz\n"}, "base")
    head = commit({"Cargo.lock": None, "src/main.rs": "fn main() {}\n"}, "work")
    found = {e.paths[-1]: e for e in list_entries(git, base, head, [])}
    assert found["Cargo.lock"].lock
    assert found["Cargo.lock"].text == (
        "lock file Cargo.lock: 6 -> 0 bytes, +0 -3 lines, 0 touch a source field, hosts: none (not diffed)\n"
    )


# ---- review N3: what is a lock file, and what its line shows ---------------------------------------------------------


def test_attack_a_source_file_renamed_to_a_lock_name_is_diffed_not_hidden(scratch):
    git, commit = scratch
    code = "def check(user):\n    return user.is_admin\n" + "".join(f"line {i}\n" for i in range(20))
    base = commit({"src/auth/guard.py": code, "src/auth/use.py": "from .guard import check\n"}, "base")
    sh(git.repo, "mv", "src/auth/guard.py", "src/auth/go.sum")
    head = commit({}, "head")
    found = {e.paths[-1]: e for e in list_entries(git, base, head, [])}
    renamed = found["src/auth/go.sum"]
    assert not renamed.lock and renamed.paths == ("src/auth/guard.py", "src/auth/go.sum")
    assert "rename from src/auth/guard.py" in renamed.text


def test_a_lock_file_renamed_to_a_lock_file_is_one_line_that_shows_the_old_path(scratch):
    git, commit = scratch
    base = commit({"old/yarn.lock": "".join(f"pkg{i}\n" for i in range(30))}, "base")
    (git.repo / "new").mkdir()
    sh(git.repo, "mv", "old/yarn.lock", "new/yarn.lock")
    head = commit({}, "head")
    (only,) = list_entries(git, base, head, [])
    assert only.lock and only.text.startswith("lock file new/yarn.lock (renamed from old/yarn.lock): ")


def test_the_lock_line_counts_source_fields_and_names_the_hosts(scratch):
    git, commit = scratch
    base = commit(
        {"package-lock.json": '{\n "a": {\n  "resolved": "https://registry.npmjs.org/a/-/a-1.tgz"\n }\n}\n'}, "base"
    )
    head = commit(
        {"package-lock.json": '{\n "a": {\n  "resolved": "https://evil.example.net/a-1.tgz",\n'
                              '  "integrity": "sha512-xx"\n }\n}\n'}, "work"
    )  # fmt: skip
    (only,) = list_entries(git, base, head, [])
    assert only.lock
    assert "3 touch a source field" in only.text  # the old resolved line, the new one and the integrity line
    assert "hosts: evil.example.net, registry.npmjs.org" in only.text and only.text.endswith("(not diffed)\n")


# ---- review M3: one git diff for the content, a bounded listing ------------------------------------------------------


def test_listing_many_files_runs_a_constant_number_of_git_diffs(scratch):
    git, commit = scratch
    base = commit({"README.md": "r\n"}, "base")
    head = commit({f"gen/f{i}.txt": f"{i}\n" for i in range(40)}, "head")
    git.history.clear()
    found = list_entries(git, base, head, [])
    assert len(found) == 40 and all(
        f"+{i}" in next(e.text for e in found if e.paths == (f"gen/f{i}.txt",)) for i in (0, 39)
    )
    diffs = [argv for argv in git.history if "diff" in argv]
    assert len(diffs) <= 3, len(diffs)  # the name-status listing and the one diff (a lock file would add its own)


def test_an_entry_dropped_from_retention_is_fetched_again_when_it_lands_in_a_part(scratch, monkeypatch):
    git, commit = scratch
    base = commit({"README.md": "r\n"}, "base")
    head = commit({f"gen/f{i}.txt": f"{i}\n" * 50 for i in range(6)}, "head")
    monkeypatch.setattr(dp, "MAX_PART_CHARS", 2000)
    monkeypatch.setattr(dp, "RETAIN_PARTS", 1)  # keep the text of about one part only
    packed = judge_parts(git, base, head, [])
    shown = [e for part in packed.parts for e in part.entries]
    assert shown and all(e.text.startswith("diff --git") and e.chars == len(e.text) for e in shown)


def test_the_listing_is_capped_and_says_where_the_rest_is():
    entries = [E2(f"gen/f{i:03d}.py", 100) for i in range(250)]
    packed = pack(entries)
    lines, more = dp.part_listing(packed)
    assert len(lines) == dp.LISTING_MAX_LINES == 200 and more == 50
    assert lines[0][1] == "gen/f000.py"
    assert dp.listing_chars(packed) > 0


def E2(path: str, n: int) -> DiffEntry:
    return DiffEntry((path,), "x" * n)


def test_the_listing_counts_in_the_part_budget(monkeypatch):
    monkeypatch.setattr(dp, "MAX_PART_CHARS", 1000)
    entries = [E2(f"src/m{i}.py", 400) for i in range(4)]  # 2 per part without a listing
    assert [len(p.entries) for p in pack(entries).parts] == [2, 2]
    assert [len(p.entries) for p in pack(entries, reserve=300).parts] == [1, 1, 1, 1]  # 1000 - 300 holds one


# ---- review M2: a test lands next to the code it imports -------------------------------------------------------------


def test_a_test_not_named_after_the_module_is_packed_with_the_module_it_imports():
    code = E2("src/app/report.py", 60_000)
    test = DiffEntry(("tests/test_api_flow.py",), "+from app.report import totals\n" + "x" * 39_000)
    big = E2("src/app/models.py", 100_000)
    packed = pack([code, test, big])
    together = [{e.paths[-1] for e in part.entries} for part in packed.parts]
    assert {"src/app/report.py", "tests/test_api_flow.py"} in together
    assert pack([big, test, code]) == packed  # the order of the input does not matter


def test_an_import_of_a_module_not_in_the_diff_changes_nothing():
    test = DiffEntry(("tests/test_api_flow.py",), "+import os\n+from other.thing import x\n")
    code = E2("src/app/report.py", 10)
    assert dp.group_key("tests/test_api_flow.py") == "api_flow"
    packed = pack([code, test])
    assert [e.paths[-1] for e in packed.parts[0].entries] == ["tests/test_api_flow.py", "src/app/report.py"]
