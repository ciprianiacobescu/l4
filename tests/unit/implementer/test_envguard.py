"""L4-SEC-036 and L4-SEC-037 on a bench with no sandbox (`sandbox.mode: none`): what the harness does with an
environment an agent step or a gate changed, created or left behind by an earlier workbench."""

import base64
import dataclasses
import hashlib
import sys
from pathlib import Path

from l4.agents.fake import Step
from l4.implementer import envguard
from l4.implementer.tdd import agent_step, run_setup

from ._env_helpers import MKNODE, MKREALVENV, SITE, TASK
from .conftest import result


def venv_bench(make_bench, tmp_path: Path, script: list[Step], **gates):
    mk = tmp_path / "mkrealvenv.py"
    mk.write_text(MKREALVENV)
    return make_bench(script, setup=[f"{sys.executable} {mk}"], **gates)


def violations(bench) -> list[dict]:
    return [e for e in bench.events("guard.violation") if e.get("rule") == "environment"]


def record_of(files: dict[str, str]) -> str:
    rows = []
    for rel, text in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(text.encode()).digest()).rstrip(b"=").decode()
        rows.append(f"{rel},sha256={digest},{len(text)}")
    return "\n".join([*rows, "newdep-1.0.dist-info/RECORD,,"]) + "\n"


def test_a_declared_dependency_is_rebuilt_without_a_violation(make_bench, tmp_path):  # SCN-SEC-90
    code = {"newdep/__init__.py": "VALUE = 1\n"}
    step = Step(
        writes={
            "uv.lock": "version = 1\n",
            f"{SITE}/newdep/__init__.py": code["newdep/__init__.py"],
            f"{SITE}/newdep-1.0.dist-info/RECORD": record_of(code),
        },
        structured=result("green"),
    )
    bench = venv_bench(make_bench, tmp_path, [step])
    wb = bench.wb
    run_setup(wb)
    agent_step(wb, "green", TASK, 1, None)
    events = bench.events("env.rebuilt")
    assert len(events) == 1 and events[0]["declared"] is True and ".venv" in events[0]["dirs"]
    assert not (wb.worktree / ".venv").exists() and wb.setup_at is None
    assert violations(bench) == [] and bench.events("guard.notice") == []


def test_a_gate_plant_under_mode_none_is_removed(make_bench, tmp_path):  # SCN-SEC-91
    bench = venv_bench(make_bench, tmp_path, [])
    wb = bench.wb
    run_setup(wb)
    assert wb.setup_at is not None and (wb.worktree / ".venv").is_dir()
    plant = f"open({f'{SITE}/sitecustomize.py'!r}, 'w').write('import os\\n')"
    wb.run_gate("test", f'{sys.executable} -c "{plant}"')
    assert not (wb.worktree / ".venv").exists()
    hits = [v for v in violations(bench) if v["phase"] == "gate"]
    assert [v["path"] for v in hits] == [f"{SITE}/sitecustomize.py"]
    assert wb.setup_at is None  # no later gate runs on the planted environment before setup builds it again
    run_setup(wb)
    assert (wb.worktree / ".venv" / "bin" / "python").exists()  # the next setup builds it without the plant
    assert not (wb.worktree / SITE / "sitecustomize.py").exists()


def test_a_changed_node_package_is_removed(make_bench, tmp_path):  # SCN-SEC-92
    mk = tmp_path / "mknode.py"
    mk.write_text(MKNODE)
    edit = Step(
        writes={"node_modules/vitest/dist/index.js": "export const real = false;\n"}, structured=result("green")
    )
    bench = make_bench([edit], setup=[f"{sys.executable} {mk}"])
    wb = bench.wb
    run_setup(wb)
    agent_step(wb, "green", TASK, 1, None)
    assert not (wb.worktree / "node_modules").exists()
    assert [v["path"] for v in violations(bench)] == ["node_modules/vitest/dist/index.js"]


def test_an_environment_a_gate_created_is_removed(make_bench):  # SCN-SEC-93
    bench = make_bench([], setup=[])
    wb = bench.wb
    run_setup(wb)
    wb.run_gate("test", f"{sys.executable} -c \"import os; os.makedirs('.venv/lib')\"")
    assert not (wb.worktree / ".venv").exists()
    assert [e["reason"] for e in bench.events("env.rebuilt")] == ["created"]


