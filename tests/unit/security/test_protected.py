import os
from collections.abc import Callable
from pathlib import Path

import pytest

from l4.security.protected import (
    CONTRACT_PROTECTED_GLOBS,
    ProtectedSet,
    forbidden_rule,
    glob_match,
    is_protected,
    restore_protected,
    revert_protected,
    revert_unsnapshotted,
    snapshot_protected,
)

UNIT = "openspec/changes/add-x"
LEDGER_DIR = f"{UNIT}/.l4/ledger"
OWN = f"{LEDGER_DIR}/r-20261003T1312Z-7f3a.jsonl"


class Sink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def append(self, event_type, /, **data):
        self.events.append((event_type, data))


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("**/migrations/**", "migrations/0001.sql", True),
        ("**/migrations/**", "app/db/migrations/0001.sql", True),
        ("**/migrations/**", "app/db/migration/0001.sql", False),
        ("infra/**", "infra/main.tf", True),
        ("infra/**", "infra", True),
        ("infra/**", "src/infra/main.tf", False),
        (".mcp.json", ".mcp.json", True),
        (".mcp.json", "sub/.mcp.json", False),
        ("*.py", "a/b.py", False),
        ("*.py", "b.py", True),
        ("**/test_*.*", "tests/unit/test_a.py", True),
        (".github/workflows/**", ".github/workflows/ci.yml", True),
        (".github/workflows/**", ".github/CODEOWNERS", False),
    ],
)
def test_glob_match_semantics(pattern, path, expected):
    assert glob_match(pattern, path) is expected


def test_contract_list_and_forbidden_paths_match():
    for path in (".gitlab-ci.yml", ".gitlab/ci/a.yml", ".l4/config.yaml", ".claude/settings.json", ".codex/config.toml",
                 "opencode.json", ".kiro/agents/x.json", ".kiro/settings/y", ".serena/project.yml",
                 ".serena/memories/harness/a.md"):  # fmt: skip
        assert is_protected(path), path
    assert len(CONTRACT_PROTECTED_GLOBS) == 27  # +4 guidance folders (L4-SEC-004, SCN-SEC-52)
    assert is_protected("db/migrations/1.sql", ["**/migrations/**"]) == "**/migrations/**"
    assert is_protected("src/app.py") is None
    assert is_protected(".serena/memories/lessons/a.md") is None


def test_a_file_below_a_protected_file_is_protected_too():
    assert is_protected(".mcp.json/evil") == ".mcp.json"


def test_unit_dir_is_protected_except_the_runs_own_ledger_file():
    protected = ProtectedSet(unit_dir=UNIT, run_ledger=OWN)
    assert protected.match(f"{UNIT}/tasks.md")
    assert protected.match(f"{UNIT}/.l4/ledger/r-20261003T1312Z-aaaa.jsonl")
    assert protected.match(f"{UNIT}/questions.md")
    assert protected.match(OWN) is None
    assert protected.match("src/app.py") is None
    assert protected.match("openspec/changes/other/tasks.md")  # HB-3: a sibling change is protected too (H18)


@pytest.fixture
def worktree(make_repo, raw, git_for) -> Callable[[], tuple[Path, str]]:
    def make():
        repo = make_repo()
        files = {
            ".claude/settings.json": "{}\n", ".gitlab-ci.yml": "ci: 1\n", ".mcp.json": "{}\n", "src/app.py": "x = 1\n",
            f"{UNIT}/tasks.md": "- [ ] 1.1 a\n", f"{UNIT}/proposal.md": "p\n", "infra/main.tf": "t\n",
            ".gitignore": "ignored/\n*.secret\n",
        }  # fmt: skip
        for name, text in files.items():
            (repo / name).parent.mkdir(parents=True, exist_ok=True)
            (repo / name).write_text(text)
        raw(repo, "add", "-A")
        raw(repo, "commit", "-q", "-m", "base")
        return repo, raw(repo, "rev-parse", "HEAD").strip()

    return make


