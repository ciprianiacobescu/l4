"""A criterion whose evidence the parts of a long diff split is judged once more on all of its files (L4-VER-056 to
L4-VER-058).

The parts of a long diff each see some of a criterion's code; a part that sees half answers `insufficient_evidence`, and
two such answers are not a confirmation. After the parts are merged, each *split* criterion (its merged verdict is
`insufficient_evidence`, a person has not decided it, its tracing tests cover it, and the files the harness knows for it
lie in two or more judged parts) is put in a follow-up call that shows those files together, whole, within one part's
characters. The follow-up's verdict replaces the merged one; a follow-up never makes a round worse (it changes only its
own group and a reply that gives no verdict keeps the parts' verdict).
"""

import os
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, cast

from l4.config.schema import L4Config
from l4.evidence.scope import file_kind
from l4.evidence.testsran import file_of_test
from l4.vcs.git import Git
from l4.verifier import diffparts
from l4.verifier.aggregate import pick_verdicts
from l4.verifier.diffparts import DiffEntry, DiffParts, _imported, _is_test, file_rows, group_key
from l4.verifier.integrity import IntegrityContext, commits
from l4.verifier.judge import JudgeVerdict, parts_text
from l4.verifier.judge_parts import _adequacy, _findings
from l4.verifier.types import CriterionEvidence

FOLLOWUP_MORE_LINE = 60  # the characters kept for the `+K more files` line of a capped list
MAX_NOTE_PATHS = 3  # the paths a note names of the files a follow-up did not show


@dataclass(frozen=True)
class Split:
    """A criterion of L4-VER-056: its judged parts, its files in D2's order (primary files, then secondary files) and
    how many of them are primary. The `weak` files are secondary files that `file_kind` calls neither code nor test (a
    lock file, a README at the root): they may be shown when room remains but never make a criterion split (D2)."""

    criterion: str
    parts: tuple[int, ...]
    files: tuple[str, ...]
    primary: int
    weak: frozenset[str] = frozenset()  # secondary files that are context only: they never count toward the split


@dataclass(frozen=True)
class Group:
    """One follow-up call: its criteria, the entries it shows (part order, then the packing's order), the parts those
    entries come from, and the files of its criteria it does not show as `(path, part number or 0, characters)`."""

    index: int
    criteria: tuple[str, ...]
    entries: tuple[DiffEntry, ...]
    parts: tuple[int, ...]
    not_shown: tuple[tuple[str, int, int], ...]


def proof_tasks(events: Iterable[Any]) -> dict[str, tuple[str, ...]]:
    """Criterion id -> the keys of the tasks whose `task.red_ok` proof for it lists tests (`discriminating` or
    `tests`), in event order. The events of a fix unit are skipped (a fix unit's task keys repeat the unit's)."""
    found: dict[str, list[str]] = {}
    for event in events:
        if event.type != "task.red_ok" or event.data.get("fix_unit"):
            continue
        key = str(event.data.get("task") or "")
        proofs = event.data.get("criteria")
        if not key or not isinstance(proofs, Mapping):
            continue
        for cid, info in proofs.items():
            if isinstance(info, Mapping) and (info.get("discriminating") or info.get("tests")):
                tasks = found.setdefault(str(cid), [])
                if key not in tasks:
                    tasks.append(key)
    return {cid: tuple(tasks) for cid, tasks in found.items()}


def task_files(
    git: Git, base: str, head: str, units: Collection[str], tasks: Collection[str]
) -> dict[str, frozenset[str]]:
    """Task key -> the files the harness commits `base..head` of that task changed, over the commits whose `L4-Unit` is
    one of `units` and whose `L4-Task` is one of `tasks` (the reading of `integrity.tagged_files`: one `git log`, then
    one `git diff-tree` per matching commit)."""
    found: dict[str, set[str]] = {}
    if not tasks:
        return {}
    ctx = cast(IntegrityContext, SimpleNamespace(git=git, base_sha=base, head_sha=head))
    for commit in commits(ctx):
        if commit.unit not in units or commit.task not in tasks:
            continue
        out = git.run_bytes(
            "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", "-m", "--first-parent", commit.sha
        )
        found.setdefault(commit.task, set()).update(os.fsdecode(p) for p in out.split(b"\0") if p)
    return {task: frozenset(paths) for task, paths in found.items()}


def _diff_paths(parts: DiffParts) -> list[str]:
    """Every path of the diff in the order the parts hold it, then the unseen ones."""
    return [e.paths[-1] for p in parts.parts for e in p.entries] + list(parts.unseen)


