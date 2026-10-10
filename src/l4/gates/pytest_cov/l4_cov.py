"""`l4_cov`: the harness-owned coverage plugin, loaded with `-p l4_cov` into the verifier's own test run (M1.6, D4).

It runs inside the project's Python environment, so it imports only the standard library, pytest and the project's
own coverage.py, never `l4`. The harness writes the rc file (`l4.gates.coverage.write_rc`) and points `L4_COV_RC` at
it; the repository's `.coveragerc` / `pyproject.toml` are never read. Output, next to the rc file: `coverage.json`
(per-line data with the test function as context) and `status.json`.

Fail-soft by construction: nothing here may change a test outcome. When coverage cannot be measured (coverage.py is
missing, pytest-cov or xdist is active, a plugin error), `status.json` says `not_run` and why.
"""

import contextlib
import hashlib
import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any

import pytest

_active: dict[str, Any] = {}


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _write_status(out: Path, status: str, reason: str = "", **extra: Any) -> None:
    with contextlib.suppress(OSError):  # an unwritable output directory is reported by the harness as no status
        body = {"status": status, "reason": reason, "nonce": _active.get("nonce", ""), **extra}
        _atomic_write(out / "status.json", json.dumps(body))


def _abandon(reason: str) -> None:
    cov, out = _active.pop("cov", None), _active.get("out")
    if cov is not None:
        with contextlib.suppress(Exception):  # never raise into pytest
            cov.stop()
    if out is not None:
        _write_status(out, "not_run", reason)
    _active.clear()


def _hide_from_children() -> None:
    """A pytest process a test spawns inherits this environment; it must not load the plugin, or it would erase the
    parent's data file and status."""
    os.environ.pop("L4_COV_RC", None)
    os.environ.pop("L4_COV_NONCE", None)
    addopts = os.environ.get("PYTEST_ADDOPTS")
    if addopts is not None:
        kept = shlex.split(addopts)
        for i, tok in enumerate(kept):
            if tok == "-p" and kept[i + 1 : i + 2] == ["l4_cov"]:
                del kept[i : i + 2]
                break
        else:
            kept = [t for t in kept if t != "-pl4_cov"]
        os.environ["PYTEST_ADDOPTS"] = shlex.join(kept)


class _NotInstalled(Exception):
    """The `coverage` module found is not coverage.py from the interpreter's site directories."""


def _site_dirs() -> list[str]:
    import site

    found: list[str] = []
    with contextlib.suppress(Exception):
        found += site.getsitepackages()
    with contextlib.suppress(Exception):
        found.append(site.getusersitepackages())
    return [os.path.realpath(d) for d in found if d]


def _under(path: str, roots: list[str]) -> bool:
    return any(path == root or path.startswith(root.rstrip(os.sep) + os.sep) for root in roots)


def _installed_coverage() -> Any:
    """coverage.py from the interpreter's site-packages. The gate runs `python -m pytest` from the repository root, so
    the root (and an ini `pythonpath` such as `src`) come before site-packages on `sys.path`: a repository module
    named `coverage` would be imported instead and write whatever report it likes. For this one import every
    `sys.path` entry inside the working directory that is not a site directory is left out (a project `.venv` there
    stays), and a module that still does not come from a site directory is refused."""
    sites, cwd = _site_dirs(), os.path.realpath(os.getcwd())
    loaded = sys.modules.get("coverage")
    if loaded is None:
        saved = sys.path[:]
        sys.path[:] = [
            p for p in saved
            if _under(os.path.realpath(p or "."), sites) or not _under(os.path.realpath(p or "."), [cwd])
        ]  # fmt: skip
        try:
            import coverage as loaded
        finally:
            sys.path[:] = saved
    if not _under(os.path.realpath(getattr(loaded, "__file__", None) or "/"), sites):
        raise _NotInstalled
    return loaded


@pytest.hookimpl(tryfirst=True)
def pytest_load_initial_conftests(early_config: pytest.Config, parser: Any, args: list[str]) -> None:
    rc = os.environ.get("L4_COV_RC")
    if not rc or os.environ.get("PYTEST_XDIST_WORKER"):
        return  # not asked to measure, or an xdist worker (the controller reports `not_run`)
    out = Path(rc).parent
    _active["nonce"] = os.environ.get("L4_COV_NONCE", "")
    _hide_from_children()
    try:
        for name in ("status.json", "coverage.json"):
            (out / name).unlink(missing_ok=True)  # a result left by an earlier run must not pass for this one's
        _active["out"] = out
        if early_config.pluginmanager.hasplugin("pytest_cov") or any(a.startswith("--cov") for a in args):
            return _abandon("pytest-cov is active; two coverage measurements would corrupt each other")
        try:
            coverage = _installed_coverage()
        except _NotInstalled:
            return _abandon("the coverage module is not the installed coverage.py (a repository module shadows it)")
        except Exception:  # noqa: BLE001 - ImportError, or whatever a broken install raises
            return _abandon("coverage.py is not importable in the project environment")
        cov = coverage.Coverage(config_file=rc)
        cov.erase()
        cov.start()
        _active.update(cov=cov, version=coverage.__version__)
    except Exception as exc:  # noqa: BLE001
        _abandon(f"plugin error at start ({type(exc).__name__})")


def pytest_configure(config: pytest.Config) -> None:
    if "cov" in _active and (
        getattr(config.option, "numprocesses", None) or getattr(config.option, "dist", "no") != "no"
    ):
        _abandon("pytest-xdist workers are running; coverage across processes is not measured")


@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config: pytest.Config) -> None:
    cov = _active.get("cov")
    if cov is None:
        return
    out: Path = _active["out"]
    try:
        cov.stop()
        cov.save()
        target = out / "coverage.json"
        cov.json_report(outfile=str(target), ignore_errors=True)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        _write_status(out, "ok", coverage_version=_active["version"], json_sha256=digest)
    except Exception as exc:  # noqa: BLE001
        (out / "coverage.json").unlink(missing_ok=True)
        _write_status(out, "not_run", f"plugin error at report ({type(exc).__name__})")
    _active.clear()
