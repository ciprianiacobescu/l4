"""Who is asking: a person, or an agent (`l4 yolo accept`, `l4 questions`). The harness cannot know who types a
command: these markers keep honest agents from deciding for a person; they are not a security boundary."""

from collections.abc import Mapping

AGENT_MARKERS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "AI_AGENT", "CODEX_SANDBOX", "L4_RESULT_PATH")


def actor(environ: Mapping[str, str], stdin_tty: bool) -> tuple[str, str | None]:
    """`("person", None)` or `("agent", <marker>)`: a person is a terminal on stdin and no marker; stdout is not
    looked at, so `l4 yolo accept ... | tee log` stays a person's command."""
    for marker in AGENT_MARKERS:
        if environ.get(marker):
            return "agent", marker
    return ("person", None) if stdin_tty else ("agent", None)
