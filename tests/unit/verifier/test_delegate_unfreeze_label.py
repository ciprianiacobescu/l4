"""A delegate's or an agent's unfreeze is never listed as a person's (delegate-answers review 2, N2; L4-DLG-014,
L4-QMD-009, SCN-DLG-55, D15)."""

from l4.verifier.integrity import check_freeze, run_integrity

from .test_integrity import _unfrozen_history


def test_a_delegates_unfreeze_is_listed_as_delegate_override(tmp_path, git_environ):
    repo, base, green = _unfrozen_history(
        tmp_path, git_environ, reason="delegate_answer", by="delegate", profile="delegate-opus", model="claude-opus-5-5"
    )
    out = check_freeze(repo.context(base, green))
    assert out.findings == []
    assert out.unfrozen == ["tests/test_a.py (task 1.1, unfrozen by Q-002 (delegate_override, claude-opus-5-5))"]
    assert "human" not in out.unfrozen[0] and "human" not in out.note
    assert "unfrozen by a delegate" in out.note
    assert run_integrity(repo.context(base, green)).unfrozen == out.unfrozen


def test_an_agents_unfreeze_is_listed_as_the_agents(tmp_path, git_environ):
    repo, base, green = _unfrozen_history(tmp_path, git_environ, reason="human_answer", by="agent")
    out = check_freeze(repo.context(base, green))
    assert out.unfrozen == ["tests/test_a.py (task 1.1, unfrozen by Q-002 (agent))"]
    assert "human" not in out.note


def test_a_persons_unfreeze_stays_a_persons(tmp_path, git_environ):
    for extra in ({}, {"by": "human"}):  # an old event has no `by`
        folder = tmp_path / str(len(extra))
        folder.mkdir()
        repo, base, green = _unfrozen_history(folder, git_environ, **extra)
        out = check_freeze(repo.context(base, green))
        assert out.unfrozen == ["tests/test_a.py (task 1.1, unfrozen by Q-002 (human))"]
        assert "(+1 unfrozen by human answers)" in out.note
