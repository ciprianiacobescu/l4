"""What a `merged` unit's feedback needs next (L4-FBK-010; design D11): the follow-up units that exist, and which of the
parent's items are still to be taken.

Nothing here writes. A follow-up `<parent>-followup-<n>` is found from what git holds, whatever became of its branch:
the unit branches `origin/<prefix><fw>/<parent>-followup-*` (an open one lives only there) and the folders on the base
(a merged one). Its marker `.l4/followup.json` names the parent and the items it took with their content hashes; both
the number of the next follow-up and "this item is already taken" come from the markers, so an archived OpenSpec parent
(no lock ref, no folder under `changes/`) needs no record of its own. A marker is believed only when the follow-up's
name and the parent it names agree.
"""

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from l4.config.schema import L4Config
from l4.specs.base import Framework, parse_unit_id
from l4.specs.feedback import FEEDBACK_FILENAME, MAX_FEEDBACK_BYTES, FeedbackFile, FeedbackItem, content_sha256
from l4.specs.followup import MARKER_PATH, MAX_MARKER_BYTES, parse_follow_up_marker, split_follow_up_name
from l4.state.fold import FeedbackState, UnitState
from l4.vcs.git import Git
from l4.vcs.tree import regular_blobs
from l4.verifier.feedback import scan_feedback

_DATED = re.compile(r"^\d{4}-\d\d-\d\d-(?P<name>.+)$")
REMOTE = "origin"


@dataclass(frozen=True)
class KnownFollowUp:
    name: str  # `<parent>-followup-<n>`
    framework: Framework
    parent_name: str
    n: int
    items: tuple[tuple[str, str], ...]  # (item id, sha256) it took
    on_base: bool  # its folder is on the base branch: it merged
    branch: str | None  # the unit branch, when `origin` has it

    @property
    def id(self) -> str:
        return f"{self.framework.value}:{self.name}"

    @property
    def parent(self) -> str:
        return f"{self.framework.value}:{self.parent_name}"


@dataclass(frozen=True)
class FollowUpOffer:
    """For a `merged` unit: the items a follow-up should take, and the follow-up that is open, if any."""

    items: tuple[FeedbackItem, ...] = ()  # takeable, and no follow-up has taken that content
    open: str | None = None  # the open follow-up's unit name
    n: int = 1  # the ordinal of the next follow-up


def base_ref(cfg: L4Config) -> str:
    return f"refs/remotes/{REMOTE}/{cfg.forge.base_branch}"


def spec_folder(cfg: L4Config, framework: Framework, name: str) -> str:
    """Where a unit's folder is, relative to the repository (not archived)."""
    if framework is Framework.KIRO:
        return f"{PurePosixPath(cfg.spec.kiro.root)}/{name}"
    return f"{PurePosixPath(cfg.spec.openspec.root)}/changes/{name}"


def _subdirs(git: Git, ref: str, path: str) -> list[str]:
    out = git.run_bytes("ls-tree", "-d", "--name-only", "-z", ref, "--", f"{path}/", check=False)
    return [PurePosixPath(p.decode("utf-8", "surrogateescape")).name for p in out.split(b"\0") if p]


def _blob(git: Git, ref: str, path: str, limit: int) -> bytes | None:
    found = regular_blobs(git, ref, path, limit)
    return git.run_bytes("cat-file", "blob", found[0].oid) if found else None


def read_feedback_at(git: Git, ref: str, folder: str) -> FeedbackFile | None:
    raw = _blob(git, ref, f"{folder}/{FEEDBACK_FILENAME}", MAX_FEEDBACK_BYTES)
    return FeedbackFile.parse(raw) if raw is not None else None


def archive_folders(git: Git, cfg: L4Config) -> dict[str, str]:
    """name -> the newest `openspec/changes/archive/<date>-<name>` on the base branch."""
    ref = base_ref(cfg)
    if git.rev_parse(ref) is None:
        return {}
    archive = f"{PurePosixPath(cfg.spec.openspec.root)}/changes/archive"
    found: dict[str, str] = {}
    for dirname in sorted(_subdirs(git, ref, archive)):
        if (m := _DATED.match(dirname)) is not None:
            found[m.group("name")] = f"{archive}/{dirname}"  # sorted: the newest date wins
    return found


