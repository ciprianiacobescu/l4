"""A changed Python file at the repository root is never measured (`coverage_sources` names directories only), so it
must not count in diff coverage either: it is listed as unmeasured, carries no label and stays out of the percentage."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from l4.config.schema import L4Config
from l4.evidence.collect import collect_evidence, coverage_sources
from l4.specs.base import Framework, UnitRef
from l4.vcs.git import Git

# the unit's commits are the harness's: the bot identity and an `L4-Run` trailer (per-commit attribution)
IDENT = ("-c", "user.name=l4-bot", "-c", "user.email=l4-bot@users.noreply.invalid")
BODY = "def run():\n" + "".join(f"    x{i} = {i}\n" for i in range(8)) + "    return 1\n"


@dataclass
class Bench:
    git: Git
    cfg: L4Config
    worktree: Path


def _commit(git: Git, msg: str) -> str:
    git.run("add", "-A")
    git.run(*IDENT, "commit", "-qm", msg, "--trailer", "L4-Run: r-1")
    return git.rev_parse("HEAD")


def _repo(tmp: Path, base_files: dict[str, str], head_files: dict[str, str]) -> tuple[Git, str, str]:
    tmp.mkdir(parents=True)
    git = Git(tmp)
    git.run("init", "--quiet")
    for rel, text in {"specs/u/proposal.md": "Change `src/shop/cart.py`.\n", **base_files}.items():
        (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp / rel).write_text(text)
    base = _commit(git, "base")
    for rel, text in head_files.items():
        (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp / rel).write_text(text)
    return git, base, _commit(git, "head")


def _cov_dir(out: Path, files: dict[str, dict]) -> None:
    out.mkdir(parents=True)
    data = json.dumps({"meta": {"version": "7.0"}, "files": files}).encode()
    (out / "coverage.json").write_bytes(data)
    (out / "nonce").write_text("n1")
    (out / "status.json").write_text(
        json.dumps(
            {"status": "ok", "nonce": "n1", "json_sha256": hashlib.sha256(data).hexdigest(), "coverage_version": "7.0"}
        )
    )


def _evidence(tmp: Path, git: Git, base: str, head: str, mode: str, cov_files: dict[str, dict]):
    cfg = L4Config.model_validate({"verifier": {"evidence": {"diff_coverage": {"mode": mode}}}})
    _cov_dir(tmp / "cov", cov_files)
    ref = UnitRef(Framework.OPENSPEC, "u", tmp / "specs" / "u")
    return collect_evidence(Bench(git, cfg, tmp), base, head, None, tmp / "cov", ref, gate_passed=True, cov_nonce="n1")


@pytest.mark.parametrize("mode", ["warn", "fail"])
def test_flat_layout_root_module_is_unmeasured_not_uncovered(tmp_path: Path, mode: str):
    git, base, head = _repo(tmp_path / "r", {"app.py": "VALUE = 1\n"}, {"app.py": BODY})
    cfg = L4Config()
    assert coverage_sources(git, base, head, cfg) == []  # a root file is never a coverage source
    ev = _evidence(tmp_path, git, base, head, mode, {})
    assert ev.coverage and ev.coverage.unmeasured_files == ("app.py",)
    assert ev.coverage.functions == [] and ev.coverage.percent == 100.0
    assert ev.labels["functions"] == {}
    assert not ev.holds and not [f for f in ev.findings if "covered" in f.title]
    assert "app.py" in "\n".join(ev.section())  # named, so a human sees it was not measured


@pytest.mark.parametrize("mode", ["warn", "fail"])
def test_src_layout_root_noxfile_does_not_drag_the_measured_code_down(tmp_path: Path, mode: str):
    cart = "def total(a):\n    b = a + 1\n    c = b + 1\n    return c\n"
    git, base, head = _repo(tmp_path / "r", {"noxfile.py": "X = 1\n"}, {"noxfile.py": BODY, "src/shop/cart.py": cart})
    assert coverage_sources(git, base, head, L4Config()) == ["src/shop"]
    ran = {"src/shop/cart.py": {"executed_lines": [1, 2, 3, 4], "missing_lines": [], "contexts": {}}}
    ev = _evidence(tmp_path, git, base, head, mode, ran)
    assert ev.coverage and ev.coverage.percent == 100.0 and ev.coverage.unmeasured_files == ("noxfile.py",)
    assert not ev.holds and not ev.findings
    assert set(ev.labels["functions"]) == {"src/shop/cart.py::total"}


# --- changed code outside the measured language (L4-VER-002 step 6, SCN-VER-55, SCN-VER-56) ------------------------

TS = "export function score(a: number) {\n  return a + 1;\n}\n"


@pytest.mark.parametrize("mode", ["warn", "fail"])
def test_typescript_only_change_is_not_measured_not_a_hundred_percent(tmp_path: Path, mode: str):
    git, base, head = _repo(
        tmp_path / "r", {"services/engine.ts": "export {};\n"},
        {"services/engine.ts": TS, "docs/notes.md": "x\n", "services/engine.test.ts": TS},
    )  # fmt: skip
    ev = _evidence(tmp_path, git, base, head, mode, {})
    dc = ev.coverage
    assert dc and dc.status == "not_applicable" and dc.other_files == ("services/engine.ts",)
    assert dc.reason == "diff coverage measures python only; changed code outside it: services/engine.ts"
    assert not ev.holds and not ev.findings and ev.coverage_check.note == f"not measured: {dc.reason}"
    text = "\n".join(ev.section())
    assert "Diff coverage not measured: diff coverage measures python only" in text and "100.0%" not in text
    attention = text[text.index("Needs attention") : text.index("### Files")]
    assert "Nothing needs attention" in attention  # not a hold and not a "needs attention" line
    assert ev.to_json()["diff_coverage"]["other_files"] == ["services/engine.ts"]


def test_mixed_change_measures_python_and_names_the_rest(tmp_path: Path):
    cart = "def total(a):\n    b = a + 1\n    c = b + 1\n    return c\n"
    git, base, head = _repo(tmp_path / "r", {}, {"src/shop/cart.py": cart, "web/app.tsx": TS})
    ran = {"src/shop/cart.py": {"executed_lines": [1, 2, 3, 4], "missing_lines": [], "contexts": {}}}
    ev = _evidence(tmp_path, git, base, head, "fail", ran)
    dc = ev.coverage
    assert dc and dc.status == "ok" and dc.percent == 100.0 and dc.other_files == ("web/app.tsx",)
    assert not ev.holds and not ev.findings
    assert "Not measured: diff coverage measures python only; changed code outside it: web/app.tsx" in "\n".join(
        ev.section()
    )


def test_a_change_with_no_code_is_still_fully_covered(tmp_path: Path):
    git, base, head = _repo(tmp_path / "r", {"README.md": "a\n"}, {"README.md": "b\n", "package.json": "{}\n"})
    dc = _evidence(tmp_path, git, base, head, "fail", {}).coverage
    assert dc and dc.status == "ok" and dc.percent == 100.0 and dc.other_files == ()
