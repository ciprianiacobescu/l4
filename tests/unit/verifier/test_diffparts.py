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
    assert lock.text == f"lock file uv.lock: {len(old)} -> {len(new)} bytes, +30000 -0 lines (not diffed)\n"
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
    assert only.lock and only.text == f"lock file {name}: 0 -> 4 bytes, +2 -0 lines (not diffed)\n"


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
    assert found["Cargo.lock"].text == "lock file Cargo.lock: 6 -> 0 bytes, +0 -3 lines (not diffed)\n"
