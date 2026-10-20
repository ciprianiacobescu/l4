"""What the harness put back during an agent step, as a note for the next attempt's prompt (handbook 10: errors are
observations; live M1.6 job 5537).

The guards (`stubs.enforce_red_scope`, `revert_protected`, `restore_frozen`, the production-file guard) revert or drop
parts of a step and record a `guard.violation` or `guard.test_tamper` event. Those events went to the ledger only, so
an agent whose step was rejected for another reason (a lint error in the file the guard had rebuilt) never learned that
the guard had changed its file, and sent the same file again. `Workbench.emit` collects them per attempt; `run_task`
appends `guard_note_text` to the reason of a failed attempt, for the prompt only (the ledger keeps the plain reason).

The note is bounded (`MAX_NOTES` lines of at most `MAX_NOTE_CHARS` characters), one line per path and rule, and carries
repository-influenced text (paths, the guard's own region note), so it only ever travels inside the previous-attempt
`<l4:data>` block, which defuses it, and the whole prompt is redacted before it is sent.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

MAX_NOTES = 5
MAX_NOTE_CHARS = 280
GUARD_EVENTS = ("guard.violation", "guard.test_tamper")
_IGNORED_RULES = ("run ledger",)  # the harness's own file: a restore there is not the agent's mistake to learn from

_RED_SCOPE = (
    "A red step may only add or change test files, signature-only stubs (a body that is exactly `raise "
    "NotImplementedError`) and the imports a stub needs; every other change to a production file is put back. "
    "Write the step so that it holds without the part that was put back: a name that only a dropped statement "
    "defined is undefined in the file the harness rebuilds."
)
_ADVICE = {
    "red scope": _RED_SCOPE,
    "gate-mutated-production": (
        "A test run changed a production file, which the harness put back: tests must not write outside their own "
        "files."
    ),
    "test path freeze": (
        "Tests belong in the red step: if a test is wrong or missing, ask a question that names its path."
    ),
    "opened file": (
        "A support file that the task names may only grow in green: keep every existing statement as it is, do not "
        "rebind a name or a fixture, do not patch or assign the unit's code from it (set the environment instead), "
        "and leave it a regular file. The harness put it back to its red version, so write the change again."
    ),
    "planted link": (
        "A test run replaced a directory or file of the worktree with a symbolic link. The harness never writes "
        "through one: it removed the link and discarded the attempt. Create links only under the test's own temporary "
        "directory (`tmp_path`)."
    ),
    "restore failed": (
        "The harness could not put a file back after a test run changed it. Tests must not replace, delete or lock "
        "source files."
    ),
    "link outside worktree": (
        "A symbolic link that points outside the repository (an absolute target, or `..` above the root) is never "
        "committed: the harness discarded the step. Keep the link out of the work, or point it at a path inside the "
        "repository."
    ),
    "gate configuration": (
        "Lint, type-check and other gate settings (ruff, mypy, eslint, tsconfig, and the gate sections of "
        "pyproject.toml, setup.cfg, tox.ini and package.json) are the project's: the harness put the whole file back "
        "to the step's base. Make the code meet them. A dependency you added in the same file must be written again "
        "without touching those sections. If a setting is wrong, ask a question that names the file."
    ),
    "runner configuration": (
        "Test-runner settings (the pytest and coverage sections, addopts and plugins, jest and the like) are not the "
        "step's to change: the harness put the whole file back to the step's base. Write the change again without "
        "them. A dependency you added in the same file must be written again too; a new pytest marker is allowed. If "
        "the task needs one of these settings, ask a question that names the file."
    ),
    "environment": (
        "The harness rebuilds `.venv` and `node_modules` from the lock files after every step and removed what the "
        "step wrote there. Declare a dependency in the manifest and the lock file (`uv add`, `npm install` are "
        "fine); never write into an installed environment."
    ),
    "frozen test": (
        "Tests and test-support files are frozen once red is committed: do not edit them, make the code pass them."
    ),
}
_GENERIC = (
    "The harness protects some paths (CI files, agent configuration, repository guidance files, anything under "
    "`.l4/`) and puts them back at every step: do not repeat the change, and leave those paths alone."
)


@dataclass(frozen=True)
class GuardNote:
    event: str
    path: str
    rule: str
    action: str
    detail: str


def _flat(text: object, limit: int) -> str:
    one = " ".join(str(text).split())
    return one if len(one) <= limit else one[: limit - 3] + "..."


def note_of(event: str, data: Mapping[str, Any]) -> GuardNote | None:
    """The note for one guard event, or None for an event the agent cannot act on."""
    if event not in GUARD_EVENTS:
        return None
    if data.get("action") == "rejected":
        return None  # the failed attempt's own reason and excerpt carry it (a note would say "put back")
    rule = str(data.get("rule") or ("frozen test" if event == "guard.test_tamper" else ""))
    if rule in _IGNORED_RULES or not data.get("path"):
        return None
    detail = data.get("region") or data.get("where") or data.get("reason") or data.get("why") or ""
    if rule == "test path freeze" and not detail:
        who = "a fix chore" if data.get("phase") == "single" else "green"
        detail = (
            f"{who} may not change test files: {data['path']} was put back "
            "(tests belong in the red step; ask a question if a test is wrong)"
        )
    return GuardNote(event, _flat(data["path"], 200), rule, str(data.get("action") or "restored"), _flat(detail, 400))


def guard_note_text(notes: Iterable[GuardNote]) -> str:
    """ "" when there is nothing; else the lines for the prompt: what was put back, then what to do instead."""
    unique = list(dict.fromkeys(notes))
    if not unique:
        return ""
    lines = []
    for note in unique[:MAX_NOTES]:
        why = f": {note.detail}" if note.detail else ""
        lines.append(_flat(f"- `{note.path}` ({note.rule or 'protected path'}) {note.action}{why}", MAX_NOTE_CHARS))
    more = f"\n(+{len(unique) - MAX_NOTES} more)" if len(unique) > MAX_NOTES else ""
    rules = list(dict.fromkeys(n.rule for n in unique))
    advice = " ".join(_ADVICE.get(r, _GENERIC) for r in rules if r in _ADVICE)
    if any(r not in _ADVICE for r in rules):
        advice = f"{advice} {_GENERIC}".strip()
    return (
        "The harness also put back parts of that step before it judged it (the rest of your step was judged as it "
        "stood):\n" + "\n".join(lines) + more + f"\nWhat to do instead: {advice}"
    )
