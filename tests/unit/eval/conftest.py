from pathlib import Path

import pytest

SEEDS = Path(__file__).resolve().parents[2] / "eval" / "seeds"


@pytest.fixture
def seeds_root() -> Path:
    return SEEDS


MKVENV = (
    "import os, stat, sys\n"
    "os.makedirs('.venv/bin', exist_ok=True)\n"
    "open('.venv/bin/python', 'w').write('#!/bin/sh\\nexec %s \"$@\"\\n' % sys.argv[1])\n"
    "os.chmod('.venv/bin/python', 0o755)\n"
)  # stands in for `uv sync --frozen --offline`: a venv launcher for the interpreter that runs the tests


@pytest.fixture
def setup_command(tmp_path: Path) -> str:
    import sys

    script = tmp_path / "mkvenv.py"
    script.write_text(MKVENV)
    return f"{sys.executable} {script} {sys.executable}"


@pytest.fixture
def profiles_file(tmp_path: Path) -> Path:
    import yaml

    path = tmp_path / "profiles.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "profiles": {
                    "p1": {"adapter": "opencode", "model": "opencode/a", "vendor": "acme"},
                    "p2": {"adapter": "opencode", "model": "opencode/b", "vendor": "beta"},
                    "j1": {"adapter": "claude-code", "vendor": "anthropic"},
                    "j2": {"adapter": "opencode", "model": "opencode/c", "vendor": "gamma"},
                },
            }
        )
    )
    return path


@pytest.fixture
def make_app(tmp_path: Path, profiles_file: Path):
    from l4.context import AppContext
    from l4.redact import Redactor

    def make(environ: dict[str, str] | None = None, config: Path | None = profiles_file) -> AppContext:
        repo = tmp_path / "harness-repo"
        repo.mkdir(exist_ok=True)
        env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(tmp_path / "home"), **(environ or {})}
        return AppContext(
            repo=repo, config_path=config, log_format="human", verbosity=0, run_id="r-20261007T1200Z-abcd",
            environ=env, redactor=Redactor({}),
        )  # fmt: skip

    return make


@pytest.fixture
def no_sockets(monkeypatch: pytest.MonkeyPatch):
    """Any attempt of this process to open a socket fails the test (the harness opens none in `l4 eval`)."""
    import socket

    opened: list[tuple] = []

    class Denied(socket.socket):
        def __init__(self, *args, **kwargs):
            opened.append(args)
            raise AssertionError("l4 eval opened a socket")

    monkeypatch.setattr(socket, "socket", Denied)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: (_ for _ in ()).throw(AssertionError("socket")))
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: (_ for _ in ()).throw(AssertionError("dns")))
    return opened


from ..doctor.conftest import make_ctx  # noqa: E402, F401  (the doctor tests' context fixture)