def test_agent_edit_to_agent_config_is_reverted(worktree, git_for, raw):
    repo, base = worktree()
    (repo / ".claude/settings.json").write_text('{"hooks": "evil"}\n')
    (repo / ".gitlab-ci.yml").unlink()
    (repo / ".mcp.json").write_text("changed\n")
    (repo / ".codex").mkdir()
    (repo / ".codex/config.toml").write_text("planted\n")  # untracked, not ignored
    (repo / "src/app.py").write_text("x = 2\n")  # not protected: stays
    (repo / f"{UNIT}/tasks.md").write_text("- [x] 1.1 a\n")
    (repo / f"{UNIT}/questions.md").write_text("# planted\n")
    (repo / "infra/main.tf").write_text("owned\n")
    sink = Sink()
    out = revert_protected(git_for(repo), ProtectedSet(("infra/**",), UNIT, OWN), base, events=sink)
    assert (repo / ".claude/settings.json").read_text() == "{}\n"
    assert (repo / ".gitlab-ci.yml").read_text() == "ci: 1\n"
    assert (repo / ".mcp.json").read_text() == "{}\n"
    assert not (repo / ".codex").exists()
    assert (repo / f"{UNIT}/tasks.md").read_text() == "- [ ] 1.1 a\n" and not (repo / f"{UNIT}/questions.md").exists()
    assert (repo / "infra/main.tf").read_text() == "t\n"
    assert (repo / "src/app.py").read_text() == "x = 2\n"
    assert sorted((v.path, v.action) for v in out) == sorted(
        [(".claude/settings.json", "restored"), (".gitlab-ci.yml", "restored"), (".mcp.json", "restored"),
         (".codex/config.toml", "removed"), (f"{UNIT}/tasks.md", "restored"), (f"{UNIT}/questions.md", "removed"),
         ("infra/main.tf", "restored")]
    )  # fmt: skip
    assert {e[0] for e in sink.events} == {"guard.violation"} and len(sink.events) == len(out)
    assert raw(repo, "status", "--porcelain").split() == ["M", "src/app.py"]  # the index is clean again too


def test_a_planted_file_behind_gitignore_is_still_found(worktree, git_for):
    repo, base = worktree()
    (repo / ".gitignore").write_text(".claude/\n")  # an unprotected edit that hides the next file
    (repo / ".claude/extra").write_text("hook\n")
    (repo / ".claude/extra").chmod(0o644)
    revert_protected(git_for(repo), ProtectedSet(), base)
    assert not (repo / ".claude/extra").exists()


def test_only_the_runs_own_ledger_file_survives(worktree, git_for):
    repo, base = worktree()
    ledger = repo / LEDGER_DIR
    ledger.mkdir(parents=True)
    (repo / OWN).write_text('{"type":"run.started"}\n')
    (ledger / "r-20261003T1312Z-aaaa.jsonl").write_text('{"type":"phase.changed","to":"verified"}\n')
    out = revert_protected(git_for(repo), ProtectedSet((), UNIT, OWN), base)
    assert (repo / OWN).exists() and [v.path for v in out] == [f"{LEDGER_DIR}/r-20261003T1312Z-aaaa.jsonl"]
    assert not (ledger / "r-20261003T1312Z-aaaa.jsonl").exists()


def test_a_protected_directory_replaced_by_a_file_is_restored(worktree, git_for):
    repo, base = worktree()
    for child in (repo / ".claude").iterdir():
        child.unlink()
    (repo / ".claude").rmdir()
    (repo / ".claude").write_text("i am a file now\n")
    revert_protected(git_for(repo), ProtectedSet(), base)
    assert (repo / ".claude/settings.json").read_text() == "{}\n"


