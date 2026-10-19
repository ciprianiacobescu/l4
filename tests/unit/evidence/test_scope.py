from pathlib import Path

import pytest

from l4.config.schema import L4Config
from l4.evidence.scope import (
    ChangedFile,
    ScopeContext,
    check_scope,
    classify_files,
    declared_scope,
    module_of,
    unit_declared_scope,
)
from l4.verifier.aggregate import aggregate_unit
from l4.verifier.types import Severity, Verdict

ROOTS = ("src", "lib", "packages", "apps")
TREE = [
    "src/shop/__init__.py", "src/shop/pricing.py", "src/shop/tax.py",
    "src/inventory/__init__.py", "src/inventory/stock.py", "tests/test_pricing.py", "tests/test_stock.py",
    "pyproject.toml",
]  # fmt: skip
SPEC_DIR = "openspec/changes/add-x"


def cfg(scope_check: str = "warn", **evidence: object) -> L4Config:
    return L4Config.model_validate({"sdd": {"scope_check": scope_check}, "verifier": {"evidence": evidence}})


def cf(path: str, status: str = "M", source: str | None = None) -> ChangedFile:
    return ChangedFile(path, status, source)  # type: ignore[arg-type]


def test_impact_design_and_task_lines_declare_paths_and_modules():
    scope = declared_scope(
        {
            "proposal.md": "## Why\n\nSee `src/ignored/in_why.py`.\n\n## Impact\n\n- Code in `src/shop/pricing.py`.\n"
            "\n## Other\n\n`src/ignored/after.py`\n",
            "design.md": "Glue in `src/inventory/` and a glob `src/shop/t*.py`.\n```\n`src/fenced/x.py`\n```\n",
            "tasks.md": "## 1. T\n\n- [ ] 1.1 Edit `tests/test_pricing.py::test_a` and `lib/util.py:12`\n",
            "specs/x/spec.md": "`src/ignored/spec.py`",
        },
        TREE,
    )
    assert scope.paths == ("src/inventory", "src/shop/pricing.py", "tests/test_pricing.py", "lib/util.py")
    assert scope.globs == ("src/shop/t*.py",)
    assert scope.modules == frozenset({"shop", "inventory", "tests", "util"})
    assert set(scope.sources) == {"proposal.md", "design.md", "tasks.md"}


def test_prose_without_backticks_declares_nothing():
    scope = declared_scope({"proposal.md": "## Impact\n\nChanges the shop pricing in src/shop/pricing.py.\n"}, TREE)
    assert (scope.paths, scope.globs, scope.modules, scope.sources) == ((), (), frozenset(), ())


def test_dotted_module_declares_its_package():
    scope = declared_scope(
        {"design.md": "In `shop.tax` add `add_tax()`; call `inventory.stock.Stock.reserve(sku, 1)`; "
         "also `SAVE10`, `Stock.reserve`, `uv run pytest`, `pricing.py` and `src.shop.cart`.\n"},
        TREE,
    )  # fmt: skip
    assert scope.modules == frozenset({"shop", "inventory"})
    assert scope.paths == () and scope.globs == ("**/pricing.py",)


def test_kiro_unit():
    scope = declared_scope(
        {"design.md": "Edit `src/shop/tax.py`.\n", "tasks.md": "- [ ] 1. Add tests\n  - `tests/test_tax.py`\n",
         "requirements.md": "`src/other/r.py`"},
        TREE,
    )  # fmt: skip
    # owner decision 7 (kiro-prompt-context): a Kiro unit's requirements.md declares scope too, as the design does
    assert scope.paths == ("src/shop/tax.py", "src/other/r.py", "tests/test_tax.py")


@pytest.mark.parametrize(
    ("path", "module"),
    [
        ("src/shop/pricing.py", "shop"), ("src/shop", "shop"), ("src/foo.py", "foo"), ("pkg/mod/x.py", "pkg"),
        ("packages/web/src/app.ts", "web"), ("setup.py", None), ("tests/test_a.py", "tests"),
    ],
)  # fmt: skip
def test_src_and_flat_layouts(path: str, module: str | None):
    assert module_of(path, ROOTS) == module


