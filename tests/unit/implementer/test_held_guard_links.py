"""The replay guard never follows a link and never acts outside the work tree (SPEC L4-IMP-065): the real Workbench, a
patch applied exactly as the replay applies it (`git apply` without --index), the guard armed, then what a gate (or a
process that outlived it) does is simulated on the file system. Ported from an independent link-attack review."""

import os
import shutil
import stat
import threading
from pathlib import Path

import pytest

from l4.implementer.held_patch import APPLY_FLAGS, GIT_PLAIN, ReplayGuard, arm_replay_guard, restore_replay

from .conftest import Bench
from .test_earlier_red import NEW

LINK = object()


def state(root: Path) -> list:
    """Everything under `root`, links not followed: (rel, kind, content-or-target, inode)."""
    out = []
    if not os.path.lexists(root):
        return ["<absent>"]
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in dirnames + filenames:
            p = Path(dirpath, name)
            st = os.lstat(p)
            rel = p.relative_to(root).as_posix()
            if stat.S_ISLNK(st.st_mode):
                out.append((rel, "link", os.readlink(p), None))
            elif stat.S_ISDIR(st.st_mode):
                out.append((rel, "dir", None, None))
            else:
                out.append((rel, "file", p.read_bytes(), st.st_ino))
    return sorted(out, key=lambda t: t[0])


def make_outside(tmp_path: Path) -> Path:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "data.txt").write_text("outside\n")  # same name as the patched file
    (outside / "victim.txt").write_text("victim\n")
    (outside / "sub.txt").mkdir()  # a folder where the patch has a file
    (outside / "sub.txt" / "keep.txt").write_text("keep\n")
    return outside


def write(root: Path, rel: str, content) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, tuple):
        os.symlink(content[1], target)
    else:
        target.write_bytes(content if isinstance(content, bytes) else content.encode())


def replayed(bench: Bench, patch: dict, *, base: dict | None = None, delete: tuple = ()) -> Path:
    """Commit `base`, build the patch of `patch`/`delete` the way capture does, discard, apply it as the replay does
    (worktree only), and mark the step as a replay. Returns the worktree."""
    wb = bench.wb
    root = wb.worktree
    if base:
        for rel, content in base.items():
            write(root, rel, content)
        wb.git.run("add", "-A", "-f", "--", *base)
        wb.commit("test: base", task="0.9", attempt=1, phase="red", tdd="red")
    for rel, content in patch.items():
        write(root, rel, content)
    for rel in delete:
        (root / rel).unlink()
    wb.git.run("add", "-A", "-f", "--", *patch, *delete)
    data = wb.git.run_bytes("diff", "--cached", "--binary", "HEAD")
    wb.git.run("reset", "-q")
    wb.discard_changes()
    for rel in patch:
        assert not os.path.lexists(root / rel)
    wb.git.run_input_bytes(*GIT_PLAIN, *APPLY_FLAGS, "-", data=data)  # exactly what replay_step does
    wb.replay_question = "Q-001"
    summary = wb.git.run_input_bytes(*GIT_PLAIN, "apply", "--summary", "-", data=data).stdout
    wb.replay_links = frozenset(  # the links the saved patch itself creates: the only ones the guard trusts
        line.split(" create mode 120000 ", 1)[1] for line in summary.splitlines() if " create mode 120000 " in line
    )
    return root


def relink(path: Path, target) -> None:
    """What test code does: the folder goes, a link takes its place."""
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    os.symlink(target, path)


def unsafe_events(bench: Bench) -> list[dict]:
    return bench.events("held.replay_unsafe")


PATCH = {"tests/test_new.py": NEW, "tests/fixtures/data.txt": "patched\n", "tests/fixtures/sub.txt": "patched sub\n"}
BASE = {"tests/fixtures/old.txt": "tracked\n"}


# --- (a) the parent is a link before the snapshot is taken (setup ran patch code) ---------------------------------


