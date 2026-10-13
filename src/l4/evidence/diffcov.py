"""Diff coverage: is each changed function run by the tests? (verifier 3.11 reduced, M1.6 D4)

Three steps, all deterministic: `diff_lines` (which head lines the unit added or modified), `changed_functions` (the
function each line belongs to, by `ast`) and `diff_coverage` (those lines against the coverage.py JSON that the `l4_cov`
plugin wrote during the verifier's own test run). A line is executable when coverage lists it as executed or missing;
comments, blank lines and docstrings never count. Execution is not verification: "covered" says the line ran.
A change with code only in a language it does not measure is `not_applicable`, never 100 percent (L4-VER-002 step 6).
M1: other languages; branch coverage; a continuation line of a multi-line statement is not an executable line, so a
change confined to one is not seen.
"""

import ast
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from l4.config.schema import L4Config
from l4.vcs.git import Git
from l4.verifier.types import Finding, Severity

MODULE = "<module>"
MAX_NAMED = 5
LANGUAGE_SUFFIXES = {"python": (".py",)}  # the languages diff coverage measures (`DiffCoverageCfg.languages`)
CODE_SUFFIXES = frozenset({  # what counts as source code when a file is not measured: by extension, never data
    ".py", ".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte", ".go", ".rs", ".java",
    ".kt", ".kts", ".scala", ".cs", ".fs", ".rb", ".php", ".swift", ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp",
    ".m", ".mm", ".dart", ".ex", ".exs", ".lua", ".sh", ".bash", ".zsh", ".ps1",
})  # fmt: skip
FuncStatus = Literal["covered", "partly", "uncovered", "n/a", "unmeasured", "not_run"]
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_ESCAPES = {"a": 7, "b": 8, "f": 12, "n": 10, "r": 13, "t": 9, "v": 11, '"': 34, "\\": 92}


def _unquote(name: str) -> str:
    """git's C-style quoting of a path with a quote, backslash, control or (by default) non-ASCII character."""
    if not (len(name) >= 2 and name.startswith('"') and name.endswith('"')):
        return name
    body, raw, i = name[1:-1], bytearray(), 0
    while i < len(body):
        if body[i] != "\\" or i + 1 >= len(body):
            raw.extend(body[i].encode("utf-8"))
            i += 1
        elif body[i + 1] in "01234567":
            raw.append(int(body[i + 1 : i + 4], 8) & 0xFF)
            i += 4
        else:
            raw.append(_ESCAPES.get(body[i + 1], ord(body[i + 1]) & 0x7F))
            i += 2
    return raw.decode("utf-8", "replace")


def diff_lines(
    git: Git, base: str, head: str, *, exclude: Callable[[str], bool] = lambda path: False
) -> dict[str, frozenset[int]]:
    """Added and modified head lines per Python file, from `git diff -U0 --find-renames`. Deleted files, pure
    deletions and the paths `exclude` names (tests, exempt files: the caller knows the config) are left out."""
    done = git.run(
        "diff", "-U0", "--find-renames", "--no-color", "--no-ext-diff", "--no-textconv", "--diff-filter=ACMR",
        "--src-prefix=a/", "--dst-prefix=b/", base, head, "--",
    )  # fmt: skip
    found: dict[str, set[int]] = {}
    current: str | None = None
    in_header = False  # a '+++ ' line is a file header only between `diff --git` and the first hunk
    for line in done.stdout.splitlines():
        if line.startswith("diff --git "):
            in_header, current = True, None
        elif line.startswith("@@"):
            in_header = False
        if in_header and line.startswith("+++ "):
            target = _unquote(line[4:].rstrip("\t"))
            current = target[2:] if target.startswith("b/") else None
            if current and (not current.endswith(".py") or exclude(current)):
                current = None
        elif current and (hunk := _HUNK.match(line)):
            start, count = int(hunk.group(1)), int(hunk.group(2) or 1)
            if count:
                found.setdefault(current, set()).update(range(start, start + count))
    return {path: frozenset(lines) for path, lines in sorted(found.items())}


