"""The replay guard never follows a link and never acts outside the work tree (SPEC L4-IMP-065): the real Workbench, a
patch applied exactly as the replay applies it (`git apply` without --index), the guard armed, then what a gate (or a
process that outlived it) does is simulated on the file system. Ported from an independent link-attack review."""

import os
import shutil
import stat
import threading
from pathlib import Path

import pytest

from l4.implementer import held_patch
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
    wb.replay_links = held_patch.links_added(wb, data)  # the real trust computation
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

    def racing_read(self, path, expect=None):
        value = real_read(self, path, expect)
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


# --- round 2 of the link-attack review: trust, the root, memory, unreadable folders ---------------------------------

import errno  # noqa: E402
import tracemalloc  # noqa: E402

from l4.implementer import confined  # noqa: E402
from l4.implementer.confined import LinkedParent, open_parent, put_entry, read_entry, remove_entry  # noqa: E402


def fds() -> int:
    return len(os.listdir("/dev/fd"))


# --- R1: a link at the work-tree root (the root path is re-opened by name at every call) ----------


def test_r1_the_work_tree_root_swapped_for_a_link_to_another_checkout(make_bench, tmp_path):
    """Needs write access to the folder that holds the work tree (no sandbox, or a writable mount above it)."""
    bench = make_bench([])
    root = replayed(bench, PATCH, base=BASE)
    arm_replay_guard(bench.wb)
    other = bench.tdd.repo  # the main checkout of the same repository, with someone's uncommitted work
    (other / "precious.txt").write_text("uncommitted work in another checkout\n")
    listing = sorted(p.name for p in other.iterdir())
    real = root.with_name(root.name + ".real")
    os.rename(root, real)
    os.symlink(other, root)
    try:
        try:
            restore_replay(bench.wb, "test run")
        except Exception as exc:  # noqa: BLE001
            f"raised {exc!r}"[:200]
        after = sorted(p.name for p in other.iterdir())
        precious = (other / "precious.txt").exists()
    finally:
        os.unlink(root)
        os.rename(real, root)
    assert precious and after == listing


# --- R2: hard links -------------------------------------------------------------------------------


def test_r2_a_hard_link_to_an_outside_file_is_never_written_or_chmodded(make_bench, tmp_path):
    outside = make_outside(tmp_path)
    os.chmod(outside / "victim.txt", 0o640)
    bench = make_bench([])
    root = replayed(bench, {**PATCH, "tests/run.sh": "#!/bin/sh\n"}, base=BASE)
    os.chmod(root / "tests" / "run.sh", 0o755)
    arm_replay_guard(bench.wb)
    for rel in ("tests/fixtures/data.txt", "tests/run.sh", "tests/fixtures/old.txt"):
        (root / rel).unlink()
        os.link(outside / "victim.txt", root / rel)  # three names of the outside inode
    before = state(outside)
    st0 = os.stat(outside / "victim.txt")
    reason = restore_replay(bench.wb, "test run")
    st1 = os.stat(outside / "victim.txt")
    assert reason is None and state(outside) == before and st1.st_mode == st0.st_mode and st1.st_nlink == 1
    assert stat.S_IMODE(os.stat(root / "tests" / "run.sh").st_mode) == 0o755


# --- R3: odd names in the patch summary -----------------------------------------------------------


@pytest.mark.parametrize("name", ['tests/q"uote', "tests/tab\there", "tests/back\\slash", "tests/ünï"])
def test_r3_a_patch_link_with_an_odd_name_is_trusted_or_the_step_fails_closed(make_bench, tmp_path, name):
    bench = make_bench([])
    root = replayed(bench, {**PATCH, name: (LINK, "test_new.py")})
    arm_replay_guard(bench.wb)
    reason = restore_replay(bench.wb, "test run")
    assert (root / name).is_symlink() or reason is not None  # never followed; at worst fails closed
    assert reason is None, "the patch's own link is not trusted: a legitimate step fails"


def test_r3b_summary_paths_are_only_compared_never_opened(make_bench, tmp_path):
    """`..`, absolute or crafted names in `wb.replay_links` are inert: trust needs the path git lists as a link."""
    outside = make_outside(tmp_path)
    before = state(outside)
    bench = make_bench([])
    root = replayed(bench, PATCH, base=BASE)
    bench.wb.replay_links = frozenset({"../outside", str(outside), "tests/../tests/fixtures", "tests/fixtures/"})
    arm_replay_guard(bench.wb)
    os.symlink(outside, root / "tests" / "fixtures2")
    (root / "tests" / "fixtures").rename(root / "tests" / "moved")
    os.symlink(outside, root / "tests" / "fixtures")
    reason = restore_replay(bench.wb, "test run")
    assert state(outside) == before and reason is not None


# --- R4: a folder that becomes a file (or link, FIFO) mid-walk ------------------------------------


class _OsProxy:
    """`os` for confined.py, with one swap of `tests/fixtures` right before the walk opens it."""

    def __init__(self, root: Path, swap):
        self._root, self._swap, self.fired = root, swap, False

    def __getattr__(self, name):
        return getattr(os, name)

    def open(self, path, flags, *args, dir_fd=None, **kw):
        if not self.fired and path == "fixtures" and dir_fd is not None:
            self.fired = True
            self._swap(self._root / "tests" / "fixtures")
        return os.open(path, flags, *args, dir_fd=dir_fd, **kw)


