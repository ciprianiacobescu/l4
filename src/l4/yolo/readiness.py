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

import hashlib
import json
import re
import shutil
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, replace
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
from l4.yolo.admit import FINISHED_PHASES
from l4.yolo.digest import current_unit_ref, is_excluded, unit_digest
from l4.yolo.model import PROFILE_NONE, Plan, PlanBatch, PlanUnit, ReviewResult, UnitInfo, Verdict, VerdictValue

SCHEMA_ID = "l4/yolo-readiness@1"
# 2: the material changed (tasks.md shown with the digest's normalisation and the note on check marks, prerequisite
# units of a batch, review 7). 3: the units already delivered on the target are listed, with the note that a
# dependency on one of them is satisfied. 4: tasks.md shown as it is; prerequisites spec first and their cut is not
# blocking; material keys. A review recorded with another version is stale,
# `plan.reviewed{prompt_version}`; an event without the key counts as 1.
PROMPT_VERSION = 4
MAX_DELIVERED = 60
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
class Budgets:
    """The size limits of the material (`yolo.review`, design D4): per file, per folder of a subject, and per folder
    of a prerequisite."""

    file: int
    folder: int
    dependency: int

    @classmethod
    def of(cls, cfg: L4Config) -> "Budgets":
        review = cfg.yolo.review
        return cls(review.max_file_chars, review.max_folder_chars, review.max_dependency_chars)


@dataclass(frozen=True)
class FolderText:
    path: str
    files: tuple[tuple[str, str], ...]  # (repository path, text), in reading order; a cut file is shown up to its limit
    omitted: tuple[Omission, ...] = ()  # files the prompt does not show, and why
    cut: tuple[tuple[str, int], ...] = ()  # (repository path, characters left out) of files shown in part
    sizes: tuple[tuple[str, int], ...] = ()  # (repository path, total characters) of every text file read
    file_budget: int = MAX_FILE_CHARS
    budget: int = MAX_FOLDER_CHARS
    base: str = "the target branch"

    @property
    def empty(self) -> bool:
        return not self.files and not self.omitted

    @property
    def left_out(self) -> tuple[str, ...]:
        """What the size limits kept from the judge, one `material_cut` sentence each (R9, design D4): for a subject."""
        return tuple(
            f"material_cut: {path} has {total} characters; the review shows {self.file_budget} per file and "
            f"{self.budget} per folder (yolo.review.max_file_chars, yolo.review.max_folder_chars). Shorten the file "
            f"(move background out of the unit folder) or raise the limit in .l4/config.yaml on {self.base}. "
            "Splitting it does not help: the implementer reads only proposal.md, design.md, requirements.md, "
            "bugfix.md and specs/*/spec.md."
            for path, total, _ in self._shortened()
        )

    def not_in_full(self, who: str, budget: int) -> tuple[str, ...]:
        """The same files for a prerequisite: listed in `missing`, never blocking (design D4)."""
        return tuple(
            f"not shown in full: {json.dumps(who)}: {path} ({shown} of {total} characters shown; "
            f"dependency budget {budget})"
            for path, total, shown in self._shortened()
        )

    def _shortened(self) -> list[tuple[str, int, int]]:
        """(path, total characters, characters shown) of every file the limits cut or left out."""
        sizes, cut = dict(self.sizes), dict(self.cut)
        found = [(path, sizes[path], sizes[path] - n) for path, n in cut.items()]
        return found + [(o.path, sizes[o.path], 0) for o in self.omitted if o.size_limit]

    @property
    def binary(self) -> tuple[str, ...]:
        return tuple(o.path for o in self.omitted if not o.size_limit)


def _rank(rel: str) -> int:
    """The reading order of a prerequisite (design D4): what a dependent needs first, the task list last."""
    parts = PurePosixPath(rel).parts
    if rel in ("proposal.md", "requirements.md"):
        return 0 if rel == "proposal.md" else 1
    if parts[0] == "specs" and parts[-1] == "spec.md":
        return 2
    return {"bugfix.md": 3, "design.md": 4, "tasks.md": 6}.get(rel, 5)


