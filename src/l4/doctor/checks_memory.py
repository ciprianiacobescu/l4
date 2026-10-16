"""MEM-001 and ENV-006..008 (reduced): the optional parts of M1.5, all warnings (they degrade, never block a run).
ENV-008 covers Serena's pinned version; gitleaks stays with its own check. Registered at import.
M1: bootstrap-core 2.16 (the gitleaks half of ENV-008)."""

import re
from pathlib import Path

from l4.config.defaults import LAYA_VERSION, PLAYWRIGHT_VERSION, cache_root
from l4.doctor.context import DoctorContext
from l4.doctor.registry import CONFIG_SCOPES, DEFAULT_SCOPES, Check, CheckResult, register
from l4.llm.system_one import LAYA_MODEL, laya_checkpoint_present, laya_version
from l4.memory.ignore import carve_out_text, ignored_harness_paths
from l4.memory.inject import read_lessons_file
from l4.memory.lessons import Problem, lint, parse_lessons
from l4.verifier.playwright import playwright_enabled
from l4.versions import parse_version

MAX_LISTED = 5
# on a CI runner the install is `l4 doctor --ci --fix` (adoption-lessons L4-ADO-015); prereqs.sh is the laptop's way
LAYA_FIX = "prereqs.sh --with-laya (on CI runners: `l4 doctor --ci --fix`)"
SERENA_FIX = "prereqs.sh --with-serena (on CI runners: `l4 doctor --ci --fix`)"


def _where(problem: Problem) -> str:
    return problem.lesson_id or (f"line {problem.line}" if problem.line else "file")


def _mem_001(ctx: DoctorContext) -> CheckResult:
    memory = ctx.cfg.memory
    if not memory.enabled:
        return CheckResult("skip", "memory.enabled is false")
    text, problem = read_lessons_file(ctx.repo, memory.lessons_file)
    if problem is None and not text:
        return CheckResult("pass", f"no {memory.lessons_file} yet")
    parsed = parse_lessons(text)
    problems = [*([problem] if problem else []), *parsed.problems]
    problems += lint(parsed.file, max_lessons=memory.max_lessons, max_bytes=memory.max_bytes)
    if not problems:
        return CheckResult("pass", f"{len(parsed.file.lessons)} lessons, lint clean")
    shown = "; ".join(f"{_where(p)}: {p.message}" for p in problems[:MAX_LISTED])
    more = f" (+{len(problems) - MAX_LISTED} more)" if len(problems) > MAX_LISTED else ""
    return CheckResult("fail", f"{len(problems)} lessons problem(s): {shown}{more}", "l4 lessons lint")


def _laya_checkpoints(ctx: DoctorContext) -> list[str]:
    cfg = ctx.cfg
    names = cfg.roles.s1_judge
    profiles = [cfg.profiles[n] for n in names if n in cfg.profiles]
    return [p.model or LAYA_MODEL for p in profiles if p.backend == "system-one" and p.engine == "laya-local"]


def _env_006(ctx: DoctorContext) -> CheckResult:
    if not ctx.cfg.verifier.s1.enabled:
        return CheckResult("skip", "verifier.s1.enabled is false")
    checkpoints = _laya_checkpoints(ctx)
    if not checkpoints:
        return CheckResult("skip", "no roles.s1_judge profile uses engine laya-local")
    if not ctx.which("laya-serve"):
        message = "laya-serve not found on PATH: step 8 is recorded unavailable"
        return CheckResult("fail", message, LAYA_FIX)
    missing = [c for c in checkpoints if not laya_checkpoint_present(ctx.env, c)]
    if missing:
        return CheckResult("fail", f"the Laya checkpoint {missing[0]} is not in the Hugging Face cache", LAYA_FIX)
    found = laya_version(ctx.which("laya-serve") or "", ctx.env)
    if not found:
        return CheckResult("fail", f"could not read the installed laya version (the pin is {LAYA_VERSION})")
    if found != LAYA_VERSION:
        message = f"laya {found} is installed, the pin is {LAYA_VERSION}: calibration rows would mix versions"
        return CheckResult("fail", message, LAYA_FIX)
    return CheckResult("pass", f"laya {found}, checkpoint {checkpoints[0]} cached")


def playwright_browsers(ctx: DoctorContext) -> Path:
    """Where the gate sandbox mounts the browsers (`sandbox.caches.playwright`, shared and read-only)."""
    return cache_root(ctx.env, repo=ctx.repo) / "shared" / "ms-playwright"


