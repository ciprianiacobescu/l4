"""The clarifier (SPEC 9): `reenter` reads what humans (and the clarifier) answered since the last run, `run` answers
the open questions or leaves a suggestion, and `clarify_hook` is what the orchestrator calls.

`reenter` changes no phase. It reloads `questions.md` from the unit directory and writes the ledger facts the rest of
the run relies on: which answers are new (`question.answered`), which are drafts (`question.unsubmitted_answer`)
and which answers an implementer prompt already carried and were edited since (`question.override`, L4-QMD-006). What
a question's answer "was" is the sha256 of its effective answer (`l4.specs.questions.answer_sha256`); "consumed" is
what the last `prompt.rendered` event that carried the question recorded. An answer edited before any prompt used it
is not an override (SCN-CLR-06): the new text is recorded as `question.answered` again.
"""

import hashlib
import logging
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from l4.agents.base import RunResult
from l4.agents.factory import RoleUnavailable
from l4.clarifier.actor import Actor, answer_actor
from l4.clarifier.backend import BackendClarifier, ClarifierReply
from l4.clarifier.context import ClarifierPrompt, ContextBuilder
from l4.clarifier.inject import render_answer_blocks
from l4.clarifier.notify import build_sticky_section
from l4.clarifier.ports import (
    ClarifyOutcome,
    QuestionResult,
    QuestionsPort,
    QuestionView,
    RoutingDecision,
    SpecQuestionsPort,
    render_answer_with_citations,
)
from l4.clarifier.router import NoS1, Router, build_s1_judge
from l4.config.schema import ClarifierCfg
from l4.exitcodes import L4Exit
from l4.forge.base import forge_platform
from l4.forge.urls import blob_url, origin_url
from l4.implementer.tasks import answers_unblock, open_blocking_questions
from l4.implementer.tdd import RoleLimit
from l4.implementer.unit_context import read_sources
from l4.implementer.workbench import Workbench, make_workbench
from l4.llm.agent_judge import JUDGE_ADAPTERS, AgentJudge, workbench_request_factory
from l4.services import HookContext, Services
from l4.specs.base import Task
from l4.specs.questions import (
    QUESTIONS_FILENAME,
    Question,
    QuestionKind,
    QuestionsFile,
    QuestionStatus,
    answer_sha256,
    is_answered,
)
from l4.state.fold import fold
from l4.state.ledger import LedgerEvent, LedgerWriter, ledger_path, read_ledger
from l4.vcs.git import Git
from l4.vcs.trailers import CommitTrailers

log = logging.getLogger("l4.clarifier")


@dataclass(frozen=True)
class Answered:
    id: str
    by: Literal["human", "agent", "clarifier", "delegate"]
    answer_sha256: str | None  # None for a dismissed question


@dataclass(frozen=True)
class Reentry:
    answered: tuple[Answered, ...]  # answered in the file and not yet recorded in the ledger
    drafts: tuple[str, ...]  # a non-empty Answer under Status `open`: never consumed
    overrides: tuple[str, ...]  # an answer a prompt consumed whose text has changed since
    unblocks: tuple[str, ...]  # answered questions whose pending tasks are free to run; empty: nothing is eligible
    index_refreshed: bool = False  # `questions.md` was rewritten (index rows) and the caller must commit it


_EMPTY = Reentry((), (), (), ())


def _recorded(events: Sequence[LedgerEvent]) -> dict[str, Mapping[str, Any]]:
    """Per question id, the last event that fixed its answer text: `question.answered` or `question.override`."""
    seen: dict[str, Mapping[str, Any]] = {}
    for event in events:
        if event.data.get("fix_unit"):
            continue  # a fix unit's questions are numbered from Q-001 in its own file (M1.3)
        if event.type in ("question.answered", "question.override") and isinstance(event.data.get("id"), str):
            seen[event.data["id"]] = event.data
    return seen


