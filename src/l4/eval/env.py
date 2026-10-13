"""What a scorecard records of the environment it was measured in (L4-EVAL-012, handbook section 38): the harness
commit, every prompt template and its hash, the CLI versions of the profiles used, the profiles' models, vendors and
options, the seed set, k, the cell timeout and the machine class. Secrets never enter: option keys that name a
credential are dropped and every string goes through the redactor (no value of an environment variable is kept).
"""

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any

from l4 import buildinfo, recordedversions, templatelock
from l4.config.defaults import OPENSPEC_PACKAGE, openspec_prefix
from l4.provision.catalog import ADAPTER_BINARIES
from l4.redact import Redactor
from l4.versions import parse_version

_SECRET_KEY = re.compile(r"key|token|secret|password|passwd|credential", re.I)
_ENV_NAME_KEY = re.compile(r"_env$")  # `api_key_env` names a variable (public); the value is never read here


def _clean(value: Any, redactor: Redactor) -> Any:
    if isinstance(value, Mapping):
        return {
            str(k): _clean(v, redactor) for k, v in value.items()
            if _ENV_NAME_KEY.search(str(k)) or not _SECRET_KEY.search(str(k))
        }  # fmt: skip
    if isinstance(value, list | tuple):
        return [_clean(v, redactor) for v in value]
    if isinstance(value, str):
        return redactor.redact_text(value)
    return value


def _git(cwd: Path, *args: str) -> str | None:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "GIT_CONFIG_NOSYSTEM": "1"}
    try:
        done = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def harness_record(harness_dir: Path, vendored_commit: Callable[[], str | None]) -> dict[str, Any]:
    head = _git(harness_dir, "rev-parse", "HEAD") if (harness_dir / ".git").exists() else None
    if head:
        # tracked changes only: an eval's own `--out` inside the checkout is not a change of the harness
        dirty = bool(_git(harness_dir, "status", "--porcelain", "--untracked-files=no"))
        return {"commit": head, "dirty": dirty, "source": "git"}
    vendored = vendored_commit()
    return {"commit": vendored, "dirty": None, "source": "vendored" if vendored else "unknown"}


def cli_version(adapter: str) -> str | None:
    """What `<binary> --version` of the adapter's CLI prints; None when the binary is absent or does not run."""
    binary = ADAPTER_BINARIES.get(adapter)
    exe = shutil.which(binary) if binary else None
    if exe is None:
        return None
    try:
        done = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout or None


def _run_text(argv: list[str]) -> str | None:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def tool_versions(
    environ: Mapping[str, str], *, run: Callable[[list[str]], str | None] = _run_text
) -> dict[str, str | None]:
    """The versions of the two tools every cell uses besides the agent CLIs: uv (`uv sync --frozen --offline` in the
    setup gate) and the OpenSpec package the harness reads units with (its `package.json`, no node call). None when
    absent or unreadable."""
    parsed = parse_version(run(["uv", "--version"]) or "")
    package = openspec_prefix(environ) / "node_modules" / OPENSPEC_PACKAGE / "package.json"
    try:
        openspec = json.loads(package.read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError, AttributeError):
        openspec = None
    return {
        "uv": ".".join(map(str, parsed)) if parsed else None,
        "openspec": openspec if isinstance(openspec, str) else None,
    }


def capture_env(
    *, harness_dir: Path, profiles: Mapping[str, Mapping[str, Any]], used: Sequence[str], seed_set_sha256: str, k: int,
    cell_timeout_s: float, runner: bool, redactor: Redactor,
    version_of: Callable[[str], str | None] = cli_version,
    vendored_commit: Callable[[], str | None] = buildinfo.harness_commit,
    recorded: dict[str, list[str]] | None = None, now: str | None = None,
    tools: Mapping[str, str | None] | None = None, kept: Mapping[str, Any] | None = None,
) -> dict[str, Any]:  # fmt: skip
    """`tools`: uv and OpenSpec versions (`tool_versions`); `kept`: the sections of `--config` a cell keeps besides
    the profiles (`cellconfig.KEPT_SECTIONS`), recorded without credential keys."""
    lock_text = resources.files("l4").joinpath(templatelock.LOCK_NAME).read_text(encoding="utf-8")
    cli: dict[str, Any] = {}
    shown_profiles: dict[str, Any] = {}
    for name in sorted(set(used)):
        profile = profiles.get(name, {})
        adapter = str(profile.get("adapter") or "")
        parsed = parse_version(version_of(adapter) or "") if adapter else None
        version = ".".join(map(str, parsed)) if parsed else None
        unrecorded = None if version is None else recordedversions.unrecorded(adapter, version, recorded) is not None
        cli[name] = {"adapter": adapter, "version": version, "unrecorded": unrecorded}
        shown = ("adapter", "model", "vendor", "auth", "options")
        shown_profiles[name] = _clean(
            {key: profile[key] for key in shown if profile.get(key) is not None},
            redactor,
        )  # fmt: skip
    return {
        "started_at": now or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "harness": harness_record(harness_dir, vendored_commit),
        "templates": _clean(templatelock.current(), redactor),
        "templates_lock_sha256": hashlib.sha256(lock_text.encode("utf-8")).hexdigest(),
        "cli_versions": cli,
        "tools": dict(tools or {}),
        "profiles": shown_profiles,
        "cell_config": _clean(dict(kept or {}), redactor),
        "seed_set_sha256": seed_set_sha256,
        "k": k,
        "cell_timeout_s": cell_timeout_s,
        "machine": {"platform": platform.platform(), "cpus": os.cpu_count() or 1, "runner": runner},
        "python": ".".join(map(str, sys.version_info[:3])),
    }