def test_the_verifiers_first_setup_rebuilds(make_bench, tmp_path):  # SCN-SEC-94
    bench = venv_bench(make_bench, tmp_path, [])
    wb = bench.wb
    run_setup(wb)
    (wb.worktree / SITE / "zz_added.txt").write_text("added after the implementer's manifest")
    second = dataclasses.replace(wb, env_manifests={}, setup_at=None)  # a workbench built later, as the verifier's
    run_setup(second)
    assert [e["reason"] for e in bench.events("env.rebuilt")] == ["unverified"]
    assert not (wb.worktree / SITE / "zz_added.txt").exists()  # rebuilt by setup, without the file
    assert (wb.worktree / ".venv" / "bin" / "python").exists()


def test_the_first_setup_in_a_fresh_worktree_removes_nothing(make_bench, tmp_path):  # SCN-SEC-95
    bench = venv_bench(make_bench, tmp_path, [])
    wb = bench.wb
    assert not (wb.worktree / ".venv").exists()
    run_setup(wb)
    assert bench.events("env.rebuilt") == []
    assert wb.worktree in wb.env_manifests and any(p.startswith(".venv/") for p in wb.env_manifests[wb.worktree])


def test_a_tracked_node_modules_is_never_removed(make_bench, tmp_path):
    bench = venv_bench(make_bench, tmp_path, [])
    wb = bench.wb
    vendored = wb.worktree / "vendor" / "node_modules" / "x.js"
    vendored.parent.mkdir(parents=True)
    vendored.write_text("module.exports = 1\n")
    wb.git.run("add", "-f", "--", "vendor/node_modules/x.js")
    wb.git.run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "vendor a package")
    from l4.sandbox.envdirs import env_dirs

    assert vendored.parent not in env_dirs(wb.worktree, ["vendor/node_modules/x.js"])
    run_setup(wb)
    vendored.write_text("module.exports = 2\n")  # a production change: the production guards judge it, not this one
    assert wb.check_env(wb.worktree, phase="green", changed=["vendor/node_modules/x.js"]) is False
    assert vendored.read_text() == "module.exports = 2\n" and violations(bench) == []


def test_a_dependency_upgrade_without_a_lock_is_a_notice_not_a_violation(make_bench, tmp_path):  # SCN-PRV-106
    mk = tmp_path / "mknode.py"
    mk.write_text(MKNODE)
    package = '{"name": "x", "version": "1.0.0", "dependencies": {"vitest": "^2.0.0"}}\n'
    step = Step(
        writes={"package.json": package, "node_modules/vitest/dist/index.js": "export const real = 2;\n"},
        structured=result("green"),
    )
    bench = make_bench([step], setup=[f"{sys.executable} {mk}"])
    wb = bench.wb
    (wb.worktree / "package.json").write_text('{"name": "x", "version": "1.0.0", "dependencies": {}}\n')
    wb.git.run("add", "package.json")
    wb.git.run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "package.json")
    run_setup(wb)
    agent_step(wb, "green", TASK, 1, None)
    assert not (wb.worktree / "node_modules").exists()  # the environment is rebuilt in both cases
    notices = bench.events("guard.notice")
    assert [n["path"] for n in notices] == ["node_modules/vitest/dist/index.js"] and notices[0]["rule"] == "environment"
    assert violations(bench) == []
    assert bench.events("env.rebuilt")[0]["declared"] is False


def test_a_startup_hook_is_a_violation_even_when_a_manifest_changed(make_bench, tmp_path):  # SCN-PRV-107
    package = '[project]\nname = "pytdd"\nversion = "0.1.0"\nrequires-python = ">=3.11"\ndependencies = ["rich"]\n'
    step = Step(writes={"pyproject.toml": package, f"{SITE}/zz.pth": "import os\n"}, structured=result("green"))
    bench = venv_bench(make_bench, tmp_path, [step])
    wb = bench.wb
    run_setup(wb)
    agent_step(wb, "green", TASK, 1, None)
    assert [v["path"] for v in violations(bench)] == [f"{SITE}/zz.pth"]


def test_the_pure_classification(tmp_path: Path):
    tree = tmp_path
    (tree / "node_modules" / "pkg").mkdir(parents=True)
    (tree / "node_modules" / "pkg" / "a.js").write_text("1")
    before = envguard.take_manifest(tree)
    (tree / "node_modules" / "pkg" / "a.js").write_text("22")
    (tree / "node_modules" / "pkg" / "b.js").write_text("3")
    diff = envguard.diff_manifest(before, envguard.take_manifest(tree))
    assert diff.added == ("node_modules/pkg/b.js",) and "node_modules/pkg/a.js" in diff.changed
    assert envguard.planted(tree, diff, []) == ["node_modules/pkg/a.js", "node_modules/pkg/b.js"]
    assert envguard.planted(tree, diff, ["package-lock.json"]) == []  # a declared install
    heads = {"package.json": b'{"dependencies": {}}'}
    (tree / "package.json").write_text('{"dependencies": {"x": "1"}}')
    sure = envguard.classify(tree, diff, ["package.json"], read_head=heads.get)
    assert sure.violations == () and len(sure.notices) == 2
    (tree / "package.json").write_text('{"dependencies": {}, "scripts": {"a": "b"}}')  # not a dependency section
    assert len(envguard.classify(tree, diff, ["package.json"], read_head=heads.get).violations) == 2


