"""The delegate pass (delegate-answers 8.1; L4-DLG-003, 005, 006, 008, 013; design D6, D8, D9).

`delegate_hook` is what the orchestrator calls at the end of a run that leaves a unit in scope in `awaiting_human` (or
`fixing` with a waiting fix unit), after the clarifier and under the unit's lease. It asks once for each open question
of the kinds `delegate.kinds` names, oldest first, at most `delegate.max_questions_per_run`, and for each question:

1. `limit_reached` (attempts, answers per task, the unit's and the plan's cost): a limit is an escalation;
2. the chain `roles.delegate` through the factory with the independence veto of the question's askers; a chain with no
   usable profile defers (every profile cooling with a known end) or escalates (a cause only a fix ends);
3. one call in the adapter's read-only mode, in a detached worktree of the pushed head that the sandbox binds read-only;
4. `check_reply`: a reply that breaks a rule is `discarded` and the question escalates;
5. a kept reply is written by the edit core of `l4 questions` (`build_edit`) on the run's worktree and committed with
   the message of `l4 questions` (`By: delegate (...)`, `Via: l4 delegate`, `[skip ci]`); an escalation writes the line
   `Escalated by:` and leaves the question open.

The run's own close pushes what the pass committed; the pass never calls `_prepare`, `unit_refusal` or `agent_refusal`
(the run's lease stands in for the live-run refusal, and the delegate needs no consent for agents). Every outcome is
recorded: `delegate.asked`, `budget.cost{role: delegate}`, `delegate.result` (with `tasks`, `target`, `cost_usd` and
`called`, which the limits read) and, for an answer, `question.answered{by: delegate}`, so that the next run's
`reenter` finds the digest recorded and writes nothing more."""

import contextlib
import dataclasses
import logging
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from l4.agents.base import PermissionPolicy, RunRequest
from l4.agents.factory import Factory, RoleUnavailable, Selected
from l4.clarifier.actor import answer_actor
from l4.clarifier.clarifier import commit_questions
from l4.clarifier.ports import QuestionView
from l4.config.schema import DelegateCfg, Profile, duration_seconds
from l4.delegate.due import deferred_now, held_ids, is_final, open_questions
from l4.delegate.independence import DELEGATE_SERVES, askers, delegate_constraint, independence_escalation
from l4.delegate.limits import PlanCost, attempts_used, delegate_cost, limit_reached
from l4.delegate.prompt import (
    AnsweredQuestion,
    DelegatePrompt,
    Material,
    build_prompt,
    delegate_schema,
    gate_excerpt,
    harness_material,
    report_test_ids,
    verdict_material,
)
from l4.delegate.reply import Discarded, HeadTree, Kept, check_reply
from l4.delegate.scope import PlansView, in_scope, plan_cost, plans_view
from l4.delegate.settings import DelegateSettings, delegate_settings
from l4.exitcodes import ExitCode, L4Exit
from l4.fsutil import read_regular_file
from l4.implementer.unit_context import prompt_inputs
from l4.implementer.workbench import Workbench, make_workbench
from l4.llm.agent_judge import AgentJudge, Msg, StructuredResult, schema_suffix
from l4.sandbox.env import build_agent_env
from l4.services import HookContext
from l4.specs.questions import (
    QUESTIONS_FILENAME,
    Question,
    QuestionKind,
    QuestionsFile,
    answer_sha256,
    effective_answer,
    is_answered,
)
from l4.specs.questions_cli import (
    DelegateMark,
    build_edit,
    commit_message,
    existing_tests,
    folder_from_worktree,
    frozen_paths,
    round_trip,
)
from l4.state.fold import fold, question_key
from l4.state.ledger import LedgerEvent, ledger_path, read_ledger
from l4.vcs.trailers import CommitTrailers
from l4.verifier.evidence import read_verdict
from l4.verifier.verdicts import hold_kind

log = logging.getLogger("l4.delegate")

