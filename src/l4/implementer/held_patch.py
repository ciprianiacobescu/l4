"""A held step is kept, and an `accept` replays it (SPEC L4-IMP-065, design D1..D4).

A step held with a harness question has its changes discarded; an `accept` that only covered the test ids the question
named was lost with them, because the next agent wrote the tests again under other names. So the step is saved first:

- `capture` (before the discard): the step's changes as `git diff --binary`, the agent's result as JSON, and the
  redacted, cut source of the tests the question names;
- `write_held` (with the questions commit): `<unit>/.l4/held/<task>-<check>.patch` and `.json`, whose digests
  `question.raised` records;
- `find_replay` (the next time the step runs): the newest harness question of the task and check decides. `accept`
  replays the patch (`replay_step`, no agent), a missing, changed or non-applying patch is a new question
  (`Refused`), and `retry` drops the files;
- `accepted_tests_block` (an agent step of a task with an accepted override): the tests to keep unchanged.
"""

import ast
import contextlib
import hashlib
import json
import logging
import os
import re
import stat
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from l4.fsutil import UnsafeFile, atomic_write_bytes, read_regular_file, reject_symlinks
from l4.implementer.confined import (
    Entry,
    LinkedParent,
    check_parents,
    describe_entry,
    exists_entry,
    put_blob,
    put_entry,
    remove_entry,
    remove_link,
    repair_dir_modes,
)
from l4.implementer.held import (
    MAX_SHOWN_TESTS,
    MAX_SOURCE_LINES,
    MAX_SUBJECTS,
    Check,
    HeldCheck,
    accepted_overrides,
    cap_line,
)
from l4.implementer.prompt import data_block
from l4.implementer.result import ImplementerResult, ResultInvalid, parse_result
from l4.implementer.workbench import Workbench
from l4.security.protected import changed_paths, revert_protected
from l4.specs.base import Task
from l4.specs.questions import QUESTIONS_FILENAME, QuestionsFile, harness_answer
from l4.state.ledger import LedgerEvent, read_ledger
from l4.vcs.git import Git, GitError
from l4.vcs.secretscan import step_secret_reason, worktree_secrets

if TYPE_CHECKING:  # a type only: tdd.py imports this module
    from l4.implementer.tdd import StepOutcome

log = logging.getLogger("l4.held")

HELD_DIR = ".l4/held"  # relative to the unit folder
MAX_PATCH_BYTES = 64 * 1024 * 1024
MAX_META_BYTES = 8 * 1024 * 1024
MAX_DIFF_FILES = 100  # changed paths whose diff is read and shown; the others are listed
_NOT_SHOWN = "[diff not shown here: it is in `{where}` on the unit branch and is replayed too]"
MAX_EVENT_SOURCE_CHARS = 20_000  # what `held.replayed` carries of the sources
CHECKS: dict[str, tuple[Check, ...]] = {
    "red": ("pre_satisfied", "vacuity"),
    "green": ("at_red",),
    "single": ("tests",),
}
ACCEPTED_TESTS_RULE = (
    "A person accepted these tests for this task: a check could not decide on them, and the person took them on the "
    "evidence of the real run. Keep them unchanged: the same name and the same body. The accept covers only them; a "
    "test of another name, or the same name with another body, is not covered and is checked again."
)
USED_UP_NOTICE = (
    "A person accepted an earlier step of this task, which a check could not decide on, and L4 replayed that step. The "
    "replay is used up: that accept was for that earlier step only and covers nothing now. If a check cannot decide on "
    "your step, the task is held again and a new step needs a new answer from a person."
)
# the operator's git configuration must not change what a patch looks like or how it applies
GIT_PLAIN = (
    "-c", "diff.noprefix=false", "-c", "diff.mnemonicPrefix=false", "-c", "color.ui=never", "-c", "diff.external=",
    "-c", "core.quotePath=false", "-c", "core.autocrlf=false", "-c", "core.safecrlf=false",
)  # fmt: skip
DIFF_FLAGS = (
    "--no-ext-diff", "--no-textconv", "--no-color", "--no-renames", "--unified=3", "--src-prefix=a/", "--dst-prefix=b/",
)  # fmt: skip
APPLY_FLAGS = ("apply", "--binary", "--whitespace=nowarn", "-p1")


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", value)


def held_rel(wb: Workbench, task: str, check: str, suffix: str) -> str:
    return f"{wb.unit_rel}/{HELD_DIR}/{_safe(task)}-{check}.{suffix}"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- capture (before the discard) ------------------------------------------------------------------------------


def _cut(text: str) -> str:
    lines = [cap_line(line) for line in text.splitlines()]
    if len(lines) <= MAX_SOURCE_LINES:
        return "\n".join(lines)
    return "\n".join([*lines[:MAX_SOURCE_LINES], f"[cut: {len(lines) - MAX_SOURCE_LINES} more lines]"])


