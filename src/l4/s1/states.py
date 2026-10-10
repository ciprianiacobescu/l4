"""The states the S1 questions are asked over (M16-G8, plan D6 and D7).

Every engine gets the identical state at the Laya budget (`S1Cfg.laya_budget()`), cut by relevance: the part that
matters least is cut first (`trim_state`), never the labels around it. A state never carries its own label, except
`tests-ok`, which is the stated sanity question: the `file-relevant` state has no module verdict and the
`change-covered` state has no executed or missing counts, only the code, the tests' names and where they mention it.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from l4.clarifier.router import approx_tokens, trim_state

MAX_MENTIONS = 8
_HEADING = re.compile(r"^##\s+(.*?)\s*$", re.M)


@dataclass(frozen=True)
class State:
    text: str
    truncated: bool  # a part was cut to fit the budget: a "no" may be the budget's


def _sections(markdown: str) -> dict[str, str]:
    heads = list(_HEADING.finditer(markdown))
    out: dict[str, str] = {}
    for i, head in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(markdown)
        out[head.group(1).strip().lower()] = markdown[head.end() : end].strip()
    return out


def spec_summary(name: str, proposal: str) -> str:
    """The change name, `What Changes` and `Impact` of an OpenSpec proposal; the whole text when it has neither."""
    sections = _sections(proposal)
    parts = [f"Change: {name}"]
    for title in ("what changes", "impact"):
        if sections.get(title):
            parts.append(f"{title.title()}:\n{sections[title]}")
    return "\n\n".join(parts) if len(parts) > 1 else f"Change: {name}\n\n{proposal.strip()}"


def hunk_summary(diff: str, *, max_lines: int = 40) -> str:
    """The added and removed lines of a `git diff` of one file, without the headers."""
    lines = [ln for ln in diff.splitlines() if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
    shown = lines[:max_lines]
    more = f"\n... ({len(lines) - max_lines} more changed lines)" if len(lines) > max_lines else ""
    return "\n".join(shown) + more


def static_mentions(name: str, test_sources: Mapping[str, str], *, limit: int = MAX_MENTIONS) -> list[str]:
    """`path:line: text` of the test lines that mention `name` (the last part of a qualname), in path order."""
    simple = name.rsplit(".", 1)[-1]
    if not simple or simple.startswith("<"):
        return []
    pattern = re.compile(rf"\b{re.escape(simple)}\b")
    found: list[str] = []
    for path in sorted(test_sources):
        for number, line in enumerate(test_sources[path].splitlines(), 1):
            if pattern.search(line):
                found.append(f"{path}:{number}: {line.strip()}")
                if len(found) >= limit:
                    return found
    return found


def _build(render_parts, parts: Sequence[str], instruction: str, budget: int) -> State:
    text = trim_state(render_parts, parts, instruction=instruction, max_tokens=budget)
    return State(text, truncated=text != render_parts(parts))


def file_state(
    spec: str, path: str, hunk: str, *, instruction: str, budget: int, declared: Sequence[str] = ()
) -> State:
    """Spec summary, what the spec's design and tasks name (`declared`), the path and a hunk summary. The hunk is cut
    first, then the prose: the path against the declared scope decides."""

    def render(parts: Sequence[str]) -> str:
        named = f"\n\nNamed in the spec's design and tasks:\n{parts[2]}" if parts[2] else ""
        return f"Spec:\n{parts[1]}{named}\n\nChanged file: {path}\n\nChange:\n{parts[0]}"

    return _build(render, [hunk, spec, "\n".join(f"- {d}" for d in declared)], instruction, budget)


def function_state(
    path: str,
    qualname: str,
    changed: str,
    test_names: Sequence[str],
    mentions: Sequence[str],
    *,
    instruction: str,
    budget: int,
) -> State:
    """Signature and changed lines, the unit's test names and where they mention the function. Not what ran."""

    def render(parts: Sequence[str]) -> str:
        return (
            f"Changed function: {qualname} in {path}\n\nChanged code:\n{parts[2]}\n\n"
            f"Tests of the unit:\n{parts[1] or '(none)'}\n\nMentions in those tests:\n{parts[0] or '(none)'}"
        )

    parts = ["\n".join(mentions), "\n".join(test_names), changed]
    return _build(render, parts, instruction, budget)


def tests_state(
    counts: Mapping[str, int],
    new_tests: Sequence[tuple[str, str]],
    *,
    problems: Sequence[tuple[str, str]] = (),
    instruction: str,
    budget: int,
) -> State:
    """The sanity question: the JUnit counts, the new tests' status and the tests that did not pass are the answer,
    on purpose (D6). The problems are cut first."""
    head = ", ".join(f"{counts.get(k, 0)} {k}" for k in ("total", "passed", "failed", "errored", "skipped"))
    listed = "\n".join(f"{test_id}: {status}" for test_id, status in new_tests)
    other = "\n".join(f"{test_id}: {status}" for test_id, status in problems)

    def render(parts: Sequence[str]) -> str:
        text = f"Test run: {head}\n\nNew tests:\n{parts[1] or '(none)'}"
        return f"{text}\n\nNot passed:\n{parts[0]}" if parts[0] else text

    return _build(render, [other, listed], instruction, budget)


def fits(state: State, instruction: str, budget: int) -> bool:
    return approx_tokens(state.text + instruction) <= budget