@dataclass(frozen=True)
class ChangedFunction:
    path: str
    qualname: str  # `Class.method`, `outer.inner`, or `<module>`
    span: tuple[int, int]
    lines: frozenset[int]  # the lines whose execution answers "did a test run this change?"


@dataclass(frozen=True)
class _Node:
    qualname: str
    start: int
    end: int
    header_end: int  # last line of decorators and signature; a class has none (0)
    entry: int | None  # the first statement of a function that is not its docstring
    is_function: bool


def _nodes(tree: ast.AST) -> list[_Node]:
    found: list[_Node] = []

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                qual = f"{prefix}{child.name}"
                start = min([child.lineno, *(d.lineno for d in child.decorator_list)])
                function = not isinstance(child, ast.ClassDef)
                body = child.body
                docstring = (
                    isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)
                )  # fmt: skip
                real = body[1:] if docstring else body
                found.append(_Node(
                    qual, start, child.end_lineno or child.lineno, body[0].lineno - 1 if function else 0,
                    real[0].lineno if real and function else None, function,
                ))  # fmt: skip
                walk(child, qual + ".")
            else:
                walk(child, prefix)

    walk(tree, "")
    return found


def changed_functions(path: str, text: str, lines: set[int] | frozenset[int]) -> list[ChangedFunction]:
    """Group `lines` by their innermost function (or class, for class-level statements); module-level lines go to
    `<module>`. A change confined to a function's signature or decorators is judged by whether the function was
    entered (its first real statement), because the `def` line itself runs at import."""
    try:
        nodes = _nodes(ast.parse(text))
    except (SyntaxError, ValueError):
        return [ChangedFunction(path, MODULE, (1, max(lines, default=1)), frozenset(lines))] if lines else []
    groups: dict[_Node | None, set[int]] = {}
    for line in sorted(lines):
        inside = [n for n in nodes if n.start <= line <= n.end]
        owner = max(inside, key=lambda n: (n.start, -n.end), default=None)
        groups.setdefault(owner, set()).add(line)
    out: list[ChangedFunction] = []
    for owner, group in groups.items():
        if owner is None:
            out.append(ChangedFunction(path, MODULE, (min(group), max(group)), frozenset(group)))
            continue
        body = {n for n in group if n > owner.header_end}
        checked = body or ({owner.entry} if owner.entry else set())
        out.append(ChangedFunction(path, owner.qualname, (owner.start, owner.end), frozenset(checked)))
    return sorted(out, key=lambda f: (f.path, f.span, f.qualname))


@dataclass(frozen=True)
class FunctionCoverage:
    path: str
    qualname: str
    status: FuncStatus
    executable: int = 0
    executed: int = 0
    tests: tuple[str, ...] = ()  # contexts: the test functions that ran its changed lines

    @property
    def label(self) -> bool | None:
        """Ground truth for `change-covered`: covered is true, uncovered false, anything else is no label."""
        return {"covered": True, "uncovered": False}.get(self.status)


@dataclass(frozen=True)
class DiffCoverage:
    percent: float
    functions: list[FunctionCoverage] = field(default_factory=list)
    status: Literal["ok", "not_run", "not_applicable"] = "ok"
    reason: str = ""
    unmeasured_files: tuple[str, ...] = ()  # changed root-level .py files: never measured
    other_files: tuple[str, ...] = ()  # changed code in a language diff coverage does not measure: never measured

    @property
    def outside_note(self) -> str:
        """What the report says about `other_files` (empty when there are none): the files, cut at `MAX_NAMED`."""
        return outside_note(self.other_files)


def outside_note(files: Sequence[str]) -> str:
    named = ", ".join(files[:MAX_NAMED]) + (f" and {len(files) - MAX_NAMED} more" if len(files) > MAX_NAMED else "")
    return f"diff coverage measures python only; changed code outside it: {named}" if files else ""