RETRY_AFTER_S = 300  # a timeout or an adapter error: the question is taken again after this long
MAX_TURNS = 40  # `--max-turns` of the Claude Code read-only run
ESCALATED_CHARS = 300  # the `Escalated by:` line: the reason, redacted, at most this long
MAX_VERIFICATION_BYTES = 400_000


@dataclass(frozen=True)
class DelegateOutcome:
    """What the pass did, by question key (`Q-003`, or `<fix unit>/Q-003`). `start_run`: the run must ask the forge for
    the next run on the base (an answer was pushed, or the soft deadline cut the pass: L4-DLG-007, SCN-DLG-12)."""

    answered: tuple[str, ...] = ()
    escalated: tuple[str, ...] = ()
    deferred: tuple[str, ...] = ()
    start_run: bool = False


@dataclass
class _Target:
    """One `questions.md` the pass reads: the unit's, or the open fix unit's."""

    path: Path  # the folder that holds the file
    rel: str  # ... relative to the worktree
    fix: str | None
    unit: str  # the id shown: the unit's, or `<framework>:<fix unit>`
    questions: list[Question] = field(default_factory=list)


@dataclass
class _Reply:
    """What one call came to: the structured document, or why there is none."""

    status: str  # ok | schema_invalid | timeout | error | limit
    parsed: dict[str, Any] | None = None
    detail: str = ""
    cost: float | None = None
    model: str | None = None
    run: Any = None  # the agent run, for the factory's `on_limit`


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def decided(events: Sequence[LedgerEvent], key: str, now: datetime) -> bool:
    """The question has a final delegate record for its current raise, or a deferral that is still in the future."""
    return is_final(events, key) or deferred_now(events, key, now)


