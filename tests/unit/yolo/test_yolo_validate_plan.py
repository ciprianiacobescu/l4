"""`scripts/validate_plan.py` (L4-YOLO-019, design D15; SCN-YOLO-39, -40, -41): the standalone plan validator.

It is held to the harness three ways: its discovery equals the providers' `list_units`, its schema verdict equals
`model.load_plan` on every fixture, and its graph (cycle text, dispatch order) is admission's."""

import ast
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from l4.config.schema import L4Config
from l4.specs.detect import collect_units
from l4.specs.providers import providers_for
from l4.yolo.admit import admit, plan_order
from l4.yolo.model import Plan, UnitInfo, load_plan

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "validate_plan.py"
SKILL_COPY = ROOT / "plugins" / "l4" / "skills" / "l4" / "scripts" / "validate_plan.py"
SCHEMA = "l4/delivery-plan@1"


def load_script():
    spec = importlib.util.spec_from_file_location("validate_plan_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


vp = load_script()


def run(repo: Path, *argv: str, python=(sys.executable, "-I")):
    done = subprocess.run(
        [*python, str(SCRIPT), "--repo", str(repo), *argv], capture_output=True, text=True, timeout=60
    )
    return done.returncode, done.stdout, done.stderr


# --- the repository fixtures --------------------------------------------------------------------------------


def touch(repo: Path, rel: str, text: str = "x\n") -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def change(repo: Path, name: str, root: str = "openspec") -> None:
    touch(repo, f"{root}/changes/{name}/proposal.md", "# p\n")


def spec(repo: Path, name: str, file: str = "requirements.md", root: str = ".kiro/specs") -> None:
    touch(repo, f"{root}/{name}/{file}", "# r\n")


def plan(plan_id: str, batches: list, **over) -> dict:
    return {"schema": SCHEMA, "plan_id": plan_id, "target": "main", "merge": "human", "batches": batches, **over}


def put(repo: Path, doc, plan_id: str | None = None) -> None:
    text = doc if isinstance(doc, str) else json.dumps(doc, indent=2)
    touch(repo, f".l4/plans/{plan_id or doc['plan_id']}.json", text)


def units(*ids: str, deps: dict | None = None) -> dict:
    return {"id": "b1", "units": [{"id": i, "depends_on": (deps or {}).get(i, [])} for i in ids]}


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "openspec" / "changes").mkdir(parents=True)
    touch(root, "openspec/config.yaml", "schema: spec-driven\n")
    return root


# --- the copy and the standard library ----------------------------------------------------------------------


def test_the_two_copies_are_byte_equal():
    assert SCRIPT.read_bytes() == SKILL_COPY.read_bytes()


def test_the_script_needs_only_the_standard_library_and_loads_no_other_module():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported = {
        (n.module if isinstance(n, ast.ImportFrom) else a.name).split(".")[0]
        for n in ast.walk(tree)
        if isinstance(n, (ast.Import, ast.ImportFrom))
        for a in (n.names if isinstance(n, ast.Import) else [None])
    }
    assert imported <= {
        "__future__",
        "argparse",
        "datetime",
        "decimal",
        "heapq",
        "json",
        "os",
        "re",
        "stat",
        "sys",
        "pathlib",
    }
    code = (
        "import importlib.util, sys\n"
        "before = set(sys.modules)\n"
        f"s = importlib.util.spec_from_file_location('vp', {str(SCRIPT)!r}); m = importlib.util.module_from_spec(s)\n"
        "s.loader.exec_module(m)\n"
        "files = {n: getattr(sys.modules[n], '__file__', '') or '' for n in set(sys.modules) - before}\n"
        "bad = sorted(n for n, f in files.items() if 'site-packages' in f)\n"
        "print(bad, 'l4' in sys.modules, 'pydantic' in sys.modules, 'yaml' in sys.modules)\n"
    )
    done = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[] False False False"


def test_it_writes_nothing_and_never_runs_git(repo):
    for name in ("a", "b"):
        change(repo, name)
    put(repo, plan("p1", [units("openspec:a")]))
    before = sorted((p.relative_to(repo).as_posix(), p.stat().st_mtime_ns) for p in repo.rglob("*"))
    run(repo)
    assert sorted((p.relative_to(repo).as_posix(), p.stat().st_mtime_ns) for p in repo.rglob("*")) == before
    source = SCRIPT.read_text(encoding="utf-8")
    assert "subprocess" not in source and "socket" not in source and "urllib" not in source
    assert "write_text" not in source and "open(" not in source


# --- discovery: the providers' rules ------------------------------------------------------------------------


def provider_ids(repo: Path, **spec_cfg) -> list[str]:
    cfg = L4Config.model_validate({"spec": spec_cfg} if spec_cfg else {})
    return sorted(u.id for u in collect_units(providers_for(cfg, repo, {})))


def script_ids(repo: Path, *flags: str) -> list[str]:
    args = vp.parser().parse_args(["--repo", str(repo), *flags])
    return sorted(vp.discover_units(repo, args)[0])


