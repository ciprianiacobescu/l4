"""Kiro steering and the OpenSpec context as data (L4-KSP-010, L4-KSP-011; SCN-IMP-290..292, SCN-IMP-284)."""

from pathlib import Path

from l4.specs.steering import (
    decide_steering,
    is_referenced,
    openspec_context,
    parse_front_matter,
    read_steering,
)

from .._kiro_probe import probe_tree


def write(root: Path, name: str, text: str) -> None:
    path = root / ".kiro" / "steering" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def decide(root: Path, paths=(), refs=""):
    files, extra = read_steering(root)
    return files, extra, decide_steering(files, list(paths), refs)


def by_name(decisions):
    return {d.path.rsplit("/", 1)[-1]: d for d in decisions}


def test_a_file_without_front_matter_is_always_included_with_its_body(tmp_path):
    """SCN-IMP-290, reader part."""
    root = probe_tree(tmp_path)
    files, extra, decisions = decide(root)
    assert extra == []
    (tech,) = decisions
    assert tech.as_dict() == {
        "path": ".kiro/steering/tech.md",
        "inclusion": "always",
        "included": True,
        "why": "always",
    }
    assert "STEERING-MARKER" in files[0].body


def test_a_file_match_pattern_applies_to_the_tasks_paths_only(tmp_path):
    """SCN-IMP-291."""
    write(tmp_path, "calc.md", '---\ninclusion: fileMatch\nfileMatchPattern: ["src/calc/**"]\n---\nCalc rules.\n')
    _, _, hit = decide(tmp_path, ["src/calc/tip.py"])
    assert hit[0].as_dict() == {
        "path": ".kiro/steering/calc.md", "inclusion": "fileMatch", "included": True, "why": "matched src/calc/tip.py"
    }  # fmt: skip
    _, _, miss = decide(tmp_path, ["docs/usage.md"])
    assert (miss[0].included, miss[0].why) == (False, "no_match")


def test_a_pattern_given_as_a_string_and_a_pattern_without_a_slash_work(tmp_path):
    write(tmp_path, "one.md", '---\ninclusion: fileMatch\nfileMatchPattern: "src/calc/**"\n---\nOne.\n')
    write(tmp_path, "two.md", "---\ninclusion: fileMatch\nfileMatchPattern: '*.py'\n---\nTwo.\n")
    got = by_name(decide(tmp_path, ["src/calc/tip.py"])[2])
    assert got["one.md"].included and got["two.md"].why == "matched src/calc/tip.py"
    got = by_name(decide(tmp_path, ["docs/usage.md"])[2])
    assert not got["one.md"].included and not got["two.md"].included


def test_manual_steering_needs_its_hash_reference_and_auto_steering_comes_last(tmp_path):
    """SCN-IMP-292, with owner decision 1: an unreferenced auto file is included when the budget has room."""
    write(tmp_path, "money.md", "---\ninclusion: manual\n---\nAmounts are Decimal.\n")
    write(
        tmp_path, "api.md",
        "---\ninclusion: auto\nname: api-design\ndescription: REST conventions\n---\nREST rules.\n",
    )  # fmt: skip
    write(tmp_path, "bad.md", "---\ninclusion: [\n---\nbroken\n")
    _, _, got = decide(tmp_path, refs="follow #money for amounts")
    named = by_name(got)
    assert (named["money.md"].included, named["money.md"].why) == (True, "referenced")
    assert (named["api.md"].included, named["api.md"].why) == (True, "auto")  # when the budget has room
    assert (named["bad.md"].included, named["bad.md"].why) == (False, "bad_front_matter")
    assert named["api.md"].bucket > named["money.md"].bucket  # auto is met after the referenced ones
    _, _, again = decide(tmp_path, refs="see #api-design")
    assert (by_name(again)["api.md"].why, by_name(again)["api.md"].bucket) == ("referenced", named["money.md"].bucket)
    assert by_name(again)["money.md"].why == "not_referenced" and not by_name(again)["money.md"].included


def test_a_reference_is_a_token_not_a_part_of_a_word_or_a_path(tmp_path):
    write(tmp_path, "money.md", "---\ninclusion: manual\n---\nx\n")
    (money,), _ = read_steering(tmp_path)
    assert is_referenced(money, "follow #money for amounts") and is_referenced(money, "#money.")
    assert not is_referenced(money, "see #moneyx") and not is_referenced(money, "docs/#money")
    assert is_referenced(money, "#[[file:.kiro/steering/money.md]]") and is_referenced(
        money, "read .kiro/steering/money.md"
    )
    assert not is_referenced(money, "money without a hash")