def test_other_module_is_out_of_scope_unless_named():
    scope = declared_scope({"proposal.md": "## Impact\n\n- `src/shop/pricing.py`\n"}, TREE)
    files = classify_files(
        [cf("src/shop/pricing.py"), cf("src/shop/tax.py"), cf("src/inventory/stock.py"), cf("tests/test_new.py", "A")],
        scope, cfg(), unit_dir=SPEC_DIR,
    )  # fmt: skip
    got = {f.path: (f.kind, f.module, f.label) for f in files}
    assert got == {
        "src/shop/pricing.py": ("code", "shop", "relevant"),
        "src/shop/tax.py": ("code", "shop", "relevant"),
        "src/inventory/stock.py": ("code", "inventory", "out_of_scope"),
        "tests/test_new.py": ("test", None, "relevant"),
    }
    named = declared_scope({"proposal.md": "## Impact\n\n- `src/shop/pricing.py` and `src/inventory/stock.py`\n"}, TREE)
    assert classify_files([cf("src/inventory/stock.py")], named, cfg())[0].label == "relevant"


def test_modified_test_of_another_module_follows_its_imports():
    scope = declared_scope({"proposal.md": "## Impact\n\n- `src/shop/pricing.py`\n"}, TREE)
    stock_test = "import pytest\nfrom inventory.stock import Stock\n\n\ndef test_a():\n    assert Stock\n"
    shop_test = "from shop import pricing\n"
    plain_test = "import os\n\n\ndef test_a():\n    assert os\n"
    files = classify_files(
        [cf("tests/test_stock.py", "M", stock_test), cf("tests/test_pricing.py", "M", shop_test),
         cf("tests/test_plain.py", "M", plain_test), cf("tests/test_gone.py", "D", None)],
        scope, cfg(),
    )  # fmt: skip
    assert [(f.label, f.module) for f in files] == [
        ("out_of_scope", "inventory"),
        ("relevant", "shop"),
        (None, None),
        (None, None),
    ]


def test_root_files_carry_no_label():
    scope = declared_scope({"proposal.md": "## Impact\n\n- `src/shop/pricing.py`\n"}, TREE)
    files = classify_files([cf("pyproject.toml"), cf("uv.lock")], scope, cfg())
    assert [(f.kind, f.label) for f in files] == [("root", None), ("root", None)]


def test_unit_spec_dir_and_harness_paths_are_exempt():
    scope = declared_scope({"proposal.md": "## Impact\n\n- `src/shop/pricing.py`\n"}, TREE)
    paths = [f"{SPEC_DIR}/tasks.md", f"{SPEC_DIR}/questions.md", ".l4-out/junit.xml", ".l4/config.yaml",
             "docs/guide.md", "README.md", "CHANGELOG.md", "src/inventory/questions.md"]  # fmt: skip
    files = classify_files([cf(p) for p in paths], scope, cfg(), unit_dir=SPEC_DIR)
    assert {f.kind for f in files} == {"exempt"} and {f.label for f in files} == {None}


def test_a_spec_that_names_nothing_labels_nothing():
    files = classify_files([cf("src/inventory/stock.py")], declared_scope({"proposal.md": "no ticks"}, TREE), cfg())
    assert files[0].label is None and "declares no scope" in files[0].reason


def _ctx(policy: str, changed: list[ChangedFile]) -> ScopeContext:
    scope = declared_scope({"proposal.md": "## Impact\n\n- `src/shop/pricing.py`\n"}, TREE)
    return ScopeContext(changed, scope, cfg(policy), unit_dir=SPEC_DIR)


CHANGED = [cf("src/shop/pricing.py"), cf("src/inventory/stock.py"), cf("src/inventory/other.py")]


def test_policy_off_warn_fail_through_aggregate_unit():
    off = check_scope(_ctx("off", CHANGED))
    assert (
        off.findings == [] and off.holds == [] and [f.label for f in off.files] == ["relevant"] + ["out_of_scope"] * 2
    )
    warn = check_scope(_ctx("warn", CHANGED))
    assert warn.findings == [] and len(warn.holds) == 2
    fail = check_scope(_ctx("fail", CHANGED))
    assert len(fail.findings) == 2 and fail.holds == []
    assert all(f.severity is Severity.MAJOR and f.source == "deterministic" for f in fail.findings)
    clean = check_scope(_ctx("fail", [cf("src/shop/pricing.py")]))
    assert not clean.findings and not clean.holds

    def verdict(outcome) -> Verdict:
        return aggregate_unit(outcome.findings, [], outcome.holds)

    assert (verdict(off), verdict(warn), verdict(fail)) == (Verdict.PASS, Verdict.NEEDS_HUMAN, Verdict.FAIL)


