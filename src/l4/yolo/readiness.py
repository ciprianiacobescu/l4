"""The readiness review of a delivery plan (design D5, requirement L4-YOLO-004, scenarios SCN-YOLO-08 and -09).

The judge role reviews each unit of a plan (its folder at a revision, its plan entry, the units it depends on) and each
batch with more than one unit (all its units' folders together). The prompt is `prompts/readiness.md`, the answer must
satisfy `schemas/readiness.schema.json`, and `review_plan` returns one `Verdict` per unit and per batch.

The call goes through the same machinery as the verifier's judge: the first usable profile of `roles.judges`
(`Factory.for_role`, probes, cool-downs, the login gate), an `AgentJudge`, and the judge's permission policy, which
allows no tool at all (stricter than read-only): everything the judge may see is in the prompt, inside `<l4:data>`
blocks, and the process runs in an empty scratch folder outside the repository, in the agent sandbox. There is no
implementer to be independent of, so the independence rule of the verifier does not apply.

Rules decide the verdict whatever the model says: an empty, unparsable or schema-invalid answer is BLOCKED with a
finding `{criterion: "schema", severity: "blocking", text: "schema_invalid: ..."}`, a blocking finding makes the
verdict at least NEEDS_REVISION, and material the size limits cut makes it at least NEEDS_REVISION with a finding that
names what was left out (R9), because the digest freezes content the judge never saw. Structural validity alone never
makes a verdict READY. A usage limit, a timeout and an error of the judge are not verdicts: `RoleLimit` or
`JudgeFailed` is raised (and `RoleUnavailable` when no judge profile can serve), so the caller can wait and nothing is
recorded for a review that did not happen (R9).

A unit is read on the revision its digest is taken on (`digest.current_unit_ref`, R3): its branch on `origin` when it
has one, else the target. File names, unit ids, batch ids and the plan's own words reach the prompt only inside
`<l4:data>` blocks, defused (R9); the `source` label of a block is escaped too.
"""

import json
import re
import shutil
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Any

from l4.agents.base import AgentAdapter, PermissionPolicy, ProbeCtx, RunRequest
from l4.agents.factory import Factory, Selected
from l4.availability.cooldown import AvailabilityStore, SystemClock
from l4.availability.errors import RoleUnavailable
from l4.config.defaults import cache_root
from l4.config.schema import L4Config
from l4.context import AppContext
from l4.implementer.prompt import data_block, defuse
from l4.implementer.tdd import RoleLimit
from l4.llm.agent_judge import JUDGE_ADAPTERS, AgentJudge, Msg, StructuredResult
from l4.proc import run_process
from l4.sandbox.base import Sandbox, SandboxSpec, expand_credential_paths, runner_tmp_paths
from l4.sandbox.env import build_agent_env
from l4.sandbox.select import select_sandbox
from l4.schemacheck import validate
from l4.vcs.git import Git
from l4.yolo.digest import current_unit_ref, is_excluded, normalise_tasks, unit_digest
from l4.yolo.model import PROFILE_NONE, Plan, PlanBatch, PlanUnit, ReviewResult, UnitInfo, Verdict, VerdictValue

SCHEMA_ID = "l4/yolo-readiness@1"
PROMPT_VERSION = 1
MAX_CALLS = 2  # the first answer and one repair prompt
DEFAULT_TIMEOUT_S = 900
MAX_FILE_CHARS = 20_000
MAX_FOLDER_CHARS = 80_000
MAX_DEPENDENCY_CHARS = 20_000
MAX_PROBLEM_CHARS = 800
MATERIAL_MARK = "<!-- material -->"
ROLE = "judges"
SCRATCH = "yolo"

DigestOf = Callable[[Git, str, str], str]  # (git, rev, unit folder) -> the unit digest (`l4.yolo.digest.unit_digest`)
_CONTROL = re.compile(r"[\x00-\x1f\x7f\u2028\u2029]")


