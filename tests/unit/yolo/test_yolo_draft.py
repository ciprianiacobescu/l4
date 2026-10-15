# ruff: noqa: F811
"""`l4 yolo draft` (L4-YOLO-018, design D15; SCN-YOLO-37, SCN-YOLO-38): the plan file scaffolded or updated from the
specs of the working tree, with no dependency and no git write beyond the fetch of the unit refs."""

import dataclasses
import json
import subprocess
import sys
from pathlib import Path

import pytest

import l4.yolo.commands as commands
from l4.yolo.draft import Found, derived_parents, new_draft, unlisted, update_draft
from l4.yolo.model import Plan, load_plan
from l4.yolo.plans import _plan_file, plan_files

from .yolo_cmd_world import A, B, ev, plan_doc, world  # noqa: F401

C, K1, K2 = "openspec:add-c", "kiro:k1", "kiro:k2"
SPEC_C = (
    "## ADDED Requirements\n\n### Requirement: C counts\nThe `other()` function SHALL return 2.\n\n"
    "#### Scenario: Other\n- **WHEN** `other()` is called\n- **THEN** it returns 2\n"
)


def kiro(name: str) -> dict[str, str]:
    return {f".kiro/specs/{name}/requirements.md": f"# {name}\n", f".kiro/specs/{name}/tasks.md": "- [ ] 1. Do it\n"}


def wide(world, merged: tuple[str, ...] = ()):
    """Three OpenSpec changes and two Kiro specs in the clone's working tree; `merged` units read as merged."""
    world.push(
        {"openspec/changes/add-c/tasks.md": "## 1. C\n\n- [ ] 1.1 Add\n", "openspec/changes/add-c/proposal.md": "# C\n",
         "openspec/changes/add-c/specs/c/spec.md": SPEC_C, **kiro("k1"), **kiro("k2")},
        "more units",
    )  # fmt: skip
    world.pull()
    return phases(merged)


def phases(merged):
    real = commands.discover

    def discover(cfg, git, providers, wanted=()):
        rows = real(cfg, git, providers, wanted)
        return [
            (
                p,
                dataclasses.replace(s, state=s.state.model_copy(update={"phase": "merged"}))
                if s.ref.id in merged
                else s,
            )
            for p, s in rows
        ]

    return discover


def draft_with(monkeypatch, world, merged=()):
    monkeypatch.setattr(commands, "discover", wide(world, merged))


def plan_path(world, plan_id="p1") -> Path:
    return world.app.repo / ".l4" / "plans" / f"{plan_id}.json"


def snapshot(world):
    """HEAD, the local branches, tags and plan refs, and the history. The remote-tracking refs are left out: the draft
    fetches them (L4-YOLO-018) and writes no other ref."""
    git = world.clone
    return (
        git.run("rev-parse", "HEAD").stdout,
        git.run("for-each-ref", "refs/heads", "refs/tags", "refs/l4/plans").stdout,
        git.run("log", "--branches", "--oneline").stdout,
    )


def test_a_draft_lists_every_unplanned_unit_without_dependencies(world, monkeypatch, capsys):  # SCN-YOLO-37
    draft_with(monkeypatch, world, merged=(K2,))
    before = snapshot(world)
    assert world.l4("draft", "p1") == 0
    text = plan_path(world).read_text(encoding="utf-8")
    assert text.endswith("}\n") and text == json.dumps(json.loads(text), indent=2) + "\n"
    plan = load_plan(text, file_name=".l4/plans/p1.json")
    assert isinstance(plan, Plan)
    assert [b.id for b in plan.batches] == ["unplanned"]
    assert plan.unit_ids() == [K1, B, C, A]  # id order
    assert all(u.depends_on == [] for u in plan.units())
    assert [(x.id, x.reason) for x in plan.exclude] == [(K2, "already merged")]
    assert plan.target == "main" and plan.merge == "human"
    assert snapshot(world) == before  # nothing committed, no ref
    assert world.clone.run("status", "--porcelain", ".l4/plans").stdout.strip() == "?? .l4/plans/"
    out = capsys.readouterr().out
    assert f"added: {A}" in out and f"added: {K2} (excluded: already merged)" in out
    assert "validate_plan.py" in out and "l4 yolo check p1" in out


