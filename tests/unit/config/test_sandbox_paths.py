"""L4-SEC-033: `sandbox.tool_paths` and `sandbox.setup_paths` are checked at load; the message names the key and never
the path."""

from pathlib import Path

import pytest

from l4.config.loader import ConfigSchemaError, load_config
from l4.exitcodes import ExitCode, L4Exit
from l4.sandbox import home as homemod


def write_config(repo: Path, text: str) -> None:
    path = repo / ".l4" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.mark.parametrize("key", ["tool_paths", "setup_paths"])
@pytest.mark.parametrize(
    "entry", ["/", "~", "~/.codex/bin", "~/.codex", "~/.local/share", "relative", "~/.claude.json"]
)
def test_a_tool_path_inside_a_login_is_refused(tmp_path: Path, key, entry):  # SCN-SEC-80
    write_config(tmp_path, f'version: 1\nsandbox:\n  {key}: ["{entry}"]\n')
    with pytest.raises(ConfigSchemaError) as caught:
        load_config(tmp_path)
    assert caught.value.code is ExitCode.USAGE_ERROR
    text = str(caught.value)
    assert f"sandbox.{key}" in text
    if len(entry) > 1:
        assert entry not in text  # never the configured path


@pytest.mark.parametrize("key", ["tool_paths", "setup_paths"])
def test_a_path_that_holds_no_login_loads(tmp_path: Path, key):
    write_config(tmp_path, f'version: 1\nsandbox:\n  {key}: ["~/.local/opt", "/opt/tools", "~/.npmrc"]\n')
    assert getattr(load_config(tmp_path).sandbox, key) == ["~/.local/opt", "/opt/tools", "~/.npmrc"]


def test_a_configured_login_path_is_checked_too(tmp_path: Path):
    write_config(
        tmp_path,
        'version: 1\nsandbox:\n  credential_paths:\n    codex: ["~/.cache/codex-login"]\n  tool_paths: ["~/.cache"]\n',
    )
    with pytest.raises(ConfigSchemaError, match="sandbox.tool_paths"):
        load_config(tmp_path)


def test_an_entry_that_contains_the_runner_cache_stops_the_run(tmp_path: Path):
    cache = tmp_path / "runner-cache"
    cache.mkdir()
    with pytest.raises(L4Exit) as caught:
        homemod.tool_paths(
            {"PATH": "/usr/bin"}, home=tmp_path / "home", cache_root=cache, kind="gate", configured=[str(tmp_path)]
        )
    assert caught.value.code is ExitCode.USAGE_ERROR and "sandbox.tool_paths" in str(caught.value)
    assert str(tmp_path) not in str(caught.value)
