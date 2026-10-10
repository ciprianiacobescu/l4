"""Stage A end to end on the py_multi fixture: real git, real pytest with the `l4_cov` plugin, four seeded heads."""

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from l4.config.schema import L4Config
from l4.evidence.collect import collect_evidence, coverage_sources
from l4.gates.coverage import cov_env
from l4.gates.junit import parse_junit
from l4.specs.base import Framework, UnitRef
from l4.vcs.git import Git
from l4.vcs.trailers import CommitTrailers

from ..unit.evidence._multi import RUN_ID, UnitHistory, build_repo

CART_RED = {"tests.test_cart::test_total_with_discount_and_tax", "tests.test_cart::test_total_without_code"}


@dataclass
class Bench:
    git: Git
    cfg: L4Config
    worktree: Path


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Git, UnitHistory]:
    repo = tmp_path_factory.mktemp("flow") / "repo"
    git, units = build_repo(repo)
    return repo, git, units[4]  # cart-totals: the spec names `src/shop/cart.py`


def commit(git: Git, message: str) -> str:
    git.run("add", "-A")
    return git.commit(message, CommitTrailers("openspec:cart-totals", RUN_ID, 1, "implementing", step="9/seed/1"))


def evidence(built, tmp_path: Path, head: str, scope_check: str = "warn", mode: str = "warn"):
    repo, git, unit = built
    git.run("checkout", "--quiet", "--detach", head)
    cfg = L4Config.model_validate(
        {"sdd": {"scope_check": scope_check}, "verifier": {"evidence": {"diff_coverage": {"mode": mode}}}}
    )
    out = tmp_path / "cov"
    junit = tmp_path / "junit.xml"
    env = {k: v for k, v in os.environ.items() if k not in ("PYTEST_ADDOPTS", "PYTHONPATH")}
    env.update(cov_env(out, coverage_sources(git, unit.base, head, cfg, unit.spec_dir)))
    subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={junit}"],
        cwd=repo, env=env, capture_output=True, text=True,
    )  # fmt: skip
    ref = UnitRef(Framework.OPENSPEC, "cart-totals", repo / unit.spec_dir)
    return collect_evidence(
        Bench(git, cfg, repo), unit.base, head, parse_junit(junit), out, ref, new_tests=CART_RED,
        gate_passed=True,
    )  # fmt: skip


def seed(built, name: str, edits: dict[str, str | None]) -> str:
    repo, git, unit = built
    git.run("checkout", "--quiet", "--detach", unit.head)
    for rel, text in edits.items():
        if text is None:
            (repo / rel).unlink()
        else:
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_text(text)
    return commit(git, name)


def test_four_seeded_heads_give_expected_labels_findings_and_holds(built, tmp_path: Path):
    repo, git, unit = built

    clean = evidence(built, tmp_path / "clean", unit.head)
    assert set(clean.labels["files"].values()) == {"relevant"} and set(clean.labels["files"]) == {
        "src/shop/cart.py", "tests/test_cart.py"
    }  # fmt: skip
    assert clean.labels["functions"] == {"src/shop/cart.py::cart_total": True, "src/shop/cart.py::<module>": True}
    assert clean.labels["tests_ok"] is True
    assert clean.findings == [] and clean.holds == []

    stock = (repo / "src/inventory/stock.py").read_text()
    other = seed(built, "edit another module", {
        "src/inventory/stock.py": stock.replace("self._levels.get(sku, 0) + qty", "self.on_hand(sku) + qty")
    })  # fmt: skip
    ev = evidence(built, tmp_path / "other", other)
    assert ev.labels["files"]["src/inventory/stock.py"] == "out_of_scope"
    assert ev.labels["functions"]["src/inventory/stock.py::Stock.add"] is True  # covered, yet out of scope
    assert ev.holds == ["scope: `src/inventory/stock.py` changes module `inventory`, which the spec does not name"]
    assert ev.findings == [] and ev.labels["tests_ok"] is True
    failing = evidence(built, tmp_path / "other-fail", other, scope_check="fail")
    assert [f.title for f in failing.findings] == ["change outside the feature: src/inventory/stock.py"]
    assert failing.holds == []

    deleted = seed(built, "delete the covering test", {"tests/test_cart.py": None})
    ev = evidence(built, tmp_path / "deleted", deleted)
    assert ev.labels["functions"]["src/shop/cart.py::cart_total"] is False
    assert ev.coverage and ev.coverage.percent < 80
    assert ev.holds == [
        "diff coverage: changed code not run by any test: `src/shop/cart.py::<module>`, `src/shop/cart.py::cart_total`"
    ]
    assert [f.title for f in ev.findings] == ["new tests did not run"]  # the red tests are gone from the report

    cart = (repo / "src/shop/cart.py").read_text()
    broken = seed(built, "break the code", {"src/shop/cart.py": cart.replace("add_tax(subtotal, rate_bp)", "1")})
    ev = evidence(built, tmp_path / "broken", broken)
    assert ev.labels["tests_ok"] is False
    assert [f.title for f in ev.findings] == ["new tests failed"] and ev.findings[0].severity.value == "blocker"
    assert ev.labels["functions"]["src/shop/cart.py::cart_total"] is True  # it ran; it was just wrong


