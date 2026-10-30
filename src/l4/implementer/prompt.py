"""Versioned prompt templates and `render_prompt` (SPEC L4-IMP-004).

Sections, in order: harness contract; unit context; the task and the unit's criteria; answered questions and lessons
(`data_blocks`: answers from `l4.clarifier.inject`; lessons are M1); the phase; the gate command; the output
contract. Everything that comes from the repository or from an agent is placed inside an `<l4:data>` block whose
closing tag it cannot forge.
M1: overrides from `.l4/prompts/` of the base branch (CFG-004), the single/stuck/repair templates, `trim_context`
with a real tokenizer estimate, lessons as `data_blocks`.
"""

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from importlib import resources
from pathlib import Path
from typing import Any, Literal

from l4.fsutil import UnsafeFile, read_regular_file
from l4.implementer.result import FILE_RESULT_SCHEMA, RESULT_SCHEMA, TraceRules, trace_rules
from l4.implementer.unit_context import (
    CHARS_PER_TOKEN as CHARS_PER_TOKEN,  # re-exported (the clarifier)
)
from l4.implementer.unit_context import (
    MAX_SOURCE_BYTES,
    Convention,
    Cut,
    SourceFile,
    cut_line,
    plan_context,
    safe_label,
    section_keys,
)
from l4.specs.base import Criterion, Framework
from l4.specs.criteria import linked_criteria

Role = Literal["red", "green", "single"]
_TAG = re.compile(r"<\s*(/?)\s*l4\s*:\s*data", re.IGNORECASE)
_ADAPTER_LINE = re.compile(r"^@([a-z0-9-]+): (.*)$")
WINDOW_SHARE = 0.6  # the whole prompt may fill this share of a stated model window
NOT_SHOWN_RESERVE = 2_000  # room for the `Not shown in full` section, which depends on the cuts
_VERSION = re.compile(r"^version: (\d+)\n\n")


@dataclass(frozen=True)
class Template:
    name: str
    version: int
    body: str


@dataclass(frozen=True)
class PromptContext:
    unit_id: str
    adapter: str
    task_key: str
    task_title: str
    sources: tuple[tuple[str, str], ...] = ()  # (path relative to the unit directory, text); see `source_files`
    criteria: tuple[Criterion, ...] = ()
    gate_command: str = ""
    result_path: Path | None = None  # only for an adapter that writes its result to a file
    previous_failure: str | None = None
    # (heading, blocks): answered questions, lessons. The supplier wraps its text in `<l4:data>` blocks itself.
    data_blocks: tuple[tuple[str, str], ...] = ()
    context_budget_tokens: int = 32000
    static_gate_commands: tuple[str, ...] = ()  # lint and typecheck: a step that makes them fail is rejected
    run_ledger: str | None = None  # the run's ledger, repo-relative: it shows as modified in `git status` (expected)
    e2e_dir: str | None = None  # where the browser tests of `gates.e2e` live; None when the project has no e2e gate
    e2e_base_url_env: str = "L4_E2E_BASE_URL"
    unfrozen: tuple[tuple[str, str], ...] = ()  # green only: (frozen test path, question id) that a human answer freed
    named: tuple[str, ...] = ()  # green only: support files the task's own text opened
    adds_tests: bool = False  # single only: the chore adds tests (a coverage hold's task): `single_tests.md`
    task_links: tuple[str, ...] = ()  # a Kiro leaf's `_Requirements: 1.1, 2_` refs; () for OpenSpec (kiro-e2e K20)
    # How a test names the criteria it checks (`{trace_rule}` in the templates, L4-CRT-002). None: decided from
    # `gate_command` by `trace_rules` (the pytest marker for a pytest gate, else the id in the test name).
    trace_rule: str | None = None
    # red only (L4-OPS-015): the tests of the base that trace a criterion a spec edit changed, and the changes
    # (`requirement`, `old_id`, `old_text`, `new_id`, `new_text`); both empty unless the task was reopened by an edit
    named_existing: tuple[str, ...] = ()  # red only (L4-IMP-082): `path::name` of the existing tests red may change
    # red only (L4-IMP-089): (token as written, why) of the names the task text uses that no test was found for
    named_kept: tuple[tuple[str, str], ...] = ()
    stale_tests: tuple[str, ...] = ()
    stale_changes: tuple[Mapping[str, Any], ...] = ()
    # kiro-prompt-context: the unit's sources as read (`sources` is converted when this is empty), the project
    # conventions, the task's whole block from `tasks.md` (empty: the title and the links line), the unit directory
    # relative to the repository, and the unit's own criteria (a Kiro leaf's links are numbers of these)
    source_files: tuple[SourceFile, ...] = ()
    conventions: tuple[Convention, ...] = ()
    task_block: str = ""
    unit_rel: str = ""
    budget_source: str = "implementer"
    window_tokens: int | None = None  # the selected model's context window, when the profile states it
    own_criteria: tuple[Criterion, ...] = ()
    max_criteria_per_test: int = 3  # `verifier.max_criteria_per_test`: the cap the contract and the red phase state
    # ci-evidence (L4-IMP-080, L4-IMP-081): the `NAME=value` pairs the gates get in CI, sorted; the CI job a
    # single-phase chore answers. Both empty: the prompt is the one without them.
    gate_env_ci: tuple[str, ...] = ()
    ci_job: str | None = None