class JudgeFailed(RoleUnavailable):
    """The judge timed out or failed (R9). Not a verdict: nothing is recorded and the next run tries again. A
    `RoleUnavailable`, so a caller that waits for a judge to be available waits for this too."""

    def __init__(self, detail: str) -> None:
        super().__init__(ROLE, f"judge_error: {detail}")


def _load_schema() -> dict[str, Any]:
    text = resources.files("l4.yolo").joinpath("schemas/readiness.schema.json").read_text(encoding="utf-8")
    return json.loads(text)  # type: ignore[no-any-return]


def _load_template() -> tuple[str, str]:
    text = resources.files("l4.yolo").joinpath("prompts/readiness.md").read_text(encoding="utf-8")
    system, _, material = text.partition(MATERIAL_MARK)
    return system.strip() + "\n", material.strip() + "\n"


READINESS_SCHEMA = _load_schema()
SYSTEM_TEMPLATE, MATERIAL_TEMPLATE = _load_template()
_SLOT = re.compile(r"\{\{([A-Z_]+)\}\}")


def _fill(template: str, values: Mapping[str, str]) -> str:
    """One pass: text that was substituted is never substituted again (a spec may contain `{{...}}`)."""
    return _SLOT.sub(lambda m: values.get(m.group(1), m.group(0)), template)


# --- the material --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Omission:
    """A file the prompt does not show at all. `size_limit` tells a file left out for the size limits (R9: the review
    cannot be READY) from one that cannot be shown to a text judge (a binary file)."""

    path: str
    reason: str
    size_limit: bool = False


@dataclass(frozen=True)
class FolderText:
    path: str
    files: tuple[tuple[str, str], ...]  # (repository path, text), sorted; a cut file is shown up to its limit
    omitted: tuple[Omission, ...] = ()  # files the prompt does not show, and why
    cut: tuple[tuple[str, int], ...] = ()  # (repository path, characters left out) of files shown in part

    @property
    def empty(self) -> bool:
        return not self.files and not self.omitted

    @property
    def left_out(self) -> tuple[str, ...]:
        """What the size limits kept from the judge, one line each (R9)."""
        cut = [f"{json.dumps(path)}: {n} characters cut at the size limit" for path, n in self.cut]
        return tuple(cut + [f"{json.dumps(o.path)}: {o.reason}" for o in self.omitted if o.size_limit])

    @property
    def binary(self) -> tuple[str, ...]:
        return tuple(o.path for o in self.omitted if not o.size_limit)


def read_folder(git: Git, rev: str, folder: str, *, budget: int) -> FolderText:
    """The files of `folder` at `rev`, without what the harness writes (`.l4/**`, `verification.md`, `questions.md`,
    `feedback.md`, at any depth, `digest.is_excluded`) and without binary files; each file and the folder are cut at a
    bounded number of characters, and what was cut is recorded in `cut` and `omitted`."""
    root = folder.strip("/")
    listing = git.run_bytes("ls-tree", "-r", "-z", "--name-only", rev, "--", root + "/", check=False)
    files: list[tuple[str, str]] = []
    omitted: list[Omission] = []
    cut: list[tuple[str, int]] = []
    left = budget
    for raw in sorted(p for p in listing.split(b"\0") if p):
        path = raw.decode("utf-8", "replace")
        if is_excluded(PurePosixPath(path).relative_to(root).parts):
            continue
        data = normalise_tasks(path.rsplit("/", 1)[-1], git.run_bytes("show", f"{rev}:{path}", check=False))
        if b"\0" in data:
            omitted.append(Omission(path, "binary file"))
            continue
        text = data.decode("utf-8", "replace")
        shown = text[: min(MAX_FILE_CHARS, max(left, 0))]
        if len(shown) < len(text):
            if left <= 0:
                omitted.append(Omission(path, f"over the size limit of the folder ({len(text)} characters)", True))
                continue
            cut.append((path, len(text) - len(shown)))
            shown += f"\n[cut: {len(text) - len(shown)} characters omitted]"
        left -= len(shown)
        files.append((path, shown))
    return FolderText(root, tuple(files), tuple(omitted), tuple(cut))


