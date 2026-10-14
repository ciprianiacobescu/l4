"""The four `l4 kg` handlers (L4-KG-002, L4-KG-009, L4-KG-011, design D1, D2, D9): `run_kg_build`, `run_kg_report`,
`run_kg_why` and `run_kg_propose`. `commands.py` holds their handler strings; nothing else imports this module
(L4-KG-001).

Each handler reads one repository only. It loads the config, asks `store.index_dir` for the folder under the cache root
(a cache root inside the repository exits 2 there, before anything is written, SCN-KG-05), and runs git through the
read-only `Git` of this module. `report`, `why` and `propose` build the index first when `read_index` says `missing`,
`incomplete` or `stale`, and say `index rebuilt (<why>)` on stderr, so that stdout holds only the report (SCN-KG-03).
`build` always builds, and prints what it read and what it skipped, never fatal (L4-KG-002).

The exit codes are the existing ones. A usage error is `L4Exit(USAGE_ERROR)`: no repository, an id of no accepted form
or not in the index, a `--min-units` below 1, a refused `--out`. Any other exception ends the command with exit 1
through `run_guarded`. A failed build changes no ref, no tracked file and no ledger: the only writes are the three
index files under the cache root, each atomic, and the manifest last, so the last complete index stays readable or the
next read finds it `incomplete` and builds again (SCN-KG-03).

`--out` names a file. A relative path is relative to the `--repo` folder (the repository root unless a subdirectory was given). A path inside the repository must be ignored by
git (`git check-ignore`), which also refuses a tracked path (SCN-KG-19); a path outside it is allowed (design D2). The
check runs before the index is built, so a refused `--out` writes nothing at all.

Everything printed or written passes `redact_text` and then `scrub_for_commit` once more (L4-KG-011, design D12): the
index is redacted already, and this keeps a later change of `report`, `why` or `propose` from leaking a value.

`report`, `why` and `propose` live in their own modules and are called through their real API:

- `report.render(nodes, edges, *, base_ref, base_sha, base_date, skipped, warnings, min_units, redactor) -> str`;
  the base date is read here with the read-only `git log -1 --format=%cI <base sha>`;
- `why.explain(nodes, edges, target, *, redactor) -> str`;
- `propose.propose(nodes, edges, *, repo, git, min_units, dry_run, today, redactor) -> ProposeResult`, whose `render()`
  is printed (it writes the inbox files unless `dry_run`).
"""

import dataclasses
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import click

from l4.config.redaction import attach_forge_urls, load_app_config
from l4.config.schema import L4Config
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.fsutil import atomic_write_bytes
from l4.kg import propose as propose_module
from l4.kg import report as report_module
from l4.kg import why as why_module
from l4.kg.extract import extract
from l4.kg.model import Edge, Node
from l4.kg.sources import FETCH_ATTEMPTS, REMOTE, collect, ref_shas
from l4.kg.store import IndexState, Manifest, index_dir, read_index, write_index
from l4.vcs.git import Git, GitError

DEFAULT_MIN_UNITS = 2
ID_FORMS = (
    "a unit id (openspec:<name> or kiro:<name>)",
    "a finding id (F-<8 hex>)",
    "a lesson id (L-<8 hex>)",
    "a run id (r-<stamp>-<suffix>)",
    "a question id (<unit>#Q-<n>)",
)
_UNIT = r"(?:openspec|kiro):[^\s#@]+"
_ID_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        rf"^{_UNIT}$", r"^F-[0-9a-f]{8}$", r"^L-[0-9a-f]{8}$", r"^r-[0-9A-Za-z]+(?:-[0-9A-Za-z]+)+$",
        rf"^{_UNIT}#Q-\d+$",
    )
)  # fmt: skip
_REASONS = {
    "missing": "no index",
    "incomplete": "index incomplete",
    "stale": "refs moved",
}


@dataclass
class Graph:
    """The index as the three handlers use it: the records and the manifest they came from."""

    nodes: list[Node]
    edges: list[Edge]
    manifest: Manifest
    warnings: tuple[str, ...] = ()  # of the build this run made; empty when the index was read


def _say(app: AppContext, text: str, *, err: bool = False) -> None:
    click.echo(app.redactor.scrub_for_commit(app.redactor.redact_text(text)), err=err)


def _git(app: AppContext) -> Git:
    """The read-only git of every handler. `GIT_NO_LAZY_FETCH=1` keeps a partial clone from fetching a blob that
    `cat-file` asks for (review #1; L4-KG-001): the object is missing, the unit is skipped, nothing is fetched."""
    return Git(app.repo, environ={**app.environ, "GIT_NO_LAZY_FETCH": "1"})


