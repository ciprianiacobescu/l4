"""Shared spec-provider types, the error tree and the `SpecProvider` Protocol (SPEC 4.2, 4.3)."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from l4.exitcodes import ExitCode, L4Exit

# A unit name becomes a path segment, a branch name and a lock-file name, and it comes from repo content.
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


_INNERMOST_PAIR = re.compile(r"\[([^\[\]]*)\]")
_TAG_CONTENT = re.compile(r"[\w\s-]*")


def untagged(text: str) -> str:
    """Model- and person-written text for a heading, a task or a proposal line, with no `[tag]` it could carry
    (`[test-infra]`, `[config]`, `[ ]` exempt a rule or open a checkbox; L4-IMP-006 (7)). NUL characters are removed. A
    bracket becomes a parenthesis only where it could form a tag: an innermost pair whose content is letters, digits,
    `_`, `-` and whitespace only, and every bracket without a partner (or left outside an innermost pair). Any other
    innermost pair stays as written (`[...ROLES].sort()`, `["a", "b"]`): it holds a character that neither tag pattern
    of the harness allows, and nothing left can pair with its brackets."""
    text = text.replace("\x00", "")
    out, pos = [], 0
    for pair in _INNERMOST_PAIR.finditer(text):
        out.append(_loose(text[pos : pair.start()]))
        out.append(f"({pair.group(1)})" if _TAG_CONTENT.fullmatch(pair.group(1)) else pair.group())
        pos = pair.end()
    out.append(_loose(text[pos:]))
    return "".join(out)


def _loose(text: str) -> str:
    return text.replace("[", "(").replace("]", ")")


class Framework(StrEnum):
    OPENSPEC = "openspec"
    KIRO = "kiro"


class Marker(StrEnum):
    NOT_STARTED = " "
    QUEUED = "~"
    IN_PROGRESS = "-"
    DONE = "x"


class SpecError(L4Exit):
    """Base of every provider error. Subclasses carry their exit code so no caller needs a mapping."""

    default_code = ExitCode.INTERNAL_ERROR

    def __init__(self, message: str = "") -> None:
        super().__init__(self.default_code, message)


class OpenSpecUnavailable(SpecError):
    """The pinned OpenSpec install or its node is missing: fail closed, never fall back to PATH or npx."""

    default_code = ExitCode.DOCTOR_FAILED


class OpenSpecCommandError(SpecError):
    """The CLI exited with an error, or printed something that is not the JSON the contract promises."""


class ArchiveRefused(SpecError):
    """`archive()` stopped before starting the CLI: a task is open or strict validation fails (L4-OSP-003)."""


class ArchiveFailed(OpenSpecCommandError):
    """The CLI's `archive` ran and said no (`archive_validation_failed`, `archive_target_exists`, ...)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.error_code = code


class MarkerWriteError(SpecError):
    pass


class MarkerNotAllowed(SpecError):
    pass


class UnknownUnit(SpecError):
    default_code = ExitCode.USAGE_ERROR


class ProviderContractError(SpecError):
    """A provider that lacks a `SpecProvider` member was registered (L4-SPI-001)."""

    default_code = ExitCode.INTERNAL_ERROR


class NoFrameworkError(SpecError):
    """`sdd.enforce` is on and the repository has no supported spec framework (L4-DET-003)."""

    default_code = ExitCode.REJECTED


class ParentHasOpenChildren(MarkerNotAllowed):
    """A Kiro parent cannot be closed while a required child is open."""


class CriterionIdCollision(SpecError):
    default_code = ExitCode.REJECTED


class FixUnitExists(SpecError):
    """`<parent>-fix-<n>` is already a change: a fix unit is never overwritten (L4-OSP-005)."""


class FixUnitInvalid(SpecError):
    """The fix unit written does not validate `--strict`: its folder is removed and nothing is committed."""


@dataclass(frozen=True)
class UnitRef:
    framework: Framework
    name: str
    path: Path  # the unit directory: where questions.md and .l4/ live

    def __post_init__(self) -> None:
        if not SAFE_NAME.match(self.name) or ".." in self.name:
            raise ValueError(f"not a valid unit name: {self.name!r}")

    @property
    def id(self) -> str:
        return f"{self.framework.value}:{self.name}"


def parse_unit_id(text: str) -> tuple[Framework, str]:
    """`openspec:add-login` -> (OPENSPEC, "add-login"); ValueError for anything that is not one."""
    framework, sep, name = text.partition(":")
    if not sep or framework not in {f.value for f in Framework}:
        raise ValueError(f"not a unit id (expected <framework>:<name>): {text!r}")
    if not SAFE_NAME.match(name) or ".." in name:
        raise ValueError(f"not a valid unit name in {text!r}")
    return Framework(framework), name


@dataclass(frozen=True)
class Task:
    """One checkbox line. `key` is the number from the title (L4-OSP-004), else `L<line>`."""

    key: str
    number: str | None
    title: str  # empty for a text-less checkbox, which OpenSpec counts in `progress` but not in `tasks[]`
    done: bool  # only x/X; `[-]`, `[~]` and `[]` are not done (L4-OSP-004)
    marker_char: str  # everything between the brackets: " ", "x", "-", "", " x ", ...
    depth: int  # leading whitespace characters; hierarchy is derived from depth and order by the selector
    line: int  # 1-based, over split('\n')
    marker_offset: int | None  # byte offset of the marker; None unless the interior is exactly one character
    optional: bool = False  # Kiro `[ ]*`: never pending, never blocks a parent
    wave: int | None = None  # Kiro `## Task Dependency Graph` wave; None when the graph does not list the task
    links: tuple[str, ...] = ()  # Kiro `_Requirements: 2.1, 3.3_` references, as written
    started: bool = False  # Kiro IDE's `[-]` (in progress) or `[~]` (queued): pending like `[ ]`, and `x` replaces it