def _consumed(events: Sequence[LedgerEvent]) -> dict[str, str | None]:
    """Per question id, the answer hash of the last prompt that carried it (None: a dismissed question)."""
    seen: dict[str, str | None] = {}
    for event in events:
        if event.type == "prompt.rendered" and not event.data.get("fix_unit"):
            for item in event.data.get("answers") or []:
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    seen[item["id"]] = item.get("answer_sha256")
    return seen


def _drafted(events: Sequence[LedgerEvent]) -> dict[str, str | None]:
    """Per question id, the hash of the draft the last `question.unsubmitted_answer` event recorded."""
    return {
        e.data["id"]: e.data.get("answer_sha256")
        for e in events
        if e.type == "question.unsubmitted_answer" and isinstance(e.data.get("id"), str) and not e.data.get("fix_unit")
    }


def clarified_ids(events: Sequence[LedgerEvent]) -> frozenset[str]:
    """Questions the clarifier has looked at in any run: one `clarifier.result` event per question, with its `id`
    (M1: clarification-loop 1.14 writes them)."""
    return frozenset(e.data["id"] for e in events if e.type == "clarifier.result" and isinstance(e.data.get("id"), str))


class Answerer(Protocol):
    """`BackendClarifier`: one question in, one reply out (the reply says `ok`, `invalid` or `unavailable`)."""

    def answer(self, question: QuestionView, prompt: ClarifierPrompt) -> ClarifierReply: ...


def _s1_record(decision: RoutingDecision | None) -> dict[str, object]:
    """What S1 said, for calibration (L4-VER-008): every raw p, the served model and the question-set id. Nothing for a
    question that never reached S1."""
    if decision is None or decision.s1 == "not_asked":
        return {}
    return {
        "p_internal": decision.p_internal, "citation_opposite": list(decision.citation_opposite),
        "s1_model": decision.s1_model, "s1_questions": decision.s1_questions, "s1_detail": dict(decision.s1_detail),
    }  # fmt: skip


def _meta(reply: ClarifierReply, decision: RoutingDecision) -> str:
    """One short line above a suggestion. It is part of the text a human may accept, and so of what an implementer
    reads and of the answer hash: nothing in it comes from a model's free text."""
    assert reply.answer is not None
    p = f"{decision.p_product:.2f}" if decision.p_product is not None else "n/a"
    return f"confidence: {reply.answer.confidence} · kind: {reply.answer.kind} (S1 p={p})"


