"""`l4 restart --unit ID --reason TEXT [--no-run]` (L4-OPS-004, L4-OPS-002, SCN-OPS-08, SCN-OPS-09): the unit starts
over and the old work is kept as a ref (design D4). The seven steps, in this order; step 1 writes nothing:

1. **Refuse** an unstarted, `merged` or locked unit (the unit's flock on this machine), and a run with no forge token.
   Any other phase, `abandoned` included, is accepted.
2. **Keep the old work.** The old branch head goes to `refs/l4/attempts/<fw>/<name>/<n>`, where `<n>` is one more than
   the highest attempt on `origin`; the lock ref `refs/l4/locks/<fw>/<name>`, if there is one, moves to
   `refs/l4/attempts/<fw>/<name>/<n>-locks`. The harness never deletes a ref under `refs/l4/attempts/`.
3. **Build the new folder** in a worktree cut from the base head: the old branch's unit folder, without `.l4/` and
   `verification.md`, with `questions.md` and `feedback.md` kept, and every task box set to its state on the base branch
   (`[ ]` for a task the base lacks). Fix-unit folders (`<name>-fix-*`) are siblings of the unit folder, so they are
   not copied.
4. **Create the new branch**: one commit `chore(<name>): restart, attempt <n> [skip ci]` with the folder and a ledger
   file (`run.started`, `unit.restarted{attempt, previous_head, reason, by, signal}`, `run.finished`). The fold reads
   `unit.restarted` as the first event of the unit: no phase, so the planner says `implement`.
5. **Replace the branch** with `--force-with-lease=<branch>:<old head>`: a person's push since step 2 makes the restart
   fail with `the branch moved: run l4 restart again`, and nothing else is undone (the attempts ref is history).
6. **Close the old merge request** with a comment that names the attempts ref and the reason.
7. **Start a run** (L4-OPS-002): the command's job, not this function's (`run_restart`, `start_run_line`).

A deleted unit branch has no old head: step 2 keeps only the lock ref, and step 5 asks for a branch that does not exist.
"""

import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import click

from l4.config.defaults import cache_root
from l4.config.redaction import load_app_config
from l4.config.schema import L4Config
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.forge.base import Forge, ForgeError, ForgeUnavailable, fetch_auth_config, make_forge
from l4.forge.gitlab import push_auth_config
from l4.forge.urls import app_forge_urls, origin_url
from l4.orchestrator import UnitOutcome
from l4.outcome import CommandResult
from l4.specs.base import SpecProvider, UnitRef
from l4.specs.providers import providers_for
from l4.state.environment import run_environment
from l4.state.ledger import LedgerWriter
from l4.state.lifecycle import Phase
from l4.state.retry import fetch_unit_refs, start_run_line
from l4.state.status import TASK_PARSERS, load_snapshot, refresh_refs, select_runnable
from l4.vcs.errors import GitError
from l4.vcs.git import Git
from l4.vcs.locks import Busy, LocalFileLease
from l4.vcs.names import UnitNames
from l4.vcs.push import ATTEMPT_REF_PREFIX, PushRejected
from l4.vcs.trailers import CommitTrailers
from l4.vcs.worktree import WorktreeManager

log = logging.getLogger("l4.restart")

TASKS_FILENAME = "tasks.md"
_DROPPED = ("verification.md", ".l4")  # the harness's files of the unit folder: the new start has none of the old
_NUMBER = re.compile(r"/(\d+)(?:-locks)?$")
_MAX_FILE_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class RestartResult:
    attempt: int  # the number of the attempts ref: the 1-based count of restarts of this unit on `origin`
    previous_head: str | None  # the old branch head; None when the branch was deleted
    attempt_ref: str | None  # `refs/l4/attempts/<fw>/<name>/<n>`; None with no old head
    branch_head: str  # the new branch head, as pushed
    closed_pr: int | None  # the number of the merge request that was closed; None when none was open
    phase_before: str | None = None  # the phase the old ledger said


