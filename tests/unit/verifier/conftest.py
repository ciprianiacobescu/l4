from typing import Any

import pytest
import yaml

from l4 import services
from l4.specs.base import ValidationIssue, ValidationReport
from l4.specs.openspec import CliResult, OpenSpecProvider

from ..archive.conftest import forge_env, gitlab, use_fake_gitlab  # noqa: F401  (a fake GitLab for the hand-off)
from ..conftest import TddRepo
from ..implementer.conftest import make_bench  # noqa: F401  (the unit worktree and its gates, no agent run)
from ..orchestrator.conftest import (  # noqa: F401  (`l4 run` with a scripted fake agent)
    BRANCH,
    UNIT_DIR,
    Run,
    fake_clock,
    run_l4,
)
from ..specs.fixcli import patch_openspec


def judge_reply(ids: list[str], verdict: str = "pass", **over: Any) -> dict[str, Any]:
    """A valid `l4/judge-verdict@1` object with one criterion entry per id."""
    criteria = [
        {"id": i, "verdict": verdict, "evidence": [{"kind": "file", "ref": "src/pytdd/pricing.py", "quote": "x"}]}
        for i in ids
    ]
    base = {
        "criteria": criteria,
        "test_adequacy": [],
        "findings": [],
        "riskiest_assumptions": ["the tests were not rerun", "the table is complete", "rounding is half-even"],
    }
    return {**base, **over}


class FakeCli:
    """The pinned OpenSpec is not installed under the tests' L4_HOME: `validate` answers from a canned result."""

    def __init__(self, valid: bool = True, issues: tuple[ValidationIssue, ...] = ()) -> None:
        self.valid, self.issues = valid, issues
        self.calls: list[tuple[str, ...]] = []

    def run_json(self, *args: str) -> CliResult:
        self.calls.append(args)
        issues = [{"level": i.level, "path": i.path, "message": i.message} for i in self.issues]
        item = {"id": args[1], "valid": self.valid, "issues": issues}
        return CliResult(args, 0, {"items": [item]})


def with_validation(wb, cli: FakeCli | None = None) -> FakeCli:
    """Rebind the bench's provider to a canned `openspec validate`."""
    cli = cli or FakeCli()
    wb.provider = OpenSpecProvider(wb.worktree, wb.host_env, cli=cli)  # type: ignore[arg-type]
    return cli


@pytest.fixture
def valid_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    """`openspec validate --strict` is not available under the tests' L4_HOME: every unit validates."""
    monkeypatch.setattr(OpenSpecProvider, "validate", lambda self, unit, strict=True: ValidationReport(True, ()))


@pytest.fixture
def run_verify(tdd_repo, raw, monkeypatch):
    """`l4 run` or `l4 verify --unit U` with a scripted fake agent: `run(script, via="verify")`."""
    from l4.agents.factory import ADAPTERS
    from l4.agents.fake import FakeAdapter
    from l4.cli import main

    from ..conftest import UNIT

    def run(script, *, via: str = "verify", **config: object) -> Run:
        tdd_repo.write_config(**config)
        adapter = FakeAdapter(script)
        monkeypatch.setitem(ADAPTERS, "fake", lambda: adapter)
        argv = [via, "--unit", UNIT, "--repo", str(tdd_repo.repo)]
        return Run(main(argv, environ=tdd_repo.environ), adapter, tdd_repo, raw)

    return run


@pytest.fixture(autouse=True)
def openspec_stand_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pinned OpenSpec is not installed under the tests' L4_HOME: `new change` writes the fix unit's folder and
    `validate` says valid (the contract test runs the real one)."""
    patch_openspec(monkeypatch)


@pytest.fixture(autouse=True)
def no_fix_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests are about the verdict: with no fix hook a FAIL stops at `fixing` (exit 10) the way `l4 verify`
    does, after the fix unit is written. The fix loop has its own tests (`test_ladder_fix.py`), which override this
    fixture."""
    monkeypatch.setitem(services.HOOKS, "fix", "l4_test_no_fix_hook:fix_hook")


@pytest.fixture
def with_verifier(monkeypatch):
    """Adds a `verifier:` section (and a verifier agent of a third vendor) to the generated config."""

    def apply(**verifier: object) -> dict:
        original = TddRepo.config

        def config(self, **kw):
            body = yaml.safe_load(original(self, **kw))
            body["verifier"] = verifier
            return yaml.safe_dump(body)

        monkeypatch.setattr(TddRepo, "config", config)
        return {
            "profiles": {"auditor": {"adapter": "fake", "vendor": "thirdco"}},
            "roles": {"verifier_agent": ["auditor"]},
        }

    return apply
