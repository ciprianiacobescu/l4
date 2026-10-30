"""L4-SEC-042 at the verifier: a Python file that the unit's diff adds or changes, by anyone, declares UTF-8."""

import os

import pytest

from l4.verifier.integrity import CHECKS, check_python_encoding, run_integrity
from l4.verifier.types import Severity

from ._integrity_helpers import new_repo

BASE_TEST = "def test_a():\n    assert 1\n"
HIDDEN = "# coding: utf-7\ndef test_a():\n    assert 1  # +AAo-    return\n"


def check(repo, base, head):
    return check_python_encoding(repo.context(base, head))


@pytest.mark.parametrize("who", ["person", "harness", "unit"])
def test_scn_sec_112_the_verifier_blocks_such_a_file_from_anyone(tmp_path, git_environ, who):
    repo, base = new_repo(tmp_path, git_environ, {"tests/test_a.py": BASE_TEST})
    repo.write({"tests/test_a.py": HIDDEN})
    head = {
        "person": repo.commit_as_human,
        "harness": lambda: repo.commit_as_harness("work", phase="implementing"),
        "unit": lambda: repo.commit("work", task="1.1", tdd="red"),
    }[who]()
    out = check(repo, base, head)
    [finding] = out.findings
    assert finding.severity is Severity.BLOCKER and finding.source == "deterministic"
    assert finding.title == "a Python file declares a non-UTF-8 encoding"
    assert "tests/test_a.py: utf-7" in finding.detail
    assert "convert" in finding.detail.lower() and "cookie" in finding.detail


def test_a_new_file_and_a_stub_file_count_and_every_path_is_named(tmp_path, git_environ):
    repo, base = new_repo(tmp_path, git_environ)
    repo.write(
        {
            "src/app/x.py": "# -*- coding: latin-1 -*-\nVALUE = 1\n",
            "src/app/x.pyi": "#!/usr/bin/env python\n# coding: cp1252\nVALUE: int\n",
            "src/app/ok.py": "VALUE = 2\n",
        }
    )
    [finding] = check(repo, base, repo.commit_as_human()).findings
    assert "src/app/x.py: iso-8859-1" in finding.detail and "src/app/x.pyi: cp1252" in finding.detail
    assert "ok.py" not in finding.detail


def test_a_file_the_diff_leaves_alone_or_removes_is_not_checked(tmp_path, git_environ):
    repo, base = new_repo(tmp_path, git_environ, {"src/old.py": HIDDEN, "src/keep.py": HIDDEN})
    repo.delete("src/old.py")
    repo.write({"README.md": "changed\n"})
    out = check(repo, base, repo.commit("work"))
    assert out.findings == []  # keep.py is not in base..head, old.py is gone


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("plain.py", "VALUE = 1\n"),
        ("cookie.py", "# -*- coding: utf-8 -*-\nVALUE = 1\n"),
        ("bom.py", "﻿VALUE = 1\n"),
        ("bom_cookie.py", "﻿# coding: utf-8\nVALUE = 1\n"),
        ("shebang.py", "#!/usr/bin/env python\n# coding: UTF8\nVALUE = 1\n"),
        ("ascii.py", "# -*- coding: us-ascii -*-\nVALUE = 1\n"),
    ],
)
def test_scn_sec_113_utf8_files_are_unaffected(tmp_path, git_environ, name, text):
    repo, base = new_repo(tmp_path, git_environ)
    repo.write({f"src/{name}": text})
    out = check(repo, base, repo.commit_as_human())
    assert out.findings == [] and not out.skipped


def test_scn_sec_114_a_non_python_file_is_unaffected(tmp_path, git_environ):
    repo, base = new_repo(tmp_path, git_environ)
    repo.write({"docs/a.md": "# coding: utf-7\nnotes\n", "src/data.txt": "# coding: utf-7\n"})
    out = check(repo, base, repo.commit_as_human())
    assert out.findings == [] and out.skipped


def test_a_link_named_like_a_python_file_is_read_through_to_its_target(tmp_path, git_environ):
    repo, base = new_repo(tmp_path, git_environ)
    os.symlink("README.md", repo.path / "src_link.py")  # the link itself is not a blob to decode: its target is
    out = check(repo, base, repo.commit_as_human())
    assert out.findings == []


def test_the_check_has_its_own_row_in_the_ladder(tmp_path, git_environ):
    assert "python encoding" in [name for name, _ in CHECKS]
    repo, base = new_repo(tmp_path, git_environ)
    repo.write({"src/x.py": HIDDEN})
    report = run_integrity(repo.context(base, repo.commit_as_human()))
    assert report.blocked
    assert {c.name: c.status for c in report.checks}["python encoding"] == "failed"


# --- a file of any size is read up to a bounded prefix (F1) ---------------------------------------------------------