def _test_path(wb: Workbench, test_id: str) -> Path | None:
    """The file of a test id as it is in the work tree: the part before the first `::` as it is, or a dotted pytest
    JUnit id's longest dotted prefix that is a module there."""
    head = test_id.split("::", 1)[0]
    candidates = [head]
    if "/" not in head and "." in head:
        parts = head.split(".")
        while parts:
            candidates.append("/".join(parts) + ".py")
            parts.pop()
    root = wb.worktree.resolve()
    for rel in candidates:
        path = wb.worktree / rel
        if path.is_file() and not path.is_symlink() and root in path.resolve().parents:
            return path
    return None


def _python_source(text: str, name: str) -> str | None:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
            return "\n".join(text.splitlines()[start - 1 : node.end_lineno])
    return None


def _raw_source(wb: Workbench, test_id: str) -> str | None:
    """The function of a test id exactly as the work tree has it (for a file that is not Python, the file from the
    first line that mentions the name to its end), or None when the file or the name is not there."""
    path = _test_path(wb, test_id)
    if path is None:
        return None
    name = re.sub(r"\[.*\]$", "", test_id.split("::")[-1])
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    found = _python_source(text, name) if path.suffix == ".py" else None
    if found is None:
        lines = text.splitlines()
        at = next((i for i, line in enumerate(lines) if name in line), None)
        found = "\n".join(lines[at:]) if at is not None else None
    return found


def source_digest(wb: Workbench, test_id: str) -> str:
    """What an accept is bound to: the sha256 of the test's exact source (`none` when it cannot be found)."""
    raw = _raw_source(wb, test_id)
    return "none" if raw is None else hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()


def test_source(wb: Workbench, test_id: str) -> str:
    """The test as a question shows it: redacted whole and then cut to `MAX_SOURCE_LINES` (a cut inside a secret would
    leave a prefix that the redactor cannot see)."""
    raw = _raw_source(wb, test_id)
    if raw is None:
        return "(the source of this test was not found)"
    return _cut(wb.redactor.redact_text(raw))


def test_sources(wb: Workbench, ids: Sequence[str]) -> tuple[tuple[str, str], ...]:
    return tuple((i, test_source(wb, i)) for i in ids[:MAX_SHOWN_TESTS])


_STATUS = {"A": "added", "M": "modified", "D": "deleted", "T": "type changed"}


def _changes(wb: Workbench) -> list[tuple[str, str]]:
    """(what, path) of every path the staged step changes, from `diff --name-status`."""
    raw = wb.git.run_bytes(
        *GIT_PLAIN, "diff", "--cached", "--name-status", "-z", "--no-renames", "HEAD", "--", ".",
        f":(exclude){wb.ledger_rel}",
    )  # fmt: skip
    fields = [os.fsdecode(f) for f in raw.split(b"\0") if f]
    return [
        (_STATUS.get(status[:1], "changed"), path) for status, path in zip(fields[0::2], fields[1::2], strict=False)
    ]


def _file_diff(wb: Workbench, path: str, patch_rel: str) -> str:
    """The diff of one changed path, redacted whole and then cut; a cut says that the cut lines are replayed too."""
    out = wb.git.run_bytes(
        *GIT_PLAIN, "diff", "--cached", *DIFF_FLAGS, "HEAD", "--", f":(literal){path}"
    ).decode("utf-8", "replace")  # fmt: skip
    lines = [cap_line(line) for line in wb.redactor.redact_text(out).splitlines()]
    if len(lines) <= MAX_SOURCE_LINES:
        return "\n".join(lines)
    note = (
        f"[cut: {len(lines) - MAX_SOURCE_LINES} more lines; the cut lines are replayed too: the whole change is in "
        f"`{patch_rel}` on the unit branch]"
    )
    return "\n".join([*lines[:MAX_SOURCE_LINES], note])


def capture(wb: Workbench, held: HeldCheck, result: ImplementerResult | None) -> HeldCheck:
    """`held` with the step's changes, its result, the list of paths it changes, the diff of each file that is no
    named test and the source and digest of each named test. Called while the changes are still in the work tree:
    `discard_changes` follows. The index is left as it was. Whatever its size, the step is saved whole."""
    wb.git.run("add", "-A", config=(*wb.exclude_config, ("core.autocrlf", "false"), ("core.safecrlf", "false")))
    patch_rel = held_rel(wb, held.task, held.check, "patch")
    try:
        patch = wb.git.run_bytes(
            *GIT_PLAIN, "diff", "--cached", "--binary", *DIFF_FLAGS, "HEAD", "--", ".", f":(exclude){wb.ledger_rel}"
        )  # fmt: skip
        changes = _changes(wb)
        diffs = tuple(
            (path, _file_diff(wb, path, patch_rel) if n < MAX_DIFF_FILES else _NOT_SHOWN.format(where=patch_rel))
            for n, (_, path) in enumerate(changes)
        )
    finally:
        wb.git.run("reset", "-q")
    return replace(
        held,
        patch=patch,
        result=json.dumps(result.model_dump(mode="json")) if result is not None else "",
        sources=test_sources(wb, held.tests),
        digests=tuple((t, source_digest(wb, t)) for t in held.tests[:MAX_SUBJECTS]),
        changes=tuple(cap_line(f"{what} {wb.redactor.redact_text(path)}") for what, path in changes),
        diffs=diffs,
        patch_path=patch_rel,
        carries=(wb.replay_question,) if wb.replay_question else (),
    )


