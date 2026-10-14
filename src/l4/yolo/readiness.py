"""The readiness review of a delivery plan (design D5, requirement L4-YOLO-004, scenarios SCN-YOLO-08 and -09).

The judge role reviews each unit of a plan (its folder at a revision, its plan entry, the units it depends on) and each
batch with more than one unit (all its units' folders together). The prompt is `prompts/readiness.md`, the answer must
satisfy `schemas/readiness.schema.json`, and `review_plan` returns one `Verdict` per unit and per batch.

The call goes through the same machinery as the verifier's judge: the first usable profile of `roles.judges`
(`Factory.for_role`, probes, cool-downs, the login gate), an `AgentJudge`, and the judge's permission policy, which
allows no tool at all (stricter than read-only): everything the judge may see is in the prompt, inside `<l4:data>`
blocks, and the process runs in an empty scratch folder outside the repository, in the agent sandbox. There is no
implementer to be independent of, so the independence rule of the verifier does not apply.

Two rules decide the verdict whatever the model says: an empty, unparsable or schema-invalid answer is BLOCKED with a
finding `{criterion: "schema", severity: "blocking", text: "schema_invalid: ..."}`, and a blocking finding makes the
verdict at least NEEDS_REVISION. Structural validity alone never makes a verdict READY. A usage limit is not a verdict:
`RoleLimit` is raised (and `RoleUnavailable` when no judge profile can serve), so the caller can wait, never record a
review that did not happen.
"""

import json
import re
import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Any

from l4.agents.base import AgentAdapter, PermissionPolicy, ProbeCtx, RunRequest
from l4.agents.factory import Factory, Selected
from l4.availability.cooldown import AvailabilityStore, SystemClock
from l4.config.defaults import cache_root
from l4.config.schema import L4Config
from l4.context import AppContext
from l4.implementer.prompt import data_block
from l4.implementer.tdd import RoleLimit
from l4.llm.agent_judge import JUDGE_ADAPTERS, AgentJudge, Msg, StructuredResult
from l4.proc import run_process
from l4.sandbox.base import Sandbox, SandboxSpec, expand_credential_paths, runner_tmp_paths
from l4.sandbox.env import build_agent_env
from l4.sandbox.select import select_sandbox
from l4.schemacheck import validate
from l4.vcs.git import Git
from l4.yolo.model import Plan, PlanBatch, PlanUnit, ReviewResult, UnitInfo, Verdict, VerdictValue

SCHEMA_ID = "l4/yolo-readiness@1"
PROMPT_VERSION = 1
MAX_CALLS = 2  # the first answer and one repair prompt
DEFAULT_TIMEOUT_S = 900
MAX_FILE_CHARS = 20_000
MAX_FOLDER_CHARS = 80_000
MAX_DEPENDENCY_CHARS = 20_000
MAX_PROBLEM_CHARS = 800
MATERIAL_MARK = "<!-- material -->"
EXCLUDED_NAMES = frozenset({"verification.md", "questions.md", "feedback.md"})  # the harness's or a person's input (D3)
ROLE = "judges"
SCRATCH = "yolo"

DigestOf = Callable[[Git, str, str], str]  # (git, rev, unit folder) -> the unit digest (`l4.yolo.digest.unit_digest`)


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
class FolderText:
    path: str
    files: tuple[tuple[str, str], ...]  # (repository path, text), sorted
    omitted: tuple[str, ...] = ()  # what the prompt does not show, and why

    @property
    def empty(self) -> bool:
        return not self.files and not self.omitted


def read_folder(git: Git, rev: str, folder: str, *, budget: int) -> FolderText:
    """The files of `folder` at `rev`, without what the harness writes (`.l4/**`, `verification.md`, `questions.md`,
    `feedback.md`) and without binary files; each file and the folder are cut at a bounded number of characters."""
    root = folder.strip("/")
    listing = git.run_bytes("ls-tree", "-r", "-z", "--name-only", rev, "--", root + "/", check=False)
    files: list[tuple[str, str]] = []
    omitted: list[str] = []
    left = budget
    for raw in sorted(p for p in listing.split(b"\0") if p):
        path = raw.decode("utf-8", "replace")
        relative = PurePosixPath(path).relative_to(root).parts
        if relative[0] == ".l4" or (len(relative) == 1 and relative[0] in EXCLUDED_NAMES):
            continue
        data = git.run_bytes("show", f"{rev}:{path}", check=False)
        if b"\0" in data:
            omitted.append(f"{path}: binary file")
            continue
        text = data.decode("utf-8", "replace")
        shown = text[: min(MAX_FILE_CHARS, max(left, 0))]
        if len(shown) < len(text):
            shown += f"\n[cut: {len(text) - len(shown)} characters omitted]"
            if left <= 0:
                omitted.append(f"{path}: over the size limit of the folder")
                continue
        left -= len(shown)
        files.append((path, shown))
    return FolderText(root, tuple(files), tuple(omitted))


