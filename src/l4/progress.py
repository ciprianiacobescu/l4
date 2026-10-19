"""The console progress trace: one line per ledger event, `[l4] <unit> <message>` on the `l4` logger.

Attached to `LedgerWriter` as an observer, so every component's events are covered without a print of their own.
The events reaching it are already redacted, and the log formatter redacts every line again. Quiet runs (`-q`) drop
the INFO lines; `-v` adds the DEBUG ones (agent step starts, verifier steps, locks). One line per event, no payloads.
"""

import logging
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path

from l4.agents.activity import ago
from l4.state.ledger import LedgerEvent

log = logging.getLogger("l4")

_Line = tuple[int, str]  # (log level, message)
MAX_TEXT = 160
PROBE_ORDER = ("binary", "auth", "quota", "hello")
ZEROED_GATES = frozenset(
    {"test-zero", "test-presatisfied", "test-extra-zero"}
)  # the harness zeroes the code on purpose: a failure is the point


class FilteredTrace:
    """A `ProgressTrace` that only sees some event types: the sweep's writer prints the CI warning line of `ci.failed`
    and `ci.preexisting`, and nothing else (an unfiltered trace would print a `run started` line per unit per sweep;
    M1.10 decision 10)."""

    def __init__(self, trace: Callable[[LedgerEvent], None], types: frozenset[str]) -> None:
        self._trace, self._types = trace, types

    def __call__(self, event: LedgerEvent) -> None:
        if event.type in self._types:
            self._trace(event)


SWEEP_TRACE_TYPES = frozenset({"ci.failed", "ci.preexisting"})