def _named(ref: str, paths: Collection[str]) -> str | None:
    """The longest path of the diff that `ref` equals or that it starts with followed by `:`."""
    best = ""
    for path in paths:
        if (ref == path or ref.startswith(path + ":")) and len(path) > len(best):
            best = path
    return best or None


def criterion_files(
    cid: str,
    *,
    replies: Sequence[JudgeVerdict],
    evidence: CriterionEvidence | None,
    parts: DiffParts,
    tasks: Sequence[str],
    task_files: Mapping[str, frozenset[str]],
    unit_dirs: Collection[str],
    cfg: L4Config,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The files of a criterion (D2): the primary ones (what the parts cited, what its tracing tests are in, the code
    those tests import), then the secondary ones (the files its tasks' commits changed). Only paths of the diff, and
    none that `file_kind` calls exempt (a harness, spec or unit-folder path)."""
    paths = _diff_paths(parts)
    known = frozenset(paths)

    def allowed(path: str) -> bool:
        return not any(file_kind(path, unit, cfg) == "exempt" for unit in unit_dirs or [""])

    primary: dict[str, None] = {}
    for reply in replies:  # 1. cited, part by part
        for item in reply.criteria:
            if item.id != cid:
                continue
            for ref in item.evidence:
                if ref.kind in ("file", "test") and (path := _named(ref.ref, known)) and allowed(path):
                    primary.setdefault(path)
    test_files: list[str] = []
    for test in evidence.tests if evidence is not None else ():  # 2. the file of each tracing test
        found = file_of_test(test.id, known)
        if found and allowed(found) and found not in test_files:
            test_files.append(found)
            primary.setdefault(found)
    entries = {e.paths[-1]: e for p in parts.parts for e in p.entries}
    for test_file in test_files:  # 3. the code those tests import (the rule by which `pack` puts a test by its code)
        text = entries[test_file].text if test_file in entries else ""
        for name in dict.fromkeys(_imported(text)):
            for path in paths:
                if path in entries and not _is_test(path) and allowed(path) and group_key(path) == name:
                    primary.setdefault(path)
    secondary: dict[str, None] = {}
    for key in tasks:  # 4. the files of its tasks' commits
        for path in sorted(task_files.get(key, ())):
            if path in known and allowed(path) and path not in primary:
                secondary.setdefault(path)
    return tuple(primary), tuple(secondary)


def _where(parts: DiffParts) -> dict[str, tuple[int, int, bool]]:
    """Path -> (part number or 0, characters, whether the file is shown whole: not in a cut part, in a judged part)."""
    found: dict[str, tuple[int, int, bool]] = {}
    for part in parts.parts:
        for entry in part.entries:
            found[entry.paths[-1]] = (part.index, entry.length, not part.cut)
    for path, chars in zip(parts.unseen, parts.unseen_chars, strict=True):
        found[path] = (0, chars, False)
    return found


def _covered(trace: CriterionEvidence | None) -> bool:
    """The aggregation's own test of a criterion the judge decides: covered, not held, and an adequate passing test."""
    return (
        trace is not None
        and trace.state == "covered"
        and not trace.held
        and any(t.status == "passed" and t.adequate for t in trace.tests)
    )


def find_splits(
    criteria: Sequence[Any],
    merged: JudgeVerdict,
    trace: Sequence[CriterionEvidence],
    parts: DiffParts,
    files_of: Callable[[str], tuple[tuple[str, ...], tuple[str, ...]]],
    counts: Callable[[str], bool] | None = None,
) -> list[Split]:
    """The split criteria of L4-VER-056, in the order of `criteria` (which holds no criterion that a person has
    decided). `trace` has the parts' test adequacy applied. `files_of` is asked only for a criterion that meets the
    first four conditions, so a round without one runs no git command. A secondary file counts toward the parts only
    when `counts(path)` is true (code or test by `file_kind`); the others are kept as context (`Split.weak`)."""
    if len(parts.parts) < 2:
        return []
    picked = pick_verdicts(merged)
    evidence = {e.criterion: e for e in trace}
    where = _where(parts)
    found = []
    for criterion in criteria:
        cid = criterion.id
        verdict = picked.get(cid)
        if verdict is None or verdict.verdict != "insufficient_evidence" or not _covered(evidence.get(cid)):
            continue
        primary, secondary = files_of(cid)
        weak = frozenset(f for f in secondary if counts is not None and not counts(f))
        files = (*primary, *secondary)
        judged = tuple(sorted({where[f][0] for f in files if f in where and where[f][0] > 0 and f not in weak}))
        if len(judged) >= 2:
            found.append(Split(cid, judged, files, len(primary), weak))
    return found


def _row_width(path: str, part: int, chars: int, shown: bool) -> int:
    """The characters of one line of the follow-up's file list (as `_followup_listing` writes it) and its newline."""
    where = f"part {part}" if part else "no part"
    return (
        len(
            f"{'shown' if shown else 'not shown'}: {path[: diffparts.LISTING_PATH_CHARS]} ({where}, {chars} characters)"
        )
        + 1
    )


def _cost(paths: Iterable[str], where: Mapping[str, tuple[int, int, bool]]) -> tuple[int, int, int]:
    """The characters of the diff, of the `shown:` lines and the number of lines that `paths` take in a follow-up."""
    chars = rows = count = 0
    for path in dict.fromkeys(paths):
        part, size, _ = where.get(path, (0, 0, False))
        chars, rows, count = chars + size, rows + _row_width(path, part, size, True), count + 1
    return chars, rows, count


def _fits(chars: int, rows: int, count: int, room: int) -> bool:
    """D4's three bounds: the diff within `room`; the diff and the `shown:` lines within a part less the line that
    says how many files the list leaves out, so that the whole prompt part stays within `MAX_PART_CHARS` whatever
    else the list holds; and at most `LISTING_MAX_LINES` shown files (the cap is on the whole list, shown first)."""
    return (
        chars <= room
        and chars + rows <= diffparts.MAX_PART_CHARS - FOLLOWUP_MORE_LINE
        and count <= diffparts.LISTING_MAX_LINES
    )


def _fit(
    files: Sequence[str], where: Mapping[str, tuple[int, int, bool]], room: int, have: Collection[str] = ()
) -> list[str]:
    """The files that are taken in order while they fit in `room` (the ones in `have` cost nothing more); a file that
    is not shown whole is never taken, and one that does not fit is skipped. A file taken is charged its characters
    and its `shown:` line of the list (`_fits`)."""
    taken: list[str] = []
    chars, rows, count = _cost(have, where)
    for path in files:
        part, size, whole = where.get(path, (0, 0, False))
        if not whole or path in taken:
            continue
        if path in have:
            taken.append(path)
        elif _fits(chars + size, rows + _row_width(path, part, size, True), count + 1, room):
            taken.append(path)
            chars, rows, count = chars + size, rows + _row_width(path, part, size, True), count + 1
    return taken


def plan_followups(splits: Sequence[Split], parts: DiffParts) -> tuple[list[Group], dict[str, dict[str, Any]]]:
    """The follow-up groups and the `judge_split` records of the criteria that get no call (D4).

    A criterion whose files taken alone lie in one part only gets none (`no_fit`). The others form groups in order, on
    their primary files, each joining the first group they fit with; a group past the bound of one call per judged part
    is not made (`no_call_left`). Then, in the same order, each criterion's secondary files fill the room of its group.
    """
    room = diffparts.MAX_PART_CHARS - parts.reserve
    where = _where(parts)
    records: dict[str, dict[str, Any]] = {}

    def skipped(split: Split, outcome: str, **extra: Any) -> None:
        left = [[f, *where.get(f, (0, 0, False))[:2]] for f in split.files]
        records[split.criterion] = {
            "parts": list(split.parts),
            "outcome": outcome,
            "followup": None,
            "files": 0,
            "not_shown": left,
            "answer": None,
            "status": None,
            **extra,
        }

    members: list[list[Split]] = []
    wanted: list[list[str]] = []  # per group, the primary files in it
    bound = len(parts.parts)
    for split in splits:
        alone = _fit(split.files, where, room)
        if len({where[f][0] for f in alone if f not in split.weak}) < 2:
            skipped(split, "no_fit")
            continue
        mine = _fit(split.files[: split.primary], where, room)
        for k, held in enumerate(wanted):
            joint = list(dict.fromkeys([*held, *mine]))
            if _fits(*_cost(joint, where), room):
                wanted[k], members[k] = joint, [*members[k], split]
                break
        else:
            if len(members) >= bound:
                skipped(split, "no_call_left", calls=bound)
                continue
            wanted.append(list(mine))
            members.append([split])
    groups = []
    for held, group in zip(wanted, members, strict=True):
        shown = list(held)
        for split in group:  # the files of the tasks' commits fill what room is left
            for path in _fit(split.files[split.primary :], where, room, have=shown):
                if path not in shown:
                    shown.append(path)
        chosen = set(shown)
        entries = tuple(e for p in parts.parts for e in p.entries if e.paths[-1] in chosen and not p.cut)
        counted = {f for s in group for f in s.files if f not in s.weak}
        if len({where[e.paths[-1]][0] for e in entries if e.paths[-1] in counted}) < 2:
            for split in group:  # the fill left the files of one part only: it is no longer split (D4)
                skipped(split, "no_fit")
            continue
        left = dict.fromkeys(f for s in group for f in s.files if f not in chosen)
        groups.append(
            Group(
                len(groups) + 1,
                tuple(s.criterion for s in group),
                entries,
                tuple(sorted({where[e.paths[-1]][0] for e in entries})),
                tuple((f, *where.get(f, (0, 0, False))[:2]) for f in left),
            )
        )
    return groups, records


def followup_rows(parts: DiffParts, group: Group) -> tuple[tuple[tuple[str, int, int, bool], ...], int]:
    """The file list of a follow-up prompt (D5): every file of the diff as `(path, part number or 0, characters,
    shown)`, the shown ones first, then the others in the packing's order, at most `LISTING_MAX_LINES` lines. The
    shown files were charged their lines when the group was planned (`_fit`), so they are all here; the others take
    what a part is left with after the diff shown, the shown lines and the line for the files left out, so the diff and
    the list together stay within `MAX_PART_CHARS`. Also the number of files left out."""
    shown = {e.paths[-1] for e in group.entries}
    every = [(path[: diffparts.LISTING_PATH_CHARS], n, chars, path in shown) for n, path, chars in file_rows(parts)]
    kept = [row for row in every if row[3]]
    others = [row for row in every if not row[3]]
    used = sum(_row_width(*row) for row in kept)
    shown_chars = sum(row[2] for row in kept)
    room = min(
        diffparts.MAX_PART_CHARS // diffparts.LISTING_SHARE - FOLLOWUP_MORE_LINE,
        diffparts.MAX_PART_CHARS - FOLLOWUP_MORE_LINE - shown_chars,
    )
    for row in others:
        width = _row_width(*row)
        if len(kept) >= diffparts.LISTING_MAX_LINES or used + width > room:
            break
        kept.append(row)
        used += width
    return tuple(kept), len(every) - len(kept)


def apply_followups(merged: JudgeVerdict, answered: Sequence[tuple[Sequence[str], JudgeVerdict]]) -> JudgeVerdict:
    """The merged verdict with each follow-up's verdicts in place of its group's. A verdict for an id outside the group
    is ignored and a group criterion the reply leaves out keeps the merged verdict. Of a reply only the
    `test_adequacy` entries and findings of its group count (an entry with no criterion is dropped), and they are merged
    as the parts' were (L4-VER-042); everything else stays the merged one."""
    if not answered:
        return merged
    criteria = list(merged.criteria)
    scoped = []
    for ids, reply in answered:
        group = set(ids)
        picked = pick_verdicts(reply)
        criteria = [picked[c.id] if c.id in group and c.id in picked else c for c in criteria]
        scoped.append(
            reply.model_copy(
                update={
                    "test_adequacy": [a for a in reply.test_adequacy if a.criterion in group],
                    "findings": [f for f in reply.findings if f.criterion in group],
                }
            )
        )
    return merged.model_copy(
        update={
            "criteria": criteria,
            "test_adequacy": _adequacy([merged, *scoped]),
            "findings": _findings([merged, *scoped]),
        }
    )


def split_note(record: Mapping[str, Any] | None) -> str:
    """The note that ends the reason of a split criterion (D8); `""` for a criterion that was not split."""
    if not record:
        return ""
    head = f"its evidence was split over parts {parts_text(record['parts'])} of the diff: "
    k, outcome = record.get("followup"), record["outcome"]
    if outcome == "answered":
        left = record.get("not_shown") or []
        named = [str(item[0] if isinstance(item, Sequence) and not isinstance(item, str) else item) for item in left]
        extra = f", +{len(named) - MAX_NOTE_PATHS} more" if len(named) > MAX_NOTE_PATHS else ""
        tail = f" ({len(named)} not shown: {', '.join(named[:MAX_NOTE_PATHS])}{extra})" if named else ""
        return (
            f"{head}follow-up call {k} judged its {record['files']} files of those parts together and answered "
            f"{record['answer']}{tail}"
        )
    if outcome == "not_answered":
        return (
            f"{head}follow-up call {k} judged its files of those parts together but gave no verdict for it, so the "
            "parts' verdict stands"
        )
    if outcome == "no_answer":
        return f"{head}follow-up call {k} gave no usable answer ({record['status']}), so the parts' verdict stands"
    if outcome == "no_fit":
        return f"{head}no follow-up call was made, because its files of those parts do not fit in one part together"
    return f"{head}no follow-up call was made, because the round's {record.get('calls', 0)} follow-up calls were used"