def _label(text: str) -> str:
    """A `source` label for a data block: control characters escaped and tag openers defused (a path may hold both)."""
    return defuse(_CONTROL.sub(lambda m: m.group().encode("unicode_escape").decode("ascii"), text))


def _folder_blocks(folder: FolderText) -> str:
    blocks = [data_block(_label(path), text) for path, text in folder.files]
    blocks += [data_block("not shown", _label(f"{o.path}: {o.reason}")) for o in folder.omitted]
    return "\n\n".join(blocks) or "(the folder has no files)"


def _entry(model: Any) -> str:
    return json.dumps(model.model_dump(by_alias=True), indent=2, sort_keys=True)


@dataclass(frozen=True)
class Subject:
    """One thing to review: its id, its prompt, and what the prompt does not show (R9): `left_out` is what the size
    limits cut (the verdict cannot be READY), `not_shown` the binary files (listed in the verdict's `missing`)."""

    kind: str  # "unit" | "batch"
    id: str
    user: str
    left_out: tuple[str, ...] = ()
    not_shown: tuple[str, ...] = ()
    groups_only: bool = False  # a batch with no acceptance profile: batch_acceptance does not apply to it


GROUPING_NOTE = (
    "This batch only groups units, has no acceptance profile and states no outcome of its own, so batch_acceptance "
    "does not apply to it. Review what lies between its units: contradiction, duplicate_scope, missing_dependency, "
    "and the interfaces the units share."
)
NOT_APPLICABLE = "batch_acceptance"
TASKS_NOTE = (
    "The check marks of the tasks in a tasks.md are the harness's progress, not part of the specification: they are "
    "shown unchecked, whatever the file says, so a task is never a sign that something is already implemented."
)
ORDER_NOTE = (
    "A prerequisite that is a unit of this plan is delivered and merged into the target before any unit that depends "
    "on it starts: the plan runs one unit at a time, in dependency order."
)


def _batch_deps(ids: Sequence[str]) -> str:
    return data_block("batch prerequisites", "\n".join(f"- batch {b}" for b in ids)) if ids else ""


def _prerequisites(plan: Plan, deps: Sequence[tuple[str, FolderText | None]]) -> list[str]:
    """The prerequisite units, each as a data block with its folder text (or that its folder is not known), and the
    ordering of the plan in plain words when one of them is a unit of this plan."""
    shown = []
    for dep, dep_folder in deps:
        text = _folder_blocks(dep_folder) if dep_folder is not None else "(its folder is not known)"
        head = data_block("prerequisite", _label(dep + (f" ({dep_folder.path})" if dep_folder else "")))
        shown.append(f"{head}\n{text}")
    in_plan = {u.id for u in plan.units()}
    return [*shown, ORDER_NOTE] if any(dep in in_plan for dep, _ in deps) else shown


def _unit_subject(
    plan: Plan, unit: PlanUnit, batch: PlanBatch, folder: FolderText, deps: Sequence[tuple[str, FolderText | None]]
) -> Subject:
    prerequisites = _prerequisites(plan, deps)
    context = data_block("context", _label(f"in batch {batch.id}; plan {plan.plan_id}, target {plan.target}"))
    values = {
        "SUBJECT_KIND": "unit",
        "SUBJECT_ID": data_block("subject", _label(unit.id)),
        "ENTRY": data_block("plan entry", _entry(unit)) + "\n" + context + "\n" + TASKS_NOTE,
        "DEPENDENCIES": "\n\n".join([*prerequisites, _batch_deps(batch.depends_on)]).strip()
        or "(none: the unit depends on nothing)",
        "FOLDERS": data_block("folder", _label(f"{unit.id} ({folder.path})")) + "\n" + _folder_blocks(folder),
    }
    parts = [(unit.id, folder), *((d, f) for d, f in deps if f is not None)]
    left_out = tuple(f"{_named(who)} {line}" for who, f in parts for line in f.left_out)
    return Subject("unit", unit.id, _fill(MATERIAL_TEMPLATE, values), left_out, folder.binary)