@pytest.mark.parametrize("with_tracked", [True, False], ids=["tracked-below", "no-tracked-below"])
def test_a_link_planted_before_the_snapshot(make_bench, tmp_path, with_tracked):
    outside = make_outside(tmp_path)
    before = state(outside)
    bench = make_bench([])
    root = replayed(bench, PATCH, base=BASE if with_tracked else None)
    relink(root / "tests" / "fixtures", outside)  # between setup and the first gate
    arm_replay_guard(bench.wb)
    _ = bench.wb.replay_guard.guarded
    # the gate does nothing; every later restore runs
    reasons = [restore_replay(bench.wb, w) for w in ("test run", "before the red commit")]
    assert state(outside) == before  # never read/written/removed outside
    if reasons == [None, None]:  # the guard accepted the planted link as part of the patch: does it get committed?
        bench.wb.commit("replay", task="1.1", attempt=1, phase="red", tdd="red")
        listed = bench.wb.git.run("ls-tree", "-r", "HEAD", "tests/").stdout
        assert state(outside) == before
        assert "120000" not in listed, "the planted link to the outside folder was committed, the patch's files dropped"


def test_a2_a_new_link_planted_before_the_snapshot_at_a_fresh_name(make_bench, tmp_path):
    outside = make_outside(tmp_path)
    before = state(outside)
    bench = make_bench([])
    root = replayed(bench, PATCH)
    os.symlink(outside, root / "tests" / "planted")  # setup code plants a link the patch never had
    arm_replay_guard(bench.wb)
    reasons = [restore_replay(bench.wb, w) for w in ("test run", "before the red commit")]
    assert state(outside) == before
    if reasons == [None, None]:
        bench.wb.commit("replay", task="1.1", attempt=1, phase="red", tdd="red")
        listed = bench.wb.git.run("ls-tree", "-r", "HEAD", "tests/").stdout
        assert "tests/planted" not in listed, "a link planted before the snapshot is committed with the replay"


# --- (b) replaced between two gates --------------------------------------------------------------------------------


def test_b_link_planted_between_two_gates(make_bench, tmp_path):
    outside = make_outside(tmp_path)
    before = state(outside)
    bench = make_bench([])
    root = replayed(bench, PATCH, base=BASE)
    arm_replay_guard(bench.wb)
    # gate 1: rewrites a patched file and adds one; nothing linked
    (root / "tests" / "fixtures" / "data.txt").write_text("changed by gate 1\n")
    (root / "tests" / "fixtures" / "extra.txt").write_text("new\n")
    first = restore_replay(bench.wb, "test run")
    assert first is None and (root / "tests" / "fixtures" / "data.txt").read_text() == "patched\n"
    # gate 2: the folder becomes a link to the outside folder, and a patched file there is "changed"
    relink(root / "tests" / "fixtures", outside)
    second = restore_replay(bench.wb, "base run")
    assert state(outside) == before
    assert second is not None and "symbolic link" in second
    assert not (root / "tests" / "fixtures").is_symlink()


# --- (c) a link chain -----------------------------------------------------------------------------


@pytest.mark.parametrize("hop", ["outside-hops", "inside-hop"])
def test_c_link_chain(make_bench, tmp_path, hop):
    outside = make_outside(tmp_path)
    hops = tmp_path / "hops"
    hops.mkdir()
    bench = make_bench([])
    root = replayed(bench, PATCH, base=BASE)
    arm_replay_guard(bench.wb)
    if hop == "outside-hops":
        os.symlink(outside, hops / "two")
        os.symlink(hops / "two", hops / "one")
        first = hops / "one"
    else:
        os.symlink(outside, root / "tests" / "hop")  # a link inside the work tree, then another to it
        first = Path("hop")
    before, before_hops = state(outside), state(hops)
    relink(root / "tests" / "fixtures", first)
    reason = restore_replay(bench.wb, "test run")
    assert state(outside) == before and state(hops) == before_hops
    assert reason is not None and "symbolic link" in reason


# --- (d) a parent link that points INSIDE the work tree, outside the guarded set ------------------------------------