# --- write (with the questions commit) -------------------------------------------------------------------------


def write_held(wb: Workbench, held: HeldCheck) -> tuple[list[str], dict[str, Any]]:
    """Write the patch and the result beside it; returns (the repository paths to commit, the digests for the
    `question.raised` event). Nothing when the hold has no patch to keep."""
    if held.patch is None or not held.result:
        return [], {}
    reject_symlinks(wb.ref.path, ".l4", "held")
    folder = wb.ref.path / HELD_DIR
    folder.mkdir(parents=True, exist_ok=True)
    profile = wb.selected.profile
    agent = f"{wb.selected.profile_name}/{profile.model}" if profile.model else wb.selected.profile_name
    meta = json.dumps(
        {"schema": "l4/held@1", "task": held.task, "check": held.check, "agent": agent,
         "result": _small(json.loads(held.result))},
        sort_keys=True,
    ).encode()  # fmt: skip
    rels = [held_rel(wb, held.task, held.check, "patch"), held_rel(wb, held.task, held.check, "json")]
    wb.held_removals[:] = [r for r in wb.held_removals if r not in rels]  # a new hold keeps its own files
    for rel, data in zip(rels, (held.patch, meta), strict=True):
        target = wb.worktree / rel
        if target.is_symlink():
            target.unlink()
        atomic_write_bytes(target, data)
    for rel, limit in zip(rels, (MAX_PATCH_BYTES, MAX_META_BYTES), strict=True):
        if isinstance(_read(wb.worktree / rel, limit), str):  # what cannot be read back cannot be replayed
            for leftover in rels:
                (wb.worktree / leftover).unlink(missing_ok=True)
            return [], {}
    return rels, {
        "saved": True, "patch_sha256": _digest(held.patch), "result_sha256": _digest(meta),
        "source_sha256": dict(held.digests),
        "carries": list(held.carries),
    }  # fmt: skip


# --- find and replay -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Replay:
    question: str
    check: Check
    patch: bytes
    patch_sha256: str
    result: ImplementerResult
    tests: tuple[str, ...]
    patch_rel: str
    meta_rel: str
    agent: str | None = None  # the profile that wrote the step: the replay's commit names it


@dataclass(frozen=True)
class Refused:
    """The accepted step cannot be replayed: the hold the next question raises, with the reason."""

    held: HeldCheck


def _events(wb: Workbench) -> list[LedgerEvent]:
    """The unit's events; a fix unit's go to its parent's ledger, so only the ones this workbench's context wrote."""
    fix_unit = wb.event_context.get("fix_unit")
    events = read_ledger(wb.worktree / Path(wb.ledger_rel).parents[2]).events
    return [e for e in events if e.data.get("fix_unit") == fix_unit]


def _tracked(wb: Workbench, rel: str) -> bool:
    return wb.git.run("ls-files", "--error-unmatch", "--", rel, check=False).returncode == 0


def drop_held(wb: Workbench, task: str, check: str, *, attempt: int, why: str) -> None:
    """Delete the saved step of `check` in a commit of its own (a `retry`, a restart or a reopened task)."""
    rels = [held_rel(wb, task, check, "patch"), held_rel(wb, task, check, "json")]
    tracked = [rel for rel in rels if _tracked(wb, rel)]
    for rel in rels:
        (wb.worktree / rel).unlink(missing_ok=True)
    if not tracked:
        return
    wb.commit(
        f"docs({wb.ref.name}): held patch dropped ({why}) [skip ci]", task=task, attempt=attempt, phase="held",
        tdd=None, paths=tracked,
    )  # fmt: skip
    wb.push()


def _queue_removal(wb: Workbench, task: str, check: str) -> None:
    """The saved step is spent (replayed, superseded): the next commit of the unit branch carries its deletion."""
    for suffix in ("patch", "json"):
        rel = held_rel(wb, task, check, suffix)
        present = (wb.worktree / rel).is_symlink() or (wb.worktree / rel).exists()
        if present and rel not in wb.held_removals:
            wb.held_removals.append(rel)


def _newest_raised(events: Sequence[LedgerEvent], task: str, checks: Sequence[str]) -> tuple[int, LedgerEvent] | None:
    found = None
    for i, event in enumerate(events):
        if (
            event.type == "question.raised"
            and event.data.get("kind") == "harness"
            and event.data.get("task") == task
            and event.data.get("check") in checks
        ):
            found = (i, event)
    return found