def _prepare(app: AppContext) -> tuple[AppContext, L4Config, Git, Path]:
    """Config, the read-only git and the index folder, for the repository root (`git rev-parse --show-toplevel`, so
    that a command started in a subdirectory reads the whole repository and its guards see the real root, review #3).
    A cache root inside the repository, a config error and a folder that is no repository all exit 2 here, before
    anything is read or written."""
    top = _toplevel(app)
    if top is None:
        raise L4Exit(ExitCode.USAGE_ERROR, f"kg: {app.repo} is not a git repository")
    app = dataclasses.replace(app, repo=top)
    app, cfg = load_app_config(app)
    attach_forge_urls(app, cfg)  # L4-KG-011: the forge host is scrubbed from the index and from everything shown
    folder = index_dir(app)
    return app, cfg, _git(app), folder


def _toplevel(app: AppContext) -> Path | None:
    """The root of the work tree that holds `app.repo`; `app.repo` itself for a bare repository; None for no
    repository."""
    git = _git(app)
    try:
        done = git.run("rev-parse", "--show-toplevel", check=False)
        if done.returncode == 0 and done.stdout.strip():
            return Path(done.stdout.strip())
        return app.repo if git.run("rev-parse", "--git-dir", check=False).returncode == 0 else None
    except GitError:
        return None


def _build(app: AppContext, cfg: L4Config, git: Git, folder: Path) -> tuple[Graph, list[str], list[str]]:
    """Collect, extract and write the index. Returns the graph just built, the warnings and the attempt refs that
    are not local. The graph is read back from the folder when the refs did not move meanwhile."""
    collected = collect(git, cfg)
    extracted = extract(collected, app.redactor, git=git)
    manifest = write_index(folder, extracted.nodes, extracted.edges, refs=collected.refs, skipped=extracted.skipped)
    state = read_index(folder, collected.refs)
    if state.status == "ok" and state.manifest is not None:
        graph = Graph(state.nodes, state.edges, state.manifest, tuple(extracted.warnings))
    else:  # the index is fine on disk; this run keeps what it built
        graph = Graph(list(extracted.nodes), list(extracted.edges), manifest, tuple(extracted.warnings))
    return graph, extracted.warnings, collected.not_local


def _show_warnings(app: AppContext, warnings: Sequence[str]) -> None:
    for warning in warnings:
        _say(app, f"warning: {warning}", err=True)


def _load(
    app: AppContext, precheck: Callable[[AppContext, Git], None] | None = None
) -> tuple[AppContext, L4Config, Git, Graph]:
    """The index for `report`, `why` and `propose`: read it, or build it first and say so on stderr. `precheck` runs
    before anything is built, so that a refused argument writes nothing."""
    app, cfg, git, folder = _prepare(app)
    if precheck is not None:
        precheck(app, git)
    state: IndexState = read_index(folder, ref_shas(git, cfg))
    if state.status == "ok" and state.manifest is not None:
        return app, cfg, git, Graph(state.nodes, state.edges, state.manifest)
    graph, warnings, _ = _build(app, cfg, git, folder)
    _say(app, f"index rebuilt ({_REASONS[state.status]})", err=True)
    _show_warnings(app, warnings)
    return app, cfg, git, graph


def _count(counts: dict[str, dict[str, int]], kind: str) -> int:
    return sum(counts.get(kind, {}).values())


def run_kg_build(app: AppContext) -> ExitCode:
    """`l4 kg build`: read the committed records, write the index, say what was read and what was skipped."""
    app, cfg, git, folder = _prepare(app)
    graph, warnings, not_local = _build(app, cfg, git, folder)
    manifest = graph.manifest
    _say(
        app,
        f"index built: {_count(manifest.counts, 'nodes')} nodes, {_count(manifest.counts, 'edges')} edges "
        f"from {len(manifest.refs)} refs (n = {len(manifest.refs)})",
    )
    skipped = ", ".join(f"{reason} {n}" for reason, n in sorted(manifest.skipped.items()))
    _say(app, f"skipped: {skipped}" if skipped else "skipped: none (n = 0)")
    if not_local:
        _say(app, f"attempts not local: {len(not_local)} (n = {len(not_local)}); to read them run: {FETCH_ATTEMPTS}")
    _show_warnings(app, warnings)
    return ExitCode.OK