@dataclass(frozen=True)
class RenderedPrompt:
    text: str
    sha256: str
    template_version: str
    sources: tuple[str, ...]
    cuts: tuple[Cut, ...] = ()
    budget_tokens: int = 0
    budget_source: str = "implementer"
    over_window: bool = False  # the never-cut parts alone exceed the share of the stated window


def load_template(name: str) -> Template:
    text = resources.files("l4.implementer").joinpath("templates", f"{name}.md").read_text(encoding="utf-8")
    match = _VERSION.match(text)
    if match is None:
        raise ValueError(f"template {name} has no version line")
    return Template(name, int(match.group(1)), text[match.end() :])


def defuse(text: str) -> str:
    """Rewrite every `<l4:data` and `</l4:data` in text, so the text cannot open or end a block (SPEC L4-SEC-003)."""
    return _TAG.sub(lambda m: f"<\\{m.group(1)}l4:data", text)


def _require_wrapped(heading: str, text: str) -> None:
    """A supplier's blocks must be `<l4:data>` blocks that open and close in turn, with nothing outside them: text
    that was not wrapped and defused would reach the agent as instructions."""
    tags = [m.group(1) == "/" for m in _TAG.finditer(text)]
    opens_first = text.lstrip().lower().startswith("<l4:data")
    if not (opens_first and text.rstrip().endswith("</l4:data>") and tags == [i % 2 == 1 for i in range(len(tags))]):
        raise ValueError(f"the {heading!r} data blocks are not wrapped in <l4:data> blocks")


def data_block(source: str, text: str) -> str:
    """`<l4:data source="...">` around text that must stay information."""
    safe = defuse(text)
    return f'<l4:data source="{safe_label(source)}">\n{safe}\n</l4:data>'


def _contract(template: Template, ctx: PromptContext) -> str:
    kept = []
    for line in template.body.rstrip("\n").splitlines():
        if "{ledger}" in line and ctx.run_ledger is None:
            continue
        match = _ADAPTER_LINE.match(line)
        if match is None:
            kept.append(line)
        elif match.group(1) == ctx.adapter:
            kept.append(f"- {match.group(2)}")
    rules = _trace_rules(ctx)
    text = "\n".join(kept).replace("{gate}", ctx.gate_command).replace("{ledger}", ctx.run_ledger or "")
    text = text.replace("{trace_rule}", rules.rule).replace("{trace_stub}", rules.stub)
    return text.replace("{max_criteria}", str(ctx.max_criteria_per_test))


def _trace_rules(ctx: PromptContext) -> TraceRules:
    """The trace wording for the unit's test gate; a `trace_rule` set on the context replaces the contract sentence."""
    rules = trace_rules(ctx.gate_command)
    return replace(rules, rule=ctx.trace_rule) if ctx.trace_rule is not None else rules


def result_values_line(schema: Mapping[str, Any], phase: str) -> str:
    """The one line next to the phase heading that names the values the result's `status` and `phase` can take
    (SCN-IMP-M1). It is built from the result schema, so an edit of the schema's enum reaches the prompt. The agent's
    own text never enters it. Before it, the allowed values sat only in the schema at the end of the prompt, and a
    model that had just read `# Phase: RED` wrote `"status": "red"`."""
    if phase not in schema["properties"]["phase"]["enum"]:  # never a value the schema would reject
        raise ValueError(f"no result values for phase {phase!r}")
    statuses = " | ".join(str(v) for v in schema["properties"]["status"]["enum"])
    return (
        f"result values: status is one of {statuses} (the outcome of this step, never the phase name); "
        f'phase is "{phase}".'
    )


def _listed(criterion: Criterion) -> str:
    """A criterion with its id, alias and full text, the text indented under them (L4-IMP-050)."""
    text = "\n".join(f"  {line}" if line.strip() else "" for line in criterion.text.strip().splitlines())
    return f"- {criterion.id}  {criterion.alias}" + (f"\n{text}" if text else "")