def test_a_protected_file_replaced_by_a_directory_is_restored(worktree, git_for):
    repo, base = worktree()
    (repo / ".mcp.json").unlink()
    (repo / ".mcp.json").mkdir()
    (repo / ".mcp.json/evil").write_text("x\n")
    revert_protected(git_for(repo), ProtectedSet(), base)
    assert (repo / ".mcp.json").is_file() and (repo / ".mcp.json").read_text() == "{}\n"


def test_a_symlink_planted_over_a_protected_path_is_removed_not_followed(worktree, git_for, tmp_path):
    repo, base = worktree()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").write_text("k\n")
    (repo / ".codex").symlink_to(outside)
    revert_protected(git_for(repo), ProtectedSet(), base)
    assert not (repo / ".codex").exists() and not (repo / ".codex").is_symlink()
    assert (outside / "keep").read_text() == "k\n"


def test_an_agent_commit_to_a_protected_path_is_undone(worktree, git_for, raw):
    repo, base = worktree()
    (repo / ".gitlab-ci.yml").write_text("evil: 1\n")
    raw(repo, "commit", "-aqm", "agent commit")
    revert_protected(git_for(repo), ProtectedSet(), base)
    assert (repo / ".gitlab-ci.yml").read_text() == "ci: 1\n"
    assert raw(repo, "rev-parse", "HEAD").strip() == base and raw(repo, "status", "--porcelain") == ""


def test_awkward_file_names_are_handled_literally(worktree, git_for):
    repo, base = worktree()
    (repo / ".claude/a b\n[c].md").write_text("x\n")
    revert_protected(git_for(repo), ProtectedSet(), base)
    assert [p.name for p in (repo / ".claude").iterdir()] == ["settings.json"]


def test_nothing_changed_is_a_no_op(worktree, git_for):
    repo, base = worktree()
    assert revert_protected(git_for(repo), ProtectedSet((), UNIT, OWN), base) == []
    assert os.listdir(repo / ".claude") == ["settings.json"]


def _commit_ignore(repo, raw, text: str, where: str = ".gitignore") -> str:
    (repo / where).parent.mkdir(parents=True, exist_ok=True)
    (repo / where).write_text(text)
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "ignore rules")
    return raw(repo, "rev-parse", "HEAD").strip()


def test_installed_dependencies_ignored_at_the_base_are_not_planted_files(worktree, git_for, raw):
    repo, _ = worktree()
    base = _commit_ignore(repo, raw, ".venv/\nnode_modules/\n")
    for name in (".venv/lib/python3.12/site-packages/django/contrib/admin/migrations/0001_initial.py",
                 "node_modules/some-orm/migrations/001.js"):  # fmt: skip
        (repo / name).parent.mkdir(parents=True)
        (repo / name).write_text("installed\n")
    (repo / "migrations").mkdir()
    (repo / "migrations/0002.py").write_text("planted\n")
    out = revert_protected(git_for(repo), ProtectedSet(("**/migrations/**",), UNIT, OWN), base)
    assert [(v.path, v.action) for v in out] == [("migrations/0002.py", "removed")]
    assert (repo / ".venv/lib/python3.12/site-packages/django/contrib/admin/migrations/0001_initial.py").exists()
    assert (repo / "node_modules/some-orm/migrations/001.js").exists()


def test_nested_ignore_files_at_the_base_apply_below_their_directory(worktree, git_for, raw):
    repo, _ = worktree()
    (repo / "web").mkdir()
    (repo / "web/.gitignore").write_text("vendor/\n/dist/migrations/\n!keep.py\n")
    base = _commit_ignore(repo, raw, "ignored/\n")
    for name in ("web/vendor/pkg/migrations/a.py", "web/dist/migrations/b.py", "vendor/migrations/c.py"):
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text("x\n")
    out = revert_protected(git_for(repo), ProtectedSet(("**/migrations/**",)), base)
    assert [v.path for v in out] == ["vendor/migrations/c.py"]  # the nested file scopes its rules to web/


