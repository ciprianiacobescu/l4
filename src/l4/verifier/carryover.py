"""Carry-over of a judge pass into a round whose judge gave no verdict (L4-VER-072; SCN-VER-273 to -277).

When step 9 of a round ends with no judge verdict (a part's reply was discarded: timeout, a schema break after the
repair), a criterion keeps the `pass` of the newest earlier round that has a judge verdict (R) only while nothing a
judge could have seen of it changed. `decide` is the rule and is pure over its inputs; `carry_over` gathers them through
`Git` and `read_verdict`. For a criterion C all of these hold:
1. R's judge verdict for C is `pass`;
2. C's source file has the same blob at R's head and at this head;
3. every path that changed between the two heads is in a directory of the unit family or the harness's memory, or is a
   test file (a test glob and no support glob); any other path carries nothing for any criterion;
4. no changed path is the file of a test that traces C in R's trace or in this round's trace (a candidate over the cap
   traces it too: the judge's reply could have had it counted);
5. the tests that trace C now are among those of R's trace, and each of them passes now.
A test whose file is not found cannot be shown unchanged, so it keeps its criterion from being carried. Only a `pass` is
carried, with R's test-adequacy rows for the criterion (`apply_carried` applies them as `judge_body` applies the
judge's). The round keeps its hold and findings are not carried. The result is stored with the round (`judge_carried`),
so that a resumed round keeps it without reading R (`carried_verdicts`).
"""

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from l4.implementer.test_locate import file_of_id
from l4.security.protected import glob_match
from l4.specs.base import Criterion
from l4.vcs.git import Git, GitError
from l4.verifier.aggregate import _WORST_FIRST
from l4.verifier.diffparts import blob_ids
from l4.verifier.evidence import HARNESS_MEMORY, read_verdict
from l4.verifier.judge import NOT_IN_PART, CriterionVerdict, TestAdequacy
from l4.verifier.traceability import apply_adequacy, count_named
from l4.verifier.types import CriterionEvidence

__all__ = ["Decision", "apply_carried", "carried_verdicts", "carry_over", "decide", "source_round"]

MAX_LISTED_PATHS = 5
NON_TEST = "a non-test file changed"
NONE_QUALIFIED = "no criterion qualified"
_COMMIT = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")


@dataclass(frozen=True)
class Decision:
    """`carried`: criterion -> `{round, head, verdict, adequacy}` (`verdict`: R's criterion row as stored; `adequacy`:
    R's test-adequacy rows for it), the shape of `VerifyResult.judge_carried`. `reason` (and `paths`, the first
    MAX_LISTED_PATHS offending ones) says why none is carried, when one reason applies to all of them; empty when
    something is carried. `from_round` is None when no earlier round has a judge verdict."""

    from_round: int | None
    from_head: str = ""
    carried: dict[str, dict[str, Any]] = field(default_factory=dict)
    reason: str = ""
    paths: tuple[str, ...] = ()


def source_round(unit_dir: Path, round_no: int) -> tuple[int, dict[str, Any]] | None:
    """R: the newest stored round below `round_no` whose `judge_verdict` is an object with criteria; no search
    further back per criterion."""
    for n in range(round_no - 1, 0, -1):
        prev = read_verdict(unit_dir, n)
        judged = prev.get("judge_verdict") if prev is not None else None
        if prev is not None and isinstance(judged, Mapping) and judged.get("criteria"):
            return n, prev
    return None


def _verdicts(prev: Mapping[str, Any]) -> dict[str, tuple[CriterionVerdict, Mapping[str, Any]]]:
    """R's verdict row per criterion as stored, the worst when an id is listed twice. An id with a row that does not
    parse is left out: its worst answer is not known."""
    rows = (prev.get("judge_verdict") or {}).get("criteria")
    picked: dict[str, tuple[CriterionVerdict, Mapping[str, Any]]] = {}
    unreadable: set[str] = set()
    for raw in rows if isinstance(rows, list) else []:
        try:
            item = CriterionVerdict.model_validate(raw)
        except ValidationError:
            if isinstance(raw, Mapping) and isinstance(raw.get("id"), str):
                unreadable.add(raw["id"])
            continue
        current = picked.get(item.id)
        if current is None or _WORST_FIRST.index(item.verdict) < _WORST_FIRST.index(current[0].verdict):
            picked[item.id] = (item, raw)
    return {cid: found for cid, found in picked.items() if cid not in unreadable}


