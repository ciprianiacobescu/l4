"""The resolver table of a base merge: the harness-owned files of a unit (and of its fix units) that git may settle
by the rules of `questions_merge` and `tasks_merge` instead of stopping at a conflict."""

from l4.specs.base import Framework
from l4.specs.questions import QUESTIONS_FILENAME
from l4.specs.questions_merge import merge_questions
from l4.specs.tasks_merge import merge_task_markers
from l4.vcs.merge import Resolvers, Sides

TASKS_FILENAME = "tasks.md"


def harness_resolvers(unit_rel: str, framework: Framework) -> Resolvers:
    """`unit_rel`: the unit directory, relative to the repository. A fix unit sits next to it as `<unit_rel>-fix-N`."""

    def owned(name: str):
        def matches(path: str) -> bool:
            rest = path.removeprefix(unit_rel)
            if rest == path:
                return False
            head, _, leaf = rest.rpartition("/")
            return leaf == name and (head == "" or (head.startswith("-fix-") and "/" not in head))

        return matches

    def questions(sides: Sides) -> bytes:
        return merge_questions(
            sides.base, sides.ours, sides.theirs, sides.ours_newer,
            ours_lines=sides.ours_lines, theirs_lines=sides.theirs_lines,
        )  # fmt: skip

    def tasks(sides: Sides) -> bytes:
        return merge_task_markers(sides.ours, sides.theirs, framework)

    return ((owned(QUESTIONS_FILENAME), questions), (owned(TASKS_FILENAME), tasks))