def messy(repo: Path) -> None:
    for name in ("good", "two-words", "UPPER", "under_score", "archive", "-lead"):
        change(repo, name)
    touch(repo, "openspec/changes/just-a-file", "x")
    touch(repo, "openspec/changes/archive/2026-01-01-old/proposal.md")
    (repo / "elsewhere").mkdir()
    (repo / "openspec" / "changes" / "linked").symlink_to(repo / "elsewhere", target_is_directory=True)
    spec(repo, "alpha")
    spec(repo, "beta.v2", "tasks.md")
    spec(repo, "gamma", "design.md")
    spec(repo, "delta", "bugfix.md")
    spec(repo, "_hidden")
    spec(repo, "no-spec-file", "notes.md")
    (repo / ".kiro" / "specs" / "empty").mkdir()
    (repo / ".kiro" / "specs" / "linkdir").symlink_to(repo / "elsewhere", target_is_directory=True)
    (repo / "elsewhere" / "requirements.md").write_text("x", encoding="utf-8")
    (repo / ".kiro" / "specs" / "onlylink").mkdir()
    (repo / ".kiro" / "specs" / "onlylink" / "design.md").symlink_to(repo / "elsewhere" / "requirements.md")


def test_the_discovery_equals_the_providers_on_a_messy_tree(repo):
    messy(repo)
    expected = provider_ids(repo)
    assert "openspec:good" in expected and "kiro:alpha" in expected and "openspec:archive" not in expected
    assert script_ids(repo) == expected
    assert script_ids(repo, "--frameworks", "openspec,kiro") == provider_ids(repo, frameworks=["openspec", "kiro"])
    assert script_ids(repo, "--frameworks", "kiro") == provider_ids(repo, frameworks=["kiro"])
    assert script_ids(repo, "--frameworks", "openspec") == provider_ids(repo, frameworks=["openspec"])


def test_the_discovery_equals_the_providers_with_other_roots(tmp_path):
    repo = tmp_path / "r"
    change(repo, "one", root="specs/os")
    touch(repo, "specs/os/config.yaml", "schema: spec-driven\n")
    spec(repo, "k1", root="docs/kiro")
    flags = ("--openspec-root", "specs/os", "--kiro-root", "docs/kiro")
    cfg = {"openspec": {"root": "specs/os"}, "kiro": {"root": "docs/kiro"}}
    assert script_ids(repo, *flags) == provider_ids(repo, **cfg) == ["kiro:k1", "openspec:one"]


def test_a_symlinked_root_lists_nothing_like_the_providers(tmp_path):
    repo = tmp_path / "r"
    (repo / "real" / "changes" / "x").mkdir(parents=True)
    (repo / "real" / "changes" / "x" / "proposal.md").write_text("x", encoding="utf-8")
    (repo / "real" / "config.yaml").write_text("x", encoding="utf-8")
    (repo / "openspec").symlink_to(repo / "real", target_is_directory=True)
    assert script_ids(repo) == provider_ids(repo, frameworks=["openspec"]) == []


def test_auto_finds_no_openspec_without_its_markers(tmp_path):
    repo = tmp_path / "r"
    write_config(repo, {"version": 1})  # no spec key: spec.frameworks is auto, as in the harness
    change(repo, "x")  # openspec/changes exists, so detection finds the framework
    assert script_ids(repo) == provider_ids(repo) == ["openspec:x"]
    legacy = tmp_path / "legacy"
    write_config(legacy, {"version": 1})
    touch(legacy, "openspec/project.md")
    change(legacy, "y")
    assert script_ids(legacy) == provider_ids(legacy) == []


# --- the configuration reader -------------------------------------------------------------------------------


def write_config(repo: Path, body: dict | str) -> None:
    touch(repo, ".l4/config.yaml", body if isinstance(body, str) else yaml.safe_dump(body, sort_keys=False))


def read_spec(repo: Path):
    return vp.read_spec_config(repo)


@pytest.mark.parametrize(
    "spec_cfg",
    [
        {"frameworks": ["openspec"]},
        {"frameworks": "auto"},
        {"frameworks": ["openspec", "kiro"], "kiro": {"root": "k/specs"}, "openspec": {"root": "o"}},
        {"openspec": {"root": "a/b", "version": "1.2.3"}, "primary": "kiro"},
    ],
)
def test_the_reader_agrees_with_yaml_on_what_l4_init_writes(repo, spec_cfg):
    body = {"version": 1, "gates": {"test": {"command": "pytest -q"}}, "spec": spec_cfg, "roles": {"x": ["a", "b"]}}
    write_config(repo, body)
    parsed, warnings = read_spec(repo)
    assert warnings == []

    def plain(value):
        return {k: plain(v) for k, v in value.items()} if isinstance(value, dict) else value

    assert plain(parsed) == spec_cfg


