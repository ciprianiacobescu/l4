"""Secret redaction (SPEC L4-OBS-002): configured values plus common token shapes."""

import re
from collections.abc import Iterable, Mapping
from typing import Any

# Order matters: the specific prefixes come before the generic `sk-`. Minimum lengths keep
# ordinary words such as `sk-learn` out, and the lookbehind keeps a prefix inside a longer identifier
# (`add-task-assignment`, `desk-booking-view`) from matching: a unit id is a routing key.
_B = r"(?<![A-Za-z0-9_\-])"
TOKEN_SHAPES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (kind, re.compile(pattern if kind == "private-key" else _B + pattern))
    for kind, pattern in (
        ("anthropic-key", r"sk-ant-[A-Za-z0-9_\-]{16,}"),
        ("openai-key", r"sk-[A-Za-z0-9_\-]{16,}"),
        ("github-token", r"gh[pous]_[A-Za-z0-9]{20,}"),
        ("github-pat", r"github_pat_[A-Za-z0-9_]{20,}"),
        ("gitlab-pat", r"glpat-[A-Za-z0-9_\-]{16,}"),
        ("gitlab-trigger", r"glptt-[A-Za-z0-9_\-]{16,}"),
        ("gitlab-deploy", r"gldt-[A-Za-z0-9_\-]{16,}"),
        ("gitlab-job", r"glcbt-[A-Za-z0-9_\-]{16,}"),
        ("jwt", r"eyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"),
        ("mintkey", r"mk_agent_[A-Za-z0-9]{16,}"),
        ("private-key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    )
)

# Agent-specific JSON fields (SPEC L4-OBS-002, spikes 01-05): the value goes, the key stays.
# `\\?"` also matches the same field inside a JSON string (a tool call's output carried in an event). The value stops
# at a line end: a JSON string holds no raw newline, and a quote on a later line must not hide the lines between (a
# source comment that opens the shape would otherwise take a diff's changed lines with it).
FIELD_SHAPE = re.compile(
    r'(\\?"(?:chatgptAccountId|accountId|chatgpt_account_id|account_id|orgId|orgName|signature)\\?"\s*:\s*\\?")'
    r'[^"\\\n\r]*(\\?")'
)
KEY_FRAGMENT = re.compile(_B + r"sk-[A-Za-z0-9_\-]*\*{3}[A-Za-z0-9_\-]*")  # codex prints `sk-...***...` fragments

MIN_VALUE_LENGTH = 8  # shorter values would corrupt ordinary text

_URL_TOKEN = re.compile(r"^https?://gitlab-ci-token:(?P<t>[^@/]+)@")


def url_job_token(environ: Mapping[str, str]) -> str:
    """The job token inside GitLab's `CI_REPOSITORY_URL` (`https://gitlab-ci-token:<token>@host/...`), else "". It is
    the real one even when a CI/CD variable named `CI_JOB_TOKEN` overrides the predefined variable."""
    found = _URL_TOKEN.match(environ.get("CI_REPOSITORY_URL") or "")
    return found.group("t") if found else ""


class Redactor:
    def __init__(self, values: Mapping[str, str]) -> None:
        usable = [(name, v) for name, v in values.items() if len(v) >= MIN_VALUE_LENGTH]
        self._values = sorted(usable, key=lambda item: len(item[1]), reverse=True)
        # the forge's addresses (`l4.forge.urls.ForgeUrls`), set in place once the config is known: what is committed
        # carries `<forge>` in their place (L4-OBS-002); the console and the JSONL mirror keep the real link
        self.forge_urls: Any = None

    def scrub_for_commit(self, text: str) -> str:
        """`text` as it may be committed: the forge host replaced. Not a secret filter (`redact_text` is)."""
        return self.forge_urls.scrub(text) if self.forge_urls is not None else text

    @classmethod
    def from_env(cls, names: Iterable[str], environ: Mapping[str, str]) -> "Redactor":
        values = {name: environ[name] for name in names if environ.get(name)}
        if token := url_job_token(environ):  # a secret too, whatever `CI_JOB_TOKEN` holds (its own name: the URL's
            values["job-token"] = token  # whole value may be listed too, and must not take this one's place)
        return cls(values)

    def adopt(self, other: "Redactor") -> None:
        """Add `other`'s values in place. The logging handler and the outcome writer hold this very object, so the
        config-aware values reach every sink once the config is read (L4-OBS-002)."""
        merged = dict(self._values) | dict(other._values)
        self._values = sorted(merged.items(), key=lambda item: len(item[1]), reverse=True)

    def kinds_in(self, text: str) -> list[str]:
        """What `redact_text` would redact as a secret in `text`, one entry per kind and never the value: `value:<NAME>`
        for a configured value, the shape's kind (`anthropic-key`, `gitlab-pat`, ...) for a token shape. The agent-field
        and key-fragment rules are not here: a field named `signature` is not a secret in a source file."""
        found: list[str] = []
        for name, value in self._values:
            if value in text:
                found.append(f"value:{name}")
                text = text.replace(value, " ")
        for kind, pattern in TOKEN_SHAPES:  # in redaction order: `sk-ant-…` is an anthropic key, not also an openai one
            if pattern.search(text):
                found.append(kind)
                text = pattern.sub(" ", text)
        return found

    def redact_text(self, text: str) -> str:
        for name, value in self._values:
            text = text.replace(value, f"[REDACTED:{name}]")
        for kind, pattern in TOKEN_SHAPES:
            text = pattern.sub(f"[REDACTED:{kind}]", text)
        text = FIELD_SHAPE.sub(r"\1[REDACTED:agent-field]\2", text)
        return KEY_FRAGMENT.sub("[REDACTED:key-fragment]", text)

    def redact_obj(self, obj: Any) -> Any:
        if isinstance(obj, str):
            return self.redact_text(obj)
        if isinstance(obj, dict):
            return {self.redact_text(k) if isinstance(k, str) else k: self.redact_obj(v) for k, v in obj.items()}
        if isinstance(obj, list | tuple):
            return [self.redact_obj(v) for v in obj]
        return obj