@pytest.mark.parametrize("into", ["unit .l4/held", "src/pytdd", "git common dir"])
def test_d_parent_link_into_the_work_tree_outside_the_guarded_set(make_bench, tmp_path, into):
    bench = make_bench([])
    wb = bench.wb
    root = replayed(bench, PATCH, base=BASE)
    held = wb.ref.path / ".l4" / "held"
    held.mkdir(parents=True, exist_ok=True)
    (held / "1.1-pre_satisfied.patch").write_text("THE SAVED PATCH\n")
    (held / "data.txt").write_text("harness data\n")
    (held / "sub.txt").mkdir(exist_ok=True)
    (held / "sub.txt" / "keep.txt").write_text("keep\n")
    targets = {
        "unit .l4/held": held,
        "src/pytdd": root / "src" / "pytdd",
        "git common dir": Path(wb.git.run("rev-parse", "--git-common-dir").stdout.strip()).resolve(),
    }
    target = targets[into]
    if into != "unit .l4/held":
        (target / "data.txt").write_text("not ours\n")
    arm_replay_guard(wb)
    (root / "tests" / "fixtures" / "data.txt").write_text("changed by the gate\n")  # gives the guard a reason to write
    before = state(target)
    relink(root / "tests" / "fixtures", os.path.relpath(target, root / "tests"))
    reason = restore_replay(wb, "test run")
    assert state(target) == before
    assert reason is not None and "symbolic link" in reason


# --- (e) a dangling link as a parent --------------------------------------------------------------


def test_e_dangling_parent_link(make_bench, tmp_path):
    outside = make_outside(tmp_path)
    bench = make_bench([])
    root = replayed(bench, PATCH, base=BASE)
    arm_replay_guard(bench.wb)
    before = state(outside)
    relink(root / "tests" / "fixtures", outside / "missing" / "deep")  # restore would mkdir(parents=True) it
    reason = restore_replay(bench.wb, "test run")
    assert state(outside) == before and not (outside / "missing").exists()
    assert reason is not None and "symbolic link" in reason


# --- (f) a leaf the patch did NOT add replaced by a link (or a hard link / FIFO) ------------------


@pytest.mark.parametrize("leaf", ["tracked-unchanged", "deleted-by-patch", "new-untracked", "patched-file"])
def test_f_leaf_replaced_by_a_symlink(make_bench, tmp_path, leaf):
    outside = make_outside(tmp_path)
    before = state(outside)
    bench = make_bench([])
    base = {**BASE, "tests/fixtures/gone.txt": "deleted by the patch\n"}
    root = replayed(bench, PATCH, base=base, delete=("tests/fixtures/gone.txt",))
    arm_replay_guard(bench.wb)
    rel = {
        "tracked-unchanged": "tests/fixtures/old.txt",
        "deleted-by-patch": "tests/fixtures/gone.txt",
        "new-untracked": "tests/fixtures/brand_new.txt",
        "patched-file": "tests/fixtures/data.txt",
    }[leaf]
    relink(root / rel, outside / "victim.txt")
    reason = restore_replay(bench.wb, "test run")
    assert state(outside) == before
    assert reason is None
    expect = {"tests/fixtures/old.txt": "tracked\n", "tests/fixtures/data.txt": "patched\n"}.get(rel)
    assert not (root / rel).is_symlink()
    assert ((root / rel).read_text() if expect else os.path.lexists(root / rel)) == (expect or False)


@pytest.mark.parametrize("leaf", ["tracked-unchanged", "patched-file"])
def test_f_leaf_replaced_by_a_hard_link_to_an_outside_file(make_bench, tmp_path, leaf):
    outside = make_outside(tmp_path)
    bench = make_bench([])
    root = replayed(bench, PATCH, base=BASE)
    arm_replay_guard(bench.wb)
    rel = {"tracked-unchanged": "tests/fixtures/old.txt", "patched-file": "tests/fixtures/data.txt"}[leaf]
    (root / rel).unlink()
    os.link(outside / "victim.txt", root / rel)  # same file system: a second name of the outside file
    before = state(outside)
    reason = restore_replay(bench.wb, "test run")
    assert state(outside) == before  # the guard unlinks the name, never writes into the inode
    assert reason is None