def test_the_reader_reads_inline_lists_quotes_and_comments(repo):
    write_config(
        repo,
        "version: 1\nspec:  # the specs\n  frameworks: [openspec, 'kiro']  # both\n"
        '  kiro:\n    root: ".kiro/s" # here\n'
        "gates:\n  test:\n    command: |\n      pytest\n",
    )
    parsed, warnings = read_spec(repo)
    assert warnings == [] and parsed == {"frameworks": ["openspec", "kiro"], "kiro": {"root": ".kiro/s"}}


@pytest.mark.parametrize(
    "text",
    [
        "spec: {frameworks: [kiro]}\n",
        "spec:\n  frameworks: &a [kiro]\n",
        "spec:\n\tframeworks: kiro\n",
        "spec:\n  frameworks:\n    - {a: b}\n",
        "spec:\n  frameworks: |\n    kiro\n",
    ],
)
def test_anything_else_falls_back_to_both_frameworks_with_a_warning(repo, text):
    write_config(repo, text)
    spec_cfg, warnings = read_spec(repo)
    assert spec_cfg == {} and len(warnings) == 1
    args = vp.parser().parse_args(["--repo", str(repo)])
    frameworks, openspec_root, kiro_root, _ = vp.resolve_discovery(repo, args)
    assert (frameworks, openspec_root, kiro_root) == (["openspec", "kiro"], "openspec", ".kiro/specs")


@pytest.mark.parametrize(
    "text",
    [
        '"spec":\n  frameworks: [openspec]\n',
        "'spec':\n  frameworks: [openspec]\n",
        "\ufeffspec:\n  frameworks: [openspec]\n",
        'spec:\n  "frameworks": [openspec]\n',
        "spec:\n  'frameworks':\n    - openspec\n",
        'spec:\n  "frameworks": [openspec]\n',
    ],
)
def test_a_quoted_spec_key_and_a_byte_order_mark_are_read_like_yaml_reads_them(repo, text):  # L3
    assert yaml.safe_load(text.lstrip("\ufeff"))["spec"] == {"frameworks": ["openspec"]}
    write_config(repo, text)
    spec_cfg, warnings = read_spec(repo)
    assert warnings == [] and spec_cfg == {"frameworks": ["openspec"]}
    args = vp.parser().parse_args(["--repo", str(repo)])
    assert vp.resolve_discovery(repo, args)[0] == ["openspec"]


def test_no_config_file_is_a_warning_and_the_defaults(repo):
    change(repo, "a")
    put(repo, plan("p1", [units("openspec:a")]))
    code, out, err = run(repo)
    assert code == 0 and "warning:" in err and "config.yaml" in err


def test_the_flags_override_the_file(repo):
    write_config(repo, {"spec": {"frameworks": ["openspec"], "kiro": {"root": "nowhere"}}})
    spec(repo, "k1", root="custom")
    args = vp.parser().parse_args(["--repo", str(repo), "--frameworks", "kiro", "--kiro-root", "custom"])
    assert vp.discover_units(repo, args)[0] == ["kiro:k1"]


def test_the_config_roots_are_used(repo):
    write_config(repo, {"spec": {"frameworks": ["kiro"], "kiro": {"root": "custom"}}})
    spec(repo, "k1", root="custom")
    assert script_ids(repo) == ["kiro:k1"]


# --- the schema: the same verdict as load_plan --------------------------------------------------------------

BASE = plan("p1", [{"id": "b", "units": [{"id": "x"}]}])


def variant(**over) -> str:
    return json.dumps({**BASE, **over})


def without(*keys: str) -> str:
    return json.dumps({k: v for k, v in BASE.items() if k not in keys})


