#!/usr/bin/env python3
"""Check that a delivery plan can go from the working tree to an active plan, and print the one next command: Python
standard library only.

    python3 yolo_preflight.py PLAN [--repo DIR] [--no-fetch] [--l4 CMD] [--json]

It runs in the consumer repository and changes no file of the working tree: it fetches the remote-tracking ref of the
base branch, and the harness commands it runs (`yolo check`, `yolo status`, `yolo findings`) fetch the unit refs. Twelve
checks run in order (plan file, clean tree, origin, HEAD is origin/<base>, the plan and its unit folders on origin, the
judge roles, the installed OpenCode major, accept_by_agents, the caller, the harness, admission, the review). Then it
prints exactly one line that starts with `Next:`. The origin is what counts: CI and `l4 yolo activate` read
`origin/<base>`, never the working tree (yolo-guardrails D10, requirement L4-SKL-005).

`--l4` is the harness command (default `l4`; `uvx --from SPEC l4` works): it is split with shlex and also names the
commands of the `Next:` line. `--no-fetch` skips the fetch of the base branch. `--json` prints one document,
`l4/yolo-preflight@1`: {plan, base, caller, checks, next, exit}.

Exit 0: no check failed. Exit 1: a check failed (its fix is the `Next:` line). Exit 2: a usage error (a plan id that is
not lower-case letters, digits and '-', or a --repo that is not a git work tree).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import selectors
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

SCHEMA = "l4/yolo-preflight@1"
PLAN_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
MAP_KEY = re.compile(r"""^(?:"([^"\\]+)"|'([^']+)'|([A-Za-z0-9_.-]+)):(?:\s+(.*))?$""")
# Constants held equal to the harness by a test (`l4.config.roles`, `l4.actor`, `l4.provision.catalog`).
JUDGE_ADAPTERS = ("claude-code", "codex", "opencode", "fake")
JUDGE_ROLES = ("judges", "verifier_agent", "clarifier", "s1_judge")
HARNESS_ADAPTERS = ("claude-code", "codex", "opencode", "kiro-cli", "command", "fake")
AGENT_MARKERS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "AI_AGENT", "CODEX_SANDBOX", "L4_RESULT_PATH")
OPENCODE_PIN = "1.18.34"
OPENCODE_MAJOR = 1
DEFAULT_OPENSPEC_ROOT = "openspec"
DEFAULT_KIRO_ROOT = ".kiro/specs"
GIT_TIMEOUT_S = 60.0
L4_TIMEOUT_S = 300.0
OPENCODE_TIMEOUT_S = 20.0
EOF_GRACE_S = 2.0
MAX_STREAM_BYTES = 16 * 1024 * 1024
MAX_NAMED = 3
PERSON_ONLY = " (stop here: activation is a person's decision)"
AGENT_REFUSAL = "acceptance is a person's decision"  # the harness text (l4.yolo.accept.check)
THIS_DIR = Path(__file__).resolve().parent


class UsageError(Exception):
    """A usage error: exit 2."""


class Unsupported(Exception):
    """The configuration uses YAML that the small reader does not handle."""


# --- a bounded subprocess: its own process group, a deadline, no wait for a pipe that a helper holds open ----------


