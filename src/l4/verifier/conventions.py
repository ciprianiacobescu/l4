"""What the project's own tests already do (M1.9, P2 and P3), read from the base commit only.

`test_conventions` lists the module-level skip helpers of the project's `conftest.py` files (`pytest.mark.skipif(`,
`pytest.importorskip(`, a name bound to `pytest.mark.<x>`) and the markers of its pytest configuration, as
`path:line: text`, for the judge ("a new test that needs an optional dependency must use them") and for the audit
writer. `base_test_header` is the start of one existing test file of the base that the unit did not change, up to its
first test, which shows the writer how this project begins a test file. Both read `git show <base>:<path>` and nothing
else: what the unit changed, or left in the worktree, cannot shape them. `e2e_support_files` is the same for the UI
test writer: the e2e suite's `conftest.py` and helper modules at the base, bounded (L4-VER-077).
"""

import re
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

from l4.config.schema import L4Config
from l4.security.protected import glob_match
from l4.vcs.git import Git
from l4.verifier.testwriter import E2E_DIR

MAX_LINES = 40
MAX_CHARS = 3000
MAX_CONFTESTS = 5
MAX_LINE_CHARS = 200
HEADER_LINES = 40
_HELPER = re.compile(
    r"^(?:[A-Za-z_][A-Za-z0-9_]*\s*=\s*.*\bpytest\.mark\.\w+|.*\bpytest\.(?:importorskip|mark\.skipif)\()"
)
_FIRST_TEST = re.compile(r"^(?:def test_|async def test_|class Test)")
_GENERATED = re.compile(r"(^|/)test_l4_audit_c_[0-9a-f]{8}_r\d+\.py$|^e2e/")
INI_FILES = ("pytest.ini", ".pytest.ini")
MAX_SUITE_FILES = 6
MAX_SUITE_FILE_CHARS = 8_000
MAX_SUITE_CHARS = 20_000
_REGULAR = ("100644", "100755")
_TEST_MODULE = re.compile(r"^(?:test_.*|.*_test)\.py$")
_SKIPPED_PART = re.compile(r"^(?:\..*|__pycache__|node_modules)$")


def _show(git: Git, base: str, path: str) -> str | None:
    done = git.run("show", f"{base}:{path}", check=False)
    return done.stdout if done.returncode == 0 else None


def _files(git: Git, base: str) -> list[str]:
    return [p for p in git.run("ls-tree", "-r", "--name-only", base).stdout.splitlines() if p]


def _conftests(files: Sequence[str], cfg: L4Config) -> list[str]:
    globs = cfg.tdd.test_globs
    found = [
        p for p in files
        if PurePosixPath(p).name == "conftest.py" and ("/" not in p or any(glob_match(g, p) for g in globs))
    ]  # fmt: skip
    return sorted(found, key=lambda p: (p.count("/"), p))[:MAX_CONFTESTS]


def _helper_lines(path: str, text: str) -> list[str]:
    return [
        f"{path}:{number}: {line.strip()[:MAX_LINE_CHARS]}"
        for number, line in enumerate(text.splitlines(), 1)
        if line and not line[0].isspace() and _HELPER.match(line)
    ]


def _marker_lines(git: Git, base: str, files: Sequence[str]) -> list[str]:
    out: list[str] = []
    text = _show(git, base, "pyproject.toml")
    if text is not None:
        try:
            markers = tomllib.loads(text).get("tool", {}).get("pytest", {}).get("ini_options", {}).get("markers", [])
        except tomllib.TOMLDecodeError:
            markers = []
        lines = text.splitlines()
        for marker in markers if isinstance(markers, list) else []:
            if isinstance(marker, str):
                number = next((n for n, line in enumerate(lines, 1) if marker in line), 0)
                out.append(f"pyproject.toml:{number}: {' '.join(marker.split())[:MAX_LINE_CHARS]}")
    for name in INI_FILES:
        if name not in files or (ini := _show(git, base, name)) is None:
            continue
        inside = False
        for number, line in enumerate(ini.splitlines(), 1):
            if re.match(r"^markers\s*[=:]", line):
                inside = True
                rest = line.split("=", 1)[-1].strip() if "=" in line else ""
                if rest:
                    out.append(f"{name}:{number}: {rest[:MAX_LINE_CHARS]}")
            elif inside and line[:1].isspace() and line.strip():
                out.append(f"{name}:{number}: {line.strip()[:MAX_LINE_CHARS]}")
            elif inside:
                inside = False
    return out


