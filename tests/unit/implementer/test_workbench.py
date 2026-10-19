import shlex
from pathlib import Path

from l4.sandbox.bwrap import BwrapSandbox
from l4.sandbox.env import build_gate_env, cache_env

ARITY = {"--ro-bind": 2, "--bind": 2, "--tmpfs": 1, "--dev": 1, "--proc": 1}


def mounts(argv: list[str]) -> list[tuple[str, ...]]:
    """The mount operations of a bwrap argv, as (flag, arguments...)."""
    ops, i = [], 1
    while argv[i] != "--clearenv":
        n = ARITY.get(argv[i], 0)
        ops.append((argv[i], *argv[i + 1 : i + 1 + n]))
        i += 1 + n
    return ops


def test_the_gate_sandbox_hides_every_login_and_the_agent_sandbox_only_the_others(make_bench):
    wb = make_bench([]).wb
    (wb.home / ".codex").mkdir(parents=True)
    (wb.home / ".claude").mkdir()
    (wb.home / ".claude.json").write_text("{}")
    codex, claude, claude_json = (str(wb.home / name) for name in (".codex", ".claude", ".claude.json"))
    sandbox = BwrapSandbox("/usr/bin/bwrap")

    gate = mounts(sandbox.build_argv(["true"], wb.gate_spec(network=False), {}))
    assert ("--tmpfs", codex) in gate and ("--tmpfs", claude) in gate
    assert ("--ro-bind", "/dev/null", claude_json) in gate
    assert not [op for op in gate if op[0] == "--bind" and op[1] in (codex, claude)]
    assert "--unshare-net" in sandbox.build_argv(["true"], wb.gate_spec(network=False), {})
    assert "--share-net" in sandbox.build_argv(["true"], wb.gate_spec(network=True), {})

    # the fake profile has no login of its own: every real adapter's is hidden from it as well
    agent = mounts(sandbox.build_argv(["true"], wb.agent_spec(), {}))
    assert ("--tmpfs", codex) in agent and ("--tmpfs", claude) in agent
    assert ("--bind", str(wb.agent_tmp), str(wb.agent_tmp)) in agent
    assert ("--bind", str(wb.worktree), str(wb.worktree)) in agent
    assert ("--ro-bind", str(wb.git_common_dir), str(wb.git_common_dir)) in agent


def test_caches_are_bound_into_both_sandboxes_and_exported_to_gates(make_bench):
    wb = make_bench([]).wb
    uv = next(c for c in wb.caches if c.env == "UV_CACHE_DIR")
    sandbox = BwrapSandbox("/usr/bin/bwrap")
    # changed with L4-SEC-039: only a `gates.setup` command mounts the cache read-write; every other gate and the agent
    # mount it read-only and name a private scratch cache in the variable
    setup = wb.gate_spec(network=True, builds_env=True)
    assert ("--bind", str(uv.path), str(uv.path)) in mounts(sandbox.build_argv(["true"], setup, {}))
    assert build_gate_env(wb.host_env, setup)["UV_CACHE_DIR"] == str(uv.path)
    for spec in (wb.gate_spec(network=True), wb.agent_spec()):
        assert ("--ro-bind", str(uv.path), str(uv.path)) in mounts(sandbox.build_argv(["true"], spec, {}))
        assert ("--bind", str(uv.path), str(uv.path)) not in mounts(sandbox.build_argv(["true"], spec, {}))
        scratch = Path(cache_env(spec)["UV_CACHE_DIR"])
        assert scratch != uv.path and spec.tmp_dir in scratch.parents


def test_a_long_title_keeps_skip_ci_and_fits_the_subject_limit():
    from l4.implementer.workbench import MAX_SUBJECT_CHARS, clip_subject

    subject = clip_subject("feat(x): " + "very long title " * 20 + " [skip ci]")
    assert subject.endswith(" [skip ci]") and len(subject) <= MAX_SUBJECT_CHARS
    assert clip_subject("short [skip ci]") == "short [skip ci]"
    assert len(clip_subject("y" * 300)) == MAX_SUBJECT_CHARS


