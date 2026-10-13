"""The resolver table of a base merge: the harness-owned files of a unit (and of its fix units) that git may settle
by the rules of `questions_merge`, `tasks_merge` and `feedback_merge` instead of stopping at a conflict."""

from pathlib import Path

from l4.specs.base import Framework
from l4.specs.feedback import FEEDBACK_FILENAME
from l4.specs.feedback_merge import merge_feedback
from l4.specs.followup import feedback_home, read_follow_up_marker
from l4.specs.questions import QUESTIONS_FILENAME
from l4.specs.questions_merge import merge_questions
from l4.specs.tasks_merge import merge_task_markers
from l4.vcs.merge import Resolvers, Sides

TASKS_FILENAME = "tasks.md"


def follow_up_feedback_rel(unit_dir: Path, root: Path) -> str | None:
    """The repository-relative path of the parent's `feedback.md` that a follow-up unit's branch edits (it sets the
    items `taken` and `addressed`), or None for a unit that is no follow-up (L4-FBK-010, review #3)."""
    if read_follow_up_marker(unit_dir) is None:
        return None
    home = feedback_home(unit_dir)
    if home == unit_dir:
        return None
    try:
        return (home / FEEDBACK_FILENAME).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def harness_resolvers(unit_rel: str, framework: Framework, *, follow_up_feedback: str | None = None) -> Resolvers:
    """`unit_rel`: the unit directory, relative to the repository. A fix unit sits next to it as `<unit_rel>-fix-N`.
    `follow_up_feedback`: for a follow-up unit, the parent's `feedback.md` (`follow_up_feedback_rel`): the follow-up's
    branch edits that one file, so a base merge that also changed it (a new item) settles by the feedback rules."""

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

    def feedback(sides: Sides) -> bytes:
        return merge_feedback(sides.base, sides.ours, sides.theirs)

    def tasks(sides: Sides) -> bytes:
        return merge_task_markers(sides.ours, sides.theirs, framework)

    table: Resolvers = (
        (owned(QUESTIONS_FILENAME), questions),
        (owned(TASKS_FILENAME), tasks),
        (owned(FEEDBACK_FILENAME), feedback),
    )
    if follow_up_feedback is None:
        return table
    return (*table, (lambda path: path == follow_up_feedback, feedback))