def _named(unit_id: str) -> str:
    return json.dumps(unit_id) + ","


def _batch_subject(
    plan: Plan,
    batch: PlanBatch,
    folders: Mapping[str, FolderText],
    skip: Collection[str] = (),
    deps: Sequence[tuple[str, FolderText | None]] = (),
) -> Subject:
    """`deps`: the prerequisites of the units of the batch that are not units of the batch, in plan order."""
    units = [u for u in batch.units if u.id not in skip]
    context = data_block("context", _label(f"plan {plan.plan_id}, target {plan.target}"))
    groups_only = batch.acceptance_profile == PROFILE_NONE
    values = {
        "SUBJECT_KIND": "batch",
        "SUBJECT_ID": data_block("subject", _label(batch.id)),
        "ENTRY": data_block("plan entry", _entry(batch))
        + "\n"
        + context
        + "\n"
        + TASKS_NOTE
        + ("\n" + GROUPING_NOTE if groups_only else ""),
        "DEPENDENCIES": "\n\n".join([*_prerequisites(plan, deps), _batch_deps(batch.depends_on)]).strip()
        or "(none: the batch depends on nothing)",
        "FOLDERS": "\n\n".join(
            data_block("folder", _label(f"{u.id} ({folders[u.id].path})")) + "\n" + _folder_blocks(folders[u.id])
            for u in units
        ),
    }
    parts = [*((u.id, folders[u.id]) for u in units), *((d, f) for d, f in deps if f is not None)]
    left_out = tuple(f"{_named(who)} {line}" for who, f in parts for line in f.left_out)
    not_shown = tuple(p for u in units for p in folders[u.id].binary)
    return Subject("batch", batch.id, _fill(MATERIAL_TEMPLATE, values), left_out, not_shown, groups_only)


# --- the answer ----------------------------------------------------------------------------------------------------


def blocked(text: str) -> Verdict:
    """BLOCKED with the harness's own finding (criterion `schema`, which the model cannot produce)."""
    return Verdict("BLOCKED", ({"criterion": "schema", "severity": "blocking", "text": text},))


def verdict_of(answer: Any, *, digest: str | None = None) -> Verdict:
    """The rules of D5 on a parsed answer: a schema break is BLOCKED (`schema_invalid`), and a blocking finding makes a
    READY verdict NEEDS_REVISION."""
    problems = validate(answer, READINESS_SCHEMA) if isinstance(answer, dict) else ["$: expected object"]
    if problems:
        return _with_digest(blocked("schema_invalid: " + "; ".join(problems[:5])), digest)
    findings = tuple({k: str(f[k]) for k in ("criterion", "severity", "text")} for f in answer["findings"])
    said: VerdictValue = answer["verdict"]
    if said == "READY" and any(f["severity"] == "blocking" for f in findings):
        said = "NEEDS_REVISION"
    return Verdict(
        said,
        findings,
        tuple(map(str, answer.get("assumptions", ()))),
        tuple(map(str, answer.get("missing", ()))),
        digest,
    )


def _with_digest(verdict: Verdict, digest: str | None) -> Verdict:
    return Verdict(verdict.verdict, verdict.findings, verdict.assumptions, verdict.missing, digest)