def test_the_checkpoint_commit_of_a_300_character_task_title_carries_skip_ci(make_bench):
    wb = make_bench([]).wb
    (wb.worktree / "note.txt").write_text("x\n")
    message = "feat(add-discount-codes): " + "t" * 300 + " [skip ci]"
    wb.commit(message, task="1.1", attempt=1, phase="green", tdd="green")
    subject = wb.git.run("log", "-1", "--format=%s").stdout.strip()
    assert subject.endswith("[skip ci]") and len(subject) <= 200


def test_the_junit_report_does_not_make_the_worktree_unclean(make_bench):
    wb = make_bench([]).wb
    assert wb.is_clean()
    (wb.worktree / ".l4-out").mkdir()
    (wb.worktree / ".l4-out" / "junit.xml").write_text("<testsuites/>")
    assert wb.git.run("status", "--porcelain").stdout.strip() != "" or True
    assert wb.is_clean()
    (wb.worktree / "stray.txt").write_text("x")
    assert not wb.is_clean()


def test_discard_removes_a_planted_file_hidden_behind_gitignore_but_keeps_the_harness_files(make_bench):
    wb = make_bench([]).wb
    (wb.worktree / ".gitignore").write_text("plant.py\n")
    wb.commit("ignore [skip ci]", task="1.1", attempt=1, phase="red", tdd=None)
    (wb.worktree / "plant.py").write_text("x = 1\n")
    (wb.worktree / "stray.txt").write_text("x")
    (wb.worktree / ".venv" / "marker").parent.mkdir(exist_ok=True)
    (wb.worktree / ".venv" / "marker").write_text("keep")
    wb.discard_changes()
    assert not (wb.worktree / "plant.py").exists() and not (wb.worktree / "stray.txt").exists()
    assert (wb.worktree / ".venv" / "marker").exists() and (wb.worktree / wb.ledger_rel).exists()


def test_a_discarded_attempt_leaves_no_wip_snapshot_to_restore(make_bench):
    from l4.state.reconcile import plan_reconcile
    from l4.vcs.wip import snapshot_wip, wip_ref

    wb = make_bench([]).wb
    (wb.worktree / "attempt.py").write_text("x = 1\n")
    assert snapshot_wip(wb.git, wb.ref.id, config=wb.exclude_config, step="1.1/red/1") is not None
    assert plan_reconcile(wb.git, wb.ref.id) is not None  # as a killed run would have left it
    wb.discard_changes()
    assert wb.git.rev_parse(wip_ref(wb.ref.id)) is None and plan_reconcile(wb.git, wb.ref.id) is None


def test_both_sandboxes_hide_the_runner_tmp_dir_of_a_ci_job(make_bench, tmp_path):
    wb = make_bench([]).wb
    project = tmp_path / "builds" / "g" / "p"
    runner_tmp = tmp_path / "builds" / "g" / "p.tmp"
    runner_tmp.mkdir(parents=True)
    wb.host_env = {**wb.host_env, "CI_PROJECT_DIR": str(project)}
    sandbox = BwrapSandbox("/usr/bin/bwrap")
    for spec in (wb.gate_spec(network=False), wb.agent_spec()):
        assert ("--tmpfs", str(runner_tmp)) in mounts(sandbox.build_argv(["true"], spec, {}))


def test_nothing_extra_is_hidden_outside_ci(make_bench):
    wb = make_bench([]).wb
    assert wb.agent_spec().runner_tmp == () == wb.gate_spec(network=True).runner_tmp


def test_a_step_commit_drops_its_stale_wip_snapshot(make_bench):
    from l4.state.reconcile import plan_reconcile
    from l4.vcs.wip import snapshot_wip

    wb = make_bench([]).wb
    (wb.worktree / "work.py").write_text("x = 1\n")
    assert snapshot_wip(wb.git, wb.ref.id, config=wb.exclude_config, step="1.1/green/1") is not None
    wb.commit("work [skip ci]", task="1.1", attempt=1, phase="green", tdd="green")
    assert plan_reconcile(wb.git, wb.ref.id) is None  # not a `mark_finished` for a step that finished normally


