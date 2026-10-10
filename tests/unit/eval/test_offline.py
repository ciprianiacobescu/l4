"""L4-EVAL-018: the harness side of `l4 eval` opens no socket; the cold uv cache is a named, fixable condition."""

import json
from pathlib import Path

from l4.eval.cellconfig import SETUP_COMMAND, render_config
from l4.eval.run import Deps
from l4.eval.score import score_implementer

from ._fakerun import ScriptedRunner
from ._go import go
from ._ledgers import ev, green_ledger


def test_dry_run_starts_nothing_and_opens_no_socket(make_app, seeds_root: Path, no_sockets, capsys) -> None:
    scripted = ScriptedRunner()
    go(make_app(), seeds_root, impl=("p1",), judge=("j1",), ref_judge="j2", deps=Deps(runner=scripted))
    assert scripted.calls == [] and no_sockets == []
    assert "cell implementer p1" in capsys.readouterr().out


def test_a_full_run_with_a_scripted_child_opens_no_socket(
    make_app, seeds_root: Path, no_sockets, tmp_path: Path
) -> None:
    scripted = ScriptedRunner()
    go(
        make_app(), seeds_root, impl=("p1",), judge=("j1",), ref_judge="j2", units=("add-shelf-code",),
        out=tmp_path / "o", dry_run=False, deps=Deps(runner=scripted, version_of=lambda a: "1"),
    )  # fmt: skip
    assert len(scripted.calls) == 2 and no_sockets == []
    assert (tmp_path / "o" / "scorecard.json").is_file()


def test_rendering_a_config_and_scoring_open_no_socket(no_sockets) -> None:
    base = {"profiles": {"p": {"adapter": "opencode", "model": "o/a", "vendor": "v"}, "j": {"adapter": "codex"}}}
    assert render_config(base, "implementer", "p", ref_judge="j")["gates"]["setup"] == [SETUP_COMMAND]
    score_implementer(green_ledger(), {})
    assert no_sockets == []


def test_the_scratch_setup_never_reaches_an_index() -> None:
    assert SETUP_COMMAND == "uv sync --frozen --offline"


def test_a_cold_cache_is_invalid_and_names_the_fix(make_app, seeds_root: Path, tmp_path: Path) -> None:
    out = tmp_path / "o"

    def behaviour(role, profile, unit):
        events = [ev("gate.finished", name="setup", status="fail", exit_code=2, reason="exit code 2", log="setup.log")]
        return events, None, 13, "gate setup fail"

    def runner(argv, env, cwd, timeout):
        (cwd / "setup.log").write_text(
            "× Failed to download `pygments==2.21.0`\n╰─▶ Network connectivity is disabled, but the"
        )
        return ScriptedRunner(behaviour)(argv, env, cwd, timeout)

    go(
        make_app(), seeds_root, judge=("j1",), units=("add-shelf-code",), out=out, dry_run=False,
        deps=Deps(runner=runner, version_of=lambda a: "1"),
    )  # fmt: skip
    (result,) = [json.loads(p.read_text()) for p in (out / "cells").glob("*/result.json")]
    assert result["status"] == "invalid" and result["invalid_reason"] == "setup_offline_cache_cold"
    assert "l4 eval --warm-cache" in result["errors"][0]["detail"]