def read_folder(
    git: Git,
    rev: str,
    folder: str,
    *,
    budget: int,
    file_budget: int = MAX_FILE_CHARS,
    order: str = "sorted",
    base: str = "the target branch",
) -> FolderText:
    """The files of `folder` at `rev` as they are (the check marks of `tasks.md` too, design D6; the digest normalises
    them, the material does not), without what the harness writes (`.l4/**`, `verification.md`, `questions.md`,
    `feedback.md`, at any depth, `digest.is_excluded`) and without binary files; each file and the folder are cut at a
    bounded number of characters, and what was cut is recorded in `cut` and `omitted`. `order` is `"sorted"` (the
    subject) or `"prerequisite"` (proposal, requirements, specs, bugfix, design, other files, `tasks.md` last)."""
    root = folder.strip("/")
    listing = git.run_bytes("ls-tree", "-r", "-z", "--name-only", rev, "--", root + "/", check=False)
    files: list[tuple[str, str]] = []
    omitted: list[Omission] = []
    cut: list[tuple[str, int]] = []
    sizes: list[tuple[str, int]] = []
    left = budget
    paths = sorted(p.decode("utf-8", "replace") for p in listing.split(b"\0") if p)
    if order == "prerequisite":
        paths.sort(key=lambda p: _rank(str(PurePosixPath(p).relative_to(root))))  # stable: sorted within a rank
    for path in paths:
        if is_excluded(PurePosixPath(path).relative_to(root).parts):
            continue
        data = git.run_bytes("show", f"{rev}:{path}", check=False)
        if b"\0" in data:
            omitted.append(Omission(path, "binary file"))
            continue
        text = data.decode("utf-8", "replace")
        sizes.append((path, len(text)))
        shown = text[: min(file_budget, max(left, 0))]
        if len(shown) < len(text):
            if left <= 0:
                omitted.append(Omission(path, f"over the size limit of the folder ({len(text)} characters)", True))
                continue
            cut.append((path, len(text) - len(shown)))
            shown += f"\n[cut: {len(text) - len(shown)} characters omitted]"
        left -= len(shown)
        files.append((path, shown))
    return FolderText(root, tuple(files), tuple(omitted), tuple(cut), tuple(sizes), file_budget, budget, base)


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
    not_in_full: tuple[str, ...] = ()  # a prerequisite's files the budget cut: listed in `missing`, never blocking (D4)
    groups_only: bool = False  # a batch with no acceptance profile: batch_acceptance does not apply to it
    key_text: str = ""  # `user` with the delivered block left empty: what the material key covers (design D2)

    @property
    def name(self) -> str:
        """The subject as the CLI, the events and the cache name it: a unit id, or `batch:<id>`."""
        return self.id if self.kind == "unit" else f"batch:{self.id}"


GROUPING_NOTE = (
    "This batch only groups units, has no acceptance profile and states no outcome of its own, so batch_acceptance "
    "does not apply to it. Review what lies between its units: contradiction, duplicate_scope, missing_dependency, "
    "and the interfaces the units share."
)
NOT_APPLICABLE = "batch_acceptance"
TASKS_NOTE = (
    "A ticked task (`[x]`) is already delivered on the revision shown: the harness will not implement it again. "
    "Judge the specification of the open tasks; do not raise a `feasibility` or `duplicate_scope` finding only "
    "because work is already done."
)
ORDER_NOTE = (
    "A prerequisite that is a unit of this plan is delivered and merged into the target before any unit that depends "
    "on it starts: the plan runs one unit at a time, in dependency order."
)


def delivered_on_target(archived: Collection[str], phases: Mapping[str, str | None]) -> dict[str, str]:
    """The units already finished on the target: the OpenSpec changes archived at the target revision
    (`plans.archived_at`) and the units a provider reads as merged or archived (`admit.FINISHED_PHASES`), unit id ->
    "archived" or "finished". The caller already holds both; nothing is discovered here."""
    found = {u: "finished" for u, phase in phases.items() if phase in FINISHED_PHASES}
    found.update(dict.fromkeys(archived, "archived"))
    return found