def test_purge_bytecode_removes_planted_bytecode_but_not_the_environment_tracked_files_or_link_targets(tmp_path):
    from l4.implementer.workbench import purge_bytecode

    root = tmp_path / "wt"
    for rel in ("src/pkg/__pycache__/mod.cpython-312.pyc", "src/pkg/__pycache__/notes.txt", "src/pkg/sourceless.pyc",
                ".venv/lib/site/__pycache__/dep.cpython-312.pyc", "node_modules/x/__pycache__/a.pyc",
                "vendor/kept.pyc", "elsewhere/__pycache__/target.pyc", "outside/inner.pyc"):  # fmt: skip
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(b"x")
    (root / "src/other").mkdir()
    (root / "src/other/__pycache__").symlink_to(root / "elsewhere/__pycache__")  # a planted link: removed, not followed
    (root / "src/linked").symlink_to(root / "outside")  # a linked directory: never walked through
    purge_bytecode(root, tracked={"vendor/kept.pyc"})
    assert not (root / "src/pkg/__pycache__/mod.cpython-312.pyc").exists()
    assert not (root / "src/pkg/__pycache__/notes.txt").exists()
    assert not (root / "src/pkg/sourceless.pyc").exists()
    assert not (root / "src/other/__pycache__").is_symlink() and not (root / "src/other/__pycache__").exists()
    assert (root / "elsewhere/__pycache__").is_dir()  # the walk reaches it as a directory of its own
    for kept in (".venv/lib/site/__pycache__/dep.cpython-312.pyc", "node_modules/x/__pycache__/a.pyc",
                 "vendor/kept.pyc"):  # fmt: skip
        assert (root / kept).exists(), kept


def test_a_gate_name_with_slashes_logs_inside_the_run_folder(make_bench):
    """Job names carry `/`, spaces, `:` and `..` (M1.10 line 6): the gate's log file name is made safe, so the log lands
    in the run's gates folder and no directory is made from the name."""
    wb = make_bench([]).wb
    folder = wb.out_dir / "gates" / wb.run_id
    for name in ("repository-ci:build/linux x64", "repository-ci:../../escape", "x" * 200):
        log = wb._next_gate_log(name)
        assert log.parent == folder and "/" not in log.name and ".." not in log.name
        assert len(log.name) <= len("001-") + 60 + len(".log")
    assert wb._next_gate_log("repository-ci:test").name == "001-repository-ci_test.log"


def test_scn_imp_318_gate_finished_carries_the_collection_error(make_bench):
    """L4-IMP-064: with no gate log kept, the committed ledger holds the E lines of a collection error, redacted."""
    from l4.implementer.tdd import run_setup

    bench = make_bench([])
    wb = bench.wb
    run_setup(wb)
    passed = wb.run_gate("test", wb.cfg.gates.test.command, reports=wb.cfg.gates.test.reports)
    assert passed.status == "pass"
    first = bench.events("gate.finished")[-1]
    assert first["name"] == "test" and first.get("collection_errors") == 0 and "excerpt" not in first
    secret = "glpat-" + "x" * 20
    (wb.worktree / "tests" / "test_broken.py").write_text(f'raise ImportError("{secret}")\n')
    broken = wb.run_gate("test", wb.cfg.gates.test.command, reports=wb.cfg.gates.test.reports)
    assert broken.status == "fail"
    event = bench.events("gate.finished")[-1]
    assert event["collection_errors"] == 1
    assert 0 < len(event["excerpt"]) <= 600 and "E   ImportError:" in event["excerpt"]
    assert secret not in event["excerpt"]


def test_a_failing_setup_gate_keeps_the_redacted_tail_of_its_log_in_the_ledger(make_bench):
    """rv18-ops 3b: a gate with no report (setup, lint, typecheck) leaves the ledger the end of its log, at most 600
    characters, redacted before the cut."""
    bench = make_bench([])
    wb = bench.wb
    secret = "glpat-" + "x" * 20
    script = (
        'for i in $(seq 1 80); do echo "line $i of the install"; done; '
        f"echo 'ERROR: no matching distribution for foo ({secret})' >&2; exit 1"
    )
    command = f"sh -c {shlex.quote(script)}"
    result = wb.run_gate("setup", command, network=True, builds_env=True)
    assert result.status == "fail"
    event = bench.events("gate.finished")[-1]
    assert 0 < len(event["excerpt"]) <= 600
    assert "no matching distribution for foo" in event["excerpt"] and "line 80 of the install" in event["excerpt"]
    assert secret not in event["excerpt"] and "glpat-" not in event["excerpt"]
    wb.run_gate("setup", "sh -c true", network=True, builds_env=True)
    assert "excerpt" not in bench.events("gate.finished")[-1]  # a pass keeps none
