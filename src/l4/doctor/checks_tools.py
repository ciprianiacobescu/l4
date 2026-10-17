"""TOOL-001 (L4-CI-005): the first word of every configured gate command is on the gate PATH. A gate that starts
`golangci-lint`, `go` or `pnpm` on a runner that has none of them fails with "command not found" only when a unit
reaches it; this names the tool at `l4 doctor --adoption` time and points at `ci.toolchains`. Registered at import."""

import re
import shlex

from l4.ci.detect import in_ci
from l4.doctor.context import DoctorContext
from l4.doctor.registry import CONFIG_SCOPES, Check, CheckResult, Severity, register

_SEGMENTS = re.compile(r"\n|&&|\|\||;|\|")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# shell builtins and keywords: they are not programs on a PATH
_SHELL_WORDS = frozenset(
    {
        "cd",
        "export",
        "set",
        "unset",
        "echo",
        "printf",
        "test",
        "[",
        "[[",
        "true",
        "false",
        "exit",
        "source",
        ".",
        ":",
        "eval",
        "exec",
        "command",
        "pwd",
        "read",
        "ulimit",
        "umask",
        "trap",
        "wait",
        "type",
        "alias",
        "return",
        "if",
        "then",
        "else",
        "elif",
        "fi",
        "for",
        "while",
        "until",
        "do",
        "done",
        "case",
        "esac",
        "!",
        "{",
        "}",
        "(",
        "time",
        "env",
    }  # fmt: skip
)
_TOOL_HINT = (
    "add the toolchain to the L4 job: `ci.toolchains` (go, node, pnpm) for GitHub, then `l4 upgrade`; on GitLab the "
    "runner image must provide it"
)


def command_words(command: str) -> list[str]:
    """The programs a gate command starts, in order: the first word of each `&&`/`||`/`;`/`|` segment after leading
    `NAME=value` assignments. Not listed: shell builtins, a path (`./gradlew`, `.venv/bin/pytest`: inside the
    repository or absolute), a word that expands (`$X`), and what `uv run` starts (uv resolves it itself, so `uv`
    is the word)."""
    found: list[str] = []
    for segment in _SEGMENTS.split(command):
        text = segment.strip()
        if not text or text.startswith("#"):
            continue
        try:
            words = shlex.split(text)
        except ValueError:
            words = text.split()
        while words and (
            _ASSIGNMENT.match(words[0]) or words[0] in ("if", "then", "else", "elif", "do", "!", "{", "(")
        ):
            words = words[1:]
        if not words:
            continue
        word = words[0]
        if word in _SHELL_WORDS or "/" in word or any(ch in word for ch in "$`(){}*?"):
            continue
        if word not in found:
            found.append(word)
    return found


def _gate_commands(ctx: DoctorContext) -> list[tuple[str, str]]:
    gates = ctx.cfg.gates
    named = [
        *(("gates.setup", c) for c in gates.setup),
        *(("gates.build", c) for c in gates.build),
        *(("gates.lint", c) for c in gates.lint),
        *(("gates.typecheck", c) for c in gates.typecheck),
        ("gates.test", gates.test.command),
        ("gates.e2e", gates.e2e.command),
        *((f"gates.extra[{g.name}]", g.command) for g in gates.extra),
    ]
    return [(where, command) for where, command in named if command.strip()]


def _on_path(ctx: DoctorContext, word: str) -> bool:
    # a runner with Python 3 and no `python` link: `python3` is enough (a venv or uv supplies the rest)
    return ctx.which(word) is not None or (word == "python" and ctx.which("python3") is not None)


def _tool_001(ctx: DoctorContext) -> CheckResult:
    commands = _gate_commands(ctx)
    if not commands:
        return CheckResult("skip", "no gate command is configured")
    missing: dict[str, list[str]] = {}
    for where, command in commands:
        for word in command_words(command):
            if _on_path(ctx, word):
                continue
            if where not in missing.setdefault(word, []):
                missing[word].append(where)
    if not missing:
        return CheckResult("pass", f"the first word of each of {len(commands)} gate command(s) is on the gate PATH")
    lines = "; ".join(f"`{word}` ({', '.join(where)})" for word, where in missing.items())
    severity: Severity = "error" if in_ci(ctx.env) and not ctx.adoption else "warn"
    return CheckResult("fail", f"not on the gate PATH: {lines}", _TOOL_HINT, severity=severity)


TOOL_001 = register(Check("TOOL-001", "Gate commands are on the gate PATH", "error", _tool_001, CONFIG_SCOPES))