def _refuse(wb: Workbench, task: Task, role: str, event: LedgerEvent, why: str) -> Refused:
    check: Check = event.data["check"]
    tests = tuple(str(t) for t in event.data.get("tests") or [])
    criteria = tuple(str(c) for c in event.data.get("criteria") or [])
    reason = f"the step saved with {event.data.get('id')} cannot be replayed, so the accept gives no override: {why}"
    phase = "red" if role == "red" else "green"
    return Refused(HeldCheck(task.key, phase, check, criteria, tests, reason))  # type: ignore[arg-type]


def _read(path: Path, limit: int) -> bytes | str:
    """The file's bytes, or why they cannot be read."""
    try:
        return read_regular_file(path, limit=limit)
    except FileNotFoundError:
        return "the file is missing"
    except UnsafeFile as exc:
        return f"the file is unusable ({exc})"
    except OSError as exc:
        return f"the file cannot be read ({exc.__class__.__name__})"


def find_replay(wb: Workbench, role: str, task: Task, *, attempt: int) -> Replay | Refused | None:
    """What the step of `role` does instead of an agent, if anything. None: run the agent."""
    checks = CHECKS[role]
    events = _events(wb)
    newest = _newest_raised(events, task.key, checks)
    if newest is None:
        return None
    index, raised = newest
    check: Check = raised.data["check"]
    qid = str(raised.data.get("id"))
    for other in checks:  # the saved step of another check of this task, replayed in an earlier run: spent
        earlier = _newest_raised(events, task.key, [other])
        if other != check and earlier is not None:
            spent = str(earlier[1].data.get("id"))
            if any(e.type == "held.replayed" and e.data.get("question") == spent for e in events):
                _queue_removal(wb, task.key, other)
    file = QuestionsFile.load(wb.ref.path / QUESTIONS_FILENAME)
    question = next((q for q in file.questions if q.id == qid), None) if file is not None else None
    answer = harness_answer(question) if question is not None else None
    if answer is None:  # no answer yet (a blocked task does not get here), or not one the harness understands
        return None
    if answer == "retry":
        drop_held(wb, task.key, check, attempt=attempt, why="retry")
        return None
    if raised.data.get("saved") is False:  # only `retry` was offered: an accept covers nothing, and the run says so
        if not any(e.type == "held.accept_ignored" and e.data.get("question") == qid for e in events):
            log.warning(
                "%s: %s was answered `accept`, but its step was not saved: no override; the step runs again",
                task.key,
                qid,
            )
            wb.emit("held.accept_ignored", question=qid, task=task.key, check=check)
        _queue_removal(wb, task.key, check)
        return None
    valid = any(o.question == qid for o in accepted_overrides(wb, task.key, check, for_replay=True).values())
    sha = raised.data.get("patch_sha256")
    stale = any(
        e.type == "unit.restarted" or (e.type == "tasks.reopened" and task.key in (e.data.get("tasks") or []))
        for e in events[index + 1 :]
    )
    replayed = any(e.type == "held.replayed" and e.data.get("question") == qid for e in events)
    if not valid or not sha or replayed:
        _queue_removal(wb, task.key, check)  # a leftover of an earlier hold of this check
        return None
    if stale:
        drop_held(wb, task.key, check, attempt=attempt, why="the unit restarted or the task was reopened")
        return None
    patch_rel, meta_rel = held_rel(wb, task.key, check, "patch"), held_rel(wb, task.key, check, "json")
    try:
        reject_symlinks(wb.ref.path, ".l4", "held")
    except UnsafeFile as exc:
        return _refuse(wb, task, role, raised, f"{exc}")
    patch = _read(wb.worktree / patch_rel, MAX_PATCH_BYTES)
    if isinstance(patch, str):
        return _refuse(wb, task, role, raised, f"the patch `{patch_rel}` is missing or unusable: {patch}")
    if _digest(patch) != sha:
        return _refuse(
            wb, task, role, raised,
            f"the digest of the patch `{patch_rel}` differs from patch_sha256 recorded when it was saved ({sha[:12]}…)",
        )  # fmt: skip
    meta = _read(wb.worktree / meta_rel, MAX_META_BYTES)
    if isinstance(meta, str):
        return _refuse(wb, task, role, raised, f"the result `{meta_rel}` is missing or unusable: {meta}")
    recorded = raised.data.get("result_sha256")
    if not recorded:
        return _refuse(
            wb, task, role, raised, f"no digest of `{meta_rel}` was recorded with the question (result_sha256)"
        )
    if _digest(meta) != recorded:
        return _refuse(wb, task, role, raised, f"the digest of `{meta_rel}` differs from the one recorded")
    try:
        saved = json.loads(meta)
        result = parse_result(saved["result"])
    except (ValueError, KeyError, TypeError, ResultInvalid) as exc:
        return _refuse(wb, task, role, raised, f"the saved result is not valid ({exc.__class__.__name__})")
    result = result.model_copy(
        update={"files_changed": sorted(_patch_paths(wb, patch)), "tests_added": list(raised.data.get("tests") or [])}
    )  # what grows with the step is not in the sidecar: it is the patch's, recomputed
    agent = saved.get("agent") if isinstance(saved.get("agent"), str) else None
    if agent is not None and not re.fullmatch(r"[A-Za-z0-9._/@+-]{1,120}", agent):
        agent = None
    odd = [p for p in _patch_paths(wb, patch) if "\n" in p or "\r" in p]
    if odd:
        return _refuse(wb, task, role, raised, "a path of the saved patch contains a line break")
    if patch:
        check_apply = wb.git.run_input_bytes(*GIT_PLAIN, *APPLY_FLAGS, "--check", "-", data=patch, check=False)
        if check_apply.returncode != 0:
            detail = wb.redactor.redact_text(" ".join(check_apply.stderr.split())[:300])
            return _refuse(
                wb, task, role, raised, f"the patch does not apply cleanly to the branch as it is now: {detail}"
            )
    tests = tuple(str(t) for t in raised.data.get("tests") or [])
    return Replay(qid, check, patch, sha, result, tests, patch_rel, meta_rel, agent)