def _delivered_note(plan: Plan, delivered: Mapping[str, str]) -> str:
    """Harness text on the units already delivered on the target, outside the data blocks except for the names
    (repository text): a dependency on one of them is satisfied. The plan's own units are not listed; the list is
    capped."""
    own = {u.id for u in plan.units()}
    names = sorted(u for u in delivered if u not in own)
    if not names:
        return ""
    shown = "\n".join(f"- {_label(u)} ({delivered[u]})" for u in names[:MAX_DELIVERED])
    more = len(names) - MAX_DELIVERED
    tail = f"\nand {more} more are delivered; the list shows the first {MAX_DELIVERED} names." if more > 0 else ""
    return (
        "Already delivered on the target (a dependency on one of these is satisfied and is not a missing_dependency; "
        "it is not a unit of this plan):\n" + data_block("already delivered", shown) + tail
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
    plan: Plan,
    unit: PlanUnit,
    batch: PlanBatch,
    folder: FolderText,
    deps: Sequence[tuple[str, FolderText | None]],
    delivered: Mapping[str, str] = {},  # noqa: B006 - read only
    dep_budget: int = MAX_DEPENDENCY_CHARS,
) -> Subject:
    prerequisites = _prerequisites(plan, deps)
    context = data_block("context", _label(f"in batch {batch.id}; plan {plan.plan_id}, target {plan.target}"))

    def text(listed: Mapping[str, str]) -> str:
        values = {
            "SUBJECT_KIND": "unit",
            "SUBJECT_ID": data_block("subject", _label(unit.id)),
            "ENTRY": data_block("plan entry", _entry(unit)) + "\n" + context + "\n" + TASKS_NOTE,
            "DEPENDENCIES": "\n\n".join(
                [*prerequisites, _batch_deps(batch.depends_on), _delivered_note(plan, listed)]
            ).strip()
            or "(none: the unit depends on nothing)",
            "FOLDERS": data_block("folder", _label(f"{unit.id} ({folder.path})")) + "\n" + _folder_blocks(folder),
        }
        return _fill(MATERIAL_TEMPLATE, values)

    return Subject(
        "unit", unit.id, text(delivered), folder.left_out, folder.binary, _cut_of(deps, dep_budget),
        key_text=text({}),
    )  # fmt: skip


def _cut_of(deps: Sequence[tuple[str, FolderText | None]], budget: int) -> tuple[str, ...]:
    return tuple(line for who, f in deps if f is not None for line in f.not_in_full(who, budget))


def _batch_subject(
    plan: Plan,
    batch: PlanBatch,
    folders: Mapping[str, FolderText],
    skip: Collection[str] = (),
    deps: Sequence[tuple[str, FolderText | None]] = (),
    delivered: Mapping[str, str] = {},  # noqa: B006 - read only
    dep_budget: int = MAX_DEPENDENCY_CHARS,
) -> Subject:
    """`deps`: the prerequisites of the units of the batch that are not units of the batch, in plan order."""
    units = [u for u in batch.units if u.id not in skip]
    context = data_block("context", _label(f"plan {plan.plan_id}, target {plan.target}"))
    groups_only = batch.acceptance_profile == PROFILE_NONE

    def text(listed: Mapping[str, str]) -> str:
        values = {
            "SUBJECT_KIND": "batch",
            "SUBJECT_ID": data_block("subject", _label(batch.id)),
            "ENTRY": data_block("plan entry", _entry(batch))
            + "\n"
            + context
            + "\n"
            + TASKS_NOTE
            + ("\n" + GROUPING_NOTE if groups_only else ""),
            "DEPENDENCIES": "\n\n".join(
                [*_prerequisites(plan, deps), _batch_deps(batch.depends_on), _delivered_note(plan, listed)]
            ).strip()
            or "(none: the batch depends on nothing)",
            "FOLDERS": "\n\n".join(
                data_block("folder", _label(f"{u.id} ({folders[u.id].path})")) + "\n" + _folder_blocks(folders[u.id])
                for u in units
            ),
        }
        return _fill(MATERIAL_TEMPLATE, values)

    left_out = tuple(line for u in units for line in folders[u.id].left_out)
    not_shown = tuple(p for u in units for p in folders[u.id].binary)
    return Subject(
        "batch", batch.id, text(delivered), left_out, not_shown, _cut_of(deps, dep_budget), groups_only, text({})
    )


class FreshRefused(Exception):
    """`--fresh` named subjects whose current material is already on the ledger: they are not judged again."""

    def __init__(self, names: tuple[str, ...]) -> None:
        super().__init__(", ".join(names))
        self.names = names