def test_a_fresh_draft_passes_the_standalone_validator(world, monkeypatch):
    draft_with(monkeypatch, world, merged=(K2,))
    assert world.l4("draft", "p1") == 0
    script = Path(__file__).resolve().parents[3] / "scripts" / "validate_plan.py"
    done = subprocess.run(
        [sys.executable, "-I", str(script), "--repo", str(world.app.repo)], capture_output=True, text=True
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "order: " in done.stdout and "wave 1: " in done.stdout


def test_target_and_merge_are_written(world, monkeypatch):
    draft_with(monkeypatch, world)
    assert world.l4("draft", "p2", "--target", "release", "--merge", "auto") == 0
    plan = json.loads(plan_path(world, "p2").read_text(encoding="utf-8"))
    assert (plan["target"], plan["merge"]) == ("release", "auto")


def test_an_existing_file_is_refused_without_update(world, monkeypatch, capsys):
    draft_with(monkeypatch, world)
    plan_path(world).parent.mkdir(parents=True)
    plan_path(world).write_text("keep me\n", encoding="utf-8")
    assert world.l4("draft", "p1") == 2
    assert plan_path(world).read_text(encoding="utf-8") == "keep me\n"
    assert "exists" in capsys.readouterr().err


def test_update_needs_a_file(world, monkeypatch, capsys):
    draft_with(monkeypatch, world)
    assert world.l4("draft", "p1", "--update") == 2
    assert not plan_path(world).exists()


def test_update_refuses_a_file_that_is_not_a_plan(world, monkeypatch, capsys):
    draft_with(monkeypatch, world)
    plan_path(world).parent.mkdir(parents=True)
    plan_path(world).write_text(json.dumps({"plan_id": "p1"}), encoding="utf-8")
    assert world.l4("draft", "p1", "--update") == 2
    assert "not a valid plan" in capsys.readouterr().err


def test_update_takes_no_target_or_merge(world, monkeypatch):
    draft_with(monkeypatch, world)
    assert world.l4("draft", "p1") == 0
    assert world.l4("draft", "p1", "--update", "--target", "x") == 2


def test_an_update_adds_a_new_spec_and_keeps_the_persons_edits(world, monkeypatch, capsys):  # SCN-YOLO-38
    draft_with(monkeypatch, world)
    doc = {
        "merge": "human",
        "schema": "l4/delivery-plan@1",
        "plan_id": "p1",
        "target": "main",  # the person's key order
        "batches": [
            {"id": "w1", "units": [{"id": A, "depends_on": []}, {"id": B, "depends_on": [A]}]},
            {"id": "w2", "depends_on": ["w1"], "acceptance_profile": "all", "units": [{"id": K1}]},
        ],
        "exclude": [{"id": K2, "reason": "in review before the plan"}],
        "limits": {"max_cost_usd": 12},
    }
    plan_path(world).parent.mkdir(parents=True)
    plan_path(world).write_text(json.dumps(doc, indent=4), encoding="utf-8")
    assert world.l4("draft", "p1", "--update") == 0
    out = capsys.readouterr().out
    assert f"added: {C}" in out and out.count("added:") == 1
    after = json.loads(plan_path(world).read_text(encoding="utf-8"))
    assert list(after) == [
        *doc,
    ] and list(after)[:3] == ["merge", "schema", "plan_id"]
    expected = json.loads(json.dumps(doc))
    expected["batches"].append({"id": "unplanned", "depends_on": [], "units": [{"id": C, "depends_on": []}]})
    assert after == expected  # only the new batch differs


def test_an_update_appends_to_an_existing_unplanned_batch_and_to_exclude(world, monkeypatch):
    draft_with(monkeypatch, world, merged=(K2,))
    doc = plan_doc({A: [], B: [A]}, batches=None)
    doc["batches"] = [{"id": "unplanned", "units": [{"id": A}, {"id": B, "depends_on": [A]}]}]
    plan_path(world).parent.mkdir(parents=True)
    plan_path(world).write_text(json.dumps(doc), encoding="utf-8")
    assert world.l4("draft", "p1", "--update") == 0
    after = json.loads(plan_path(world).read_text(encoding="utf-8"))
    assert [u["id"] for u in after["batches"][0]["units"]] == [A, B, K1, C]
    assert after["batches"][0]["units"][1] == {"id": B, "depends_on": [A]}
    assert after["exclude"] == [{"id": K2, "reason": "already merged"}]
    assert len(after["batches"]) == 1


def test_an_update_with_nothing_to_add_leaves_the_file_as_it_is(world, monkeypatch, capsys):
    draft_with(monkeypatch, world)
    assert world.l4("draft", "p1") == 0
    plan_path(world).write_text(plan_path(world).read_text(encoding="utf-8").replace("  ", "\t"), encoding="utf-8")
    raw = plan_path(world).read_bytes()
    capsys.readouterr()
    assert world.l4("draft", "p1", "--update") == 0
    assert plan_path(world).read_bytes() == raw
    assert "nothing to add" in capsys.readouterr().out


def test_a_listed_unit_no_provider_finds_is_gone_and_kept(world, monkeypatch, capsys):
    draft_with(monkeypatch, world)
    doc = plan_doc({A: [], B: [A], "openspec:vanished": [B]}, exclude=[{"id": "kiro:old", "reason": "r"}])
    plan_path(world).parent.mkdir(parents=True)
    plan_path(world).write_text(json.dumps(doc), encoding="utf-8")
    assert world.l4("draft", "p1", "--update") == 0
    out = capsys.readouterr().out
    assert "gone: openspec:vanished" in out and "gone: kiro:old" in out
    after = json.loads(plan_path(world).read_text(encoding="utf-8"))
    assert "openspec:vanished" in [u["id"] for b in after["batches"] for u in b["units"]]
    assert after["exclude"][0] == {"id": "kiro:old", "reason": "r"}


def test_a_unit_another_plan_file_lists_is_not_drafted_again(world, monkeypatch):
    draft_with(monkeypatch, world)
    other = plan_doc({A: [], B: [A], K1: []}, plan_id="p0", exclude=[{"id": K2, "reason": "later"}])
    plan_path(world, "p0").parent.mkdir(parents=True)
    plan_path(world, "p0").write_text(json.dumps(other), encoding="utf-8")
    assert world.l4("draft", "p1") == 0
    plan = load_plan(plan_path(world).read_text(encoding="utf-8"), file_name=".l4/plans/p1.json")
    assert plan.unit_ids() == [C] and plan.exclude == []


def test_an_active_plan_is_warned_about_on_update(world, monkeypatch, capsys):
    draft_with(monkeypatch, world)
    assert world.l4("draft", "p1") == 0
    monkeypatch.setattr(
        commands,
        "local_plans",
        lambda git: {
            "p1": [ev("plan.activated", plan_digest="x", digests={}, by="a", reason="go", limits={})]
        },  # fmt: skip
    )
    plan_path(world).write_text(plan_path(world).read_text(encoding="utf-8").replace(f'"{C}"', '"openspec:zz"'),
                                encoding="utf-8")  # fmt: skip
    capsys.readouterr()
    assert world.l4("draft", "p1", "--update") == 0
    out = capsys.readouterr().out
    assert "warning: plan p1 is active here" in out and "inputs_changed" in out


def test_an_invalid_plan_id_is_a_usage_error(world):
    assert world.l4("draft", "Bad_Id") == 2


# --- the pure part ---------------------------------------------------------------------------------------------------


def files(*docs):
    return [_plan_file(f".l4/plans/{d['plan_id']}.json", json.dumps(d)) for d in docs]


def test_derived_parents_follow_the_fix_and_follow_up_name_patterns():
    assert derived_parents("openspec:a-fix-2") == ["openspec:a"]
    assert derived_parents("kiro:a-followup-1") == ["kiro:a"]
    assert derived_parents("openspec:a-followup-1-fix-3") == ["openspec:a-followup-1", "openspec:a"]
    assert derived_parents("openspec:a-fix") == [] and derived_parents("openspec:a-fix-0") == []


def test_a_derived_unit_is_covered_by_a_listed_parent():
    found = [Found(i, None) for i in ("openspec:a", "openspec:a-fix-1", "openspec:a-followup-2", "openspec:b-fix-1")]
    listed = files(plan_doc({"openspec:a": []}))
    assert [u.id for u in unlisted(found, listed)] == ["openspec:b-fix-1"]  # b is no unit anyone lists: kept


def test_a_parent_the_draft_adds_covers_its_derived_units():
    found = [Found(i, None) for i in ("openspec:a", "openspec:a-fix-1", "openspec:a-followup-1-fix-1")]
    assert [u.id for u in unlisted(found, [])] == ["openspec:a"]


def test_a_derived_unit_of_an_excluded_parent_is_covered():
    found = [Found("openspec:a-fix-1", None)]
    assert unlisted(found, files(plan_doc({"openspec:z": []}, exclude=[{"id": "openspec:a", "reason": "r"}]))) == []


def test_finished_units_go_to_exclude_with_their_phase():
    found = [Found("openspec:a", "merged"), Found("openspec:b", "archived"), Found("openspec:c", "abandoned")]
    draft = new_draft("p1", target="main", merge="human", found=found, files=[])
    assert draft.added == ("openspec:c",)
    assert draft.excluded == (("openspec:a", "already merged"), ("openspec:b", "already archived"))


def test_update_appends_in_id_order_and_never_adds_a_dependency():
    own = files(plan_doc({"openspec:a": []}))[0]
    data = json.loads(own.text)
    draft = update_draft(
        data, [Found("openspec:a", None), Found("openspec:z", None), Found("openspec:m", None)], [own], own
    )
    after = json.loads(draft.text)
    assert [u["id"] for u in after["batches"][-1]["units"]] == ["openspec:m", "openspec:z"]
    assert all(u.get("depends_on") == [] for u in after["batches"][-1]["units"])


def test_the_draft_reads_invalid_plan_files_too():
    bad = _plan_file(".l4/plans/p9.json", json.dumps({"batches": [{"units": [{"id": "openspec:a"}]}], "x": 1}))
    assert bad.plan is None
    assert unlisted([Found("openspec:a", None)], [bad]) == []


def test_plan_files_reads_the_working_tree(world):
    world.push_plan()
    world.pull()
    assert [f.plan_id for f in plan_files(world.app.repo)] == ["p1"]


@pytest.mark.parametrize("phase", [None, "implementing", "in_review"])
def test_unfinished_phases_are_planned(phase):
    draft = new_draft("p1", target="main", merge="human", found=[Found("openspec:a", phase)], files=[])
    assert draft.added == ("openspec:a",) and draft.excluded == ()