def test_f_fifo_at_a_patched_path_hangs_the_guard(make_bench, tmp_path):
    """Not an escape: a FIFO where a patched file was makes `write_bytes` block until a reader opens it."""
    bench = make_bench([])
    root = replayed(bench, PATCH, base=BASE)
    arm_replay_guard(bench.wb)
    fifo = root / "tests" / "fixtures" / "data.txt"
    fifo.unlink()
    os.mkfifo(fifo)
    out: list = []
    worker = threading.Thread(target=lambda: out.append(restore_replay(bench.wb, "test run")), daemon=True)
    worker.start()
    worker.join(timeout=5)
    hung = worker.is_alive()
    if hung:  # release it so the test ends
        with open(fifo, "rb") as reader:
            _ = reader.read()
        worker.join(timeout=5)
    assert not hung, "restore() blocks forever on a FIFO planted at a guarded path (no reader under bwrap)"


# --- (g) a symlink the patch added, retargeted by a gate ------------------------------------------


@pytest.mark.parametrize("change", ["retarget-to-outside-file", "retarget-to-outside-dir", "replace-by-dir"])
def test_g_patch_symlink_retargeted(make_bench, tmp_path, change):
    outside = make_outside(tmp_path)
    before = state(outside)
    bench = make_bench([])
    patch = {**PATCH, "tests/alias.py": (LINK, "test_new.py"), "tests/linkdir": (LINK, "fixtures")}
    root = replayed(bench, patch)
    assert (root / "tests" / "alias.py").is_symlink() and (root / "tests" / "linkdir").is_symlink()
    arm_replay_guard(bench.wb)
    assert bench.wb.replay_guard.guarded["tests/alias.py"] == ("link", "test_new.py")
    if change == "retarget-to-outside-file":
        relink(root / "tests" / "alias.py", outside / "victim.txt")
        relink(root / "tests" / "linkdir", outside / "data.txt")
    elif change == "retarget-to-outside-dir":
        relink(root / "tests" / "alias.py", outside / "sub.txt")
        relink(root / "tests" / "linkdir", outside)
    else:
        (root / "tests" / "alias.py").unlink()
        (root / "tests" / "alias.py").mkdir()
        (root / "tests" / "alias.py" / "x").write_text("x")
    reason = restore_replay(bench.wb, "test run")
    assert state(outside) == before
    assert reason is None
    assert os.readlink(root / "tests" / "alias.py") == "test_new.py"
    assert os.readlink(root / "tests" / "linkdir") == "fixtures"


# --- (h) TOCTOU: the parent becomes a link between the guard's check and its write ----------------


def test_h_simulated_window_between_check_and_write(make_bench, tmp_path, monkeypatch):
    """The parent is swapped for a link right after the guard's last check of the path (inside `_read`, which is the
    last call before unlink/mkdir/write_bytes). Simulates a process that outlived its gate winning the race."""
    outside = make_outside(tmp_path)
    before = state(outside)
    bench = make_bench([])
    root = replayed(bench, PATCH, base=BASE)
    arm_replay_guard(bench.wb)
    (root / "tests" / "fixtures" / "data.txt").write_text("changed by the gate\n")
    real_read = ReplayGuard._read
    fired = []

    def racing_read(self, path):
        value = real_read(self, path)
        if path == "tests/fixtures/data.txt" and not fired:
            fired.append(path)
            relink(root / "tests" / "fixtures", outside)  # the attacker wins the race here
        return value

    monkeypatch.setattr(ReplayGuard, "_read", racing_read)
    _ = restore_replay(bench.wb, "test run")
    after = state(outside)
    assert after == before


