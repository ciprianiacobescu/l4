"""Live M1.6 step 4: `show-item-count` and `show-subtotal` added `e2e/test_l4_c_*.py`, which the canary's `tests/`
command never runs, so `check_tests_ran` said "new test file ran no test", the untouched baseline was not clean and
every run of the unit was `baseline_failed`. The canary skips the e2e part with a recorded reason; the unit's other
items still count (m1.x fix F7)."""

import sys
from pathlib import Path

from l4.config.schema import L4Config
from l4.redact import Redactor
from l4.s1 import canary as c
from l4.vcs.trailers import CommitTrailers

from ..evidence._multi import RUN_ID, build_repo

E2E_TEST = "import pytest\n\n\ndef test_cart_page_shows_the_total():\n    pytest.fail('needs a browser and a server')\n"


def e2e_repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    git, _ = build_repo(path, units=5)  # cart-totals is the last unit
    (path / "e2e").mkdir()
    (path / "e2e" / "test_l4_c_0123abcd.py").write_text(E2E_TEST, encoding="utf-8")
    git.run("add", "-A")
    git.commit(
        "e2e: cart-totals", CommitTrailers("openspec:cart-totals", RUN_ID, 1, "implementing", task="1.2", tdd="green")
    )
    return path


def make(path: Path, tmp_path: Path, *, command: str | None = None) -> c.Canary:
    command = command or f"{sys.executable} -m pytest -q -p no:cacheprovider tests --junitxml=.l4-out/junit.xml"
    canary = c.Canary(
        path, cfg=L4Config(), seed=1, work_dir=tmp_path / "work", redactor=Redactor({}), test_command=command
    )
    canary.units = c.find_source_units(canary.git)
    return canary


def test_a_unit_with_e2e_tests_still_gives_its_other_items(tmp_path: Path):
    canary = make(e2e_repo(tmp_path), tmp_path)
    unit = next(u for u in canary.units if u.name == "cart-totals")
    result = canary.run(unit, "none", 0)
    assert result.dropped == "" and result.items, result.dropped
    assert canary.counts["run:none:ok"] == 1


def test_the_skipped_e2e_part_is_recorded_with_its_reason(tmp_path: Path):
    canary = make(e2e_repo(tmp_path), tmp_path)
    unit = next(u for u in canary.units if u.name == "cart-totals")
    canary.run(unit, "none", 0)
    assert canary.skipped_e2e[unit.id] == ["e2e/test_l4_c_0123abcd.py"]
    assert "e2e" in canary.skip_reason and "not run" in canary.skip_reason


def test_a_unit_without_e2e_tests_records_nothing(tmp_path: Path):
    canary = make(e2e_repo(tmp_path), tmp_path)
    unit = next(u for u in canary.units if u.name == "reserve-stock")
    assert canary.run(unit, "none", 0).items
    assert canary.skipped_e2e == {}


def test_generate_reports_the_skip_in_its_counts_and_its_progress_lines(tmp_path: Path):
    canary = make(e2e_repo(tmp_path), tmp_path)
    lines: list[str] = []
    done = c.generate([canary], c.Quota(target=1), max_variants=1, mutations=("none",), on_run=lines.append)
    assert done.counts[f"e2e_skipped:{canary.project}:cart-totals"] == 1
    assert not any(k.startswith("e2e_skipped:") and "reserve-stock" in k for k in done.counts)
    assert sum("e2e test files were not run" in line and "cart-totals" in line for line in lines) == 1
    assert done.counts["none:baseline_failed"] == 0


def test_no_mutation_edits_an_e2e_test_file_the_canary_does_not_run(tmp_path: Path, monkeypatch):
    """Review of F7: a test mutation (`break_test`, `add_passing_test`) that lands on an e2e file changes nothing the
    canary runs, so the run is dropped as `checker_disagreement` (break) or repeats the untouched state (add): false
    telemetry about the checker. The e2e files are not mutation targets."""
    path = e2e_repo(tmp_path)
    e2e = path / "e2e" / "test_l4_c_0123abcd.py"
    e2e.write_text("def test_count():\n    assert len('ab') == 2\n\n\ndef test_more():\n    assert 3 == 3\n")
    git = c.Git(path)
    git.run("add", "-A")
    git.commit(
        "e2e: flip-able", CommitTrailers("openspec:cart-totals", RUN_ID, 1, "implementing", task="1.2", tdd="green")
    )
    canary = make(path, tmp_path)
    unit = next(u for u in canary.units if u.name == "cart-totals")
    edited: list[str] = []
    apply = canary._apply

    def recording(mutation, ctx):
        applied = apply(mutation, ctx)
        edited.extend(applied.edits if applied is not None else ())
        return applied

    monkeypatch.setattr(canary, "_apply", recording)
    results = [canary.run(unit, m, v) for m in ("break_test", "add_passing_test") for v in range(1, 5)]
    assert edited and not [p for p in edited if p.startswith("e2e/")], edited
    assert not [r for r in results if r.dropped == "checker_disagreement"]