def _to_file(p: Path) -> None:
    os.rename(p, p.with_name("fixtures.moved"))
    p.write_text("a file now\n")


def _to_link(target):
    def swap(p: Path) -> None:
        os.rename(p, p.with_name("fixtures.moved"))
        os.symlink(target, p)

    return swap


def _to_fifo(p: Path) -> None:
    os.rename(p, p.with_name("fixtures.moved"))
    os.mkfifo(p)


@pytest.mark.parametrize("swap", ["file", "link", "fifo"])
@pytest.mark.parametrize("op", ["read", "put", "remove"])
def test_r4_folder_swapped_mid_walk(tmp_path, monkeypatch, swap, op):
    outside = make_outside(tmp_path)
    root = tmp_path / "wt"
    (root / "tests" / "fixtures").mkdir(parents=True)
    (root / "tests" / "fixtures" / "data.txt").write_text("patched\n")
    swaps = {"file": _to_file, "link": _to_link(outside), "fifo": _to_fifo}
    proxy = _OsProxy(root, swaps[swap])
    monkeypatch.setattr(confined, "os", proxy)
    before, n0 = state(outside), fds()
    rel = "tests/fixtures/data.txt"
    try:
        if op == "read":
            read_entry(root, rel)
        elif op == "put":
            put_entry(root, rel, ("file", b"restored\n", 0o644))
        else:
            remove_entry(root, rel)
    except Exception:  # noqa: BLE001
        pass
    monkeypatch.undo()
    stat.filemode(os.lstat(root / "tests" / "fixtures").st_mode)
    assert proxy.fired and state(outside) == before and fds() == n0


# --- R5: ELOOP / ENOTDIR / EMLINK: every kind of link on the way is a LinkedParent ----------------


@pytest.mark.parametrize("kind", ["to-dir", "to-file", "dangling", "loop", "to-root"])
def test_r5_every_link_on_the_way_is_refused(tmp_path, kind):
    outside = make_outside(tmp_path)
    root = tmp_path / "wt"
    (root / "tests").mkdir(parents=True)
    link = root / "tests" / "fixtures"
    target = {"to-dir": outside, "to-file": outside / "victim.txt", "dangling": outside / "missing",
              "loop": link, "to-root": root}[kind]  # fmt: skip
    os.symlink(target, link)
    try:
        os.open("fixtures", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=os.open(root / "tests", os.O_RDONLY))
    except OSError as exc:
        errno.errorcode[exc.errno]
    results = []
    for create in (False, True):
        try:
            open_parent(root, "tests/fixtures/data.txt", create=create)
            results.append("opened!")
        except LinkedParent as exc:
            results.append(f"LinkedParent({exc.rel})")
        except OSError as exc:
            results.append(f"{exc.__class__.__name__}")
    assert results == ["LinkedParent(tests/fixtures)"] * 2


# --- R6: fd leaks over every error path -----------------------------------------------------------


def test_r6_no_fd_leak_on_any_path(make_bench, tmp_path):
    outside = make_outside(tmp_path)
    before = state(outside)
    root = tmp_path / "wt"
    (root / "a" / "b").mkdir(parents=True)
    (root / "a" / "b" / "f").write_text("x")
    (root / "a" / "file").write_text("x")
    os.symlink(outside, root / "a" / "link")
    (root / "locked").mkdir()
    (root / "locked" / "f").write_text("x")
    os.mkfifo(root / "a" / "fifo")
    calls = [
        lambda: read_entry(root, "a/link/data.txt"),  # LinkedParent
        lambda: read_entry(root, "a/missing/x"),  # FileNotFoundError
        lambda: read_entry(root, "a/file/x"),  # ENOTDIR, not create
        lambda: read_entry(root, "a/fifo"),  # a FIFO is not opened
        lambda: read_entry(root, "locked/f"),  # EACCES on the folder
        lambda: put_entry(root, "a/link/x", ("file", b"y", 0o644)),
        lambda: put_entry(root, "locked/g", ("file", b"y", 0o644)),
        lambda: put_entry(root, "a/b/f", ("file", b"y", 0o644)),
        lambda: remove_entry(root, "a/link/x"),
        lambda: remove_entry(root, "locked/f"),
        lambda: confined.check_parents(root, "a/link/x"),
    ]
    os.chmod(root / "locked", 0)
    try:
        n0 = fds()
        outcomes = set()
        for _ in range(50):
            for call in calls:
                try:
                    call()
                    outcomes.add("ok")
                except Exception as exc:  # noqa: BLE001
                    outcomes.add(exc.__class__.__name__)
        n1 = fds()
    finally:
        os.chmod(root / "locked", 0o755)
    assert n1 == n0 and state(outside) == before


# --- R7: rmtree(dir_fd) never follows links inside the removed folder -----------------------------


