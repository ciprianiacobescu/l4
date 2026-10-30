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


def test_a_link_named_like_a_python_file_is_not_read(tmp_path, git_environ):
    repo, base = new_repo(tmp_path, git_environ)
    os.symlink("../README.md", repo.path / "src_link.py")
    out = check(repo, base, repo.commit_as_human())
    assert out.findings == []


def test_the_check_has_its_own_row_in_the_ladder(tmp_path, git_environ):
    assert "python encoding" in [name for name, _ in CHECKS]
    repo, base = new_repo(tmp_path, git_environ)
    repo.write({"src/x.py": HIDDEN})
    report = run_integrity(repo.context(base, repo.commit_as_human()))
    assert report.blocked
    assert {c.name: c.status for c in report.checks}["python encoding"] == "failed"