class Clarifier:
    def __init__(self, unit_dir: Path, ledger: LedgerWriter) -> None:
        self.unit_dir = unit_dir
        self.ledger = ledger

    def _actor(self, question: Question, events: Sequence[LedgerEvent]) -> Actor:
        """Who answered, of every kind (L4-QMD-009): `answer_actor` reads the status, the ledger and the `By:` line."""
        return answer_actor(Git(self.unit_dir), self.unit_dir, question, events)

    def reenter(self, tasks: Sequence[Task], *, refresh_index: bool = True) -> Reentry:
        """`refresh_index=False` for a unit whose branch head must not get a harness commit (a unit in review)."""
        file = QuestionsFile.load(self.unit_dir / QUESTIONS_FILENAME)
        if file is None:
            return _EMPTY
        events = read_ledger(self.unit_dir).events
        recorded, consumed, drafted = _recorded(events), _consumed(events), _drafted(events)
        answered, overrides = [], []
        for question in file.questions:
            if not is_answered(question):
                continue
            digest = answer_sha256(question)
            before = recorded.get(question.id)
            if before is not None and before.get("answer_sha256") == digest:
                continue
            if before is not None and question.id in consumed and consumed[question.id] != digest:
                overrides.append(question.id)
                self.ledger.append(
                    "question.override", id=question.id, previous_sha256=consumed[question.id], answer_sha256=digest
                )  # fmt: skip
            else:  # new, or edited before any prompt carried it
                actor = self._actor(question, events)
                answered.append(Answered(question.id, actor.by, digest))
                self.ledger.append(
                    "question.answered", id=question.id, by=actor.by, answer_sha256=digest, **actor.fields()
                )
        drafts = tuple(i.question_id for i in file.issues if i.kind == "unsubmitted_answer")
        for qid in drafts:  # once per id and text: a run that finds the same draft again says nothing new
            question = file.get(qid)
            digest = hashlib.sha256(question.answer_text.encode("utf-8")).hexdigest() if question else None
            if qid not in drafted or drafted[qid] != digest:
                self.ledger.append("question.unsubmitted_answer", id=qid, answer_sha256=digest)
        for issue in file.issues:
            if issue.kind != "unsubmitted_answer":
                log.warning("%s: %s %s", issue.question_id, issue.kind.replace("_", " "), issue.detail)
        refreshed = file.refresh_index() if refresh_index else file
        changed = refreshed.data != file.data
        if changed:
            refreshed.save(self.unit_dir / QUESTIONS_FILENAME)
        return Reentry(tuple(answered), drafts, tuple(overrides), tuple(answers_unblock(file, tasks)), changed)

    def run(
        self,
        port: QuestionsPort,
        *,
        prompt_for: Callable[[QuestionView], ClarifierPrompt],
        answerer: Answerer,
        router: Router,
        cfg: ClarifierCfg,
        profile: str | None,
        blocking: Collection[str],
        location: tuple[str, str],
        link: str | None,
        drafts: Sequence[str] = (),
        hint: str | None = None,
    ) -> ClarifyOutcome:
        """The open questions in `blocking` that the clarifier has not looked at yet, at most `cfg.max_open_questions`
        and never a `verdict` or `harness` question: each becomes `answered-by-clarifier` (every L4-CLR-002 condition
        held) or a suggestion with Status `open`. The ones left out of the batch have no `clarifier.result`, so a
        later pass takes them. A reply that is `unavailable` ends the calls: the remaining questions of the batch are
        recorded as unavailable without asking again. The phase that follows is `implementing` only when nothing that
        blocks a task is still open. `location` is (path of questions.md, unit branch) for the sticky section."""
        done = clarified_ids(read_ledger(self.unit_dir).events)
        batch = [
            v for v in port.load()
            if v.id in blocking and v.status is QuestionStatus.OPEN
            and v.kind not in (QuestionKind.VERDICT, QuestionKind.HARNESS) and v.id not in done
        ][: cfg.max_open_questions]  # fmt: skip
        results: dict[str, QuestionResult] = {}
        available, invalid = True, []
        for view in batch:
            if available:
                prompt, reply = self._ask(view, prompt_for, answerer)
                available = reply.status != "unavailable"
                self._record_limit(reply.limit)
                if reply.cost_usd:
                    self.ledger.append("budget.cost", usd=reply.cost_usd, profile=profile, role="clarifier")
                if reply.credits:
                    self.ledger.append(
                        "budget.cost",
                        credits=round(reply.credits, 6),
                        credits_source=reply.credits_source,
                        profile=profile,
                        role="clarifier",
                    )  # plan credits, never dollars (kiro-judge L4-KJD-004)
            else:
                prompt, reply = None, ClarifierReply("unavailable", detail="the clarifier was unavailable")
            result = self._decide(port, view, reply, router, profile)
            results[view.id] = result
            if reply.status == "invalid":
                invalid.append(view.id)
            self._record_result(view, reply, result, prompt)
        open_ids = [v for v in port.load() if v.id in blocking and v.by is None]
        unreadable = [qid for qid in port.unreadable_ids() if qid in blocking]  # no view, but they still hold tasks
        if not open_ids and not unreadable:
            return ClarifyOutcome("implementing", 0, results)
        path, branch = location
        section = build_sticky_section(
            open_ids, path=path, branch=branch, link=link, clarifier_unavailable=not available, invalid=invalid,
            drafts=drafts, unreadable=unreadable, hint=hint,
        )  # fmt: skip
        return ClarifyOutcome("awaiting_human", 11, results, clarifier_available=available, sticky_section=section)

    @staticmethod
    def _ask(
        view: QuestionView, prompt_for: Callable[[QuestionView], ClarifierPrompt], answerer: Answerer
    ) -> tuple[ClarifierPrompt | None, ClarifierReply]:
        """A failure of the call itself (an adapter error, an OS error spawning the sandboxed CLI, a parse bug) is the
        clarifier being unavailable (L4-CLR-005): the question stays open for a human, the run does not crash with
        the unit parked in `clarifying`. Only the exception type is recorded at warning level (its text may carry
        paths or output); the traceback is at debug level, to tell a harness bug from a backend outage."""
        prompt: ClarifierPrompt | None = None
        try:
            prompt = prompt_for(view)
            return prompt, answerer.answer(view, prompt)
        except (L4Exit, RoleLimit):  # the orchestrator parks those with their own record
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("%s: the clarifier call failed: %s", view.id, type(exc).__name__)
            log.debug("%s: the clarifier call failed", view.id, exc_info=True)  # redacted by the log formatter
            return prompt, ClarifierReply("unavailable", detail=type(exc).__name__)

    def _decide(
        self, port: QuestionsPort, view: QuestionView, reply: ClarifierReply, router: Router, profile: str | None
    ) -> QuestionResult:
        if reply.status != "ok" or reply.answer is None:
            return QuestionResult("open", reply.status, reasons=(reply.detail or reply.status,), profile=profile)
        answer = reply.answer
        try:
            decision = router.route(view, answer)
        except Exception as exc:  # noqa: BLE001 - a model's input must never turn "ask a human" into exit 1
            log.warning("%s: the router failed: %s", view.id, type(exc).__name__)
            decision = RoutingDecision(False, (f"router error: {type(exc).__name__}",))
        self._record_limit(decision.s1_limit)
        meta = _meta(reply, decision)
        if decision.auto_accept:
            port.set_clarifier_answer(view.id, f"{meta}\n\n{answer.answer}", answer.citations)
            self.ledger.append(
                "question.answered", id=view.id, by="clarifier", answer_sha256=port.answer_sha256(view.id)
            )  # fmt: skip
            return QuestionResult("answered-by-clarifier", "ok", answer, decision, profile=profile)
        suggestion = render_answer_with_citations(answer.answer, answer.citations)
        port.set_clarifier_suggestion(view.id, suggestion, f"{meta} · needs a human")
        return QuestionResult("open", "ok", answer, decision, suggestion, decision.reasons, profile)

    def _record_result(
        self, view: QuestionView, reply: ClarifierReply, result: QuestionResult, prompt: ClarifierPrompt | None
    ) -> None:
        decision, answer = result.decision, result.answer
        self.ledger.append(
            "clarifier.result", id=view.id, status=reply.status, profile=result.profile,
            kind=answer.kind if answer else None, confidence=answer.confidence if answer else None,
            auto_accepted=result.status == "answered-by-clarifier", reasons=list(result.reasons),
            s1=decision.s1 if decision else None, p_product=decision.p_product if decision else None,
            p_technical=decision.p_technical if decision else None,
            citation_support=list(decision.citation_support) if decision else [], calls=reply.calls,
            **_s1_record(decision),
            cost_usd=reply.cost_usd, model=reply.model_resolved, prompt_sha256=prompt.sha256 if prompt else None,
        )  # fmt: skip

    def _record_limit(self, run: RunResult | None) -> None:
        signal = run.limit if run is not None else None
        if signal is not None:
            self.ledger.append(
                "availability.limit", tool=signal.tool, kind=signal.kind, source=signal.source,
                excerpt=signal.raw_excerpt,
            )  # fmt: skip


