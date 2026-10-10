"""Commit trailers (L4-IMP-007). M1: state-vcs-locks 1.5 `parse` arrives with reconcile."""

from dataclasses import dataclass

from l4.exitcodes import ExitCode, L4Exit


class MissingTrailer(L4Exit):
    def __init__(self, message: str) -> None:
        super().__init__(ExitCode.INTERNAL_ERROR, message)


@dataclass(frozen=True)
class CommitTrailers:
    unit: str
    run_id: str
    iteration: int
    phase: str
    task: str | None = None
    tdd: str | None = None  # red | green | already-satisfied | exempt
    agent: str | None = None
    fallback_from: str | None = None
    step: str | None = None  # `<task>/<phase>/<attempt>` until step_key lands (M1: state-vcs-locks 1.22)


def render(trailers: CommitTrailers) -> list[tuple[str, str]]:
    """In SPEC order, `L4-Step` last. Refuses a missing mandatory field or a value that is not one line, before
    any git process exists: a value with a newline would forge a second trailer."""
    if not trailers.unit or not trailers.run_id or not trailers.phase or trailers.iteration < 1:
        raise MissingTrailer("a harness commit needs L4-Unit, L4-Run, L4-Iteration (>= 1) and L4-Phase")
    ordered = [
        ("L4-Unit", trailers.unit),
        ("L4-Run", trailers.run_id),
        ("L4-Iteration", str(trailers.iteration)),
        ("L4-Phase", trailers.phase),
        ("L4-Task", trailers.task),
        ("L4-TDD", trailers.tdd),
        ("L4-Agent", trailers.agent),
        ("L4-Fallback-From", trailers.fallback_from),
        ("L4-Step", trailers.step),
    ]
    rendered = [(key, value) for key, value in ordered if value is not None]
    for key, value in rendered:
        if not value or "\n" in value or "\r" in value:
            raise MissingTrailer(f"trailer {key} must be a non-empty single line")
    return rendered