def _source_files(ctx: PromptContext) -> tuple[SourceFile, ...]:
    """The unit's sources: `source_files`, else `sources` as they were given (path and text)."""
    if ctx.source_files:
        return ctx.source_files
    return tuple(
        SourceFile(path, f"{ctx.unit_rel}/{path}" if ctx.unit_rel else path, text, len(text.encode("utf-8")))
        for path, text in ctx.sources
    )


def _criteria_section(ctx: PromptContext) -> tuple[str, str]:
    """(the task block's text, the criteria section). A Kiro leaf shows its `_Requirements:_` line and gets only the
    criteria it names (kiro-e2e K20); a leaf whose refs name none, and every OpenSpec task, gets the whole list."""
    linked = linked_criteria(ctx.own_criteria or ctx.criteria, ctx.task_links)
    with_links = "" if ctx.task_block else f"\n_Requirements: {', '.join(ctx.task_links)}_"
    if not ctx.task_links:
        title, shown = ctx.task_title, ctx.criteria
        lead = (
            "OpenSpec does not link tasks to scenarios, so all of them are listed; cover those that this task's "
            "requirement names."
        )
    elif linked:
        title, shown = f"{ctx.task_title}{with_links}", tuple(linked)
        lead = (
            "This task's `_Requirements:_` line names these criteria; cover these. The unit's other criteria belong "
            "to its other tasks: do not test them here."
        )
    else:
        title, shown = f"{ctx.task_title}{with_links}", ctx.criteria
        lead = "This task's `_Requirements:_` line names none of the criteria below, so all of them are listed."
    listing = "\n".join(_listed(c) for c in shown) or "(the unit has no scenarios)"
    return title, f"# Criteria of this unit\n{lead}\n" + data_block("criteria", listing)


def _stale_section(ctx: PromptContext) -> str:
    """The red step of a reopened task (L4-OPS-015): which tests were written for the old text of a changed
    criterion, and what the criterion says now."""
    changes = "\n".join(
        f"- Requirement {c.get('requirement')}: id {c.get('old_id')} -> "
        + (f"{c.get('new_id')}" if c.get("new_id") else "(removed)")
        + f"\n  old text: {c.get('old_text')}\n  new text: {c.get('new_text') or '(removed)'}"
        for c in ctx.stale_changes
    )
    tests = "\n".join(f"- {t}" for t in ctx.stale_tests)
    return (
        "# Stale tests\nA spec edit changed the criteria below after these tests were written, so the tests assert "
        "the OLD text and contradict the new one. They must be replaced, not kept: delete each one, or rewrite it "
        "under a NEW name for the new criterion id. The harness does not count a stale test that is gone or fails as "
        "a regression. Your red test for the new id is a new test (a new name) and fails against the current code. "
        "Every other existing test stays as it is: do not change or delete it.\n"
        + data_block("changed criteria", changes)
        + "\n"
        + data_block("stale tests", tests)
    )


MAX_NAMED_LINE_CHARS = 200


def one_line(text: str, limit: int = MAX_NAMED_LINE_CHARS) -> str:
    """A name from the repository as one line of at most `limit` characters: whitespace (a newline too) becomes a
    space, so a describe or test name cannot start a heading of its own."""
    line = " ".join(text.split())
    return line if len(line) <= limit else f"{line[:limit]}..."


def _named_section(ctx: PromptContext) -> str:
    """The existing tests that the reviewed text names and that red changes in place (L4-IMP-082, L4-IMP-089). Their
    names come from the repository: a data block, one bounded line each (L4-SEC-003)."""
    parts = ["# Existing tests this task changes in place"]
    if ctx.named_existing:
        listing = "\n".join(f"- {one_line(test)}" for test in ctx.named_existing)
        parts.append(
            "The task's text or one of its criteria names these existing tests. Change each one in place so that it "
            "asserts what the task asks, and so that it fails against the current code by an assertion; do not "
            "delete or rename one, and still write the new tests the criteria need:\n"
            + data_block("existing tests this task changes in place", listing)
        )
    if ctx.named_kept:
        skipped = "\n".join(f"- {one_line(token)}: {one_line(why)}" for token, why in ctx.named_kept)
        parts.append(
            "The task's text also names these, but no test was found to change in place (write the name as the "
            "tests report it, or the path and name as `path::name`), so each stays as it is:\n"
            + data_block("names the harness did not apply", skipped)
        )
    return "\n".join(parts)


