"""L4-SEC-042: a Python file that an agent step adds or changes must be UTF-8, in every kind of step.

The reproduction of the review of 2026-10-30: a red step adds `# coding: utf-7` to a pre-existing test and a
`# +AAo-    return` comment to one of its lines; Python reads the comment as a newline and a `return`."""

import pytest

from l4.agents.fake import Step
from l4.implementer.guardnotes import guard_note_text, note_of
from l4.implementer.tdd import run_green, run_red, run_single
from l4.specs.base import Task

from .conftest import IMPL, KNOWN, STUB, TESTS, UNKNOWN, red_step, result

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 3, 3)
FIX_TASK = Task("1.1", "1.1", "1.1 a finding (F-6eb0cc43)", False, " ", 0, 3, 3)
FINDINGS = ["F-6eb0cc43"]
BASE_TEST = "tests/test_pricing.py"
PRICING = "src/pytdd/pricing.py"
COOKIE = "# coding: utf-7\n"
HIDDEN = (
    COOKIE
    + "from pytdd import total\n\n\ndef test_total_adds_prices():\n"
    + "    assert total([1.25, 2.5]) == 3.75  # +AAo-    return\n"
    + "\n\ndef test_total_of_nothing_is_zero():\n    assert total([]) == 0\n"
)
ADVICE = "Python files must stay UTF-8: do not add a coding cookie that names another encoding"


def violations(bench) -> list[dict]:
    return [e for e in bench.events("guard.violation") if e.get("rule") == "python encoding"]


def red_with(extra: dict[str, str]) -> Step:
    return Step(
        writes={"tests/test_discount.py": TESTS, PRICING: STUB, **extra},
        structured=result(
            "red", tests_added=["tests/test_discount.py::test_known_code"], criteria_ids=[KNOWN, UNKNOWN]
        ),
    )


def test_scn_sec_110_red_cannot_hide_a_return_in_a_pre_existing_test(make_bench):
    bench = make_bench([red_with({BASE_TEST: HIDDEN})])
    original = (bench.wb.worktree / BASE_TEST).read_text()
    base = bench.wb.head()
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "failed", out.reason
    assert BASE_TEST in out.reason and "iso" not in out.reason and "utf-7" in out.reason
    assert (bench.wb.worktree / BASE_TEST).read_text() == original  # put back
    assert bench.wb.head() == base and bench.events("task.red_ok") == []
    [event] = violations(bench)
    assert event["path"] == BASE_TEST and event["action"] == "restored" and event["phase"] == "red"
    assert "utf-7" in event["why"]
    assert ADVICE in guard_note_text([note_of("guard.violation", event)])


def test_scn_sec_111_green_cannot_hide_code_in_a_product_file(make_bench):
    bench = make_bench([red_step(), Step(writes={PRICING: COOKIE + IMPL}, structured=result("green"))])
    red = run_red(bench.wb, TASK, attempt=1)
    assert red.status == "ok", red.reason
    out = run_green(bench.wb, TASK, red, attempt=1)
    assert out.status == "failed" and PRICING in out.reason
    assert (bench.wb.worktree / PRICING).read_text() == STUB  # red's version
    assert bench.wb.head() == red.sha and bench.events("task.done") == []
    [event] = violations(bench)
    assert event["path"] == PRICING and event["phase"] == "green" and event["action"] == "restored"


def test_a_new_file_with_another_encoding_is_removed(make_bench):
    bench = make_bench([red_with({"src/pytdd/extra.py": COOKIE + "VALUE = 1\n"})])
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "failed"
    assert not (bench.wb.worktree / "src/pytdd/extra.py").exists()
    [event] = violations(bench)
    assert event["path"] == "src/pytdd/extra.py" and event["action"] == "removed"


def test_a_single_step_of_a_fix_chore_is_guarded_too(make_bench):
    bench = make_bench([Step(writes={PRICING: COOKIE + IMPL}, structured=result("single"))])
    base = bench.wb.head()
    out = run_single(bench.wb, FIX_TASK, FINDINGS, attempt=1)
    assert out.status == "failed" and PRICING in out.reason
    assert bench.wb.head() == base and bench.events("task.done") == []
    [event] = violations(bench)
    assert event["phase"] == "single" and event["path"] == PRICING


