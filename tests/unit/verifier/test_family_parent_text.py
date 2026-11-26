"""ui-carry-followup 1.1 (L4-VER-096, SCN-VER-412..415): the family reads its merged parent's criteria at the wording
the base holds, in a temporary git repository with an `origin`, and the three readers of the base commit agree."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from l4.gates.junit import TestCase, TestReport
from l4.implementer.discrimination import unit_base
from l4.implementer.tdd import unchanged_on_base
from l4.specs.base import Framework, UnitRef
from l4.specs.criteria import base_criteria_at, openspec_criteria, spec_baseline, unchanged_ids
from l4.specs.followup import FollowUpMarker, write_follow_up_marker
from l4.state.ledger import LedgerEvent
from l4.vcs.unit_base import unit_base_commit
from l4.verifier.fixloop import FamilyProvider, family_of
from l4.verifier.verdicts import effective_verdicts, text_sha256

from ..orchestrator.test_kiro_unit import REQUIREMENTS

PARENT, FOLLOW = "add-journeys", "add-journeys-followup-1"
OLD_FLOW = "- **WHEN** a person opens a journey\n- **THEN** the page opens /flows"
NEW_FLOW = (
    "- **WHEN** a person opens a journey\n- **THEN** the page opens /no-such-page-deep-link, a path no feature owns"
)
OLD_COUNT = "- **WHEN** the plan runs\n- **THEN** the plan's eight calls are made"
NEW_COUNT = "- **WHEN** the plan runs\n- **THEN** the nine calls are made, the frozen calls.test.ts included"
THIRD = "- **WHEN** a person opens a journey\n- **THEN** a third wording"


def block(requirement: str, scenarios) -> str:
    body = "".join(f"\n#### Scenario: {name}\n{text}\n" for name, text in scenarios)
    return f"### Requirement: {requirement}\nThe system SHALL open it.\n{body}"


def delta(*scenarios: tuple[str, str], requirement: str = "Opening a journey", more: str = "") -> str:
    return f"## ADDED Requirements\n\n{block(requirement, scenarios)}\n{more}"


def spec(*scenarios: tuple[str, str], requirement: str = "Opening a journey", more: str = "") -> str:
    head = "# journeys Specification\n\n## Purpose\nOpens journeys.\n\n## Requirements\n\n"
    return f"{head}{block(requirement, scenarios)}\n{more}"


class Inner:
    """What `FamilyProvider` asks the plain provider for: the follow-up is the one unit, no fix units."""

    framework = Framework.OPENSPEC

    def __init__(self, ref: UnitRef) -> None:
        self.ref = ref

    def list_units(self):
        return [self.ref]

    def criteria(self, unit):
        return openspec_criteria(unit.path)

    def tasks(self, unit):
        return []


class World:
    def __init__(self, repo: Path, raw, git) -> None:
        self.repo, self.raw, self.git = repo, raw, git
        self.changes = repo / "openspec" / "changes"
        self.ref = UnitRef(Framework.OPENSPEC, FOLLOW, self.changes / FOLLOW)

    def write(self, path: str, text: str) -> None:
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def commit(self, message: str) -> str:
        self.raw(self.repo, "add", "-A")
        self.raw(self.repo, "commit", "-q", "-m", message)
        return self.raw(self.repo, "rev-parse", "HEAD").strip()

    def base_spec(self, text: str) -> None:
        self.write("openspec/specs/journeys/spec.md", text)

    def follow_up(self, own: str | None = None) -> None:
        folder = self.changes / FOLLOW
        folder.mkdir(parents=True, exist_ok=True)
        write_follow_up_marker(folder, FollowUpMarker(f"openspec:{PARENT}", (("FB-001", "0" * 64),)))
        if own is not None:
            self.write(f"openspec/changes/{FOLLOW}/specs/journeys/spec.md", own)

    def family(self, base_rev="auto") -> FamilyProvider:
        rev = (lambda: unit_base_commit(self.git, "main")) if base_rev == "auto" else base_rev
        return FamilyProvider(Inner(self.ref), self.ref, git=self.git, base_rev=rev)


@pytest.fixture
def world(make_repo, raw, git_for) -> World:
    """main (pushed to origin) holds the archived parent and the base spec as a later change reworded it; the unit
    branch holds the follow-up."""
    repo = make_repo("repo", remote=True)
    w = World(repo, raw, git_for(repo))
    w.write(f"openspec/changes/archive/2026-01-01-{PARENT}/specs/journeys/spec.md",
            delta(("opens the flow", OLD_FLOW), ("keeps the count", OLD_COUNT)))  # fmt: skip
    w.base_spec(spec(("opens the flow", NEW_FLOW), ("keeps the count", NEW_COUNT)))
    w.commit("base: the archived parent and the reworded spec")
    raw(repo, "push", "-q", "origin", "main")
    raw(repo, "fetch", "-q", "origin")
    raw(repo, "checkout", "-q", "-b", "unit")
    w.follow_up()
    w.commit("the follow-up")
    return w


def texts(criteria):
    return {c.scenario: c.text for c in criteria}


def test_scn_ver_412_both_real_shapes_are_read_at_the_bases_wording_with_the_same_ids(world):
    before = world.family(base_rev=None).criteria(world.ref)  # 0.4.60
    after = world.family().criteria(world.ref)
    assert texts(before) == {"opens the flow": OLD_FLOW, "keeps the count": OLD_COUNT}
    assert texts(after) == {"opens the flow": NEW_FLOW, "keeps the count": NEW_COUNT}
    assert [(c.id, c.alias, c.source_path, c.source_line) for c in after] == [
        (c.id, c.alias, c.source_path, c.source_line) for c in before
    ]  # the ids, their number and their order do not change
    baseline = spec_baseline(world.git, Framework.OPENSPEC, SimpleNamespace(), unit_base_commit(world.git, "main"))
    assert unchanged_ids(after, baseline) == {c.id for c in after}  # step 4 sees them unchanged on the base
    assert unchanged_ids(before, baseline) == frozenset()


def test_the_base_text_is_read_once_per_provider_and_only_when_a_parent_criterion_is_asked_for(world):
    calls: list[int] = []

    def rev():
        calls.append(1)
        return unit_base_commit(world.git, "main")

    family = world.family(base_rev=rev)
    assert calls == []  # building the provider and listing its units reads no git
    family.units(), family.tasks(world.ref)
    assert calls == []
    family.criteria(world.ref), family.criteria(world.ref), family.merged_parent_criteria()
    assert calls == [1]


def test_scn_ver_413_nothing_is_rewritten_without_a_single_scenario_of_that_id_or_a_different_text(world):
    # the parent has four scenarios: one the base rewords (for contrast), one the base holds twice under its
    # requirement, one whose base text is the parent's, and one under a requirement the base renamed
    archived = delta(
        ("opens the flow", OLD_FLOW), ("keeps the count", OLD_COUNT), ("same words", THIRD),
        more=block("Renamed away", [("renamed", OLD_FLOW)]),
    )  # fmt: skip
    world.write(f"openspec/changes/archive/2026-01-01-{PARENT}/specs/journeys/spec.md", archived)
    world.base_spec(
        spec(
            ("opens the flow", NEW_FLOW),
            ("opens the flow", THIRD),
            ("keeps the count", NEW_COUNT),
            ("same words", THIRD),
            more=block("Renamed", [("renamed", NEW_FLOW)]),
        )  # fmt: skip
    )
    world.commit("base moved")
    world.raw(world.repo, "push", "-q", "origin", "HEAD:main")
    world.raw(world.repo, "fetch", "-q", "origin")
    read = texts(world.family().criteria(world.ref))
    assert read["opens the flow"] == OLD_FLOW  # the base holds that id twice: the parent's text stays
    assert read["keeps the count"] == NEW_COUNT  # the one that is rewritten, for contrast
    assert read["same words"] == THIRD  # the base's text equals the parent's
    assert read["renamed"] == OLD_FLOW  # no base scenario has this id (the requirement was renamed)
    assert texts(world.family(base_rev=None).criteria(world.ref))["keeps the count"] == OLD_COUNT


def test_scn_ver_413_no_base_commit_or_a_git_that_cannot_read_the_specs_keeps_the_parents_text(world, tmp_path):
    expected = {"opens the flow": OLD_FLOW, "keeps the count": OLD_COUNT}
    assert texts(world.family(base_rev=None).criteria(world.ref)) == expected  # no base commit is known
    assert texts(world.family(base_rev=lambda: "0" * 40).criteria(world.ref)) == expected  # git cannot read that rev
    assert texts(world.family(base_rev=lambda: "").criteria(world.ref)) == expected

    def boom():
        raise OSError("git is not there")

    assert texts(world.family(base_rev=boom).criteria(world.ref)) == expected


def test_scn_ver_413_a_kiro_follow_up_is_unchanged(tmp_path, make_repo):
    repo = make_repo("kiro")
    specs = repo / ".kiro" / "specs"
    (specs / "tip-calc").mkdir(parents=True)
    (specs / "tip-calc" / "requirements.md").write_text(REQUIREMENTS)
    (specs / "tip-calc-followup-1").mkdir()
    write_follow_up_marker(specs / "tip-calc-followup-1", FollowUpMarker("kiro:tip-calc", (("FB-001", "0" * 64),)))
    ref = UnitRef(Framework.KIRO, "tip-calc-followup-1", specs / "tip-calc-followup-1")

    class KiroInner(Inner):
        framework = Framework.KIRO

        def criteria(self, unit):
            return []

    asked: list[int] = []
    family = FamilyProvider(KiroInner(ref), ref, base_rev=lambda: asked.append(1) or "deadbeef")
    merged = family.merged_parent_criteria()
    assert merged and all(c.framework is Framework.KIRO for c in merged)
    assert asked == []  # a Kiro id hashes the text: no base is read, and the baseline is the parent's own criteria
    assert spec_baseline(None, Framework.KIRO, family, "x") == merged  # type: ignore[arg-type]


def test_scn_ver_414_the_follow_ups_own_scenario_wins_and_is_not_unchanged(world):
    world.follow_up(
        own=delta(("opens the flow", "- **WHEN** a person opens a journey\n- **THEN** the page opens /own"))
    )
    world.commit("the follow-up says it again, with a changed sentence")
    read = world.family().criteria(world.ref)
    by = {c.scenario: c for c in read}
    assert by["opens the flow"].text.endswith("/own") and by["opens the flow"].source_path.startswith("specs/")
    assert by["keeps the count"].text == NEW_COUNT  # the other one is the base's
    assert [c.scenario for c in read].count("opens the flow") == 1
    assert by["opens the flow"].id not in unchanged_ids(
        read, base_criteria_at(world.git, unit_base_commit(world.git, "main"))
    )


def test_scn_ver_415_one_reading_for_every_reader_and_an_accept_bound_to_the_old_text_is_void_once(world):
    family = world.family()
    old, new = world.family(base_rev=None).criteria(world.ref), family.criteria(world.ref)
    assert family.load(world.ref).criteria == tuple(new)  # the units the verifier's steps and prompts load
    assert [c.text for c in family.criteria(world.ref)] == [c.text for c in family.merged_parent_criteria()]

    # the red step's `unchanged_on_base` reads `wb.provider.criteria(wb.ref)`: the base's text
    flow = next(c for c in new if c.scenario == "opens the flow")
    case = TestCase(f"web.flow.test.ts::{flow.id} opens", "passed")  # the id names the criterion: it traces to it
    config = SimpleNamespace(
        forge=SimpleNamespace(base_branch="main"), verifier=SimpleNamespace(max_criteria_per_test=3)
    )
    wb = SimpleNamespace(git=world.git, ref=world.ref, provider=family, cfg=config)
    report = TestReport({case.id: case})
    found = unchanged_on_base(wb, new, report, report)
    assert found == {flow.id: (case.id,)}
    wb_old = SimpleNamespace(git=world.git, ref=world.ref, provider=world.family(base_rev=None), cfg=config)
    assert unchanged_on_base(wb_old, old, report, report) == {}

    # a person's accept bound to the old text is not in force; the other criterion's accept is
    def accepted(seq: int, target: str, sha: str) -> LedgerEvent:
        return LedgerEvent(
            datetime.now(UTC), "r-1", "openspec:x", seq, "human.verdict",
            {
                "question": f"Q-{seq:03d}", "target": target, "decision": "accept", "by": "ana", "reason": "r",
                "text_sha256": sha,
            },
        )  # fmt: skip

    count_old = next(c for c in old if c.scenario == "keeps the count")
    count_new = next(c for c in new if c.scenario == "keeps the count")
    events = [
        accepted(1, flow.id, text_sha256(next(c for c in old if c.id == flow.id))),
        accepted(2, count_new.id, text_sha256(count_new)),
    ]
    in_force = effective_verdicts(events, {c.id: text_sha256(c) for c in new})
    assert set(in_force) == {count_new.id}  # the accept of the reworded one is void, the other is untouched
    assert count_old.id == count_new.id


def test_the_three_readers_of_the_base_commit_agree_when_the_local_base_branch_is_ahead_of_origin(world):
    # the local `main` holds one more commit than `origin/main`, and the unit branch forks from it
    world.raw(world.repo, "checkout", "-q", "main")
    world.base_spec(spec(("opens the flow", THIRD), ("keeps the count", NEW_COUNT)))
    local_only = world.commit("local main, never pushed")
    world.raw(world.repo, "checkout", "-q", "unit")
    world.raw(world.repo, "merge", "-q", "--no-edit", "main")
    origin_tip = world.raw(world.repo, "rev-parse", "origin/main").strip()
    assert local_only != origin_tip
    wb = SimpleNamespace(git=world.git, cfg=SimpleNamespace(forge=SimpleNamespace(base_branch="main")))
    ctx = SimpleNamespace(
        cfg=wb.cfg, services=SimpleNamespace(provider=Inner(world.ref), ref=world.ref, git=world.git,
                                             worktree=world.repo, ledger=None),
    )  # fmt: skip
    family = family_of(ctx)
    assert unit_base(wb) == origin_tip  # the red step: origin first
    assert unit_base_commit(world.git, "main") == origin_tip
    assert family._base_rev() == origin_tip  # the family: the same helper, the same commit
    assert texts(family.criteria(world.ref))["opens the flow"] == NEW_FLOW  # origin's wording, not the local one


def test_step_0_reads_the_same_commit_as_the_red_step_and_the_family(make_bench):
    """The third reader: `check_preconditions` gives `base_sha`, the commit step 4's baseline is read at."""
    from l4.specs.base import Marker
    from l4.verifier.preconditions import check_preconditions

    from .conftest import with_validation

    wb = make_bench([]).wb
    with_validation(wb)
    wb.provider.set_marker(wb.ref, "1.1", Marker.DONE)
    wb.commit("feat: 1.1", task="1.1", attempt=1, phase="green", tdd="green")
    local_only = wb.git.run("commit-tree", "-m", "local", "-p", "main", "main^{tree}").stdout.strip()
    wb.git.run("update-ref", "refs/heads/main", local_only)  # the local base branch is ahead of origin/main
    origin = wb.git.rev_parse("refs/remotes/origin/main")
    assert wb.git.rev_parse("main") != origin
    pre = check_preconditions(wb)
    assert pre.base_sha == origin == unit_base(wb) == unit_base_commit(wb.git, wb.cfg.forge.base_branch)


