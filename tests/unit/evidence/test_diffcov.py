from pathlib import Path

import pytest

from l4.config.schema import L4Config
from l4.evidence.diffcov import (
    ChangedFunction,
    DiffCoverage,
    changed_functions,
    check_diff_coverage,
    diff_coverage,
    diff_lines,
)
from l4.vcs.git import Git
from l4.verifier.aggregate import aggregate_unit
from l4.verifier.types import Severity, Verdict

SRC = '''"""Doc."""
import os

LIMIT = 3


def plain(a):
    """Docstring."""
    b = a + 1
    return b


class Box:
    kind = "box"

    def __init__(self, size):
        self.size = size

    @staticmethod
    def make(n):
        def inner(x):
            return x * n

        return inner(2)


async def later():
    await os.sleep(1)
'''


def cf(text: str, *lines: int, path: str = "m.py") -> dict[str, ChangedFunction]:
    return {f.qualname: f for f in changed_functions(path, text, set(lines))}


def test_hunks_map_to_enclosing_functions():
    got = cf(SRC, 4, 9, 14, 17, 22, 24, 28)
    assert set(got) == {"<module>", "plain", "Box", "Box.__init__", "Box.make.inner", "Box.make", "later"}
    assert got["<module>"].lines == {4}
    assert got["plain"].lines == {9}
    assert got["Box"].lines == {14}
    assert got["Box.__init__"].lines == {17}
    assert got["Box.make.inner"].lines == {22}
    assert got["Box.make"].lines == {24}
    assert got["later"].lines == {28}
    assert got["plain"].span == (7, 10) and got["Box.make"].span == (19, 24)  # the span starts at the decorator


def test_signature_only_change_is_judged_by_entering_the_function():
    got = cf(SRC, 7)  # `def plain(a):` alone
    assert got["plain"].lines == {9}  # the first statement after the docstring: was it entered?
    decorated = cf(SRC, 19, 20)  # the decorator and the def line of `make`
    assert decorated["Box.make"].lines == {21}  # `def inner`: the first body statement


def test_rename_keeps_lines(tmp_path: Path):
    git = Git(tmp_path)
    git.run("init", "--quiet")
    (tmp_path / "old.py").write_text("def f():\n    return 1\n\n\ndef g():\n    return 2\n")
    git.run("add", "-A")
    git.run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "a")
    base = git.rev_parse("HEAD")
    git.run("mv", "old.py", "new.py")
    (tmp_path / "new.py").write_text("def f():\n    return 1\n\n\ndef g():\n    return 3\n")
    git.run("add", "-A")
    git.run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "b")
    assert diff_lines(git, base, git.rev_parse("HEAD")) == {"new.py": frozenset({6})}


def test_deletion_only_hunk_changes_nothing(tmp_path: Path):
    git = Git(tmp_path)
    git.run("init", "--quiet")
    (tmp_path / "a.py").write_text("x = 1\ny = 2\nz = 3\n")
    (tmp_path / "t.py").write_text("x = 1\n")
    (tmp_path / "notes.txt").write_text("a\n")
    git.run("add", "-A")
    git.run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "a")
    base = git.rev_parse("HEAD")
    (tmp_path / "a.py").write_text("x = 1\nz = 3\n")
    (tmp_path / "t.py").write_text("x = 2\n")
    (tmp_path / "notes.txt").write_text("b\n")
    (tmp_path / "ünï code.py").write_text("q = 1\n")
    git.run("add", "-A")
    git.run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "b")
    got = diff_lines(git, base, git.rev_parse("HEAD"), exclude=lambda p: p == "t.py")
    assert got == {"ünï code.py": frozenset({1})}  # a.py only lost a line; t.py is excluded; notes.txt is not Python


def test_added_line_that_looks_like_a_file_header_does_not_drop_later_hunks(tmp_path: Path):
    git = Git(tmp_path)
    git.run("init", "--quiet")
    body = [f"v{i} = {i}" for i in range(1, 31)]
    (tmp_path / "m.py").write_text("\n".join(body) + "\n")
    git.run("add", "-A")
    git.run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "a")
    base = git.rev_parse("HEAD")
    new = body[:2] + ["++ a1"] + body[2:25] + ["v26 = 'changed'"] + body[26:]
    (tmp_path / "m.py").write_text("\n".join(new) + "\n")
    git.run("add", "-A")
    git.run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "b")
    assert diff_lines(git, base, git.rev_parse("HEAD")) == {"m.py": frozenset({3, 27})}