_REVISION_DIR = re.compile(r"^\s*Install location:\s*(\S*/(?:chromium|chromium_headless_shell)-\d+)\s*$", re.M)


def _wanted_browsers(ctx: DoctorContext, folder: Path) -> list[str]:
    """The browser directories the pinned Playwright wants (what `playwright install --dry-run` prints, as PRQ-14
    reads it); empty when `uvx` is missing or its wheel is not cached (offline), so the revision cannot be told."""
    uvx = ctx.which("uvx")
    if not uvx:
        return []
    argv = [
        uvx,
        "--offline",
        "--from",
        f"playwright=={PLAYWRIGHT_VERSION}",
        "playwright",
        "install",
        "--dry-run",
        "chromium",
    ]
    done = ctx.run(argv, timeout=60.0, env={**ctx.env, "PLAYWRIGHT_BROWSERS_PATH": str(folder)})
    return [Path(m).name for m in _REVISION_DIR.findall(done.stdout)] if done.returncode == 0 else []


def _env_007(ctx: DoctorContext) -> CheckResult:
    if not (ctx.cfg.gates.e2e.command.strip() and playwright_enabled(ctx.cfg)):
        return CheckResult("skip", "no e2e gate, or verifier.playwright.enabled is false")
    folder = playwright_browsers(ctx)
    if not any(folder.glob("chromium*")):
        return CheckResult("fail", f"no Chromium under {folder}: UI tests cannot run", "prereqs.sh --with-playwright")
    wanted = _wanted_browsers(ctx, folder)
    if not wanted:  # the revision cannot be told: a name check is all there is
        return CheckResult("pass", f"Chromium cached under {folder} (revision not checked)")
    missing = [name for name in wanted if not (folder / name).is_dir()]
    if missing:
        message = (
            f"playwright {PLAYWRIGHT_VERSION} wants {', '.join(missing)}, not under {folder}: UI tests cannot launch"
        )
        return CheckResult("fail", message, "prereqs.sh --with-playwright")
    return CheckResult("pass", f"Chromium for playwright {PLAYWRIGHT_VERSION} cached under {folder}")


def _env_008(ctx: DoctorContext) -> CheckResult:
    memory = ctx.cfg.memory
    if not (memory.enabled and memory.serena.enabled):
        return CheckResult("skip", "memory.serena.enabled is false")
    binary = ctx.which("serena")
    pin = memory.serena.version
    if not binary:
        message = f"serena not found on PATH (pin {pin}): lessons still reach the prompt"
        return CheckResult("fail", message, SERENA_FIX)
    out = ctx.run([binary, "--version"], timeout=60.0)
    found = parse_version(out.stdout) if out.returncode == 0 else None
    if found is None:
        return CheckResult("fail", "could not read the output of `serena --version`")
    if found != parse_version(pin):
        return CheckResult("fail", f"serena {'.'.join(map(str, found))} is installed, the pin is {pin}", SERENA_FIX)
    return CheckResult("pass", f"serena {pin}")


def _mem_002(ctx: DoctorContext) -> CheckResult:
    """The repository's `.gitignore` must not swallow the committed harness paths (M1.8 A5): git cannot re-include a
    file under an ignored directory, so lessons would stay on one machine. The answer is `git check-ignore`'s."""
    if not (ctx.cfg.memory.enabled and ctx.cfg.memory.serena.enabled):
        return CheckResult("skip", "memory or Serena is off")
    ignored = ignored_harness_paths(ctx.repo, ctx.env)
    if not ignored:
        return CheckResult("pass", "git ignores none of the harness memory paths")
    return CheckResult(
        "fail", carve_out_text(ignored),
        "replace the ignoring rule in .gitignore with the lines above, or set memory.enabled: false",
    )  # fmt: skip


for _id, _title, _run in (
    ("MEM-001", "lessons file lint", _mem_001),
    ("MEM-002", "memory paths are not git-ignored", _mem_002),
    ("ENV-006", "Laya installed and checkpoint cached", _env_006),
    ("ENV-007", "Playwright browsers", _env_007),
    ("ENV-008", "Serena pinned version", _env_008),
):
    register(Check(_id, _title, "warn", _run, CONFIG_SCOPES if _id.startswith("MEM-") else DEFAULT_SCOPES))