def test_coverage_not_measured_is_a_hold_only_in_fail_mode(built, tmp_path: Path):
    repo, git, unit = built
    git.run("checkout", "--quiet", "--detach", unit.head)
    cfg = L4Config.model_validate({"verifier": {"evidence": {"diff_coverage": {"mode": "fail"}}}})
    ref = UnitRef(Framework.OPENSPEC, "cart-totals", repo / unit.spec_dir)
    ev = collect_evidence(
        Bench(git, cfg, repo), unit.base, unit.head, None, tmp_path / "nothing", ref, gate_passed=True
    )
    assert ev.holds == ["diff coverage: not measured: the coverage plugin wrote no status"]
    assert ev.ran is None and ev.labels["tests_ok"] is None


HELPER = "def report(rows):\n" + "".join(f"    row{i} = rows[{i}]\n" for i in range(30)) + "    return rows\n"


@pytest.mark.parametrize("mode", ["warn", "fail"])
def test_changed_file_in_a_namespace_subpackage_is_not_silently_unmeasured(built, tmp_path: Path, mode: str):
    head = seed(built, f"uncovered helper {mode}", {"src/shop/extra/helpers.py": HELPER})
    ev = evidence(built, tmp_path / "ns", head, mode=mode)
    assert ev.coverage and ev.coverage.percent < 80
    texts = [*ev.holds, *(f.detail for f in ev.findings)]
    assert any("src/shop/extra/helpers.py::report" in t for t in texts), texts


def test_unmeasured_function_counts_in_fail_mode_even_when_the_file_is_missing_from_the_report(tmp_path: Path):
    from l4.evidence.diffcov import ChangedFunction, check_diff_coverage, diff_coverage

    funcs = [ChangedFunction("src/x/y.py", "f", (1, 9), frozenset(range(2, 10)))]
    dc = diff_coverage(funcs, {"files": {}}, {"status": "ok"})
    assert dc.percent == 0.0
    cfg = L4Config.model_validate({"verifier": {"evidence": {"diff_coverage": {"mode": "fail"}}}})
    assert check_diff_coverage(dc, cfg).findings


def test_a_newline_in_a_path_cannot_rewrite_the_coverage_rc(built, tmp_path: Path):
    evil = "src/a\nomit = */m.py/m.py"
    head = seed(built, "hostile path", {evil: "def g():\n    return 1\n"})
    ev = evidence(built, tmp_path / "evil", head)
    assert ev.coverage and ev.coverage.status == "ok"  # the rc was not corrupted
    assert any(h.startswith("unsafe path name:") for h in ev.holds), ev.holds
    assert not any("\n" in h or "\r" in h for h in ev.holds)
    assert ev.labels["functions"]["src/shop/cart.py::cart_total"] is True


def test_declared_scope_is_read_at_base_not_at_head(built, tmp_path: Path):
    repo, git, unit = built
    stock = (repo / "src/inventory/stock.py").read_text()
    stock = stock.replace("self._levels.get(sku, 0) + qty", "self.on_hand(sku) + qty")
    tasks = repo / unit.spec_dir / "tasks.md"
    head = seed(built, "widen scope in tasks.md", {
        "src/inventory/stock.py": stock,
        f"{unit.spec_dir}/tasks.md": tasks.read_text() + "\n- [x] 1.2 Tidy `src/inventory/stock.py`\n",
    })  # fmt: skip
    ev = evidence(built, tmp_path / "widen", head)
    assert ev.labels["files"]["src/inventory/stock.py"] == "out_of_scope"