@dataclass(frozen=True)
class Criterion:
    id: str
    alias: str  # `capability › Requirement › Scenario`
    framework: Framework
    capability: str
    requirement: str
    scenario: str
    text: str  # the scenario body (WHEN/THEN lines)
    source_path: str  # relative to the unit directory
    source_line: int


@dataclass(frozen=True)
class ValidationIssue:
    level: Literal["ERROR", "WARNING", "INFO"]
    path: str
    message: str
    line: int | None = None


@dataclass(frozen=True)
class ValidationReport:
    valid: bool
    issues: tuple[ValidationIssue, ...]


@dataclass(frozen=True)
class GateReport:
    passed: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ArchiveReport:
    archived_as: str  # the dated folder name under `<root>/changes/archive/`
    specs_updated: bool
    moved_to: str | None = None  # Kiro: where the folder went; always None until `kiro.archive_dir` is honoured


@dataclass(frozen=True)
class Finding:
    """One fix task (spec-providers 1.32): a group of verifier findings on the same criterion. `ids` are the `F-...`
    ids it cites, `criteria` the `C-...` ids of existing criteria; a group with no criterion and no scenario is a
    `[chore]` task that runs in a single phase (D8)."""

    ids: tuple[str, ...]
    title: str
    detail: str = ""
    severity: str = "major"
    criteria: tuple[str, ...] = ()
    chore: bool = False
    tests: bool = False  # a chore that adds tests (a coverage hold's task): the step may write new test files (M1.11)
    # a person's feedback item (L4-FBK-005): `item` is its FB id, `request` the sentence "Requested by <By> in FB-NNN
    # (<kind>, <places>): <text>" (the text whole up to 1,200 characters), `code` the lines quoted in the item;
    # `refactor` marks a chore that keeps behaviour (the marker's `refactors`: the tests are frozen)
    refactor: bool = False
    item: str = ""
    request: str = ""
    code: str = ""
    retake: bool = False  # the item was taken before (the marker's `retakes`): "nothing left to change" completes it


@dataclass(frozen=True)
class DeltaScenario:
    name: str
    text: str  # the body: `- **WHEN** ...` and `- **THEN** ...` lines
    finding: str  # the id of the first finding that asked for it: its task cites the criterion this scenario gets


@dataclass(frozen=True)
class DeltaRequirement:
    capability: str
    title: str  # `<requirement of the cited criterion> — regression <n>`
    scenarios: tuple[DeltaScenario, ...]


@dataclass(frozen=True)
class SpecDelta:
    """The ADDED regression requirements of a fix unit. Never MODIFIED, REMOVED or RENAMED: the parent's own
    requirements are not in the base specs until it is archived (L4-VER-006, L4-OSP-006)."""

    requirements: tuple[DeltaRequirement, ...]


@dataclass(frozen=True)
class Unit:
    ref: UnitRef
    tasks: tuple[Task, ...]
    criteria: tuple[Criterion, ...]


# `archive` is on both providers but not in this Protocol: only the orchestrator's archive hook calls it, and it
# narrows to the providers that have one. `create_fix_unit` is the optional `FixUnitCapable` Protocol (M1.3).
@runtime_checkable
class SpecProvider(Protocol):
    framework: Framework

    def list_units(self) -> list[UnitRef]: ...
    def unit_dir(self, unit: UnitRef) -> Path: ...
    def load(self, unit: UnitRef) -> Unit: ...
    def tasks(self, unit: UnitRef) -> list[Task]: ...
    def criteria(self, unit: UnitRef) -> list[Criterion]: ...
    def set_marker(self, unit: UnitRef, task_key: str, marker: Marker) -> None: ...
    def validate(self, unit: UnitRef, strict: bool = True) -> ValidationReport: ...
    def done_gate(self, unit: UnitRef) -> GateReport: ...


PROVIDER_MEMBERS = (
    "framework",
    "list_units",
    "unit_dir",
    "load",
    "tasks",
    "criteria",
    "set_marker",
    "validate",
    "done_gate",
)  # fmt: skip  (one tuple: `runtime_checkable` Protocols cannot tell us which member is missing)


class ProviderRegistry:
    """Providers by framework. A provider is checked when it is registered, not when it first fails."""

    def __init__(self) -> None:
        self._providers: dict[Framework, SpecProvider] = {}

    def register(self, provider: SpecProvider) -> None:
        missing = [name for name in PROVIDER_MEMBERS if not hasattr(provider, name)]
        if missing:
            raise ProviderContractError(f"{type(provider).__name__} lacks SpecProvider member(s): {', '.join(missing)}")
        self._providers[provider.framework] = provider

    def get(self, framework: Framework) -> SpecProvider:
        try:
            return self._providers[framework]
        except KeyError:
            raise UnknownUnit(f"no spec provider is active for {framework.value}") from None

    def for_unit(self, unit: UnitRef) -> SpecProvider:
        return self.get(unit.framework)

    def providers(self) -> list[SpecProvider]:
        return list(self._providers.values())


@runtime_checkable
class FixUnitCapable(Protocol):
    """Not a `SpecProvider` member: the registry checks `SpecProvider` only. Both providers write fix units (an OpenSpec
    change, a Kiro bugfix spec); a provider without `create_fix_unit` escalates a failed round instead."""

    def create_fix_unit(
        self, parent: UnitRef, round: int, findings: Sequence[Finding], spec_delta: SpecDelta | None
    ) -> UnitRef: ...


# What a fix task keeps of the human decisions that open it, all of them together: each is kept whole up to its share
# of this (a decision is cut only far beyond any sentence a person writes), and the finding detail is what is cut.
MAX_DECISION_CHARS = 4000
