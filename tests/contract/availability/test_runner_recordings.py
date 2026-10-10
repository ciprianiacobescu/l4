"""G14: what the runner's own CLIs answer to the zero-cost probes, recorded by scripts/runner/record-probes.sh."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from l4.availability.quota import codex_windows, parse_usage

RECORDED = Path(__file__).resolve().parents[2] / "fixtures" / "recorded"
KIRO = RECORDED / "kiro-cli" / "2.27.1"
CLAUDE = RECORDED / "claude-code" / "2.1.288"
CODEX = RECORDED / "codex" / "0.160.0"
OPENCODE = RECORDED / "opencode" / "1.18.34"
RUNNER_FILES = [
    KIRO / "runner-version.stdout.txt", KIRO / "runner-whoami.exit.txt", KIRO / "runner-whoami.stdout.txt",
    KIRO / "runner-whoami.stderr.txt", CLAUDE / "runner-usage-pro.json", CODEX / "runner-app-server.json",
    OPENCODE / "runner-version.stdout.txt",
]  # fmt: skip


def test_runner_recordings_parse():
    # Kiro, logged out: exit 1 and `{"account": null}` on stdout, nothing on stderr. The adapter (M1.2 Stage B) maps
    # this to "kiro-cli installed, not authenticated".
    assert (KIRO / "runner-version.stdout.txt").read_text().strip() == "kiro-cli 2.27.1"
    assert (KIRO / "runner-whoami.exit.txt").read_text().strip() == "1"
    assert json.loads((KIRO / "runner-whoami.stdout.txt").read_text()) == {"account": None}
    assert (KIRO / "runner-whoami.stderr.txt").read_text().strip() == ""

    # Claude `pro`: `/usage` prints a session window without a reset and a weekly one with "Oct 8, 11:59am (UTC)"
    usage = json.loads((CLAUDE / "runner-usage-pro.json").read_text())
    assert usage["is_error"] is False
    windows = parse_usage(usage["result"], datetime(2026, 10, 4, 9, 0, tzinfo=UTC))
    assert [w.name for w in windows] == ["session", "weekly (all models)"] and windows[0].resets_at is None

    # Codex on the runner's login: ChatGPT plus, both windows, and the reset-credits object is present but unused
    session = json.loads((CODEX / "runner-app-server.json").read_text())
    account = session["account_read"]["result"]["account"]
    assert account == {"type": "chatgpt", "planType": "plus"}
    result = session["rate_limits_read"]["result"]
    parsed, extra = codex_windows(result, None)
    assert [w.window_minutes for w in parsed] == [300, 10080] and extra is None
    assert result["rateLimitResetCredits"]["availableCount"] >= 0

    assert (OPENCODE / "runner-version.stdout.txt").read_text().strip() == "1.18.34"


@pytest.mark.parametrize("path", RUNNER_FILES, ids=lambda p: p.name)
def test_no_recording_holds_an_identity(path: Path):
    text = path.read_text()
    assert "@" not in text
    for key in ("email", "chatgptAccountId", "accountId"):
        assert f'"{key}"' not in text