FIXTURES = {
    "valid": json.dumps(BASE),
    "valid full": variant(
        limits={"max_cost_usd": 5, "max_unit_attempts": 3, "max_runs": 9, "deadline": "2026-12-31T18:00:00Z"},
        promotion={"mode": "manual", "target_branch": "release"},
        exclude=[{"id": "y", "reason": "r"}],
        batches=[{"id": "b", "depends_on": [], "acceptance_profile": "all", "units": [{"id": "x", "depends_on": []}]}],
    ),
    "not json": "{ nope",
    "empty": "",
    "list": "[]",
    "null": "null",
    "bom": "﻿" + json.dumps(BASE),
    "no schema": without("schema"),
    "schema_id alias": json.dumps({**{k: v for k, v in BASE.items() if k != "schema"}, "schema_id": SCHEMA}),
    "wrong schema": variant(schema="l4/delivery-plan@2"),
    "no plan_id": without("plan_id"),
    "plan_id int": variant(plan_id=1),
    "plan_id upper": variant(plan_id="P1"),
    "plan_id empty": variant(plan_id=""),
    "plan_id long": variant(plan_id="a" * 64),
    "plan_id max": variant(plan_id="a" * 63),
    "plan_id other than the file": variant(plan_id="p2"),
    "no target": without("target"),
    "target empty": variant(target=""),
    "no merge": without("merge"),
    "merge bad": variant(merge="AUTO"),
    "merge auto": variant(merge="auto"),
    "no batches": without("batches"),
    "batches null": variant(batches=None),
    "batches empty": variant(batches=[]),
    "batch without units": variant(batches=[{"id": "b"}]),
    "batch without id": variant(batches=[{"units": []}]),
    "batch unknown field": variant(batches=[{"id": "b", "units": [], "x": 1}]),
    "unit without id": variant(batches=[{"id": "b", "units": [{}]}]),
    "unit id int": variant(batches=[{"id": "b", "units": [{"id": 1}]}]),
    "unit unknown field": variant(batches=[{"id": "b", "units": [{"id": "x", "x": 1}]}]),
    "unit depends null": variant(batches=[{"id": "b", "units": [{"id": "x", "depends_on": None}]}]),
    "unit depends item": variant(batches=[{"id": "b", "units": [{"id": "x", "depends_on": [1]}]}]),
    "unit not object": variant(batches=[{"id": "b", "units": ["x"]}]),
    "profile int": variant(batches=[{"id": "b", "acceptance_profile": 1, "units": []}]),
    "unknown top field": variant(parallel=3),
    "limits null": variant(limits=None),
    "limits unknown": variant(limits={"x": 1}),
    "cost int": variant(limits={"max_cost_usd": 5}),
    "cost zero": variant(limits={"max_cost_usd": 0}),
    "cost negative": variant(limits={"max_cost_usd": -1}),
    "cost bool": variant(limits={"max_cost_usd": True}),
    "cost string": variant(limits={"max_cost_usd": "5"}),
    "cost null": variant(limits={"max_cost_usd": None}),
    "cost nan": f'{{"schema": "{SCHEMA}", "plan_id": "p1", "target": "t", "merge": "human", "batches": [], '
    '"limits": {"max_cost_usd": NaN}}',
    "attempts zero": variant(limits={"max_unit_attempts": 0}),
    "attempts float": variant(limits={"max_unit_attempts": 2.0}),
    "attempts null": variant(limits={"max_unit_attempts": None}),
    "attempts bool": variant(limits={"max_unit_attempts": True}),
    "runs zero": variant(limits={"max_runs": 0}),
    "runs null": variant(limits={"max_runs": None}),
    "runs float": variant(limits={"max_runs": 3.0}),
    "deadline naive": variant(limits={"deadline": "2026-12-31T18:00:00"}),
    "deadline date": variant(limits={"deadline": "2026-12-31"}),
    "deadline offset": variant(limits={"deadline": "2026-12-31 18:00:00+02:00"}),
    "deadline compact offset": variant(limits={"deadline": "2026-12-31T18:00+0200"}),
    "deadline hour offset": variant(limits={"deadline": "2026-12-31T18:00:00+01"}),
    "deadline lower z": variant(limits={"deadline": "2026-12-31t18:00:00z"}),
    "deadline fraction": variant(limits={"deadline": "2026-12-31T18:00:00.5Z"}),
    "deadline hour 24": variant(limits={"deadline": "2026-12-31T24:00:00Z"}),
    "deadline second 60": variant(limits={"deadline": "2026-12-31T18:00:60Z"}),
    "deadline day 30 of feb": variant(limits={"deadline": "2026-02-30T10:00:00Z"}),
    "deadline offset 24": variant(limits={"deadline": "2026-12-31T18:00:00+24:00"}),
    "deadline offset minute 60": variant(limits={"deadline": "2026-12-31T18:00:00+00:60"}),
    "deadline unix int": variant(limits={"deadline": 1767225600}),
    "deadline unix string": variant(limits={"deadline": "1767225600"}),
    "deadline padded": variant(limits={"deadline": " 2026-12-31T18:00:00Z"}),
    "deadline null": variant(limits={"deadline": None}),
    "deadline junk": variant(limits={"deadline": "soon"}),
    "deadline unix '1760000000.5'": variant(limits={"deadline": "1760000000.5"}),
    "deadline unix '-1'": variant(limits={"deadline": "-1"}),
    "deadline unix '99999999999999999999'": variant(limits={"deadline": "99999999999999999999"}),
    "deadline unix '1760000000.'": variant(limits={"deadline": "1760000000."}),
    "deadline unix '+1'": variant(limits={"deadline": "+1"}),
    "deadline unix '.5'": variant(limits={"deadline": ".5"}),
    "deadline unix '1e3'": variant(limits={"deadline": "1e3"}),
    "deadline unix '1_000'": variant(limits={"deadline": "1_000"}),
    "deadline unix '-0.5'": variant(limits={"deadline": "-0.5"}),
    "deadline unix '0'": variant(limits={"deadline": "0"}),
    "deadline unix '00012'": variant(limits={"deadline": "00012"}),
    "deadline unix '253402300799999'": variant(limits={"deadline": "253402300799999"}),
    "deadline unix '253402300800000'": variant(limits={"deadline": "253402300800000"}),
    "deadline unix '-62135596800000'": variant(limits={"deadline": "-62135596800000"}),
    "deadline unix '-62135596800001'": variant(limits={"deadline": "-62135596800001"}),
    "deadline unix '1000000000000000'": variant(limits={"deadline": "1000000000000000"}),
    "deadline unix '1111111111111111111.5'": variant(limits={"deadline": "1111111111111111111.5"}),
    "deadline unix '111111111111111111.5'": variant(limits={"deadline": "111111111111111111.5"}),
    "deadline unix '-1111111111111111111.5'": variant(limits={"deadline": "-1111111111111111111.5"}),
    "deadline unix '-111111111111111.5'": variant(limits={"deadline": "-111111111111111.5"}),
    "deadline unix '9223372036854775807'": variant(limits={"deadline": "9223372036854775807"}),
    "deadline unix '9223372036854775808'": variant(limits={"deadline": "9223372036854775808"}),
    "deadline unix '20000000000.5'": variant(limits={"deadline": "20000000000.5"}),
    "deadline unix '٣'": variant(limits={"deadline": "٣"}),
    "deadline unix '1 '": variant(limits={"deadline": "1 "}),
    "deadline unix ' 1'": variant(limits={"deadline": " 1"}),
    "deadline unix '.'": variant(limits={"deadline": "."}),
    "promotion null": variant(promotion=None),
    "promotion ok": variant(promotion={"mode": "manual", "target_branch": "x"}),
    "promotion mode": variant(promotion={"mode": "auto", "target_branch": "x"}),
    "promotion no branch": variant(promotion={"mode": "manual"}),
    "promotion unknown": variant(promotion={"mode": "manual", "target_branch": "x", "y": 1}),
    "external empty": variant(external_dependencies=[]),
    "external object": variant(external_dependencies=[{}]),
    "external int": variant(external_dependencies=[1]),
    "external null": variant(external_dependencies=None),
    "exclude ok": variant(exclude=[{"id": "y", "reason": "r"}]),
    "exclude null": variant(exclude=None),
    "exclude string": variant(exclude="y"),
    "exclude no reason": variant(exclude=[{"id": "y"}]),
    "exclude empty reason": variant(exclude=[{"id": "y", "reason": ""}]),
    "exclude 200": variant(exclude=[{"id": "y", "reason": "r" * 200}]),
    "exclude 201": variant(exclude=[{"id": "y", "reason": "r" * 201}]),
    "exclude unknown": variant(exclude=[{"id": "y", "reason": "r", "z": 1}]),
    "exclude no id": variant(exclude=[{"reason": "r"}]),
    "exclude id int": variant(exclude=[{"id": 3, "reason": "r"}]),
    "exclude not object": variant(exclude=["y"]),
    "duplicate keys": f'{{"schema": "{SCHEMA}", "plan_id": "p1", "plan_id": "p2", "target": "t", "merge": "human", '
    '"batches": []}',
}


