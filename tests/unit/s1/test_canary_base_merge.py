"""A unit branch that merged the base in (M1.7: `chore(<unit>): merge <base>@<sha> into the unit branch [skip ci]`,
two parents): the canary mirrors the verifier, so the unit's change is `diff(merge-base(head, base-as-merged), head)`
and what main brought in is not the unit's change, so it is no item."""

from pathlib import Path

from l4.config.schema import L4Config
from l4.redact import Redactor
from l4.s1 import canary as c
from l4.s1 import questions as q
from l4.vcs.git import Git
from l4.vcs.trailers import CommitTrailers

from ..evidence._multi import FIXTURE, RUN_ID, _overlay, build_repo

NAME = "cart-totals"
UNIT = f"openspec:{NAME}"
MAIN_ONLY = "src/inventory/main_only.py"


def merged_history(repo: Path) -> tuple[Git, str, str]:
    """Units 1 to 4 and the spec of `cart-totals` on main, then the unit branch as the harness leaves it after a
    base merge: red, the merge of a main that moved on (it added `MAIN_ONLY`), green.
    Returns (git, main's new head, the unit's head)."""
    git, units = build_repo(repo, units=5)
    cart = units[4]
    folder = FIXTURE / "units" / "05-cart-totals"
    git.run("checkout", "--quiet", "-B", "unit", cart.red)  # red on top of the spec
    git.run("checkout", "--quiet", "-B", "main", cart.base)  # the spec is on main; main then moves on without the unit
    (repo / MAIN_ONLY).write_text("def only_on_main():\n    return 1\n", encoding="utf-8")
    git.run("add", "-A")
    moved = git.commit("main moves on", CommitTrailers("base", RUN_ID, 1, "planning"))
    git.run("checkout", "--quiet", "unit")
    subject = f"chore({NAME}): merge main@{moved[:10]} into the unit branch [skip ci]"
    message = f"{subject}\n\nL4-Unit: {UNIT}\nL4-Run: {RUN_ID}\nL4-Iteration: 1\nL4-Phase: verifying\n"
    git.run("merge", "--no-ff", "--quiet", "-m", message, moved)
    _overlay(folder / "green", repo)
    git.run("add", "-A")
    head = git.commit(f"green {NAME}", CommitTrailers(UNIT, RUN_ID, 1, "implementing", task="1.1", tdd="green"))
    return git, moved, head


def test_the_unit_base_is_the_merge_base_with_the_base_as_merged(tmp_path: Path):
    git, moved, head = merged_history(tmp_path / "repo")
    [unit] = [u for u in c.find_source_units(git, "unit") if u.name == NAME]
    assert unit.head == head and unit.base == moved  # not the parent of the first implementing commit
    assert len(git.run("rev-list", "--parents", "-n", "1", head).stdout.split()) == 2  # green is a plain commit


def test_files_brought_in_from_main_are_not_items(tmp_path: Path):
    git, moved, head = merged_history(tmp_path / "repo")
    canary = c.Canary(tmp_path / "repo", cfg=L4Config(), seed=1, work_dir=tmp_path / "work", redactor=Redactor({}))
    canary.units = [u for u in c.find_source_units(canary.git, "unit") if u.name == NAME]
    items = canary.run(canary.units[0], "none", 0).items
    files = {i.subject for i in items if i.question_set == q.FILE_RELEVANT}
    assert "src/shop/cart.py" in files and MAIN_ONLY not in files, sorted(files)
    assert all(MAIN_ONLY not in i.subject for i in items)


def test_a_unit_without_a_base_merge_keeps_the_parent_of_its_first_implementing_commit(tmp_path: Path):
    git, units = build_repo(tmp_path / "repo", units=5)
    [unit] = [u for u in c.find_source_units(git) if u.name == NAME]
    assert unit.base == units[4].base
