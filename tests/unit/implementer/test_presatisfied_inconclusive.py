"""L4-IMP-002, L4-IMP-060 (SCN-IMP-300, 308, 309): the pre-satisfied confirmation is confirmed, refuted or inconclusive.
A run that collected nothing is not "its tests still pass"; a fixture assertion counts in the unit's own files only."""

from l4.implementer import discrimination
from l4.implementer.discrimination import confirm_pre_satisfied
from l4.implementer.tdd import run_setup

from .conftest import Bench

C1, C2, C3 = "C-aaaaaaaa", "C-bbbbbbbb", "C-cccccccc"
CONFIG = 'def load() -> dict:\n    return {"rate": 2}\n\n\nRATE = load()["rate"]\n'
TEST_CONFIG = "from pytdd.config import RATE\n\n\ndef test_rate():\n    assert RATE == 2\n"
TELEMETRY = """\
def init(out: list) -> bool:
    out.append("on")
    return True


def span_names(out: list) -> list[str]:
    return [f"span:{e}" for e in out]
"""
FIXTURE = "@pytest.fixture\ndef exporter():\n    out = []\n    assert telemetry.init(out) is True\n    return out\n"
SPANS_HEAD = "import pytest\n\nfrom pytdd import telemetry\nfrom pytdd.telemetry import span_names\n\n\n"
SPAN_TESTS = "".join(
    f'\n\n@pytest.mark.l4("{c}")\ndef test_{n}(exporter):\n    assert span_names(exporter) == ["span:on"]\n'
    for c, n in ((C1, "one"), (C2, "two"), (C3, "three"))
)
CANDIDATES = {
    C1: ["tests.test_spans::test_one"],
    C2: ["tests.test_spans::test_two"],
    C3: ["tests.test_spans::test_three"],
}


def real_report(bench: Bench):
    gate = bench.wb.run_gate("test", bench.wb.cfg.gates.test.command, reports=bench.wb.cfg.gates.test.reports)
    assert gate.report is not None
    return gate.report


def test_scn_imp_300_a_run_that_collects_nothing_is_inconclusive_not_still_passing(make_bench, monkeypatch):
    monkeypatch.setattr(discrimination, "MAX_KEEP_RERUNS", 0)
    bench: Bench = make_bench([])
    (bench.wb.worktree / "src/pytdd/config.py").write_text(CONFIG)
    (bench.wb.worktree / "tests/test_config.py").write_text(TEST_CONFIG)
    run_setup(bench.wb)
    real = real_report(bench)
    got = confirm_pre_satisfied(bench.wb, {C1: ["tests.test_config::test_rate"]}, real=real)
    assert set(got.inconclusive) == {C1} and "KeyError" in got.inconclusive[C1]
    assert got.unconfirmed == {} and got.confirmed == {}
    assert got.message.startswith(f"inconclusive: {C1} (")
    assert "still pass" not in got.message


def test_scn_imp_308_a_fixture_assertion_in_the_units_own_test_file_counts(make_bench):
    bench: Bench = make_bench([])
    (bench.wb.worktree / "src/pytdd/telemetry.py").write_text(TELEMETRY)
    (bench.wb.worktree / "tests/test_spans.py").write_text(SPANS_HEAD + FIXTURE + SPAN_TESTS)
    run_setup(bench.wb)
    real = real_report(bench)
    got = confirm_pre_satisfied(bench.wb, CANDIDATES, real=real)
    assert set(got.confirmed) == {C1, C2, C3}, got.message
    assert got.reruns == 0 and got.inconclusive == {} and got.unconfirmed == {}


def test_scn_imp_309_a_fixture_assertion_in_a_pre_existing_conftest_does_not_count(make_bench, tdd_repo, raw):
    root = tdd_repo.repo
    (root / "src/pytdd/telemetry.py").write_text(TELEMETRY)
    (root / "tests/conftest.py").write_text("import pytest\n\nfrom pytdd import telemetry\n\n\n" + FIXTURE)
    raw(root, "add", "-A")
    raw(root, "commit", "-q", "-m", "telemetry and its fixture")
    raw(root, "push", "-q", "origin", "main")
    raw(root, "fetch", "-q", "origin")
    bench: Bench = make_bench([])
    (bench.wb.worktree / "tests/test_spans.py").write_text(SPANS_HEAD + SPAN_TESTS)
    run_setup(bench.wb)
    real = real_report(bench)
    got = confirm_pre_satisfied(bench.wb, CANDIDATES, real=real)
    assert set(got.confirmed) == {C1, C2, C3}, got.message
    assert got.reruns == 1 and got.kept == {"src/pytdd/telemetry.py": ("init",)}
    assert [(k["rerun"], k["cause"]) for k in bench.events("zero.kept")] == [(1, "setup")]


def test_the_refuted_message_is_the_same_text_as_before(make_bench):
    bench: Bench = make_bench([])
    (bench.wb.worktree / "tests/test_existing.py").write_text(
        "from pytdd import total\n\n\ndef test_nothing():\n    assert total([]) == total([])\n"
    )
    run_setup(bench.wb)
    got = confirm_pre_satisfied(bench.wb, {C1: ["tests.test_existing::test_nothing"]}, real=real_report(bench))
    assert got.message == (
        f"not discriminating: {C1} (its tests still pass, or fail by an error rather than an assertion, "
        "when the functions they use answer the zero value)"
    )