def test_r7_rmtree_of_a_folder_full_of_links(tmp_path):
    outside = make_outside(tmp_path)
    before = state(outside)
    root = tmp_path / "wt"
    d = root / "tests" / "data.txt"  # a folder where the snapshot has a file
    (d / "deep" / "deeper").mkdir(parents=True)
    os.symlink(outside, d / "to_outside")
    os.symlink(outside / "victim.txt", d / "deep" / "to_victim")
    os.symlink(outside / "sub.txt", d / "deep" / "deeper" / "to_sub")
    os.mkfifo(d / "deep" / "fifo")
    put_entry(root, "tests/data.txt", ("file", b"restored\n", 0o644))
    assert (root / "tests" / "data.txt").read_bytes() == b"restored\n"
    assert state(outside) == before


# --- R8: availability: a huge sparse file a gate writes is read whole -----------------------------


def test_r8_a_gate_written_sparse_file_is_read_whole(make_bench, tmp_path):
    bench = make_bench([])
    root = replayed(bench, PATCH, base=BASE)
    arm_replay_guard(bench.wb)
    size = 256 * 1024 * 1024
    with open(root / "tests" / "fixtures" / "big.bin", "wb") as handle:  # a new path: removed by the restore
        handle.truncate(size)  # sparse: costs the gate nothing
    tracemalloc.start()
    restore_replay(bench.wb, "test run")
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert peak < size // 4, "the guard reads a gate-written file whole to decide it is not absent"


# --- R9: an OSError other than a link in the pre-scan or the snapshot -----------------------------


def test_r9_a_folder_made_unreadable_by_a_gate(make_bench, tmp_path):
    bench = make_bench([])
    root = replayed(bench, PATCH, base=BASE)
    arm_replay_guard(bench.wb)
    os.chmod(root / "tests" / "fixtures", 0)
    try:
        try:
            out = restore_replay(bench.wb, "test run")
        except Exception as exc:  # noqa: BLE001
            out = f"raised {exc.__class__.__name__}: {str(exc)[:120]}"
    finally:
        os.chmod(root / "tests" / "fixtures", 0o755)
    assert not str(out).startswith("raised"), "an exception escapes restore(): the run crashes, no attempt is counted"


def test_r9b_a_patched_file_made_unreadable_before_the_snapshot(make_bench, tmp_path):
    bench = make_bench([])
    root = replayed(bench, PATCH, base=BASE)
    os.chmod(root / "tests" / "fixtures" / "data.txt", 0)  # setup code, before the guard is armed
    try:
        try:
            arm_replay_guard(bench.wb)
            out = restore_replay(bench.wb, "test run")
        except Exception as exc:  # noqa: BLE001
            out = f"raised {exc.__class__.__name__}: {str(exc)[:120]}"
    finally:
        os.chmod(root / "tests" / "fixtures" / "data.txt", 0o644)
    assert not str(out).startswith("raised"), "an exception escapes the guard: the run crashes"


def test_r9c_end_to_end_what_a_crash_leaves(make_bench, monkeypatch, raw, tmp_path):
    """Through run_task: a gate chmods a folder 000 while the saved step is replayed."""
    from l4.implementer.loop import run_task

    from .test_earlier_red import NEW, TASK, new_step
    from .test_held_accept import held_new
    from .test_held_answers import answer

    evil = (
        "import os, pathlib\n"
        "_held = pathlib.Path('openspec/changes/add-discount-codes/.l4/held/1.1-pre_satisfied.patch')\n"
        "if _held.exists():\n"
        "    os.chmod('tests/fixtures', 0)\n"
    )
    bench = held_new(make_bench, monkeypatch, [new_step(("tests/fixtures/data.txt", "patched\n"),
                                                        ("tests/test_new.py", evil + NEW)), new_step()])  # fmt: skip
    answer(bench, raw, "accept: fine")
    try:
        try:
            outcome = run_task(bench.wb, TASK)
            out = (outcome.status, outcome.reason)
        except Exception as exc:  # noqa: BLE001
            out = f"raised {exc.__class__.__name__}: {str(exc)[:160]}"
    finally:
        fixtures = bench.wb.worktree / "tests" / "fixtures"
        if fixtures.exists():
            os.chmod(fixtures, 0o755)
    assert not str(out).startswith("raised")


# --- R3c: a newline in a patch link's name splits the `git apply --summary` line ------------------


def test_r3c_a_newline_in_a_link_name_makes_another_path_trusted(make_bench, tmp_path):
    outside = make_outside(tmp_path)
    before = state(outside)
    bench = make_bench([])
    root = replayed(bench, {**PATCH, "tests/notes\n create mode 120000 tests/planted": "a regular file\n"})
    trusted = bench.wb.replay_links
    os.symlink(outside, root / "tests" / "planted")  # setup code, before the guard is armed
    arm_replay_guard(bench.wb)
    reasons = [restore_replay(bench.wb, w) for w in ("test run", "before the red commit")]
    if reasons == [None, None]:
        bench.wb.commit("replay", task="1.1", attempt=1, phase="red", tdd="red")
    assert state(outside) == before
    assert "tests/planted" not in trusted, "a line of the summary names a link the patch does not create"