CI_JOB_LINE = (
    "This task answers the repository CI job `{job}`. The gates here may not show that failure. If they do not, do "
    "not guess a change they cannot check: say so in notes_for_verifier and name the file and the change a person "
    "must make."
)
MAX_JOB_NAME_CHARS = 200


def _job_name(job: str) -> str:
    """A CI job's name is repository-influenced text: one line, cut, and unable to open or end a data block."""
    return defuse(" ".join(job.split())[:MAX_JOB_NAME_CHARS]).replace("`", "'")


def render_prompt(role: Role, ctx: PromptContext) -> RenderedPrompt:
    if role not in ("red", "green", "single"):
        raise ValueError(f"no prompt template for role {role!r}")
    contract = load_template("contract")
    phase = load_template("single_tests" if role == "single" and ctx.adds_tests else role)
    title, criteria = _criteria_section(ctx)
    task_source = f"{ctx.unit_rel}/tasks.md" if ctx.task_block and ctx.unit_rel else "tasks.md"
    task_section = f"# Task {ctx.task_key}\n" + data_block(task_source, ctx.task_block or title)
    after: list[str] = []
    for heading, text in ctx.data_blocks:
        _require_wrapped(heading, text)
        after.append(f"# {heading.capitalize()}\n{text}")
    if ctx.previous_failure:
        after.append(
            "# Your previous attempt was rejected\nThe harness rejected it for the reason below; do not repeat it.\n"
            + data_block("previous attempt", ctx.previous_failure)
        )
    if role == "green" and ctx.unfrozen:
        by = ", ".join(sorted({q for _, q in ctx.unfrozen}))
        listing = "\n".join(f"- {path} ({question})" for path, question in ctx.unfrozen)
        after.append(
            f"# Tests unfrozen by a human answer\nThe human answer to {by} names these frozen test files, so you may "
            "change them as the answer says; every other test stays frozen.\n" + data_block("unfrozen tests", listing)
        )
    if role == "green" and ctx.named:
        after.append(
            "# Files this task names\nThe task's own text names these frozen support files, so you may change them as "
            "the task says. Keep every existing statement of each one as it is: add new statements, never edit, move "
            "or rebind an old one, and do not patch or assign the unit's code from them (setting the environment is "
            "fine). Every other test and support file stays frozen.\n"
            + data_block("files this task names", "\n".join(f"- {path}" for path in ctx.named))
        )
    if role == "red" and (ctx.named_existing or ctx.named_kept):
        after.append(_named_section(ctx))
    if role == "red" and ctx.stale_tests:
        after.append(_stale_section(ctx))
    rules = _trace_rules(ctx)
    phase_text = phase.body.strip("\n").replace("{result_values}", result_values_line(RESULT_SCHEMA, role))
    fills = (
        ("{trace_rule}", rules.rule), ("{trace_also}", rules.also), ("{trace_form}", rules.form),
        ("{max_criteria}", str(ctx.max_criteria_per_test)),
    )  # fmt: skip
    for placeholder, value in fills:
        phase_text = phase_text.replace(placeholder, value)
    after.append(phase_text)
    if role == "single" and ctx.ci_job:
        after.append("# CI failure\n" + CI_JOB_LINE.format(job=_job_name(ctx.ci_job)))
    gate = (
        f"# Gate command\nRun tests only with `{ctx.gate_command}` (the network is off, and `uv run` cannot write its "
        "cache here). The harness installed the dependencies before this step."
    )
    if ctx.gate_env_ci:
        listed = ", ".join(f"`{pair}`" for pair in ctx.gate_env_ci)
        gate += (
            f"\nThe gates run with {listed} set, as the repository's CI does; your shell in this step does not have "
            f"them. To reproduce a failure that only the CI shows, run the gate command as "
            f"`{' '.join(ctx.gate_env_ci)} {ctx.gate_command}`. Under them tools may colour their output (typer and "
            "rich under `GITHUB_ACTIONS`), so a test of a command's help or output must not depend on colour: strip "
            "the ANSI codes before comparing (for example `click.unstyle`), or turn the command's colour off inside "
            "the test."
        )
    if ctx.static_gate_commands:
        listed = ", ".join(f"`{c}`" for c in ctx.static_gate_commands)
        if role == "red":
            gate += (
                f"\nThe harness also runs {listed} after your step. Your new tests (and any stub) must pass them: "
                "a lint or type error in a test file rejects this attempt, and those files are frozen afterwards."
            )
        else:
            gate += f"\nThe harness also runs {listed} after your step and rejects the task while they fail."
    if role == "red" and ctx.e2e_dir:
        # an e2e directory under `tests/` (`tests/e2e`) is not contradicted by "never under `tests/`"
        elsewhere = "and nowhere else" if f"{ctx.e2e_dir}/".startswith("tests/") else "never under `tests/`"
        gate += (
            f"\nBrowser (Playwright) tests are not run by that command: put each one in `{ctx.e2e_dir}/` (for example "
            f"`{ctx.e2e_dir}/test_<name>.py`), {elsewhere}, where the unit gate would run it without a "
            f"server and reject the attempt. The harness serves the app for `gates.e2e` and gives its address in "
            f"`{ctx.e2e_base_url_env}`; tag the test with the criterion id like any other."
        )
    after.append(gate)
    version = f"{contract.name}@{contract.version}+{phase.name}@{phase.version}"
    if ctx.result_path is None:  # a native adapter: the CLI enforces the schema
        fields = (
            f'phase "{role}", task_ids ["{ctx.task_key}"], criteria_ids = the criterion ids your work traces, '
            "tests_added = the pytest node ids you added, suppressions = every new `# noqa` or `# type: ignore`, "
            "files_changed; use null for anything you have nothing for."
        )
        output = f"# Output\nYour final message is the result JSON object (schema enforced): {fields}"
    else:  # prompt contract (SPEC 8.1, design D1): nothing enforces the schema, so the prompt carries it
        template = load_template("output")
        schema = json.dumps(FILE_RESULT_SCHEMA, separators=(",", ":"), sort_keys=True)
        output = template.body.strip("\n").replace("{path}", str(ctx.result_path)).replace("{schema}", schema)
        version += f"+{template.name}@{template.version}"
    after.append(output)
    framework = Framework.OPENSPEC if ctx.unit_id.startswith("openspec:") else Framework.KIRO
    # what the budget does not govern: the contract, the data blocks, the phase, the gate and the output
    others = len(_contract(contract, ctx)) + sum(len(x) for x in after) + 2 * (len(after) + 4)
    tokens, source, over = ctx.context_budget_tokens, ctx.budget_source, False
    if ctx.window_tokens:  # the model's window caps the WHOLE prompt at WINDOW_SHARE of it (owner decision)
        room = int(ctx.window_tokens * WINDOW_SHARE) * CHARS_PER_TOKEN - others - NOT_SHOWN_RESERVE
        over = room - len(task_section) - len(criteria) < 0  # contract, task and criteria alone: never cut
        if max(room, 0) // CHARS_PER_TOKEN < tokens:
            tokens, source = max(room, 0) // CHARS_PER_TOKEN, "model_window"
    plan = plan_context(
        fixed_chars=len(task_section) + len(criteria), budget_tokens=tokens,
        conventions=ctx.conventions, source_files=_source_files(ctx),
        keys=section_keys(ctx.task_block or title, ctx.task_links, framework),
    )  # fmt: skip
    parts = [_contract(contract, ctx)]
    if plan.conventions:
        parts.append(
            "# Project conventions\nThe project's conventions for this task. The harness contract says how to use "
            "them.\n" + "\n".join(data_block(b.path, b.body()) for b in plan.conventions)
        )
    parts.append("# Unit context\n" + "\n".join(data_block(b.path, b.body()) for b in plan.sources))
    if plan.cuts:
        parts.append(
            "# Not shown in full\nThese files were cut to fit this prompt or could not be read in full. The harness "
            "contract says what to do with them.\n"
            + data_block("not shown in full", "\n".join(cut_line(c) for c in plan.cuts))
        )
    parts += [task_section, criteria, *after]
    text = "\n\n".join(parts) + "\n"
    return RenderedPrompt(
        text,
        hashlib.sha256(text.encode("utf-8")).hexdigest(),
        version,
        tuple(s.name for s in _source_files(ctx)),
        plan.cuts,
        tokens,
        source,
        over,
    )


def collect_sources(unit_dir: Path) -> tuple[tuple[str, str], ...]:
    """proposal.md, design.md, a Kiro unit's requirements.md and bugfix.md, and the spec deltas of the unit, in that
    order. A symlink, a non-regular file or an oversized file is skipped: the path is repository content."""
    candidates = [unit_dir / name for name in ("proposal.md", "design.md", "requirements.md", "bugfix.md")]
    specs = unit_dir / "specs"
    if specs.is_dir() and not specs.is_symlink():
        candidates += [d / "spec.md" for d in sorted(specs.iterdir(), key=lambda p: p.name) if d.is_dir()]
    found = []
    for path in candidates:
        try:
            data = read_regular_file(path, limit=MAX_SOURCE_BYTES)
        except (UnsafeFile, OSError):
            continue
        found.append((path.relative_to(unit_dir).as_posix(), data.decode("utf-8", errors="replace")))
    return tuple(found)