def _folder_blocks(folder: FolderText) -> str:
    blocks = [data_block(path, text) for path, text in folder.files]
    blocks += [f"(not shown: {note})" for note in folder.omitted]
    return "\n\n".join(blocks) or "(the folder has no files)"


def _entry(model: Any) -> str:
    return json.dumps(model.model_dump(by_alias=True), indent=2, sort_keys=True)


@dataclass(frozen=True)
class Subject:
    """One thing to review: its id, its prompt, and (for a unit) the folder that its digest is taken of."""

    kind: str  # "unit" | "batch"
    id: str
    user: str


def _unit_subject(
    plan: Plan, unit: PlanUnit, batch: PlanBatch, folder: FolderText, deps: Sequence[tuple[str, FolderText | None]]
) -> Subject:
    prerequisites = []
    for dep, dep_folder in deps:
        shown = _folder_blocks(dep_folder) if dep_folder is not None else "(its folder is not known)"
        prerequisites.append(f"### {dep}" + (f" ({dep_folder.path})" if dep_folder else "") + f"\n{shown}")
    batch_deps = [f"- batch {b}" for b in batch.depends_on]
    entry = (
        data_block("plan entry", _entry(unit)) + f"\n(in batch {batch.id}; plan {plan.plan_id}, target {plan.target})"
    )
    values = {
        "SUBJECT_KIND": "unit",
        "SUBJECT_ID": unit.id,
        "ENTRY": entry,
        "DEPENDENCIES": "\n\n".join([*prerequisites, *batch_deps]) or "(none: the unit depends on nothing)",
        "FOLDERS": f"### {unit.id} ({folder.path})\n{_folder_blocks(folder)}",
    }
    return Subject("unit", unit.id, _fill(MATERIAL_TEMPLATE, values))


def _batch_subject(plan: Plan, batch: PlanBatch, folders: Mapping[str, FolderText]) -> Subject:
    values = {
        "SUBJECT_KIND": "batch",
        "SUBJECT_ID": batch.id,
        "ENTRY": data_block("plan entry", _entry(batch)) + f"\n(plan {plan.plan_id}, target {plan.target})",
        "DEPENDENCIES": "\n".join(f"- batch {b}" for b in batch.depends_on) or "(none: the batch depends on nothing)",
        "FOLDERS": "\n\n".join(
            f"### {u.id} ({folders[u.id].path})\n{_folder_blocks(folders[u.id])}" for u in batch.units
        ),
    }
    return Subject("batch", batch.id, _fill(MATERIAL_TEMPLATE, values))


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
                return _with_digest(blocked(f"judge_error: {result.detail or result.status}"), digest), cost
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


def _default_digest() -> DigestOf | None:
    try:
        from l4.yolo.digest import unit_digest  # agent A's module; absent until the waves are merged
    except ImportError:
        return None
    return unit_digest  # type: ignore[no-any-return]


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
) -> tuple[ReviewResult, float]:
    """`review_plan` and the cost in dollars the judge reported (what the plan step charges to the plan)."""
    digest_fn = digest_of or _default_digest()
    folders: dict[str, FolderText] = {}
    for unit in plan.units():
        info = units.get(unit.id)
        folders[unit.id] = read_folder(git, rev, info.folder, budget=MAX_FOLDER_CHARS) if info else FolderText("", ())
    subjects: list[tuple[Subject, str | None]] = []
    result_units: dict[str, Verdict] = {}
    result_batches: dict[str, Verdict] = {}
    for batch in plan.batches:
        for unit in batch.units:
            info, folder = units.get(unit.id), folders[unit.id]
            digest = digest_fn(git, rev, info.folder) if digest_fn and info and not folder.empty else None
            if folder.empty:
                note = (
                    f"the folder of {unit.id} has no files at {rev[:10]}" if info else f"{unit.id} is not a known unit"
                )
                result_units[unit.id] = _with_digest(blocked(f"unit_missing: {note}"), digest)
                continue
            deps = [
                (d, read_folder(git, rev, units[d].folder, budget=MAX_DEPENDENCY_CHARS) if d in units else None)
                for d in unit.depends_on
            ]
            subjects.append((_unit_subject(plan, unit, batch, folder, deps), digest))
    for batch in plan.batches:
        if len(batch.units) > 1 and all(not folders[u.id].empty for u in batch.units):
            subjects.append((_batch_subject(plan, batch, folders), None))
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
    admission read of each unit (its folder). A `Verdict.digest` is the unit digest: `digest_of`, else
    `l4.yolo.digest.unit_digest` when that module exists, else None. `sandbox` replaces the selected sandbox."""
    result, _ = review_plan_costed(
        app, cfg, plan, units, git=git, rev=rev, adapters=adapters, digest_of=digest_of, sandbox=sandbox
    )
    return result


__all__ = [
    "READINESS_SCHEMA",
    "FolderText",
    "Subject",
    "read_folder",
    "review_plan",
    "review_plan_costed",
    "verdict_of",
]