def test_a_gitignore_edited_by_the_agent_hides_nothing(worktree, git_for, raw):
    repo, base = worktree()
    (repo / "migrations").mkdir()
    (repo / "migrations/0002.py").write_text("planted\n")
    (repo / ".gitignore").write_text("ignored/\n*.secret\nmigrations/\n")  # not the base's rules
    out = revert_protected(git_for(repo), ProtectedSet(("**/migrations/**",)), base)
    assert [v.path for v in out] == ["migrations/0002.py"]


def test_a_contract_path_hidden_by_the_base_ignore_rules_is_still_removed(worktree, git_for, raw):
    repo, _ = worktree()
    base = _commit_ignore(repo, raw, ".codex/\n")  # a repo that ignores an agent's local config directory
    (repo / ".codex").mkdir()
    (repo / ".codex/config.toml").write_text("planted\n")
    out = revert_protected(git_for(repo), ProtectedSet(), base)
    assert [(v.path, v.action) for v in out] == [(".codex/config.toml", "removed")]


def test_a_snapshot_puts_back_what_a_gate_changed_added_deleted_or_linked(tmp_path: Path):
    from l4.security.protected import restore_protected, snapshot_protected

    root = tmp_path / "repo"
    (root / UNIT / ".l4/ledger").mkdir(parents=True)
    (root / UNIT / "questions.md").write_text("asked\n")
    (root / UNIT / "tasks.md").write_text("- [ ] 1.1 a\n")
    (root / UNIT / ".l4/ledger/r-old.jsonl").write_text("old\n")
    (root / OWN).write_text("mine\n")
    (root / ".github/workflows").mkdir(parents=True)
    (root / ".github/workflows/ci.yml").write_text("on: push\n")
    (root / ".mcp.json").write_text("{}")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep\n")
    protected = ProtectedSet((), UNIT, OWN)
    before = snapshot_protected(root, protected)

    (root / UNIT / "questions.md").write_text("forged\n")  # changed
    (root / UNIT / "tasks.md").unlink()  # deleted
    (root / UNIT / ".l4/ledger/r-old.jsonl").write_text("planted\n")  # an earlier run's ledger
    (root / UNIT / "new.md").write_text("new\n")  # added
    (root / OWN).write_text("the run's own ledger is not this function's business\n")
    (root / ".mcp.json").unlink()
    (root / ".mcp.json").symlink_to(outside / "keep.txt")  # a file replaced by a link
    (root / ".github/workflows").rename(root / "wf-moved")
    (root / ".github/workflows").symlink_to(outside)  # a directory replaced by a link out of the tree

    violations = restore_protected(root, protected, before)

    assert (root / UNIT / "questions.md").read_text() == "asked\n"
    assert (root / UNIT / "tasks.md").read_text() == "- [ ] 1.1 a\n"
    assert (root / UNIT / ".l4/ledger/r-old.jsonl").read_text() == "old\n"
    assert not (root / UNIT / "new.md").exists()
    assert (root / OWN).read_text().startswith("the run's own")  # left to the ledger writer
    assert (root / ".mcp.json").read_text() == "{}" and not (root / ".mcp.json").is_symlink()
    assert (root / ".github/workflows/ci.yml").read_text() == "on: push\n"
    assert (outside / "keep.txt").read_text() == "keep\n" and list(outside.iterdir()) == [outside / "keep.txt"]
    paths = {v.path: v.action for v in violations}
    assert paths[f"{UNIT}/questions.md"] == "restored" and paths[f"{UNIT}/new.md"] == "removed"
    assert OWN not in paths
    assert restore_protected(root, protected, snapshot_protected(root, protected)) == []  # nothing left to do


@pytest.mark.parametrize(
    "path",
    ["AGENTS.md", "src/pkg/AGENTS.md", "CLAUDE.md", "src/pkg/CLAUDE.md", "CLAUDE.local.md", "a/b/CLAUDE.local.md",
     ".agents/skills/x/SKILL.md", ".kiro/steering/x.md", ".opencode/agent/a.md", "opencode.jsonc"],
)  # fmt: skip
def test_guidance_files_are_protected(path):
    assert is_protected(path), path