def _check_out(app: AppContext, git: Git, out: Path | str, start: Path) -> Path:
    """The file `--out` names, after the rule of design D2: inside the repository only when git ignores it. A
    relative path is relative to the folder the command was given (`start`, the `--repo` folder), and the rule is
    applied against the repository root, so a subdirectory cannot reach a not-ignored path (review #3)."""
    given = str(out)
    path = Path(out)
    path = (path if path.is_absolute() else start / path).resolve()
    if path.is_dir():
        raise L4Exit(ExitCode.USAGE_ERROR, f"kg: --out {given} is a folder: name a file")
    repo = app.repo.resolve()
    if path.is_relative_to(repo):
        relative = path.relative_to(repo).as_posix()
        if git.run("check-ignore", "-q", "--", relative, check=False).returncode != 0:
            raise L4Exit(
                ExitCode.USAGE_ERROR,
                f"{given} is not git-ignored: use .l4-out/kg/ or a path outside the repository",
            )
    return path


def run_kg_report(app: AppContext, *, out: Path | str | None = None, min_units: int = DEFAULT_MIN_UNITS) -> ExitCode:
    """`l4 kg report [--out PATH] [--min-units N]`: the markdown report, on stdout or in the file."""
    _check_min_units(min_units)
    targets: list[Path] = []
    start = app.repo

    def precheck(checked: AppContext, git: Git) -> None:
        if out is not None:
            targets.append(_check_out(checked, git, out, start))

    app, cfg, git, graph = _load(app, precheck)
    target = targets[0] if targets else None
    base_ref, base_sha, base_date = _base_facts(cfg, git, graph)
    text = app.redactor.scrub_for_commit(app.redactor.redact_text(
        report_module.render(
            graph.nodes, graph.edges, base_ref=base_ref, base_sha=base_sha, base_date=base_date,
            skipped=graph.manifest.skipped, warnings=graph.warnings, min_units=min_units, redactor=app.redactor,
        )
    ))  # fmt: skip
    text = text if text.endswith("\n") else text + "\n"
    if target is None:
        click.echo(text, nl=False)
        return ExitCode.OK
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(target, text.encode("utf-8"))
    _say(app, f"report written to {out}")
    return ExitCode.OK


def _base_facts(cfg: L4Config, git: Git, graph: Graph) -> tuple[str, str | None, str | None]:
    """The base ref the index was read at, its commit and its commit date. The date is not in the index (L4-KG-003):
    it comes from the read-only `git log -1 --format=%cI`."""
    named = f"refs/remotes/{REMOTE}/{cfg.forge.base_branch}"
    sha = graph.manifest.refs.get(named)
    ref = named
    if sha is None:
        ref, sha = "HEAD", git.rev_parse("HEAD")
    if sha is None:
        return ref, None, None
    date = git.run("log", "-1", "--format=%cI", sha, check=False).stdout.strip()
    return ref, sha, date or None


def _check_min_units(min_units: int) -> None:
    if min_units < 1:
        raise L4Exit(ExitCode.USAGE_ERROR, f"kg: --min-units must be 1 or more, not {min_units}")


def _unknown_id(ident: str, why: str) -> L4Exit:
    forms = "; ".join(ID_FORMS)
    return L4Exit(ExitCode.USAGE_ERROR, f"kg why: {why} {ident!r}. Accepted ids: {forms}")


def run_kg_why(app: AppContext, *, id: str) -> ExitCode:  # noqa: A002 - the option name of the command
    """`l4 kg why ID`: the timeline of a unit, or the 1-hop view of a finding, lesson, run or question."""
    ident = id.strip()
    if not any(pattern.match(ident) for pattern in _ID_PATTERNS):
        raise _unknown_id(ident, "not an id of an accepted form:")
    app, _cfg, _git_, graph = _load(app)
    if ident not in {node.id for node in graph.nodes}:
        raise _unknown_id(ident, "not in the index:")
    _say(app, why_module.explain(graph.nodes, graph.edges, ident, redactor=app.redactor))
    return ExitCode.OK


def run_kg_propose(app: AppContext, *, min_units: int = DEFAULT_MIN_UNITS, dry_run: bool = False) -> ExitCode:
    """`l4 kg propose [--min-units N] [--dry-run]`: draft lessons in the inbox for a person; never a lesson."""
    _check_min_units(min_units)
    app, cfg, git, graph = _load(app)
    today = datetime.now(UTC).date()
    result = propose_module.propose(
        graph.nodes, graph.edges, repo=app.repo, git=git, min_units=min_units, dry_run=dry_run, today=today,
        redactor=app.redactor,
    )  # fmt: skip
    text = result.render().rstrip("\n")
    if text:
        _say(app, text)
    return ExitCode.OK
