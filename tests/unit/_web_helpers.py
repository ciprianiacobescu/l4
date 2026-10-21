"""The fixture web app and its serve wrapper, staged into a worktree: shared by the gate and the verifier tests."""

import shutil
import socket
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "fixtures" / "web"
PY = sys.executable
PYTEST = f"{PY} -m pytest -q -p no:cacheprovider -o junit_family=xunit1 --junitxml=.l4-out/e2e.xml e2e"
# starts the fixture app but first records its pid and starts a child in the same process group (the server's helper)
SERVE = """import os, runpy, subprocess, sys
os.makedirs(".l4-out", exist_ok=True)
open(".l4-out/serve.pid", "w").write(str(os.getpid()))
child = subprocess.Popen(  # ignores SIGTERM: only the final SIGKILL to the group can stop it
    [sys.executable, "-c", "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(120)"]
)
open(".l4-out/child.pid", "w").write(str(child.pid))
sys.argv = ["app.py", sys.argv[1]]
runpy.run_path("app.py", run_name="__main__")
"""


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def e2e_config(port: int, **serve: object) -> dict:
    return {
        "command": PYTEST, "reports": [".l4-out/e2e.xml"], "format": "junit",
        "serve": {
            "command": f"{PY} serve.py {port}", "ready_url": f"http://127.0.0.1:{port}/", "timeout": "20s", **serve,
        },
    }  # fmt: skip


def stage(root: Path) -> None:
    """The fixture web app, its smoke test and the serve wrapper, copied into a worktree."""
    shutil.copytree(WEB, root, dirs_exist_ok=True)
    (root / "serve.py").write_text(SERVE)