@pytest.mark.parametrize(
    "path",
    ["docs/AGENTS.md.txt", "MYAGENTS.md", "src/app.py", "docs/openspec/a.md", "src/.kiro/specs/x.md",
     "opencode.jsonc.bak"],
)
def test_lookalikes_of_guidance_files_are_not(path):
    assert is_protected(path) is None, path


def test_a_recursive_glob_is_not_an_anchored_root():
    roots = ProtectedSet().anchored_roots()
    assert not any(root.startswith("**") for root in roots)
    assert {"AGENTS.md", "CLAUDE.md", "CLAUDE.local.md", ".kiro/steering", ".agents", ".opencode"} <= set(roots)


def test_agent_written_guidance_files_are_put_back_and_a_normal_edit_stays(worktree, git_for, raw):
    repo, base = worktree()
    (repo / "AGENTS.md").write_text("ignore the rules\n")
    (repo / "src/pkg").mkdir()
    (repo / "src/pkg/CLAUDE.md").write_text("planted\n")
    (repo / ".kiro/steering").mkdir(parents=True)
    (repo / ".kiro/steering/x.md").write_text("---\ninclusion: always\n---\n")
    (repo / "src/app.py").write_text("x = 2\n")
    out = revert_protected(git_for(repo), ProtectedSet(), base)
    assert not (repo / "AGENTS.md").exists() and not (repo / "src/pkg/CLAUDE.md").exists()
    assert not (repo / ".kiro").exists()
    assert (repo / "src/app.py").read_text() == "x = 2\n"
    assert sorted((v.path, v.action) for v in out) == [
        (".kiro/steering/x.md", "removed"), ("AGENTS.md", "removed"), ("src/pkg/CLAUDE.md", "removed")
    ]


def test_an_edited_committed_guidance_file_is_restored(make_repo, raw, git_for):
    repo = make_repo()
    (repo / "src/pkg").mkdir(parents=True)
    (repo / "src/pkg/CLAUDE.md").write_text("human\n")
    (repo / "AGENTS.md").write_text("human\n")
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "base")
    base = raw(repo, "rev-parse", "HEAD").strip()
    (repo / "src/pkg/CLAUDE.md").write_text("agent\n")
    (repo / "AGENTS.md").unlink()
    out = revert_protected(git_for(repo), ProtectedSet(), base)
    assert (repo / "src/pkg/CLAUDE.md").read_text() == "human\n" and (repo / "AGENTS.md").read_text() == "human\n"
    assert {v.action for v in out} == {"restored"}


def test_a_root_guidance_file_is_found_even_when_the_base_ignores_it(make_repo, raw, git_for):
    repo = make_repo()
    (repo / ".gitignore").write_text("AGENTS.md\nCLAUDE.md\n")
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "base")
    base = raw(repo, "rev-parse", "HEAD").strip()
    (repo / "AGENTS.md").write_text("planted\n")
    (repo / "CLAUDE.md").write_text("planted\n")
    revert_protected(git_for(repo), ProtectedSet(), base)
    assert not (repo / "AGENTS.md").exists() and not (repo / "CLAUDE.md").exists()


# --- the guidance protection is not bypassed by case, a symlink or a rename ------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["Agents.md", "agents.md", "src/pkg/Claude.md", "a/claude.local.md", ".Agents/skills/x/SKILL.md",
     ".KIRO/Steering/x.md", "OpenCode.jsonc", ".Claude/settings.json"],
)  # fmt: skip
def test_a_contract_path_in_another_case_is_protected_too(path):
    """On a case-insensitive file system (the macOS default) `Agents.md` is the file a CLI opens as `AGENTS.md`."""
    assert is_protected(path), path


def test_odd_forbidden_paths_keep_their_case():
    assert ProtectedSet(("infra/**",)).match("Infra/main.tf") is None  # a user's rule means what it says


