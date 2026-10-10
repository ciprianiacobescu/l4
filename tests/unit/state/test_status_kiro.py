from l4.specs.kiro import KiroProvider
from l4.state.status import load_snapshot
from l4.vcs.git import BOT_IDENTITY

SPEC = ".kiro/specs/greet"
TASKS = (
    "- [ ] 1. Greet\n  - [ ] 1.1 Add greet\n    - _Requirements: 1.1_\n  - [ ]* 1.2 Blank name test\n"
    "\n## Task Dependency Graph\n\n```json\n" '{"waves": [{"id": 0, "tasks": ["1.1"]}]}\n```\n'
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