BIG = 9 * 1024 * 1024
FILLER = ("#" + " " * 1022 + "\n") * (BIG // 1024 + 8)


def test_scn_sec_115_a_cookie_in_a_file_padded_over_eight_mib_is_a_blocker(tmp_path, git_environ):
    repo, base = new_repo(tmp_path, git_environ, {"tests/test_a.py": BASE_TEST})
    repo.write({"tests/test_a.py": HIDDEN + FILLER})
    out = check(repo, base, repo.commit_as_human())
    [finding] = out.findings
    assert "tests/test_a.py: utf-7" in finding.detail
    assert "all UTF-8" not in out.note


def test_scn_sec_115_a_cookie_on_line_two_after_a_huge_first_line_is_unreadable(tmp_path, git_environ):
    repo, base = new_repo(tmp_path, git_environ)
    repo.write({"src/x.py": "# " + "x" * BIG + "\n# coding: utf-7\nVALUE = 1\n"})
    out = check(repo, base, repo.commit_as_human())
    [finding] = out.findings
    assert "src/x.py: unreadable" in finding.detail
    assert "all UTF-8" not in out.note


def test_a_huge_first_line_of_code_is_not_a_finding_and_the_note_says_what_was_read(tmp_path, git_environ):
    repo, base = new_repo(tmp_path, git_environ)
    repo.write({"src/data.py": "DATA = '" + "x" * BIG + "'\n"})
    out = check(repo, base, repo.commit_as_human())
    assert out.findings == [] and "1 Python file(s)" in out.note


# --- a Python-named link is followed (F2) -----------------------------------------------------------------------------

PAYLOAD = "# coding: utf-7\nVALUE = 1  # +AAo-VALUE = 2\n"


def link(repo, rel: str, target: str) -> None:
    (repo.path / rel).parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target, repo.path / rel)


def test_scn_sec_116_a_new_link_to_a_new_file_with_a_cookie_is_a_blocker(tmp_path, git_environ):
    repo, base = new_repo(tmp_path, git_environ)
    repo.write({"pkg/notes.txt": PAYLOAD})
    link(repo, "pkg/x.py", "notes.txt")
    out = check(repo, base, repo.commit_as_human())
    [finding] = out.findings
    assert "pkg/x.py: utf-7" in finding.detail and "pkg/notes.txt" in finding.detail
    assert "all UTF-8" not in out.note


def test_scn_sec_116_a_link_of_the_base_whose_target_the_unit_changes_is_a_blocker(tmp_path, git_environ):
    repo, _ = new_repo(tmp_path, git_environ)
    repo.write({"pkg/notes.txt": "VALUE = 1\n"})
    link(repo, "pkg/x.py", "notes.txt")
    base = repo.commit_as_human("links")
    repo.write({"pkg/notes.txt": PAYLOAD})  # the diff lists only notes.txt
    out = check(repo, base, repo.commit_as_human())
    [finding] = out.findings
    assert "pkg/x.py: utf-7" in finding.detail and "pkg/notes.txt" in finding.detail


def test_scn_sec_116_a_chain_and_a_linked_directory_are_followed(tmp_path, git_environ):
    repo, base = new_repo(tmp_path, git_environ)
    repo.write({"real/notes.txt": PAYLOAD})
    link(repo, "dir", "real")
    link(repo, "mid.txt", "dir/notes.txt")
    link(repo, "src/x.py", "../mid.txt")
    [finding] = check(repo, base, repo.commit_as_human()).findings
    assert "src/x.py: utf-7" in finding.detail and "real/notes.txt" in finding.detail


def test_a_link_to_a_clean_file_is_not_a_finding(tmp_path, git_environ):
    repo, base = new_repo(tmp_path, git_environ)
    repo.write({"pkg/notes.txt": "VALUE = 1\n"})
    link(repo, "pkg/x.py", "notes.txt")
    out = check(repo, base, repo.commit_as_human())
    assert out.findings == [] and not out.skipped


@pytest.mark.parametrize(
    "target",
    ["missing.txt", "/etc/passwd", "../../outside.txt", "loop.py", "pkg", "."],
    ids=["dangling", "absolute", "outside", "loop", "directory", "dot"],
)
def test_scn_sec_116_a_changed_link_that_cannot_be_resolved_to_a_file_is_a_blocker(tmp_path, git_environ, target):
    repo, base = new_repo(tmp_path, git_environ, {"pkg/keep.txt": "x\n"})
    link(repo, "pkg/x.py", target)
    if target == "loop.py":
        link(repo, "pkg/loop.py", "x.py")
    [finding] = check(repo, base, repo.commit_as_human()).findings
    assert "pkg/x.py: link that cannot be checked" in finding.detail


def test_an_unchanged_link_that_cannot_be_resolved_is_not_reported(tmp_path, git_environ):
    repo, _ = new_repo(tmp_path, git_environ)
    link(repo, "pkg/x.py", "missing.txt")
    base = repo.commit_as_human("a dangling link")
    repo.write({"README.md": "changed\n"})
    out = check(repo, base, repo.commit_as_human())
    assert out.findings == []


def test_a_link_changed_to_a_chain_element_that_now_dangles_is_reported(tmp_path, git_environ):
    repo, _ = new_repo(tmp_path, git_environ)
    repo.write({"pkg/notes.txt": "VALUE = 1\n"})
    link(repo, "pkg/mid.txt", "notes.txt")
    link(repo, "pkg/x.py", "mid.txt")
    base = repo.commit_as_human("links")
    (repo.path / "pkg/mid.txt").unlink()
    link(repo, "pkg/mid.txt", "gone.txt")
    [finding] = check(repo, base, repo.commit_as_human()).findings
    assert "pkg/x.py: link that cannot be checked" in finding.detail
