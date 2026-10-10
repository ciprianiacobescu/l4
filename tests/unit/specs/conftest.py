import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

RECORDED = Path(__file__).resolve().parents[2] / "fixtures" / "recorded" / "openspec" / "1.14.0"

# The 39-line grammar file of spikes/04 (setup.sh), without a trailing newline.
GRAMMAR_LINES = [
    "\ufeff- [ ] 0.1 BOM-prefixed first line", "# Tasks", "", "## 1. Grammar", "",
    "- [ ] 1.1 plain unchecked", "- [x] 1.2 lower x", "- [X] 1.3 upper X",
    "  - [ ] 1.3.1 indented two spaces", "    - [x] 1.3.2 indented four spaces", "\t- [ ] 1.3.3 tab indented",
    "- [ x] 1.4 padded x", "- [ x ] 1.5 padded both", "- [-] 1.6 dash marker", "- [~] 1.7 tilde marker",
    "- [] 1.8 empty brackets", "* [ ] 1.9 star bullet", "+ [ ] 1.10 plus bullet", "1. [ ] 1.11 ordered dot",
    "2) [x] 1.12 ordered paren", "-[ ] 1.13 no space after bullet", "- [x]1.14 no space after bracket",
    "- [ ]", "- [x]", "- [ ]* 1.15 kiro optional star", "\u00a0\u00a0- [ ] 1.16 nbsp indented",
    "- [A](https://example.com) link bullet", "- [ ](https://example.com) blank-box link",
    "- [WIP] multi-char marker", "- [ ] 1.17 trailing spaces   ", "- [ ] 1.18 has a form\x0cfeed inside",
    "- [ ] 1.19 has a line\u2028separator inside", "```md", "- [ ] 9.9 inside code fence", "```",
    "<!--", "- [ ] 9.8 inside html comment", "-->", "- [ ] 1.20 last line without newline",
]  # fmt: skip


@pytest.fixture
def recorded() -> Callable[[str], Any]:
    def load(name: str) -> Any:
        return json.loads((RECORDED / name).read_text(encoding="utf-8"))

    return load


@pytest.fixture
def grammar_lf() -> bytes:
    return "\n".join(GRAMMAR_LINES).encode("utf-8")


@pytest.fixture
def grammar_crlf(grammar_lf: bytes) -> bytes:
    return grammar_lf.replace(b"\n", b"\r\n")


GREETING_DELTA = """## MODIFIED Requirements

### Requirement: Greet by name
The system SHALL greet the user by the name given on the command line, trimming surrounding whitespace.

#### Scenario: Named greeting
- **WHEN** the user runs `greet " Ada "`
- **THEN** the output is `Hello, Ada!`

## ADDED Requirements

### Requirement: Shout
The system SHALL print the greeting in upper case when `--shout` is given.

#### Scenario: Shouted greeting
- **WHEN** the user runs `greet Ada --shout`
- **THEN** the output is `HELLO, ADA!`
"""
FAREWELL_DELTA = """## Purpose
The farewell capability says goodbye to a named user of the greeter command line tool.

## ADDED Requirements

### Requirement: Say goodbye
The system SHALL print `Goodbye, <name>!` for `farewell <name>`.

#### Scenario: Named farewell
- **WHEN** the user runs `farewell Ada`
- **THEN** the output is `Goodbye, Ada!`
"""
FAREWELL_TASKS = (
    "# Tasks\n\n## 1. Greeting\n\n- [x] 1.1 Trim whitespace around the name\n- [x] 1.2 Add `--shout`\n\n"
    "## 2. Farewell\n\n- [ ] 2.1 Add `farewell` function\n- [ ] 2.2 Wire `farewell` command\n"
    "- [ ] 2.3 Document both commands\n"
)  # the add-farewell change of spikes/04 setup.sh


@pytest.fixture
def make_change():
    """Write an OpenSpec change directory under `<repo>/openspec/changes/<name>`; returns its path."""

    def make(
        repo: Path, name: str, *, tasks: str | bytes | None = None, specs: dict[str, str | bytes] | None = None
    ) -> Path:
        change = repo / "openspec" / "changes" / name
        change.mkdir(parents=True)
        if tasks is not None:
            (change / "tasks.md").write_bytes(tasks if isinstance(tasks, bytes) else tasks.encode())
        for capability, text in (specs or {}).items():
            (change / "specs" / capability).mkdir(parents=True)
            (change / "specs" / capability / "spec.md").write_bytes(text if isinstance(text, bytes) else text.encode())
        return change

    return make


@pytest.fixture
def add_farewell(tmp_path: Path, make_change) -> tuple[Path, Path]:
    """(repo, change dir) holding the add-farewell change recorded in spikes/04."""
    repo = tmp_path / "repo"
    change = make_change(
        repo, "add-farewell", tasks=FAREWELL_TASKS, specs={"greeting": GREETING_DELTA, "farewell": FAREWELL_DELTA}
    )
    return repo, change


class ReplayRunner:
    """A `Runner` that answers from recorded OpenSpec outputs (tests/fixtures/recorded/openspec/1.14.0)."""

    def __init__(self, replies: dict[tuple[str, ...], tuple[int, str]]) -> None:
        self.replies = replies
        self.calls: list[tuple[list[str], Path, dict[str, str], float]] = []

    def __call__(self, argv, cwd, env, timeout):
        from l4.doctor.context import CmdResult

        self.calls.append((list(argv), cwd, dict(env), timeout))
        exit_code, stdout = self.replies[tuple(argv[2:])]
        return CmdResult(exit_code, stdout, "")


@pytest.fixture
def replay() -> Callable[..., ReplayRunner]:
    """replay("validate-modify-missing-strict", ...) -> a runner that serves those recorded cases by argv."""
    index = {
        row["case"]: row
        for row in map(json.loads, (RECORDED / "_index.jsonl").read_text(encoding="utf-8").splitlines())
    }

    def make(*cases: str) -> ReplayRunner:
        replies = {}
        for case in cases:
            row = index[case]
            replies[tuple(row["argv"][1:])] = (row["exit"], (RECORDED / row["stdout_file"]).read_text(encoding="utf-8"))
        return ReplayRunner(replies)

    return make


@pytest.fixture
def fake_install(tmp_path: Path) -> dict[str, str]:
    """An environment with a fake node and a fake pinned install under tmp_path (never the developer's)."""
    node = tmp_path / "bin" / "node"
    node.parent.mkdir()
    node.write_text("#!/bin/sh\n")
    node.chmod(0o755)
    home = tmp_path / "l4home"
    entry = home / "npm" / "node_modules" / "@fission-ai" / "openspec" / "bin" / "openspec.js"
    entry.parent.mkdir(parents=True)
    entry.write_text("// fake\n")
    return {
        "PATH": str(node.parent), "HOME": str(tmp_path / "home"), "L4_HOME": str(home),
        "L4_CACHE": str(tmp_path / "cache"),
    }  # fmt: skip
