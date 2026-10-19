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
import hashlib
import json
import logging
import os
import re
import shutil
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from l4.fsutil import UnsafeFile, atomic_write_bytes, read_regular_file, reject_symlinks
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
from l4.implementer.stubs import restore_to_base
from l4.implementer.workbench import Workbench
from l4.security.protected import changed_paths, revert_protected
from l4.specs.base import Task
from l4.specs.questions import QUESTIONS_FILENAME, QuestionsFile, harness_answer
from l4.state.ledger import LedgerEvent, read_ledger
from l4.vcs.git import GitError
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
    """The tree of a replayed step as it was when its first gate was about to run (SPEC L4-IMP-065), modelled on
    `ProductionGuard`: gates run test code with a writable work tree, so after every gate run the content of every
    non-ignored path is put back to what it was (a new path removed, a changed one restored, a deleted one deleted
    again) and what was restored is recorded as `held.replay_restored`. The commit then holds exactly the saved
    patch."""

    def __init__(self, wb: Workbench) -> None:
        self.wb = wb
        self.base = wb.head()
        self.guarded: dict[str, bytes | None] = {path: self._read(path) for path in self._paths()}

    def _own(self, path: str) -> bool:
        wb, parts = self.wb, path.split("/")
        return (
            path in (wb.ledger_rel, f"{wb.unit_rel}/tasks.md", f"{wb.unit_rel}/questions.md")
            or ".l4" in parts
            or any(part in _NOISE for part in parts)
            or path.endswith(".pyc")
        )

    def _paths(self) -> dict[str, bool]:
        wb = self.wb
        return {p: e for p, e in changed_paths(wb.git, self.base, excludes=wb.excludes).items() if not self._own(p)}

    def _read(self, path: str) -> bytes | None:
        target = self.wb.worktree / path
        try:
            if target.is_symlink() or not target.is_file():
                return None
            return target.read_bytes()
        except OSError:
            return None

    def release(self, paths: Sequence[str]) -> None:
        """The harness itself changed these paths (an unused stub put back to the base): guard the state they are in."""
        now = self._paths()
        for path in paths:
            if path in now:
                self.guarded[path] = self._read(path)
            else:
                self.guarded.pop(path, None)

    def restore(self, where: str) -> str | None:
        """Put back what a gate run changed; the reason when a path cannot be put back, else None."""
        wb = self.wb
        now = self._paths()
        restored: list[str] = []
        try:
            for path in sorted(set(now) | set(self.guarded)):
                target = wb.worktree / path
                if path not in self.guarded:
                    restore_to_base(wb, self.base, path, now[path])
                    restored.append(path)
                    continue
                expected = self.guarded[path]
                if self._read(path) == expected and (expected is not None or not target.is_symlink()):
                    continue
                if target.is_symlink() or target.is_file():
                    target.unlink()
                elif target.is_dir():
                    shutil.rmtree(target)
                if expected is not None:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(expected)
                restored.append(path)
        except (OSError, GitError) as exc:
            return f"the replayed step could not be put back to its saved patch ({where}): {exc.__class__.__name__}"
        if restored:
            wb.emit("held.replay_restored", where=where, count=len(restored), paths=restored[:50])
        return None


def arm_replay_guard(wb: Workbench) -> None:
    """Called right before the first gate of a step: a replayed step is guarded from here on."""
    wb.replay_guard = ReplayGuard(wb) if wb.replay_question is not None else None


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

    base = wb.head()
    wb.setup_at = None  # as after an agent: the setup runs again on what the step changed (a lock file, a manifest)
    wb.commit_agent = replay.agent  # the commit names the profile that wrote the step
    wb.replay_question = replay.question  # the accept applies in this step only
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
    """The data block `accepted tests` of an agent step. A question of 0.4.16 (no saved step) still covers its tests by
    id: they are listed with their source and the rule to keep them unchanged. After a replay that is used up, the
    accept covers nothing: the block says that it was for an earlier step and that a new step needs a new answer."""
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
