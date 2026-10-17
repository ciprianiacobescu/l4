"""TOOL-001 (L4-CI-005): a gate command whose first word is not on the gate PATH is named, with the ci.toolchains
hint; a warning in `l4 doctor --adoption`, an error in a CI run."""

import dataclasses

import pytest

from l4.config.schema import L4Config
from l4.doctor.checks_tools import TOOL_001, command_words


def gates(**over):
    return L4Config.model_validate({"gates": over})


def run(make_ctx, cfg, tools=None, *, adoption=False):
    ctx, _ = make_ctx(tools if tools is not None else {"uv": "uv 0.10", "go": "go1.26"}, cfg=cfg)
    return TOOL_001.run(dataclasses.replace(ctx, adoption=adoption))


def test_scn_ci_23_a_gate_command_not_on_the_path_is_named_with_the_hint(make_ctx):
    """SCN-CI-23 (-): `golangci-lint run ./...` with no golangci-lint on the gate PATH."""
    result = run(make_ctx, gates(lint=["golangci-lint run ./..."]), adoption=True)
    assert result.status == "fail"
    assert "golangci-lint" in result.message and "gate PATH" in result.message and "gates.lint" in result.message
    assert result.fix_hint and "ci.toolchains" in result.fix_hint
    assert result.severity == "warn"  # l4 doctor --adoption


def test_in_a_ci_run_the_miss_is_an_error(make_ctx):
    result = run(make_ctx, gates(lint=["golangci-lint run ./..."]), adoption=False)
    assert result.status == "fail" and result.severity == "error"


def test_commands_on_the_path_pass(make_ctx):
    result = run(make_ctx, gates(build=["go build ./..."], test={"command": "go test ./..."}))
    assert result.status == "pass", result.message


def test_every_kind_of_gate_is_read(make_ctx):
    cfg = gates(
        setup=["pnpm install"],
        build=["cargo build"],
        lint=["golangci-lint run"],
        typecheck=["tsc --noEmit"],
        test={"command": "ginkgo ./..."},
        e2e={"command": "playwright test"},
        extra=[{"name": "vuln", "command": "govulncheck ./..."}],
    )
    result = run(make_ctx, cfg, {"uv": "x"}, adoption=True)
    for word in ("pnpm", "cargo", "golangci-lint", "tsc", "ginkgo", "playwright", "govulncheck"):
        assert word in result.message, word


def test_a_missing_tool_is_named_once_with_the_gates_that_use_it(make_ctx):
    result = run(make_ctx, gates(lint=["pnpm lint"], test={"command": "pnpm test"}), {"uv": "x"})
    assert result.message.count("pnpm") == 1 and "gates.lint" in result.message and "gates.test" in result.message


@pytest.mark.parametrize(
    ("command", "words"),
    [
        ("go test ./...", ["go"]),
        ("FOO=bar BAZ=1 go vet ./...", ["go"]),
        ("uv run pytest -q", ["uv"]),  # what `uv run` starts is uv's business
        (".venv/bin/pytest", []),  # a path inside the repository
        ("./gradlew test", []),
        ("sh .l4/gates/test.sh", ["sh"]),
        ("cd web && pnpm test", ["pnpm"]),  # `cd` is a builtin
        ("export A=1; go test ./... | tee out.txt", ["go", "tee"]),
        ("go build ./... || true", ["go"]),
        ("", []),
        ("# only a comment", []),
        ("python -m pytest", ["python"]),
    ],
)
def test_command_words(command, words):
    assert command_words(command) == words


def test_no_gate_configured_skips(make_ctx):
    cfg = L4Config.model_validate({"gates": {"test": {"command": ""}}})
    assert run(make_ctx, cfg, {}).status in ("skip", "pass")