def test_a_refactor_chore_is_guarded_too(make_bench):
    bench = make_bench([Step(writes={PRICING: COOKIE + IMPL}, structured=result("single"))])
    out = run_single(bench.wb, FIX_TASK, FINDINGS, attempt=1, kind="refactor")
    assert out.status == "failed" and PRICING in out.reason
    [event] = violations(bench)
    assert event["phase"] == "single" and event["path"] == PRICING


def test_a_test_chore_is_guarded_too(make_bench):
    new_test = "tests/test_more.py"
    step = Step(writes={new_test: COOKIE + "def test_more():\n    assert True\n"}, structured=result("single"))
    bench = make_bench([step])
    out = run_single(bench.wb, FIX_TASK, FINDINGS, attempt=1, kind="tests")
    assert out.status == "failed" and new_test in out.reason
    assert not (bench.wb.worktree / new_test).exists()
    [event] = violations(bench)
    assert event["path"] == new_test


def test_a_blocked_step_cannot_carry_one_either(make_bench):
    step = Step(
        writes={PRICING: COOKIE + IMPL},
        structured=result("single", status="blocked", questions=[
            {"title": "Which rounding?", "context": "x", "kind": "ambiguous", "options": ["a", "b"]}
        ]),
    )  # fmt: skip
    bench = make_bench([step])
    out = run_single(bench.wb, FIX_TASK, FINDINGS, attempt=1)
    # on the code before L4-SEC-042 the blocked result won: status "blocked" with the question, no violation recorded
    assert out.status == "failed" and not out.questions
    assert PRICING in out.reason and "UTF-8" in out.reason
    [event] = violations(bench)
    assert event["path"] == PRICING and event["action"] == "restored"
    assert not (bench.wb.worktree / PRICING).read_bytes().startswith(COOKIE.encode())


@pytest.mark.parametrize("status", ["timeout", "error"])
def test_a_step_that_ends_badly_still_has_its_file_put_back_and_the_attempt_fails(make_bench, status):
    step = Step(status=status, writes={PRICING: COOKIE + IMPL}, structured=result("single"))
    bench = make_bench([step])
    base = bench.wb.head()
    out = run_single(bench.wb, FIX_TASK, FINDINGS, attempt=1)
    assert out.status == "failed"
    assert not (bench.wb.worktree / PRICING).read_bytes().startswith(COOKIE.encode())
    assert bench.wb.head() == base and bench.events("task.done") == []
    [event] = violations(bench)
    assert event["path"] == PRICING and event["action"] == "restored"


# --- a file of any size is checked: the cookie sits in the first two lines (F1) --------------------------------------

