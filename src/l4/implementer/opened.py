"""What a support file that a task's text or a person's answer opened may become in green (design D5).

Three rules, checked on the red version and the new version of the file, after the agent step and before the frozen
files are put back:

1. every top-level statement of the red version is still there, unchanged (`ast.dump`) and in order; new statements may
   come between them (`guards.appended_only` without its "only at the end" and "definitions only" limits);
2. no new statement binds a name that the red version binds, or a name that pytest reads at module level;
3. no new code patches or assigns a symbol of a production module that the unit changed.

`check_opened` returns the reason to put the file back (the `why` of `guard.violation{rule: "opened file"}`), or
None."""

import ast
from collections.abc import Collection

from .guards import _MODULE_HOOKS, _bound


def check_opened(
    before: str,
    after: str,
    *,
    named_by_task: bool,
    unit_modules: Collection[str],
) -> str | None:
    """None when `after` is an allowed edit of `before`, else why not. Rules 1 and 2 apply to a file opened by task
    text (`named_by_task`); a file opened by an answer keeps only rule 3."""
    try:
        old, new = ast.parse(before).body, ast.parse(after).body
    except (SyntaxError, ValueError):
        return "does not parse"
    if named_by_task:
        return _kept_and_not_rebound(old, new)
    return None


def _kept_and_not_rebound(old: list[ast.stmt], new: list[ast.stmt]) -> str | None:
    kept, added = 0, []
    for node in new:
        if kept < len(old) and ast.dump(node) == ast.dump(old[kept]):
            kept += 1
        else:
            added.append(node)
    if kept < len(old):
        return "changes an existing statement"
    bound = {name for node in old for name in _bound(node)}
    for node in added:
        if isinstance(node, ast.Import | ast.ImportFrom) and any(ast.dump(node) == ast.dump(o) for o in old):
            continue  # a repeated import is no rebinding
        for name in sorted(_bound(node)):
            if name in bound or _MODULE_HOOKS.match(name):
                return f"rebinds {name}"
        bound |= _bound(node)
    return None