def known_follow_ups(git: Git, cfg: L4Config) -> list[KnownFollowUp]:
    """Every follow-up the base branch or `origin` holds, merged or not, sorted by name."""
    ref = base_ref(cfg)
    on_base: dict[tuple[Framework, str], str] = {}  # (framework, name) -> its folder
    if git.rev_parse(ref) is not None:
        for name in _subdirs(git, ref, str(PurePosixPath(cfg.spec.kiro.root))):
            on_base[(Framework.KIRO, name)] = spec_folder(cfg, Framework.KIRO, name)
        changes = f"{PurePosixPath(cfg.spec.openspec.root)}/changes"
        for name in _subdirs(git, ref, changes):
            on_base[(Framework.OPENSPEC, name)] = f"{changes}/{name}"
        for name, folder in archive_folders(git, cfg).items():
            on_base.setdefault((Framework.OPENSPEC, name), folder)
    prefix = f"refs/remotes/{REMOTE}/{cfg.forge.branch_prefix}"
    branches: dict[tuple[Framework, str], str] = {}
    for line in git.run("for-each-ref", "--format=%(refname)", prefix, check=False).stdout.splitlines():
        rest = line.removeprefix(f"refs/remotes/{REMOTE}/")
        framework_name, _, name = rest.removeprefix(cfg.forge.branch_prefix).partition("/")
        try:
            framework, _ = parse_unit_id(f"{framework_name}:{name}")
        except ValueError:
            continue
        branches[(framework, name)] = rest
    found = []
    for framework, name in sorted({*on_base, *branches}, key=lambda k: (k[0].value, k[1])):
        split = split_follow_up_name(name)
        if split is None:
            continue
        folder = on_base.get((framework, name)) or spec_folder(cfg, framework, name)
        source = ref if (framework, name) in on_base else f"refs/remotes/{REMOTE}/{branches.get((framework, name), '')}"
        raw = _blob(git, source, "/".join((folder, *MARKER_PATH)), MAX_MARKER_BYTES)
        marker = parse_follow_up_marker(raw) if raw is not None else None
        if marker is None or marker.parent != f"{framework.value}:{split[0]}":
            continue  # a folder that only looks like a follow-up
        found.append(
            KnownFollowUp(
                name, framework, split[0], split[1], marker.items, (framework, name) in on_base,
                branches.get((framework, name)),
            )
        )  # fmt: skip
    return found


def follow_ups_of(known: list[KnownFollowUp], parent_id: str) -> list[KnownFollowUp]:
    return sorted((k for k in known if k.parent == parent_id), key=lambda k: k.n)


def next_ordinal(follows: list[KnownFollowUp]) -> int:
    """1 + the follow-ups of the parent, open or not; never a number that is taken."""
    taken = {k.n for k in follows}
    n = len(follows) + 1
    while n in taken:
        n += 1
    return n


def taken_by_follow_ups(state: UnitState, file: FeedbackFile | None, follows: list[KnownFollowUp]) -> UnitState:
    """The parent's state with the takes of its follow-ups (`round` 0, `fix_unit` the follow-up): they are written to
    the follow-up's ledger, so the parent's own fold knows nothing of them. The latest follow-up wins over an earlier
    one, and over the parent's own entry when it took the content the file has now. An edit after the take reads as
    an edit (D7), and the item is takeable again."""
    now = {i.id: content_sha256(i) for i in file.items} if file is not None else {}
    overlay: dict[str, FeedbackState] = {}
    for k in follows:  # by ordinal: the latest take of an item stands
        for fid, sha in k.items:
            overlay[fid] = FeedbackState(status="taken", sha256=sha, round=0, fix_unit=k.name)
    merged = dict(state.feedback)
    for fid, took in overlay.items():
        if fid not in merged or now.get(fid) == took.sha256:
            merged[fid] = took
    return state.model_copy(update={"feedback": merged})


def offer_for(
    file: FeedbackFile | None,
    state: UnitState,
    follows: list[KnownFollowUp],
    open_names: set[str],
    released: set[str] = frozenset(),  # type: ignore[assignment]
) -> FollowUpOffer:
    """The takeable items of the parent's file, less those a follow-up has taken (same id, same content hash), and the
    open follow-up. `open_names`: the follow-ups whose unit is neither merged nor abandoned. `released`: the abandoned
    ones, which keep their number but no longer hold their items."""
    took = {pair for k in follows if k.name not in released for pair in k.items}
    scan = scan_feedback(file, state)
    items = tuple(i for i in scan.takeable if (i.id, content_sha256(i)) not in took)
    opened = next((k.name for k in follows if k.name in open_names and not k.on_base), None)
    return FollowUpOffer(items, opened, next_ordinal(follows))