def test_conventions(git: Git, base_sha: str, cfg: L4Config) -> str:
    """The project's skip helpers and markers at `base_sha` as `path:line: text` lines (at most 40 lines and 3,000
    characters); '' when the project defines none."""
    files = _files(git, base_sha)
    lines: list[str] = []
    for path in _conftests(files, cfg):
        if (text := _show(git, base_sha, path)) is not None:
            lines += _helper_lines(path, text)
    lines += _marker_lines(git, base_sha, files)
    kept: list[str] = []
    size = 0
    for line in lines[:MAX_LINES]:
        if size + len(line) + 1 > MAX_CHARS:
            break
        kept.append(line)
        size += len(line) + 1
    return "\n".join(kept)


test_conventions.__test__ = False  # type: ignore[attr-defined]  # not a pytest test


def _header(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        if _FIRST_TEST.match(line):
            break
        lines.append(line)
    return ("\n".join(lines[:HEADER_LINES]).rstrip() + "\n") if "".join(lines).strip() else ""


def base_test_header(git: Git, base_sha: str, changed: Sequence[str], near: str) -> tuple[str, str] | None:
    """(path, header) of one test file of the base that the unit did not change: the lines before its first test, at
    most 40. The same directory as `near` (the new test's path) is preferred, then the first path in order; the
    harness's own generated tests and the e2e folder are never shown. None when no such file has a header."""
    tests = [
        p for p in _files(git, base_sha)
        if p.endswith(".py") and PurePosixPath(p).name.startswith("test_") and p not in changed
        and not _GENERATED.search(p)
    ]  # fmt: skip
    here = str(PurePosixPath(near).parent)
    for path in sorted(tests, key=lambda p: (str(PurePosixPath(p).parent) != here, p)):
        if (text := _show(git, base_sha, path)) is not None and (header := _header(text)):
            return path, header
    return None


@dataclass(frozen=True)
class E2eSupport:
    """What the UI test writer is shown of the e2e suite: (label, text) blocks, the paths shown and the paths left out
    (also named in the last block)."""

    blocks: tuple[tuple[str, str], ...] = ()
    shown: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()


def _support_candidates(git: Git, base: str) -> list[str]:
    """The regular `.py` files under `e2e/` at the base that support the suite: not a test module, not a `conftest.py`
    below `e2e/`, no part that starts with `.` or is `__pycache__` or `node_modules`. `e2e/conftest.py` first, then
    by depth and path."""
    listing = git.run("ls-tree", "-r", "-z", base, "--", E2E_DIR).stdout
    found = []
    for entry in listing.split("\0"):
        meta, _, path = entry.partition("\t")
        parts = PurePosixPath(path).parts
        if not path or meta.split(" ")[0] not in _REGULAR or not path.endswith(".py"):
            continue
        name = parts[-1]
        if _TEST_MODULE.match(name) or any(_SKIPPED_PART.match(part) for part in parts):
            continue
        if name == "conftest.py" and path != f"{E2E_DIR}/conftest.py":
            continue
        found.append(path)
    return sorted(found, key=lambda p: (p != f"{E2E_DIR}/conftest.py", p.count("/"), p))


def e2e_support_files(git: Git, base_sha: str) -> E2eSupport:
    """The e2e suite's support files at `base_sha` for the UI test writer (L4-VER-077): `e2e/conftest.py`, then the
    other helper modules, each cut at 8,000 characters and taken until six are taken or the next would bring the total
    past 20,000; the rest are named in one more block. The base only: the generated test runs at the base and, at
    head, with the support files the unit changed at their base versions, so a helper the unit added is not shown."""
    blocks: list[tuple[str, str]] = []
    shown: list[str] = []
    skipped: list[str] = []
    size = 0
    for path in _support_candidates(git, base_sha):
        text = _show(git, base_sha, path)
        if text is None or not text.strip():
            continue
        cut = text[:MAX_SUITE_FILE_CHARS]
        if skipped or len(shown) >= MAX_SUITE_FILES or size + len(cut) > MAX_SUITE_CHARS:
            skipped.append(path)
            continue
        note = f", first {MAX_SUITE_FILE_CHARS} characters" if len(cut) < len(text) else ""
        blocks.append((f"{path} (e2e support file at the merge base{note})", cut))
        shown.append(path)
        size += len(cut)
    if skipped:
        blocks.append(("e2e support files not shown", "\n".join(skipped)))
    return E2eSupport(tuple(blocks), tuple(shown), tuple(skipped))
