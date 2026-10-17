import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass

import pytest

from l4.agents.base import ProbeCtx
from l4.agents.factory import Factory
from l4.agents.fake import FakeAdapter, Step
from l4.config.loader import load_config
from l4.context import AppContext
from l4.doctor.context import CmdResult
from l4.implementer.workbench import Workbench, make_workbench
from l4.redact import Redactor
from l4.sandbox.none import NoSandbox
from l4.specs.providers import providers_for
from l4.state.ledger import LedgerWriter
from l4.vcs.git import Git
from l4.vcs.names import UnitNames
from l4.vcs.worktree import WorktreeManager

from .._kiro_probe import PROBE_IDS, probe_tree
from ..conftest import UNIT, TddRepo

RUN_ID = "r-20261003T1312Z-7f3a"

STUB = (
    "def total(prices: list[float]) -> float:\n    return round(sum(prices), 2)\n\n\n"
    "def apply_discount(amount, code):\n    raise NotImplementedError\n"
)
IMPL = (
    'CODES = {"SAVE10": 10}\n\n\ndef total(prices: list[float]) -> float:\n    return round(sum(prices), 2)\n\n\n'
    "def apply_discount(amount, code):\n    if code not in CODES:\n        raise ValueError(code)\n"
    "    return round(amount * (100 - CODES[code]) / 100, 2)\n"
)
KNOWN, UNKNOWN = "C-2d3a8daf", "C-d80f494d"  # the scenarios of the fixture unit's spec
HEADER = "import pytest\n\nfrom pytdd.pricing import apply_discount\n\n\n"
KNOWN_TEST = f'@pytest.mark.l4("{KNOWN}")\ndef test_known_code():\n    assert apply_discount(50.0, "SAVE10") == 45.0\n'
UNKNOWN_TEST = (
    f'@pytest.mark.l4("{UNKNOWN}")\ndef test_unknown_code():\n'
    '    with pytest.raises(ValueError):\n        apply_discount(50.0, "NOPE")\n'
)
TESTS = HEADER + KNOWN_TEST + "\n\n" + UNKNOWN_TEST


def result(phase: str, **over: object) -> dict:
    base = {"status": "done", "phase": phase, "task_ids": ["1.1"], "summary": f"{phase} done", "criteria_ids": []}
    return {**base, **over}


def red_step(**over: object) -> Step:
    return Step(
        writes={"tests/test_discount.py": TESTS, "src/pytdd/pricing.py": STUB},
        structured=result(
            "red", tests_added=["tests/test_discount.py::test_known_code"], criteria_ids=[KNOWN, UNKNOWN]
        ),
        **over,
    )  # fmt: skip


def green_step(**over: object) -> Step:
    return Step(writes={"src/pytdd/pricing.py": IMPL}, structured=result("green"), **over)


TIP_STUB = "def tip(bill, percent):\n    raise NotImplementedError\n"
TIP_IMPL = (
    "from decimal import ROUND_HALF_UP, Decimal\n\n\ndef tip(bill, percent):\n"
    "    if percent < 0:\n        raise ValueError(percent)\n"
    '    return (Decimal(str(bill)) * Decimal(str(percent)) / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)\n'
)
TIP_HEADER = "import pytest\n\nfrom pytdd.tip import tip\n\n\n"
TIP_ROUNDS = (
    f'@pytest.mark.l4("{PROBE_IDS["1.1"]}")\ndef test_tip_is_rounded():\n    assert str(tip(10, 12.5)) == "1.25"\n'
)
TIP_NEGATIVE = (
    f'@pytest.mark.l4("{PROBE_IDS["1.2"]}")\ndef test_negative_percent_raises():\n'
    "    try:\n        tip(10, -1)\n    except ValueError:\n        return\n    raise AssertionError('no ValueError')\n"
)


def kiro_red_step(*, tests: str = TIP_ROUNDS + "\n\n" + TIP_NEGATIVE, criteria: list[str] | None = None) -> Step:
    """A red step for the probe's task 1: the stub `pytdd.tip.tip` and tests tagged with the probe's criterion ids."""
    ids = list(PROBE_IDS.values()) if criteria is None else criteria
    return Step(
        writes={"tests/test_tip.py": TIP_HEADER + tests, "src/pytdd/tip.py": TIP_STUB},
        structured=result("red", task_ids=["1"], criteria_ids=ids),
    )


def blocked_step(**over: object) -> Step:
    questions = [
        {"title": "Which rounding?", "context": "scenarios disagree", "kind": "ambiguous", "options": ["a", "b"]}
    ]
    return Step(structured=result("red", status="blocked", questions=questions), **over)