def test_leftover_coverage_never_passes_for_this_runs(built, tmp_path: Path):
    """Round 2 adds an untested function and its gate drops the plugin environment (tox, nox, `env -i`)."""
    repo, git, unit = built
    cfg = L4Config.model_validate({"verifier": {"evidence": {"diff_coverage": {"mode": "fail"}}}})
    round1 = tmp_path / "r1"
    assert evidence(built, round1, unit.head, mode="fail").holds == []
    cart = (repo / "src/shop/cart.py").read_text()
    head = seed(
        built, "untested refund", {"src/shop/cart.py": cart + "\n\ndef refund_total(a):\n    b = a\n    return -b\n"}
    )
    cov = round1 / "cov"
    assert (cov / "status.json").exists()  # round 1 left a perfectly consistent status and coverage file behind
    junit = tmp_path / "junit2.xml"
    env = {k: v for k, v in os.environ.items() if k not in ("PYTEST_ADDOPTS", "PYTHONPATH")}
    subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={junit}"],
        cwd=repo, env=env, capture_output=True, text=True,
    )  # fmt: skip
    ref = UnitRef(Framework.OPENSPEC, "cart-totals", repo / unit.spec_dir)

    def collect(**kw):
        return collect_evidence(
            Bench(git, cfg, repo), unit.base, head, parse_junit(junit), cov, ref, new_tests=CART_RED,
            gate_passed=True, **kw,
        )  # fmt: skip

    stale = collect(cov_nonce="the-nonce-of-round-2")
    assert stale.coverage is not None and stale.coverage.status == "not_run"
    assert stale.holds and "coverage was not written by this run" in stale.holds[0]
    cov_env(cov, coverage_sources(git, unit.base, head, cfg, unit.spec_dir))  # round 2 prepares the directory
    assert not (cov / "status.json").exists() and not (cov / "coverage.json").exists()
    assert "wrote no status" in collect().holds[0]


def test_evidence_json_carries_the_holds_and_item_keys_for_a_later_verdict(built, tmp_path: Path):
    from l4.evidence.collect import scope_evidence
    from l4.s1.items import item_keys_by_subject
    from l4.verifier.verdicts import hold_id

    repo, git, unit = built
    stock = (repo / "src/inventory/stock.py").read_text()
    head = seed(built, "edit another module again", {"src/inventory/stock.py": stock + "\n# touched\n"})
    ev = evidence(built, tmp_path / "holds", head)
    (hold,) = ev.hold_records
    text = "scope: `src/inventory/stock.py` changes module `inventory`, which the spec does not name"
    assert (hold.id, hold.text, hold.kind, hold.subjects) == (hold_id(text), text, "scope", ("src/inventory/stock.py",))
    assert ev.holds == [hold.text]
    ev.item_keys = item_keys_by_subject([])  # filled by the caller that builds the S1 items
    ev.item_keys["l4/file-relevant@1|src/inventory/stock.py"] = "k" * 32
    doc = ev.to_json()
    assert doc["holds"] == [{"id": hold.id, "text": text, "kind": "scope", "subjects": ["src/inventory/stock.py"]}]
    assert doc["items"] == {"l4/file-relevant@1|src/inventory/stock.py": "k" * 32}
    assert "## Evidence" in ev.section()[0]
    # step 1 of the ladder needs no test run: the same hold comes out of the scope half alone
    ref = UnitRef(Framework.OPENSPEC, "cart-totals", repo / unit.spec_dir)
    cfg = L4Config.model_validate({})
    git.run("checkout", "--quiet", "--detach", head)
    step1 = scope_evidence(Bench(git, cfg, repo), unit.base, head, ref)
    assert [h.id for h in step1.holds] == [hold.id]


def test_a_coverage_hold_names_the_functions_it_is_about(built, tmp_path: Path):
    repo, git, unit = built
    deleted = seed(built, "delete the covering test again", {"tests/test_cart.py": None})
    ev = evidence(built, tmp_path / "cov-hold", deleted)
    (hold,) = ev.hold_records
    assert hold.kind == "coverage" and hold.subjects == ("src/shop/cart.py::<module>", "src/shop/cart.py::cart_total")