def test_a_gate_that_changes_nothing_never_rebuilds_the_environment(make_bench, tmp_path):
    """The tool-cache reset before every gate rewrites `node_modules/.cache`, `.vite`, `.vite-temp` and `.vitest-cache`,
    which moves the directory's own timestamps: that alone is not a change (a planted child is an added entry, a
    replaced directory a new inode)."""
    mk = tmp_path / "mknode.py"
    mk.write_text(MKNODE)
    bench = make_bench([], setup=[f"{sys.executable} {mk}"])
    wb = bench.wb
    run_setup(wb)
    for _ in range(3):
        wb.run_gate("test", f'{sys.executable} -c "pass"')
    assert bench.events("env.rebuilt") == [] and wb.setup_at is not None
    assert (wb.worktree / "node_modules" / "vitest" / "dist" / "index.js").is_file()
    (wb.worktree / "node_modules" / "vitest" / "planted.js").write_text("x")  # a child that is new is still a change
    wb.check_env(wb.worktree, phase="gate")
    assert not (wb.worktree / "node_modules").exists()


def test_a_file_written_into_vite_temp_by_a_gate_is_no_change(make_bench, tmp_path):  # SCN-SEC-87
    """Vite bundles a TypeScript config into `node_modules/.vite-temp`: like `.cache` and `.vite`, the manifest leaves
    it out, so a gate that writes there neither plants nor rebuilds anything."""
    mk = tmp_path / "mknode.py"
    mk.write_text(MKNODE)
    bench = make_bench([], setup=[f"{sys.executable} {mk}"])
    wb = bench.wb
    run_setup(wb)
    write = (
        "import os; d = 'node_modules/.vite-temp'; os.makedirs(d, exist_ok=True); open(d + '/x.mjs', 'w').write('1')"
    )
    wb.run_gate("test", f'{sys.executable} -c "{write}"')
    assert (wb.worktree / "node_modules" / ".vite-temp" / "x.mjs").is_file()
    assert violations(bench) == [] and bench.events("env.rebuilt") == [] and wb.setup_at is not None
    assert (wb.worktree / "node_modules" / "vitest" / "dist" / "index.js").is_file()


def test_a_file_written_into_vitest_cache_by_a_gate_is_no_change(make_bench, tmp_path):  # SCN-SEC-87
    """Vitest 5 keeps transformed modules in `node_modules/.vitest-cache`: like the other tool caches, the manifest
    leaves it out, so a gate that writes there neither plants nor rebuilds anything."""
    mk = tmp_path / "mknode.py"
    mk.write_text(MKNODE)
    bench = make_bench([], setup=[f"{sys.executable} {mk}"])
    wb = bench.wb
    run_setup(wb)
    write = "import os; d = 'node_modules/.vitest-cache'; os.makedirs(d, exist_ok=True); open(d + '/k', 'w').write('1')"
    wb.run_gate("test", f'{sys.executable} -c "{write}"')
    assert (wb.worktree / "node_modules" / ".vitest-cache" / "k").is_file()
    assert violations(bench) == [] and bench.events("env.rebuilt") == [] and wb.setup_at is not None
    assert (wb.worktree / "node_modules" / "vitest" / "dist" / "index.js").is_file()


def test_a_file_written_into_vitest_cache_by_an_agent_step_is_no_change(make_bench, tmp_path):  # SCN-SEC-87
    """An agent sandbox keeps `node_modules` writable, so Vitest run by an agent fills `.vitest-cache`: the environment
    check after the step finds no change, reports no violation and rebuilds nothing."""
    mk = tmp_path / "mknode.py"
    mk.write_text(MKNODE)
    bench = make_bench([], setup=[f"{sys.executable} {mk}"])
    wb = bench.wb
    run_setup(wb)
    cache = wb.worktree / "node_modules" / ".vitest-cache"
    cache.mkdir(exist_ok=True)
    (cache / "0a1b2c").write_text("transformed module")
    wb.check_env(wb.worktree, phase="red")
    assert violations(bench) == [] and bench.events("env.rebuilt") == []
    assert (wb.worktree / "node_modules").is_dir() and (cache / "0a1b2c").is_file() and wb.setup_at is not None