def restart_unit(
    app: AppContext,
    cfg: L4Config,
    git: Git,
    provider: SpecProvider,
    ref: UnitRef,
    *,
    reason: str,
    signal: str | None = None,
    by: str | None = None,
) -> RestartResult:
    """The restart of one unit, steps 1 to 6 of the module text; no run is started. `L4Exit(USAGE_ERROR)` for a refusal,
    `L4Exit(INTERNAL_ERROR, "the branch moved: run l4 restart again")` for a lost lease."""
    names = UnitNames.for_unit(
        ref.id, branch_prefix=cfg.forge.branch_prefix, cache=cache_root(app.environ, repo=app.repo)
    )
    config = push_auth_config(cfg, app.environ, origin_url(app.repo, app.environ))
    state = load_snapshot(provider, git, ref, branch_prefix=cfg.forge.branch_prefix).state
    forge = _forge(cfg, app)
    _refuse_unstarted_or_merged(ref, state.phase, names, git, forge)
    lease = LocalFileLease(names.flock_path, unit=ref.id, run_id=app.run_id, job=app.environ.get("CI_JOB_ID"))
    try:
        lease.acquire()
    except Busy:
        raise L4Exit(ExitCode.USAGE_ERROR, f"restart: {ref.id} is locked by another run on this machine") from None
    try:
        if isinstance(forge, ForgeUnavailable):
            raise L4Exit(
                ExitCode.USAGE_ERROR, f"restart: it closes the merge request, which needs a forge token: {forge}"
            )
        return _restart(app, cfg, git, provider, ref, names, config, forge, state.phase, state.iteration, reason,
                        signal, by)  # fmt: skip
    finally:
        lease.release()


def _forge(cfg: L4Config, app: AppContext) -> Forge | ForgeUnavailable:
    try:
        return make_forge(cfg, app.environ, repo=app.repo)
    except ForgeUnavailable as exc:
        return exc  # refused after the other checks, so that "unstarted" and "locked" are said first


def _refuse_unstarted_or_merged(
    ref: UnitRef, phase: str | None, names: UnitNames, git: Git, forge: Forge | ForgeUnavailable
) -> None:
    if phase == Phase.MERGED.value:
        raise L4Exit(ExitCode.USAGE_ERROR, f"restart: {ref.id} is merged: a merged change gets a follow-up unit")
    if phase is not None or git.rev_parse(f"refs/remotes/origin/{names.branch}") is not None:
        return
    # no ledger and no branch: a deleted branch still has its merge request (or an earlier attempt) to show it started
    if not isinstance(forge, ForgeUnavailable) and any(
        pr.head_branch == names.branch for pr in forge.list_prs(names.branch)
    ):
        return
    raise L4Exit(ExitCode.USAGE_ERROR, f"restart: {ref.id} is not started: the next run starts it")


