from ...live.protocol_m12 import (
    console_lines,
    fallback_number,
    independence_line,
    selected_line,
    selections,
    skipped_line,
    trailer_values,
    unit_implementer_commits,
)

LOG = """\
Running with gitlab-runner 18.0
section_start:1:step_script\r\x1b[0K\x1b[36;1m
[l4] implementer: codex skipped — quota: 5h window 80% used, 20% remaining < 100% (profile reserve); cool-down recorded
[l4] implementer: kiro skipped — auth: kiro-cli installed, not authenticated
[l4] implementer: opencode-free ok (binary 1.18.34 · auth skipped · quota skipped · hello 4.2s) → selected, fallback #2
[l4] judges: claude-code ok (binary 2.1.288 · auth max · quota 12% used (session) · hello 2.0s · cached) → selected
"""


def test_console_lines_are_found_by_role_and_profile():
    assert len(console_lines(LOG, "implementer", "codex")) == 1
    assert skipped_line(LOG, "implementer", "kiro") == (
        "[l4] implementer: kiro skipped — auth: kiro-cli installed, not authenticated"
    )
    assert skipped_line(LOG, "implementer", "opencode-free") is None
    line = selected_line(LOG, "implementer", "opencode-free")
    assert line is not None and fallback_number(line) == 2
    judge = selected_line(LOG, "judges", "claude-code")
    assert judge is not None and fallback_number(judge) is None and "· cached" in judge


def test_events_trailers_and_the_independence_line():
    events = [
        {"type": "availability.selected", "role": "judges", "selected": "a"},
        {"type": "availability.selected", "role": "implementer", "selected": "b"},
        {"type": "phase.changed"},
    ]
    assert [e["selected"] for e in selections(events, "judges")] == ["a"]
    message = "feat(x): y\n\nL4-Unit: openspec:x\nL4-Agent: codex/gpt\nL4-Fallback-From: codex\n"
    assert trailer_values(message, "L4-Fallback-From") == ["codex"] and trailer_values(message, "L4-Tdd") == []
    md = "# V\n\n- Judge: j\n- independence: declared (unverified): j zhipu (declared), codex openai (tool)\n"
    assert independence_line(md) == "independence: declared (unverified): j zhipu (declared), codex openai (tool)"
    assert independence_line("nothing here") is None


def test_only_the_units_own_red_and_green_commits_count():
    """Live finding (P2 re-run, job 5467): a unit branch also reaches main's history, where another unit's codex commits
    sit; those must not be read as this unit's implementer commits."""

    def commit(title: str, unit: str, task: bool = True) -> dict[str, str]:
        trailers = f"L4-Unit: openspec:{unit}\n" + ("L4-Task: 1.1\nL4-Agent: x\n" if task else "")
        return {"title": title, "message": f"{title}\n\n{trailers}"}

    commits = [
        commit("docs(add-split-amount): hand off to review", "add-split-amount", task=False),
        commit("feat(add-split-amount): 1.1 split", "add-split-amount"),
        commit("test(add-split-amount): red for 1.1", "add-split-amount"),
        commit("feat(add-discount-codes): 1.2 apply_code", "add-discount-codes"),
        {"title": "Seed add-split-amount", "message": "Seed add-split-amount\n"},
    ]
    found = unit_implementer_commits(commits, "openspec:add-split-amount")
    assert [c["title"] for c in found] == ["feat(add-split-amount): 1.1 split", "test(add-split-amount): red for 1.1"]
