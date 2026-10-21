"""Run a simulation fixture's own gate on a plain copy of its seed tree, applying payloads like a scripted agent."""

import subprocess
import sys
from pathlib import Path

from l4.gates.junit import TestReport, parse_junit
from l4.sim.remote import _copy
from l4.sim.scenarios import fixture_root


def seed_copy(fixture: str, destination: Path) -> Path:
    _copy(fixture_root(fixture).joinpath("repo"), destination)
    return destination


def payload(fixture: str, name: str) -> str:
    return fixture_root(fixture).joinpath("payloads", name).read_text(encoding="utf-8")


def apply(fixture: str, repo: Path, files: dict[str, str]) -> None:
    """`files`: repository path -> payload file name."""
    for path, name in files.items():
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload(fixture, name), encoding="utf-8")


def gate(repo: Path) -> tuple[int, TestReport]:
    done = subprocess.run(
        [sys.executable, "tests/run_junit.py"], cwd=repo, capture_output=True, text=True, check=False, timeout=60
    )
    return done.returncode, parse_junit(repo / ".l4-out" / "junit.xml")