def _amend(verdict: Verdict, subject: Subject) -> Verdict:
    """What the judge was not shown is the harness's finding, not the model's (R9): material the size limits cut makes
    the verdict at least NEEDS_REVISION (BLOCKED stays BLOCKED) with a blocking finding that names it; the binary files
    are listed in `missing`."""
    findings, said, missing, assumptions = verdict.findings, verdict.verdict, verdict.missing, verdict.assumptions
    if subject.groups_only and any(f["criterion"] == NOT_APPLICABLE for f in findings):
        # the plan file has nowhere to state a batch outcome: the finding cannot be fixed, so it is kept as a note
        assumptions = (
            *assumptions,
            *(
                f"batch_acceptance does not apply (the batch has no acceptance profile), {f['severity']}: {f['text']}"
                for f in findings
                if f["criterion"] == NOT_APPLICABLE
            ),
        )
        findings = tuple(f for f in findings if f["criterion"] != NOT_APPLICABLE)
        if said == "NEEDS_REVISION" and not any(f["severity"] in ("blocking", "major") for f in findings):
            said = "READY"
        if said == "BLOCKED" and not findings:  # nothing is left that a person could fix: the note was all there was
            said = "READY"
    if subject.left_out:
        text = "material_cut: left out of the review by the size limits, so the review is partial: " + "; ".join(
            subject.left_out
        )
        findings = (*findings, {"criterion": "material", "severity": "blocking", "text": text})
        said = "NEEDS_REVISION" if said == "READY" else said
    if subject.not_shown:
        missing = (*missing, *(f"not shown to the judge (binary file): {path}" for path in subject.not_shown))
    return Verdict(said, findings, assumptions, missing, verdict.digest)


# --- the judge call ------------------------------------------------------------------------------------------------