BIG = 9 * 1024 * 1024  # more than the 8 MiB the first version read
FILLER = ("#" + " " * 1022 + "\n") * (BIG // 1024 + 8)


def test_scn_sec_115_a_cookie_in_a_file_padded_over_eight_mib_is_flagged(make_bench):
    bench = make_bench([red_with({BASE_TEST: HIDDEN + FILLER})])
    original = (bench.wb.worktree / BASE_TEST).read_text()
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "failed" and BASE_TEST in out.reason and "utf-7" in out.reason
    assert (bench.wb.worktree / BASE_TEST).read_text() == original
    [event] = violations(bench)
    assert event["path"] == BASE_TEST and event["action"] == "restored"


def test_scn_sec_115_a_cookie_on_line_two_after_a_huge_first_line_is_flagged_as_unreadable(make_bench):
    huge = "# " + "x" * BIG + "\n" + COOKIE + IMPL
    bench = make_bench([Step(writes={PRICING: huge}, structured=result("single"))])
    out = run_single(bench.wb, FIX_TASK, FINDINGS, attempt=1)
    assert out.status == "failed" and PRICING in out.reason and "unreadable" in out.reason
    [event] = violations(bench)
    assert event["path"] == PRICING and "unreadable" in event["why"]


def test_a_huge_first_line_of_code_is_not_a_violation(make_bench):
    code = "DATA = '" + "x" * BIG + "'\n"
    bench = make_bench([Step(writes={PRICING: IMPL, "src/pytdd/data.py": code}, structured=result("single"))])
    out = run_single(bench.wb, FIX_TASK, FINDINGS, attempt=1)
    assert out.status == "ok", out.reason
    assert violations(bench) == []


def test_scn_sec_113_utf8_files_are_unaffected(make_bench):
    bodies = {
        "src/pytdd/plain.py": "VALUE = 1\n",
        "src/pytdd/utf8cookie.py": "# -*- coding: utf-8 -*-\nVALUE = 2\n",
        "src/pytdd/bom.py": "﻿VALUE = 3\n",
        "src/pytdd/shebang.py": "#!/usr/bin/env python\n# coding: UTF-8\nVALUE = 4\n",
        "src/pytdd/stub.pyi": "# coding: utf-8\nVALUE: int\n",
        "src/pytdd/ascii.py": "# coding: ascii\nVALUE = 5\n",
    }
    bench = make_bench([Step(writes={PRICING: IMPL, **bodies}, structured=result("single"))])
    out = run_single(bench.wb, FIX_TASK, FINDINGS, attempt=1)
    assert out.status == "ok", out.reason
    assert violations(bench) == []
    for rel, text in bodies.items():
        assert (bench.wb.worktree / rel).read_text(encoding="utf-8") == text


def test_the_guard_covers_pyi_and_other_declared_encodings_with_cookie_on_line_two(make_bench):
    writes = {
        "src/pytdd/a.pyi": "#!/usr/bin/env python\n# -*- coding: latin-1 -*-\nVALUE: int\n",
        "src/pytdd/b.py": "# coding: cp1252\nVALUE = 1\n",
    }
    bench = make_bench([Step(writes={PRICING: IMPL, **writes}, structured=result("single"))])
    out = run_single(bench.wb, FIX_TASK, FINDINGS, attempt=1)
    assert out.status == "failed"
    assert sorted(e["path"] for e in violations(bench)) == sorted(writes)
    assert "iso-8859-1" in out.reason and "cp1252" in out.reason
    assert not any((bench.wb.worktree / rel).exists() for rel in writes)


def test_scn_sec_114_a_file_that_is_not_python_is_unaffected(make_bench):
    bench = make_bench([Step(writes={PRICING: IMPL, "docs/a.md": COOKIE + "notes\n"}, structured=result("single"))])
    out = run_single(bench.wb, FIX_TASK, FINDINGS, attempt=1)
    assert out.status == "ok", out.reason
    assert violations(bench) == []
    assert (bench.wb.worktree / "docs/a.md").read_text() == COOKIE + "notes\n"


def test_a_replayed_step_loses_a_python_file_with_another_encoding_like_an_agent_step(make_bench, monkeypatch, raw):
    from l4.implementer.loop import run_task

    from .test_earlier_red import NEW
    from .test_earlier_red import TASK as HELD_TASK
    from .test_held_accept import forge_hold, held_new
    from .test_held_answers import answer

    bench = held_new(make_bench, monkeypatch)
    forge_hold(bench, raw, {"tests/test_new.py": NEW, "src/pytdd/hidden.py": COOKIE + "VALUE = 1\n"})
    answer(bench, raw, "accept: fine")
    run_task(bench.wb, HELD_TASK)
    assert len(bench.events("held.replayed")) == 1
    [event] = violations(bench)
    assert event["path"] == "src/pytdd/hidden.py" and event["action"] == "removed"
    assert not (bench.wb.worktree / "src/pytdd/hidden.py").exists()
    committed = bench.wb.git.run("log", "--name-only", "--format=", "main..HEAD").stdout
    assert "hidden.py" not in committed


# --- a Python-named link is followed (F2) ---------------------------------------------------------------------------

NOTES = "src/pytdd/notes.txt"
LINK = "src/pytdd/x.py"
PAYLOAD = COOKIE + "VALUE = 1  # +AAo-VALUE = 2\n"


def commit_links(bench, files: dict[str, str], links: dict[str, str]) -> None:
    import os

    for rel, text in files.items():
        (bench.wb.worktree / rel).write_text(text)
    for rel, target in links.items():
        os.symlink(target, bench.wb.worktree / rel)
    bench.wb.git.run("add", "-A")
    bench.wb.git.run("commit", "-q", "-m", "links of the repository")


def test_scn_sec_116_a_new_link_to_a_new_file_with_a_cookie_is_removed_with_its_target(make_bench):
    step = Step(writes={PRICING: IMPL, NOTES: PAYLOAD}, links={LINK: "notes.txt"}, structured=result("single"))
    bench = make_bench([step])
    base = bench.wb.head()
    out = run_single(bench.wb, FIX_TASK, FINDINGS, attempt=1)
    assert out.status == "failed" and LINK in out.reason and NOTES in out.reason
    assert not (bench.wb.worktree / LINK).is_symlink() and not (bench.wb.worktree / NOTES).exists()
    assert bench.wb.head() == base and bench.events("task.done") == []
    events = {e["path"]: e for e in violations(bench)}
    assert set(events) == {LINK, NOTES}
    assert all(e["action"] == "removed" and "utf-7" in e["why"] for e in events.values())
    assert LINK in events[NOTES]["why"] and NOTES in events[NOTES]["why"]  # the why names the link and its target


def test_scn_sec_116_a_link_already_in_the_base_whose_target_the_step_changes(make_bench):
    bench = make_bench([])
    commit_links(bench, {NOTES: "VALUE = 1\n"}, {LINK: "notes.txt"})
    bench.adapter._script.append(Step(writes={PRICING: IMPL, NOTES: PAYLOAD}, structured=result("single")))
    out = run_single(bench.wb, FIX_TASK, FINDINGS, attempt=1)
    assert out.status == "failed" and NOTES in out.reason
    assert (bench.wb.worktree / NOTES).read_text() == "VALUE = 1\n"  # put back
    assert (bench.wb.worktree / LINK).is_symlink()  # the link is the base's own: it stays
    [event] = violations(bench)
    assert event["path"] == NOTES and event["action"] == "restored" and LINK in event["why"]


def test_scn_sec_116_a_chain_of_links_is_followed(make_bench):
    bench = make_bench([])
    commit_links(bench, {"src/pytdd/real.txt": "VALUE = 1\n"}, {"src/pytdd/mid.txt": "real.txt", LINK: "mid.txt"})
    step = Step(writes={PRICING: IMPL, "src/pytdd/real.txt": PAYLOAD}, structured=result("single"))
    bench.adapter._script.append(step)
    out = run_single(bench.wb, FIX_TASK, FINDINGS, attempt=1)
    assert out.status == "failed"
    [event] = violations(bench)
    assert event["path"] == "src/pytdd/real.txt" and LINK in event["why"]


def test_a_python_named_link_to_a_clean_file_is_not_a_violation(make_bench):
    step = Step(writes={PRICING: IMPL, NOTES: "VALUE = 1\n"}, links={LINK: "notes.txt"}, structured=result("single"))
    bench = make_bench([step])
    out = run_single(bench.wb, FIX_TASK, FINDINGS, attempt=1)
    assert out.status == "ok", out.reason
    assert violations(bench) == [] and (bench.wb.worktree / LINK).is_symlink()


def test_a_link_that_does_not_resolve_to_a_file_in_the_tree_is_left_to_the_other_guards(make_bench):
    links = {LINK: "missing.txt", "src/pytdd/y.py": "../pytdd"}
    bench = make_bench([Step(writes={PRICING: IMPL}, links=links, structured=result("single"))])
    run_single(bench.wb, FIX_TASK, FINDINGS, attempt=1)
    assert violations(bench) == []
