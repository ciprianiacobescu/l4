"""The action form of an adoption (adoption-kit L4-ACT-004, L4-ACT-005, D4, D5): resolving `--harness-ref` to a sha,
and reading the pin out of a workflow. `l4 upgrade` moves it by re-rendering the whole workflow (`l4.init.upgrade`)."""

import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import yaml

from l4.ci.github import ACTION_PATH
from l4.exitcodes import ExitCode, L4Exit

LS_REMOTE_TIMEOUT_S = 60
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_SSH_REPO = re.compile(r"^ssh://git@github\.com/(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?$")


def remote_url(repository: str) -> str:
    """Where `owner/repo` is read from (`git ls-remote`): its https URL, which git's credential helpers can serve."""
    return f"https://github.com/{repository}.git"


def resolve_ref(remote: str, ref: str, environ: Mapping[str, str]) -> str:
    """The commit sha `ref` names in `remote`, from one `git ls-remote`: an annotated tag's commit (the peeled entry)
    first, then a lightweight tag, then a branch. Exit 2, naming `ref`, when it names nothing or the remote cannot be
    read."""
    if not _REF.match(ref):
        raise L4Exit(ExitCode.USAGE_ERROR, f"--harness-ref {ref!r} is not a tag or branch name")
    patterns = [f"refs/tags/{ref}", f"refs/tags/{ref}^{{}}", f"refs/heads/{ref}"]
    try:
        done = subprocess.run(  # argv list, never a shell; no prompt for a credential
            ["git", "ls-remote", "--", remote, *patterns],
            capture_output=True, text=True, timeout=LS_REMOTE_TIMEOUT_S, check=False, stdin=subprocess.DEVNULL,
            env={**environ, "GIT_TERMINAL_PROMPT": "0"},
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise L4Exit(
            ExitCode.USAGE_ERROR, f"--harness-ref {ref!r}: cannot read {remote} ({type(exc).__name__})"
        ) from None
    if done.returncode != 0:
        reason = (done.stderr.strip().splitlines() or ["git ls-remote failed"])[-1]
        raise L4Exit(ExitCode.USAGE_ERROR, f"--harness-ref {ref!r}: cannot read {remote}: {reason}")
    found: dict[str, str] = {}
    for line in done.stdout.splitlines():
        sha, _, name = line.partition("\t")
        if _SHA.match(sha):
            found[name] = sha
    for name in (f"refs/tags/{ref}^{{}}", f"refs/tags/{ref}", f"refs/heads/{ref}"):
        if name in found:
            return found[name]
    raise L4Exit(ExitCode.USAGE_ERROR, f"--harness-ref {ref!r} names no tag or branch in {remote}")


@dataclass(frozen=True)
class WorkflowPin:
    """What an action-form workflow says about its harness."""

    uses: str  # the `uses:` value of the setup action step, for example `o/harness/.github/actions/l4@<sha>`
    pin: str | None  # the text after `@`, None for a local action (`./.github/actions/l4`)
    inputs: Mapping[str, Any]

    @property
    def local(self) -> bool:
        return self.pin is None

    @property
    def repository(self) -> str | None:
        """`owner/repo` of the harness: the `uses:` repository, or for the local copy the `repository` input."""
        if self.pin is not None:
            return self.uses.split("@", 1)[0].removesuffix(f"/{ACTION_PATH}")
        match = _SSH_REPO.match(str(self.inputs.get("repository", "")))
        return match["repo"] if match else None

    @property
    def effective(self) -> str | None:
        """The pin that counts: the sha of `uses:`, or for a local action its `commit` input."""
        return self.pin if self.pin is not None else (str(self.inputs["commit"]) if "commit" in self.inputs else None)


def read_pin(workflow_text: str) -> WorkflowPin | None:
    """The setup-action step of an action-form workflow, or None when there is none (or it is not YAML)."""
    try:
        document = yaml.safe_load(workflow_text)
    except yaml.YAMLError:
        return None
    jobs = document.get("jobs") if isinstance(document, dict) else None
    for job in jobs.values() if isinstance(jobs, dict) else ():
        for step in job.get("steps", []) if isinstance(job, dict) else ():
            uses = step.get("uses") if isinstance(step, dict) else None
            if not isinstance(uses, str):
                continue
            action, _, pin = uses.partition("@")
            if action == f"./{ACTION_PATH}" or action.endswith(f"/{ACTION_PATH}"):
                inputs = step.get("with")
                return WorkflowPin(uses, pin or None, inputs if isinstance(inputs, dict) else {})
    return None