class _Pass:
    def __init__(self, ctx: HookContext, settings: DelegateSettings) -> None:
        self.ctx, self.s, self.cfg = ctx, ctx.services, settings.delegate
        # `roles.delegate` and the profiles it names are the base branch's, like the rest of the section (L4-DLG-001)
        self.profiles = dict(settings.profiles)
        base = ctx.cfg.model_copy(
            update={"profiles": self.profiles, "roles": ctx.cfg.roles.model_copy(update={"delegate": settings.chain})}
        )
        self.chain = settings.chain
        self.factory = ctx.services.factory.with_config(base)
        self.answered: list[str] = []
        self.escalated: list[str] = []
        self.deferred: list[str] = []
        self.start_run = False
        self.benches: list[Workbench] = []
        self.logs: list[tuple[Path, Path]] = []
        self.tree: Path | None = None
        self.head = ""
        self.heads: dict[str, HeadTree] = {}
        self.calls = 0
        self.view: PlansView | None = None  # the plans, read once for the cost share

    # -- what to ask ---------------------------------------------------------------------------------------------

    def _events(self) -> list[LedgerEvent]:
        return list(read_ledger(self.s.ref.path).events)

    def _now(self) -> datetime:
        return self.s.factory.now()

    def _targets(self) -> list[_Target]:
        s = self.s
        root = s.worktree.resolve()
        state = fold(self._events(), s.ref.id)
        out = []
        file = QuestionsFile.load(s.ref.path / QUESTIONS_FILENAME)
        if file is not None:
            tasks = s.provider.tasks(s.ref)
            held = held_ids(file, tasks, state.verdicts_consumed, verdicts=True)
            out.append(_Target(s.ref.path, s.ref.path.resolve().relative_to(root).as_posix(), None, s.ref.id))
            out[0].questions = open_questions(file, held, self.cfg)
        if state.phase == "fixing" and state.open_fix_unit:
            from l4.verifier.fixloop import family_of

            family = family_of(self.ctx)
            fix = next((r for r in family.units()[1:] if r.name == state.open_fix_unit), None)
            ffile = QuestionsFile.load(fix.path / QUESTIONS_FILENAME) if fix is not None else None
            if fix is not None and ffile is not None:
                tasks = family.tasks(fix)
                held = held_ids(ffile, tasks, (), verdicts=False)
                target = _Target(
                    fix.path, fix.path.resolve().relative_to(root).as_posix(), fix.name,
                    f"{s.ref.id.partition(':')[0]}:{fix.name}",
                )  # fmt: skip
                target.questions = open_questions(ffile, held, self.cfg)
                out.append(target)
        return [t for t in out if t.questions]

    @staticmethod
    def _key(target: _Target, question: Question) -> str:
        return question.id if target.fix is None else f"{target.fix}/{question.id}"

    # -- the pass ------------------------------------------------------------------------------------------------

    def run(self) -> DelegateOutcome:
        events = self._events()
        now = self._now()
        work = [
            (t, q) for t in self._targets() for q in t.questions if not decided(events, self._key(t, q), now)
        ]  # fmt: skip
        if not work:
            return DelegateOutcome()
        s = self.s
        state = fold(events, s.ref.id)
        commit_questions(s, phase=state.phase, iteration=state.iteration, what="delegate")
        self.ctx.push()  # the head the delegate reads, and its claims resolve at, is the one on origin
        self.head = s.git.rev_parse("HEAD") or ""
        try:
            for target, question in work:
                if self.calls >= self.cfg.max_questions_per_run:
                    break
                self._question(target, question)
        finally:
            self._cleanup()
        return DelegateOutcome(
            tuple(self.answered), tuple(self.escalated), tuple(self.deferred), self.start_run or bool(self.answered)
        )

    def _cleanup(self) -> None:
        if self.tree is not None:
            self.s.git.run("worktree", "remove", "--force", str(self.tree), check=False)
            shutil.rmtree(self.tree, ignore_errors=True)
            self.s.git.run("worktree", "prune", check=False)
        if self.benches:
            for raw, published in self.logs:
                self.benches[0].publish_agent_logs(raw, published)
        for wb in self.benches:
            wb.restore_ledger()

    def _soft_deadline(self) -> bool:
        left = self.ctx.shared.get("job_remaining_s")
        remaining = left() if callable(left) else None
        return remaining is not None and remaining < duration_seconds(self.cfg.timeout)

    def _question(self, target: _Target, question: Question) -> None:
        events = self._events()
        key = self._key(target, question)
        raised = next((e for e in reversed(events) if e.type == "question.raised" and question_key(e) == key), None)
        verdict_target = str(raised.data["target"]) if raised and question.kind is QuestionKind.VERDICT else None
        shared = dict(tasks=list(question.blocking_tasks), target=verdict_target, kind=question.kind.value)  # type: ignore[union-attr]
        if self._soft_deadline():
            self.calls += 1
            self._defer(target, key, shared, "soft_deadline", self._now())
            self.start_run = True
            return
        plan = self._plan_cost(events)
        if (reason := limit_reached(key, question.blocking_tasks, verdict_target, events, plan, self.cfg)) is not None:
            self._escalate(target, question, key, shared, reason, who=None)
            return
        try:
            selected = select_delegate(self.factory, self.s.ref.id, events, key, self.cfg, self.profiles)
        except RoleUnavailable as exc:
            self._unavailable(target, question, key, shared, exc)
            return
        self.calls += 1
        self._ask(target, question, key, shared, selected, raised)

    # -- one call ------------------------------------------------------------------------------------------------

    def _ask(
        self, target: _Target, question: Question, key: str, shared: dict[str, Any], selected: Selected,
        raised: LedgerEvent | None,
    ) -> None:  # fmt: skip
        s = self.s
        events = self._events()
        folder_head = self._head_tree(target)
        for _ in range(len(self.chain) + 1):  # a limit moves to the next profile of the chain
            prompt = self._prompt(target, question, key, events, selected, raised)
            model = selected.profile.model
            s.ledger.append(
                "delegate.asked", question=key, kind=shared["kind"], profile=selected.profile_name, model=model,
                prompt_sha256=prompt.sha256, **({"fix_unit": target.fix} if target.fix else {}),
            )  # fmt: skip
            reply = self._call(selected, prompt, key)
            if reply.status != "limit":
                break
            try:
                selected = self.factory.on_limit(selected, reply.run)
            except RoleUnavailable as exc:
                self._record_cost(key, selected, reply)
                self._unavailable(target, question, key, shared, exc, called=True, cost=reply.cost)
                return
        self._record_cost(key, selected, reply)
        if reply.status == "limit":  # the chain is out of profiles that were not limited in this pass
            reply = dataclasses.replace(reply, status="error", detail="limit")
        who = (reply.model or selected.profile.model or selected.profile_name, selected.profile.adapter or "", selected)
        if reply.status in ("timeout", "error"):
            spent = attempts_used(events, key)
            if spent + 1 >= self.cfg.max_attempts_per_question:
                self._escalate(
                    target, question, key, shared, f"delegate attempts used ({spent + 1})", who=who, called=True,
                    cost=reply.cost,
                )  # fmt: skip
            else:
                self._defer(
                    target, key, shared, reply.status, self._now() + timedelta(seconds=RETRY_AFTER_S), who, reply
                )
            return
        verdict = self._verdict(target)
        material = self._material_hold(question, key, raised, verdict)
        kept = (
            check_reply(
                reply.parsed or {},
                question,
                self._file(target),
                head=folder_head,
                test_ids=report_test_ids(verdict),
                frozen=self._frozen(events, target, question),
                unit=target.unit,
                branch=s.names.branch,
                redactor=s.app.redactor,
                hold_kind=material,
                unfreeze=self.cfg.unfreeze,
                existing=self._existing(events, target, question),
            )
            if reply.status == "ok"
            else Discarded(f"not an l4/delegate-result@1 document: {reply.detail}")
        )
        if isinstance(kept, Discarded):
            self._escalate(
                target, question, key, shared, kept.reason, who=who, called=True, cost=reply.cost, status=kept.status
            )  # fmt: skip
        elif kept.escalates:
            self._escalate(
                target, question, key, shared, kept.reason or "the delegate could not check the claim", who=who,
                called=True, cost=reply.cost, status="escalated", decision="escalate", checked=kept.checked,
            )  # fmt: skip
        else:
            self._answer(target, question, key, shared, kept, who, reply)

    def _call(self, selected: Selected, prompt: DelegatePrompt, key: str) -> _Reply:
        s = self.s
        wb = self._bench(selected)
        tree = self._detached()
        judge = AgentJudge(
            selected.impl, self._requests(wb, selected, tree), events=s.ledger, role="delegate",
            profile=selected.profile_name,
        )  # fmt: skip
        try:
            done: StructuredResult = judge.complete_structured(
                prompt.system, [Msg("user", prompt.user)], delegate_schema(), effort=None, max_tokens=0,
                timeout_s=duration_seconds(self.cfg.timeout),
            )  # fmt: skip
        except L4Exit:
            raise
        except Exception as exc:  # noqa: BLE001 - an adapter failure is a deferral, the run does not crash
            log.warning("%s: the delegate call failed: %s", key, type(exc).__name__)
            log.debug("%s: the delegate call failed", key, exc_info=True)
            return _Reply("error", detail=type(exc).__name__)
        cost = done.usage.cost_usd if done.usage is not None else None
        return _Reply(done.status, done.parsed, done.detail, cost, done.model_resolved, done.run)

    def _requests(self, wb: Workbench, selected: Selected, tree: Path):
        spec = dataclasses.replace(wb.agent_spec(), worktree=tree, worktree_read_only=True)
        extra = dict(getattr(wb.impl, "extra_env", {}))
        caps = wb.impl.capabilities()
        budget = self.cfg.max_cost_usd_per_answer if caps.budget_cap else None

        def make(prompt: str, schema: dict[str, Any], timeout_s: int) -> RunRequest:
            tmp = wb.reset_agent_tmp()
            raw, published = wb.agent_log_paths(f"delegate-{len(self.logs) + 1}")
            self.logs.append((raw, published))
            wb.publish_prompt(published, prompt.removesuffix(schema_suffix(schema)))
            return RunRequest(
                profile=selected.profile, role="delegate", cwd=tree, prompt=prompt, result_path=tmp / "result.json",
                raw_events_path=raw, env=build_agent_env(wb.host_env, spec, extra=extra), result_schema=schema,
                permission_policy=PermissionPolicy("read_only"), timeout_s=timeout_s, max_turns=MAX_TURNS,
                max_budget_usd=budget, wrap=lambda argv, env, cwd=None: wb.sandbox.wrap(argv, spec, env, cwd),
                host_env=wb.host_env,
            )  # fmt: skip

        return make

    def _bench(self, selected: Selected) -> Workbench:
        s = self.s
        state = fold(self._events(), s.ref.id)
        wb = make_workbench(
            cfg=self.ctx.cfg, app=s.app, ref=s.ref, provider=s.provider, worktree=s.worktree, git=s.git,
            ledger=s.ledger, sandbox=s.sandbox, selected=selected, iteration=state.iteration, push=self.ctx.push,
        )  # fmt: skip
        self.benches.append(wb)
        return wb

    def _detached(self) -> Path:
        """A detached worktree of the pushed head, in the unit's private cache, removed after the pass."""
        if self.tree is None:
            base = self.benches[-1].unit_cache / "delegate-tree"
            shutil.rmtree(base, ignore_errors=True)
            self.s.git.run("worktree", "add", "--detach", "--quiet", str(base), self.head)
            self.tree = base
        return self.tree

    # -- the prompt ----------------------------------------------------------------------------------------------

    def _file(self, target: _Target) -> QuestionsFile:
        file = QuestionsFile.load(target.path / QUESTIONS_FILENAME)
        assert file is not None
        return file

    def _head_tree(self, target: _Target) -> HeadTree:
        if target.rel not in self.heads:
            self.heads[target.rel] = HeadTree.at(self.s.git, self.head, target.rel)
        return self.heads[target.rel]

    def _verdict(self, target: _Target) -> dict[str, Any]:
        root = target.path / ".l4" / "evidence"
        numbers = (p.name.removeprefix("round-") for p in root.glob("round-*"))
        rounds = sorted((int(n) for n in numbers if n.isdigit()), reverse=True)
        for number in rounds:
            if (found := read_verdict(target.path, number)) is not None:
                return found
        return {}

    def _material_hold(
        self, question: Question, key: str, raised: LedgerEvent | None, verdict: dict[str, Any]
    ) -> str | None:  # fmt: skip
        """The kind of the hold a verdict question is about (None: a criterion, a finding, or not a verdict)."""
        if question.kind is not QuestionKind.VERDICT or raised is None:
            return None
        found = verdict_material(verdict, "", str(raised.data.get("target") or ""))
        return hold_kind(found.text.removeprefix(f"{found.target} ")) if found and found.kind == "hold" else None

    def _prompt(
        self, target: _Target, question: Question, key: str, events: Sequence[LedgerEvent], selected: Selected,
        raised: LedgerEvent | None,
    ) -> DelegatePrompt:  # fmt: skip
        s, cfg = self.s, self.ctx.cfg
        file = self._file(target)
        view = QuestionView.of(question)
        tasks = s.provider.tasks(s.ref)
        task = next((t for t in tasks if t.key in question.blocking_tasks), tasks[0] if tasks else None)
        sources: tuple = ()
        conventions: tuple = ()
        if task is not None:
            inputs = prompt_inputs(
                root=s.worktree, provider=s.provider, ref=s.ref, task=task, tasks=tasks, changed=[], cfg=cfg,
                profile_name=selected.profile_name, profile=selected.profile,
            )  # fmt: skip
            sources, conventions = inputs.source_files, inputs.conventions
        git = s.git.at(target.path)
        answered = tuple(
            AnsweredQuestion(q.id, answer_actor(git, target.path, q, events).by, effective_answer(q) or "")
            for q in file.questions
            if is_answered(q) and q.id != question.id
        )  # fmt: skip
        verdict = harness = None
        if question.kind is QuestionKind.VERDICT and raised is not None:
            md = _read_text(target.path / "verification.md")
            verdict = verdict_material(self._verdict(target), md, str(raised.data.get("target") or ""))
        if question.kind is QuestionKind.HARNESS:
            harness = harness_material(events, question.id)
        material = Material(
            sources, conventions, answered, verdict, harness, gate_excerpt(events, task.key if task else None)
        )  # fmt: skip
        return build_prompt(
            view, material, budget_tokens=cfg.implementer.context_budget_tokens, redact=s.app.redactor.redact_text
        )  # fmt: skip

    def _frozen(self, events: Sequence[LedgerEvent], target: _Target, question: Question) -> dict[str, tuple[str, ...]]:
        return frozen_paths(events, question.blocking_tasks, target.fix)

    def _existing(
        self, events: Sequence[LedgerEvent], target: _Target, question: Question
    ) -> dict[str, tuple[str, ...]]:
        frozen = self._frozen(events, target, question)
        try:
            return existing_tests(self.s.git, self._folder(target), self.ctx.cfg, question, frozen)
        except L4Exit:
            return {}

    def _folder(self, target: _Target):
        s = self.s
        state = fold(self._events(), s.ref.id)
        ledger_rel = s.ref.path.resolve().relative_to(s.worktree.resolve()).as_posix()
        return folder_from_worktree(
            s.git, s.worktree, target.unit, target.rel, ledger_rel, s.names.branch, state.phase or "", target.fix
        )  # fmt: skip

    def _plan_cost(self, events: Sequence[LedgerEvent]) -> PlanCost | None:
        try:
            if self.view is None:
                self.view = plans_view(self.s.app.repo, self.ctx.cfg, self.s.git)
            return plan_cost(self.view, self.s.ref.id, lambda unit: self._unit_delegate_cost(unit, events))
        except Exception as exc:  # noqa: BLE001 - the plan's share is a bound, never a reason to stop the pass
            log.warning("the plan's delegate cost could not be read: %s", type(exc).__name__)
            log.debug("plan cost", exc_info=True)
            return None

    def _unit_delegate_cost(self, unit: str, events: Sequence[LedgerEvent]) -> float:
        from l4.state.status import load_snapshot

        if unit == self.s.ref.id:
            return delegate_cost(events, self.cfg.max_cost_usd_per_answer)
        s = self.s
        for provider in [s.provider]:
            ref = next((r for r in provider.list_units() if r.id == unit), None)
            if ref is not None:
                snap = load_snapshot(provider, s.git, ref, branch_prefix=self.ctx.cfg.forge.branch_prefix)
                return delegate_cost(snap.events, self.cfg.max_cost_usd_per_answer)
        return 0.0

    # -- the records ---------------------------------------------------------------------------------------------

    def _record_cost(self, key: str, selected: Selected, reply: _Reply) -> None:
        if reply.cost:
            self.s.ledger.append(
                "budget.cost", usd=reply.cost, profile=selected.profile_name, role="delegate", question=key
            )  # fmt: skip

    def _result(
        self, target: _Target, key: str, shared: dict[str, Any], status: str, *, reason: str, who: Any = None,
        called: bool = False, cost: float | None = None, **more: Any,
    ) -> None:  # fmt: skip
        data: dict[str, Any] = dict(
            question=key, id=key.rpartition("/")[2], status=status, reason=reason, called=called
        )
        data |= shared
        if who is not None:
            data |= dict(profile=who[2].profile_name, model=who[0], cli=who[1])
        if called:
            data["cost_usd"] = cost
        if target.fix:
            data["fix_unit"] = target.fix
        self.s.ledger.append("delegate.result", **data, **more)

    def _line_who(self, who: Any) -> str:
        return f"the delegate ({who[0]} via {who[1]})" if who is not None else "the delegate"

    def _defer(
        self, target: _Target, key: str, shared: dict[str, Any], why: str, retry_after: datetime, who: Any = None,
        reply: _Reply | None = None,
    ) -> None:  # fmt: skip
        called = reply is not None
        self._result(
            target, key, shared, "deferred", reason=why, who=who, called=called, cost=reply.cost if reply else None,
            retry_after=_iso(retry_after),
        )  # fmt: skip
        self.deferred.append(key)
        log.info("%s: the delegate defers (%s) until %s", key, why, _iso(retry_after))

    def _unavailable(
        self, target: _Target, question: Question, key: str, shared: dict[str, Any], exc: RoleUnavailable,
        *, called: bool = False, cost: float | None = None,
    ) -> None:  # fmt: skip
        """No usable profile: independence, an empty chain or a cause only a fix ends is an escalation; every profile
        cooling with a known end is a deferral (L4-DLG-013)."""
        if (why := independence_escalation(exc)) is not None:
            self._escalate(target, question, key, shared, why, who=None, called=called, cost=cost)
            return
        text = str(exc).partition(" is unavailable: ")[2] or str(exc)
        retry = getattr(exc, "retry_after", None) or self._cooling_until()
        if retry is not None:
            self._defer(target, key, shared, "cooling", retry)
            return
        reason = text if not exc.steps else f"no delegate profile is usable: {text}"
        self._escalate(target, question, key, shared, reason, who=None, called=called, cost=cost)

    def _cooling_until(self) -> datetime | None:
        """The earliest end of a cool-down among the profiles the latest `availability.unavailable` skipped."""
        latest = next((e for e in reversed(self._events()) if e.type == "availability.unavailable"), None)
        ends: list[datetime] = []
        for item in (latest.data.get("skipped") or []) if latest else []:
            if isinstance(item, dict) and item.get("step") == "cooling" and item.get("resets_at"):
                with contextlib.suppress(ValueError):
                    ends.append(datetime.fromisoformat(str(item["resets_at"]).replace("Z", "+00:00")))
        return min(ends) if ends else None

    def _escalate(
        self, target: _Target, question: Question, key: str, shared: dict[str, Any], reason: str, *, who: Any,
        called: bool = False, cost: float | None = None, status: str = "escalated", decision: str | None = None,
        checked: Sequence[Any] = (),
    ) -> None:  # fmt: skip
        """The question stays open: `delegate.result` and the line `Escalated by:`, committed with the ledger."""
        s = self.s
        shown = s.app.redactor.redact_text(" ".join(reason.split()))[:ESCALATED_CHARS]
        more: dict[str, Any] = {}
        if decision:
            more["decision"] = decision
        if checked:
            more["checked"] = [dict(c) for c in checked]
        self._result(target, key, shared, status, reason=shown, who=who, called=called, cost=cost, **more)
        path = target.path / QUESTIONS_FILENAME
        file = self._file(target)
        line = f"{self._line_who(who)}: {shown}"
        edited = file.set_field(question.id, "Escalated by", line)
        edited.save(path)
        self._commit(target, question, "escalate", "open", who, key)
        self.escalated.append(key)
        log.info("%s: the delegate escalates: %s", key, shown)

    def _answer(
        self, target: _Target, question: Question, key: str, shared: dict[str, Any], kept: Kept,
        who: Any, reply: _Reply,
    ) -> None:  # fmt: skip
        s = self.s
        model, cli, selected = who
        try:
            folder = self._folder(target)
            edit = build_edit(kept.form or "answer", folder, question.id, kept.text, redactor=s.app.redactor)
            line = self._line_who(who).removeprefix("the delegate ")
            new = edit.new.set_field(question.id, "Answered by", f"the delegate {line}")
            if why := round_trip(edit.old, new, question.id, edit.status, kept.text if edit.form == "answer" else None):
                raise L4Exit(ExitCode.USAGE_ERROR, why)
        except L4Exit as exc:  # a refusal of the edit core is an escalation, the question stays open
            self._escalate(
                target, question, key, shared, f"the answer could not be written: {exc}", who=who, called=True,
                cost=reply.cost,
            )  # fmt: skip
            return
        answered = new.get(question.id)
        digest = answer_sha256(answered) if answered is not None else None
        mark = DelegateMark(model, cli, selected.profile_name)
        self._result(
            target, key, shared, "answered", reason=kept.reason, who=who, called=True, cost=reply.cost,
            decision=kept.decision, answer_sha256=digest, checked=[dict(c) for c in kept.checked],
        )  # fmt: skip
        s.ledger.append(
            "question.answered", id=question.id, by="delegate", profile=selected.profile_name, model=model,
            answer_sha256=digest, **({"fix_unit": target.fix} if target.fix else {}),
        )  # fmt: skip
        new.save(target.path / QUESTIONS_FILENAME)
        self._commit(target, question, edit.form, edit.status.value, who, key, edit=edit, mark=mark)
        self.answered.append(key)
        self.start_run = True
        log.info("%s: the delegate answered (%s)", key, kept.decision)

    def _commit(
        self, target: _Target, question: Question, what: str, status: str, who: Any, key: str, *, edit: Any = None,
        mark: DelegateMark | None = None,
    ) -> None:  # fmt: skip
        """`questions.md` and the run's ledger so far, as one commit of the run (its identity and trailers)."""
        s = self.s
        root = s.worktree.resolve()
        state = fold(self._events(), s.ref.id)
        paths = [target.path / QUESTIONS_FILENAME, ledger_path(s.ref.path, s.app.run_id)]
        s.git.run("add", "--", *(p.resolve().relative_to(root).as_posix() for p in paths if p.exists()))
        if edit is not None and mark is not None:
            message = commit_message(edit, "", "delegate", None, mark=mark)
        else:
            unit = target.unit.partition(":")[2] or target.unit
            title = " ".join(question.title.split())[:60].rstrip()
            by = f"delegate ({who[0]} via {who[1]}; profile {who[2].profile_name})" if who else "delegate (no call)"
            message = (
                f"{what} {question.id} ({unit}): {title}\n\nStatus: {status}\nBy: {by}\nVia: l4 delegate\n[skip ci]\n"
            )
        trailers = CommitTrailers(
            unit=s.ref.id, run_id=s.app.run_id, iteration=max(state.iteration, 1), phase=state.phase or "intake"
        )  # fmt: skip
        s.git.commit(message, trailers)


