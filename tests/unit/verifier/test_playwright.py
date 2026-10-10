from pathlib import Path

import pytest

from l4.config.schema import L4Config
from l4.exitcodes import ExitCode, L4Exit
from l4.gates.e2e import run_e2e
from l4.gates.junit import TestCase, TestReport
from l4.specs.base import Criterion, Framework
from l4.verifier.playwright import (
    artifact_dir,
    base_checkout,
    failure_artifacts,
    playwright_enabled,
    ui_facing_criteria,
    ui_files,
    unit_changed_files,
)

from .._web_bench import stage_base_and_head, web_bench
from ..implementer.conftest import make_bench  # noqa: F401

UI = ("web/**", "frontend/**", "app/**/*.tsx", "src/**/*.vue", "templates/**")


def test_ui_files_are_the_changed_files_under_ui_paths():
    changed = [
        "README.md", "web/cart.tsx", "src/pricing.py", "app/pages/cart.tsx", "templates/cart.html", "src/a/b.vue",
    ]
    assert ui_files(changed, UI) == ["web/cart.tsx", "app/pages/cart.tsx", "templates/cart.html", "src/a/b.vue"]
    assert ui_files(["src/pricing.py", "docs/web/x.md"], UI) == []  # anchored: docs/web/ is not web/
    assert ui_files(["web/cart.tsx"], ()) == []


def test_criteria_are_ui_facing_when_the_unit_touched_the_ui():
    crit = Criterion("C-0000000a", "a", Framework.OPENSPEC, "cap", "Req", "scn", "WHEN x", "specs/cap/spec.md", 1)
    assert ui_facing_criteria([crit], ["web/cart.tsx"], UI) == [crit]
    assert ui_facing_criteria([crit], ["src/pricing.py"], UI) == []


def test_playwright_auto_follows_the_e2e_gate():
    base = {"version": 1}
    assert playwright_enabled(L4Config.model_validate(base)) is False
    on = {**base, "gates": {"e2e": {"command": "pytest e2e"}}}
    assert playwright_enabled(L4Config.model_validate(on)) is True
    off = {**on, "verifier": {"playwright": {"enabled": False}}}
    assert playwright_enabled(L4Config.model_validate(off)) is False
    forced = {**base, "verifier": {"playwright": {"enabled": True}}}
    assert playwright_enabled(L4Config.model_validate(forced)) is True


def test_unit_changed_files_since_the_merge_base(make_repo, raw, git_for):
    repo: Path = make_repo()
    git = git_for(repo)
    raw(repo, "checkout", "-q", "-b", "unit")
    (repo / "web").mkdir()
    (repo / "web" / "cart.tsx").write_text("x\n")
    (repo / "name with space.py").write_text("x\n")
    (repo / "README.md").write_text("changed\n")
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "unit work")
    base = git.run("merge-base", "main", "HEAD").stdout.strip()
    assert unit_changed_files(git, base) == ["README.md", "name with space.py", "web/cart.tsx"]
    assert unit_changed_files(git, git.run("rev-parse", "HEAD").stdout.strip()) == []


@pytest.fixture
def web(make_bench, raw):  # noqa: F811
    bench = web_bench(make_bench)
    return bench, stage_base_and_head(bench, raw)


def test_serve_started_and_stopped_per_worktree(web):
    bench, base = web
    wb = bench.wb
    with base_checkout(wb, base) as tree:
        assert tree != wb.worktree and "3 items" in (tree / "app.py").read_text()
        at_base = run_e2e(wb, tree, name="e2e-base")
        at_head = run_e2e(wb, name="e2e-head")
        assert 'item-count">3 items<' in at_base.snapshot_text  # each tree serves its own app
        assert 'item-count">4 items<' in at_head.snapshot_text
        assert (tree / ".l4-out/serve.pid").is_file() and (wb.worktree / ".l4-out/serve.pid").is_file()
    assert not tree.exists() and str(tree) not in wb.git.run("worktree", "list").stdout


def test_base_checkout_is_removed_when_the_body_raises_and_a_stale_one_is_replaced(web):
    bench, base = web
    wb = bench.wb
    with pytest.raises(RuntimeError, match="boom"), base_checkout(wb, base) as tree:
        raise RuntimeError("boom")
    assert not tree.exists()
    stale = wb.unit_cache / "e2e-base"
    stale.mkdir()
    (stale / "junk").write_text("left by a killed run")
    with base_checkout(wb, base) as tree:
        assert not (tree / "junk").exists() and (tree / "app.py").is_file()


def test_serve_never_ready_is_internal_error(web):
    bench, base = web
    wb = bench.wb
    wb.cfg.gates.e2e.serve.command = "python3 -c 'import time; time.sleep(120)'"
    wb.cfg.gates.e2e.serve.timeout = "1s"
    with pytest.raises(L4Exit) as err, base_checkout(wb, base) as tree:
        run_e2e(wb, tree, name="e2e-base")
    assert err.value.code == ExitCode.INTERNAL_ERROR and not tree.exists()


def test_a_failing_setup_at_the_merge_base_is_an_internal_error(web):
    bench, base = web
    bench.wb.cfg.gates.setup = ["python3 -c 'raise SystemExit(7)'"]
    with pytest.raises(L4Exit, match="gates.setup failed at the merge base") as err, base_checkout(bench.wb, base):
        pass
    assert err.value.code == ExitCode.INTERNAL_ERROR
    assert not (bench.wb.unit_cache / "e2e-base").exists()


def test_disabled_playwright_falls_back():
    cfg = L4Config.model_validate({"version": 1, "gates": {"e2e": {"command": "pytest e2e"}},
                                   "verifier": {"playwright": {"enabled": False}}})  # fmt: skip
    assert playwright_enabled(cfg) is False  # no base checkout, no generation: the M0 traceability override stays


def case(status: str) -> TestCase:
    return TestCase("e2e.t::x", status, "")  # type: ignore[arg-type]


def test_trace_and_screenshot_paths_linked_in_report(tmp_path: Path):
    out = tmp_path / "test-results" / "e2e-test-badge-chromium"
    out.mkdir(parents=True)
    for name in ("trace.zip", "test-failed-1.png", "video.webm", "notes.txt"):
        (out / name).write_bytes(b"x")
    (tmp_path / "test-results" / "link.png").symlink_to(out / "trace.zip")
    failing = TestReport({"e2e.t::x": case("failed")})
    assert failure_artifacts(tmp_path, failing) == [
        "test-results/e2e-test-badge-chromium/test-failed-1.png",
        "test-results/e2e-test-badge-chromium/trace.zip",
        "test-results/e2e-test-badge-chromium/video.webm",
    ]  # sorted, regular files only, no symlink and no unrelated file
    assert failure_artifacts(tmp_path, TestReport({"e2e.t::x": case("passed")})) == []  # nothing failed
    assert failure_artifacts(tmp_path, None) == []
    assert failure_artifacts(tmp_path / "nowhere", failing) == []


def test_artifact_dir_follows_the_output_argument_of_the_e2e_command():
    assert artifact_dir("pytest e2e") == "test-results"
    assert artifact_dir("pytest e2e --output .l4-out/e2e/artifacts --tracing on") == ".l4-out/e2e/artifacts"
    assert artifact_dir("pytest --output=out/pw") == "out/pw"
    for bad in ("pytest --output /etc", "pytest --output ../x", "pytest --output", "pytest 'unterminated"):
        assert artifact_dir(bad) == "test-results"
