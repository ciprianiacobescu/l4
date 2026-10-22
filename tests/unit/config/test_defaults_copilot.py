"""L4-PRV-048, L4-PRV-049: the Copilot package cache, its version environment and its login path."""

from pathlib import Path

from l4.agents import gate
from l4.config import defaults


def test_the_cache_lies_under_l4_home():
    assert defaults.copilot_cache({"L4_HOME": "/x"}) == Path("/x/copilot-cache")
    assert defaults.copilot_cache({"HOME": "/h"}) == Path("/h/.local/share/l4/copilot-cache")
    assert defaults.COPILOT_CACHE_DIR == "copilot-cache"


def test_copilot_env_is_the_version_environment():
    assert defaults.copilot_env({"L4_HOME": "/x", "CI": "true", "HOME": "/h"}) == {
        "COPILOT_AUTO_UPDATE": "false",
        "XDG_CACHE_HOME": "/x/copilot-cache",
    }


def test_the_login_path_and_the_oauth_list():
    assert defaults.CREDENTIAL_PATHS["copilot-cli"] == ("~/.copilot",)
    assert "COPILOT_GITHUB_TOKEN" in defaults.DEFAULT_REDACT_ENV
    assert "copilot-cli" not in gate.OAUTH_ADAPTERS