def _then(prev: Mapping[str, Any]) -> dict[str, tuple[frozenset[str], frozenset[str]]]:
    """criterion -> (the ids of its tracing tests, the ids of its candidates over the cap) in R's stored trace."""
    return {
        str(e["criterion"]): (
            frozenset(str(t["id"]) for t in e["tests"]),
            frozenset(str(t["id"]) for t in e.get("capped") or ()),
        )
        for e in prev["trace"]
    }


def _adequacy(prev: Mapping[str, Any], cid: str, then_ids: Collection[str]) -> list[dict[str, Any]] | None:
    """R's test-adequacy rows that apply to `cid`: its own, and those of no criterion about a test that traced it (they
    apply to the test everywhere, so they apply to it). None when a row does not parse."""
    found: list[dict[str, Any]] = []
    for raw in (prev.get("judge_verdict") or {}).get("test_adequacy") or ():
        try:
            row = TestAdequacy.model_validate(raw)
        except ValidationError:
            return None
        if row.criterion == cid or (not row.criterion and row.test in then_ids):
            found.append(dict(raw))
    return found


def _is_test(path: str, test_globs: Sequence[str], support_globs: Sequence[str]) -> bool:
    return any(glob_match(g, path) for g in test_globs) and not any(glob_match(g, path) for g in support_globs)


def _in_family(path: str, unit_dirs: Sequence[str]) -> bool:
    """A path of the unit family's directories, or of the harness's own memory (`l4 lessons promote` writes it, agent
    steps cannot): neither changes what the product does."""
    return path.startswith(HARNESS_MEMORY) or any(path.startswith(d.rstrip("/") + "/") for d in unit_dirs)


def decide(
    prev: Mapping[str, Any], criteria: Sequence[Criterion], trace: Sequence[CriterionEvidence],
    changed: Sequence[str], *, unit_dirs: Sequence[str], test_globs: Sequence[str], support_globs: Sequence[str],
    same_source: Mapping[str, bool], file_of: Mapping[str, str | None],
) -> Decision:  # fmt: skip
    """The rule of the module docstring over R's stored verdict `prev`, this round's `criteria` and `trace`, the paths
    that `changed` between the two heads, `same_source` (criterion id -> its source file has the same blob at both
    heads; no answer is no) and `file_of` (test id -> the file that holds it; None or no answer: not found)."""
    from_round, from_head = int(prev.get("round") or 0), str(prev.get("head_sha") or "")

    def none(reason: str, paths: Sequence[str] = ()) -> Decision:
        return Decision(from_round, from_head, {}, reason, tuple(paths))

    try:
        then = _then(prev)
    except (KeyError, TypeError, AttributeError):
        return none("the stored trace of the earlier round could not be read")
    if offending := [p for p in changed if not (_in_family(p, unit_dirs) or _is_test(p, test_globs, support_globs))]:
        return none(NON_TEST, offending[:MAX_LISTED_PATHS])  # condition 3
    moved = set(changed)
    verdicts = _verdicts(prev)
    now = {e.criterion: e for e in trace}
    carried: dict[str, dict[str, Any]] = {}
    for c in criteria:
        found = verdicts.get(c.id)
        if found is None or found[0].verdict != "pass":  # condition 1: only a pass is carried
            continue
        if not same_source.get(c.id, False):  # condition 2
            continue
        item = now.get(c.id)
        tests = item.tests if item is not None else ()
        candidates = item.capped if item is not None else ()
        before, before_capped = then.get(c.id, (frozenset(), frozenset()))
        now_ids = {t.id for t in tests}
        if not now_ids <= before or any(t.status != "passed" for t in tests):  # condition 5
            continue
        traced = {*before, *before_capped, *now_ids, *(t.id for t in candidates)}
        files = [file_of.get(t) for t in traced]
        if any(f is None for f in files) or moved & {f for f in files if f}:  # condition 4
            continue
        rows = _adequacy(prev, c.id, before | before_capped)
        if rows is None:
            continue
        carried[c.id] = {"round": from_round, "head": from_head, "verdict": dict(found[1]), "adequacy": rows}
    return Decision(from_round, from_head, carried, "" if carried else NONE_QUALIFIED)