def model_verdict(text: str, name: str) -> bool:
    return isinstance(load_plan(text, file_name=name), Plan)


def script_verdict(text: str, name: str) -> bool:
    report = vp.check_plan(name, text, set(), set())
    return not any(code in ("invalid", "external_dependencies") for code, _, _ in report.problems)


@pytest.mark.parametrize("label", sorted(FIXTURES))
def test_the_schema_verdict_equals_load_plan(label):
    text = FIXTURES[label]
    assert script_verdict(text, "p1.json") == model_verdict(text, "p1.json"), label


def test_the_fixtures_include_both_verdicts():
    verdicts = {model_verdict(t, "p1.json") for t in FIXTURES.values()}
    assert verdicts == {True, False}


def test_the_external_dependencies_have_their_admission_code():
    report = vp.check_plan("p1.json", variant(external_dependencies=[{"repo": "x"}]), set(), set())
    assert [(c, s) for c, s, _ in report.problems] == [("external_dependencies", "p1")]


def test_a_schema_problem_names_the_field_and_stops_the_graph_checks(repo):
    change(repo, "a")
    put(repo, variant(parallel=3, batches=[units("openspec:a", deps={"openspec:a": ["openspec:a"]})]), "p1")
    code, out, _ = run(repo)
    assert code == 1 and "p1: invalid: parallel: unknown field" in out and "self_dependency" not in out


# --- the graph: admission's graph ---------------------------------------------------------------------------


def admission(text: str, known: list[str]):
    parsed = load_plan(text)
    assert isinstance(parsed, Plan), parsed
    info = {i: UnitInfo(id=i, folder="f") for i in known}
    cfg = L4Config.model_validate({"forge": {"base_branch": "main"}})
    return parsed, admit(parsed, known_units=info, cfg=cfg)