@dataclass
class Bench:
    wb: Workbench
    adapter: FakeAdapter
    writer: LedgerWriter
    tdd: TddRepo
    pushes: list[str]

    def events(self, event_type: str) -> list[dict]:
        lines = (self.wb.ref.path / ".l4" / "ledger" / f"{RUN_ID}.jsonl").read_text().splitlines()
        return [e for e in map(json.loads, lines) if e["type"] == event_type]

    def subjects(self) -> list[str]:
        """Commit subjects of the unit branch, oldest first."""
        return self.wb.git.run("log", "--format=%s", "main..HEAD").stdout.splitlines()[::-1]


def build_bench(
    tdd_repo: TddRepo, script: list[Step], unit: str, *, implementer: dict | None = None,
    frameworks: list[str] | None = None, **gates: object,
) -> Bench:  # fmt: skip
    """A worktree of `unit` with a ledger, the fake adapter and no sandbox: what the loop runs in."""
    tdd_repo.write_config(implementer=implementer, frameworks=frameworks, **gates)
    repo, environ = tdd_repo.repo, tdd_repo.environ
    cfg = load_config(repo)
    app = AppContext(repo, None, "human", 0, RUN_ID, environ, Redactor({}))
    git = Git(repo, environ=environ)
    names = UnitNames.for_unit(unit, branch_prefix=cfg.forge.branch_prefix, cache=tdd_repo.cache, repo_key=tdd_repo.key)
    worktree = WorktreeManager(git, base_branch="main", branch_prefix="l4/", cache=tdd_repo.cache).ensure(names)
    wgit = git.at(worktree.path)
    provider = providers_for(cfg, worktree.path, environ)[0]
    ref = next(r for r in provider.list_units() if r.id == unit)
    writer = LedgerWriter.open(ref.path, unit, RUN_ID, redactor=app.redactor)
    adapter = FakeAdapter(script)
    ctx = ProbeCtx(environ, tdd_repo.cache, lambda *a: CmdResult(0, "", ""))
    selected = Factory(cfg, ctx, events=writer, adapters={"fake": adapter}).for_role("implementer", unit)
    pushes: list[str] = []

    def push() -> None:
        pushes.append(wgit.rev_parse("HEAD") or "")
        wgit.push("origin", [f"HEAD:refs/heads/{names.branch}"])

    wb = make_workbench(
        cfg=cfg, app=app, ref=ref, provider=provider, worktree=worktree.path, git=wgit, ledger=writer,
        sandbox=NoSandbox(allow_none=True), selected=selected, iteration=1, push=push,
    )  # fmt: skip
    return Bench(wb, adapter, writer, tdd_repo, pushes)


@pytest.fixture
def make_bench(tdd_repo: TddRepo) -> Callable[..., Bench]:
    """A worktree of the py_tdd unit with a ledger, the fake adapter and no sandbox: what the loop runs in."""

    def make(script: list[Step], *, implementer: dict | None = None, **gates: object) -> Bench:
        return build_bench(tdd_repo, script, UNIT, implementer=implementer, **gates)

    return make


KIRO_UNIT = "kiro:tip-calc"


def to_kiro(tdd_repo: TddRepo, *, long_design: bool = False, steering: dict[str, str] | None = None) -> None:
    """Turn the py_tdd repository into the probe's: its OpenSpec change gives way to `.kiro/specs/tip-calc/` and
    `.kiro/steering/tech.md`, committed on `main` and pushed (the worktree of the bench starts from there)."""
    repo, git = tdd_repo.repo, Git(tdd_repo.repo, environ=tdd_repo.environ)
    shutil.rmtree(repo / "openspec")
    probe_tree(repo, long=long_design)
    for name, text in (steering or {}).items():
        (repo / ".kiro" / "steering" / name).write_text(text)
    git.run("add", "-A")
    git.run("commit", "-q", "-m", "the kiro probe")
    git.push("origin", ["main"])


@pytest.fixture
def make_kiro_bench(tdd_repo: TddRepo) -> Callable[..., Bench]:
    """`make_bench` for the probe unit `kiro:tip-calc` (kiro-prompt-context): the py_tdd repository with the OpenSpec
    change replaced by the probe's spec and steering, `spec.frameworks: [kiro]` and the fake adapter."""

    def make(
        script: list[Step], *, implementer: dict | None = None, long_design: bool = False,
        steering: dict[str, str] | None = None, **gates: object,
    ) -> Bench:  # fmt: skip
        to_kiro(tdd_repo, long_design=long_design, steering=steering)
        return build_bench(tdd_repo, script, KIRO_UNIT, implementer=implementer, frameworks=["kiro"], **gates)

    return make


@pytest.fixture(autouse=True)
def _fresh_serena_checks():
    """`RUN_ID` is fixed, and the one `check_serena` of a run is cached per run id (process-wide)."""
    from l4.implementer import workbench

    workbench._SERENA_CHECKED.clear()
    yield
    workbench._SERENA_CHECKED.clear()
