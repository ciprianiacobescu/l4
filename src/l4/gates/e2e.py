"""`gates.e2e` (SPEC L4-GAT, M15-G4): serve the app and run the browser tests in ONE gate spawn.

`run_e2e` builds the command line of the stdlib launcher `e2e_launch.py` (server, readiness poll, page snapshot, e2e
command, teardown), and runs it as an ordinary gate with `--unshare-net`: the server and the tests share the sandbox's
loopback, and no network reaches them. It works on any worktree of the repository, so the verifier can serve the
merge-base app and the head app one after the other (D3).

Reports are JUnit only (pytest-playwright); a server that never gets ready is an internal error (L4-VER-010), not a
test failure. The launcher says so by exit code 97 AND a marker file, because 97 is also a legal exit code of the
project's own e2e command; the launcher removes the marker once that command has run, so the tests cannot forge it.
96 with the same marker means the command could not be started: a usage error. Both files are written inside a tree
that agent code writes to: they are read without following symlinks, and the snapshot comes back as text, never as a
path.
M1: implementer-tdd-loop's other report formats (`playwright-json`).
"""

import shlex
import sys
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from l4.config.schema import E2eGate, L4Config, duration_seconds
from l4.exitcodes import ExitCode, L4Exit
from l4.fsutil import UnsafeFile, read_regular_file, reject_symlinks
from l4.gates import e2e_launch
from l4.gates.junit import TestReport
from l4.gates.runner import GateResult, GateSpec
from l4.implementer.workbench import Workbench

NOT_READY = e2e_launch.NOT_READY
NO_COMMAND = e2e_launch.NO_COMMAND
SNAPSHOT_RELPATH = ".l4-out/e2e/page.html"
NOT_READY_RELPATH = ".l4-out/e2e/not-ready"
SNAPSHOT_LIMIT = e2e_launch.SNAPSHOT_LIMIT
E2E_TEST_DIR = "e2e"  # where the harness writes generated tests (`testwriter.test_path`) and the default for the prompt
# pytest options that take a value in the next word, so that the word is not read as a test path
_PYTEST_VALUE_OPTIONS = frozenset({
    "-p", "-k", "-m", "-c", "-o", "-n", "-r", "-W", "--browser", "--output", "--junitxml", "--tracing", "--screenshot",
    "--video", "--base-url", "--rootdir", "--confcutdir", "--maxfail", "--durations", "--device",
})  # fmt: skip


class ServerNotReady(L4Exit):
    """The server never became ready: exit 1, unless the caller can tell it is about the tree (step 5 at the base)."""

    def __init__(self, message: str) -> None:
        super().__init__(ExitCode.INTERNAL_ERROR, message)


@dataclass(frozen=True)
class E2eRun:
    """`gate.report` is parsed whenever the report is readable, whatever the exit code, so that a test that fails is
    told apart from a run that did not happen. `snapshot_text` is `GET <origin>/` saved by the launcher,
    if it was served (decoded leniently: it is page content, not ours)."""

    gate: GateResult
    snapshot_text: str | None

    @property
    def report(self) -> TestReport | None:
        return self.gate.report


def e2e_configured(cfg: L4Config) -> bool:
    gate = cfg.gates.e2e
    return bool(gate.command.strip() and gate.serve.command.strip() and gate.serve.ready_url.strip())


def e2e_test_dir(gate: E2eGate, tree: Path | None = None) -> str:
    """The directory the e2e command runs its tests from: the first path word after `pytest` that is a relative
    directory inside `tree` (when given), else `E2E_TEST_DIR`. The implementer's red prompt names it (live M1.5 P3:
    a browser test written under `tests/` lost a red attempt)."""
    try:
        words = shlex.split(gate.command)
    except ValueError:
        return E2E_TEST_DIR
    start = next((i for i, w in enumerate(words) if PurePosixPath(w).name == "pytest"), None)
    skip = False
    for word in words[start + 1 :] if start is not None else ():
        if skip:
            skip = False
        elif word.startswith("-"):
            skip = word in _PYTEST_VALUE_OPTIONS
        else:
            path = PurePosixPath(word)
            ok = not path.is_absolute() and ".." not in path.parts and word not in (".", "")
            if ok and "::" not in word and (tree is None or (tree / path).is_dir()):
                return path.as_posix()
    return E2E_TEST_DIR