GRAPHS = {
    "chain": [
        units(
            "openspec:a", "openspec:b", "openspec:c", deps={"openspec:b": ["openspec:a"], "openspec:c": ["openspec:b"]}
        )
    ],
    "reverse file order": [
        units(
            "openspec:c", "openspec:b", "openspec:a", deps={"openspec:b": ["openspec:a"], "openspec:c": ["openspec:b"]}
        )
    ],
    "ties by batch then unit": [
        {"id": "b1", "units": [{"id": "x"}, {"id": "y", "depends_on": ["z"]}, {"id": "z"}]},
        {"id": "b2", "units": [{"id": "w"}]},
    ],
    "batch prerequisites": [
        {"id": "b1", "units": [{"id": "a"}, {"id": "b"}]},
        {"id": "b2", "depends_on": ["b1"], "units": [{"id": "c"}, {"id": "d", "depends_on": ["c"]}]},
        {"id": "b3", "depends_on": ["b2"], "units": [{"id": "e"}]},
        {"id": "b0", "units": [{"id": "f"}]},
    ],
    "diamond": [
        {"id": "b1", "units": [{"id": "a"}, {"id": "b", "depends_on": ["a"]}, {"id": "c", "depends_on": ["a"]}]},
        {"id": "b2", "units": [{"id": "d", "depends_on": ["b", "c"]}]},
    ],
}


def ids_of(batches) -> list[str]:
    return [u["id"] for b in batches for u in b["units"]]


@pytest.mark.parametrize("label", sorted(GRAPHS))
def test_the_dispatch_order_equals_admission_s(label):
    text = json.dumps(plan("p1", GRAPHS[label]))
    parsed, result = admission(text, ids_of(GRAPHS[label]))
    assert result.ok
    report = vp.check_plan("p1.json", text, set(ids_of(GRAPHS[label])), set())
    assert report.problems == [] and tuple(report.order) == plan_order(parsed) == result.order


FAULTY = {
    "duplicate unit": [{"id": "b1", "units": [{"id": "a"}, {"id": "a"}]}],
    "duplicate batch": [{"id": "b1", "units": [{"id": "a"}]}, {"id": "b1", "units": [{"id": "c"}]}],
    "self dependency": [{"id": "b1", "units": [{"id": "a", "depends_on": ["a"]}]}],
    "batch self dependency": [{"id": "b1", "depends_on": ["b1"], "units": [{"id": "a"}]}],
    "unknown dependency": [{"id": "b1", "units": [{"id": "a", "depends_on": ["ghost"]}]}],
    "unknown batch dependency": [{"id": "b1", "depends_on": ["ghost"], "units": [{"id": "a"}]}],
    "unit cycle": [{"id": "b1", "units": [{"id": "a", "depends_on": ["b"]}, {"id": "b", "depends_on": ["a"]}]}],
    "cycle through a batch": [
        {"id": "b1", "units": [{"id": "a", "depends_on": ["c"]}]},
        {"id": "b2", "depends_on": ["b1"], "units": [{"id": "c"}]},
    ],
    "batch cycle": [
        {"id": "b1", "depends_on": ["b2"], "units": [{"id": "a"}]},
        {"id": "b2", "depends_on": ["b1"], "units": [{"id": "c"}]},
    ],
    "empty": [],
}
SHARED = {"duplicate_id", "self_dependency", "unknown_dependency", "cycle", "empty_plan"}


@pytest.mark.parametrize("label", sorted(FAULTY))
def test_the_findings_are_admissions_with_the_same_text(label):
    text = json.dumps(plan("p1", FAULTY[label]))
    known = [i for i in ids_of(FAULTY[label])]
    _, result = admission(text, known)
    expected = sorted((f.code, f.subject, f.text) for f in result.findings if f.code in SHARED)
    report = vp.check_plan("p1.json", text, set(known), set())
    assert sorted(p for p in report.problems if p[0] in SHARED) == expected
    assert expected, label
    assert report.order is None


def test_a_planned_and_excluded_unit_and_a_repeated_exclusion_are_admissions():
    text = variant(exclude=[{"id": "x", "reason": "r"}, {"id": "z", "reason": "r"}, {"id": "z", "reason": "again"}])
    _, result = admission(text, ["x", "z"])
    expected = sorted((f.code, f.subject, f.text) for f in result.findings)
    got = sorted(vp.check_plan("p1.json", text, {"x", "z"}, set()).problems)
    assert got == expected and {c for c, _, _ in got} == {"excluded_and_planned", "duplicate_id"}


def test_an_unknown_unit_is_admissions_code_for_planned_and_excluded_units():
    text = variant(exclude=[{"id": "ghost", "reason": "r"}])
    _, result = admission(text, ["x"])
    got = vp.check_plan("p1.json", text, {"x"}, set()).problems
    assert [(f.code, f.subject) for f in result.findings] == [(c, s) for c, s, _ in got] == [("unknown_unit", "ghost")]
    planned = vp.check_plan("p1.json", variant(), set(), set()).problems
    assert [(c, s) for c, s, _ in planned] == [("unknown_unit", "x")]


# --- the scenarios ------------------------------------------------------------------------------------------