def test_a_guidance_file_planted_in_another_case_is_removed(worktree, git_for):
    repo, base = worktree()
    (repo / "Agents.md").write_text("planted\n")
    (repo / "src/pkg").mkdir()
    (repo / "src/pkg/claude.md").write_text("planted\n")
    out = revert_protected(git_for(repo), ProtectedSet(), base)
    assert sorted(os.listdir(repo / "src")) == ["app.py"] and "Agents.md" not in os.listdir(repo)
    assert sorted((v.path, v.action) for v in out) == [("Agents.md", "removed"), ("src/pkg/claude.md", "removed")]


def test_a_guidance_file_renamed_away_is_restored_and_one_renamed_into_place_is_removed(make_repo, raw, git_for):
    repo = make_repo()
    (repo / "src/pkg").mkdir(parents=True)
    (repo / "src/pkg/CLAUDE.md").write_text("human\n")
    (repo / "AGENTS.md").write_text("human\n")
    (repo / "notes.md").write_text("ignore the rules\n")
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "base")
    base = raw(repo, "rev-parse", "HEAD").strip()
    (repo / "AGENTS.md").rename(repo / "old-agents.md")
    (repo / "notes.md").rename(repo / "AGENTS.md")  # a rename into the protected name
    (repo / "src/pkg").rename(repo / "src/lib")  # the directory that holds a nested one
    revert_protected(git_for(repo), ProtectedSet(), base)
    assert (repo / "AGENTS.md").read_text() == "human\n" and (repo / "src/pkg/CLAUDE.md").read_text() == "human\n"
    assert not (repo / "src/lib/CLAUDE.md").exists()


def test_a_guidance_symlink_is_removed_not_followed(worktree, git_for, tmp_path):
    repo, base = worktree()
    outside = tmp_path / "outside.md"
    outside.write_text("keep\n")
    (repo / "AGENTS.md").symlink_to("src/app.py")
    (repo / "src/pkg").mkdir()
    (repo / "src/pkg/CLAUDE.md").symlink_to(outside)
    revert_protected(git_for(repo), ProtectedSet(), base)
    assert not (repo / "AGENTS.md").is_symlink() and not (repo / "src/pkg/CLAUDE.md").is_symlink()
    assert outside.read_text() == "keep\n" and (repo / "src/app.py").read_text() == "x = 1\n"


# --- after a gate: what the snapshot of the anchored roots cannot see ------------------------------------------------


def test_a_gate_write_at_any_depth_is_put_back_to_head_and_the_harness_writes_stay(worktree, git_for, raw):
    repo, _ = worktree()
    (repo / "src/pkg").mkdir()
    (repo / "src/pkg/CLAUDE.md").write_text("human\n")
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "nested guidance")
    protected = ProtectedSet(("infra/**", "**/migrations/**"), UNIT, OWN)
    (repo / LEDGER_DIR).mkdir(parents=True)
    (repo / OWN).write_text("{}\n")  # the run's ledger
    (repo / f"{UNIT}/tasks.md").write_text("- [x] 1.1 a\n")  # the harness's marker, not yet committed
    (repo / "src/app.py").write_text("x = 2\n")  # the step's own change
    before = snapshot_protected(repo, protected)
    # the gate
    (repo / "src/pkg/CLAUDE.md").write_text("gate\n")
    (repo / "src/lib").mkdir()
    (repo / "src/lib/AGENTS.md").write_text("gate\n")
    (repo / "src/lib/Claude.local.md").write_text("gate\n")
    (repo / "app/migrations").mkdir(parents=True)
    (repo / "app/migrations/0002.py").write_text("gate\n")
    (repo / "infra/main.tf").write_text("gate\n")
    (repo / "ignored").mkdir()
    (repo / "ignored/CLAUDE.md").write_text("ignored at HEAD\n")
    assert restore_protected(repo, protected, before) == []
    out = revert_unsnapshotted(git_for(repo), protected)
    assert sorted((v.path, v.action) for v in out) == [
        ("app/migrations/0002.py", "removed"), ("infra/main.tf", "restored"), ("src/lib/AGENTS.md", "removed"),
        ("src/lib/Claude.local.md", "removed"), ("src/pkg/CLAUDE.md", "restored"),
    ]  # fmt: skip
    assert (repo / "src/pkg/CLAUDE.md").read_text() == "human\n" and (repo / "infra/main.tf").read_text() == "t\n"
    assert not (repo / "src/lib").exists() and not (repo / "app").exists()
    assert (repo / f"{UNIT}/tasks.md").read_text() == "- [x] 1.1 a\n" and (repo / OWN).read_text() == "{}\n"
    assert (repo / "src/app.py").read_text() == "x = 2\n" and (repo / "ignored/CLAUDE.md").exists()
    assert revert_unsnapshotted(git_for(repo), protected) == []  # nothing left