def test_hold_text_has_no_counts():
    one = check_scope(_ctx("warn", [cf("src/inventory/stock.py")])).holds
    many = check_scope(_ctx("warn", CHANGED)).holds
    assert one == ["scope: `src/inventory/stock.py` changes module `inventory`, which the spec does not name"]
    assert one[0] in many and not any(ch.isdigit() for ch in one[0].replace("src/inventory/stock.py", ""))


def test_real_fixture_unit_is_relevant(tmp_path: Path):
    from ._multi import build_repo

    git, units = build_repo(tmp_path / "repo")
    unit = units[0]
    names = git.run("diff", "--name-only", f"{unit.base}..{unit.head}").stdout.split()
    files = [cf(n, "A" if n.startswith("tests/") else "M") for n in names]
    unit_files = {
        n: git.run("show", f"{unit.head}:{unit.spec_dir}/{n}").stdout for n in ("proposal.md", "tasks.md")
    }  # fmt: skip
    tree = git.run("ls-tree", "-r", "--name-only", unit.head).stdout.split()
    got = check_scope(ScopeContext(files, declared_scope(unit_files, tree), cfg("fail"), unit_dir=unit.spec_dir))
    assert not got.findings and [f.label for f in got.files] == ["relevant"] * len(files)


def test_a_bare_module_name_in_prose_does_not_declare_the_module():
    scope = declared_scope({"proposal.md": "## Impact\n\nTouches `inventory` and `shop`.\n"}, TREE)
    assert scope.empty


def test_empty_scope_under_fail_holds_instead_of_passing_silently():
    spec = {"proposal.md": "## Impact\nAdds a bulk discount to pricing."}
    changed = [cf("src/inventory/stock.py"), cf("src/shop/pricing.py"), cf("tests/test_x.py", "A")]
    ctx = ScopeContext(changed, declared_scope(spec, TREE), cfg("fail"), unit_dir=SPEC_DIR)
    out = check_scope(ctx)
    assert out.findings == [] and out.skipped
    assert out.holds == ["scope: the spec declares no path or module; the changed modules are `inventory`, `shop`"]
    for policy in ("off", "warn"):
        assert check_scope(ScopeContext(changed, ctx.scope, cfg(policy), unit_dir=SPEC_DIR)).holds == []
    assert check_scope(ScopeContext([cf("README.md")], ctx.scope, cfg("fail"), unit_dir=SPEC_DIR)).holds == []


REAL_PATHS = [  # dummy-agentic !15, range 8ff4f030..390aa7ea (copied from `git diff --name-status`)
    "openspec/changes/add-shipping-fee-fix-1/.l4/fix.json",
    "openspec/changes/add-shipping-fee-fix-1/.openspec.yaml",
    "openspec/changes/add-shipping-fee-fix-1/proposal.md",
    "openspec/changes/add-shipping-fee-fix-1/specs/shipping/spec.md",
    "openspec/changes/add-shipping-fee/.l4/evidence/round-1/verdict.json",
    "openspec/changes/add-shipping-fee/.l4/ledger/r-20261004T2008Z-5488.jsonl",
    "openspec/changes/add-shipping-fee/.l4/ledger/r-20261004T2013Z-f889.jsonl",
    "openspec/changes/add-shipping-fee/questions.md",
]


@pytest.mark.parametrize("unit_dir", ["openspec/changes/add-shipping-fee", "openspec/changes/add-shipping-fee-fix-1"])
def test_harness_and_spec_files_in_any_change_directory_are_exempt(unit_dir: str):
    """A-B1: another change directory's `.l4/` and `.openspec.yaml` are not code, from either unit's range."""
    scope = declared_scope({"proposal.md": "## Impact\n\n- `src/pricing/shipping.py`\n"}, TREE)
    files = classify_files([cf(p, "A") for p in REAL_PATHS], scope, cfg(), unit_dir=unit_dir)
    assert {f.kind for f in files} == {"exempt"} and {f.label for f in files} == {None}
    out = check_scope(ScopeContext([cf(p, "A") for p in REAL_PATHS], scope, cfg("warn"), unit_dir=unit_dir))
    assert out.holds == [] and out.findings == []


