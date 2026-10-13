"""ENV-013 (the Ollama engine), S1-001, S1-002 and COV-001 (M1.6 plan line 39): the optional parts of the evidence
work, all warnings (they degrade, never block a run). Registered at import."""

from pathlib import Path

import httpx

from l4.availability.errors import RoleUnavailable
from l4.doctor.context import DoctorContext
from l4.doctor.registry import Check, CheckResult, register
from l4.gates.coverage import is_python_gate, project_python
from l4.llm.s1_checkpoint import checkpoint_problem, is_checkpoint_path
from l4.llm.system_one import open_s1_profile
from l4.redact import Redactor

MAX_LISTED = 5


def _client() -> httpx.Client | None:
    """The seam for the remote health probe: tests inject a mock transport."""
    return None


def _shadow(ctx: DoctorContext) -> list[str]:
    s1 = ctx.cfg.verifier.s1
    return list(s1.shadow) if s1.enabled else []


def _listed(problems: list[str]) -> str:
    more = f" (+{len(problems) - MAX_LISTED} more)" if len(problems) > MAX_LISTED else ""
    return "; ".join(problems[:MAX_LISTED]) + more


def _s1_001(ctx: DoctorContext) -> CheckResult:
    names = _shadow(ctx)
    if not names:
        return CheckResult("skip", "verifier.s1.shadow names no profile")
    problems = []
    for name in names:
        try:
            open_s1_profile(ctx.cfg, name, environ=ctx.env, client=_client(), redactor=Redactor({}))
        except RoleUnavailable as exc:
            problems.append(f"{name}: {str(exc).split('is unavailable: ', 1)[-1]}")
    if problems:
        return CheckResult("fail", f"shadow engine(s) not usable, recorded as errors: {_listed(problems)}")
    return CheckResult("pass", f"{len(names)} shadow profile(s) usable: {', '.join(names)}")


def _s1_002(ctx: DoctorContext) -> CheckResult:
    cfg = ctx.cfg
    names = [*cfg.roles.s1_judge, *cfg.verifier.s1.shadow]
    checkpoints = {
        n: p.model
        for n in dict.fromkeys(names)
        if (p := cfg.profiles.get(n)) is not None
        and p.backend == "system-one"
        and p.engine == "laya-local"
        and is_checkpoint_path(p.model)
    }
    if not checkpoints:
        return CheckResult("skip", "no System-One profile names a tuned checkpoint path")
    checked = {n: checkpoint_problem(str(model), ctx.env) for n, model in checkpoints.items()}
    problems = [f"{n}: {why}" for n, why in checked.items() if why]
    if problems:
        message = f"checkpoint not usable: {_listed(problems)}"
        return CheckResult("fail", message, "scripts/s1/deploy_checkpoint.sh <id>")
    return CheckResult("pass", f"gated and sha-intact: {', '.join(checkpoints)}")


def _project_python(ctx: DoctorContext) -> Path | None:
    return project_python(ctx.cfg, ctx.repo, ctx.which)


def _cov_001(ctx: DoctorContext) -> CheckResult:
    if ctx.cfg.verifier.evidence.diff_coverage.mode == "off":
        return CheckResult("skip", "verifier.evidence.diff_coverage.mode is off")
    python = _project_python(ctx)
    if python is None and not is_python_gate(ctx.cfg.gates.test.command):  # with a .venv, `make test` still checks
        return CheckResult("skip", "no python test gate: diff coverage does not apply")
    if python is None and ctx.cfg.gates.setup:
        # in CI the doctor runs before the job's gates.setup creates .venv (live M1.6 job 5535): the run looks again
        # right after setup and records the answer as `doctor.check{id: COV-001, when: "after gates.setup"}`
        return CheckResult(
            "skip",
            "no project interpreter yet: gates.setup creates it inside the run, which checks coverage.py again right "
            "after it (the doctor.check event, COV-001)",
        )
    if python is None:
        return CheckResult("skip", "no project interpreter found (gates.test.command or .venv/bin/python)")
    done = ctx.run([str(python), "-c", "import coverage"], timeout=30.0)
    if done.returncode != 0:
        message = f"coverage.py is not importable by {python}: diff coverage will be recorded not_run"
        return CheckResult("fail", message, "add coverage to the project's dev dependencies")
    return CheckResult("pass", f"coverage.py imports in {python}")


def _env_013(ctx: DoctorContext) -> CheckResult:
    """Every `engine: ollama` profile of `roles.s1_judge` or the shadow list: the host answers, runs Ollama >= 0.35.0
    and has the model. A host that sleeps degrades step 8 (the chain falls back), it never blocks a run."""
    cfg = ctx.cfg
    if not cfg.verifier.s1.enabled:
        return CheckResult("skip", "verifier.s1.enabled is false")
    names = [
        n for n in dict.fromkeys([*cfg.roles.s1_judge, *cfg.verifier.s1.shadow])
        if (p := cfg.profiles.get(n)) is not None and p.backend == "system-one" and p.engine == "ollama"
    ]  # fmt: skip
    if not names:
        return CheckResult("skip", "no System-One profile uses engine ollama")
    problems, ready = [], []
    for name in names:
        try:
            backend = open_s1_profile(cfg, name, environ=ctx.env, client=_client(), redactor=Redactor({}))
        except RoleUnavailable as exc:
            problems.append(f"{name}: {str(exc).split('is unavailable: ', 1)[-1]}")
        else:
            ready.append(f"{name} ({backend.model}, {backend.server_version})")
    if problems:
        message = f"Ollama host not usable (step 8 falls back to the next S1 profile): {_listed(problems)}"
        return CheckResult("fail", message, "start Ollama on the host, or `ollama pull <model>` there")
    return CheckResult("pass", f"Ollama ready: {', '.join(ready)}")


for _id, _title, _run in (
    ("ENV-013", "Ollama System-One host reachable, model pulled", _env_013),
    ("S1-001", "S1 shadow engines usable", _s1_001),
    ("S1-002", "S1 tuned checkpoint gated and intact", _s1_002),
    ("COV-001", "coverage.py in the project environment", _cov_001),
):
    register(Check(_id, _title, "warn", _run))
