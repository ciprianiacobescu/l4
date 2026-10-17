import json

from l4.specs.kiro import KiroProvider
from l4.state.status import load_snapshot
from l4.vcs.git import BOT_IDENTITY

SPEC = ".kiro/specs/greet"
TASKS = (
    "- [ ] 1. Greet\n  - [ ] 1.1 Add greet\n    - _Requirements: 1.1_\n  - [ ]* 1.2 Blank name test\n"
    "\n## Task Dependency Graph\n\n```json\n"
    '{"waves": [{"id": 0, "tasks": ["1.1"]}]}\n```\n'
)


def test_kiro_tasks_parsed_from_unit_branch(make_repo, git_for, trailers):
    repo = make_repo(remote=True)
    git = git_for(repo)
    (repo / SPEC).mkdir(parents=True)
    (repo / SPEC / "tasks.md").write_text(TASKS)
    (repo / SPEC / "requirements.md").write_text("### Requirement 1\n\n1. WHEN greeted THEN it answers\n")
    git.run("add", "-A")
    git.commit("add the spec", trailers, BOT_IDENTITY)
    git.push("origin", ["HEAD:refs/heads/main"])
    git.run("checkout", "-q", "-b", "l4/kiro/greet")
    (repo / SPEC / "tasks.md").write_text(TASKS.replace("[ ] 1.1", "[x] 1.1").replace("[ ] 1. ", "[x] 1. "))
    git.run("add", "-A")
    git.commit("checkpoint", trailers, BOT_IDENTITY)
    git.push("origin", ["HEAD:refs/heads/l4/kiro/greet"])
    git.run("checkout", "-q", "main")
    git.run("branch", "-q", "-D", "l4/kiro/greet")
    git.fetch("origin")

    provider = KiroProvider(repo)
    (ref,) = provider.list_units()
    snap = load_snapshot(provider, git, ref, branch_prefix="l4/")
    assert snap.source == "branch"
    assert [(t.key, t.done, t.optional, t.wave) for t in snap.tasks] == [
        ("1", True, False, None), ("1.1", True, False, 0), ("1.2", False, True, None),
    ]  # fmt: skip
    assert (snap.tasks_done, snap.tasks_total) == (2, 2)  # the open optional leaf is not counted


# -- the last cut of a unit's prompt (kiro-prompt-context, L4-IMP-054; SCN-IMP-289, status part) ----------------------

CUT = {
    "path": ".kiro/specs/tip-calc/design.md", "kind": "design", "reason": "budget", "shown_chars": 61234,
    "total_chars": 125492, "omitted": [[640, 2203]], "readable": True,
}  # fmt: skip


def truncated(**over: object) -> dict:
    return {"role": "red", "task": "1", "attempt": 1, "budget_tokens": 24000, "sources": [CUT], **over}


def test_status_prints_the_last_implementer_cut_and_json_carries_it(unit_repo, trailers, capsys):
    from .test_status_activity import UNIT, started_at, status

    def ledger(repo):
        events = [(5, "prompt.truncated", truncated()), (3, "prompt.truncated", truncated(role="judge", task=""))]
        started_at(repo, "r-20261016T1101Z-1a2b", 21, events, command="run")

    unit_repo.push_unit_branch(ledger, trailers)
    block = status(unit_repo, capsys, "--unit", UNIT)
    assert (
        "Prompt cut: task 1 red attempt 1: .kiro/specs/tip-calc/design.md 61234 of 125492 characters "
        "(raise implementer.context_budget_tokens or shorten the file)"
    ) in block.splitlines()  # a later judge cut does not replace it
    data = json.loads(status(unit_repo, capsys, "--json"))
    cut = data["units"][0]["prompt_cut"]
    assert (cut["role"], cut["task"], cut["attempt"]) == ("red", "1", 1) and cut["sources"][0]["path"] == CUT["path"]


def test_status_lists_at_most_three_files_and_a_unit_without_a_cut_prints_no_line(unit_repo, trailers, capsys):
    from .test_status_activity import UNIT, started_at, status

    many = [{**CUT, "path": f"f{i}.md"} for i in range(5)]
    unit_repo.push_unit_branch(
        lambda repo: started_at(repo, "r-20261016T1101Z-1a2b", 21, [(5, "prompt.truncated", truncated(sources=many))]),
        trailers,
    )
    line = next(x for x in status(unit_repo, capsys, "--unit", UNIT).splitlines() if x.startswith("Prompt cut:"))
    assert "f0.md 61234 of 125492 characters" in line and "f2.md" in line and "f3.md" not in line
    assert ", and 2 more (raise" in line


def test_a_unit_with_no_cut_prints_no_prompt_cut_line_and_a_null_key(unit_repo, trailers, capsys):
    from .test_status_activity import UNIT, ledger_with_open_run, status

    unit_repo.push_unit_branch(ledger_with_open_run, trailers)
    assert "Prompt cut" not in status(unit_repo, capsys, "--unit", UNIT)
    assert json.loads(status(unit_repo, capsys, "--json"))["units"][0]["prompt_cut"] is None