def run(argv: list[str], cwd: Path, timeout: float, env: dict[str, str] | None = None) -> tuple[int, str, str]:
    """(returncode, stdout, stderr). 124 and 'timed out' at the deadline; 127 when the program cannot start. Output is
    read until the child exits plus a short grace, never until a grandchild closes the pipe (the group is killed)."""
    try:
        proc = subprocess.Popen(  # noqa: S603
            argv, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True, close_fds=True,
        )  # fmt: skip
    except OSError as exc:
        return 127, "", str(exc)
    chunks: dict[int, list[bytes]] = {}
    sizes: dict[int, int] = {}
    selector = selectors.DefaultSelector()
    for stream in (proc.stdout, proc.stderr):
        assert stream is not None
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ)
        chunks[stream.fileno()], sizes[stream.fileno()] = [], 0
    out_fd, err_fd = proc.stdout.fileno(), proc.stderr.fileno()  # type: ignore[union-attr]
    started = time.monotonic()
    exited_at: float | None = None
    timed_out = False

    def kill() -> None:
        with contextlib.suppress(OSError):
            os.killpg(proc.pid, signal.SIGKILL)

    while True:
        now = time.monotonic()
        if exited_at is None and proc.poll() is not None:
            exited_at = now
        if exited_at is None:
            if now - started >= timeout:
                kill()
                timed_out = True  # only a child that is still running at the deadline timed out
                break
        else:
            if not selector.get_map():
                break
            if now - exited_at >= EOF_GRACE_S or now - started >= timeout:
                kill()
                break
        if not selector.get_map():
            time.sleep(0.05)
            continue
        for key, _ in selector.select(0.1):
            fd = key.fileobj.fileno()  # type: ignore[union-attr]
            try:
                data = os.read(fd, 65536)
            except BlockingIOError:
                continue
            except OSError:
                data = b""
            if not data:
                selector.unregister(key.fileobj)
                continue
            room = MAX_STREAM_BYTES - sizes[fd]
            if room > 0:
                chunks[fd].append(data[:room])
                sizes[fd] += min(len(data), room)
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=5)
    for stream in (proc.stdout, proc.stderr):
        with contextlib.suppress(OSError):
            stream.close()  # type: ignore[union-attr]
    selector.close()
    if timed_out:
        return 124, "", "timed out"
    decode = lambda fd: b"".join(chunks[fd]).decode("utf-8", "replace")  # noqa: E731
    return (proc.returncode if proc.returncode is not None else 124), decode(out_fd), decode(err_fd)


# --- the configuration: a small block-style reader (copied from validate_plan.py) ----------------------------------


def _strip_comment(value: str) -> str:
    value = value.strip()
    if value.startswith("#"):  # `key:   # note` with its block below: the note is not the key's value
        return ""
    if value[:1] in ("'", '"'):
        end = value.find(value[0], 1)
        while value[0] == '"' and end > 0 and value[end - 1] == "\\":
            end = value.find(value[0], end + 1)
        if end < 0:
            raise Unsupported("unterminated quote")
        rest = value[end + 1 :].strip()
        if rest and not rest.startswith("#"):
            raise Unsupported("text after a quoted value")
        return value[: end + 1]
    cut = value.find(" #")
    return (value[:cut] if cut >= 0 else value).strip()


def _scalar(text: str) -> object:
    text = _strip_comment(text)
    if not text:
        return None
    if text[0] in "&*!|>{%@`":
        raise Unsupported(f"unsupported value {text[:12]!r}")
    if text[0] in ("'", '"'):
        inner = text[1:-1]
        return inner.replace("''", "'") if text[0] == "'" else inner.replace('\\"', '"').replace("\\\\", "\\")
    if text.startswith("["):
        if not text.endswith("]"):
            raise Unsupported("a flow list over several lines")
        body = text[1:-1].strip()
        return [_scalar(item) for item in body.split(",")] if body else []
    return None if text in ("~", "null") else text


def _logical_lines(block: list[str]) -> list[tuple[int, str]]:
    lines = []
    for raw in block:
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise Unsupported("a tab in the indentation")
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append((len(raw) - len(raw.lstrip(" ")), stripped))
    return lines


def _parse_list(lines: list[tuple[int, str]], i: int, indent: int) -> tuple[list[object], int]:
    items: list[object] = []
    while i < len(lines) and lines[i][0] == indent and (lines[i][1] == "-" or lines[i][1].startswith("- ")):
        body = lines[i][1][1:].strip()
        if re.match(r"^[^'\"\[{]+:(\s|$)", body):
            raise Unsupported("a mapping inside a list")
        items.append(_scalar(body))
        i += 1
    return items, i


def _parse_map(lines: list[tuple[int, str]], i: int, indent: int) -> tuple[dict[str, object], int]:
    out: dict[str, object] = {}
    while i < len(lines) and lines[i][0] >= indent:
        ind, text = lines[i]
        if ind > indent:
            raise Unsupported("unexpected indentation")
        match = MAP_KEY.match(text)
        if not match:
            raise Unsupported(f"cannot read {text[:20]!r}")
        key, rest = next(g for g in match.groups()[:3] if g is not None), match.group(4)
        i += 1
        if rest is not None and _strip_comment(rest):
            out[key] = _scalar(rest)
        elif i < len(lines) and lines[i][0] > indent:
            if lines[i][1] == "-" or lines[i][1].startswith("- "):
                out[key], i = _parse_list(lines, i, lines[i][0])
            else:
                out[key], i = _parse_map(lines, i, lines[i][0])
        elif i < len(lines) and lines[i][0] == indent and (lines[i][1] == "-" or lines[i][1].startswith("- ")):
            out[key], i = _parse_list(lines, i, indent)  # YAML's own dumper puts a list at its key's indent
        else:
            out[key] = None
    return out, i