def _read_text(path: Path) -> str:
    try:
        return read_regular_file(path, limit=MAX_VERIFICATION_BYTES).decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - the section is a help for the delegate, not a requirement
        return ""


def select_delegate(
    factory: Factory,
    unit: str,
    events: Sequence[LedgerEvent],
    key: str,
    cfg: DelegateCfg,
    profiles: Mapping[str, Profile],
) -> Selected:
    """The first usable profile of `roles.delegate` that is neither an asker of the question `key` nor a judge of it
    (L4-DLG-002): each question has its own askers, so each gets its own constraint. `RoleUnavailable` when none is."""
    constraint = delegate_constraint(askers(events, key), cfg.independence, profiles=profiles)
    return factory.for_role("delegate", unit, serves=DELEGATE_SERVES, constraints=[constraint])


def delegate_hook(ctx: HookContext) -> DelegateOutcome:
    """The orchestrator's `delegate` hook (`l4.delegate.run:delegate_hook`). Nothing is written, read or committed while
    the base branch does not enable the delegate (L4-DLG-001)."""
    s = ctx.services
    settings = delegate_settings(s.git, ctx.cfg.forge.base_branch)
    if not settings.delegate.enabled:
        return DelegateOutcome()
    phase = fold(read_ledger(s.ref.path).events, s.ref.id).phase
    view = plans_view(s.app.repo, ctx.cfg, s.git)
    if not in_scope(s.ref.id, view, settings.delegate, phase=phase):
        return DelegateOutcome()
    return _Pass(ctx, settings).run()