def _restart(
    app: AppContext, cfg: L4Config, git: Git, provider: SpecProvider, ref: UnitRef, names: UnitNames,
    config: tuple[tuple[str, str], ...], forge: Forge, phase: str | None, iteration: int,
    reason: str, signal: str | None, by: str | None,
) -> RestartResult:  # fmt: skip
    branch = names.branch
    attempts = f"{ATTEMPT_REF_PREFIX}{ref.framework.value}/{ref.name}"
    old_pr = forge.find_pr(branch)  # read before anything is written
    # step 2: the old work becomes a ref
    attempt = 1 + max((int(m.group(1)) for r in _remote_refs(git, config, f"{attempts}/*") if (m := _NUMBER.search(r))),
                      default=0)  # fmt: skip
    old_head = next(iter(_remote_refs(git, config, f"refs/heads/{branch}").values()), None)
    attempt_ref = f"{attempts}/{attempt}" if old_head else None
    if old_head and attempt_ref:
        git.fetch("origin", refspecs=(f"+refs/heads/{branch}:refs/remotes/origin/{branch}",), config=config)
        # a plain push, never `+`: the ref is new (max + 1), and one that exists makes git refuse instead of moving it
        git.push("origin", [f"{old_head}:{attempt_ref}"], config=config)
    if lock := next(iter(_remote_refs(git, config, names.lock_ref).values()), None):
        git.fetch("origin", refspecs=(f"+{names.lock_ref}:{names.lock_ref}",), config=config)
        try:
            git.retire_lock_ref("origin", lock, names.lock_ref, f"{attempts}/{attempt}-locks", config=config)
        except PushRejected:
            raise L4Exit(ExitCode.INTERNAL_ERROR, "the lock moved: run l4 restart again") from None
        git.run("update-ref", "-d", names.lock_ref, check=False)
    # steps 3 and 4: the new folder and its one commit, in a worktree cut from the base head
    tree = WorktreeManager(
        git, base_branch=cfg.forge.base_branch, branch_prefix=cfg.forge.branch_prefix,
        fetch_config=fetch_auth_config(cfg, app.environ, origin_url(app.repo, app.environ)),
    ).ensure_from_base(branch, names.worktree)  # fmt: skip
    inside = git.at(tree.path)
    relative = provider.unit_dir(ref).resolve().relative_to(app.repo.resolve()).as_posix()
    unit_dir = tree.path / relative
    _build_folder(git, ref, old_head, relative, unit_dir, f"refs/remotes/origin/{cfg.forge.base_branch}")
    writer = LedgerWriter.open(
        unit_dir, ref.id, app.run_id, redactor=app.redactor, command="restart", branch=branch, base=tree.head,
        source=tree.source, iteration=iteration + 1, file_filter=app_forge_urls(app, cfg).scrub,
        **run_environment(app.environ),
    )  # fmt: skip
    extra = {k: v for k, v in (("by", by), ("signal", signal)) if v}
    writer.append(
        "unit.restarted", attempt=attempt, previous_head=old_head, attempt_ref=attempt_ref, reason=reason[:300], **extra
    )
    writer.finish(0)
    inside.run("add", "-A", "--", relative)
    trailers = CommitTrailers(unit=ref.id, run_id=app.run_id, iteration=iteration + 1, phase="intake")
    inside.commit(f"chore({ref.name}): restart, attempt {attempt} [skip ci]", trailers)
    # step 5: the lease on the old head
    try:
        inside.replace_branch("origin", branch, old_head or "", config=config)
    except PushRejected:
        raise L4Exit(ExitCode.INTERNAL_ERROR, "the branch moved: run l4 restart again") from None
    head = inside.run("rev-parse", "HEAD").stdout.strip()
    git.run("update-ref", f"refs/remotes/origin/{branch}", head)
    # step 6: the old merge request
    closed = _close(app, forge, old_pr.number if old_pr else None, attempt_ref, old_head, reason)
    return RestartResult(attempt, old_head, attempt_ref, head, closed, phase)


def _remote_refs(git: Git, config: tuple[tuple[str, str], ...], pattern: str) -> dict[str, str]:
    """`ref -> sha` of the refs on `origin` that match `pattern` (git's glob)."""
    out = git.run("ls-remote", "origin", pattern, config=config).stdout
    return {fields[1]: fields[0] for line in out.splitlines() if len(fields := line.split()) == 2}


def _folder_files(git: Git, ref: str, relative: str) -> dict[str, tuple[bytes, bool]]:
    """The regular files under `relative` at `ref` (path inside the folder -> bytes, executable). A symlink, a submodule
    and an oversized blob are not something the harness wrote; they are left out."""
    listing = git.run_bytes("ls-tree", "-r", "-z", "-l", ref, "--", f"{relative}/", check=False)
    files: dict[str, tuple[bytes, bool]] = {}
    for record in filter(None, listing.split(b"\0")):
        meta, _, name = record.partition(b"\t")
        fields = meta.split()
        if len(fields) != 4 or fields[0] not in (b"100644", b"100755") or int(fields[3]) > _MAX_FILE_BYTES:
            continue
        inside = name.decode("utf-8", "surrogateescape").removeprefix(f"{relative}/")
        files[inside] = (git.run_bytes("cat-file", "blob", fields[2].decode("ascii")), fields[0] == b"100755")
    return files