def _top_block(rows: list[str], key: str) -> tuple[dict[str, object], str | None]:
    """(the mapping under the top-level `key`, why it cannot be read or None). {} when the file has no such key."""
    key_row = r"""^(?:%s|"%s"|'%s')\s*:""" % ((re.escape(key),) * 3)
    start = next((n for n, row in enumerate(rows) if re.match(key_row + r"\s*(#.*)?$", row)), None)
    if start is None:
        if any(re.match(key_row, row) for row in rows):
            return {}, "is not in block style"
        return {}, None
    block = []
    for row in rows[start + 1 :]:
        if row.strip() and not row.startswith((" ", "\t", "#")):
            break
        block.append(row)
    try:
        lines = _logical_lines(block)
        return (_parse_map(lines, 0, lines[0][0])[0] if lines else {}), None
    except Unsupported as exc:
        return {}, f"is not block style ({exc})"


def config_rows(text: str | None) -> list[str] | None:
    return None if text is None else text.lstrip("\ufeff").splitlines()


def block(rows: list[str] | None, key: str) -> tuple[dict[str, object], str | None]:
    """(the mapping under the top-level `key`, why it cannot be read or None). {} when there is no such key."""
    if rows is None:
        return {}, "is missing"
    parsed, why = _top_block(rows, key)
    return parsed, why


def nested(mapping: dict[str, object], *keys: str) -> object:
    value: object = mapping
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


# --- plan, spec roots and unit folders ----------------------------------------------------------------------------


def unit_folder(unit_id: str, openspec_root: str, kiro_root: str) -> str:
    framework, _, name = unit_id.partition(":")
    return "/".join(
        [
            *Path(openspec_root if framework == "openspec" else kiro_root).parts,
            *(["changes"] if framework == "openspec" else []),
            name,
        ]
    )


def plan_units(doc: object) -> list[str]:
    ids: list[str] = []
    if isinstance(doc, dict):
        for batch in doc.get("batches") or []:
            for unit in (batch.get("units") or []) if isinstance(batch, dict) else []:
                if isinstance(unit, dict) and isinstance(unit.get("id"), str) and unit["id"] not in ids:
                    ids.append(unit["id"])
    return ids


# --- the words shared with the harness (staleness.py): D1 -------------------------------------------------------------


def commits(n: int) -> str:
    return f"{n} commit" if n == 1 else f"{n} commits"


def named(items: list[str]) -> str:
    shown = ", ".join(items[:MAX_NAMED])
    return f"{shown} and {len(items) - MAX_NAMED} more" if len(items) > MAX_NAMED else shown


def divergence_text(head: str, origin: str, ahead: int, behind: int, paths: list[str], base: str) -> str:
    if ahead and behind:
        text = (
            f"HEAD ({head[:7]}) and origin/{base} ({origin[:7]}) have diverged: {commits(ahead)} only on HEAD, "
            f"{behind} only on origin/{base}"
        )
    elif ahead:
        text = f"origin/{base} ({origin[:7]}) is {commits(ahead)} behind HEAD ({head[:7]})"
    else:
        text = f"origin/{base} ({origin[:7]}) is {commits(behind)} ahead of HEAD ({head[:7]})"
    return f"{text}; they differ in {named(paths)}" if paths else text


def divergence_fix(ahead: int, behind: int, base: str, then: str) -> str:
    if ahead and behind:
        return f"git pull --rebase, then git push origin HEAD:{base}, then {then}"
    if ahead:
        return f"git push origin HEAD:{base}, then {then}"
    return f"git pull --ff-only, then {then}"


