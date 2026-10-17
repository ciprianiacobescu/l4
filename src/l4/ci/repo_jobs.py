"""The repository's own CI jobs and whether the gates mirror them (adoption-lessons L4-ADO-006, design D6).

A heuristic for a warning, never a verdict: a job is *mirrored* when each of its commands is contained in a gate
command (setup, lint, test, e2e, or a gate a `yolo.profiles` entry names), or contains one; a job with no `run:`
command (only `uses:` steps or a reusable workflow) or with services is never mirrored. GitHub: the workflows under
`.github/workflows` except `l4.yml` that run on `push` or `pull_request`. GitLab: the jobs of `.gitlab-ci.yml` except
the harness's `l4` job. A file that does not parse is named in `problems`, never raised.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from l4.ci.gitlab_jobs import (
    GITLAB_CI_RELPATH,
    MAX_CI_BYTES,
    JobScript,
    gitlab_jobs,
    job_script,
)
from l4.config.schema import L4Config
from l4.fsutil import read_regular_file

WORKFLOWS_DIR = ".github/workflows"
HARNESS_WORKFLOW = "l4.yml"
HARNESS_JOB = "l4"
_TRIGGERS = ("push", "pull_request")
_PREFIXES = ("uv run ", ".venv/bin/", "python -m ")
# the options of `uv run` that choose the project or the lock, not the command: `--directory apps/api`, `--frozen`
_UV_RUN_OPTION = re.compile(r"^(?:--(?:directory|project|package)(?:=|\s+)\S+|--frozen|--locked|--no-sync)\s+")
_SPLIT = re.compile(r"\n|&&|;")


@dataclass(frozen=True)
class RepoJob:
    file: str  # the workflow's file name, or `.gitlab-ci.yml`
    name: str
    commands: tuple[str, ...]  # normalised
    services: tuple[str, ...] = ()
    container: bool = False


@dataclass(frozen=True)
class RepoCi:
    present: bool = False  # a CI file other than the harness's own exists
    jobs: tuple[RepoJob, ...] = ()
    problems: tuple[str, ...] = ()


def normalise(run: str) -> list[str]:
    """The commands of one `run:` string: split on newlines, `&&` and `;`; no empty line or comment; a leading
    `uv run ` (with its `--directory`, `--project`, `--package`, `--frozen`, `--locked` and `--no-sync` options),
    `.venv/bin/` and `python -m ` (repeatedly) stripped; whitespace collapsed."""
    found = []
    for part in _SPLIT.split(run):
        text = " ".join(part.split())
        if not text or text.startswith("#"):
            continue
        stripped = True
        while stripped:
            stripped = False
            for prefix in _PREFIXES:
                if text.startswith(prefix):
                    text, stripped = text[len(prefix) :].lstrip(), True
                    while prefix == "uv run " and (option := _UV_RUN_OPTION.match(text)):
                        text = text[option.end() :]
        if text:
            found.append(text)
    return found


def _on_names(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {v for v in value if isinstance(v, str)}
    if isinstance(value, dict):
        return {k for k in value if isinstance(k, str)}
    return set()


def _github(repo: Path) -> tuple[bool, list[RepoJob], list[str]]:
    folder = repo / WORKFLOWS_DIR
    files = sorted(p for p in folder.glob("*.y*ml") if p.suffix in (".yml", ".yaml") and p.name != HARNESS_WORKFLOW)
    jobs: list[RepoJob] = []
    problems: list[str] = []
    for path in files:
        try:
            document = yaml.safe_load(read_regular_file(path, limit=MAX_CI_BYTES).decode("utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            problems.append(f"{path.name}: cannot be read ({type(exc).__name__})")
            continue
        if not isinstance(document, dict):
            problems.append(f"{path.name}: the top level is not a mapping")
            continue
        triggers = _on_names(document.get("on", document.get(True)))  # YAML 1.1 reads a bare `on` as True
        block = document.get("jobs")
        if not triggers & set(_TRIGGERS) or not isinstance(block, dict):
            continue
        for name, job in block.items():
            if not isinstance(job, dict):
                continue
            steps = job.get("steps")
            runs = (
                [s["run"] for s in steps if isinstance(s, dict) and isinstance(s.get("run"), str)]
                if isinstance(steps, list)
                else []
            )
            services = job.get("services")
            commands = tuple(c for run in runs for c in normalise(run))
            jobs.append(
                RepoJob(
                    path.name, str(name), commands,
                    tuple(str(k) for k in services) if isinstance(services, dict) else (),
                    bool(job.get("container")),
                )
            )  # fmt: skip
    return bool(files), jobs, problems


def _gitlab(repo: Path) -> tuple[bool, list[RepoJob], list[str]]:
    found = gitlab_jobs(repo)
    if not found.present:
        return False, [], []
    problems = list(found.problems)
    jobs: list[RepoJob] = []
    try:
        text = read_regular_file(repo / GITLAB_CI_RELPATH, limit=MAX_CI_BYTES).decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return True, jobs, problems

    def load(relpath: str) -> str | None:
        try:
            return read_regular_file(repo / relpath, limit=MAX_CI_BYTES).decode("utf-8")
        except FileNotFoundError:
            return None
        except UnicodeDecodeError:
            raise OSError("not UTF-8") from None

    for job in found.jobs:
        if job.name == HARNESS_JOB or job.trigger:
            continue
        script = job_script(text, load, job.name)
        if not isinstance(script, JobScript):
            problems.append(f"{GITLAB_CI_RELPATH}: job {job.name} not compared ({script.reason})")
            continue
        commands = tuple(c for line in (*script.before, *script.script) for c in normalise(line))
        jobs.append(RepoJob(GITLAB_CI_RELPATH, job.name, commands))
    return True, jobs, problems


def repo_ci_jobs(repo: Path) -> RepoCi:
    """The jobs of the repository's own CI that run on `push` or `pull_request` (every GitLab job)."""
    github_present, github_jobs, github_problems = _github(repo)
    gitlab_present, gitlab, gitlab_problems = _gitlab(repo)
    return RepoCi(github_present or gitlab_present, (*github_jobs, *gitlab), (*github_problems, *gitlab_problems))


def _gate_commands(cfg: L4Config) -> list[str]:
    """The commands every verification round runs (setup, build, lint and typecheck in step 2, test and e2e in step
    3), and the extra gates a `yolo.profiles` entry names."""
    gates = cfg.gates
    commands = [*gates.setup, *gates.build, *gates.lint, *gates.typecheck, gates.test.command, gates.e2e.command]
    named = {kind for kinds in cfg.yolo.profiles.values() for kind in kinds}
    commands += [g.command for g in gates.extra if f"extra:{g.name}" in named]
    return [c for command in commands for c in normalise(command)]


def _mirrored(command: str, gates: list[str]) -> bool:
    return any(command in gate or gate in command for gate in gates)


def open_commands(job: RepoJob, cfg: L4Config) -> list[str]:
    """The commands of `job` that no gate command contains (or is contained in)."""
    gates = _gate_commands(cfg)
    return [c for c in job.commands if not _mirrored(c, gates)]


def opaque(job: RepoJob) -> bool:
    """A job the gates cannot mirror whatever they run: it has no `run:` command (only `uses:` steps such as docker or
    helm, or a reusable workflow) or it starts services."""
    return not job.commands or bool(job.services)


def unmirrored(jobs: Iterable[RepoJob], cfg: L4Config) -> list[RepoJob]:
    """The jobs with a command that no gate command contains (or is contained in), and the opaque ones."""
    return [j for j in jobs if open_commands(j, cfg) or opaque(j)]