def _small(result: dict[str, Any]) -> dict[str, Any]:
    """The agent's result without the fields that grow with the step (the patch holds them)."""
    return {**result, "files_changed": [], "tests_added": []}


def _patch_paths(wb: Workbench, patch: bytes) -> frozenset[str]:
    """The paths a patch changes, as `git apply --numstat -z` lists them."""
    if not patch:
        return frozenset()
    out = wb.git.run_input_bytes(*GIT_PLAIN, "apply", "--numstat", "-z", "-", data=patch).stdout
    paths = set()
    for record in out.split("\0"):
        parts = record.split("\t", 2)
        if len(parts) == 3 and parts[2]:
            paths.add(parts[2])
    return frozenset(paths)


_NOISE = ("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache")


class ReplayGuard:
    """What a replayed step may leave in the work tree (SPEC L4-IMP-065), modelled on `ProductionGuard`: the step base
    plus the saved patch, and nothing else. The expected state is not read from the tree (setup may have run code of the
    patch before the guard was armed): `wb.replay_expected` comes from a temporary index (`expected_state`), and after
    every gate run each non-ignored path is put back to it: a path of the patch to the patch's blob (streamed in), mode
    and link target; every other path that differs from the step base (a tracked file setup or a gate changed, a new
    file) to the base. Ignored files (a setup's `.venv`, caches) are left alone. What was restored is recorded as
    `held.replay_restored`, so the commit holds exactly the saved patch.

    The guard never follows a link (`confined.py`): the work tree folder is opened once when the guard is armed and
    every walk starts from that descriptor. Each path is read and acted on through the descriptor of its folder, reached
    one component at a time with `O_NOFOLLOW`, right before it is acted on; before every restore and every git call the
    work tree is checked to be still the same folder. A link is trusted only where the saved patch creates it, with the
    patch's target; any other link in the tree when the guard is armed, or a folder a gate replaced by a link above a
    path of the step, fails the step (`held.replay_unsafe`) and the link itself is removed. A file is hashed in chunks,
    and only where the expected blob has the file's size. A path the guard cannot read fails the step cleanly."""

    def __init__(self, wb: Workbench) -> None:
        self.wb = wb
        self.base = wb.head()
        self.expected: dict[str, tuple | None] = {}  # path -> ("blob", id, exec, size) | ("link", target) | None
        self.planted: list[str] = []  # links in the tree before the first gate that the saved patch does not create
        self.unreadable: list[str] = []  # what the snapshot could not read: the first restore fails the step
        self.root_fd = os.open(wb.worktree, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        st = os.fstat(self.root_fd)
        self.root_id = (st.st_dev, st.st_ino)
        self.fmt = self._object_format()
        for path, entry in dict(wb.replay_expected).items():
            if wb.protected.match(path) is None:  # a protected path of the patch was put back to the base: it stays so
                self.expected[path] = self._expect(entry)
        try:
            paths = self._paths()
        except (OSError, GitError) as exc:
            paths = {}
            self.unreadable.append(exc.__class__.__name__)
        for path in paths:  # only what is there: a link must be the patch's
            try:
                now = describe_entry(self.root_fd, path, None, self.fmt)
            except LinkedParent:
                continue
            except OSError as exc:
                self.unreadable.append(exc.__class__.__name__)
                continue
            if now is not None and now[0] == "link" and now != self.expected.get(path):
                self.planted.append(path)  # a link the patch does not create, or one re-pointed since the patch

    def _object_format(self) -> str:
        try:
            return self.wb.git.run("rev-parse", "--show-object-format").stdout.strip() or "sha1"
        except GitError:
            return "sha1"

    def _expect(self, entry: tuple | None) -> tuple | None:
        """The guard's form of a (mode, blob, size) entry of the temporary index."""
        if entry is None:
            return None
        mode, blob, size = entry
        if mode == "120000":
            try:
                return ("link", os.fsdecode(self.wb.git.run_bytes("cat-file", "blob", blob)))
            except GitError:
                return ("link", "\0unknown")  # nothing matches it: the link stays untrusted
        return ("blob", blob, mode == "100755", size)

    def close(self) -> None:
        if self.root_fd >= 0:
            os.close(self.root_fd)
            self.root_fd = -1

    def __del__(self) -> None:
        with contextlib.suppress(OSError, AttributeError):
            self.close()

    def _root_ok(self) -> bool:
        """The work tree is still the folder the guard started in (not swapped for a link to another checkout)."""
        try:
            st = os.stat(self.wb.worktree, follow_symlinks=False)
        except OSError:
            return False
        return stat.S_ISDIR(st.st_mode) and (st.st_dev, st.st_ino) == self.root_id

    def _own(self, path: str) -> bool:
        """The harness's own outputs: the run's ledger, the unit folder's `.l4/`, `tasks.md` and `questions.md`."""
        wb = self.wb
        unit = wb.unit_rel
        return (
            path in (wb.ledger_rel, f"{unit}/tasks.md", f"{unit}/questions.md")
            or path.startswith(f"{unit}/.l4/")
            or any(part in _NOISE for part in path.split("/"))
            or path.endswith(".pyc")
        )

    def _paths(self) -> dict[str, bool]:
        """The paths that differ from the step base: by the base's ignore rules (as `changed_paths` lists them) and by
        the work tree's (a patch's `.gitignore` can show a file the base hides, and a commit would take it)."""
        wb = self.wb
        found = {p: e for p, e in changed_paths(wb.git, self.base, excludes=wb.excludes).items() if not self._own(p)}
        shown = wb.git.run_bytes("ls-files", "--others", "--exclude-standard", "--exclude-from", str(wb.excludes), "-z")
        for raw in shown.split(b"\0"):
            path = os.fsdecode(raw)
            if path and path not in found and not self._own(path):
                found[path] = False
        return found

    def stage_paths(self, extra: Sequence[str] = ()) -> list[str]:
        """What the commit of the replayed step stages: the paths of the saved patch (deletions included) and the
        harness's own outputs (`extra`, the ledger, `tasks.md`), nothing the work tree happens to hold."""
        wb = self.wb
        wanted = [*self.expected, wb.ledger_rel, f"{wb.unit_rel}/tasks.md", *extra]
        tracked = set(os.fsdecode(p) for p in wb.git.run_bytes("ls-files", "-z").split(b"\0") if p)
        return sorted({p for p in wanted if p in tracked or os.path.lexists(wb.worktree / p)})

    def _describe(self, path: str) -> Entry | None:
        return describe_entry(self.root_fd, path, self.expected.get(path), self.fmt)

    def release(self, paths: Sequence[str]) -> None:
        """The harness itself put these paths back to the step base (an unused stub): they are expected unchanged."""
        for path in paths:
            self.expected.pop(path, None)

    def _fail(self, where: str, links: Sequence[str], paths: Sequence[str], why: str) -> str:
        """Remove each link itself (by its folder's descriptor, never what it points to), record it, give the reason."""
        wb = self.wb
        for link in links:
            try:
                remove_link(self.root_fd, link)
            except OSError:
                continue
        wb.emit("held.replay_unsafe", where=where, links=list(links)[:20], paths=list(paths)[:20])
        return f"{why} ({where}): the replay does not follow it, so the step fails"

    @staticmethod
    def _put_back_failed(where: str, exc: Exception) -> str:
        return f"the replayed step could not be put back to its saved patch ({where}): {exc.__class__.__name__}"

    def restore(self, where: str) -> str | None:
        """Put back what a gate run changed; the reason when the step must fail, else None."""
        wb = self.wb
        if not self._root_ok():
            return self._fail(where, [], [], "the work tree folder is no longer the one the replay started in")
        if self.planted:
            shown = ", ".join(f"`{p}`" for p in self.planted[:5])
            return self._fail(
                where, self.planted, self.planted,
                f"a link {shown} was in the work tree before the first gate and the saved patch does not create it",
            )  # fmt: skip
        if self.unreadable:
            return f"the replayed step could not be put back to its saved patch ({where}): {self.unreadable[0]}"
        try:
            now = self._paths()
        except (OSError, GitError) as exc:
            return self._put_back_failed(where, exc)
        everything = sorted(set(now) | set(self.expected))
        for path in everything:  # before any action: a link above any path of the step fails it, whatever the order
            try:
                check_parents(self.root_fd, path)
            except LinkedParent as linked:
                if not self._beneath_own_link(linked.rel):
                    return self._fail(where, [linked.rel], [path], self._why(linked.rel))
            except OSError as exc:
                if isinstance(exc, PermissionError):  # a folder a gate made unreadable would also stop the discard
                    repair_dir_modes(self.root_fd, path)
                return self._put_back_failed(where, exc)
        restored: list[str] = []
        try:
            for path in everything:
                try:
                    self._restore_one(path, now.get(path), restored)
                except LinkedParent as linked:  # a link appeared meanwhile: checked again right before acting
                    if self._beneath_own_link(linked.rel):
                        continue
                    return self._fail(where, [linked.rel], [path], self._why(linked.rel))
        except _RootChanged:
            return self._fail(where, [], [], "the work tree folder is no longer the one the replay started in")
        except (OSError, GitError) as exc:
            return self._put_back_failed(where, exc)
        if restored:
            wb.emit("held.replay_restored", where=where, count=len(restored), paths=restored[:50])
        return None

    def _beneath_own_link(self, rel: str) -> bool:
        """`rel` is a link the saved patch creates: what stood below it went with the folder that it replaced."""
        entry = self.expected.get(rel)
        return entry is not None and entry[0] == "link"

    @staticmethod
    def _why(rel: str) -> str:
        return f"a gate run replaced the folder `{rel}` by a symbolic link above a path of the replayed patch"

    def _git(self, *args: str) -> None:
        if not self._root_ok():  # git runs in the work tree by name: never in another checkout
            raise _RootChanged
        self.wb.git.run(*args)

    def _restore_one(self, path: str, existed: bool | None, restored: list[str]) -> None:
        wb = self.wb
        if path not in self.expected:  # not part of the saved patch: it must be as at the step base
            if not existed and not exists_entry(self.root_fd, path):  # decided by lstat, nothing is read
                return
            remove_entry(self.root_fd, path)
            if existed:
                self._git("checkout", self.base, "--", f":(literal){path}")
            else:
                self._git("rm", "--quiet", "--cached", "--ignore-unmatch", "--", f":(literal){path}")
            restored.append(path)
            return
        expected = self.expected[path]
        now = self._describe(path)
        if expected is None:
            if now is None:
                return
            remove_entry(self.root_fd, path)
        elif expected[0] == "link":
            if now == expected:
                return
            put_entry(self.root_fd, path, expected)
        else:  # a blob of the patch
            if now is not None and now[0] == "blob" and now[1] == expected[1] and now[2] == expected[2]:
                return
            blob = expected[1]
            put_blob(self.root_fd, path, lambda out: wb.git.stream_blob(blob, out), expected[2])
        restored.append(path)


class _RootChanged(Exception):
    pass


def _index_entries(git: Git) -> dict[str, tuple[str, str]]:
    """path -> (mode, blob id) of every entry of the index."""
    out = git.run_bytes("ls-files", "-s", "-z")
    entries = {}
    for record in out.split(b"\0"):
        meta, _, name = record.partition(b"\t")
        parts = meta.split()
        if len(parts) == 3:
            entries[os.fsdecode(name)] = (parts[0].decode(), parts[1].decode())
    return entries


def expected_state(wb: Workbench, patch: bytes) -> dict[str, tuple[str, str, int] | None]:
    """The paths the saved patch changes, as (mode, blob id, size) of the entry it leaves (None: deleted). Taken from a
    temporary index (the step base, the patch applied to it, `ls-files -s -z`), never from text that a file name
    can forge, and never from the tree. A patch that does not apply there expects nothing."""
    if not patch:
        return {}
    with tempfile.TemporaryDirectory(prefix="l4-index-") as tmp:
        git = wb.git.at(wb.worktree)
        git.env = {**git.env, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        try:
            git.run("read-tree", wb.head())
            before = _index_entries(git)
            git.run_input_bytes(*GIT_PLAIN, *APPLY_FLAGS, "--cached", "-", data=patch)
            after = _index_entries(git)
            changed = {p: after.get(p) for p in set(before) | set(after) if before.get(p) != after.get(p)}
            blobs = sorted({entry[1] for entry in changed.values() if entry is not None and entry[0] != "160000"})
            sizes = _blob_sizes(git, blobs)
        except GitError:
            return {}
    return {
        path: None if entry is None else (entry[0], entry[1], sizes.get(entry[1], -1))
        for path, entry in changed.items()
        if entry is None or entry[0] != "160000"
    }


def _blob_sizes(git: Git, blobs: Sequence[str]) -> dict[str, int]:
    if not blobs:
        return {}
    out = git.run_input_bytes("cat-file", "--batch-check", data=("\n".join(blobs) + "\n").encode()).stdout
    sizes = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[2].isdigit():
            sizes[parts[0]] = int(parts[2])
    return sizes


def links_added(wb: Workbench, patch: bytes) -> dict[str, str]:
    """The links the saved patch creates or changes, path -> blob id of the target it gives."""
    return {path: entry[1] for path, entry in expected_state(wb, patch).items() if entry and entry[0] == "120000"}


def arm_replay_guard(wb: Workbench) -> None:
    """Called right before the first gate of a step: a replayed step is guarded from here on."""
    close_replay_guard(wb)
    wb.replay_guard = ReplayGuard(wb) if wb.replay_question is not None else None


def close_replay_guard(wb: Workbench) -> None:
    if wb.replay_guard is not None:
        wb.replay_guard.close()
    wb.replay_guard = None


def restore_replay(wb: Workbench, where: str) -> str | None:
    return wb.replay_guard.restore(where) if wb.replay_guard is not None else None


def release_replay(wb: Workbench, paths: Sequence[str]) -> None:
    if wb.replay_guard is not None:
        wb.replay_guard.release(paths)


def replay_step(wb: Workbench, role: str, task: Task, attempt: int, replay: Replay) -> "StepOutcome":
    """Apply the saved step and hand over what an agent step hands over: the guards that `agent_step` runs after an
    agent returns (protected paths put back, the ledger restored, the secret scan), then the saved result. Everything
    after the step in `run_red`, `run_green` and `run_single` is the same code. Returns a `StepOutcome`."""
    from l4.implementer.tdd import StepOutcome  # the module imports this one

    if wb.worktree.is_symlink():
        return StepOutcome("failed", reason="the work tree folder is a link: the saved step is not applied")
    base = wb.head()
    wb.setup_at = None  # as after an agent: the setup runs again on what the step changed (a lock file, a manifest)
    wb.commit_agent = replay.agent  # the commit names the profile that wrote the step
    wb.replay_question = replay.question  # the accept applies in this step only
    wb.replay_expected = expected_state(wb, replay.patch)
    wb.replay_links = {p: e[1] for p, e in wb.replay_expected.items() if e and e[0] == "120000"}
    if replay.patch:
        try:
            wb.git.run_input_bytes(*GIT_PLAIN, *APPLY_FLAGS, "-", data=replay.patch)  # the bytes that were verified
        except GitError as exc:  # `--check` passed a moment ago: the work tree changed under us
            wb.discard_changes()
            return StepOutcome("failed", reason=f"the saved step could not be applied: {exc}")
    revert_protected(wb.git, wb.protected, base, events=wb, excludes=wb.excludes)
    wb.restore_ledger(task=task.key, phase=role, attempt=attempt)
    sources = {i: test_source(wb, i) for i in replay.tests[:MAX_SHOWN_TESTS]}
    wb.emit(
        "held.replayed", question=replay.question, task=task.key, check=replay.check, patch_sha256=replay.patch_sha256,
        tests=list(replay.tests[:50]), sources={k: v[:MAX_EVENT_SOURCE_CHARS] for k, v in sources.items()},
        phase=role, attempt=attempt,
    )  # fmt: skip
    changed = sorted(p for p in wb.changed_files() if p != wb.ledger_rel)
    if hits := worktree_secrets(wb.git, wb.redactor, changed):
        for hit in hits:
            wb.emit("guard.secret", path=hit.path, kind=hit.kind, task=task.key, phase=role, attempt=attempt)
        _queue_removal(wb, task.key, replay.check)
        return StepOutcome("failed", reason=step_secret_reason(hits))
    _queue_removal(wb, task.key, replay.check)  # the step's own commit deletes the saved step
    return StepOutcome("ok", replay.result)


# --- the prompt of a later agent step (D4) ---------------------------------------------------------------------


def accepted_tests_block(wb: Workbench, role: str, task: Task) -> tuple[tuple[str, str], ...]:
    """The data block `accepted tests` of an agent step. A question raised before 0.4.18 (no saved step) still covers
    its tests by id: they are listed with their source and the rule to keep them unchanged. After a replay that is
    used up, the accept covers nothing: the block says that it was for an earlier step and
    that a new step needs a new answer."""
    lines: list[str] = []
    tests: list[str] = []
    for check in CHECKS[role]:
        for override in accepted_overrides(wb, task.key, check).values():
            tests += sorted(t for t in override.tests if t not in tests)
    if tests:
        lines += [ACCEPTED_TESTS_RULE]
        for test in tests[:MAX_SHOWN_TESTS]:
            lines += ["", f"{test}:", *(f"    {line}" for line in test_source(wb, test).splitlines())]
        if len(tests) > MAX_SHOWN_TESTS:
            lines += ["", f"(+{len(tests) - MAX_SHOWN_TESTS} more accepted tests)"]
    if any(e.type == "held.replayed" and e.data.get("task") == task.key for e in _events(wb)):
        lines += ["", USED_UP_NOTICE] if lines else [USED_UP_NOTICE]
    if not lines:
        return ()
    return (("accepted tests", data_block("accepted tests", wb.redactor.redact_text("\n".join(lines)))),)