def judge_role_message(name: str, role: str, adapter: str) -> str:
    """The text of `l4.config.schema.L4Config._judge_roles_can_judge`, without its ` at $`."""
    known = adapter if adapter in HARNESS_ADAPTERS else "(not one the harness knows)"
    return (
        f"profiles.{name} is in roles.{role}, but its adapter {known} cannot judge (a judge call has no tools): an "
        f"adapter profile in roles.judges, roles.verifier_agent, roles.clarifier or roles.s1_judge must use one of "
        f"{', '.join(JUDGE_ADAPTERS)}; remove {name} from roles.{role}"
    )


def stdin_is_tty() -> bool:
    try:
        return sys.stdin.isatty()
    except (OSError, ValueError):
        return False


def caller(environ: dict[str, str]) -> tuple[str, str | None]:
    """`l4.actor.actor`: a person is a terminal on stdin and no marker."""
    for marker in AGENT_MARKERS:
        if environ.get(marker):
            return "agent", marker
    return ("person", None) if stdin_is_tty() else ("agent", None)


# --- the checks ----------------------------------------------------------------------------------------------------


class Check:
    def __init__(self, name: str, result: str, detail: str = "", fix: str = "") -> None:
        self.name, self.result, self.detail, self.fix = name, result, detail, fix

    def as_json(self) -> dict[str, str]:
        return {"name": self.name, "result": self.result, "detail": self.detail, "fix": self.fix}