def test_h_real_thread_racing_the_guard(make_bench, tmp_path):
    """A concurrent flipper (dir <-> link to outside) while restore() runs, many rounds: does it ever land?"""
    outside = make_outside(tmp_path)
    before = state(outside)
    bench = make_bench([])
    root = replayed(bench, PATCH, base=BASE)
    arm_replay_guard(bench.wb)
    fixtures = root / "tests" / "fixtures"
    stash = tmp_path / "stash"
    stop = threading.Event()

    def flipper():
        while not stop.is_set():
            try:  # rename keeps the folder; the link then stands where the folder was
                os.rename(fixtures, stash)
                os.symlink(outside, fixtures)
                os.unlink(fixtures)
                os.rename(stash, fixtures)
            except OSError:
                pass

    hits, results = 0, []
    for _ in range(60):
        if fixtures.is_symlink():
            fixtures.unlink()
        if not fixtures.exists() and stash.exists():
            os.rename(stash, fixtures)
        fixtures.mkdir(parents=True, exist_ok=True)
        (fixtures / "data.txt").write_text("changed by the gate\n")
        stop.clear()
        t = threading.Thread(target=flipper, daemon=True)
        t.start()
        try:
            results.append(restore_replay(bench.wb, "test run"))
        except Exception as exc:  # noqa: BLE001
            results.append(f"raised {exc.__class__.__name__}: {exc}")
        stop.set()
        t.join()
        if state(outside) != before:
            hits += 1
            break
    assert hits == 0


# --- (g2) the guard re-creates a guarded link, then acts on a listed child THROUGH it -------------


@pytest.mark.parametrize("origin", ["patch-adds-the-link", "link-planted-before-the-snapshot"])
def test_g2_link_recreated_then_child_removed_through_it(make_bench, tmp_path, origin):
    """The gate replaces a guarded link by a real folder holding `victim.txt`. The restore loop (sorted: parent first)
    rmtree's the folder and re-creates the link, then handles the listed child `tests/linkdir/victim.txt`: a new
    path, so `restore_to_base(existed=False)` unlinks it - through the link it just re-created. The pre-scan ran
    while `tests/linkdir` was a plain folder, so nothing flags it."""
    outside = make_outside(tmp_path)
    before = state(outside)
    bench = make_bench([])
    if origin == "patch-adds-the-link":
        root = replayed(bench, {**PATCH, "tests/linkdir": (LINK, str(outside))})
    else:  # no link in the patch: setup code ran from the patch and planted it before the guard was armed
        root = replayed(bench, PATCH)
        os.symlink(outside, root / "tests" / "linkdir")
    arm_replay_guard(bench.wb)
    assert bench.wb.replay_guard.guarded["tests/linkdir"] == ("link", str(outside))
    # the gate (inside the sandbox it may only write the work tree): the link becomes a folder with a same-named file
    (root / "tests" / "linkdir").unlink()
    (root / "tests" / "linkdir").mkdir()
    (root / "tests" / "linkdir" / "victim.txt").write_text("decoy\n")
    _ = restore_replay(bench.wb, "test run")
    after = state(outside)
    assert after == before


# --- (h2) the real window: the whole restore loop, git subprocesses included ----------------------


def test_h2_window_is_the_whole_loop_not_one_call(make_bench, tmp_path, monkeypatch):
    """The parent is swapped while the guard runs `git` for an EARLIER path (restore_to_base of a new file that sorts
    first). The later patched files under the swapped folder are not even changed by the gate: `_read` returns None
    for a linked parent (meaning "unsafe"), the loop takes None as "absent", and rmtree's/writes through the link."""
    outside = make_outside(tmp_path)
    before = state(outside)
    bench = make_bench([])
    root = replayed(bench, PATCH, base=BASE)
    arm_replay_guard(bench.wb)
    (root / "tests" / "a_first.txt").write_text("a new file that sorts before tests/fixtures\n")
    git = bench.wb.git
    real = type(git).run
    fired = []

    def slow_git(*args, **kw):  # the first `git rm`/`git checkout` the restore loop runs for an earlier path
        if not fired and args and args[0] in ("rm", "checkout"):
            fired.append(args)
            relink(root / "tests" / "fixtures", outside)  # a surviving process wins during this git call
        return real(git, *args, **kw)

    monkeypatch.setattr(git, "run", slow_git)
    _ = restore_replay(bench.wb, "test run")
    after = state(outside)
    assert after == before