def test_crlf(tmp_path: Path):
    git = Git(tmp_path)
    git.run("init", "--quiet")
    (tmp_path / "a.py").write_bytes(b"def f():\r\n    return 1\r\n")
    git.run("add", "-A")
    git.run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "a")
    base = git.rev_parse("HEAD")
    (tmp_path / "a.py").write_bytes(b"def f():\r\n    return 2\r\n\r\n\r\ndef g():\r\n    return 3\r\n")
    git.run("add", "-A")
    git.run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "b")
    lines = diff_lines(git, base, git.rev_parse("HEAD"))["a.py"]
    assert lines == {2, 3, 4, 5, 6}
    text = git.run_bytes("show", "HEAD:a.py").decode()
    assert {f.qualname for f in changed_functions("a.py", text, set(lines))} == {"f", "g", "<module>"}


def test_syntax_error_head_counts_everything_as_module_code():
    got = changed_functions("bad.py", "def f(:\n  pass\n", {1, 2})
    assert [(f.qualname, f.lines) for f in got] == [("<module>", {1, 2})]


FUNCS = [
    ChangedFunction("src/a.py", "alpha", (1, 5), frozenset({2, 3, 4})),
    ChangedFunction("src/a.py", "beta", (7, 9), frozenset({8, 9})),
    ChangedFunction("src/a.py", "gamma", (11, 13), frozenset({12})),
    ChangedFunction("src/b.py", "<module>", (1, 2), frozenset({1, 2})),
    ChangedFunction("src/b.py", "doc_only", (4, 6), frozenset({5})),
    ChangedFunction("src/c.py", "elsewhere", (1, 3), frozenset({2})),
]
COV = {
    "meta": {"version": "7.0"},
    "files": {
        "src/a.py": {
            "executed_lines": [1, 2, 3, 4, 8, 9, 12],
            "missing_lines": [],
            "contexts": {
                "2": ["test_a.test_one|run", "test_a.test_two"], "3": ["test_a.test_one"], "4": [""],
                "8": ["test_a.TestC.test_m"],
            },
        },
        "src/b.py": {"executed_lines": [], "missing_lines": [1, 2], "contexts": {}},
    },
}  # fmt: skip


def cov_for(missing: list[int]) -> dict:
    data = {k: dict(v) for k, v in COV["files"].items()}
    data["src/a.py"]["executed_lines"] = [n for n in COV["files"]["src/a.py"]["executed_lines"] if n not in missing]
    data["src/a.py"]["missing_lines"] = missing
    return {"meta": COV["meta"], "files": data}


def test_percent_function_labels_and_tests_from_contexts():
    cov = cov_for([4, 9, 12])
    dc = diff_coverage(FUNCS, cov, {"status": "ok"})
    by = {(f.path, f.qualname): f for f in dc.functions}
    assert by["src/a.py", "alpha"].status == "partly" and by["src/a.py", "alpha"].label is None
    assert by["src/a.py", "beta"].status == "partly"
    assert by["src/a.py", "gamma"].status == "uncovered" and by["src/a.py", "gamma"].label is False
    assert by["src/b.py", "<module>"].status == "uncovered"
    assert by["src/b.py", "doc_only"].status == "n/a" and by["src/b.py", "doc_only"].label is None
    assert by["src/c.py", "elsewhere"].status == "unmeasured"
    # executable changed lines: alpha 3 (2 ran), beta 2 (1 ran), gamma 1 (0), module 2 (0), unmeasured 1 (0): 3 of 9
    assert dc.percent == 33.3 and dc.status == "ok"
    assert by["src/a.py", "alpha"].tests == ("test_a.test_one", "test_a.test_two")
    assert by["src/a.py", "beta"].tests == ("test_a.TestC.test_m",)
    covered = diff_coverage(FUNCS[:2], COV, {"status": "ok"})
    assert [f.label for f in covered.functions] == [True, True] and covered.percent == 100.0