class Preflight:
    def __init__(self, plan: str, repo: Path, l4: list[str], fetch: bool, environ: dict[str, str]) -> None:
        self.plan, self.repo, self.l4, self.fetch, self.environ = plan, repo, l4, fetch, environ
        self.l4_text = " ".join(shlex.quote(p) for p in l4)
        self.checks: list[Check] = []
        self.plan_path = f".l4/plans/{plan}.json"
        self.doc: object = None
        self.config_text: str | None = None
        rel = repo / ".l4" / "config.yaml"
        try:
            self.config_text = rel.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            self.config_text = None
        self.rows = config_rows(self.config_text)
        self.openspec_root, self.kiro_root = DEFAULT_OPENSPEC_ROOT, DEFAULT_KIRO_ROOT
        self.base = "main"
        self.origin_sha = ""
        self.opencode_ok = False
        self.status: dict[str, object] | None = None
        self.who: tuple[str, str | None] = ("agent", None)

    # git and the harness
    def git(self, *args: str, timeout: float = GIT_TIMEOUT_S) -> tuple[int, str, str]:
        env = {**self.environ, "GIT_TERMINAL_PROMPT": "0"}
        return run(["git", *args], self.repo, timeout, env)

    def harness(self, *args: str) -> tuple[int, str, str]:
        return run([*self.l4, *args], self.repo, L4_TIMEOUT_S, self.environ)

    def add(self, name: str, result: str, detail: str = "", fix: str = "") -> Check:
        check = Check(name, result, detail, fix)
        self.checks.append(check)
        return check

    def failed(self) -> bool:
        return any(c.result == "FAIL" for c in self.checks)

    def command(self, *words: str) -> str:
        return " ".join([self.l4_text, *words])

    # the configuration
    def read_config(self) -> None:
        spec, why = block(self.rows, "spec")
        if why is None:
            for key, attr in (("openspec", "openspec_root"), ("kiro", "kiro_root")):
                root = nested(spec, key, "root")
                if isinstance(root, str) and root:
                    setattr(self, attr, root)
        forge, why = block(self.rows, "forge")
        branch = forge.get("base_branch") if why is None else None
        if isinstance(branch, str) and branch:
            self.base = branch
        elif isinstance(self.doc, dict) and isinstance(self.doc.get("target"), str) and self.doc["target"]:
            self.base = self.doc["target"]

    @property
    def target_ref(self) -> str:
        return f"refs/remotes/origin/{self.base}"

    def folders(self) -> list[str]:
        return [unit_folder(u, self.openspec_root, self.kiro_root) for u in plan_units(self.doc)]

    def profiles(self) -> dict[str, dict[str, object]]:
        parsed, why = block(self.rows, "profiles")
        if why is not None:
            return {}
        return {k: v for k, v in parsed.items() if isinstance(v, dict)}

    def role_chain(self, role: str) -> list[str]:
        roles, why = block(self.rows, "roles")
        chain = roles.get(role) if why is None else None
        return [str(n) for n in chain] if isinstance(chain, list) else []

    # 1
    def plan_file(self) -> None:
        path = self.repo / self.plan_path
        if not path.is_file():
            self.add("plan-file", "FAIL", f"{self.plan_path} does not exist", self.command("yolo", "draft", self.plan))
            return
        try:
            self.doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.add(
                "plan-file", "FAIL", f"{self.plan_path} is not JSON",
                f"python3 {THIS_DIR / 'validate_plan.py'}, and fix {self.plan_path}",
            )  # fmt: skip
            return
        self.add("plan-file", "ok", self.plan_path)

    # 2
    def clean_tree(self) -> None:
        code, out, err = self.git("status", "--porcelain=v1", "--untracked-files=all")
        if code != 0:
            self.add(
                "clean-tree",
                "FAIL",
                f"git status failed: {err.strip()[:120]}",
                "fix the repository, then run this script again",
            )
            return
        folders = self.folders()
        dirty = []
        for line in out.splitlines():
            if len(line) < 4:
                continue
            path = line[3:].split(" -> ")[-1].strip().strip('"')
            if not line.startswith("??") or path.startswith(".l4/") or any(path.startswith(f + "/") for f in folders):
                dirty.append(path)
        if dirty:
            self.add(
                "clean-tree", "FAIL", named(dirty),
                f"commit the changes git status lists, then git push origin HEAD:{self.base}",
            )  # fmt: skip
        else:
            self.add("clean-tree", "ok", "no change under the plan or its units")

    # 3
    def origin(self) -> None:
        code, _, _ = self.git("remote", "get-url", "origin")
        if code != 0:
            self.add("origin", "FAIL", "this repository has no origin", "git remote add origin <url>")
            return
        if self.fetch:
            spec = f"+refs/heads/{self.base}:{self.target_ref}"
            code, _, err = self.git("fetch", "--quiet", "origin", spec)
            if code != 0:
                self.add(
                    "origin", "FAIL", f"git fetch origin {self.base} failed: {err.strip()[:120]}",
                    f"git push -u origin {self.base}",
                )  # fmt: skip
                return
        code, out, _ = self.git("rev-parse", "--verify", "--quiet", f"{self.target_ref}^{{commit}}")
        if code != 0:
            self.add("origin", "FAIL", f"origin/{self.base} is not here", f"git push -u origin {self.base}")
            return
        self.origin_sha = out.strip()
        self.add("origin", "ok", f"origin/{self.base} {self.origin_sha[:7]}")

    # 4
    def head_is_origin(self) -> None:
        code, out, _ = self.git("rev-parse", "--verify", "--quiet", "HEAD^{commit}")
        head = out.strip()
        if code != 0:
            self.add("head-is-origin", "FAIL", "HEAD is not a commit", f"git push -u origin {self.base}")
            return
        if head == self.origin_sha:
            self.add("head-is-origin", "ok", f"HEAD is origin/{self.base} ({head[:7]})")
            return
        _, counts, _ = self.git("rev-list", "--left-right", "--count", f"{self.target_ref}...HEAD")
        try:
            behind, ahead = (int(n) for n in counts.split())
        except ValueError:
            behind, ahead = 0, 0
        differ = []
        for path in [self.plan_path, *self.folders()]:
            _, names, _ = self.git("diff", "--name-only", self.target_ref, "HEAD", "--", path)
            if names.strip():
                differ.append(path)
        self.add(
            "head-is-origin", "FAIL", divergence_text(head, self.origin_sha, ahead, behind, differ, self.base),
            divergence_fix(ahead, behind, self.base, "run this script again"),
        )  # fmt: skip

    # 5
    def on_origin(self) -> None:
        missing = []
        code, _, _ = self.git("cat-file", "-e", f"{self.target_ref}:{self.plan_path}")
        if code != 0:
            missing.append(self.plan_path)
        for folder in self.folders():
            _, listing, _ = self.git("ls-tree", self.target_ref, "--", folder)
            if not listing.strip():
                missing.append(folder)
        if missing:
            self.add(
                "on-origin", "FAIL", f"not on origin/{self.base}: {named(missing)}",
                f"commit and push {missing[0]}, then run this script again",
            )  # fmt: skip
        else:
            self.add("on-origin", "ok", "the plan file and the unit folders are on origin")

    # 6
    def judge_roles(self) -> None:
        if self.rows is None:
            self.add("judge-roles", "skip", "no .l4/config.yaml (l4 doctor checks it)")
            return
        profiles, why = block(self.rows, "profiles")
        if why is not None:
            self.add("judge-roles", "skip", f"profiles {why} (l4 doctor checks it)")
            return
        for role in JUDGE_ROLES:
            for name in self.role_chain(role):
                profile = profiles.get(name)
                adapter = profile.get("adapter") if isinstance(profile, dict) else None
                if isinstance(adapter, str) and adapter and adapter not in JUDGE_ADAPTERS:
                    self.add(
                        "judge-roles", "FAIL", judge_role_message(name, role, adapter),
                        f"remove {name} from roles.{role} in .l4/config.yaml, commit and push, then run this script "
                        "again",
                    )  # fmt: skip
                    return
        self.add("judge-roles", "ok", "every judge role holds adapters that can judge")

    # 7
    def opencode(self) -> None:
        profiles = self.profiles()
        used = any(
            isinstance(profiles.get(n), dict) and profiles[n].get("adapter") == "opencode"
            for role in ("implementer", *JUDGE_ROLES, "spec_writer")
            for n in self.role_chain(role)
        )
        if not used:
            self.add("opencode", "skip", "no opencode profile in a role")
            return
        if shutil.which("opencode", path=self.environ.get("PATH")) is None:
            self.add(
                "opencode", "skip",
                "not on PATH here: a local review cannot use an opencode judge; CI's runner needs it",
            )  # fmt: skip
            return
        code, out, err = run(["opencode", "--version"], self.repo, OPENCODE_TIMEOUT_S, self.environ)
        found = re.search(r"\d+\.\d+\.\d+", out + " " + err) if code != 124 else None
        if found is None:
            self.add("opencode", "FAIL", "opencode did not report a version", self.command("doctor"))
            return
        major = int(found.group(0).split(".")[0])
        if major != OPENCODE_MAJOR:
            self.add(
                "opencode", "FAIL",
                f"opencode {found.group(0)} is OpenCode v{major}; this profile runs v{OPENCODE_MAJOR} "
                f"(opencode-ai {OPENCODE_MAJOR}.x)",
                f"{self.command('doctor', '--fix')} (it installs opencode-ai@{OPENCODE_PIN} user-locally), then run this "
                "script again",
            )  # fmt: skip
            return
        self.opencode_ok = True
        self.add("opencode", "ok", f"opencode {found.group(0)}")

    # 8
    def accept_by_agents(self) -> None:
        text, rounds, flag = None, "2", "false"
        code, out, _ = self.git("show", f"{self.target_ref}:.l4/config.yaml")
        if code == 0:
            rows = config_rows(out)
            yolo, why = block(rows, "yolo")
            if why is None:
                review = yolo.get("review")
                if isinstance(review, dict):
                    if isinstance(review.get("accept_by_agents"), str):
                        flag = str(review["accept_by_agents"]).lower()
                    if isinstance(review.get("accept_after_rounds"), str):
                        rounds = str(review["accept_after_rounds"])
        text = f"accept_by_agents: {flag}, accept_after_rounds: {rounds} (at origin/{self.base})"
        self.accepting = flag == "true"
        self.add("accept-by-agents", "info", text)

    # 9
    def caller_check(self) -> None:
        self.who = caller(self.environ)
        kind, marker = self.who
        if kind == "person":
            self.add("caller", "info", "person")
        elif marker:
            self.add("caller", "info", f"agent ({marker})")
        else:
            self.add("caller", "info", "agent (stdin is not a terminal)")

    # 10 to 12
    def harness_checks(self) -> None:
        code, _, err = self.harness("--version")
        if code != 0:
            self.add(
                "harness", "FAIL", f"{self.l4_text} --version failed: {err.strip()[:100]}",
                "install the l4 harness (references/adopt.md), then run this script again",
            )  # fmt: skip
            return
        self.add("harness", "ok", f"{self.l4_text} --version")
        code, out, err = self.harness("yolo", "check", self.plan)
        if code != 0:
            first = next(
                (ln.strip() for ln in (out + "\n" + err).splitlines() if ln.strip() and not ln.startswith("[l4]")), ""
            )
            self.add(
                "admission", "FAIL", first[:200] or f"{self.command('yolo', 'check', self.plan)} exited {code}",
                f"{self.command('yolo', 'check', self.plan)}: fix what it prints, commit and push, then run this "
                "script again",
            )  # fmt: skip
            return
        self.add("admission", "ok", f"{self.command('yolo', 'check', self.plan)} exits 0")
        code, out, err = self.harness("yolo", "status", self.plan, "--json")
        try:
            doc = json.loads(out)
            plan = doc["plans"][0]
            assert isinstance(plan, dict)
        except (ValueError, KeyError, IndexError, AssertionError, TypeError):
            self.add(
                "review",
                "FAIL",
                f"{self.command('yolo', 'status', self.plan, '--json')} gave no status ({err.strip()[:80]})",
                f"{self.command('yolo', 'status', self.plan)}: read what it prints, then run this script again",
            )  # fmt: skip
            return
        self.status = plan
        review = plan.get("review") if isinstance(plan.get("review"), dict) else {}
        state = review.get("state", "none") if isinstance(review, dict) else "none"
        stale = review.get("stale") if isinstance(review, dict) else None
        detail = f"status {plan.get('status')}, review {state}"
        if state == "stale" and isinstance(stale, list) and stale:
            detail += f": {stale[0]}"
        self.add("review", "info", detail)

    def skip_harness(self) -> None:
        for name in ("harness", "admission", "review"):
            self.add(name, "skip", "after the failures above")

    def run_all(self) -> None:
        self.plan_file()
        self.read_config()
        self.clean_tree()
        self.origin()
        if self.origin_sha:
            self.head_is_origin()
            self.on_origin()
        else:
            self.add("head-is-origin", "skip", "origin is not usable")
            self.add("on-origin", "skip", "origin is not usable")
        self.judge_roles()
        self.opencode()
        if self.origin_sha:
            self.accept_by_agents()
        else:
            self.accepting = False
            self.add("accept-by-agents", "skip", "origin is not usable")
        self.caller_check()
        if self.failed():
            self.skip_harness()
        else:
            self.harness_checks()

    # --- the one Next line ---------------------------------------------------------------------------------------

    def judge_can_run(self) -> bool:
        chain = self.role_chain("judges")
        if not chain:
            return False
        profile = self.profiles().get(chain[0]) or {}
        adapter = profile.get("adapter")
        path = self.environ.get("PATH")
        if adapter == "claude-code":
            return shutil.which("claude", path=path) is not None
        if adapter == "opencode":
            return self.opencode_ok
        if adapter == "codex":
            return shutil.which("codex", path=path) is not None and shutil.which("bwrap", path=path) is not None
        return False

    def localize(self, text: str) -> str:
        """The harness prints `l4 <command>`; the person runs `--l4`."""
        if self.l4_text == "l4":
            return text
        return re.sub(r"(?<![\w/.-])l4 (?=[a-z])", lambda _: self.l4_text + " ", text)

    def hand_over(self, line: str) -> str:
        """A line that activates or forces is a person's step: an agent is told to stop (L4-SKL-005)."""
        if self.who[0] == "person":
            return line
        return f"a person runs: {line}{PERSON_ONLY}"

    def next_line(self) -> str:
        failure = next((c for c in self.checks if c.result == "FAIL"), None)
        if failure is not None:
            return failure.fix
        plan = self.status or {}
        status = plan.get("status")
        stop = plan.get("stop") if isinstance(plan.get("stop"), dict) else {}
        if status not in ("new", "refused", "admitted", "reviewed") and not (
            status == "stopped" and isinstance(stop, dict) and stop.get("reason") == "inputs_changed"
        ):
            line = self.localize(str(plan.get("next") or self.command("yolo", "status", self.plan)))
            return self.hand_over(line) if "yolo activate" in line or "--force" in line else line
        review = plan.get("review") if isinstance(plan.get("review"), dict) else {}
        state = review.get("state", "none") if isinstance(review, dict) else "none"
        problems = review.get("problems") if isinstance(review, dict) else None
        force = review.get("force_accepted") if isinstance(review, dict) else None
        if isinstance(force, dict) and force.get("covered") is True and not problems:
            return self.hand_over(f'{self.command("yolo", "activate", self.plan)} --reason "<why>"')  # no review needed
        if state in ("none", "stale"):
            if self.judge_can_run():
                return self.command("yolo", "review", self.plan, "--worktree", "--record")
            return (
                f"{self.command('yolo', 'review', self.plan)} (CI reviews origin/{self.base} at its next run; "
                "then run this script again)"
            )
        if state == "current" and not problems:
            return self.hand_over(f'{self.command("yolo", "activate", self.plan)} --reason "<why>"')
        return self.not_ready()

    def may_accept(self, item: dict[str, object], refusal: object) -> bool:
        """The findings run has no terminal, so the harness answers as an agent. A person may accept under the normal
        rules (the agent-only refusal does not apply); an agent only when `yolo.review.accept_by_agents` is true."""
        if self.who[0] == "person":
            only_agents = isinstance(refusal, dict) and refusal.get("why") == AGENT_REFUSAL
            return bool(item.get("accept_available")) or only_agents
        return bool(item.get("accept_available")) and self.accepting

    def not_ready(self) -> str:
        code, out, _ = self.harness("yolo", "findings", self.plan, "--json")
        findings = self.command("yolo", "findings", self.plan)
        try:
            subjects = json.loads(out)["subjects"]
        except (ValueError, KeyError, TypeError):
            return findings
        for item in subjects if isinstance(subjects, list) else []:
            if not isinstance(item, dict) or item.get("verdict") == "READY":
                continue
            accepted = item.get("accepted")
            if isinstance(accepted, dict) and accepted.get("holds"):
                continue
            subject = str(item.get("subject"))
            refusal = item.get("accept_refusal")
            if self.may_accept(item, refusal):
                yes = " --yes" if self.who[0] == "agent" else ""  # an agent has no terminal to confirm on
                return (
                    f'{self.command("yolo", "accept", self.plan, subject)} --reason "<what the implementer should do>"'
                    f"{yes}"
                )
            fix = self.localize(str(refusal.get("fix") or "")) if isinstance(refusal, dict) else ""
            if fix.startswith("a person runs:"):
                return f"{fix} (stop here)"
            if isinstance(refusal, dict) and item.get("persistent"):
                return (
                    f"a person decides {subject}: {self.command('yolo', 'findings', self.plan, subject)} (the finding "
                    "came back after a spec fix and cannot be accepted; stop here)"
                )
            return (
                f"{self.command('yolo', 'findings', self.plan, subject)}, fix the spec as its Resolve: lines say, "
                "commit and push, then run this script again"
            )
        return findings