@pytest.mark.parametrize(
    "path",
    [".l4/ledger/x.jsonl", "packages/app/.l4/x.json", ".l4-out/junit.xml", "svc/.l4-out/a.xml",
     "openspec/changes/other/design.md", "openspec/changes/other/specs/a/data.json",
     "openspec/changes/archive/x/.openspec.yaml",
     ".kiro/specs/feature/requirements.md", ".kiro/specs/feature/tasks.json", ".kiro/specs/feature/.config.kiro"],
)  # fmt: skip
def test_harness_and_spec_paths_at_any_depth_are_exempt(path: str):
    scope = declared_scope({"proposal.md": "## Impact\n\n- `src/shop/pricing.py`\n"}, TREE)
    (fs,) = classify_files([cf(path)], scope, cfg(), unit_dir=SPEC_DIR)
    assert fs.kind == "exempt" and fs.label is None


def test_a_source_file_is_not_exempt_for_living_near_a_harness_name():
    scope = declared_scope({"proposal.md": "## Impact\n\n- `src/shop/pricing.py`\n"}, TREE)
    (fs,) = classify_files([cf("src/inventory/l4/stock.py")], scope, cfg(), unit_dir=SPEC_DIR)
    assert fs.kind == "code" and fs.label == "out_of_scope"


# -- a fix unit inherits its parent's declared scope (round 5b)

PARENT_DIR = "openspec/changes/add-cart"
FIX_DIR = f"{PARENT_DIR}-fix-1"
FIX_TREE = [*TREE, "src/shop/cart.py"]
FIX_PROPOSAL = "## Why\n\nReview findings.\n\n## Impact\n\nThe code and the tests of `add-cart`.\n"
MARKER = '{"schema": "l4/fix-unit@1", "parent": "openspec:add-cart", "round": 1, "findings": ["F1"], "chores": []}'


def _repo(parent_proposal: str, *, marker: str | None = MARKER, fix_proposal: str = FIX_PROPOSAL):
    files = {f"{PARENT_DIR}/proposal.md": parent_proposal, f"{FIX_DIR}/proposal.md": fix_proposal}
    if marker is not None:
        files[f"{FIX_DIR}/.l4/fix.json"] = marker
    return files.get


def test_a_fix_unit_that_names_nothing_inherits_its_parents_scope():
    read = _repo("## Impact\n\n- `src/shop/cart.py`\n")
    fix = unit_declared_scope(read, FIX_DIR, FIX_TREE)
    assert not fix.empty and "src/shop/cart.py" in fix.paths and "shop" in fix.modules
    labels = {
        f.path: f.label
        for f in classify_files([cf("src/shop/cart.py"), cf("src/inventory/stock.py")], fix, cfg(), unit_dir=FIX_DIR)
    }
    assert labels == {"src/shop/cart.py": "relevant", "src/inventory/stock.py": "out_of_scope"}

    def run(policy: str):
        return check_scope(ScopeContext([cf("src/inventory/stock.py")], fix, cfg(policy), unit_dir=FIX_DIR))

    assert len(run("warn").holds) == 1 and not run("warn").skipped
    assert [f.severity for f in run("fail").findings] == [Severity.MAJOR]
    assert not check_scope(ScopeContext([cf("src/shop/cart.py")], fix, cfg("fail"), unit_dir=FIX_DIR)).findings


def test_a_fix_units_own_scope_is_kept_with_the_parents():
    read = _repo("## Impact\n\n- `src/shop/cart.py`\n", fix_proposal="## Impact\n\n- `src/inventory/stock.py`\n")
    fix = unit_declared_scope(read, FIX_DIR, FIX_TREE)
    assert set(fix.paths) == {"src/shop/cart.py", "src/inventory/stock.py"}


def test_a_parent_never_inherits_from_its_fix_units():
    read = _repo("## Impact\n\n- `src/shop/cart.py`\n", fix_proposal="## Impact\n\n- `src/inventory/stock.py`\n")
    assert unit_declared_scope(read, PARENT_DIR, FIX_TREE).paths == ("src/shop/cart.py",)


def test_a_fix_unit_of_a_parent_that_declares_nothing_is_skipped_as_before():
    fix = unit_declared_scope(_repo("## Impact\n\nNothing in backticks.\n"), FIX_DIR, FIX_TREE)
    assert fix.empty
    out = check_scope(ScopeContext([cf("src/inventory/stock.py")], fix, cfg("warn"), unit_dir=FIX_DIR))
    assert out.skipped and not out.holds and not out.findings
    assert len(check_scope(ScopeContext([cf("src/inventory/stock.py")], fix, cfg("fail"), unit_dir=FIX_DIR)).holds) == 1