def test_the_red_step_never_reads_a_parent_criterion_whatever_its_provider_is(world):
    """Task 1.3: the red step of the follow-up's own tasks gets the plain provider (`orchestrator._workbench`), whose
    criteria are the unit's own delta; the red step of a fix task gets the family (`fixloop._child_workbench`), whose
    reading of a FIX unit leaves the merged parent out (`FamilyProvider.criteria` adds it for the parent only). So no
    parent text reaches `unchanged_on_base` through either provider, and there is nothing to give it the rewrite."""
    family = world.family()
    parent_ids = {c.id for c in family.criteria(world.ref)}
    assert len(parent_ids) == 2
    assert Inner(world.ref).criteria(world.ref) == []  # the plain provider: the follow-up has no delta of its own
    fix = UnitRef(Framework.OPENSPEC, f"{FOLLOW}-fix-1", world.changes / f"{FOLLOW}-fix-1")
    assert family.criteria(fix) == []  # the family's reading of a fix unit: no merged parent criterion

    config = SimpleNamespace(
        forge=SimpleNamespace(base_branch="main"), verifier=SimpleNamespace(max_criteria_per_test=3)
    )
    cases = {c: TestCase(f"web.flow.test.ts::{c} opens", "passed") for c in parent_ids}
    report = TestReport({case.id: case for case in cases.values()})
    for provider, ref in ((Inner(world.ref), world.ref), (family, fix)):
        wb = SimpleNamespace(git=world.git, ref=ref, provider=provider, cfg=config)
        assert unchanged_on_base(wb, provider.criteria(ref), report, report) == {}