def _clip(value: object, limit: int = MAX_TEXT) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _num(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _usd(value: object) -> str:
    number = _num(value)
    return f"${number:.4f}" if number is not None else "$?"


def _probe_parts(probes: dict) -> list[str]:
    parts: list[str] = []
    for step in PROBE_ORDER:
        detail = probes.get(step)
        if not isinstance(detail, dict):
            continue
        if step == "binary":
            parts.append(f"binary {detail['version']}" if detail.get("version") else "binary ok")
        elif step == "auth":
            parts.append(f"auth {detail.get('auth_method') or 'ok'}")
        elif step == "quota":
            used = detail.get("used_percent")
            window = detail.get("window")
            parts.append(f"quota {used}% used" + (f" ({window})" if window else "") if used is not None else "quota ok")
        elif step == "hello":
            ms = _num(detail.get("ms"))
            parts.append(f"hello {ms / 1000:.1f}s" if ms is not None else "hello ok")
    return parts


class ProgressTrace:
    """Callable `LedgerEvent -> None`; keeps the step start times and the running cost, nothing else."""

    def __init__(self, project_url: str | None = None) -> None:
        self._project_url = project_url.rstrip("/") if project_url else None
        self._unit = ""
        self._branch = ""
        self._base: str | None = None
        self._head: str | None = None
        self._mr: str | None = None
        self._started: datetime | None = None
        self._steps: dict[tuple[object, object, object], datetime] = {}
        self._cost = 0.0
        self._handlers: dict[str, Callable[[LedgerEvent], _Line | list[_Line] | None]] = {
            "run.started": self._run_started,
            "availability.selected": self._selected,
            "availability.limit": self._limit,
            "phase.changed": self._phase,
            "question.raised": self._raised,
            "clarifier.result": self._clarified,
            "question.answered": self._answered,
            "task.started": self._task_started,
            "step.started": self._step_started,
            "agent.idle": self._agent_idle,
            "agent.finished": self._agent_finished,
            "result.normalized": self._result_normalized,
            "budget.cost": self._budget,
            "gate.finished": self._gate,
            "check.inconclusive": self._check_inconclusive,
            "check.accepted": self._check_accepted,
            "zero.kept": self._zero_kept,
            "task.red_ok": self._red_ok,
            "task.red_resumed": self._red_resumed,
            "task.done": self._done,
            "task.attempt_failed": self._attempt_failed,
            "breaker.tripped": self._breaker,
            "implementer.escalated": self._escalated,
            "implementer.escalation_skipped": self._escalation_skipped,
            "prompt.rendered": self._prompt_rendered,
            "guard.violation": self._guard,
            "doctor.check": self._doctor_check,
            "base.merged": self._base_merged,
            "base.conflict": self._base_conflict,
            "ci.failed": self._ci_failed,
            "ci.preexisting": self._ci_preexisting,
            "ci.step": self._ci_step,
            "task.unfrozen": self._unfrozen,
            "verify.step": self._verify_step,
            "verify.judge": self._verify_judge,
            "verify.verdict": self._verdict,
            "pr.updated": self._pr_updated,
            "pr.ready": self._pr_ready,
            "pr.labels": self._pr_labels,
            "lock.acquired": lambda e: (logging.DEBUG, "lock acquired"),
            "lock.released": lambda e: (logging.DEBUG, "lock released"),
            "run.finished": self._finished,
        }

    def __call__(self, event: LedgerEvent) -> None:
        handler = self._handlers.get(event.type)
        made = handler(event) if handler else None
        lines = [] if made is None else made if isinstance(made, list) else [made]
        fix = event.data.get("fix_unit")  # task keys repeat across a parent and its fix units: say whose task it is
        tag = f"[{fix}] " if isinstance(fix, str) and fix else ""
        for level, message in lines:
            if log.isEnabledFor(level):
                log.log(level, "%s %s%s", event.unit, tag, message)

    def _compare(self, old: str | None, new: str) -> str:
        return f" {self._project_url}/-/compare/{old}...{new}" if self._project_url and old else ""

    def commit(self, sha: str, message: str) -> None:
        """A commit the harness made (`Git.on_commit`)."""
        self._head = sha
        log.info("%s commit %s %s", self._unit, sha[:10], _clip(message.splitlines()[0] if message else "", 100))

    def pushed(self, branch: str, old: str | None, new: str) -> None:
        """A push of the unit branch (`Git.on_push`); the first push of a branch starts from the run's base commit."""
        self._branch, self._head = branch, new
        start = old or self._base
        span = f"{start[:10]}..{new[:10]}" if start else new[:10]
        log.info("%s pushed %s %s%s", self._unit, branch, span, self._compare(start, new))

    def _seconds(self, since: datetime | None, event: LedgerEvent) -> str:
        return f"{max((event.ts - since).total_seconds(), 0):.1f}s" if since else "?s"

    def _run_started(self, e: LedgerEvent) -> tuple[int, str]:
        self._started = e.ts
        self._unit = e.unit
        self._base = str(e.data["base"]) if e.data.get("base") else None
        self._branch = str(e.data.get("branch") or "")
        commit = str(e.data.get("harness_commit") or "unknown")[:12]
        iteration = e.data.get("iteration")
        shown = f"iteration {iteration}, " if iteration is not None else ""
        return logging.INFO, f"run {e.run_id} started ({shown}harness {commit})"

    def _selected(self, e: LedgerEvent) -> list[_Line]:
        role, name = e.data.get("role"), e.data.get("selected")
        probes = e.data.get("probes")
        parts = _probe_parts(probes) if isinstance(probes, dict) else []
        out: list[_Line] = []
        for skipped in e.data.get("skipped") or []:
            if isinstance(skipped, dict):
                why = _clip(skipped.get("reason") or skipped.get("step") or "unavailable", 80)
                out.append((logging.INFO, f"{role}: {skipped.get('profile')} skipped — {why}"))
        index = e.data.get("fallback_index")
        escalated_from = e.data.get("escalated_from")
        if escalated_from:  # an escalation's index is absolute in the chain: say what it was, not "fallback #n"
            tail = f", escalated from {escalated_from}"
        else:
            tail = ", fallback #" + str(index) if isinstance(index, int) and index > 0 else ""
        checks = f" ({' · '.join(parts)})" if parts else ""
        out.append((logging.INFO, f"{role}: {name} ok{checks} → selected{tail}"))
        return out

    def _limit(self, e: LedgerEvent) -> tuple[int, str]:
        return logging.WARNING, f"agent limit: {e.data.get('tool')} {e.data.get('kind')} ({e.data.get('source')})"

    def _phase(self, e: LedgerEvent) -> tuple[int, str]:
        before = e.data.get("from") or "none"
        why = self._review_reason(e)
        return logging.INFO, f"phase {before} → {e.data.get('to')} ({e.data.get('trigger')}{why})"

    def _review_reason(self, e: LedgerEvent) -> str:
        """Why an `in_review` unit went back (SPEC 12.0): the commit(s) after H, or the red jobs on H."""
        d = e.data
        if d.get("trigger") == "repository_ci_failed":
            jobs = ", ".join(str(j.get("name")) for j in d.get("jobs") or [] if isinstance(j, dict))
            return f": {jobs} on {str(d.get('head'))[:10]}" if jobs else ""
        commits = [c for c in d.get("commits") or [] if isinstance(c, dict)]
        if d.get("lost"):
            return ": the hand-off commit is not on the branch"
        if not commits:
            return ""
        newest = commits[-1]
        count = f"{len(commits)} commit{'' if len(commits) == 1 else 's'}"
        shown = f"{str(newest.get('sha'))[:10]} {_clip(newest.get('subject'), 80)} by {_clip(newest.get('author'), 40)}"
        return f": {count}, {shown}"

    def _ci_failed(self, e: LedgerEvent) -> tuple[int, str]:
        d = e.data
        jobs = ", ".join(str(j.get("name")) for j in d.get("jobs") or [] if isinstance(j, dict))
        pipeline = f" (pipeline {d.get('pipeline')})" if d.get("pipeline") is not None else ""
        return (
            logging.WARNING,
            f"repository CI failed on {str(d.get('head'))[:10]}: {jobs}{pipeline}; l4 run re-verifies",
        )

    def _ci_preexisting(self, e: LedgerEvent) -> tuple[int, str]:
        jobs = ", ".join(str(j) for j in e.data.get("jobs") or [])
        return logging.INFO, f"CI jobs red on H and on the base: {jobs} (pre-existing, no fix round)"

    def _ci_step(self, e: LedgerEvent) -> tuple[int, str]:
        d = e.data
        what = _clip(d.get("command") or d.get("step") or "", 100)
        why = f" ({_clip(d.get('reason'), 100)})" if d.get("reason") else ""
        return logging.INFO, f"CI job {d.get('job')}: failing step {d.get('status')}{why}" + (
            f" `{what}`" if what else ""
        )

    def _unfrozen(self, e: LedgerEvent) -> tuple[int, str]:
        paths = ", ".join(str(p) for p in e.data.get("paths") or [])
        if e.data.get("reason") == "named_by_task":  # an event without a reason is a human answer
            kept = "; ".join(
                f"{k.get('path')} ({k.get('why')})" for k in e.data.get("kept") or [] if isinstance(k, dict)
            )
            what = paths or ("nothing" + (f"; kept {kept}" if kept else ""))
            return logging.INFO, f"task {e.data.get('task')} opened by its text ({e.data.get('source')}): {what}"
        label = ""
        if e.data.get("reason") == "delegate_answer":  # L4-DLG-014: an unfreeze by the delegate is never a person's
            label = f" (delegate_override, {e.data.get('model') or e.data.get('profile') or 'the delegate'})"
        return logging.INFO, f"task {e.data.get('task')} unfrozen by {e.data.get('question')}{label}: {paths}"

    def _raised(self, e: LedgerEvent) -> tuple[int, str]:
        """The question's title, else its target (a verdict question of an older ledger), else nothing: never `None`."""
        what = _clip(e.data.get("title") or e.data.get("target") or "", 100)
        return logging.INFO, f"question {e.data.get('id')} raised ({e.data.get('kind')})" + (
            f": {what}" if what else ""
        )

    def _clarified(self, e: LedgerEvent) -> tuple[int, str]:
        qid = e.data.get("id")
        if e.data.get("auto_accepted"):
            return (
                logging.INFO,
                f"clarifier {qid}: auto-accepted ({e.data.get('kind')}, confidence {e.data.get('confidence')})",
            )
        reasons = "; ".join(_clip(r, 80) for r in (e.data.get("reasons") or [])) or str(e.data.get("status"))
        return logging.INFO, f"clarifier {qid}: escalated to a human ({reasons})"

    def _answered(self, e: LedgerEvent) -> tuple[int, str]:
        return logging.INFO, f"question {e.data.get('id')} answered by {e.data.get('by')}"

    def _task_started(self, e: LedgerEvent) -> tuple[int, str]:
        return logging.INFO, f"task {e.data.get('task')} started: {_clip(e.data.get('title'), 100)}"

    def _step_started(self, e: LedgerEvent) -> tuple[int, str]:
        self._steps[(e.data.get("fix_unit"), e.data.get("task"), e.data.get("phase"))] = e.ts
        d = e.data
        return (
            logging.INFO,
            f"agent {d.get('phase')} step started (task {d.get('task')}, attempt {d.get('attempt')}, {d.get('agent')})",
        )

    def _agent_idle(self, e: LedgerEvent) -> tuple[int, str]:
        d = e.data
        silent = _num(d.get("silent_s"))
        return (
            logging.WARNING,
            f"task {d.get('task')} {d.get('phase')} attempt {d.get('attempt')}: no activity from {d.get('profile')} "
            f"for {ago(silent or 0)}; L4 stopped it (implementer.idle_timeout)",
        )

    def _agent_finished(self, e: LedgerEvent) -> tuple[int, str]:
        d = e.data
        took = self._seconds(self._steps.pop((d.get("fix_unit"), d.get("task"), d.get("phase")), None), e)
        model = f", {d['model']}" if d.get("model") else ""
        detail = f": {_clip(d['detail'], 100)}" if d.get("status") != "ok" and d.get("detail") else ""
        peak = ""
        tokens, percent = _num(d.get("context_peak_tokens")), _num(d.get("context_peak_percent"))
        if tokens is not None:
            peak = f", context peak {tokens / 1000:.1f}k tokens"
        elif percent is not None:
            peak = f", context peak {percent:g}%"
        return (
            logging.INFO,
            f"agent {d.get('phase')} task {d.get('task')} {d.get('status')} ({took}{model}){detail}{peak}",
        )

    @staticmethod
    def _fix(f: dict) -> str:
        """`<field> <fix>` and what the fix says: `to`, `from`, `length`, `count`, then `was`."""
        out = f"{f.get('field')} {f.get('fix')}"
        if f.get("to") is not None:
            out += f" to {f['to']}"
        if f.get("from") is not None:
            out += f" from {f['from']}"
        if f.get("length") is not None:
            out += f" from {f['length']} characters"
        if f.get("count") is not None:
            out += f" {f['count']}"
        if f.get("was") is not None:
            out += f", was {f['was']}"
        return out

    def _result_normalized(self, e: LedgerEvent) -> tuple[int, str]:
        d = e.data
        fixes = d.get("fixes")
        shown = "; ".join(self._fix(f) for f in fixes if isinstance(f, dict)) if isinstance(fixes, list) else ""
        return (
            logging.INFO,
            f"task {d.get('task')} {d.get('phase')} attempt {d.get('attempt')}: L4 repaired the result ({shown})",
        )

    def _budget(self, e: LedgerEvent) -> tuple[int, str] | None:
        usd = _num(e.data.get("usd"))
        if usd is None:
            return None
        self._cost += usd
        who = e.data.get("task") or e.data.get("role") or e.data.get("profile")
        return logging.INFO, f"cost +{_usd(usd)} ({who}), run total {_usd(self._cost)}"

    def _gate(self, e: LedgerEvent) -> _Line | list[_Line]:
        d = e.data
        new = d.get("red_new_failing")
        if isinstance(new, int) and not isinstance(new, bool) and new > 0:  # a red gate that fails only on new tests
            tests = "1 new test fails" if new == 1 else f"{new} new tests fail"
            return [(logging.INFO, f"red: {tests}, as intended"), (logging.DEBUG, self._gate_line(d))]
        return logging.INFO, self._gate_line(d)

    @staticmethod
    def _gate_line(d: dict) -> str:
        counts = ""
        if d.get("tests") is not None:
            counts = f", {d['tests']} tests: {d.get('passed')} passed, {d.get('failed')} failed"
        why = f" — {_clip(d['reason'], 100)}" if d.get("status") != "pass" and d.get("reason") else ""
        ran_nothing = d.get("tests") == 0 or d.get("exit_code") == 2 or bool(d.get("collection_errors"))
        expected = (  # a zeroed run that ran no test did not "fail as expected": it did not run (L4-IMP-064)
            " (expected: zero values must fail)"
            if d.get("name") in ZEROED_GATES and d.get("status") == "fail" and not ran_nothing
            else ""
        )
        return f"gate {d.get('name')} {d.get('status')}{expected} (exit {d.get('exit_code')}{counts}){why}"

    def _check_inconclusive(self, e: LedgerEvent) -> tuple[int, str]:
        d = e.data
        return logging.WARNING, (
            f"task {d.get('task')} {d.get('phase')}: the {d.get('check')} check could not decide "
            f"({_clip(d.get('reason') or 'no reason', 200)}); no attempt counted, {d.get('question')} asks a person"
        )

    def _check_accepted(self, e: LedgerEvent) -> tuple[int, str]:
        d = e.data
        subjects = d.get("criteria") or d.get("tests") or []
        noun = "criteria" if d.get("criteria") else "tests"
        return logging.INFO, (
            f"task {d.get('task')}: {d.get('question')} accepted {len(subjects)} {noun} on the evidence of the real run"
        )

    def _zero_kept(self, e: LedgerEvent) -> tuple[int, str]:
        d = e.data
        functions = d.get("functions") or []
        return logging.INFO, (
            f"gate {d.get('gate')}: kept {len(functions)} function(s) real ({d.get('cause')}): "
            f"{_clip(', '.join(str(f) for f in functions), 200)}"
        )

    def _red_ok(self, e: LedgerEvent) -> tuple[int, str]:
        n = len(e.data.get("tests") or [])
        if e.data.get("tdd") == "already-satisfied":  # the tests passed on the base: nothing failed, no green step runs
            if not n:  # no test was added: the tests an earlier task wrote carry the criteria (L4-IMP-003)
                return logging.INFO, f"task {e.data.get('task')} already satisfied by existing tests, no green step"
            tests = "1 new test passes" if n == 1 else f"{n} new tests pass"
            return logging.INFO, f"task {e.data.get('task')} already satisfied: {tests} on the base, no green step"
        return logging.INFO, f"task {e.data.get('task')} red ok: {n} new test(s) failing as expected"

    def _red_resumed(self, e: LedgerEvent) -> tuple[int, str]:
        return logging.INFO, f"task {e.data.get('task')} red already committed: resuming at green"

    def _done(self, e: LedgerEvent) -> tuple[int, str] | None:
        if e.data.get("tdd") == "already-satisfied":
            return None  # `_red_ok` already said so; there was no green step to report
        if e.data.get("tdd") == "already-done":
            return logging.INFO, f"task {e.data.get('task')} done: {e.data.get('reason')}"
        return logging.INFO, f"task {e.data.get('task')} green ok: all tests passing"

    def _attempt_failed(self, e: LedgerEvent) -> tuple[int, str]:
        d = e.data
        on = f" on {d['profile']}" if d.get("profile") else ""
        return (
            logging.WARNING,
            f"task {d.get('task')} {d.get('phase')} attempt {d.get('attempt')} failed{on}: {_clip(d.get('reason'))}",
        )

    def _breaker(self, e: LedgerEvent) -> tuple[int, str]:
        profiles = [p for p in e.data.get("profiles") or [] if isinstance(p, dict)]
        if len(profiles) >= 2:
            ran = ", ".join(f"{p.get('profile')} {p.get('failures')}" for p in profiles)
            return logging.WARNING, f"halted: {e.data.get('reason')} (task {e.data.get('task')}: {ran})"
        return logging.WARNING, f"halted: {e.data.get('reason')} (task {e.data.get('task')})"

    @staticmethod
    def _count(value: object) -> str:
        """`failures` is a number, or the list of the failed attempts; neither: say it without a number."""
        if isinstance(value, list | tuple):
            return str(len(value))
        return str(value) if isinstance(value, int) and not isinstance(value, bool) else ""

    def _escalated(self, e: LedgerEvent) -> tuple[int, str]:
        d = e.data
        n = self._count(d.get("failures"))
        after = f" after {n} failed attempts" if n else ""
        return (
            logging.INFO,
            f"task {d.get('task')} {d.get('phase')}: escalated from {d.get('from')} to {d.get('to')}{after}",
        )

    def _escalation_skipped(self, e: LedgerEvent) -> tuple[int, str]:
        d = e.data
        n = self._count(d.get("failures"))
        failed = f"failed {n} attempts" if n else "failed its attempts"
        return (
            logging.WARNING,
            f"task {d.get('task')} {d.get('phase')}: {d.get('from')} {failed}; no later profile can take it "
            f"({_clip(d.get('reason'))}); it stays on {d.get('from')}",
        )

    def _prompt_rendered(self, e: LedgerEvent) -> tuple[int, str] | None:
        note = e.data.get("retry_note")
        if not isinstance(note, dict):
            return None  # a prompt without a note stays silent, as before
        step = e.data.get("phase") or e.data.get("role")  # the real event names the step by `role`
        return (
            logging.INFO,
            f"task {e.data.get('task')} {step}: the prompt holds the person's retry note of {note.get('ts')}",
        )

    def _doctor_check(self, e: LedgerEvent) -> tuple[int, str]:
        d = e.data
        level = logging.WARNING if d.get("status") == "fail" else logging.INFO
        return level, f"doctor {d.get('id')} {d.get('status')}: {_clip(d.get('message'))}"

    def _guard(self, e: LedgerEvent) -> tuple[int, str]:
        d = e.data
        return logging.WARNING, f"guard violation: {d.get('rule')} on {_clip(d.get('path'), 80)} → {d.get('action')}"

    def _base_merged(self, e: LedgerEvent) -> tuple[int, str]:
        d = e.data
        behind = int(d.get("behind") or 0)
        resolved = [str(f) for f in d.get("resolved") or []]
        detail = f"{behind} commit{'' if behind == 1 else 's'}"
        detail += f"; resolved {', '.join(resolved)}" if resolved else ""
        return (
            logging.INFO,
            f"base merged: {d.get('base')}@{str(d.get('base_sha'))[:10]} into {self._branch or 'the unit branch'} "
            f"as {str(d.get('merge_sha'))[:10]} ({detail})",
        )

    def _base_conflict(self, e: LedgerEvent) -> tuple[int, str]:
        d = e.data
        files = ", ".join(str(f) for f in d.get("files") or [])
        return (
            logging.WARNING,
            f"base merge conflict with {d.get('base')}@{str(d.get('base_sha'))[:10]}: {files}; "
            "merge it by hand and push (exit 1)",
        )

    def _verify_step(self, e: LedgerEvent) -> tuple[int, str]:
        return logging.DEBUG, f"verify round {e.data.get('round')} step {e.data.get('step')}: {e.data.get('status')}"

    def _verify_judge(self, e: LedgerEvent) -> tuple[int, str]:
        d = e.data
        return (
            logging.INFO,
            f"verify judge (profile {d.get('profile')}): {d.get('status')} "
            f"({d.get('calls')} call(s), {d.get('model') or 'model unknown'})",
        )

    def _verdict(self, e: LedgerEvent) -> tuple[int, str]:
        d = e.data
        crit = ""
        if d.get("criteria_total") is not None:
            crit = f", {d.get('criteria_passed')}/{d['criteria_total']} criteria pass"
        return (
            logging.INFO,
            f"verdict {d.get('verdict')} (round {d.get('round')}{crit}, {d.get('findings')} finding(s))",
        )

    def _pr_updated(self, e: LedgerEvent) -> tuple[int, str]:
        self._mr = str(e.data.get("url"))
        if self._project_url is None and "/-/merge_requests/" in self._mr:
            self._project_url = self._mr.split("/-/merge_requests/")[0]
        state = "draft" if e.data.get("draft", True) else "ready"
        return logging.INFO, f"MR {e.data.get('url')} ({state})"

    def _pr_ready(self, e: LedgerEvent) -> tuple[int, str]:
        return logging.INFO, f"MR {e.data.get('url')} marked ready for review"

    def _pr_labels(self, e: LedgerEvent) -> tuple[int, str]:
        return logging.INFO, f"MR !{e.data.get('number')} labels: {', '.join(map(str, e.data.get('labels') or []))}"

    def _finished(self, e: LedgerEvent) -> list[_Line]:
        took = self._seconds(self._started, e)
        cost = f", cost {_usd(self._cost)}" if self._cost else ""
        lines = [(logging.INFO, f"run finished: exit {e.data.get('exit_code')} in {took}{cost}")]
        if self._head and self._base:
            diff = f" diff {self._project_url}/-/compare/{self._base}...{self._head}" if self._project_url else ""
            mr = f" MR {self._mr}" if self._mr else ""
            lines.append(
                (
                    logging.INFO,
                    f"summary: branch {self._branch} head {self._head[:10]} base {self._base[:10]}{diff}{mr}",
                )
            )
        return lines


def artefacts_note(environ: Mapping[str, str], upload_artifacts: bool) -> str:
    """What the artefacts line says when a GitHub Actions job uploads nothing (`ci.upload_artifacts: false`): the
    evidence is then the excerpts of the committed ledger (L4-IMP-064). Empty everywhere else."""
    if environ.get("GITHUB_ACTIONS") == "true" and not upload_artifacts:
        return (
            " (not uploaded: ci.upload_artifacts is false; the ledger's gate.finished and task.attempt_failed events "
            "carry the excerpts)"
        )
    return ""


def log_artefacts(out_dir: Path, run_id: str, note: str = "") -> None:
    """Once, after the last unit: where this run's agent transcripts and gate logs are (a CI job uploads `.l4-out/`
    unless `note` says it does not)."""
    out = out_dir.resolve()
    log.info("artefacts: %s/, %s/%s", out / "agent" / run_id, out / "gates" / run_id, note or " (CI: job artifacts)")


def project_web_url(environ: Mapping[str, str], gitlab_api_url: str | None, project: str | None) -> str | None:
    """The project's web address: `CI_PROJECT_URL` in a job, else the API host plus a `group/project` path."""
    if environ.get("CI_PROJECT_URL"):
        return environ["CI_PROJECT_URL"].rstrip("/")
    if gitlab_api_url and project and not project.isdigit():
        return f"{gitlab_api_url.rstrip('/').removesuffix('/api/v4')}/{project.strip('/')}"
    return None