def main(argv: list[str] | None = None, environ: dict[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="yolo_preflight.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("plan")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--no-fetch", action="store_true")
    parser.add_argument("--l4", default="l4")
    parser.add_argument("--json", action="store_true", dest="as_json")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code not in (0, None) else 0
    try:
        if not PLAN_ID.match(args.plan):
            raise UsageError(f"{args.plan!r} is not a plan id (lower-case letters, digits and '-')")
        repo = Path(args.repo).resolve()
        env = dict(os.environ if environ is None else environ)
        code, out, _ = (
            run(["git", "rev-parse", "--is-inside-work-tree"], repo, GIT_TIMEOUT_S, env)
            if repo.is_dir()
            else (1, "", "")
        )
        if code != 0 or out.strip() != "true":
            raise UsageError(f"{args.repo} is not a git work tree")
        try:
            l4 = shlex.split(args.l4)
        except ValueError as exc:
            raise UsageError(f"--l4: {exc}") from None
        if not l4:
            raise UsageError("--l4 is empty")
    except UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    pre = Preflight(args.plan, repo, l4, not args.no_fetch, env)
    pre.run_all()
    next_line = pre.next_line()
    exit_code = 1 if pre.failed() else 0
    if args.as_json:
        kind, marker = pre.who
        print(
            json.dumps(
                {
                    "schema": SCHEMA, "plan": args.plan, "base": pre.base, "caller": {"kind": kind, "marker": marker},
                    "checks": [c.as_json() for c in pre.checks], "next": next_line, "exit": exit_code,
                },
                indent=2,
            )
        )  # fmt: skip
    else:
        for c in pre.checks:
            print(f"{c.result:<5}  {c.name}: {c.detail}".rstrip())
        print(f"Next: {next_line}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