# --- the orchestrator's `clarify` hook ----------------------------------------------------------------------------


def sticky_location(ctx: HookContext) -> tuple[str, str, str | None]:
    """(path of questions.md in the repository, unit branch, link to it on the forge when its address is known)."""
    s = ctx.services
    path = (s.ref.path.resolve().relative_to(s.worktree.resolve()) / QUESTIONS_FILENAME).as_posix()
    base = ctx.shared.get("project_url")
    # GitHub has no `/-/` separator (live run 38175559320)
    platform = forge_platform(ctx.cfg, s.app.environ, origin_url(s.app.repo, s.app.environ))
    link = blob_url(base, s.names.branch, path, platform) if base else None
    return path, s.names.branch, link


def awaiting_section(ctx: HookContext, **notes: Any) -> str | None:
    """The sticky section for the unit's open blocking questions as the file holds them now (None: it is not
    readable or has none). `notes` are the keyword arguments of `build_sticky_section` after `link`."""
    s = ctx.services
    file = QuestionsFile.load(s.ref.path / QUESTIONS_FILENAME)
    ids = set(open_blocking_questions(file, s.provider.tasks(s.ref)))
    views = [QuestionView.of(q) for q in file.questions if q.id in ids] if file else []
    unreadable = [qid for qid in file.unreadable_ids if qid in ids] if file else []
    if not views and not unreadable:
        return None
    path, branch, link = sticky_location(ctx)
    notes.setdefault("hint", sticky_hint(ctx, [v.kind.value if v.kind else "unknown" for v in views]))
    return build_sticky_section(views, path=path, branch=branch, link=link, unreadable=unreadable, **notes)


