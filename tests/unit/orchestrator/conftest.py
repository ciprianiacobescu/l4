import json
import sys
import types
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from l4 import services
from l4.agents.factory import ADAPTERS
from l4.agents.fake import FakeAdapter, Step
from l4.cli import main
from l4.specs.questions import QuestionsFile, QuestionStatus
from l4.vcs.names import UnitNames

from ..conftest import UNIT, TddRepo  # noqa: F401

BRANCH = "l4/openspec/add-discount-codes"
LOCK_REF = "refs/l4/locks/openspec/add-discount-codes"
UNIT_DIR = "openspec/changes/add-discount-codes"


@dataclass
class Run:
    code: int
    adapter: FakeAdapter
    tdd: TddRepo
    raw: Callable[..., str]

    @property
    def outcome(self) -> dict:
        return json.loads((self.tdd.repo / ".l4-out" / "outcome.json").read_text())

    def pushed(self, path: str) -> str:
        """A file of the unit branch as `origin` has it."""
        return self.raw(self.tdd.origin, "show", f"{BRANCH}:{path}")

    def branch_ledger(self) -> list[dict]:
        """The events the unit branch holds, and only those."""
        listing = self.raw(self.tdd.origin, "ls-tree", "--name-only", BRANCH, f"{UNIT_DIR}/.l4/ledger/").split()
        lines = [line for path in sorted(listing) for line in self.pushed(path).splitlines()]
        return sorted((json.loads(line) for line in lines), key=lambda e: (e["ts"], e["run_id"], e["seq"]))

    def pending_files(self) -> dict[str, str]:
        """`ledger-pending/<run>.jsonl` of the unit's lock ref on `origin` (what a run writes after H)."""
        ref = LOCK_REF
        if not self.raw(self.tdd.origin, "for-each-ref", ref).strip():
            return {}
        listing = self.raw(self.tdd.origin, "ls-tree", "--name-only", ref, "ledger-pending/").split()
        return {Path(name).name: self.raw(self.tdd.origin, "show", f"{ref}:{name}") for name in listing}

    def ledger(self) -> list[dict]:
        """The unit's whole ledger as the fold sees it: the branch plus the pending files, by (run_id, seq)."""
        events = {(e["run_id"], e["seq"]): e for e in self.branch_ledger()}
        for text in self.pending_files().values():
            for line in text.splitlines():
                event = json.loads(line)
                events.setdefault((event["run_id"], event["seq"]), event)
        return sorted(events.values(), key=lambda e: (e["ts"], e["run_id"], e["seq"]))

    def local_events(self, event_type: str) -> list[dict]:
        """From the unit's worktree, for a run that pushed nothing."""
        names = UnitNames.for_unit(UNIT, branch_prefix="l4/", cache=self.tdd.cache)
        files = sorted((names.worktree / UNIT_DIR / ".l4" / "ledger").glob("*.jsonl"))
        events = [json.loads(line) for f in files for line in f.read_text().splitlines()]
        return [e for e in events if e["type"] == event_type]

    def events(self, event_type: str) -> list[dict]:
        return [e for e in self.ledger() if e["type"] == event_type]

    def triggers(self) -> list[str]:
        return [e["trigger"] for e in self.events("phase.changed")]

    def subjects(self) -> list[str]:
        return self.raw(self.tdd.origin, "log", "--format=%s", f"main..{BRANCH}").splitlines()[::-1]


