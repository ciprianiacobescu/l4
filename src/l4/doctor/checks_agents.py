"""LIVE-001 (SPEC L4-AVL-001, reduced): the first profile of the implementer and judge chains passes binary, auth and
hello. Runs only with `l4 doctor --live` because hello spends a few tokens. ENV-004 (binary of every profile) is
bootstrap-core's and is not registered here. M1: agent-factory 1.26 (`command`/`acp` rows), LIVE-002."""

import contextlib
import json
import re
import sqlite3
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from l4 import recordedversions
from l4.agents.base import ProbeCtx
from l4.agents.factory import Factory
from l4.availability.steps import SLOW_STEP_MS
from l4.delegate.independence import DELEGATE_SERVES
from l4.doctor.checks_env import version_env
from l4.doctor.context import DoctorContext
from l4.doctor.registry import Check, CheckResult, register
from l4.exitcodes import ExitCode, L4Exit
from l4.forge.base import forge_platform
from l4.forge.urls import origin_url
from l4.proc import run_process
from l4.provision.catalog import (
    ADAPTER_BINARIES,
    SUPPORTED_MAJORS,
    adapters_in_use,
    gate_pin,
    major_problem,
    profile_cli,
)

LIVE_ROLES = ("implementer", "judges")


@contextmanager
def scratch_dir(repo: Path) -> Iterator[str]:
    """An empty directory outside any checkout: a probe must not read or write the repository."""
    with tempfile.TemporaryDirectory(prefix="l4-probe-") as name:
        if repo.resolve() in Path(name).resolve().parents:
            raise L4Exit(
                ExitCode.USAGE_ERROR, "the system temp directory is inside the repository; set TMPDIR elsewhere"
            )
        yield name


def _live_001(ctx: DoctorContext) -> CheckResult:
    lines: list[str] = []
    failures: list[str] = []
    optional: list[str] = []  # the delegate is an optional role (L4-AVL-010): its failure is a warning
    roles = (*LIVE_ROLES, *(("delegate",) if ctx.cfg.delegate.enabled else ()))
    with scratch_dir(ctx.repo) as scratch:
        probe_ctx = ProbeCtx(environ=ctx.env, cwd=Path(scratch), run=run_process, forbid=(ctx.repo,))
        factory = Factory(ctx.cfg, probe_ctx)
        for role in roles:
            try:
                picked = factory.for_role(role, "doctor", serves=DELEGATE_SERVES if role == "delegate" else None)
            except L4Exit as exc:
                (optional if role == "delegate" else failures).append(str(exc))
                continue
            hello = picked.probes.get("hello", {}).get("ms")
            slow = [  # a step of a second or more, so the next slow step is visible
                f"{step} {detail['step_ms']} ms"
                for step, detail in picked.probes.items()
                if step != "hello" and isinstance(detail.get("step_ms"), int) and detail["step_ms"] >= SLOW_STEP_MS
            ]
            shown = [f"hello {hello} ms"] if hello is not None else []
            lines.append(
                f"{role}: {picked.profile_name} ok" + (f" ({'; '.join([*shown, *slow])})" if shown or slow else "")
            )
    hint = "log in or install the CLI as the runner user (docs/runner/README.md)"
    if failures:
        return CheckResult("fail", "; ".join([*failures, *optional]), hint)
    if optional:  # only the delegate failed: it escalates to a person, so the run is not blocked
        return CheckResult("fail", "; ".join([*lines, *optional]), hint, severity="warn")
    return CheckResult("pass", "; ".join(lines))


LIVE_001 = register(Check("LIVE-001", "Implementer and judge profiles answer", "error", _live_001, frozenset({"live"})))


_VERSION = re.compile(r"\d+\.\d+\.\d+")


def _live_005(ctx: DoctorContext) -> CheckResult:
    """HB-17 (SPEC L4-FAC-007): the CLI of every profile in the implementer and judge chains has recorded contract
    fixtures at its installed version. A newer patch version is not refused (its output may still parse); it is
    reported with both versions, so a format drift is looked for before it costs a run. A CLI of another major than
    the adapter supports (`opencode` v2, L4-OCG-001) is an error naming the reason, checked before and instead of the
    recorded-version comparison. Reads `--version` only."""
    unrecorded: list[str] = []
    wrong_major: list[str] = []
    checked: set[str] = set()
    for role in (*LIVE_ROLES, *(("delegate",) if ctx.cfg.delegate.enabled else ())):
        for name in getattr(ctx.cfg.roles, role):
            profile = ctx.cfg.profiles.get(name)
            if name in checked or profile is None or profile.adapter not in ADAPTER_BINARIES:
                continue
            checked.add(name)
            key, binary = profile_cli(profile)  # a cli_major: 2 profile runs opencode2 and is gated by its own key
            exe = ctx.which(binary)
            text = ctx.run([exe, "--version"], env=version_env(ctx, binary)).stdout if exe else ""
            found = _VERSION.search(text)
            if found is None:
                continue  # a missing or unreadable binary is ENV-004's finding
            # a wrong major is a misconfiguration, never a newer patch
            if key in SUPPORTED_MAJORS and (why := major_problem(key, binary, text, gate_pin(ctx.cfg, key))):
                wrong_major.append(f"profile `{name}`: {why}")
                continue
            known = recordedversions.unrecorded(profile.adapter, found.group(0))
            if known is not None:
                unrecorded.append(
                    f"unrecorded version: profile `{name}` ({profile.adapter}) runs {found.group(0)}, "
                    f"fixtures are recorded for {', '.join(known)}"
                )
    if wrong_major:
        return CheckResult(
            "fail", "; ".join([*wrong_major, *unrecorded]),
            "`l4 doctor --fix` installs the pinned version user-locally (L4-OCG-004); a Kiro CLI of another major: "
            "`l4 doctor --ci --fix` in CI, the command `l4 doctor` prints on this machine (L4-OCG-005)",
            severity="error",
        )  # fmt: skip
    if unrecorded:
        return CheckResult(
            "fail", "; ".join(unrecorded),
            "re-record with the spikes' recorder and add the version directory under tests/fixtures/recorded/",
            severity="warn",
        )  # fmt: skip
    return CheckResult("pass", f"{len(checked)} profile(s) at a recorded version")