class _Calls:
    """One judge, opened once for the whole review: its request factory writes under the plan's scratch folder."""

    def __init__(self, app: AppContext, cfg: L4Config, git: Git, plan_id: str, selected: Selected, sandbox: Sandbox):
        self.app, self.cfg, self.selected, self.sandbox = app, cfg, selected, sandbox
        self.root = cache_root(app.environ, repo=app.repo) / SCRATCH / plan_id / "review"
        self.cwd, self.tmp = self.root / "cwd", self.root / "tmp"
        common = git.run("rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
        home = Path(app.environ["HOME"]) if app.environ.get("HOME") else Path.home()
        self.spec = SandboxSpec(
            "agent", self.cwd, Path(common), self.tmp, home,
            expand_credential_paths(cfg.sandbox.credential_paths, home),
            adapter=selected.profile.adapter, network=True, runner_tmp=runner_tmp_paths(app.environ),
        )  # fmt: skip
        self.count = 0
        self.judge = AgentJudge(selected.impl, self._request, role=ROLE, profile=selected.profile_name)

    def _request(self, prompt: str, schema: dict[str, Any], timeout_s: int) -> RunRequest:
        for folder in (self.cwd, self.tmp):
            shutil.rmtree(folder, ignore_errors=True)
            folder.mkdir(parents=True)
        self.count += 1
        raw = self.root / "agent-raw" / self.app.run_id / f"readiness-{self.count}.jsonl"
        extra = dict(getattr(self.selected.impl, "extra_env", {}))
        return RunRequest(
            profile=self.selected.profile, role="judge", cwd=self.cwd, prompt=prompt,
            result_path=self.tmp / "result.json", raw_events_path=raw,
            env=build_agent_env(self.app.environ, self.spec, extra=extra), result_schema=schema,
            permission_policy=PermissionPolicy("judge"), timeout_s=timeout_s,
            wrap=lambda argv, env, cwd=None: self.sandbox.wrap(argv, self.spec, env, cwd), host_env=self.app.environ,
        )  # fmt: skip

    def ask(self, subject: Subject, *, timeout_s: int, digest: str | None) -> tuple[Verdict, float]:
        """At most two calls: a break of the schema gets one repair prompt. Returns the verdict and the cost."""
        first = [Msg("user", self.app.redactor.redact_text(subject.user))]
        messages = first
        system = _fill(SYSTEM_TEMPLATE, {"SUBJECT_KIND": subject.kind})
        cost = 0.0
        detail = ""
        for _ in range(MAX_CALLS):
            result: StructuredResult = self.judge.complete_structured(
                system, messages, READINESS_SCHEMA, effort=None, max_tokens=0, timeout_s=timeout_s
            )
            cost += result.usage.cost_usd or 0.0
            if result.status == "limit":
                assert result.run is not None
                raise RoleLimit(result.run)
            if result.status in ("timeout", "error"):
                raise JudgeFailed(result.detail or result.status)  # R9: not a verdict, nothing is recorded
            if result.status == "ok":
                return verdict_of(result.parsed, digest=digest), cost
            detail = result.detail  # schema_invalid: the paths, never the values
            problem = detail if len(detail) <= MAX_PROBLEM_CHARS else detail[: MAX_PROBLEM_CHARS - 1] + "…"
            rejected = result.raw
            echo = [Msg("assistant", self.app.redactor.redact_text(json.dumps(rejected)))] if rejected else []
            messages = [
                *first,
                *echo,
                Msg(
                    "user", f"Your reply did not satisfy the schema ({problem}). Reply again with the JSON object only."
                ),
            ]
        return _with_digest(blocked(f"schema_invalid: {detail or 'no valid answer'}"), digest), cost


# --- the public functions ------------------------------------------------------------------------------------------


def _unit_revs(git: Git, cfg: L4Config, plan: Plan, units: Mapping[str, UnitInfo], target: str) -> dict[str, str]:
    """The commit each known unit of the plan and each unit it depends on is read on: its branch on `origin` when it
    has one, else the target (`current_unit_ref`, R3). Raises `RevisionMissing` before any model is asked."""
    wanted = dict.fromkeys([u.id for u in plan.units()] + [d for u in plan.units() for d in u.depends_on])
    revs = {}
    for unit_id in (u for u in wanted if u in units):
        ref = current_unit_ref(git, cfg, unit_id, target)
        revs[unit_id] = git.rev_parse(ref) or ref
    return revs


def review_plan_costed(
    app: AppContext,
    cfg: L4Config,
    plan: Plan,
    units: Mapping[str, UnitInfo],
    *,
    git: Git,
    rev: str,
    adapters: Mapping[str, AgentAdapter] | None = None,
    digest_of: DigestOf | None = None,
    sandbox: Sandbox | None = None,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    done: Collection[str] = (),
) -> tuple[ReviewResult, float]:
    """`review_plan` and the cost in dollars the judge reported (what the plan step charges to the plan). `done` names
    the units the plan already merged or integrated (`admit.done_units`): the target holds their work, so the judge is
    not asked about them (they are READY, with their digest when their folder is there) and a batch is reviewed on its
    other units. A batch of done units only is READY."""
    revs = _unit_revs(git, cfg, plan, units, rev)
    digest_fn = digest_of or unit_digest  # on the revision a unit is read on: `current_unit_digest` of that unit (R3)
    folders: dict[str, FolderText] = {}
    for unit in plan.units():
        info = units.get(unit.id)
        folders[unit.id] = (
            read_folder(git, revs[unit.id], info.folder, budget=MAX_FOLDER_CHARS) if info else FolderText("", ())
        )
    read_deps: dict[str, FolderText | None] = {}

    def dependency(dep: str) -> FolderText | None:  # a prerequisite is read once, whoever shows it
        if dep not in read_deps:
            read_deps[dep] = (
                read_folder(git, revs[dep], units[dep].folder, budget=MAX_DEPENDENCY_CHARS) if dep in units else None
            )
        return read_deps[dep]

    subjects: list[tuple[Subject, str | None]] = []
    result_units: dict[str, Verdict] = {}
    result_batches: dict[str, Verdict] = {}
    for batch in plan.batches:
        for unit in batch.units:
            info, folder = units.get(unit.id), folders[unit.id]
            digest = digest_fn(git, revs[unit.id], info.folder) if info and not folder.empty else None
            if unit.id in done:
                result_units[unit.id] = _with_digest(Verdict("READY"), digest)
                continue
            if folder.empty:
                note = (
                    f"the folder of {unit.id} has no files at {revs[unit.id][:10]}"
                    if info
                    else f"{unit.id} is not a known unit"
                )
                result_units[unit.id] = _with_digest(blocked(f"unit_missing: {note}"), digest)
                continue
            deps = [(d, dependency(d)) for d in unit.depends_on]
            subjects.append((_unit_subject(plan, unit, batch, folder, deps), digest))
    for batch in plan.batches:
        left = [u for u in batch.units if u.id not in done]
        if len(batch.units) > 1 and not left:
            result_batches[batch.id] = Verdict("READY")
        elif len(batch.units) > 1 and all(not folders[u.id].empty for u in left):
            inside = {u.id for u in batch.units}
            # the prerequisites of the units reviewed that lie outside the batch, once each, in plan order
            outside = dict.fromkeys(d for u in left for d in u.depends_on if d not in inside)
            batch_deps = [(d, dependency(d)) for d in outside]
            subjects.append((_batch_subject(plan, batch, folders, skip=done, deps=batch_deps), None))
    cost = 0.0
    if subjects:
        factory = Factory(
            cfg,
            ProbeCtx(app.environ, cache_root(app.environ, repo=app.repo), run_process, forbid=(app.repo,)),
            adapters=adapters,
            availability=AvailabilityStore(cache_root(app.environ, repo=app.repo)),
            clock=SystemClock(),
        )
        selected = factory.for_role(ROLE, f"plan:{plan.plan_id}", serves=JUDGE_ADAPTERS)
        chosen = sandbox or select_sandbox(cfg.sandbox, app.environ, repo=app.repo)
        calls = _Calls(app, cfg, git, plan.plan_id, selected, chosen)
        for subject, digest in subjects:
            verdict, spent = calls.ask(subject, timeout_s=timeout_s, digest=digest)
            cost += spent
            verdict = _amend(verdict, subject)
            (result_units if subject.kind == "unit" else result_batches)[subject.id] = verdict
    for batch in plan.batches:  # a batch with a unit that cannot be reviewed is not reviewed as a whole either
        if len(batch.units) > 1 and batch.id not in result_batches:
            result_batches[batch.id] = blocked("unit_missing: a unit of the batch has no folder to review")
    ordered = {u.id: result_units[u.id] for u in plan.units()}
    return ReviewResult(ordered, result_batches), cost


def review_plan(
    app: AppContext,
    cfg: L4Config,
    plan: Plan,
    units: Mapping[str, UnitInfo],
    *,
    git: Git,
    rev: str,
    adapters: Mapping[str, AgentAdapter] | None = None,
    digest_of: DigestOf | None = None,
    sandbox: Sandbox | None = None,
) -> ReviewResult:
    """Review every unit of `plan` and every batch of more than one unit, with the judge role, on the folders at `rev`.

    `adapters` replaces the adapters by name (tests and `l4 simulate` inject a `FakeAdapter`). `units` is what
    admission read of each unit (its folder). `rev` is the target: a unit that has a branch on `origin` is read, and
    digested, on that branch (D3, R3). A `Verdict.digest` is the unit digest on the revision the unit was read on:
    `digest_of` when given, else `l4.yolo.digest.unit_digest`. A revision that does not exist raises `RevisionMissing`;
    a judge that fails raises `JudgeFailed`. `sandbox` replaces the selected sandbox."""
    result, _ = review_plan_costed(
        app, cfg, plan, units, git=git, rev=rev, adapters=adapters, digest_of=digest_of, sandbox=sandbox
    )
    return result


__all__ = [
    "READINESS_SCHEMA",
    "FolderText",
    "JudgeFailed",
    "Omission",
    "Subject",
    "read_folder",
    "review_plan",
    "review_plan_costed",
    "verdict_of",
]