@pytest.mark.parametrize(
    "path",
    ["openspec/changes/add-vat/.l4/ledger/r-x.jsonl", ".kiro/specs/other/.l4/evidence/round-1/verdict.json",
     "openspec/changes/archive/2026-10-01-old/.l4/ledger/r-y.jsonl", ".l4/config.yml"],
)  # fmt: skip
def test_every_l4_directory_is_protected_at_any_depth(path):
    """Another unit's ledger folds into that unit's state once this branch is merged (L4-STA-001)."""
    assert ProtectedSet(unit_dir=UNIT, run_ledger=OWN).match(path), path


def test_the_runs_own_ledger_and_lookalikes_of_l4_stay_unprotected():
    protected = ProtectedSet(unit_dir=UNIT, run_ledger=OWN)
    assert protected.match(OWN) is None
    assert all(protected.match(p) is None for p in (".l4-out/junit.xml", "src/.l4rc", "docs/l4/notes.md"))


@pytest.mark.parametrize(
    "path",
    ["openspec/specs/greeting/spec.md", "openspec/changes/other/specs/greeting/spec.md",
     "openspec/changes/archive/2026-01-01-x/proposal.md", "openspec/config.yaml",
     ".kiro/specs/feature-x/requirements.md", ".kiro/specs/feature-x/tasks.md"],
)  # fmt: skip
def test_the_spec_root_is_contract_protected_for_agent_steps(path):
    """HB-3: a criterion copied into the archived specs or another change would leave the audit pool (pass-to-pass)."""
    assert is_protected(path), path
    assert ProtectedSet(unit_dir=UNIT, run_ledger=OWN).match(path)


def test_the_spec_root_protection_keeps_the_runs_own_ledger_exception():
    protected = ProtectedSet(unit_dir=UNIT, run_ledger=OWN)
    assert protected.match(OWN) is None  # the ledger is the harness's to append to during the step
    assert protected.match(f"{LEDGER_DIR}/r-20261003T1312Z-0000.jsonl")  # another run's ledger is not
    assert {"openspec", ".kiro/specs"} <= set(protected.anchored_roots())


def test_a_criterion_copied_into_the_archived_specs_is_reverted_with_a_guard_violation(worktree, git_for, raw):
    repo, base = worktree()
    spec = repo / "openspec/specs/greeting/spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("## Requirements\n### Requirement: Greet\n#### Scenario: Named\n- **WHEN** x\n")  # untracked
    sibling = repo / "openspec/changes/other/proposal.md"
    sibling.parent.mkdir(parents=True)
    sibling.write_text("sibling\n")
    kiro = repo / ".kiro/specs/x/requirements.md"
    kiro.parent.mkdir(parents=True)
    kiro.write_text("1. WHEN\n")
    sink = Sink()
    out = revert_protected(git_for(repo), ProtectedSet((), UNIT, OWN), base, events=sink)
    assert not (repo / "openspec/specs").exists() and not (repo / "openspec/changes/other").exists()
    assert not (repo / ".kiro").exists()
    assert sorted((v.path, v.action) for v in out) == [
        (".kiro/specs/x/requirements.md", "removed"), ("openspec/changes/other/proposal.md", "removed"),
        ("openspec/specs/greeting/spec.md", "removed"),
    ]
    assert {e[0] for e in sink.events} == {"guard.violation"} and len(sink.events) == 3


