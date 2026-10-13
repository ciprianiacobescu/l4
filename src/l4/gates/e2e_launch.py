"""The e2e launcher (M15-G4, D4): one process tree inside ONE gate spawn that serves the app, waits for it, runs the e2e
command against it and tears the server down. Stdlib only, started by `l4.gates.e2e.run_e2e` as
`<harness python> -I e2e_launch.py ...` under the gate sandbox.

The gate sandbox has `--unshare-net`, and every spawn gets its own network namespace: a separate "serve" spawn would
sit in another namespace than the tests. Here the server and the tests share the namespace's loopback.

Exit code: the e2e command's own, 97 when the server never became ready (including a server that exited early), or 96
when the e2e command cannot be started. In both cases `--not-ready` is written too, since the e2e command may exit 97
or 96 itself; once the command has run the launcher removes that file again, so only a launcher that never got to run
the command leaves it (the project's tests cannot forge it).
"""

import argparse
import contextlib
import os
import shlex
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

NOT_READY = 97
NO_COMMAND = 96
SNAPSHOT_LIMIT = 200 * 1024
POLL_INTERVAL_S = 0.2
STOP_GRACE_S = 5.0


def _ready(url: str) -> str:
    """ "" when the URL answers with a 2xx/3xx, else the reason."""
    try:
        with urllib.request.urlopen(url, timeout=2) as response:  # noqa: S310 - the harness's own ready_url
            return "" if 200 <= response.status < 400 else f"HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        return f"HTTP {exc.code}"
    except (OSError, ValueError) as exc:
        return type(exc).__name__


def _stop(server: subprocess.Popen[bytes]) -> None:
    if server.poll() is None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(server.pid, signal.SIGTERM)
        with contextlib.suppress(subprocess.TimeoutExpired):
            server.wait(STOP_GRACE_S)
    with contextlib.suppress(ProcessLookupError):  # children of the server that outlived it
        os.killpg(server.pid, signal.SIGKILL)
    server.wait()


def _snapshot(origin: str, target: Path) -> None:
    """`GET <origin>/` saved for the test writer (at most 200 KB); a failure only means there is no snapshot."""
    try:
        with urllib.request.urlopen(origin + "/", timeout=5) as response:  # noqa: S310
            body = response.read(SNAPSHOT_LIMIT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    except (OSError, ValueError):
        pass


def _mark(marker: Path, code: int) -> int:
    with contextlib.suppress(OSError):
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(code))
    return code


def _not_ready(marker: Path) -> int:
    return _mark(marker, NOT_READY)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="e2e_launch")
    parser.add_argument("--serve", required=True, help="the server command (split with shlex, no shell)")
    parser.add_argument("--ready-url", required=True)
    parser.add_argument("--timeout", type=float, required=True, help="seconds to wait for ready-url")
    parser.add_argument("--page", required=True, help="where to save GET <origin>/ (relative to the worktree)")
    parser.add_argument("--not-ready", required=True, help="marker file written when the server never got ready")
    parser.add_argument("--base-url-env", required=True, help="the variable the e2e command reads the origin from")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        print("e2e_launch: no e2e command", file=sys.stderr)
        return _not_ready(Path(args.not_ready))
    parts = urlsplit(args.ready_url)
    origin = f"{parts.scheme}://{parts.netloc}"
    private = os.environ.get("TMPDIR") or "/tmp"
    # the server may write; the gate's home is read-only
    server_env = {**os.environ, "HOME": private, "TMPDIR": private}
    try:
        server = subprocess.Popen(  # noqa: S603 - argv list, never a shell
            shlex.split(args.serve), env=server_env, stdin=subprocess.DEVNULL, start_new_session=True
        )
    except (OSError, ValueError) as exc:
        print(f"e2e_launch: cannot start the server ({type(exc).__name__})", file=sys.stderr)
        return _not_ready(Path(args.not_ready))
    ran = False
    try:
        deadline = time.monotonic() + args.timeout
        why = "not tried"
        while True:
            if server.poll() is not None:
                code = server.returncode
                print(f"e2e_launch: the server exited with code {code} before it was ready", file=sys.stderr)
                return _not_ready(Path(args.not_ready))
            why = _ready(args.ready_url)
            if not why:
                break
            if time.monotonic() >= deadline:
                print(f"e2e_launch: {args.ready_url} not ready within {args.timeout:.0f}s ({why})", file=sys.stderr)
                return _not_ready(Path(args.not_ready))
            time.sleep(POLL_INTERVAL_S)
        _snapshot(origin, Path(args.page))
        try:
            ran = True
            return subprocess.run(  # noqa: S603
                command, env={**os.environ, args.base_url_env: origin}, stdin=subprocess.DEVNULL
            ).returncode
        except OSError as exc:
            ran = False
            print(f"e2e_launch: cannot start the e2e command ({type(exc).__name__})", file=sys.stderr)
            return _mark(Path(args.not_ready), NO_COMMAND)
    finally:
        _stop(server)
        if ran:
            with contextlib.suppress(OSError):
                Path(args.not_ready).unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
