"""L4-EVAL-016: scorecard.json and scorecard.md are rewritten atomically after every cell, and nothing in the run
directory holds a raw prompt or an unredacted log."""

import json
from pathlib import Path

from l4.eval.run import Deps
from l4.eval.scorecard import canonical_json
from l4.redact import Redactor
from l4.schemacheck import validate

from ._fakerun import ScriptedRunner
from ._go import go
from ._ledgers import green_ledger

SECRET = "sk-ant-abcdefghijklmnopqrstuvwx"


def deps(runner) -> Deps:
    return Deps(runner=runner, version_of=lambda adapter: "1.2.3")


def test_the_scorecard_is_valid_and_partial_after_every_cell(make_app, seeds_root: Path, tmp_path: Path) -> None:
    from importlib import resources

    out = tmp_path / "out"
    schema = json.loads(resources.files("l4.eval").joinpath("scorecard.schema.json").read_text(encoding="utf-8"))
    seen: list[tuple[int, bool]] = []
    scripted = ScriptedRunner()

    def watching(argv, env, cwd, timeout):
        path = out / "scorecard.json"
        if path.exists():
            card = json.loads(path.read_text())
            assert validate(card, schema) == []
            seen.append((len(card["cells"]), card["complete"]))
        return scripted(argv, env, cwd, timeout)

    go(make_app(), seeds_root, impl=("p1",), ref_judge="j1", out=out, dry_run=False, deps=deps(watching))
    assert seen == [(1, False), (2, False)]  # before the 2nd and 3rd cell: a valid partial scorecard
    final = json.loads((out / "scorecard.json").read_text())
    assert final["complete"] is True and len(final["cells"]) == 3
    assert (out / "scorecard.md").read_text().startswith("# l4 eval scorecard\n")


def test_the_files_are_written_atomically(make_app, seeds_root: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    go(
        make_app(),
        seeds_root,
        judge=("j1",),
        units=("add-shelf-code",),
        out=out,
        dry_run=False,
        deps=deps(ScriptedRunner()),
    )
    assert sorted(p.name for p in out.iterdir() if p.is_file()) == ["scorecard.json", "scorecard.md"]


def test_the_scorecard_holds_the_environment_and_the_seed_set(make_app, seeds_root: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    go(
        make_app(),
        seeds_root,
        impl=("p1",),
        ref_judge="j1",
        units=("add-shelf-code",),
        k=1,
        out=out,
        dry_run=False,
        runner=True,
        deps=deps(ScriptedRunner()),
    )
    card = json.loads((out / "scorecard.json").read_text())
    assert card["seeds"]["units"] == ["add-late-fee", "add-reorder-quantity", "add-shelf-code", "add-tip-amount"]
    assert card["env"]["seed_set_sha256"] == card["seeds"]["sha256"] and card["env"]["machine"]["runner"] is True
    assert set(card["env"]["cli_versions"]) == {"p1", "j1"}
    assert card["env"]["cli_versions"]["p1"]["version"] == "1.2.3"
    assert (out / "scorecard.json").read_text() == canonical_json(card)


def test_no_file_holds_a_secret_a_prompt_or_a_workspace(make_app, seeds_root: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    scripted = ScriptedRunner(lambda role, profile, unit: (green_ledger(), None, 0, f"agent printed {SECRET}"))

    def runner(argv, env, cwd, timeout):
        prompt = cwd / ".l4-out" / "agent" / "r-1" / "prompt.md"
        prompt.parent.mkdir(parents=True)
        prompt.write_text("RAW-PROMPT-MARKER the whole prompt")
        return scripted(argv, env, cwd, timeout)

    app = make_app()
    object.__setattr__(app, "redactor", Redactor({"K": SECRET}))
    go(
        app,
        seeds_root,
        impl=("p1",),
        ref_judge="j1",
        units=("add-shelf-code",),
        out=out,
        dry_run=False,
        deps=deps(runner),
    )
    texts = {p: p.read_text(errors="replace") for p in out.rglob("*") if p.is_file()}
    assert texts
    for path, text in texts.items():
        assert SECRET not in text and "RAW-PROMPT-MARKER" not in text, path
    assert any("[REDACTED" in t for p, t in texts.items() if p.name == "run.log")
    assert not any(p.name in ("ws", "cache") for p in out.rglob("*"))