# --- end to end (run_task, the real replay and gates): g2 -----------------------------------------


def test_e2e_g2_a_gate_makes_the_guard_delete_a_file_outside(make_bench, monkeypatch, raw, tmp_path):
    """Modelled on test_u1_minor: a saved step that adds the link `tests/linkdir -> <outside>` and a test whose module
    code, only while the saved patch is replayed, turns the link into a folder holding `victim.txt`. The test code
    itself never touches the outside folder (a sandboxed gate could not)."""
    import hashlib

    from l4.implementer.loop import run_task

    from .test_earlier_red import TASK
    from .test_held_accept import commit_all, held_new, patch_of
    from .test_held_answers import answer

    outside = make_outside(tmp_path)
    before = state(outside)
    evil = (
        "import pathlib\n"
        "_held = pathlib.Path('openspec/changes/add-discount-codes/.l4/held/1.1-pre_satisfied.patch')\n"
        "_l = pathlib.Path('tests/linkdir')\n"
        "if _held.exists() and _l.is_symlink():  # inside the work tree only\n"
        "    _l.unlink()\n"
        "    _l.mkdir()\n"
        "    (_l / 'victim.txt').write_text('decoy\\n')\n"
    )
    bench = held_new(make_bench, monkeypatch)
    wb = bench.wb
    (wb.worktree / "tests" / "test_new.py").write_text(evil + NEW)
    os.symlink(str(outside), wb.worktree / "tests" / "linkdir")
    wb.git.run("add", "-A", "-f", "--", "tests/test_new.py", "tests/linkdir")
    data = wb.git.run_bytes("diff", "--cached", "--binary", "HEAD")
    wb.git.run("reset", "-q")
    wb.discard_changes()
    patch_of(bench).write_bytes(data)
    keep = ("id", "task", "kind", "title", "check", "criteria", "tests", "result_sha256", "saved")
    last = {k: v for k, v in bench.events("question.raised")[-1].items() if k in keep}
    bench.writer.append("question.raised", **{**last, "patch_sha256": hashlib.sha256(data).hexdigest()})
    commit_all(bench, raw, "forged hold with a link to a folder outside")
    answer(bench, raw, "accept: fine")
    run_task(bench.wb, TASK)
    after = state(outside)
    assert after == before


# --- modes, and only the harness's own .l4 locations are exempt -----------------------------------------------------


def test_a_gates_chmod_of_a_patched_file_is_put_back(make_bench):
    bench = make_bench([])
    root = replayed(bench, PATCH, base=BASE)
    arm_replay_guard(bench.wb)
    target = root / "tests" / "fixtures" / "data.txt"
    mode = stat.S_IMODE(target.stat().st_mode)
    target.chmod(0o755)
    assert restore_replay(bench.wb, "test run") is None
    assert stat.S_IMODE(target.stat().st_mode) == mode and target.read_text() == "patched\n"


def test_a_path_with_an_l4_component_elsewhere_is_guarded(make_bench):
    bench = make_bench([])
    root = replayed(bench, PATCH, base=BASE)
    arm_replay_guard(bench.wb)
    (root / "tests" / ".l4").mkdir()
    (root / "tests" / ".l4" / "x.txt").write_text("written by a gate\n")
    (root / ".l4").mkdir(exist_ok=True)
    (root / ".l4" / "stray.txt").write_text("written by a gate\n")
    assert restore_replay(bench.wb, "test run") is None
    assert not (root / "tests" / ".l4" / "x.txt").exists() and not (root / ".l4" / "stray.txt").exists()
    unit_l4 = bench.wb.ref.path / ".l4" / "something.json"  # the unit folder's own .l4 is the harness's
    unit_l4.parent.mkdir(parents=True, exist_ok=True)
    unit_l4.write_text("{}")
    assert restore_replay(bench.wb, "test run") is None and unit_l4.exists()