def test_a_linked_steering_directory_gives_one_decision_and_reads_nothing(tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "x.md").write_text("secret\n")
    (tmp_path / ".kiro").mkdir()
    (tmp_path / ".kiro" / "steering").symlink_to(elsewhere)
    files, decisions = read_steering(tmp_path)
    assert files == [] and [d.as_dict() for d in decisions] == [
        {"path": ".kiro/steering", "inclusion": "none", "included": False, "why": "symlink"}
    ]


def test_a_linked_file_is_named_and_the_home_steering_is_never_read(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".kiro" / "steering").mkdir(parents=True)
    (home / ".kiro" / "steering" / "global.md").write_text("HOME-STEERING\n")
    monkeypatch.setenv("HOME", str(home))
    repo = tmp_path / "repo"
    write(repo, "real.md", "Real.\n")
    (repo / ".kiro" / "steering" / "link.md").symlink_to(repo / ".kiro" / "steering" / "real.md")
    files, _, decisions = decide(repo)
    assert [f.path for f in files] == [".kiro/steering/link.md", ".kiro/steering/real.md"]
    assert by_name(decisions)["link.md"].why == "symlink" and by_name(decisions)["real.md"].included
    assert all("HOME-STEERING" not in f.body for f in files) and "global.md" not in {Path(f.path).name for f in files}


def test_front_matter_needs_both_fences_and_a_mapping():
    meta, body = parse_front_matter("---\ninclusion: always\n---\nbody\n")
    assert meta == {"inclusion": "always"} and body == "body\n"
    assert parse_front_matter("---\nno closing fence\n") == ({}, "---\nno closing fence\n")
    assert parse_front_matter("plain\n") == ({}, "plain\n")
    assert parse_front_matter("﻿---\n---\nx\n") == ({}, "x\n")


def test_a_file_match_without_a_pattern_and_an_unknown_inclusion_are_bad(tmp_path):
    write(tmp_path, "a.md", "---\ninclusion: fileMatch\n---\nx\n")
    write(tmp_path, "b.md", "---\ninclusion: sometimes\n---\nx\n")
    write(tmp_path, "c.md", "---\n- a list\n---\nx\n")
    write(tmp_path, "d.md", "---\ndescription: no inclusion key\n---\nkept\n")
    got = by_name(decide(tmp_path)[2])
    assert (got["a.md"].why, got["b.md"].why, got["c.md"].why) == ("bad_front_matter",) * 3
    assert (got["d.md"].included, got["d.md"].why) == (True, "always")  # a mapping without `inclusion` is always


def test_the_openspec_context_is_read_and_its_rules_are_not(tmp_path):
    """SCN-IMP-284, reader part."""
    (tmp_path / "openspec").mkdir()
    (tmp_path / "openspec" / "config.yaml").write_text(
        'context: "Runtime: Python >= 3.11, uv, src layout"\nrules:\n  tasks:\n    - Tasks are TDD-shaped\n'
    )
    text, decision = openspec_context(tmp_path, "openspec")
    assert text == "Runtime: Python >= 3.11, uv, src layout"
    assert decision is not None and decision.as_dict() == {
        "path": "openspec/config.yaml#context", "inclusion": "context", "included": True, "why": "context"
    }  # fmt: skip


def test_an_openspec_config_that_does_not_parse_gives_no_context_and_a_decision(tmp_path):
    (tmp_path / "openspec").mkdir()
    (tmp_path / "openspec" / "config.yaml").write_text("context: [unclosed\n")
    text, decision = openspec_context(tmp_path, "openspec")
    assert text is None and decision is not None
    assert (decision.included, decision.why, decision.inclusion) == (False, "bad_front_matter", "context")


def test_an_openspec_config_without_a_context_or_with_none_adds_nothing(tmp_path):
    assert openspec_context(tmp_path, "openspec") == (None, None)
    (tmp_path / "openspec").mkdir()
    (tmp_path / "openspec" / "config.yaml").write_text("rules:\n  tasks: [x]\n")
    assert openspec_context(tmp_path, "openspec") == (None, None)
    (tmp_path / "openspec" / "config.yaml").write_text("context: 5\n")
    text, decision = openspec_context(tmp_path, "openspec")
    assert text is None and decision is not None and decision.why == "bad_front_matter"