def suffixes(languages: Sequence[str]) -> tuple[str, ...]:
    return tuple(x for lang in languages for x in LANGUAGE_SUFFIXES.get(lang, ()))


def _tests_of(file: Mapping[str, Any], lines: set[int]) -> tuple[str, ...]:
    contexts = file.get("contexts") or {}
    names = {c.split("|", 1)[0] for n in lines for c in contexts.get(str(n), []) if c}
    return tuple(sorted(names))


def diff_coverage(
    changed: Sequence[ChangedFunction], cov_json: Mapping[str, Any] | None, status: Mapping[str, Any]
) -> DiffCoverage:
    """`status` is the plugin's `status.json`; anything but `ok`, or no data, is `not_run` with the reason."""
    if status.get("status") != "ok" or cov_json is None:
        reason = str(status.get("reason") or "no coverage data was produced")
        return DiffCoverage(0.0, [FunctionCoverage(f.path, f.qualname, "not_run") for f in changed], "not_run", reason)
    files = cov_json.get("files", {})
    functions: list[FunctionCoverage] = []
    executable_total = executed_total = 0
    for f in changed:
        data = files.get(f.path)
        if data is None:
            functions.append(FunctionCoverage(f.path, f.qualname, "unmeasured", len(f.lines)))
            executable_total += len(f.lines)  # fail closed: a file the report lacks is not a file without risk
            continue
        executed = set(data.get("executed_lines", ()))
        executable = f.lines & (executed | set(data.get("missing_lines", ())))
        ran = executable & executed
        if not executable:
            functions.append(FunctionCoverage(f.path, f.qualname, "n/a"))
            continue
        state: FuncStatus = "covered" if ran == executable else "uncovered" if not ran else "partly"
        functions.append(FunctionCoverage(f.path, f.qualname, state, len(executable), len(ran), _tests_of(data, ran)))
        executable_total += len(executable)
        executed_total += len(ran)
    percent = round(100.0 * executed_total / executable_total, 1) if executable_total else 100.0
    return DiffCoverage(percent, functions)


@dataclass
class CoverageCheck:
    findings: list[Finding] = field(default_factory=list)
    holds: list[str] = field(default_factory=list)
    hold_subjects: list[list[str]] = field(default_factory=list)  # `path::qualname` of the functions each hold names
    note: str = ""


def check_diff_coverage(dc: DiffCoverage, cfg: L4Config) -> CoverageCheck:
    """Below `min_percent`: `warn` is one hold, `fail` a deterministic major finding. The check fails closed: under
    `fail`, coverage that could not be measured is a hold, never a pass. The hold text has no numbers (C-M16-3)."""
    setting = cfg.verifier.evidence.diff_coverage
    out = CoverageCheck()
    if setting.mode == "off":
        return out
    if dc.status == "not_applicable":
        out.note = f"not measured: {dc.reason}"  # no hold under `fail` either: there was nothing it could measure
        return out
    if dc.status == "not_run":
        out.note = f"diff coverage not measured: {dc.reason}"
        if setting.mode == "fail":
            out.holds.append(f"diff coverage: not measured: {dc.reason}")
            out.hold_subjects.append([])
        return out
    if dc.percent >= setting.min_percent:
        return out
    named = sorted(f"{f.path}::{f.qualname}" for f in dc.functions if f.status in ("uncovered", "partly", "unmeasured"))
    text = "diff coverage: changed code not run by any test: " + ", ".join(f"`{n}`" for n in named)
    if setting.mode == "warn":
        out.holds.append(text)
        out.hold_subjects.append(named)
    else:
        detail = f"{dc.percent}% of the changed executable lines ran, below the minimum {setting.min_percent}%. {text}"
        out.findings.append(Finding(Severity.MAJOR, "changed code is not covered by tests", detail, "deterministic"))
    return out
