"""HB-3: the verifier's pass-to-pass baseline is read from git at the unit's base commit, never from the worktree."""

from l4.specs.criteria import base_criteria, base_criteria_at

SPEC = """# greeting Specification

## Purpose
Greets.

## Requirements

### Requirement: Greet by name
The system SHALL greet.

#### Scenario: Named greeting
- **WHEN** the user runs `greet Ada`
- **THEN** it prints Hello, Ada
"""
NEW = SPEC.replace("Named greeting", "Planted by the agent")


def test_the_baseline_is_the_base_commit_not_the_worktree(make_repo, raw, git_for):
    repo = make_repo()
    (repo / "openspec/specs/greeting").mkdir(parents=True)
    (repo / "openspec/specs/greeting/spec.md").write_text(SPEC)
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "specs")
    base = raw(repo, "rev-parse", "HEAD").strip()
    (repo / "openspec/specs/farewell").mkdir()
    (repo / "openspec/specs/farewell/spec.md").write_text(NEW)  # a criterion that exists only at head
    (repo / "openspec/specs/greeting/spec.md").write_text(SPEC + "\n#### Scenario: Extra\n- **WHEN** x\n")
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "agent copies its delta into the main specs")
    at_base = base_criteria_at(git_for(repo), base)
    assert [(c.capability, c.scenario) for c in at_base] == [("greeting", "Named greeting")]
    from_worktree = base_criteria(repo / "openspec" / "specs")  # what the verifier read before: head
    assert {c.scenario for c in from_worktree} == {"Named greeting", "Planted by the agent", "Extra"}
    only_head = {c.id for c in from_worktree} - {c.id for c in at_base}
    assert len(only_head) == 2
    assert at_base[0].source_path == "openspec/specs/greeting/spec.md" and at_base[0].text


def test_a_missing_specs_dir_or_an_unknown_rev_is_an_empty_baseline(make_repo, git_for, raw):
    repo = make_repo()
    head = raw(repo, "rev-parse", "HEAD").strip()
    assert base_criteria_at(git_for(repo), head) == []
    assert base_criteria_at(git_for(repo), "0" * 40) == []


def test_a_symlinked_capability_or_spec_file_is_skipped(make_repo, raw, git_for):
    repo = make_repo()
    (repo / "openspec/specs/greeting").mkdir(parents=True)
    (repo / "openspec/specs/greeting/spec.md").write_text(SPEC)
    (repo / "openspec/specs/linked").symlink_to("greeting")  # a link: not the commit's own content
    (repo / "openspec/specs/odd").mkdir()
    (repo / "openspec/specs/odd/spec.md").symlink_to("../greeting/spec.md")
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "specs")
    assert [c.capability for c in base_criteria_at(git_for(repo), "HEAD")] == ["greeting"]
