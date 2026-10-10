"""What the project's own tests already do (M1.9, P2 and P3), read from the base commit only.

`test_conventions` lists the module-level skip helpers of the project's `conftest.py` files (`pytest.mark.skipif(`,
`pytest.importorskip(`, a name bound to `pytest.mark.<x>`) and the markers of its pytest configuration, as
`path:line: text`, for the judge ("a new test that needs an optional dependency must use them") and for the audit
writer. `base_test_header` is the start of one existing test file of the base that the unit did not change, up to its
first test, which shows the writer how this project begins a test file. Both read `git show <base>:<path>` and nothing
else: what the unit changed, or left in the worktree, cannot shape them.
"""

import re
import tomllib
from collections.abc import Sequence
from pathlib import PurePosixPath

from l4.config.schema import L4Config
from l4.security.protected import glob_match
from l4.vcs.git import Git

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