def test_a_cycle_through_a_batch_is_found_and_named(repo):  # SCN-YOLO-39
    for name in ("a", "c"):
        change(repo, name)
    batches = [
        {"id": "b1", "units": [{"id": "openspec:a", "depends_on": ["openspec:c"]}]},
        {"id": "b2", "depends_on": ["b1"], "units": [{"id": "openspec:c"}]},
    ]
    put(repo, plan("p1", batches))
    code, out, _ = run(repo)
    _, result = admission(json.dumps(plan("p1", batches)), ["openspec:a", "openspec:c"])
    cycle = next(f for f in result.findings if f.code == "cycle")
    assert code == 1
    assert out.strip() == f"p1: cycle: {cycle.subject}: {cycle.text}"
    assert "dependency cycle: openspec:a -> openspec:c -> b1 -> openspec:a" in out


def test_a_spec_no_plan_covers_is_found(repo):  # SCN-YOLO-40
    touch(repo, "openspec/changes/a/proposal.md")
    spec(repo, "new-report")
    put(repo, plan("p1", [units("openspec:a")]))
    put(repo, plan("p2", [units("openspec:a")]), "p2")
    code, out, _ = run(repo)
    assert code == 1
    assert "uncovered: kiro:new-report (add it to a plan or to a plan's exclude with a reason)" in out.splitlines()


def test_a_valid_plan_prints_its_order_and_waves(repo):  # SCN-YOLO-41
    names = "abcdefghij"
    for n in names:
        change(repo, n)
    u = {n: f"openspec:{n}" for n in names}
    dep = {"d": "abc", "e": "abc", "f": "d", "g": "e", "h": "f"}
    batches = [
        {"id": f"w{i + 1}", "units": [{"id": u[n], "depends_on": [u[x] for x in dep.get(n, "")]} for n in group]}
        for i, group in enumerate(["abc", "de", "fg", "h", "ij"])
    ]
    text = json.dumps(plan("p1", batches))
    put(repo, text, "p1")
    code, out, err = run(repo)
    parsed, result = admission(text, list(u.values()))
    assert code == 0, out + err
    lines = out.splitlines()
    assert "wave 1: " + ", ".join(u[n] for n in "abcij") in lines
    assert "wave 2: " + ", ".join(u[n] for n in "de") in lines
    assert "wave 3: " + ", ".join(u[n] for n in "fg") in lines
    assert "wave 4: " + u["h"] in lines and not any(line.startswith("wave 5") for line in lines)
    assert f"order: {', '.join(plan_order(parsed))}" in lines
    assert plan_order(parsed) == result.order


def test_waves_go_through_batch_nodes():
    batches = [
        {"id": "b1", "units": [{"id": "a"}, {"id": "b", "depends_on": ["a"]}]},
        {"id": "b2", "depends_on": ["b1"], "units": [{"id": "c"}]},
        {"id": "b3", "units": [{"id": "d"}]},
    ]
    report = vp.check_plan("p1.json", json.dumps(plan("p1", batches)), {"a", "b", "c", "d"}, set())
    assert report.waves == [["a", "d"], ["b"], ["c"]]


# --- coverage -----------------------------------------------------------------------------------------------


def test_an_excluded_unit_is_covered_and_so_is_a_derived_unit_of_a_listed_parent(repo):
    for name in ("a", "b", "a-fix-1", "a-followup-2", "b-fix-1"):
        change(repo, name)
    spec(repo, "k-followup-1")
    put(repo, plan("p1", [units("openspec:a")], exclude=[{"id": "openspec:b", "reason": "in review"}]))
    code, out, _ = run(repo)
    assert code == 1
    assert out.splitlines() == ["uncovered: kiro:k-followup-1 (add it to a plan or to a plan's exclude with a reason)"]


def test_a_unit_planned_in_two_plan_files_is_covered_twice(repo):
    change(repo, "a")
    put(repo, plan("p1", [units("openspec:a")]))
    put(repo, plan("p2", [units("openspec:a")]), "p2")
    code, out, _ = run(repo)
    assert code == 1 and out.splitlines() == ["covered_twice: openspec:a (listed in plans p1, p2)"]


def test_a_unit_planned_in_one_plan_and_excluded_in_another_is_fine(repo):
    change(repo, "a")
    put(repo, plan("p1", [units("openspec:a")]))
    put(
        repo,
        plan(
            "p2",
            [units("openspec:a")][:0] or [{"id": "b1", "units": []}],
            exclude=[{"id": "openspec:a", "reason": "p1 has it"}],
        ),
        "p2",
    )
    code, out, _ = run(repo)
    assert "covered_twice" not in out and "uncovered" not in out
    assert code == 1 and "p2: empty_plan" in out  # the only problem is p2 having nothing to deliver


def test_an_invalid_plan_file_still_covers_the_units_it_names(repo):
    change(repo, "a")
    put(repo, plan("p1", [units("openspec:a")], parallel=1))
    code, out, _ = run(repo)
    assert code == 1 and "uncovered" not in out and "p1: invalid: parallel: unknown field" in out


