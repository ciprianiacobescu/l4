"""The delegate pass (delegate-answers 8.1; L4-DLG-003, 005, 006, 008, 013; design D6, D8, D9).

`delegate_hook` is what the orchestrator calls at the end of a run that leaves a unit in scope in `awaiting_human` (or
`fixing` with a waiting fix unit), after the clarifier and under the unit's lease. It asks once for each open question
of the kinds `delegate.kinds` names, oldest first, and for each question:

1. `limit_reached` (attempts, answers per task, the unit's and the plan's cost): a limit is an escalation;
2. the chain `roles.delegate` through the factory with the independence veto of the question's askers; a chain with no
   usable profile defers (every profile cooling with a known end) or escalates (a cause only a fix ends);
3. one call in the adapter's read-only mode, in a detached worktree of the pushed head that the sandbox binds read-only;
4. `check_reply`: a reply that breaks a rule is `discarded` and the question escalates;
5. a kept reply is written by the edit core of `l4 questions` (`build_edit`) on the run's worktree and committed with
   the message of `l4 questions` (`By: delegate (...)`, `Via: l4 delegate`, `[skip ci]`); an escalation writes the line
   `Escalated by:` and leaves the question open.

The pass at the end of a run that did work for the unit asks at most `delegate.max_questions_per_run`; a run that exists
for the delegate (no step of the unit ran before the pass: `idle_run` in `HookContext.shared`) asks until no question is
due, the first deferral for lack of time ends it (the rest are asked by the next run) or a cost limit escalates it.
`delegate.pass` records which bound applied (`cap`, `none_due`, `deadline`, `cost`).

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
from l4.agents.opencode import mask_instruction_files
from l4.clarifier.actor import answer_actor
from l4.clarifier.clarifier import commit_questions
from l4.clarifier.ports import QuestionView
from l4.config.schema import DelegateCfg, Profile, duration_seconds
from l4.delegate.due import deferred_now, held_ids, is_final, open_questions
from l4.delegate.independence import DELEGATE_SERVES, askers, delegate_constraint, independence_escalation
from l4.delegate.kinds import kinds_constraint
from l4.delegate.limits import (
    MAX_SOFT_DEFERRALS,
    PlanCost,
    attempts_used,
    batch_failed,
    delegate_cost,
    is_cost_reason,
    last_discard,
    limit_reached,
    soft_deferrals_in_a_row,
)
from l4.delegate.prompt import (
    BATCH_MAX_CHARS,
    AnsweredQuestion,
    DelegatePrompt,
    Material,
    VerdictMaterial,
    batch_schema,
    build_batch_prompt,
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
from l4.implementer.unfreeze import NOTE_PREFIX
from l4.implementer.unit_context import prompt_inputs
from l4.implementer.workbench import Workbench, make_workbench
from l4.llm.agent_judge import AgentJudge, Msg, StructuredResult, strip_suffix
from l4.sandbox.env import build_agent_env
from l4.services import HookContext
from l4.specs.questions import (
    QUESTIONS_FILENAME,
    Question,
    QuestionKind,
    QuestionsFile,
    QuestionStatus,
    accept_text,
    answer_sha256,
    effective_answer,
    is_answered,
    unescape_text,
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
BATCH_TURNS = 20  # ... and the turns each question after the first adds to a batch's run (L4-DLG-028)
MAX_BATCH_TURNS = 140
ESCALATED_CHARS = 300  # the `Escalated by:` line: the reason, redacted, at most this long
MAX_VERIFICATION_BYTES = 400_000
# the adapters whose agent may load an instruction file from the directory of a file it reads (L4-DLG-016, D4)
MASKED_TREE_ADAPTERS = ("opencode", "copilot-cli")
CHORE_NOTE = f"{NOTE_PREFIX} this is a fix task."  # the first sentence of `chore_question_note`


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
    credits: float | None = None  # plan credits (Kiro): a different unit from dollars, never converted (L4-DLG-020)
    credits_source: str | None = None


@dataclass
class _Item:
    """A question that passed its checks and waits for its call: the question as the file has it now, its key, what
    every `delegate.result` of it records (`shared`) and the event that raised it."""

    question: Question
    key: str
    shared: dict[str, Any]
    raised: LedgerEvent | None


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
        self.implementers = tuple(ctx.cfg.roles.implementer)  # the askers of a verdict, when the ledger names none
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
        self.masked_tree: Path | None = None  # an masked-tree delegate's worktree (see `_detached`)
        self.head = ""
        self.heads: dict[str, HeadTree] = {}
        self.calls = 0  # questions asked (a batch adds its size): `max_questions_per_run` bounds them
        self.adapter_calls = 0  # calls made to an adapter, recorded by `delegate.pass`
        self.only = False  # no step of the unit ran in this run before the pass: it is not bound by the cap
        self.bound: str | None = None  # what ended the pass first: deadline | cost | cap (else none_due)
        self.late = False  # a question was deferred for lack of time: an uncapped pass asks no further question
        self.unpriced = 0  # calls of the question being asked that hit a limit and reported no cost
        self.credits = 0.0  # plan credits of the calls made for the question being asked
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
            held = held_ids(file, tasks, state.verdicts_consumed, verdicts=True, raised=state.verdicts_raised)
            out.append(_Target(s.ref.path, s.ref.path.resolve().relative_to(root).as_posix(), None, s.ref.id))
            out[0].questions = open_questions(file, held, self.cfg)
        if state.phase == "fixing" and state.open_fix_unit:
            from l4.verifier.fixloop import family_of

            family = family_of(self.ctx)
            fix = next((r for r in family.units()[1:] if r.name == state.open_fix_unit), None)
            ffile = QuestionsFile.load(fix.path / QUESTIONS_FILENAME) if fix is not None else None
            if fix is not None and ffile is not None:
                tasks = family.tasks(fix)
                held = held_ids(ffile, tasks, (), verdicts=False, raised=())
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
        idle = self.ctx.shared.get("idle_run")
        self.only = bool(idle()) if callable(idle) else False
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
        done: set[int] = set()  # the work indices a batch took or put back: a batch takes questions after its first
        try:
            for i, (target, question) in enumerate(work):
                if i in done:
                    continue
                if not self.only and self.calls >= self.cfg.max_questions_per_run:
                    self.bound = self.bound or "cap"
                    break
                if question.kind is QuestionKind.VERDICT and self.cfg.batch_size > 1:
                    self._batched(work, i, done)
                else:
                    self._question(target, question)
                if self.only and self.late:  # the rest wait for the next run, which the deferral asks for
                    break
            self.s.ledger.append(
                "delegate.pass", bound=self.bound or "none_due", delegate_only=self.only, calls=self.adapter_calls
            )
        finally:
            self._cleanup()
        return DelegateOutcome(
            tuple(self.answered), tuple(self.escalated), tuple(self.deferred), self.start_run or bool(self.answered)
        )

    def _cleanup(self) -> None:
        trees = [tree for tree in (self.tree, self.masked_tree) if tree is not None]
        for tree in trees:
            self.s.git.run("worktree", "remove", "--force", str(tree), check=False)
            shutil.rmtree(tree, ignore_errors=True)
        if trees:
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

    def _current(self, target: _Target, question: Question) -> Question | None:
        """The question as `questions.md` of the worktree has it now, or None when it is no longer open. The pass pushes
        before it asks, and that push can merge a person's answer (L4-RACE-001): a question read before it may be
        answered by now, and then there is nothing to ask, no call to pay for and no section to write into."""
        file = QuestionsFile.load(target.path / QUESTIONS_FILENAME)
        found = file.get(question.id) if file is not None else None
        return found if found is not None and found.status is QuestionStatus.OPEN else None

    def _question(self, target: _Target, question: Question) -> None:
        """One question on its own: its checks, then its call (every kind but a batched verdict question)."""
        if (item := self._prechecks(target, question)) is not None:
            self._ask_one(target, item)

    def _prechecks(self, target: _Target, question: Question) -> "_Item | None":
        """The checks a question passes before any call, in their order: still open (`_current`), `limit_reached`
        (an escalation), a question no call can settle (an escalation). None: it was dropped or escalated here."""
        if (current := self._current(target, question)) is None:
            return None
        question = current
        events = self._events()
        key = self._key(target, question)
        raised = next((e for e in reversed(events) if e.type == "question.raised" and question_key(e) == key), None)
        verdict_target = str(raised.data["target"]) if raised and question.kind is QuestionKind.VERDICT else None
        shared = dict(tasks=list(question.blocking_tasks), target=verdict_target, kind=question.kind.value)  # type: ignore[union-attr]
        plan = self._plan_cost(events)
        if (reason := limit_reached(key, question.blocking_tasks, verdict_target, events, plan, self.cfg)) is not None:
            self.bound = self.bound or ("cost" if is_cost_reason(reason) else None)
            self._escalate(target, question, key, shared, reason, who=None)
            return None
        if (why := self._without_a_call(target, question, raised)) is not None:
            self._escalate(target, question, key, shared, why, who=None)  # no call could settle it (L4-DLG-024)
            return None
        return _Item(question, key, shared, raised)

    def _defer_for_time(self, target: _Target, item: "_Item") -> None:
        """No call, no attempt (L4-DLG-013); the runs it asks for are bounded (L4-DLG-026)."""
        self.calls += 1
        self.bound = self.bound or "deadline"
        self.late = True
        in_a_row = soft_deferrals_in_a_row(self._events(), item.key) + 1
        self._defer(target, item.key, item.shared, "soft_deadline", self._now())
        if in_a_row < MAX_SOFT_DEFERRALS:  # the third in a row waits for the next scheduled or pushed run
            self.start_run = True

    def _ask_one(self, target: _Target, item: "_Item") -> None:
        """The soft deadline, the selection of a profile with the question's own askers, and the call."""
        if self._soft_deadline():
            self._defer_for_time(target, item)
            return
        self._select_and_ask(target, item)

    def _select_and_ask(self, target: _Target, item: "_Item") -> None:
        try:
            selected = select_delegate(
                self.factory, self.s.ref.id, self._events(), item.key, self.cfg, self.profiles, self.implementers,
                kind=item.question.kind.value,  # type: ignore[union-attr]
            )  # fmt: skip
        except RoleUnavailable as exc:
            self._unavailable(target, item.question, item.key, item.shared, exc)
            return
        self.calls += 1
        self._ask(target, item.question, item.key, item.shared, selected, item.raised)

    # -- a batch (L4-DLG-028) -------------------------------------------------------------------------------------

    def _batch_keys(self, events: Sequence[LedgerEvent], target: _Target, question: Question) -> set[str]:
        """What `answers_used` counts a question under: the tasks it blocks, else its verdict target. Two questions that
        share a key do not share a call."""
        if question.blocking_tasks:
            return {str(t) for t in question.blocking_tasks}
        key = self._key(target, question)
        raised = next((e for e in reversed(events) if e.type == "question.raised" and question_key(e) == key), None)
        found = raised.data.get("target") if raised is not None else None
        return {found} if isinstance(found, str) and found else set()

    def _batched(self, work: Sequence[tuple[_Target, Question]], first: int, done: set[int]) -> None:
        """The verdict question `work[first]` and the due ones after it that share its call: the same target folder, the
        same askers, no key in common, none whose last attempt was a batch that failed, up to `batch_size` and, in a
        capped pass, up to the questions the cap still allows. Each passes the checks of a single question; the soft
        deadline, once, ends the batch; the money and the size of the prompt shorten it; a batch of one is asked as
        before. What the batch leaves out is put back in `done` order for the loop to take."""
        target, question = work[first]
        events = self._events()
        key = self._key(target, question)
        if batch_failed(events, key):  # its batch timed out or failed: alone, so that it does not fail again
            self._question(target, question)
            return
        room = (
            self.cfg.batch_size if self.only else min(self.cfg.batch_size, self.cfg.max_questions_per_run - self.calls)
        )
        found, keys = [first], self._batch_keys(events, target, question)
        same = set(askers(events, key, self.implementers))
        for j in range(first + 1, len(work)):
            if len(found) >= room:
                break
            other, q = work[j]
            if j in done or other is not target or q.kind is not QuestionKind.VERDICT:
                continue
            k = self._key(other, q)
            if batch_failed(events, k) or set(askers(events, k, self.implementers)) != same:
                continue
            if (more := self._batch_keys(events, other, q)) & keys:
                continue
            keys |= more
            found.append(j)
        done.update(found[1:])
        items = [(j, item) for j in found if (item := self._prechecks(*work[j])) is not None]
        if not items:
            return
        put_back = [j for j, _ in items[1:]]
        if self._soft_deadline():  # the first is deferred as a single question is; the others are taken by the loop
            self._defer_for_time(target, items[0][1])
            done.difference_update(put_back)
            return
        if len(items) > 1 and len(items) > (fit := self._money_fit(self._events())):
            done.difference_update(j for j, _ in items[fit:])
            items = items[:fit]
        if len(items) == 1:
            self._select_and_ask(target, items[0][1])
            return
        batch = [item for _, item in items]
        try:
            selected = select_delegate(
                self.factory, self.s.ref.id, self._events(), batch[0].key, self.cfg, self.profiles,
                self.implementers, kind=QuestionKind.VERDICT.value,
            )  # fmt: skip
        except RoleUnavailable as exc:
            for item in batch:
                self._unavailable(target, item.question, item.key, item.shared, exc)
            return
        left_out = {item.key for item in self._ask_batch(target, batch, selected)}
        done.difference_update(j for j, item in items if item.key in left_out)

    def _money_fit(self, events: Sequence[LedgerEvent]) -> int:
        """How many answers' cost are left in the unit's cap and in the plan's share, at least one (each question passed
        `limit_reached`): a batch of N needs N (L4-DLG-009, L4-DLG-028)."""
        per = self.cfg.max_cost_usd_per_answer
        fit = int((self.cfg.max_cost_usd_per_unit - delegate_cost(events, per)) / per + 1e-9)
        plan = self._plan_cost(events)
        share = plan.share_usd(self.cfg) if plan is not None else None
        if plan is not None and share is not None:
            fit = min(fit, int((share - plan.delegate_cost_usd) / per + 1e-9))
        return max(fit, 1)

    def _batch_prompt(
        self, target: _Target, batch: Sequence[_Item], events: Sequence[LedgerEvent], selected: Selected
    ) -> DelegatePrompt:
        items = [self._material(target, i.question, i.key, events, selected, i.raised) for i in batch]
        return build_batch_prompt(
            items, budget_tokens=self.ctx.cfg.implementer.context_budget_tokens, redact=self.s.app.redactor.redact_text
        )

    def _ask_batch(self, target: _Target, batch: list[_Item], selected: Selected) -> list[_Item]:
        """The call of `_ask` for several verdict questions at once: one prompt `delegate-batch@1`, one document
        `l4/delegate-batch@1`, one `delegate.asked` for each question, the cost recorded once with a share on each
        result. A `limit` moves the whole batch to the next profile. Returns the questions it left out because the
        prompt was too long (`BATCH_MAX_CHARS`): the loop takes them in a later batch."""
        s = self.s
        events = self._events()
        folder_head = self._head_tree(target)
        self.unpriced = 0
        self.credits = 0.0
        left_out: list[_Item] = []
        previous: _Reply | None = None
        reply = _Reply("error")
        for _ in range(len(self.chain) + 1):
            if previous is not None:
                self.unpriced += previous.cost is None
            prompt = self._batch_prompt(target, batch, events, selected)
            if previous is None:  # the first prompt decides the size of the batch
                while len(prompt.user) > BATCH_MAX_CHARS and len(batch) > 2:
                    left_out.insert(0, batch.pop())
                    prompt = self._batch_prompt(target, batch, events, selected)
                self.calls += len(batch)
                name = f"{batch[0].key}+{len(batch)}"
                for item in batch:
                    item.shared |= dict(batch=name, batch_size=len(batch))
            n = len(batch)
            model = selected.profile.model
            for item in batch:
                s.ledger.append(
                    "delegate.asked", question=item.key, kind=item.shared["kind"], profile=selected.profile_name,
                    model=model, prompt_sha256=prompt.sha256, batch=name, batch_size=n,
                    **({"fix_unit": target.fix} if target.fix else {}),
                )  # fmt: skip
            reply = self._call(selected, prompt, batch[0].key, n)
            self._record_cost(batch[0].key, selected, reply, questions=[i.key for i in batch], batch=name)
            if reply.status != "limit":
                break
            try:
                selected = self.factory.on_limit(selected, reply.run)
            except RoleUnavailable as exc:
                share = self._share(reply, n)
                for item in batch:
                    self._unavailable(target, item.question, item.key, item.shared, exc, called=True, cost=share.cost)
                return left_out
            previous = reply
        if reply.status == "limit":  # the chain is out of profiles that were not limited in this pass
            reply = dataclasses.replace(reply, status="error", detail="limit")
        per = self._share(reply, n)
        who = (reply.model or selected.profile.model or selected.profile_name, selected.profile.adapter or "", selected)
        if reply.status == "error" and reply.detail.startswith("model_mismatch:"):
            for item in batch:  # a configuration the person fixes: another model served than the profile names
                self._escalate(
                    target, item.question, item.key, item.shared, self._mismatch(reply, selected), who=who,
                    called=True, cost=per.cost, status="discarded",
                )  # fmt: skip
            return left_out
        if reply.status != "ok":  # a timeout, an error, a document that is no `l4/delegate-batch@1`: a failed attempt
            why = "timeout" if reply.status == "timeout" else "error"  # a batch that failed is asked alone next
            for item in batch:
                spent = attempts_used(events, item.key)
                if spent + 1 >= self.cfg.max_attempts_per_question:
                    self._escalate(
                        target, item.question, item.key, item.shared, f"delegate attempts used ({spent + 1})",
                        who=who, called=True, cost=per.cost,
                    )  # fmt: skip
                else:
                    self._defer(
                        target, item.key, item.shared, why, self._now() + timedelta(seconds=RETRY_AFTER_S),
                        who, per,
                    )  # fmt: skip
            return left_out
        if reply.model and (veto := self._served_veto(selected, reply.model, events, batch[0].key)) is not None:
            for item in batch:  # the askers are the batch's: the CLI served an asker's model, no result is independent
                self._escalate(
                    target, item.question, item.key, item.shared, veto, who=who, called=True, cost=per.cost,
                    status="discarded",
                )  # fmt: skip
            return left_out
        found: dict[str, list[dict[str, Any]]] = {}
        for result in (reply.parsed or {}).get("results") or []:
            found.setdefault(str(result.get("question")), []).append(result)
        ours = {item.question.id for item in batch}
        for stray in sorted(set(found) - ours):
            log.info(
                "%s: the batch reply holds a result for %s, which is not in the batch: ignored", batch[0].key, stray
            )
        for item in batch:
            got = found.get(item.question.id, [])
            if len(got) != 1:
                why = f"the batch reply had {'no result' if not got else 'two results'} for {item.question.id}"
                if attempts_used(events, item.key) + 1 < self.cfg.max_attempts_per_question:
                    self._defer(
                        target, item.key, item.shared, why, self._now() + timedelta(seconds=RETRY_AFTER_S), who, per
                    )  # fmt: skip
                else:
                    self._escalate(
                        target, item.question, item.key, item.shared, why, who=who, called=True, cost=per.cost
                    )
                continue
            one = dataclasses.replace(per, parsed=got[0])
            self._settle(target, item.question, item.key, item.shared, item.raised, one, who, folder_head, events)
        return left_out

    def _share(self, reply: _Reply, n: int) -> _Reply:
        """The reply as each of the `n` questions of its batch sees it: a share of the call's cost, and of its credits
        in `self.credits`, which `_result` records (the unit's cost is counted once, in `budget.cost`)."""
        if self.credits:
            self.credits = round(self.credits / n, 6)
        return dataclasses.replace(reply, cost=None if reply.cost is None else round(reply.cost / n, 6))

    # -- one call ------------------------------------------------------------------------------------------------

    def _ask(
        self, target: _Target, question: Question, key: str, shared: dict[str, Any], selected: Selected,
        raised: LedgerEvent | None,
    ) -> None:  # fmt: skip
        s = self.s
        events = self._events()
        folder_head = self._head_tree(target)
        self.unpriced = 0
        self.credits = 0.0
        previous: _Reply | None = None
        for _ in range(len(self.chain) + 1):  # a limit moves to the next profile of the chain
            if previous is not None:  # a call that hit a limit and was followed by another: its own cost is unknown
                self.unpriced += previous.cost is None
            prompt = self._prompt(target, question, key, events, selected, raised)
            model = selected.profile.model
            s.ledger.append(
                "delegate.asked", question=key, kind=shared["kind"], profile=selected.profile_name, model=model,
                prompt_sha256=prompt.sha256, **({"fix_unit": target.fix} if target.fix else {}),
            )  # fmt: skip
            reply = self._call(selected, prompt, key)
            self._record_cost(key, selected, reply)  # every call's cost, also one that hit a limit (review F11)
            if reply.status != "limit":
                break
            try:
                selected = self.factory.on_limit(selected, reply.run)
            except RoleUnavailable as exc:
                self._unavailable(target, question, key, shared, exc, called=True, cost=reply.cost)
                return
            previous = reply
        if reply.status == "limit":  # the chain is out of profiles that were not limited in this pass
            reply = dataclasses.replace(reply, status="error", detail="limit")
        who = (reply.model or selected.profile.model or selected.profile_name, selected.profile.adapter or "", selected)
        if reply.status == "error" and reply.detail.startswith("model_mismatch:"):
            # a configuration the person fixes: another model served than the profile names (L4-DLG-017)
            self._escalate(
                target, question, key, shared, self._mismatch(reply, selected), who=who, called=True, cost=reply.cost,
                status="discarded",
            )  # fmt: skip
            return
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
        if reply.model and (veto := self._served_veto(selected, reply.model, events, key)) is not None:
            self._escalate(
                target, question, key, shared, veto, who=who, called=True, cost=reply.cost, status="discarded"
            )  # the CLI served another model than the profile names: the answer is not independent (review F3)
            return
        self._settle(target, question, key, shared, raised, reply, who, folder_head, events)

    def _settle(
        self, target: _Target, question: Question, key: str, shared: dict[str, Any], raised: LedgerEvent | None,
        reply: _Reply, who: Any, folder_head: HeadTree, events: Sequence[LedgerEvent],
    ) -> None:  # fmt: skip
        """A call that gave a document, or a schema break, for this question: `check_reply` on its own inputs, then
        its answer, its escalation or its retryable deferral (L4-DLG-005). Also the end of each result of a batch."""
        s = self.s
        verdict = self._verdict(target)
        found = self._target(target, question, raised)
        material = self._hold_kind(found)
        cfg = self.ctx.cfg
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
                chore=is_chore(raised, question, target.fix),
                fix_task=target.fix is not None,
                cap_only=bool(found and found.cap_only),
                cap_only_file=found.candidate_file if found else None,
                judge_view_files=found.files if found else (),
                test_globs=tuple(cfg.tdd.test_globs),
                support_globs=tuple(cfg.tdd.test_support_globs),
            )
            if reply.status == "ok"
            else Discarded(f"not an l4/delegate-result@1 document: {reply.detail}")
        )
        if isinstance(kept, Discarded):
            why = f"the reply was discarded: {kept.reason}" if kept.status == "discarded" else kept.reason
            if kept.retryable and attempts_used(events, key) + 1 < self.cfg.max_attempts_per_question:
                # a reference that did not resolve: asked again once, with the reason in the next prompt (L4-DLG-005)
                shown = self.s.app.redactor.redact_text(" ".join(kept.reason.split()))
                self._defer(
                    target, key, shared, f"the reply was discarded: {shown}; it is asked again",
                    self._now() + timedelta(seconds=RETRY_AFTER_S), who, reply, discarded=shown,
                    checked=[dict(c) for c in kept.checked],
                )  # fmt: skip
                return
            self._escalate(
                target, question, key, shared, why, who=who, called=True, cost=reply.cost, status=kept.status,
                decision=kept.decision, checked=kept.checked,
            )  # fmt: skip
        elif kept.escalates:
            self._escalate(
                target, question, key, shared, kept.reason or "the delegate could not check the claim", who=who,
                called=True, cost=reply.cost, status="escalated", decision="escalate", checked=kept.checked,
            )  # fmt: skip
        else:
            self._answer(target, question, key, shared, kept, who, reply)

    @staticmethod
    def _mismatch(reply: "_Reply", selected: Selected) -> str:
        """The escalation text of a CLI that served another model than the profile names, both ids when known."""
        if reply.model and selected.profile.model:
            return f"{selected.profile.adapter} served {reply.model}, the profile names {selected.profile.model}"
        return reply.detail.removeprefix("model_mismatch:").strip()

    def _served_veto(self, selected: Selected, served: str, events: Sequence[LedgerEvent], key: str) -> str | None:
        """The independence rule applied to the model that served the call (a fallback or an alias can differ from the
        profile's `model`), as `_ask_judges` re-checks a judge's served model."""
        profile = selected.profile.model_copy(update={"model": served})
        check = delegate_constraint(
            askers(events, key, self.implementers), self.cfg.independence, profiles=self.profiles
        )
        reason = check(selected.profile_name, profile)
        return None if reason is None else f"{reason} (served by {selected.profile_name})"

    def _call(self, selected: Selected, prompt: DelegatePrompt, key: str, batch: int = 1) -> _Reply:
        """One adapter call. `batch`: the questions it asks (L4-DLG-028), more than one for the document
        `l4/delegate-batch@1`, with the budget and the turns of that many answers."""
        s = self.s
        self.adapter_calls += 1
        wb = self._bench(selected)
        tree = self._detached(masked=True) if selected.profile.adapter in MASKED_TREE_ADAPTERS else self._detached()
        judge = AgentJudge(
            selected.impl, self._requests(wb, selected, tree, batch), events=s.ledger, role="delegate",
            profile=selected.profile_name, reading=True,
        )  # fmt: skip
        try:
            done: StructuredResult = judge.complete_structured(
                prompt.system, [Msg("user", prompt.user)], batch_schema(batch) if batch > 1 else delegate_schema(),
                effort=None, max_tokens=0, timeout_s=duration_seconds(self.cfg.timeout),
            )  # fmt: skip
        except L4Exit:
            raise
        except Exception as exc:  # noqa: BLE001 - an adapter failure is a deferral, the run does not crash
            log.warning("%s: the delegate call failed: %s", key, type(exc).__name__)
            log.debug("%s: the delegate call failed", key, exc_info=True)
            return _Reply("error", detail=type(exc).__name__)
        cost = done.usage.cost_usd if done.usage is not None else None
        credits = (done.usage.credits or None) if done.usage is not None else None
        source = done.usage.credits_source if credits else None
        return _Reply(done.status, done.parsed, done.detail, cost, done.model_resolved, done.run, credits, source)

    def _requests(self, wb: Workbench, selected: Selected, tree: Path, batch: int = 1):
        spec = dataclasses.replace(wb.agent_spec(), worktree=tree, worktree_read_only=True)
        extra = dict(getattr(wb.impl, "extra_env", {}))
        caps = wb.impl.capabilities()
        budget = batch * self.cfg.max_cost_usd_per_answer if caps.budget_cap else None  # N answers' cost (L4-DLG-028)
        turns = min(MAX_TURNS + BATCH_TURNS * (batch - 1), MAX_BATCH_TURNS)

        def make(prompt: str, schema: dict[str, Any], timeout_s: int) -> RunRequest:
            tmp = wb.reset_agent_tmp()
            raw, published = wb.agent_log_paths(f"delegate-{len(self.logs) + 1}")
            self.logs.append((raw, published))
            wb.publish_prompt(published, strip_suffix(prompt, schema))
            return RunRequest(
                profile=selected.profile, role="delegate", cwd=tree, prompt=prompt, result_path=tmp / "result.json",
                raw_events_path=raw, env=build_agent_env(wb.host_env, spec, extra=extra), result_schema=schema,
                permission_policy=PermissionPolicy("read_only"), timeout_s=timeout_s, max_turns=turns,
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

    def _detached(self, *, masked: bool = False) -> Path:
        """A detached worktree of the pushed head, in the unit's private cache, removed after the pass. `masked`: an
        delegate's of `MASKED_TREE_ADAPTERS`, from which the nested instruction files are removed (L4-DLG-016); the git
        tree, which the claims resolve against, is untouched, and the worktrees of the other adapters are never
        masked."""
        if (self.masked_tree if masked else self.tree) is None:
            base = self.benches[-1].unit_cache / ("delegate-tree-masked" if masked else "delegate-tree")
            shutil.rmtree(base, ignore_errors=True)
            self.s.git.run("worktree", "prune", check=False)  # a pass killed mid-call left it registered (review F12)
            self.s.git.run("worktree", "add", "--detach", "--quiet", str(base), self.head)
            if masked:
                mask_instruction_files(base)
                self.masked_tree = base
            else:
                self.tree = base
        found = self.masked_tree if masked else self.tree
        assert found is not None
        return found

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

    def _target(self, target: _Target, question: Question, raised: LedgerEvent | None) -> VerdictMaterial | None:
        """What the verifier knows of the target of a verdict question (None: not a verdict question)."""
        if question.kind is not QuestionKind.VERDICT or raised is None:
            return None
        return verdict_material(self._verdict(target), "", str(raised.data.get("target") or ""))

    @staticmethod
    def _hold_kind(found: VerdictMaterial | None) -> str | None:
        """The kind of the hold a verdict question is about (None: a criterion, a finding, or not a verdict)."""
        return hold_kind(found.text.removeprefix(f"{found.target} ")) if found and found.kind == "hold" else None

    def _without_a_call(self, target: _Target, question: Question, raised: LedgerEvent | None) -> str | None:
        """Why the question is a person's without a delegate call: the check an answer needs cannot be made
        (L4-DLG-024). A cap-only criterion's accept must cite the candidate test's file, which the test report has to
        name; a judge-view hold is accepted after reading one of the files it names, and a hold that names none (the
        0.4.14 `LEGACY_LENGTH_HOLD`) has nothing to read. A repair proposal of a test (a harness question whose raise
        has `check: repair`, L4-IMP-091) is a person's decision, whatever the delegate's scope and kinds say."""
        if raised is not None and raised.data.get("check") == "repair" and question.kind is QuestionKind.HARNESS:
            return "a repair of a test is a person's decision"
        found = self._target(target, question, raised)
        if found is None:
            return None
        if found.kind == "criterion" and found.cap_only and found.candidate_file is None:
            return (
                "the check of an accept cannot be made: the test report names no file for the candidate test "
                f"{found.candidate} of this cap-only criterion"
            )
        if self._hold_kind(found) == "judge_view" and not found.files:
            return "this judge-view hold names no file the delegate could read: only a person decides it"
        return None

    def _material(
        self, target: _Target, question: Question, key: str, events: Sequence[LedgerEvent], selected: Selected,
        raised: LedgerEvent | None,
    ) -> tuple[QuestionView, Material]:  # fmt: skip
        """What a prompt about `question` is built from: the view of the question and its material."""
        s, cfg = self.s, self.ctx.cfg
        file = self._file(target)
        # L4-QMD-008: the suggestion shown is what `accept` takes, option 1 of a question with no block included
        view = dataclasses.replace(QuestionView.of(question), suggestion_text=accept_text(question))
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
            AnsweredQuestion(
                q.id, answer_actor(git, target.path, q, events, fix_unit=target.fix).by, effective_answer(q) or ""
            )
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
            sources, conventions, answered, verdict, harness, gate_excerpt(events, task.key if task else None),
            previous=last_discard(events, key),
        )  # fmt: skip
        return view, material

    def _prompt(
        self, target: _Target, question: Question, key: str, events: Sequence[LedgerEvent], selected: Selected,
        raised: LedgerEvent | None,
    ) -> DelegatePrompt:  # fmt: skip
        view, material = self._material(target, question, key, events, selected, raised)
        return build_prompt(
            view, material, budget_tokens=self.ctx.cfg.implementer.context_budget_tokens,
            redact=self.s.app.redactor.redact_text,
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

    def _record_cost(self, key: str, selected: Selected, reply: _Reply, **more: Any) -> None:
        """A cost the CLI reported in dollars (0 is a known cost: a free model), and its credits as credits, never
        converted to dollars (L4-DLG-020); a call with neither counts at the cap through its `delegate.result`. `more`:
        what a batch adds (`questions`, `batch`), on the call's one record of each."""
        if reply.cost is not None:
            self.s.ledger.append(
                "budget.cost", usd=reply.cost, profile=selected.profile_name, role="delegate", question=key, **more
            )  # fmt: skip
        if reply.credits:
            self.s.ledger.append(
                "budget.cost", credits=round(reply.credits, 6), credits_source=reply.credits_source,
                profile=selected.profile_name, role="delegate", question=key, **more,
            )  # fmt: skip
            self.credits = round(self.credits + reply.credits, 6)

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
            if cost is None:
                data["counted_usd"] = self.cfg.max_cost_usd_per_answer  # an unpriced call counts at the cap (D10)
            if self.credits:
                data["credits"] = self.credits
            if self.unpriced:
                data["unpriced_calls"] = self.unpriced
        if target.fix:
            data["fix_unit"] = target.fix
        self.s.ledger.append("delegate.result", **data, **more)

    def _line_who(self, who: Any) -> str:
        return f"the delegate ({who[0]} via {who[1]})" if who is not None else "the delegate"

    def _defer(
        self, target: _Target, key: str, shared: dict[str, Any], why: str, retry_after: datetime, who: Any = None,
        reply: _Reply | None = None, *, called: bool = False, cost: float | None = None, **more: Any,
    ) -> None:  # fmt: skip
        """`called`/`cost`: a call was made before the deferral (a limit moved the pass on, and nothing was left).
        `more` is recorded on the result (a discarded reply's `discarded` reason and `checked` entries)."""
        called = called or reply is not None
        self._result(
            target, key, shared, "deferred", reason=why, who=who, called=called, cost=reply.cost if reply else cost,
            retry_after=_iso(retry_after), **more,
        )  # fmt: skip
        self.deferred.append(key)
        log.info("%s: the delegate defers (%s) until %s", key, why, _iso(retry_after))

    def _unavailable(
        self, target: _Target, question: Question, key: str, shared: dict[str, Any], exc: RoleUnavailable,
        *, called: bool = False, cost: float | None = None,
    ) -> None:  # fmt: skip
        """No usable profile: independence, an empty chain or a cause only a fix ends is an escalation; every profile
        cooling with a known end is a deferral (L4-DLG-013)."""
        if (why := independence_escalation(exc, shared.get("kind"))) is not None:
            self._escalate(target, question, key, shared, why, who=None, called=called, cost=cost)
            return
        text = str(exc).partition(" is unavailable: ")[2] or str(exc)
        retry = getattr(exc, "retry_after", None) or self._cooling_until()
        if retry is not None:
            self._defer(target, key, shared, "cooling", retry, called=called, cost=cost)
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
            cli=cli, answer_sha256=digest, **({"fix_unit": target.fix} if target.fix else {}),
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
    implementers: Sequence[str] = (),
    kind: str | None = None,
) -> Selected:
    """The first usable profile of `roles.delegate` that is neither an asker of the question `key` nor a judge of it
    (L4-DLG-002): each question has its own askers, so each gets its own constraint; a verdict question's askers
    include the unit's implementer profiles (`implementers`: `roles.implementer`, the fallback when the ledger names
    none). `kind`, the question's: a profile that may not answer it (a free-tier model, `options.delegate_kinds`) is
    skipped for it, so that no fallback reaches it (L4-DLG-019). `RoleUnavailable` when none is."""
    constraints = [delegate_constraint(askers(events, key, implementers), cfg.independence, profiles=profiles)]
    if kind is not None:
        constraints.append(kinds_constraint(kind, cfg))
    return factory.for_role("delegate", unit, serves=DELEGATE_SERVES, constraints=constraints)


def is_chore(raised: LedgerEvent | None, question: Question, fix_unit: str | None) -> bool:
    """The question is a blocked fix chore's (L4-DLG-025): its `question.raised` says so (`chore: true`), or, for a
    raise from before the field, it is a fix unit's technical question whose context holds the fix-task note."""
    if raised is not None and raised.data.get("chore") is True:
        return True
    if fix_unit is None or question.kind is not QuestionKind.TECHNICAL:
        return False
    return CHORE_NOTE in unescape_text(question.context_text)


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