def _kept(path: str) -> bool:
    return path.split("/", 1)[0] not in _DROPPED


def _build_folder(git: Git, ref: UnitRef, old_head: str | None, relative: str, unit_dir: Path, base_ref: str) -> None:
    """Step 3: the old branch's unit folder replaces the base's in the new worktree (no old head: the base's stays),
    then the task boxes are set to the base's."""
    files = _folder_files(git, old_head, relative) if old_head else {}
    if files:
        shutil.rmtree(unit_dir, ignore_errors=True)
        for path, (data, executable) in files.items():
            if not _kept(path):
                continue
            target = unit_dir / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(0o755 if executable else 0o644)
    tasks = unit_dir / TASKS_FILENAME
    if tasks.is_file() and not tasks.is_symlink():
        base = git.run_bytes("show", f"{base_ref}:{relative}/{TASKS_FILENAME}", check=False)
        tasks.write_bytes(reset_boxes(tasks.read_bytes(), base, ref))


def reset_boxes(current: bytes, base: bytes, ref: UnitRef) -> bytes:
    """`current` with each task box set to its state in `base`, the task matched by its key (its number, else its line);
    a task that `base` lacks is `[ ]`. Both task formats go through the provider's own parser, and only the one byte
    between the brackets changes (the optional marker of a Kiro task stays). A box whose interior is not one character
    has no offset to write and is left as it is."""
    parse = TASK_PARSERS[ref.framework]
    done = {task.key for task in parse(base) if task.done} if base else set()
    out = bytearray(current)
    for task in parse(current):
        if task.marker_offset is not None and task.key not in done and task.marker_char != " ":
            out[task.marker_offset] = ord(" ")
    return bytes(out)


def _close(
    app: AppContext, forge: Forge, number: int | None, attempt_ref: str | None, old_head: str | None, reason: str
) -> int | None:
    """Step 6. The branch is already replaced, so a forge that cannot close the merge request is an error line, not a
    failed restart: running it again would make a second attempt for nothing."""
    if number is None:
        return None
    kept = f"The old work is kept at `{attempt_ref}` ({old_head[:10] if old_head else ''})." if attempt_ref else (
        "The unit branch was gone, so no old work was kept."
    )  # fmt: skip
    comment = f"Closed by `l4 restart`: the unit starts over on a new branch. {kept} Reason: {reason[:300]}"
    try:
        forge.close_pr(number, app.redactor.redact_text(comment))
    except (ForgeError, GitError) as exc:
        log.error("could not close merge request %s: %s; close it by hand", number, app.redactor.redact_text(str(exc)))
        return None
    return number


def run_restart(app: AppContext, *, unit: str, reason: str, no_run: bool = False) -> CommandResult:
    if not reason.strip():
        raise L4Exit(ExitCode.USAGE_ERROR, "restart: --reason must say why")
    app, cfg = load_app_config(app)
    git = Git(app.repo, environ=app.environ)
    fetch_unit_refs(app, cfg, git)
    refresh_refs(app, cfg, git)
    provider, ref = select_runnable(cfg, git, list(providers_for(cfg, app.repo, app.environ)), unit)
    result = restart_unit(app, cfg, git, provider, ref, reason=reason)
    kept = f"the old work is kept at {result.attempt_ref}" if result.attempt_ref else "there was no branch to keep"
    closed = f", merge request {result.closed_pr} is closed" if result.closed_pr else ""
    click.echo(app.redactor.redact_text(f"{unit} restarted attempt {result.attempt}: {kept}{closed}"))
    if not no_run:
        click.echo(app.redactor.redact_text(start_run_line(app, cfg)))
    outcome = UnitOutcome(unit=unit, phase_before=result.phase_before or "none", phase_after="none")
    return CommandResult(ExitCode.OK, [outcome])