@pytest.fixture(autouse=True)
def no_verifier(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests are about the run up to `implemented`: the verifier (tests/unit/verifier) is switched off by
    pointing its hook at a module that does not exist, which is how an absent hook looks."""
    monkeypatch.setitem(services.HOOKS, "verify", "l4_test_no_verifier:verify_hook")


@pytest.fixture(autouse=True)
def no_clarifier(monkeypatch: pytest.MonkeyPatch) -> None:
    """Likewise for the clarifier: these tests send blocked units straight to a human unless one installs a hook
    (`install_hooks(clarify=...)`); the real hook is tested in tests/unit/clarifier."""
    monkeypatch.setitem(services.HOOKS, "clarify", "l4_test_no_clarifier:clarify_hook")


@pytest.fixture
def run_l4(tdd_repo: TddRepo, raw: Callable[..., str], monkeypatch: pytest.MonkeyPatch):
    """`l4 run` through the CLI with a scripted fake agent: `run(script, *flags)`. The fake adapter replaces the
    registry entry, so everything else (config, lease, worktree, sandbox selection, factory, ledger, pushes) is real."""

    def run(script: list[Step], *flags: str, unit: bool = True, probes: dict | None = None, **config: object) -> Run:
        tdd_repo.write_config(**config)  # type: ignore[arg-type]
        adapter = FakeAdapter(script, probes=probes)
        monkeypatch.setitem(ADAPTERS, "fake", lambda: adapter)
        argv = ["run", *(["--unit", UNIT] if unit else []), *flags, "--repo", str(tdd_repo.repo)]
        return Run(main(argv, environ=tdd_repo.environ), adapter, tdd_repo, raw)

    return run


@pytest.fixture
def install_hooks(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Point services.HOOKS at fake hook functions: `install(forge=fn, verify=fn, ...)`."""

    def install(**hooks: Callable) -> None:
        module = types.ModuleType("l4_test_hooks")
        for name, fn in hooks.items():
            setattr(module, name, fn)
            monkeypatch.setitem(services.HOOKS, name, f"l4_test_hooks:{name}")
        monkeypatch.setitem(sys.modules, "l4_test_hooks", module)

    return install


def new_origin_main(tdd: TddRepo, raw: Callable[..., str], files: dict[str, str]) -> None:
    """Commit `files` on main and push it, as a human would before running l4."""
    for name, text in files.items():
        (tdd.repo / name).write_text(text)
    raw(tdd.repo, "add", "-A")
    raw(tdd.repo, "commit", "-q", "-m", "change the unit")
    raw(tdd.repo, "push", "-q", "origin", "main")
    raw(tdd.repo, "fetch", "-q", "origin")


def edit_questions_on_origin(
    tdd: TddRepo, raw: Callable[..., str], *, status: str, answer: str = "", qid: str = "Q-001", suggestion: str = ""
) -> None:
    """What a human does: clone the remote, edit `questions.md` on the unit branch, push."""
    clone = tdd.repo.parent / f"human-{status}"
    raw(tdd.repo.parent, "clone", "-q", "--branch", BRANCH, str(tdd.origin), str(clone))
    path = clone / UNIT_DIR / "questions.md"
    file = QuestionsFile.load(path)
    assert file is not None
    file = file.set_status(qid, QuestionStatus(status))
    if answer:
        body = file.get(qid).answer.body  # type: ignore[union-attr]
        file = QuestionsFile.parse(file.data[: body.end] + answer.encode() + b"\n" + file.data[body.end :])
    if suggestion:
        from l4.redact import Redactor

        file = file.set_suggestion(qid, suggestion, redactor=Redactor({}))
    file.save(path)
    raw(clone, "add", "-A")
    raw(clone, "commit", "-q", "-m", f"answer {qid}")
    raw(clone, "push", "-q", "origin", BRANCH)


@pytest.fixture
def fake_clock(monkeypatch: pytest.MonkeyPatch):
    """One `FakeClock` for every run of a test: the factory of each `l4 run` reads it, so a cool-down recorded by
    one run ends when the test advances the clock, not when the machine's does."""
    from datetime import UTC, datetime

    from l4.availability.cooldown import FakeClock

    clock = FakeClock(datetime(2026, 1, 1, 0, 0, tzinfo=UTC))
    monkeypatch.setattr("l4.services.SystemClock", lambda: clock)
    return clock
