"""named-tests-trace 2.1 (L4-IMP-093, L4-VER-009): red and the verifier read "unchanged on the base" through the same
two helpers, `unchanged_ids` and `spec_baseline`."""

from types import SimpleNamespace

from l4.specs.base import Criterion, Framework
from l4.specs.criteria import spec_baseline, unchanged_ids

SPEC = """# registry Specification

## Purpose
Lists tools.

## Requirements

### Requirement: Registry
The system SHALL list tools.

#### Scenario: lists tools
- **WHEN** the user runs `tools`
- **THEN** it prints every tool
"""


def criterion(cid: str, text: str, framework: Framework = Framework.OPENSPEC) -> Criterion:
    return Criterion(cid, f"cap > Req > {cid}", framework, "cap", "Req", cid, text, "spec.md", 1)


A, B, C = "C-aaaaaaaa", "C-bbbbbbbb", "C-cccccccc"


def test_unchanged_ids_holds_the_ids_with_the_same_text_and_no_others():
    base = [criterion(A, "WHEN x\nTHEN y"), criterion(B, "WHEN x\nTHEN y")]
    now = [criterion(A, "WHEN x\nTHEN y"), criterion(B, "WHEN x\nTHEN z"), criterion(C, "WHEN x\nTHEN y")]
    assert unchanged_ids(now, base) == {A}  # B has another body under the same id, C is not in the base


def test_unchanged_ids_reads_re_wrapped_text_as_the_same():
    base = [criterion(A, "- **WHEN** x\n- **THEN** it prints every tool")]
    now = [criterion(A, "- **WHEN**   x\n- **THEN** it prints\n  every tool\n")]
    assert unchanged_ids(now, base) == {A}


def test_unchanged_ids_of_nothing_is_empty():
    assert unchanged_ids([], [criterion(A, "x")]) == frozenset()
    assert unchanged_ids([criterion(A, "x")], []) == frozenset()


def test_an_openspec_baseline_is_the_archived_specs_at_the_rev(make_repo, raw, git_for):
    repo = make_repo()
    (repo / "openspec/specs/registry").mkdir(parents=True)
    (repo / "openspec/specs/registry/spec.md").write_text(SPEC)
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "specs")
    rev = raw(repo, "rev-parse", "HEAD").strip()
    (repo / "openspec/specs/registry/spec.md").write_text(SPEC.replace("every tool", "nothing"))  # head differs
    git = git_for(repo)
    found = spec_baseline(git, Framework.OPENSPEC, SimpleNamespace(), rev)
    assert [(c.capability, c.scenario) for c in found] == [("registry", "lists tools")]
    assert "every tool" in found[0].text
    assert spec_baseline(git, Framework.OPENSPEC, SimpleNamespace(), None) == []


def test_a_kiro_follow_up_baseline_is_the_merged_parent():
    parent = [criterion(A, "x", Framework.KIRO)]
    provider = SimpleNamespace(merged_parent_criteria=lambda: parent)
    assert spec_baseline(None, Framework.KIRO, provider, "abc123") == parent  # type: ignore[arg-type]


def test_a_kiro_unit_that_is_not_a_follow_up_has_no_baseline():
    assert spec_baseline(None, Framework.KIRO, SimpleNamespace(), "abc123") == []  # type: ignore[arg-type]
    plain = SimpleNamespace(merged_parent_criteria=lambda: [])
    assert spec_baseline(None, Framework.KIRO, plain, "abc123") == []  # type: ignore[arg-type]
