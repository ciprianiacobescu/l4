"""Which of the project's jobs run on a pipeline of a given source (gitlab-adoption D1, L4-INS-007).

A small three-valued evaluator of `rules`, `only`, `except`, a job's `when` and `workflow: rules` for the pipelines the
harness starts (schedule, api, trigger, web and the push of a unit branch). Whatever it cannot read is `unknown`, and
an unknown job never raises the empty-pipeline warning. Pure: no I/O.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from l4.ci.gitlab_jobs import GitlabCi

Source = Literal["schedule", "api", "trigger", "web", "push"]
Decision = Literal["run", "skip", "unknown"]
Tri = bool | None  # True / False / None (unknown)

HARNESS_JOB = "l4"
_NOT_NORMAL_STAGES = frozenset({".pre", ".post"})
_DEFAULT_STAGE = "test"
_SOURCE_KEYWORDS = {"schedules": "schedule", "api": "api", "triggers": "trigger", "web": "web", "pushes": "push"}
_NEVER_KEYWORDS = frozenset({"tags", "merge_requests", "external", "external_pull_requests", "chat", "pipelines"})


@dataclass(frozen=True)
class Pipeline:
    source: Source
    branch: str  # the branch the pipeline runs on (always a branch: no tag or merge-request pipelines)
    default_branch: str


@dataclass(frozen=True)
class JobsOn:
    workflow: Decision
    run: tuple[str, ...]
    skip: tuple[str, ...]
    unknown: tuple[str, ...]
    normal_run: tuple[str, ...] = ()  # run jobs whose stage is not .pre/.post
    normal_unknown: tuple[str, ...] = ()


# --- tri-state logic ---------------------------------------------------------------------------------------------


def _and(left: Tri, right: Tri) -> Tri:
    if left is False or right is False:
        return False
    return True if left is True and right is True else None


def _or(left: Tri, right: Tri) -> Tri:
    if left is True or right is True:
        return True
    return False if left is False and right is False else None


def _not(value: Tri) -> Tri:
    return None if value is None else not value


def _decision(value: Tri) -> Decision:
    return "unknown" if value is None else "run" if value else "skip"


# --- `if:` expressions -------------------------------------------------------------------------------------------

_TOKEN = re.compile(
    r"""\s*(?:
    (?P<var>\$[A-Za-z_][A-Za-z0-9_]*)
  | (?P<str>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')
  | (?P<re>/(?:\\.|[^/\\])*/[A-Za-z]*)
  | (?P<op>==|!=|=~|!~|&&|\|\||\(|\))
  | (?P<null>null\b)
    )""",
    re.VERBOSE,
)


class _Unreadable(Exception):
    pass


def _tokens(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    position = 0
    while text[position:].strip():
        match = _TOKEN.match(text, position)
        if match is None or match.end() == position:
            raise _Unreadable
        kind = match.lastgroup or ""
        found.append((kind, match.group(kind)))
        position = match.end()
    return found


def _known_variables(pipeline: Pipeline) -> dict[str, str]:
    known = {
        "CI_PIPELINE_SOURCE": pipeline.source,
        "CI_COMMIT_BRANCH": pipeline.branch,
        "CI_COMMIT_REF_NAME": pipeline.branch,
        "CI_DEFAULT_BRANCH": pipeline.default_branch,
        "CI_COMMIT_TAG": "",
    }
    known.update({"CI_MERGE_REQUEST_ID": "", "CI_MERGE_REQUEST_IID": ""})
    return known


def _is_empty_merge_request(name: str) -> bool:
    return name.startswith("CI_MERGE_REQUEST_")


class _Expr:
    """Recursive descent over the tokens: or > and > primary. A `_Unreadable` anywhere makes the whole unknown."""

    def __init__(self, tokens: list[tuple[str, str]], pipeline: Pipeline) -> None:
        self.tokens = tokens
        self.at = 0
        self.known = _known_variables(pipeline)

    def peek(self) -> tuple[str, str] | None:
        return self.tokens[self.at] if self.at < len(self.tokens) else None

    def take(self) -> tuple[str, str]:
        token = self.peek()
        if token is None:
            raise _Unreadable
        self.at += 1
        return token

    def parse(self) -> Tri:
        value = self.or_()
        if self.peek() is not None:
            raise _Unreadable
        return value

    def or_(self) -> Tri:
        value = self.and_()
        while self.peek() == ("op", "||"):
            self.take()
            value = _or(value, self.and_())
        return value

    def and_(self) -> Tri:
        value = self.primary()
        while self.peek() == ("op", "&&"):
            self.take()
            value = _and(value, self.primary())
        return value

    def primary(self) -> Tri:
        if self.peek() == ("op", "("):
            self.take()
            value = self.or_()
            if self.take() != ("op", ")"):
                raise _Unreadable
            return value
        left = self.take()
        nxt = self.peek()
        if nxt is None or nxt[0] != "op" or nxt[1] not in {"==", "!=", "=~", "!~"}:
            if left[0] != "var":
                raise _Unreadable
            value = self.value(left)
            return None if value is _UNKNOWN else bool(value)
        operator = self.take()[1]
        right = self.take()
        if operator in {"==", "!="}:
            result = self.equal(left, right)
            return result if operator == "==" else _not(result)
        result = self.match(left, right)
        return result if operator == "=~" else _not(result)

    def value(self, token: tuple[str, str]) -> Any:
        """The string a token stands for; `None` for null, `_UNKNOWN` for an unknown variable."""
        kind, text = token
        if kind == "null":
            return None
        if kind == "str":
            return text[1:-1]
        if kind == "var":
            name = text[1:]
            if name in self.known:
                return self.known[name] or None
            return None if _is_empty_merge_request(name) else _UNKNOWN
        raise _Unreadable

    def equal(self, left: tuple[str, str], right: tuple[str, str]) -> Tri:
        a, b = self.value(left), self.value(right)
        if a is _UNKNOWN or b is _UNKNOWN:
            return None
        return bool(a == b)

    def match(self, left: tuple[str, str], right: tuple[str, str]) -> Tri:
        if right[0] != "re" or left[0] != "var":
            raise _Unreadable
        subject = self.value(left)
        if subject is _UNKNOWN:
            return None
        return _regex_match(right[1], subject or "")


_UNKNOWN: Any = object()


def _regex_match(literal: str, subject: str) -> Tri:
    """`/re/flags` searched in `subject`; the flag `i` is honoured, any other flag or a pattern Python rejects is
    unknown."""
    end = literal.rindex("/")
    pattern, flags = literal[1:end], literal[end + 1 :]
    if flags not in ("", "i"):
        return None
    try:
        return re.search(pattern, subject, re.IGNORECASE if flags else 0) is not None
    except re.error:
        return None


def _evaluate_if(text: Any, pipeline: Pipeline) -> Tri:
    if not isinstance(text, str):
        return None
    try:
        return _Expr(_tokens(text), pipeline).parse()
    except _Unreadable:
        return None


# --- rules / only / except ---------------------------------------------------------------------------------------


def _rules_decision(rules: Any, job_when: Any, pipeline: Pipeline) -> tuple[Decision, str]:
    if not isinstance(rules, list):
        return "unknown", "rules is not a list"
    for index, item in enumerate(rules, 1):
        if not isinstance(item, dict):
            return "unknown", f"rules item {index} is not a mapping"
        condition: Tri = _evaluate_if(item["if"], pipeline) if "if" in item else True
        if condition is False:
            continue
        if condition is None:
            return "unknown", f"the if of rules item {index} cannot be evaluated"
        if "changes" in item or "exists" in item:
            return "unknown", f"rules item {index} depends on changes or exists"
        when = item.get("when", job_when if job_when is not None else "on_success")
        if when == "never":
            return "skip", f"rules item {index} says when: never"
        return "run", f"rules item {index} matches"
    return "skip", "no rules item matches"


def _entry_matches(entry: Any, pipeline: Pipeline) -> Tri:
    if not isinstance(entry, str):
        return None
    if entry == "branches":
        return True
    if entry in _NEVER_KEYWORDS:
        return False
    if entry in _SOURCE_KEYWORDS:
        return pipeline.source == _SOURCE_KEYWORDS[entry]
    if len(entry) >= 2 and entry.startswith("/") and "/" in entry[1:]:
        return _regex_match(entry, pipeline.branch)
    return entry == pipeline.branch


def _refs_match(value: Any, pipeline: Pipeline) -> Tri:
    """Whether an `only`/`except` value matches the pipeline (None: cannot tell)."""
    if isinstance(value, dict):
        if set(value) - {"refs"} or "refs" not in value:
            return None
        value = value["refs"]
    entries = [value] if isinstance(value, str) else value
    if not isinstance(entries, list):
        return None
    result: Tri = False
    for entry in entries:
        result = _or(result, _entry_matches(entry, pipeline))
    return result


def job_decision(job: Mapping[str, Any], pipeline: Pipeline) -> tuple[Decision, str]:
    """Whether `job` (its keys, `extends` already merged) runs on `pipeline`, and why."""
    if "rules" in job:
        return _rules_decision(job["rules"], job.get("when"), pipeline)
    if job.get("when") == "never":
        return "skip", "when: never"
    selected = _refs_match(job["only"], pipeline) if "only" in job else True
    excluded = _refs_match(job["except"], pipeline) if "except" in job else False
    verdict = _and(selected, _not(excluded))
    if verdict is None:
        return "unknown", "only or except cannot be evaluated"
    if verdict:
        return "run", "only and except allow the pipeline"
    return "skip", "only or except exclude the pipeline"


def workflow_decision(workflow: Any, pipeline: Pipeline) -> tuple[Decision, str]:
    """Whether `workflow: rules` creates a pipeline of this source on this branch."""
    if workflow is None:
        return "run", "no workflow"
    if not isinstance(workflow, dict):
        return "unknown", "workflow is not a mapping"
    if "rules" not in workflow:
        return "run", "workflow has no rules"
    return _rules_decision(workflow["rules"], None, pipeline)


def jobs_on(ci: GitlabCi, pipeline: Pipeline) -> JobsOn:
    """The project's jobs (not hidden, not trigger jobs, not the harness's own `l4`) by decision, names sorted."""
    run: list[str] = []
    skip: list[str] = []
    unknown: list[str] = []
    normal_run: list[str] = []
    normal_unknown: list[str] = []
    for job in ci.jobs:
        if job.trigger or job.name == HARNESS_JOB:
            continue
        keys = ci.raw.get(job.name, {})
        decision, _why = job_decision(keys, pipeline)
        stage = keys.get("stage")
        normal = (stage if isinstance(stage, str) else _DEFAULT_STAGE) not in _NOT_NORMAL_STAGES
        if decision == "run":
            run.append(job.name)
            if normal:
                normal_run.append(job.name)
        elif decision == "skip":
            skip.append(job.name)
        else:
            unknown.append(job.name)
            if normal:
                normal_unknown.append(job.name)
    return JobsOn(
        workflow_decision(ci.workflow, pipeline)[0],
        tuple(sorted(run)),
        tuple(sorted(skip)),
        tuple(sorted(unknown)),
        tuple(sorted(normal_run)),
        tuple(sorted(normal_unknown)),
    )
