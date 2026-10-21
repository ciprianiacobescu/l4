import re
import subprocess
import sys
from pathlib import Path

import pytest

from l4.config.schema import L4Config
from l4.exitcodes import ExitCode, L4Exit
from l4.redact import Redactor
from l4.s1 import canary as c
from l4.s1 import mutations as mut
from l4.s1 import questions as q

from ..evidence._multi import build_repo


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("canary") / "repo"
    build_repo(path)
    return path


def make(repo: Path, tmp_path: Path, seed: int = 1) -> c.Canary:
    canary = c.Canary(repo, cfg=L4Config(), seed=seed, work_dir=tmp_path / "work", redactor=Redactor({}))
    canary.units = c.find_source_units(canary.git)
    return canary


def unit_named(canary: c.Canary, name: str) -> c.SourceUnit:
    return next(u for u in canary.units if u.name == name)


def by_subject(items):
    return {(i.question_set, i.subject): i for i in items}


def test_source_units_come_from_trailer_ranges(repo: Path, tmp_path: Path):
    canary = make(repo, tmp_path)
    assert [u.name for u in canary.units][:3] == ["add-discount-codes", "add-sales-tax", "reserve-stock"]
    cart = unit_named(canary, "cart-totals")
    assert cart.id == "openspec:cart-totals" and cart.spec_dir == "openspec/changes/cart-totals"
    assert canary.git.run("rev-parse", f"{cart.head}~2").stdout.strip() == cart.base  # spec, red, green


def test_each_mutation_gives_its_intended_label_on_py_multi(repo: Path, tmp_path: Path):
    canary = make(repo, tmp_path)
    cart = unit_named(canary, "cart-totals")
    results = {m: canary.run(cart, m, 0) for m in mut.MUTATIONS}
    assert {m: r.dropped for m, r in results.items()} == {m: "" for m in mut.MUTATIONS}, canary.counts

    def expected(mutation: str, set_name: str, subject: str) -> dict:
        return by_subject(results[mutation].items)[(set_name, subject)].expected

    clean = results["none"].items
    assert all(i.expected[c.CLASS_QUESTION[i.question_set]] is True for i in clean)
    assert {i.question_set for i in clean} == {q.FILE_RELEVANT, q.CHANGE_COVERED, q.TESTS_OK}

    moved = [
        i for i in results["transplant_hunk"].items if i.question_set == q.FILE_RELEVANT and not i.expected["relevant"]
    ]
    assert [i.subject for i in moved] == ["src/inventory/stock.py"] and moved[0].expected["relatedness"] == 0
    assert "mutation:transplant_hunk" in moved[0].tags and "source:openspec:cart-totals" in moved[0].tags
    template = [
        i for i in results["template_edit"].items if i.question_set == q.FILE_RELEVANT and not i.expected["relevant"]
    ]
    assert len(template) == 1 and template[0].subject.startswith("src/inventory/")

    assert expected("drop_covering_test", q.CHANGE_COVERED, "src/shop/cart.py::cart_total")["exercised"] is False
    fresh = [
        i for i in results["untested_function"].items
        if i.question_set == q.CHANGE_COVERED and i.expected.get("untested") is True
    ]  # fmt: skip
    assert len(fresh) == 1 and fresh[0].subject.startswith("src/shop/cart.py::")
    assert expected("break_test", q.TESTS_OK, "tests") == {"all_passed": False}
    assert expected("none", q.TESTS_OK, "tests") == {"all_passed": True}
    assert expected("skip_old_test", q.TESTS_OK, "tests") == {"all_passed": False}
    assert expected("add_passing_test", q.TESTS_OK, "tests") == {"all_passed": True}

    for r in results.values():  # the ground truth and its provenance are on every item
        for i in r.items:
            assert i.origin == "canary" and i.label_source.startswith("deterministic:")
            assert i.question_sha256 == q.get_set(i.question_set).sha256 and i.expected
            assert i.unit == "openspec:cart-totals" and "origin:canary" in i.tags
    # the skip variant (odd) of drop_covering_test is a different edit with the same intended label
    skipped = canary.run(cart, "drop_covering_test", 1)
    assert not skipped.dropped
    assert by_subject(skipped.items)[(q.CHANGE_COVERED, "src/shop/cart.py::cart_total")].expected["exercised"] is False


