"""M1.5 Exit B, live: the real `claude` test writer, and real Playwright on the fixture web app (base fails, head
passes). `L4_LIVE=1`, a logged-in `claude`, and for the second playwright and pytest-playwright plus a Chromium on the
host, none of them project dependencies: run it as
`L4_LIVE=1 uv run --with playwright==1.63.0 --with pytest-playwright==0.9.0 pytest <this file>`.
The gate's environment has a fake home, so the browsers come in the way production provides them: the read-only
`playwright` cache mount (`$L4_CACHE/shared/ms-playwright`)."""

import importlib.util
import os
import shutil
from pathlib import Path

import pytest

from l4.agents.base import PermissionPolicy, RunRequest, Usage
from l4.agents.claude_code import ClaudeCodeAdapter
from l4.config.defaults import cache_root
from l4.config.schema import Profile
from l4.llm.agent_judge import AgentJudge, StructuredResult
from l4.specs.base import Criterion, Framework
from l4.verifier.generate import generate_ui_test
from l4.verifier.playwright import base_checkout
from l4.verifier.testwriter import request_test

from .._web_bench import stage_base_and_head, web_bench
from ..implementer.conftest import make_bench  # noqa: F401

pytestmark = pytest.mark.live
CID = "C-de7f2d3f"
CRITERION = Criterion(CID, "web › Cart › Count", Framework.OPENSPEC, "web", "Cart", "Count",
                      "WHEN the cart page opens THEN it shows 4 items", "spec.md", 3)  # fmt: skip
PAGE = '<h1>Your cart</h1><p data-testid="item-count">4 items</p>'


def real_claude(tmp_path: Path) -> AgentJudge:
    if shutil.which("claude") is None:
        pytest.skip("claude is not installed")
    env = {k: os.environ[k] for k in ("PATH", "HOME", "USER") if k in os.environ}
    env |= {"LANG": "C.UTF-8", "TMPDIR": str(tmp_path)}
    work = tmp_path / "wt"
    work.mkdir()

    def make(prompt: str, schema: dict, timeout_s: int) -> RunRequest:
        return RunRequest(
            profile=Profile(adapter="claude-code", model="sonnet", auth="subscription", vendor="anthropic"),
            role="judge", cwd=work, prompt=prompt, result_path=tmp_path / "result.json",
            raw_events_path=tmp_path / "raw" / "writer.jsonl", env={**env, **ClaudeCodeAdapter.extra_env},
            result_schema=schema, permission_policy=PermissionPolicy("judge"), timeout_s=timeout_s,
        )  # fmt: skip

    return AgentJudge(ClaudeCodeAdapter(), make)


def test_the_real_claude_writes_a_test_in_the_generated_test_schema(tmp_path: Path):
    reply = request_test(
        real_claude(tmp_path), kind="e2e", criterion_id=CID, criterion_text=CRITERION.text,
        data_blocks=[("page snapshot", PAGE)], timeout_s=240,
    )  # fmt: skip
    assert reply.status in ("ok", "not_testable"), reply.detail
    assert reply.status != "ok" or "def test_" in (reply.test.code if reply.test else "")


def host_browsers() -> Path | None:
    """The host's Playwright browsers directory, if it holds a Chromium."""
    explicit = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    home = Path.home()
    for candidate in (
        Path(explicit) if explicit else None,
        home / "Library/Caches/ms-playwright",
        home / ".cache/ms-playwright",
    ):
        if candidate is not None and candidate.is_dir() and any(candidate.glob("chromium*")):
            return candidate
    return None


@pytest.mark.skipif(
    importlib.util.find_spec("playwright") is None or importlib.util.find_spec("pytest_playwright") is None,
    reason="playwright and pytest-playwright are not installed (see the module docstring)",
)
def test_real_playwright_fails_at_base_and_passes_at_head(make_bench, tdd_repo, raw):  # noqa: F811
    browsers = host_browsers()
    if browsers is None:
        pytest.skip("no Chromium in PLAYWRIGHT_BROWSERS_PATH, ~/Library/Caches/ms-playwright or ~/.cache/ms-playwright")
    mount = cache_root(tdd_repo.environ) / "shared" / "ms-playwright"
    mount.parent.mkdir(parents=True)
    mount.symlink_to(browsers, target_is_directory=True)  # before the bench: an absent read-only cache is not mounted
    bench = web_bench(make_bench)
    base = stage_base_and_head(bench, raw)
    code = (
        "import os\nfrom playwright.sync_api import Page, expect\n\n\n"
        "def test_count(page: Page):\n    page.goto(os.environ['L4_E2E_BASE_URL'])\n"
        "    expect(page.get_by_test_id('item-count')).to_have_text('4 items')\n"
    )

    class Fixed:
        def complete_structured(self, *args, **kwargs):
            return StructuredResult("ok", {"criterion": CID, "code": code}, "fixed", Usage())

    with base_checkout(bench.wb, base) as tree:
        done = generate_ui_test(bench.wb, Fixed(), CRITERION, tree, ui_diff="", snapshot=PAGE)
    assert done.accepted, done.reason