def _refuse(message: str) -> L4Exit:
    return L4Exit(ExitCode.USAGE_ERROR, f"gates.e2e: {message}")


def launcher_command(gate: E2eGate, base_url_env: str) -> str:
    """The gate command: the harness's own interpreter, isolated (`-I`), runs the launcher."""
    return shlex.join([
        sys.executable, "-I", e2e_launch.__file__,
        "--serve", gate.serve.command, "--ready-url", gate.serve.ready_url,
        "--timeout", str(duration_seconds(gate.serve.timeout)), "--page", SNAPSHOT_RELPATH,
        "--not-ready", NOT_READY_RELPATH,
        "--base-url-env", base_url_env, "--", *shlex.split(gate.command),
    ])  # fmt: skip


def run_gate_at(wb: Workbench, tree: Path, spec: GateSpec, *, network: bool) -> GateResult:
    """`Workbench.run_gate` for another worktree of the repository (the merge-base checkout): the very same wrapper."""
    return wb.run_gate_spec(spec, network=network, tree=tree)


def _read(tree: Path, relpath: str, *, limit: int) -> str | None:
    """The file's text, or None when it is absent, a symlink, not a regular file or too large (the tests of the gate
    ran in this tree and could have swapped it for a link to a host file)."""
    try:
        reject_symlinks(tree, *relpath.split("/"))
        return read_regular_file(tree / relpath, limit=limit).decode("utf-8", errors="replace")
    except (UnsafeFile, OSError):
        return None


def run_e2e(
    wb: Workbench, worktree: Path | None = None, *, name: str = "e2e", must_contain: Collection[str] = ()
) -> E2eRun:
    """Serve and test `worktree` (default: the unit's own). The result is `E2eRun`; a server that never gets ready
    raises `L4Exit(INTERNAL_ERROR)`. `must_contain`: test ids the report has to hold, or the gate fails (a generated
    test that did not run must not pass for one that did)."""
    cfg = wb.cfg
    gate = cfg.gates.e2e
    tree = wb.worktree if worktree is None else worktree
    if not e2e_configured(cfg):
        raise _refuse("command, serve.command and serve.ready_url must all be set")
    if not gate.reports:
        raise _refuse("reports must name the JUnit file, or the run could not be judged")
    if gate.format != "junit":
        raise _refuse(f"format {gate.format} is not supported yet (only junit)")
    try:
        command = launcher_command(gate, cfg.verifier.playwright.base_url_env)
    except ValueError:
        raise _refuse("serve.command or command cannot be parsed") from None
    spec = GateSpec(
        name, command, tuple(gate.reports), "junit", duration_seconds(cfg.gates.timeout), frozenset(must_contain)
    )  # fmt: skip
    try:
        reject_symlinks(tree, ".l4-out", "e2e")  # an `unlink` follows symlinked parents
    except UnsafeFile as exc:
        raise L4Exit(ExitCode.INTERNAL_ERROR, f"gates.e2e: {exc}") from None
    for relpath in (SNAPSHOT_RELPATH, NOT_READY_RELPATH):  # files of an earlier run must not pass for this run's
        (tree / relpath).unlink(missing_ok=True)
    result = run_gate_at(wb, tree, spec, network=False)
    marker = _read(tree, NOT_READY_RELPATH, limit=64)
    if result.exit_code == NOT_READY and marker == str(NOT_READY):
        raise ServerNotReady(f"gates.e2e: the server was not ready (see {result.log_path.name})")
    if result.exit_code == NO_COMMAND and marker == str(NO_COMMAND):
        raise _refuse(f"command cannot be started (see {result.log_path.name})")
    return E2eRun(result, _read(tree, SNAPSHOT_RELPATH, limit=SNAPSHOT_LIMIT))