def sticky_hint(ctx: HookContext, kinds: Sequence[str], *, phase: str = "awaiting_human") -> str | None:
    """The `Hint:` sentence that ends a waiting section while the delegate is off (L4-DLG-021)."""
    from l4.delegate.hint import HintReader

    return HintReader(ctx.services.git, ctx.cfg).hint(ctx.services.ref.id, phase, kinds)


def commit_questions(services: Services, *, phase: str | None, iteration: int, what: str) -> None:
    """`questions.md` and the run's ledger so far as a checkpoint `docs(<unit>): <what> [skip ci]`: an agent step later
    in the run may discard uncommitted changes. Nothing is committed when neither file differs from HEAD."""
    s = services
    root = s.worktree.resolve()
    paths = [s.ref.path / QUESTIONS_FILENAME, ledger_path(s.ref.path, s.app.run_id)]
    s.git.run("add", "--", *(p.resolve().relative_to(root).as_posix() for p in paths if p.exists()))
    if s.git.run("diff", "--cached", "--quiet", check=False).returncode == 0:
        return
    trailers = CommitTrailers(unit=s.ref.id, run_id=s.app.run_id, iteration=max(iteration, 1), phase=phase or "intake")
    s.git.commit(f"docs({s.ref.name}): {what} [skip ci]", trailers)


_NO_PROMPT = ClarifierPrompt("", "", "0" * 64, "none")


class _Down:
    """The clarifier role cannot be opened: every question gets the `unavailable` reply, without a call."""

    def __init__(self, detail: str) -> None:
        self._detail = detail

    def answer(self, question: QuestionView, prompt: ClarifierPrompt) -> ClarifierReply:
        return ClarifierReply("unavailable", detail=self._detail)