def test_unimported_new_module_counts_as_uncovered():
    dc = diff_coverage([FUNCS[3]], COV, {"status": "ok"})
    assert dc.functions[0].status == "uncovered" and dc.percent == 0.0 and dc.functions[0].tests == ()


def cfg(mode: str, minimum: int = 80) -> L4Config:
    return L4Config.model_validate(
        {"verifier": {"evidence": {"diff_coverage": {"mode": mode, "min_percent": minimum}}}}
    )


def test_warn_holds_fail_fails():
    dc = diff_coverage(FUNCS[:3], cov_for([4, 9, 12]), {"status": "ok"})
    warn = check_diff_coverage(dc, cfg("warn"))
    assert warn.findings == [] and warn.holds == [
        "diff coverage: changed code not run by any test: `src/a.py::alpha`, `src/a.py::beta`, `src/a.py::gamma`"
    ]
    assert "%" not in warn.holds[0] and not any(c.isdigit() for c in warn.holds[0].replace("src/a.py", ""))
    fail = check_diff_coverage(dc, cfg("fail"))
    assert fail.holds == [] and len(fail.findings) == 1
    assert fail.findings[0].severity is Severity.MAJOR and fail.findings[0].source == "deterministic"
    assert aggregate_unit(fail.findings, [], []) is Verdict.FAIL
    assert aggregate_unit([], [], warn.holds) is Verdict.NEEDS_HUMAN
    assert check_diff_coverage(dc, cfg("off")).holds == []
    assert check_diff_coverage(dc, cfg("warn", 30)).holds == []  # 50 % is above the minimum


def test_not_run_never_passes_fail_mode():
    dc = diff_coverage(FUNCS[:3], None, {"status": "not_run", "reason": "coverage.py is not importable"})
    assert dc.status == "not_run" and {f.status for f in dc.functions} == {"not_run"}
    fail = check_diff_coverage(dc, cfg("fail"))
    assert fail.holds == ["diff coverage: not measured: coverage.py is not importable"] and fail.findings == []
    warn = check_diff_coverage(dc, cfg("warn"))
    assert warn.holds == [] and "not measured" in warn.note
    missing = diff_coverage(FUNCS[:1], None, {"status": "ok"})  # "ok" with no data is still not run
    assert missing.status == "not_run"


@pytest.mark.parametrize("mode", ["warn", "fail"])
def test_nothing_changed_is_fully_covered(mode: str):
    dc = diff_coverage([], COV, {"status": "ok"})
    assert dc.percent == 100.0 and check_diff_coverage(dc, cfg(mode)).holds == []


# --- code outside the measured language (L4-VER-002 step 6, SCN-VER-55, SCN-VER-56) -------------------------------


def test_outside_note_names_files_and_caps_the_list():
    from l4.evidence.diffcov import outside_note, suffixes

    assert outside_note([]) == ""
    assert outside_note(["services/g.ts"]) == (
        "diff coverage measures python only; changed code outside it: services/g.ts"
    )
    many = [f"s/f{i}.ts" for i in range(8)]
    assert outside_note(many).endswith("s/f0.ts, s/f1.ts, s/f2.ts, s/f3.ts, s/f4.ts and 3 more")
    assert DiffCoverage(100.0, other_files=("a.ts",)).outside_note == outside_note(["a.ts"])
    assert suffixes(["python"]) == (".py",)


@pytest.mark.parametrize("mode", ["warn", "fail"])
def test_not_applicable_says_not_measured_and_never_holds(mode: str):
    """SCN-VER-55: a change with no code in a measured language is not 100 percent covered and not a hold."""
    reason = "diff coverage measures python only; changed code outside it: a.ts"
    dc = DiffCoverage(0.0, status="not_applicable", reason=reason)
    out = check_diff_coverage(dc, cfg(mode))
    assert out.holds == [] and out.findings == []
    assert out.note == f"not measured: {reason}"
    assert aggregate_unit(out.findings, [], out.holds) is Verdict.PASS