LIVE_005 = register(Check("LIVE-005", "CLI versions have recorded fixtures", "warn", _live_005, frozenset({"live"})))


RUNNER_USER = "gitlab-runner"
# a login shell (`-i`): the runner user's PATH finds a CLI installed in its own ~/.local/bin, which sudo's would not
RELOGIN_COMMAND = {
    "claude-code": "claude, then type /login",
    "codex": "codex login --device-auth",
    "kiro-cli": "kiro-cli login",
}
# GitHub's runner service has no fixed user name (L4-GHP-009): the hint names the user it runs as
GITHUB_RUNNER_USER = "<the user the runner service runs as>"


def relogin(adapter: str, platform: str = "gitlab") -> str:
    user = GITHUB_RUNNER_USER if platform == "github" else RUNNER_USER
    return f"sudo -iu {user} {RELOGIN_COMMAND[adapter]}"


RELOGIN = {adapter: relogin(adapter) for adapter in RELOGIN_COMMAND}


def _json_file(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _claude_wiped(env: Mapping[str, str], home: Path) -> str | None:
    if env.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return None  # the CLI uses the static token, not the stored login
    folder = Path(env["CLAUDE_CONFIG_DIR"]) if env.get("CLAUDE_CONFIG_DIR") else home / ".claude"
    oauth = (_json_file(folder / ".credentials.json") or {}).get("claudeAiOauth")
    if not isinstance(oauth, dict):
        return None
    if not oauth.get("refreshToken"):
        return "refreshToken empty"
    if oauth.get("expiresAt") == 0:
        return "expiresAt 0"
    return None


def _codex_wiped(env: Mapping[str, str], home: Path) -> str | None:
    folder = Path(env["CODEX_HOME"]) if env.get("CODEX_HOME") else home / ".codex"
    auth = _json_file(folder / "auth.json")
    if auth is None or auth.get("auth_mode") != "chatgpt":
        return None  # no login, or an API key: nothing refreshes
    tokens = auth.get("tokens")
    if isinstance(tokens, dict) and not tokens.get("refresh_token"):
        return "refresh_token empty"
    return None


KIRO_STORES = (".local/share/kiro-cli/data.sqlite3", "Library/Application Support/kiro-cli/data.sqlite3")


def _kiro_wiped(env: Mapping[str, str], home: Path) -> str | None:
    """`auth_kv` rows that are JSON objects with a `refresh_token` key: one that is empty means a wiped login [I]."""
    for relative in KIRO_STORES:
        store = home / relative
        if not store.is_file():
            continue
        try:
            with contextlib.closing(sqlite3.connect(f"file:{store}?mode=ro", uri=True, timeout=2)) as db:
                rows = db.execute("select value from auth_kv").fetchall()
        except sqlite3.Error:
            continue
        for (value,) in rows:
            try:
                entry = json.loads(value)
            except (TypeError, ValueError):
                continue
            if isinstance(entry, dict) and "refresh_token" in entry and not entry["refresh_token"]:
                return "refresh_token empty"
    return None


_WIPED = {"claude-code": _claude_wiped, "codex": _codex_wiped, "kiro-cli": _kiro_wiped}


def _env_014(ctx: DoctorContext) -> CheckResult:
    """ENV-014 (SPEC L4-FAC-008): a stored OAuth login that was cleared (two processes refreshed the same single-use
    refresh token and the loser wrote empty credentials: runner incident 2026-10-07). Reads the credential store of
    each subscription profile in a role chain for emptiness only; nothing is printed from it and nothing is sent."""
    home = Path(ctx.env["HOME"]) if ctx.env.get("HOME") else Path.home()
    platform = forge_platform(ctx.cfg, ctx.env, origin_url(ctx.repo, ctx.env))
    found: list[str] = []
    hints: list[str] = []
    for adapter, names in adapters_in_use(ctx.cfg).items():
        detect = _WIPED.get(adapter)
        for name in names:
            profile = ctx.cfg.profiles[name]
            if detect is None or profile.auth == "api_key":
                continue
            if (why := detect(ctx.env, home)) is not None:
                found.append(f"profile `{name}` ({adapter}): the stored login looks wiped ({why})")
                hints.append(relogin(adapter, platform))
    if not found:
        return CheckResult("pass", "no stored login looks wiped")
    return CheckResult("fail", "; ".join(found), " | ".join(dict.fromkeys(hints)), severity="warn")


ENV_014 = register(Check("ENV-014", "A stored agent login looks wiped", "warn", _env_014))