def clarify_hook(ctx: HookContext) -> ClarifyOutcome:
    """The orchestrator's `clarify` hook (`l4.clarifier.clarifier:clarify_hook`), run on `implementing -> clarifying`:
    `reenter` first (it records drafts and answers that are new), then `Clarifier.run`, then the checkpoint commit
    `docs(<unit>): clarifier [skip ci]` and a push, so that an answer is on the branch before the next agent step.
    A clarifier that cannot be opened is not an error: the questions go to a human (L4-CLR-005)."""
    cfg, s = ctx.cfg, ctx.services
    tasks = s.provider.tasks(s.ref)
    clarifier = Clarifier(s.ref.path, s.ledger)
    reentry = clarifier.reenter(tasks, refresh_index=False)
    path = s.ref.path / QUESTIONS_FILENAME
    file = QuestionsFile.load(path)
    if file is None:  # the orchestrator only comes here with questions on file: nothing for the clarifier to do
        return ClarifyOutcome("awaiting_human", 11)
    port = SpecQuestionsPort(path, file, redactor=s.app.redactor)
    blocking = open_blocking_questions(file, tasks)
    logs: list[tuple[Path, Path]] = []
    workbenches: list[Workbench] = []
    path_in_repo, branch, link = sticky_location(ctx)
    open_kinds = [v.kind.value if v.kind else "unknown" for v in port.load() if v.id in blocking and v.by is None]
    run = dict(
        cfg=cfg.clarifier, blocking=blocking, location=(path_in_repo, branch), link=link, drafts=reentry.drafts,
        hint=sticky_hint(ctx, open_kinds),
    )  # fmt: skip
    try:
        selected = s.factory.for_role("clarifier", s.ref.id, serves=JUDGE_ADAPTERS)
    except RoleUnavailable as exc:
        outcome = clarifier.run(
            port, prompt_for=lambda view: _NO_PROMPT, answerer=_Down(str(exc)),
            router=Router(cfg.clarifier, cfg.verifier.s1, NoS1(str(exc)), []), profile=None, **run,
        )  # fmt: skip
    else:
        state = fold(read_ledger(s.ref.path).events, s.ref.id)

        def bench(chosen):  # the clarifier's adapter, or the one S1 judge profile: its login is the only one visible
            wb = make_workbench(
                cfg=cfg, app=s.app, ref=s.ref, provider=s.provider, worktree=s.worktree, git=s.git, ledger=s.ledger,
                sandbox=s.sandbox, selected=chosen, iteration=state.iteration, push=ctx.push,
            )  # fmt: skip
            workbenches.append(wb)
            return wb

        wb = bench(selected)
        redact = s.app.redactor.redact_text
        judge = AgentJudge(
            selected.impl,
            workbench_request_factory(wb, selected.profile, stem="clarify", logs=logs, publish_prompts=True),
            events=s.ledger,
            role="clarifier",
            profile=selected.profile_name,
        )
        s1 = build_s1_judge(
            cfg, s.factory, s.ref.id,
            lambda chosen: workbench_request_factory(
                bench(chosen), chosen.profile, stem="s1", logs=logs, publish_prompts=True
            ),
            redact=redact,
            on_cost=lambda usd, profile: s.ledger.append("budget.cost", usd=usd, profile=profile, role="s1_judge"),
            redactor=s.app.redactor, events=s.ledger, environ=s.app.environ,
            log_path=s.app.repo / cfg.observability.log_dir / "system-one.jsonl",
        )  # fmt: skip
        builder = ContextBuilder(
            s.worktree, s.git, budget_tokens=cfg.implementer.context_budget_tokens, redact=redact
        )  # fmt: skip
        documents = read_sources(s.ref.path, s.worktree)
        base_specs = builder.base_specs()

        def prompt_for(view: QuestionView) -> ClarifierPrompt:
            texts = [view.title, view.context, *(d.text for d in documents)]
            code = builder.code_context(texts)
            answered = render_answer_blocks(port.file.questions, redact).text  # includes this batch's earlier answers
            prompt = builder.build_prompt(
                view, documents=documents, base_specs=base_specs, answered=answered, code=code
            )
            return prompt

        try:
            outcome = clarifier.run(
                port, prompt_for=prompt_for, answerer=BackendClarifier(judge, redact=redact),
                router=Router(cfg.clarifier, cfg.verifier.s1, s1, [s.ref.path, s.worktree]),
                profile=selected.profile_name, **run,
            )  # fmt: skip
        finally:
            s1.close()  # laya-serve must not outlive the clarifier pass (plan D7)
            for raw, published in logs:
                wb.publish_agent_logs(raw, published)
            for each in workbenches:
                each.restore_ledger()
    state = fold(read_ledger(s.ref.path).events, s.ref.id)
    commit_questions(s, phase=state.phase, iteration=state.iteration, what="clarifier")
    ctx.push()
    return outcome