# --- per-commit attribution (sandbox-security 2.10, L4-SEC-004) ----------------------------------------------------

BOT = ("-c", "user.name=l4-bot", "-c", "user.email=l4-bot@users.noreply.invalid")


def _commit(raw, repo, files: dict[str, str], message: str, *, bot: bool) -> str:
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    raw(repo, "add", "-A")
    identity = BOT if bot else ("-c", "user.name=Ann", "-c", "user.email=ann@example.invalid")
    trailers = ["--trailer=L4-Run: r-1"] if bot else []
    raw(repo, *identity, "commit", "-q", "-m", message, *trailers)
    return raw(repo, "rev-parse", "HEAD").strip()


def test_human_ci_edit_is_listed_not_reverted(make_repo, raw, git_for):
    """A person's commit on the unit branch that changes a protected path is allowed and listed; one a harness commit
    also touched stays out of the list (the caller treats it as a blocker)."""
    from l4.security.protected import HumanChange, protected_changes_by_human

    repo = make_repo()
    base = raw(repo, "rev-parse", "HEAD").strip()
    _commit(raw, repo, {".github/workflows/ci.yml": "on: push\n", "src/a.py": "a\n"}, "harness work", bot=True)
    human = _commit(raw, repo, {".gitlab-ci.yml": "test:\n  script: pytest\n"}, "fix the CI job", bot=False)
    both = _commit(raw, repo, {".github/workflows/ci.yml": "on: [push, pull_request]\n"}, "tweak", bot=False)
    head = raw(repo, "rev-parse", "HEAD").strip()
    paths = [".gitlab-ci.yml", ".github/workflows/ci.yml", "infra/none.tf"]
    found = protected_changes_by_human(git_for(repo), base, head, paths)
    assert [c.path for c in found] == [".gitlab-ci.yml"]  # the workflow file was also written by the harness
    assert isinstance(found[0], HumanChange) and [(c.sha, c.author) for c in found[0].commits] == [(human, "Ann")]
    assert both not in [c.sha for h in found for c in h.commits]
    assert protected_changes_by_human(git_for(repo), base, head, []) == []
    # nothing was put back: the path is still the person's
    assert (repo / ".gitlab-ci.yml").read_text().startswith("test:")


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("app/migrations/0001_initial.py", "**/migrations/**"),
        ("migrations", "**/migrations/**"),
        ("infra/compose.yml", "infra/**"),
        ("src/infra/compose.yml", None),
        ("app/models.py", None),
        (".github/workflows/ci.yml", None),  # only the globs passed are consulted: the contract list is not
    ],
)
def test_forbidden_rule_names_the_glob_of_the_list_that_matches(path, expected):
    assert forbidden_rule(path, ("**/migrations/**", "infra/**")) == expected


def test_forbidden_rule_walks_the_parent_prefixes_like_match():
    globs = ("db/**", "db/archive/*.sql")
    assert forbidden_rule("db/archive/a.sql", globs) == "db/**"  # the shorter prefix is tried first
    assert forbidden_rule("db/archive/a.sql", ("db/archive/*.sql",)) == "db/archive/*.sql"
    assert forbidden_rule("db/archive/a.sql/extra", ("db/archive/*.sql",)) == "db/archive/*.sql"  # a parent matches
    assert forbidden_rule("x", ()) is None


def test_match_still_reports_the_forbidden_glob_it_used_to():
    protected = ProtectedSet(odd_forbidden=("**/migrations/**", "infra/**"))
    assert protected.match("app/migrations/0001_initial.py") == forbidden_rule(
        "app/migrations/0001_initial.py", protected.odd_forbidden
    )