def material_key(kind: str, key_text: str) -> str:
    """The material key of a subject (design D2): the prompt version, the kind and the user text without the delivered
    block, so a verdict is reused exactly when the judge would be shown the same thing."""
    return hashlib.sha256(f"{PROMPT_VERSION}\0{kind}\0{key_text}".encode()).hexdigest()[:16]


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
    are listed in `missing` and so is what a prerequisite's budget cut. Then the rules of L4-YOLO-023: a
    minor or major `batch_acceptance` finding on a unit (any severity on a batch without a
    profile) becomes an assumption; a NEEDS_REVISION with no finding gets the harness
    finding `verdict`; a NEEDS_REVISION whose findings are all minor is READY (the findings stay). The judge's own
    `blocking` and a BLOCKED are not touched."""
    findings, said, missing, assumptions = verdict.findings, verdict.verdict, verdict.missing, verdict.assumptions
    named_none = not findings
    why = (
        "batch_acceptance does not apply (the batch has no acceptance profile)"
        if subject.groups_only
        else "batch_acceptance does not apply to a unit"
        if subject.kind == "unit"
        else ""
    )
    # on a unit only a minor or major note can be moved: a blocking finding is the judge's own and stays (D3)
    moved = tuple(
        f
        for f in findings
        if f["criterion"] == NOT_APPLICABLE and (subject.groups_only or f["severity"] in ("minor", "major"))
    )
    if why and moved:
        # the plan file has nowhere to state a batch outcome: the finding cannot be fixed, so it is kept as a note
        assumptions = (*assumptions, *(f"{why}, {f['severity']}: {f['text']}" for f in moved))
        findings = tuple(f for f in findings if f not in moved)
        if said == "NEEDS_REVISION" and not any(f["severity"] in ("blocking", "major") for f in findings):
            said = "READY"
        if said == "BLOCKED" and not findings and subject.groups_only:
            said = "READY"  # a subject that only groups units: the note was all there was
    if subject.left_out:
        text = " ".join(subject.left_out)
        findings = (*findings, {"criterion": "material", "severity": "blocking", "text": text})
        said = "NEEDS_REVISION" if said == "READY" else said
    if said == "NEEDS_REVISION" and named_none and not findings:
        shown = "; ".join(verdict.missing) or "nothing"
        text = f"the judge said NEEDS_REVISION and named no finding; missing: {shown}"
        findings = ({"criterion": "verdict", "severity": "major", "text": text},)
    elif said == "NEEDS_REVISION" and findings and all(f["severity"] == "minor" for f in findings):
        said = "READY"  # the prompt defines minor as a nit
    if subject.not_shown:
        missing = (*missing, *(f"not shown to the judge (binary file): {path}" for path in subject.not_shown))
    missing = (*missing, *subject.not_in_full)
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


def _given_revs(plan: Plan, units: Mapping[str, UnitInfo], given: Mapping[str, str], rev: str) -> dict[str, str]:
    wanted = dict.fromkeys([u.id for u in plan.units()] + [d for u in plan.units() for d in u.depends_on])
    return {u: given.get(u, rev) for u in wanted if u in units}


NO_REVIEW = ("schema", "unit_missing", "completeness")  # harness findings: a verdict that is no review is never reused


def _reusable(entry: Mapping[str, Any]) -> bool:
    return not any(f.get("criterion") in NO_REVIEW for f in entry.get("findings", ()))


def _reused(entry: Mapping[str, Any], key: str, digest: str | None) -> Verdict:
    return Verdict(
        entry["verdict"],
        tuple(dict(f) for f in entry.get("findings", ())),
        tuple(entry.get("assumptions", ())),
        tuple(entry.get("missing", ())),
        digest,
        key,
        entry.get("at") or entry.get("reused_from"),
    )


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
    delivered: Mapping[str, str] = {},  # noqa: B006 - read only
    prior: Mapping[str, Mapping[str, Any]] = {},  # noqa: B006 - read only
    fresh: Collection[str] = (),
    revs: Mapping[str, str] | None = None,
    budgets: Budgets | None = None,
    sandbox_for: Callable[[str, str], Sandbox] | None = None,
    refuse_fresh_of_prior: bool = False,
) -> tuple[ReviewResult, float]:
    """`review_plan` and the cost in dollars the judge reported (what the plan step charges to the plan). `done` names
    the units the plan already merged or integrated (`admit.done_units`): the target holds their work, so the judge is
    not asked about them (they are READY, with their digest when their folder is there) and a batch is reviewed on its
    other units. A batch of done units only is READY. `delivered` (`delivered_on_target`) names the units already
    finished on the target; the judge is told a dependency on one of them is satisfied.

    `prior` maps a material key to a recorded entry (`plan.reviewed`): a subject whose key is there and whose name
    (`Subject.name`) is not in `fresh` gets that verdict again (`reused_from`), with no judge call and no cost, unless
    the entry is no review (a harness `schema`, `unit_missing` or `completeness` finding). `revs` replaces the revision
    every unit and prerequisite is read on (the working-tree snapshot). The judge and its sandbox are created only when
    a subject is judged; `sandbox_for(adapter, profile)` then replaces `sandbox` and `select_sandbox`. With
    `refuse_fresh_of_prior`, a subject named in `fresh` whose material is already in `prior` raises `FreshRefused`
    before any judge call (a recorded review is not re-rolled)."""
    revs = _unit_revs(git, cfg, plan, units, rev) if revs is None else _given_revs(plan, units, revs, rev)
    limits = budgets or Budgets.of(cfg)
    digest_fn = digest_of or unit_digest  # on the revision a unit is read on: `current_unit_digest` of that unit (R3)
    folders: dict[str, FolderText] = {}
    for unit in plan.units():
        info = units.get(unit.id)
        folders[unit.id] = (
            read_folder(
                git, revs[unit.id], info.folder, budget=limits.folder, file_budget=limits.file, base=plan.target
            )
            if info
            else FolderText("", ())
        )
    read_deps: dict[str, FolderText | None] = {}

    def dependency(dep: str) -> FolderText | None:  # a prerequisite is read once, whoever shows it
        if dep not in read_deps:
            read_deps[dep] = (
                read_folder(
                    git,
                    revs[dep],
                    units[dep].folder,
                    budget=limits.dependency,
                    file_budget=limits.file,
                    order="prerequisite",
                )  # fmt: skip
                if dep in units
                else None
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
            subjects.append((_unit_subject(plan, unit, batch, folder, deps, delivered, limits.dependency), digest))
    for batch in plan.batches:
        left = [u for u in batch.units if u.id not in done]
        if len(batch.units) > 1 and not left:
            result_batches[batch.id] = Verdict("READY")
        elif len(batch.units) > 1 and all(not folders[u.id].empty for u in left):
            inside = {u.id for u in batch.units}
            # the prerequisites of the units reviewed that lie outside the batch, once each, in plan order
            outside = dict.fromkeys(d for u in left for d in u.depends_on if d not in inside)
            batch_deps = [(d, dependency(d)) for d in outside]
            subjects.append(
                (_batch_subject(plan, batch, folders, done, batch_deps, delivered, limits.dependency), None)
            )
    cost = 0.0
    asked: list[tuple[Subject, str | None, str]] = []
    refused: list[str] = []
    for subject, digest in subjects:
        key = material_key(subject.kind, subject.key_text)
        entry = prior.get(key)
        if refuse_fresh_of_prior and subject.name in fresh and entry is not None and _reusable(entry):
            refused.append(subject.name)
        if entry is not None and subject.name not in fresh and _reusable(entry):
            (result_units if subject.kind == "unit" else result_batches)[subject.id] = _reused(entry, key, digest)
        else:
            asked.append((subject, digest, key))
    if refused:
        raise FreshRefused(tuple(refused))
    if asked:
        factory = Factory(
            cfg,
            ProbeCtx(app.environ, cache_root(app.environ, repo=app.repo), run_process, forbid=(app.repo,)),
            adapters=adapters,
            availability=AvailabilityStore(cache_root(app.environ, repo=app.repo)),
            clock=SystemClock(),
        )
        selected = factory.for_role(ROLE, f"plan:{plan.plan_id}", serves=JUDGE_ADAPTERS)
        if sandbox_for is not None:
            chosen = sandbox_for(selected.profile.adapter, selected.profile_name)
        else:
            chosen = sandbox or select_sandbox(cfg.sandbox, app.environ, repo=app.repo)
        calls = _Calls(app, cfg, git, plan.plan_id, selected, chosen)
        for subject, digest, key in asked:
            verdict, spent = calls.ask(subject, timeout_s=timeout_s, digest=digest)
            cost += spent
            verdict = replace(_amend(verdict, subject), material=key)
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
    "Budgets",
    "FolderText",
    "FreshRefused",
    "JudgeFailed",
    "Omission",
    "Subject",
    "delivered_on_target",
    "material_key",
    "read_folder",
    "review_plan",
    "review_plan_costed",
    "verdict_of",
]
