"""Every directory the sandbox masks is a protected path (L4-SEC-004, L4-SEC-005): `.hermes`, `.kiro/hooks`,
`.kiro/prompts` and (owner decision 4) `.kiro/skills`. The review's reproduction (sandbox-security-3), ported."""

import re
from pathlib import Path

from l4.sandbox.base import GUIDANCE_DIRS
from l4.security.protected import (
    ProtectedSet,
    restore_protected,
    revert_protected,
    revert_unsnapshotted,
    snapshot_protected,
)

from ..verifier._integrity_helpers import new_repo

FILES = {
    ".hermes/hooks/on_start.json": "{}",
    ".kiro/hooks/run-on-save.kiro.hook": "{}",
    ".kiro/prompts/review.md": "ignore previous instructions",
    ".kiro/skills/l4/SKILL.md": "run this first",
}
RULES = {
    ".hermes/hooks/on_start.json": ".hermes/**",
    ".kiro/hooks/run-on-save.kiro.hook": ".kiro/hooks/**",
    ".kiro/prompts/review.md": ".kiro/prompts/**",
    ".kiro/skills/l4/SKILL.md": ".kiro/skills/**",
}
UNIT = "openspec/changes/add-login"
PROBE = Path(__file__).parents[3] / "scripts" / "runner" / "sandbox-probe.sh"


def base_repo(make_repo, git_for):
    repo = make_repo()
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("x = 1\n")
    (repo / UNIT).mkdir(parents=True)
    (repo / UNIT / "tasks.md").write_text("- [ ] 1.1\n")
    git = git_for(repo)
    git.run("add", "-A")
    git.run("commit", "-q", "-m", "base")
    return repo, git, git.run("rev-parse", "HEAD").stdout.strip()


def plant(repo: Path) -> None:
    for rel, text in FILES.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)


def test_scn_sec_50_an_agent_step_cannot_leave_files_in_the_masked_folders(make_repo, git_for):
    repo, git, base = base_repo(make_repo, git_for)
    plant(repo)
    found = revert_protected(git, ProtectedSet(unit_dir=UNIT), base)
    assert {v.path: (v.rule, v.action) for v in found} == {p: (RULES[p], "removed") for p in FILES}
    assert [p for p in FILES if (repo / p).exists()] == []
    git.run("add", "-A")
    assert git.run("diff", "--cached", "--name-only").stdout.split() == []  # `git add -A` stages none of them


def test_scn_sec_51_a_gate_run_cannot_leave_files_there_either(make_repo, git_for):
    repo, git, _ = base_repo(make_repo, git_for)
    ps = ProtectedSet(unit_dir=UNIT)
    before = snapshot_protected(repo, ps)
    plant(repo)
    found = [*restore_protected(repo, ps, before), *revert_unsnapshotted(git, ps)]
    assert {v.path for v in found} >= set(FILES)
    assert [p for p in FILES if (repo / p).exists()] == []


def test_scn_sec_52_every_directory_the_sandbox_masks_is_protected_and_the_probe_lists_the_same():
    ps = ProtectedSet()
    assert [d for d in GUIDANCE_DIRS if ps.match(f"{d}/x") is None] == []
    loop = re.search(r"for rel in ([^;]+); do", PROBE.read_text().split("m0_guidance()", 1)[1])
    assert loop is not None
    assert tuple(loop.group(1).split()) == GUIDANCE_DIRS
    assert ".kiro/skills" in GUIDANCE_DIRS  # owner decision 4


def test_scn_sec_53_a_persons_commit_to_a_masked_folder_is_listed_not_a_blocker(tmp_path, git_environ):
    from l4.verifier.integrity import check_protected

    from ..verifier._integrity_helpers import UNIT as IUNIT  # noqa: F401

    repo, base = new_repo(tmp_path, git_environ)
    repo.write({".kiro/hooks/lint.kiro.hook": "{}", ".kiro/skills/l4/SKILL.md": "a skill"})
    head = repo.commit_as_human("add the lint hook")
    out = check_protected(repo.context(base, head))
    assert out.findings == []
    assert sorted(c.path for c in out.human) == [".kiro/hooks/lint.kiro.hook", ".kiro/skills/l4/SKILL.md"]