def test_same_seed_same_items(repo: Path, tmp_path: Path):
    def keys(seed: int, where: str) -> list[str]:
        canary = make(repo, tmp_path / where, seed)
        unit = unit_named(canary, "low-stock-alerts")
        return sorted(
            i.item_key for m in ("transplant_hunk", "untested_function") for i in canary.run(unit, m, 0).items
        )

    assert keys(7, "a") == keys(7, "b") and keys(7, "a")
    assert mut.pick(7, 50, "u", "x") != mut.pick(8, 50, "u", "x") or mut.pick(7, 50, "u", "y") != mut.pick(
        8, 50, "u", "y"
    )


def test_disagreement_is_dropped_and_counted(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def called_at_import(text: str, variant: int) -> tuple[str, str]:
        name = f"l4_canary_untested_{variant}"
        return text.rstrip("\n") + f"\n\n\ndef {name}(value):\n    return value\n\n\n_ = {name}(1)\n", name

    monkeypatch.setattr(mut, "add_untested_function", called_at_import)
    canary = make(repo, tmp_path)
    result = canary.run(unit_named(canary, "cart-totals"), "untested_function", 0)
    assert result.dropped == "checker_disagreement" and result.items == []
    assert canary.counts["run:untested_function:checker_disagreement"] == 1


def test_no_engine_is_constructed(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    code = "import sys, l4.s1.canary; print('l4.llm.system_one' in sys.modules)"
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert done.stdout.strip() == "False"
    import l4.llm.system_one as s1

    def boom(*a, **k):
        raise AssertionError("an engine was constructed")

    monkeypatch.setattr(s1.SystemOneBackend, "__init__", boom)
    monkeypatch.setattr(s1.SystemOneBackend, "query", boom)
    canary = make(repo, tmp_path)
    assert canary.run(unit_named(canary, "add-sales-tax"), "untested_function", 0).items


def test_quotas_reach_target_on_py_multi_with_small_target(repo: Path, tmp_path: Path):
    canary = make(repo, tmp_path)
    lines: list[str] = []
    quota = c.Quota(target=40, min_share=0.3, min_test=0)
    done = c.generate([canary], quota, max_variants=2, on_run=lines.append)
    assert done.met and len(done.items) >= 40 and c.quota_gaps(done.items, quota) == []
    assert len(lines) < 20  # it stopped as soon as the quotas held, not after the whole history
    for set_name, qid in c.CLASS_QUESTION.items():
        if set_name == q.TESTS_OK:  # the sanity question is exempt from the share quota
            continue
        rows = [i for i in done.items.values() if i.question_set == set_name]
        share = sum(i.expected[qid] is False for i in rows) / len(rows)
        assert 0.3 <= share <= 0.7, (set_name, share)
    # a quota that cannot be met says what is missing instead of looping
    strict = c.Quota(target=10_000, min_test=500)
    assert any("items" in g for g in c.quota_gaps(done.items, strict)) and any(
        "test split" in g for g in c.quota_gaps(done.items, strict)
    )
    again = c.generate([make(repo, tmp_path / "again")], quota, max_variants=2)
    assert sorted(again.items) == sorted(done.items)  # reproducible


def test_repository_allow_list_exits_2(tmp_path: Path):
    inside, outside = tmp_path / "mine", tmp_path / "other"
    inside.mkdir()
    outside.mkdir()
    env = {c.ROOTS_ENV: str(inside)}
    assert c.check_repo_allowed(inside, env) == inside.resolve()
    with pytest.raises(L4Exit) as caught:
        c.check_repo_allowed(outside, env)
    assert caught.value.code == ExitCode.USAGE_ERROR


LEAK = re.compile(r"canary|untested|l4_|template", re.I)


def test_no_state_names_its_generator_or_its_label(repo: Path, tmp_path: Path):
    canary = make(repo, tmp_path)
    cart = unit_named(canary, "cart-totals")
    seen = 0
    for mutation in mut.MUTATIONS:
        for variant in (0, 1):
            for item in canary.run(cart, mutation, variant).items:
                seen += 1
                assert not LEAK.search(item.state), (mutation, item.subject, LEAK.search(item.state).group(0))
                assert not LEAK.search(item.subject.split("::")[-1]), item.subject
    assert seen > 20


def test_file_states_carry_what_the_spec_declares(repo: Path, tmp_path: Path):
    canary = make(repo, tmp_path)
    cart = unit_named(canary, "cart-totals")
    items = [i for i in canary.run(cart, "none", 0).items if i.question_set == q.FILE_RELEVANT]
    assert items and all("Named in the spec's design and tasks:" in i.state for i in items)
    assert all("src/shop/cart.py" in i.state.split("Changed file:")[0] for i in items)


def test_project_key_does_not_depend_on_the_directory_name(repo: Path, tmp_path: Path):
    clones = []
    for name in ("one", "two/deeper"):
        target = tmp_path / name
        subprocess.run(["git", "clone", "--quiet", str(repo), str(target)], check=True)
        work = tmp_path / f"w-{target.name}"
        clones.append(c.Canary(target, cfg=L4Config(), seed=1, work_dir=work, redactor=Redactor({})))
    assert clones[0].project == clones[1].project == make(repo, tmp_path / "orig").project
    assert clones[0].project.startswith("git-")
    keys = []
    for canary in clones:
        canary.units = c.find_source_units(canary.git)
        keys.append(sorted(i.item_key for i in canary.run(unit_named(canary, "cart-totals"), "none", 0).items))
    assert keys[0] == keys[1] and keys[0]


def test_a_crlf_file_stays_crlf_when_a_mutation_rewrites_it(tmp_path: Path):
    target = tmp_path / "m.py"
    target.write_bytes(b"A = 1\r\nB = 2\r\n")
    c.write_preserving_newlines(target, "A = 1\nB = 3\n")
    assert target.read_bytes() == b"A = 1\r\nB = 3\r\n"
    fresh = tmp_path / "sub" / "n.py"
    c.write_preserving_newlines(fresh, "X = 1\n")
    assert fresh.read_bytes() == b"X = 1\n"


@pytest.mark.parametrize("gone", ["flip_expected_literal", "add_missing_fixture"])
def test_break_test_falls_back_when_a_test_has_no_literal_to_flip(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gone: str
):
    monkeypatch.setattr(mut, "flip_expected_literal", lambda *a, **k: None)
    if gone == "add_missing_fixture":
        monkeypatch.setattr(mut, "add_missing_fixture", lambda *a, **k: None)
    canary = make(repo, tmp_path)
    result = canary.run(unit_named(canary, "cart-totals"), "break_test", 0)
    assert not result.dropped, canary.counts
    (item,) = [i for i in result.items if i.question_set == q.TESTS_OK]
    assert item.expected == {"all_passed": False}
    assert "errored" in item.state or "skipped" in item.state


def test_tests_ok_is_a_sanity_question_exempt_from_the_share_and_test_quotas():
    from ._make import make_item

    only_true = {
        i.item_key: i
        for i in (make_item(f"t{n:030d}", unit=f"openspec:u{n}", truth={"tests_ok": True}) for n in range(40))
    }
    gaps = c.quota_gaps(only_true, c.Quota(target=1, min_share=0.3, min_test=30))
    assert not any(g.startswith(q.TESTS_OK) for g in gaps), gaps
    assert any(g.startswith(q.FILE_RELEVANT) for g in gaps)  # the other sets are still held to them
    assert c.quota_gaps(only_true, c.Quota(target=1000, min_test=0)) and "rows after the class balance" in " ".join(
        c.quota_gaps(only_true, c.Quota(target=1000, min_test=0))
    )  # the target count still applies


def test_passing_and_skipping_variants_change_the_tests_ok_state_and_label_it_literally(repo: Path, tmp_path: Path):
    canary = make(repo, tmp_path)
    cart = unit_named(canary, "cart-totals")
    baseline = canary.run(cart, "none", 0).items
    base_ok = next(i for i in baseline if i.question_set == q.TESTS_OK)
    seen = {base_ok.item_key: base_ok.state}
    for mutation in ("add_passing_test", "skip_old_test"):
        for variant in (0, 1):
            result = canary.run(cart, mutation, variant)
            assert not result.dropped, (mutation, variant, canary.counts)
            ok = next(i for i in result.items if i.question_set == q.TESTS_OK)
            # B-M1: a skipped old test is listed under "Not passed", so "did every test pass?" is no
            assert ok.expected == {"all_passed": mutation == "add_passing_test"}, mutation
            assert f"mutation:{mutation}" in ok.tags
            assert ok.item_key not in seen and ok.state not in seen.values(), (mutation, variant)
            seen[ok.item_key] = ok.state
    assert len(seen) == 5  # the baseline and four distinct states


def _branch_repo(path: Path) -> tuple[c.Git, dict[str, str]]:
    """A base commit, then one unit on each of two branches that never meet (as open MRs do)."""
    from l4.vcs.trailers import CommitTrailers

    path.mkdir()
    git = c.Git(path)
    git.env.update(GIT_AUTHOR_DATE="2026-10-04T00:00:00+00:00", GIT_COMMITTER_DATE="2026-10-04T00:00:00+00:00")
    git.run("init", "--quiet", "--initial-branch=main")
    (path / "README.md").write_text("base\n", encoding="utf-8")
    git.run("add", "-A")
    git.commit("base", CommitTrailers("base", "R", 1, "planning"))
    base = git.rev_parse("HEAD")
    heads: dict[str, str] = {}
    for branch, name in (("l4/openspec/one", "one"), ("l4/openspec/two", "two")):
        git.run("checkout", "--quiet", "-b", branch, base)
        spec = path / "openspec" / "changes" / name
        spec.mkdir(parents=True)
        (spec / "proposal.md").write_text(f"# {name}\n", encoding="utf-8")
        git.run("add", "-A")
        git.commit(f"spec {name}", CommitTrailers(f"openspec:{name}", "R", 1, "planning"))
        (path / f"{name}.py").write_text("X = 1\n", encoding="utf-8")
        git.run("add", "-A")
        heads[name] = git.commit(f"green {name}", CommitTrailers(f"openspec:{name}", "R", 1, "implementing"))
    git.run("checkout", "--quiet", "main")
    return git, heads


def test_source_units_on_every_local_branch_are_found(tmp_path: Path):
    git, heads = _branch_repo(tmp_path / "repo")
    assert c.find_source_units(git) == []  # main alone carries no unit
    found = {u.name: u for u in c.find_source_units(git, "HEAD", "--branches")}
    assert set(found) == {"one", "two"}
    for name, unit in found.items():
        assert unit.head == heads[name] and unit.spec_dir == f"openspec/changes/{name}"
        assert git.run("rev-parse", f"{unit.head}~1").stdout.strip() == unit.base  # base = parent of first implementing


def test_the_generator_reads_units_from_every_local_branch(tmp_path: Path):
    git, heads = _branch_repo(tmp_path / "repo")
    canary = c.Canary(tmp_path / "repo", cfg=L4Config(), seed=1, work_dir=tmp_path / "w", redactor=Redactor({}))
    c.generate([canary], c.Quota(target=1), max_variants=0)
    assert sorted(u.name for u in canary.units) == ["one", "two"]
    # a remote-tracking ref is not read: only the branches the operator checked out locally are source units
    git.run("update-ref", "refs/remotes/origin/l4/openspec/two", heads["two"])
    git.run("branch", "--quiet", "-D", "l4/openspec/two")
    c.generate([canary], c.Quota(target=1), max_variants=0)
    assert [u.name for u in canary.units] == ["one"]


def test_items_carry_their_project_key_as_a_tag(repo: Path, tmp_path: Path):
    canary = make(repo, tmp_path)
    items = canary.run(unit_named(canary, "cart-totals"), "none", 0).items
    assert items and all(f"project:{canary.project}" in i.tags for i in items)
    assert all(canary.project not in i.state for i in items)  # metadata, never part of what an engine reads
