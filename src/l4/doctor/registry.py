"""Check registry (SPEC L4-DOC-001 b): other changes add checks by calling `register` at import."""

import dataclasses
import importlib
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from l4.config.schema import L4Config
from l4.doctor.context import DoctorContext
from l4.exitcodes import ExitCode

if TYPE_CHECKING:
    from l4.provision.runner import FixAction

Severity = Literal["error", "warn", "info"]
Scope = Literal["ci", "local", "live", "config", "adoption"]
Status = Literal["pass", "fail", "skip"]
FixKind = Literal["prune", "release", "delete", "create", "rebuild-mirrors", "re-render", "install"]
FixScope = Literal["provision", "repo"]
SAFE_FIX_KINDS: frozenset[FixKind] = frozenset(
    {"prune", "release", "delete", "create", "rebuild-mirrors", "re-render", "install"}
)

DEFAULT_SCOPES: frozenset[Scope] = frozenset({"ci", "local"})
# the rows that read only the repository: with `config`, `doctor --adoption --no-gates` runs them on a laptop (A4)
CONFIG_SCOPES: frozenset[Scope] = frozenset({"ci", "local", "config"})


def doctor_scopes(*, ci: bool, adoption: bool, no_gates: bool) -> frozenset[Scope]:
    """`--ci`: `ci`. `--adoption`: the repository's own rows (`config`) and the gate dry run (`adoption`); `--no-gates`
    drops the latter. `--ci --adoption` adds `ci` to them. Plain: `ci` and `local`."""
    if adoption:
        return frozenset({"config"} | ({"ci"} if ci else set()) | (set() if no_gates else {"adoption"}))
    return frozenset({"ci"}) if ci else DEFAULT_SCOPES


# Modules of other changes that register checks at import; absent until their change lands.
CHECK_MODULES = (
    "l4.doctor.checks_agents", "l4.doctor.checks_spec", "l4.doctor.checks_provision", "l4.doctor.checks_memory",
    "l4.doctor.checks_s1", "l4.doctor.checks_sandbox", "l4.doctor.checks_gates", "l4.doctor.checks_eval",
)  # fmt: skip


class DuplicateCheckError(ValueError):
    pass


@dataclass(frozen=True)
class CheckResult:
    status: Status
    message: str
    fix_hint: str | None = None
    cost_usd: float = 0.0
    severity: Severity | None = None  # a check whose failures differ in weight says so (ENV-004: head vs fallback)


@dataclass(frozen=True)
class Fix:
    """What `--fix` may do about a failing check. `apply` returns what it did, one `FixAction` per step. `survey` is
    its read-only form, run when the check passes: it lists what is already in place (nothing is changed)."""

    kind: FixKind
    scope: FixScope
    apply: Callable[[DoctorContext], "Sequence[FixAction]"]
    survey: Callable[[DoctorContext], "Sequence[FixAction]"] | None = None


@dataclass(frozen=True)
class Check:
    id: str
    title: str
    severity: Severity | Callable[[L4Config], Severity]
    run: Callable[[DoctorContext], CheckResult]
    scopes: frozenset[Scope] = DEFAULT_SCOPES
    unit_aware: bool = False  # reads `ctx.unit`: with `--unit ID` it looks at that unit only, else at every unit
    fix: Fix | None = None


@dataclass(frozen=True)
class CheckOutcome:
    id: str
    title: str
    severity: Severity
    status: Status
    message: str
    fix_hint: str | None
    cost_usd: float


@dataclass
class Registry:
    _checks: dict[str, Check] = field(default_factory=dict)

    def register(self, check: Check) -> Check:
        if check.id in self._checks:
            raise DuplicateCheckError(f"doctor check {check.id} is already registered")
        self._checks[check.id] = check
        return check

    def checks(self) -> list[Check]:
        return list(self._checks.values())

    def attach_fix(self, check_id: str, fix: Fix) -> None:
        """Hang a fix on a check another change owns, without registering a second check."""
        check = self._checks.get(check_id)
        if check is None:
            raise KeyError(f"doctor check {check_id} is not registered")
        if check.fix is not None:
            raise DuplicateCheckError(f"doctor check {check_id} already has a fix")
        self._checks[check_id] = dataclasses.replace(check, fix=fix)


REGISTRY = Registry()


def register(check: Check) -> Check:
    return REGISTRY.register(check)


def attach_fix(check_id: str, fix: Fix) -> None:
    REGISTRY.attach_fix(check_id, fix)


def load_check_modules(modules: tuple[str, ...] = CHECK_MODULES) -> None:
    """Import the check modules of other changes. Only 'that module does not exist yet' is skipped."""
    for name in modules:
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if not (exc.name and (name == exc.name or name.startswith(exc.name + "."))):
                raise


def run_checks(
    ctx: DoctorContext,
    *,
    live: bool = False,
    registry: Registry | None = None,
    scopes: Collection[Scope] = DEFAULT_SCOPES,
    unit: str | None = None,
    only: Collection[str] | None = None,
) -> list[CheckOutcome]:
    """`scopes`: a check runs when it declares one of them (`--ci` passes just `ci`); `live` adds the `live` scope.
    `unit` narrows the unit-aware checks to one unit; every other check runs once. `only` re-runs named checks."""
    wanted = {*scopes, *(["live"] if live else [])}
    outcomes: list[CheckOutcome] = []
    for check in (registry or REGISTRY).checks():
        if not wanted & check.scopes or (only is not None and check.id not in only):
            continue
        severity = check.severity(ctx.cfg) if callable(check.severity) else check.severity
        try:
            result = check.run(dataclasses.replace(ctx, unit=unit) if check.unit_aware else ctx)
        except Exception as exc:  # one broken check must not hide the others or the --json document
            result = CheckResult("fail", f"check crashed: {type(exc).__name__}: {exc}")
        outcomes.append(
            CheckOutcome(
                check.id, check.title, result.severity or severity, result.status,
                result.message, result.fix_hint, result.cost_usd,
            )
        )  # fmt: skip
    return outcomes


def exit_code(outcomes: list[CheckOutcome]) -> ExitCode:
    failed = any(o.severity == "error" and o.status == "fail" for o in outcomes)
    return ExitCode.DOCTOR_FAILED if failed else ExitCode.OK