def test_a_planned_unit_whose_change_is_archived_is_accepted_with_a_finished_line(repo):  # L4-YOLO-019, Z1
    change(repo, "a")
    touch(repo, "openspec/changes/archive/2026-02-03-done/proposal.md")
    put(repo, plan("p1", [units("openspec:a", "openspec:done", deps={"openspec:a": ["openspec:done"]})]))
    code, out, _ = run(repo)
    assert code == 0 and "p1: valid (2 unit(s))" in out
    assert (
        "finished: openspec:done (archived: l4 yolo check refuses it as unknown_unit unless this plan already merged or "
        "integrated it)" in out
    )
    assert "p1: unknown_unit" not in out  # no problem line: the script only says what `l4 yolo check` does
    doc = json.loads(run(repo, "--json")[1])
    assert doc["ok"] is True and doc["finished"] == ["openspec:done"]


def test_a_planned_unit_with_no_change_at_all_is_still_unknown(repo):
    change(repo, "a")
    put(repo, plan("p1", [units("openspec:a", "openspec:ghost")]))
    code, out, _ = run(repo)
    assert code == 1 and "p1: unknown_unit: openspec:ghost" in out and "finished:" not in out


def test_the_help_and_the_docstring_say_an_archived_planned_unit_is_accepted(repo):
    out = run(repo, "--help")[1]
    assert "already merged or integrated" in " ".join(out.split())
    assert "already merged or integrated" in " ".join((vp.__doc__ or "").split())
    assert "refuses it as unknown_unit" in " ".join((vp.__doc__ or "").split())


def test_an_excluded_archived_change_is_known(repo):
    change(repo, "a")
    touch(repo, "openspec/changes/archive/2026-02-03-done/proposal.md")
    put(repo, plan("p1", [units("openspec:a")], exclude=[{"id": "openspec:done", "reason": "already merged"}]))
    assert run(repo)[0] == 0


# --- output, exit codes -------------------------------------------------------------------------------------


def test_json_prints_the_same_facts(repo):
    for name in ("a", "b"):
        change(repo, name)
    put(repo, plan("p1", [units("openspec:a", "openspec:b", deps={"openspec:b": ["openspec:a"]})]))
    code, out, _ = run(repo, "--json")
    doc = json.loads(out)
    assert code == 0 and doc["ok"] is True and doc["problems"] == []
    assert doc["plans"] == {"p1": {"order": ["openspec:a", "openspec:b"], "waves": [["openspec:a"], ["openspec:b"]]}}
    assert doc["units"] == ["openspec:a", "openspec:b"]


def test_json_lists_the_problems(repo):
    change(repo, "a")
    change(repo, "b")
    put(repo, plan("p1", [units("openspec:a")]))
    code, out, _ = run(repo, "--json")
    doc = json.loads(out)
    assert code == 1 and doc["ok"] is False
    assert doc["problems"] == [
        {
            "plan": None,
            "code": "uncovered",
            "subject": "openspec:b",
            "text": "add it to a plan or to a plan's exclude with a reason",
        }  # fmt: skip
    ]


def test_problem_lines_are_plan_code_subject_text(repo):
    change(repo, "a")
    put(repo, plan("p1", [units("openspec:a", "openspec:ghost")]))
    code, out, _ = run(repo)
    assert code == 1
    assert out.splitlines() == [
        "p1: unknown_unit: openspec:ghost: unit openspec:ghost was not found by a spec provider"
    ]


def test_exit_2_for_a_usage_or_read_error(repo, tmp_path):
    assert run(repo)[0] == 2  # no .l4/plans
    (repo / ".l4" / "plans").mkdir(parents=True)
    assert run(repo)[0] == 2  # no plan file
    assert run(tmp_path / "missing")[0] == 2
    assert run(repo, "--frameworks", "speckit")[0] == 2
    assert run(repo, "--nonsense")[0] == 2
    (repo / ".l4" / "plans" / "p1.json").write_bytes(b"\xff\xfe")
    assert run(repo)[0] == 2  # not readable as text


def test_exit_2_for_an_openspec_root_outside_the_repository(repo):
    put(repo, plan("p1", [units("openspec:a")]))
    assert run(repo, "--openspec-root", "../x", "--frameworks", "openspec")[0] == 2


def test_help_says_what_only_l4_yolo_check_checks(repo):
    code, out, _ = run(repo, "--help")
    assert code == 0
    for word in (
        "open questions",
        "intake",
        "finished units",
        "acceptance profiles",
        "forge.base_branch",
        "merge policy",
    ):
        assert word in out
    assert "l4 yolo check" in out


def test_the_script_runs_with_the_system_python_too():
    python3 = "/usr/bin/python3"
    if not Path(python3).exists():
        pytest.skip("no /usr/bin/python3")
    done = subprocess.run([python3, "-I", str(SCRIPT), "--help"], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0