@pytest.mark.parametrize(
    "marker", [None, "not json", '{"schema": "other@1", "parent": "x"}', '{"schema": "l4/fix-unit@1"}']
)
def test_without_a_valid_marker_a_unit_is_not_a_fix_unit(marker):
    read = _repo("## Impact\n\n- `src/shop/cart.py`\n", marker=marker)
    assert unit_declared_scope(read, FIX_DIR, FIX_TREE).empty


def test_a_file_only_a_human_changed_raises_no_hold():
    """Per-commit attribution (sandbox-security 2.10, M1.9): a person's change during review is not the unit's scope."""
    scope = declared_scope({"proposal.md": "## Impact\n\n- `src/shop/pricing.py`\n"}, TREE)
    changed = [
        ChangedFile("src/shop/pricing.py", "M"),
        ChangedFile("src/inventory/stock.py", "M", human="abcdef1234"),  # only people's commits touched it
        ChangedFile("src/inventory/stock.py".replace("stock", "other"), "M"),  # the harness's, out of scope
    ]
    out = check_scope(ScopeContext(changed, scope, cfg("warn"), unit_dir=SPEC_DIR))
    by_path = {f.path: f for f in out.files}
    human = by_path["src/inventory/stock.py"]
    assert (human.kind, human.label, human.reason) == ("exempt", None, "changed by human commit abcdef1234")
    assert out.holds == ["scope: `src/inventory/other.py` changes module `inventory`, which the spec does not name"]
    assert by_path["src/inventory/other.py"].label == "out_of_scope"


def test_scope_evidence_attributes_each_file_to_its_commits(make_repo, raw, git_for):
    from types import SimpleNamespace

    from l4.evidence.collect import scope_evidence
    from l4.specs.base import Framework, UnitRef

    repo = make_repo()
    unit = repo / "openspec" / "changes" / "add-x"
    unit.mkdir(parents=True)
    (unit / "proposal.md").write_text("## Impact\n\n- `src/shop/pricing.py`\n")
    (repo / "src" / "shop").mkdir(parents=True)
    (repo / "src" / "inventory").mkdir(parents=True)
    for rel in ("src/shop/pricing.py", "src/inventory/stock.py", "src/inventory/ours.py"):
        (repo / rel).write_text("x = 1\n")
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "base")
    base = raw(repo, "rev-parse", "HEAD").strip()
    bot = ("-c", "user.name=l4-bot", "-c", "user.email=l4-bot@users.noreply.invalid")
    for rel in ("src/shop/pricing.py", "src/inventory/ours.py"):
        (repo / rel).write_text("x = 2\n")
    raw(repo, "add", "-A")
    raw(repo, *bot, "commit", "-q", "-m", "work", "--trailer", "L4-Run: r-1")
    (repo / "src/inventory/stock.py").write_text("x = 3\n")
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "a person's fix")
    human = raw(repo, "rev-parse", "HEAD").strip()
    head = human
    ref = UnitRef(Framework.OPENSPEC, "add-x", unit)
    bench = SimpleNamespace(git=git_for(repo), cfg=L4Config.model_validate({}), worktree=repo)
    step1 = scope_evidence(bench, base, head, ref)
    files = {f.path: f for f in step1.outcome.files}
    assert files["src/inventory/stock.py"].reason == f"changed by human commit {human[:10]}"
    assert files["src/inventory/ours.py"].label == "out_of_scope"  # the harness changed it: held to the spec
    assert [h.subjects for h in step1.holds] == [("src/inventory/ours.py",)]


def test_a_kiro_units_requirements_and_bugfix_files_declare_scope_like_the_design():
    """Owner decision 7: a path named only in a Kiro unit's `requirements.md` or `bugfix.md` is declared."""
    files = {
        ".kiro/specs/tip/requirements.md": "1. WHEN asked THEN `src/shop/pricing.py` SHALL answer.\n",
        ".kiro/specs/tip/bugfix.md": "2.1 WHEN x THEN `src/inventory/stock.py` SHALL hold.\n",
        ".kiro/specs/tip/design.md": "# Design\n",
    }
    scope = unit_declared_scope(files.get, ".kiro/specs/tip", TREE)
    assert {"src/shop/pricing.py", "src/inventory/stock.py"} <= set(scope.paths)