def apply_carried(
    trace: Sequence[CriterionEvidence], carried: Mapping[str, Mapping[str, Any]], *, cap: int
) -> list[CriterionEvidence]:
    """The trace with the carried criteria's test-adequacy rows applied as `judge_body` applies the judge's: a test it
    called inadequate stops being evidence (`apply_adequacy`), then a candidate over the cap that an adequate row names
    for a carried pass counts (`count_named`). A row of no criterion applies to its carried criterion only, never to
    the tests of a criterion that was not carried."""
    reviewed: list[tuple[str, str, bool]] = []
    named: set[tuple[str, str]] = set()
    rejected: set[tuple[str, str]] = set()
    for cid, entry in carried.items():
        for raw in entry.get("adequacy") or ():
            row = TestAdequacy.model_validate(raw)
            reviewed.append((row.test, cid, row.adequate))
            if not row.adequate:
                rejected.add((row.test, cid))
            elif row.criterion and not row.reason.strip().lower().startswith(NOT_IN_PART):
                named.add((row.test, row.criterion))
    if not carried:
        return list(trace)
    return count_named(apply_adequacy(trace, reviewed), frozenset(carried), named, rejected, cap=cap)


def carried_verdicts(judge_carried: Mapping[str, Any]) -> dict[str, tuple[CriterionVerdict, int, str]]:
    """criterion -> (the verdict, R's round, R's head) of a stored `judge_carried`. A row that does not parse, or is
    not a `pass`, is left out (only a pass is carried)."""
    found: dict[str, tuple[CriterionVerdict, int, str]] = {}
    for cid, entry in judge_carried.items():
        try:
            verdict = CriterionVerdict.model_validate(entry["verdict"])
            found[str(cid)] = (verdict, int(entry["round"]), str(entry["head"]))
        except (KeyError, TypeError, ValueError, ValidationError):
            continue
    return {cid: item for cid, item in found.items() if item[0].verdict == "pass"}


def carry_over(
    git: Git, *, unit_dir: Path, unit_rel: str, unit_dirs: Sequence[str], round_no: int, head: str,
    criteria: Sequence[Criterion], trace: Sequence[CriterionEvidence], test_globs: Sequence[str],
    support_globs: Sequence[str],
) -> Decision:  # fmt: skip
    """`decide` over the facts of the repository: R is `source_round`, the changed paths are `git diff --name-only`
    between R's head and `head`, the blobs of each criterion's source file (`unit_rel/<source_path>`) are compared
    at both, and a test id is placed in the files of the head tree. Any failure to read (no such round, an R head that
    is not a commit of this repository, a git error) carries nothing and says why."""
    found = source_round(unit_dir, round_no)
    if found is None:
        return Decision(None, "", {}, "no earlier round has a judge verdict")
    n, prev = found
    sha = prev.get("head_sha")
    try:
        if not isinstance(sha, str) or not _COMMIT.fullmatch(sha):
            raise ValueError("head_sha is not a commit id")
        git.run("rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}")
        raw = git.run_bytes("diff", "--name-only", "-z", "--no-renames", sha, head)
        changed = [p.decode("utf-8", "replace") for p in raw.split(b"\0") if p]
        sources = {c.id: f"{unit_rel.rstrip('/')}/{c.source_path}" for c in criteria}
        paths = sorted(set(sources.values()))
        before, after = blob_ids(git, sha, paths), blob_ids(git, head, paths)
        same = {cid: path in before and before[path] == after.get(path) for cid, path in sources.items()}
        tree = [
            p
            for p in git.run_bytes("ls-tree", "-r", "--name-only", "-z", head).decode("utf-8", "replace").split("\0")
            if p
        ]
        ids = {t.id for e in trace for t in (*e.tests, *e.capped)}
        for entry in prev.get("trace") or ():
            ids |= {str(t["id"]) for t in (*entry["tests"], *(entry.get("capped") or ()))}
        files = {i: file_of_id(i, tree, set(changed)) for i in ids}
        return decide(
            {**prev, "round": n}, criteria, trace, changed, unit_dirs=unit_dirs, test_globs=test_globs,
            support_globs=support_globs, same_source=same, file_of=files,
        )  # fmt: skip
    except (GitError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return Decision(
            n, sha if isinstance(sha, str) else "", {}, f"the earlier round could not be read ({type(exc).__name__})"
        )
