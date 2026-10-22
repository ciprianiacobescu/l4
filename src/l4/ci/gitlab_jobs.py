"""The jobs of a GitLab pipeline file: names, stages and runner tags, from `.gitlab-ci.yml` and its local includes
(forge-and-ci 2.19, M1.8 A11: CI-002; `l4 init`'s edit asserts on the same reader).

Not a GitLab CI interpreter. It reads what CI-002 and `init` need: the job names in order, the stage and the tags of
each (`extends` resolved, `default: tags` kept apart), the local includes one level deep, and a list of what was NOT
read (remote, project, template and component includes, nested includes, unreadable files). Same-named jobs of the
main file override those of an include key by key, as GitLab merges them.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from l4.fsutil import read_regular_file

GITLAB_CI_RELPATH = ".gitlab-ci.yml"
MAX_CI_BYTES = 1024 * 1024
_NOT_JOBS = frozenset(
    {"default", "include", "stages", "variables", "workflow", "image", "services", "cache", "before_script",
     "after_script", "spec"}
)  # fmt: skip
_MAX_EXTENDS_DEPTH = 5
Load = Callable[[str], str | None]  # a repository path -> its text, None when there is no such file
_ABSENT: Any = object()


class _Loader(yaml.SafeLoader):
    """GitLab's `!reference [job, key]` and any other custom tag are read as plain data, never executed."""


def _plain(loader: yaml.SafeLoader, suffix: str, node: yaml.Node) -> Any:
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    return loader.construct_scalar(node)  # type: ignore[arg-type]


_Loader.add_multi_constructor("!", _plain)


@dataclass(frozen=True)
class Tagged:
    """A custom YAML tag (`!reference [job, key]`) kept as a value by the script reader, which refuses it."""

    tag: str


class _StrictLoader(yaml.SafeLoader):
    """The script reader's loader: a custom tag is a `Tagged` value, never flattened into plain data."""


def _tagged(loader: yaml.SafeLoader, suffix: str, node: yaml.Node) -> Tagged:
    return Tagged(node.tag)


_StrictLoader.add_multi_constructor("!", _tagged)


@dataclass(frozen=True)
class CiJob:
    name: str
    source: str  # the file the job is first defined in
    stage: str | None
    tags: tuple[str, ...] | None  # None: no `tags` on the job or what it extends (`default: tags` may apply)
    trigger: bool = False  # a bridge job: it runs no script on a runner
    overridden: bool = False  # the main file sets keys of a job an include defined


@dataclass(frozen=True)
class GitlabCi:
    present: bool = False
    jobs: tuple[CiJob, ...] = ()
    default_tags: tuple[str, ...] | None = None
    not_checked: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()
    includes: tuple[str, ...] = ()  # the local includes that were read, normalised
    raw: Mapping[str, Mapping[str, Any]] = field(default_factory=dict, compare=False)  # job -> keys, `extends` merged
    workflow: Any = field(default=None, compare=False)  # the top-level `workflow`, as read (None: there is none)

    def effective_tags(self, job: CiJob) -> tuple[str, ...]:
        if job.tags is not None:
            return job.tags
        return self.default_tags or ()

    def job(self, name: str) -> CiJob | None:
        return next((j for j in self.jobs if j.name == name), None)


@dataclass
class _Walk:
    load: Load
    raw: dict[str, dict[str, Any]] = field(default_factory=dict)  # job or hidden key -> keys, merged
    first_source: dict[str, str] = field(default_factory=dict)
    overridden: set[str] = field(default_factory=set)
    order: list[str] = field(default_factory=list)
    default_tags: tuple[str, ...] | None = None
    not_checked: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    includes: list[str] = field(default_factory=list)
    loader: type[yaml.SafeLoader] = _Loader
    default_before: Any = _ABSENT  # `default: before_script` (else the deprecated top-level key), as read
    workflow: Any = None  # the top-level `workflow`; the main file's wins over an include's


def _parse(text: str, source: str, walk: _Walk) -> dict[str, Any] | None:
    try:
        document = yaml.load(text, Loader=walk.loader)  # noqa: S506  (a SafeLoader subclass)
    except yaml.YAMLError as exc:
        walk.problems.append(f"{source}: not valid YAML ({type(exc).__name__})")
        return None
    if document is None:
        return {}
    if not isinstance(document, dict):
        walk.problems.append(f"{source}: the top level is not a mapping")
        return None
    return document


def _tags(value: Any) -> tuple[str, ...] | None:
    if isinstance(value, list) and all(isinstance(t, str) for t in value):
        return tuple(value)
    return None


def _include_items(document: dict[str, Any]) -> list[Any]:
    include = document.get("include")
    if include is None:
        return []
    return include if isinstance(include, list) else [include]


def _local_path(item: Any) -> tuple[str | None, str | None]:
    """(local path, not-checked description) of one `include:` entry."""
    if isinstance(item, str):
        if item.startswith(("http://", "https://")):
            return None, f"remote include {item}"
        return item.lstrip("/"), None
    if isinstance(item, dict):
        if isinstance(item.get("local"), str):
            return item["local"].lstrip("/"), None
        for key in ("remote", "project", "template", "component"):
            if key in item:
                return None, f"{key} include {item[key]}"
    return None, "an include of a form this reader does not know"


def _add_jobs(document: dict[str, Any], source: str, walk: _Walk, *, main: bool) -> None:
    default = document.get("default")
    if isinstance(default, dict) and (tags := _tags(default.get("tags"))) is not None:
        walk.default_tags = tags
    if isinstance(default, dict) and "before_script" in default:
        walk.default_before = default["before_script"]
    elif "before_script" in document and walk.default_before is _ABSENT:
        walk.default_before = document["before_script"]
    if "workflow" in document and (main or walk.workflow is None):
        walk.workflow = document["workflow"]
    for key, value in document.items():
        if key in _NOT_JOBS or not isinstance(key, str) or not isinstance(value, dict):
            continue
        if key in walk.raw:
            walk.raw[key].update(value)
            if main:
                walk.overridden.add(key)
            continue
        walk.raw[key] = dict(value)
        walk.first_source[key] = source
        walk.order.append(key)


def _resolved_tags(name: str, walk: _Walk, depth: int = 0) -> tuple[str, ...] | None:
    job = walk.raw.get(name, {})
    if (own := _tags(job.get("tags"))) is not None:
        return own
    parents = job.get("extends")
    parents = [parents] if isinstance(parents, str) else parents if isinstance(parents, list) else []
    if depth >= _MAX_EXTENDS_DEPTH:
        return None
    for parent in reversed([p for p in parents if isinstance(p, str)]):  # the last parent wins, as in GitLab
        if (inherited := _resolved_tags(parent, walk, depth + 1)) is not None:
            return inherited
    return None


def _merged_keys(name: str, walk: _Walk, depth: int = 0) -> dict[str, Any]:
    """The keys of job `name` with `extends` merged in (the last parent first, the job's own keys last; shallow)."""
    job = walk.raw.get(name, {})
    merged: dict[str, Any] = {}
    parents = job.get("extends")
    parents = [parents] if isinstance(parents, str) else parents if isinstance(parents, list) else []
    if depth < _MAX_EXTENDS_DEPTH:
        for parent in [p for p in parents if isinstance(p, str)]:
            merged.update(_merged_keys(parent, walk, depth + 1))
    merged.update(job)
    return merged


def _read_files(text: str, load: Load, source: str, loader: type[yaml.SafeLoader]) -> tuple[_Walk, bool]:
    """The main file and its local includes merged into a `_Walk`; False when the main file does not parse."""
    walk = _Walk(load, loader=loader)
    main = _parse(text, source, walk)
    if main is None:
        return walk, False
    for item in _include_items(main):
        path, unchecked = _local_path(item)
        if unchecked is not None:
            walk.not_checked.append(unchecked)
            continue
        assert path is not None
        if "*" in path or "$" in path:
            walk.not_checked.append(f"local include {path} (a pattern or variable)")
            continue
        try:
            body = load(path)
        except OSError as exc:
            walk.problems.append(f"{path}: cannot be read ({type(exc).__name__})")
            continue
        if body is None:
            walk.problems.append(f"{path}: included but not found")
            continue
        walk.includes.append(path)
        included = _parse(body, path, walk)
        if included is None:
            continue
        if _include_items(included):
            walk.not_checked.append(f"nested includes of {path}")
        _add_jobs(included, path, walk, main=False)
    _add_jobs(main, source, walk, main=True)
    return walk, True


def parse_gitlab_ci(text: str, load: Load, *, source: str = GITLAB_CI_RELPATH) -> GitlabCi:
    walk, parsed = _read_files(text, load, source, _Loader)
    if not parsed:
        return GitlabCi(present=True, problems=tuple(walk.problems))
    jobs = tuple(
        CiJob(
            name, walk.first_source[name], walk.raw[name].get("stage") if isinstance(walk.raw[name].get("stage"), str)
            else None, _resolved_tags(name, walk), "trigger" in walk.raw[name], name in walk.overridden,
        )
        for name in walk.order
        if not name.startswith(".")
    )  # fmt: skip
    raw = {name: _merged_keys(name, walk) for name in walk.order if not name.startswith(".")}
    return GitlabCi(
        True, jobs, walk.default_tags, tuple(walk.not_checked), tuple(walk.problems), tuple(walk.includes), raw,
        walk.workflow,
    )  # fmt: skip


def gitlab_jobs(repo: Path) -> GitlabCi:
    """The jobs of `<repo>/.gitlab-ci.yml`; `present` is False when there is no such file."""
    path = repo / GITLAB_CI_RELPATH
    try:
        text = read_regular_file(path, limit=MAX_CI_BYTES).decode("utf-8")
    except FileNotFoundError:
        return GitlabCi()
    except (OSError, UnicodeDecodeError) as exc:
        return GitlabCi(present=True, problems=(f"{GITLAB_CI_RELPATH}: cannot be read ({type(exc).__name__})",))

    def load(relpath: str) -> str | None:
        try:
            return read_regular_file(repo / relpath, limit=MAX_CI_BYTES).decode("utf-8")
        except FileNotFoundError:
            return None
        except UnicodeDecodeError:
            raise OSError("not UTF-8") from None

    return parse_gitlab_ci(text, load)


# --- what a job runs (M1.10 decision 2): the commands of `before_script` and `script`, for the failing-step check ----


@dataclass(frozen=True)
class JobScript:
    before: tuple[str, ...]
    script: tuple[str, ...]


@dataclass(frozen=True)
class ScriptRefusal:
    reason: str


def _commands(value: Any, where: str) -> tuple[str, ...] | ScriptRefusal:
    """A `script`-shaped value as commands: strings, one level of nested lists flattened; a custom tag or anything else
    refuses."""
    if isinstance(value, Tagged):
        return ScriptRefusal(f"{where} uses {value.tag}, which this reader does not resolve")
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return ScriptRefusal(f"{where} is not a list of commands")
    found: list[str] = []
    for entry in value:
        items = entry if isinstance(entry, list) else [entry]
        for item in items:
            if isinstance(item, Tagged):
                return ScriptRefusal(f"{where} uses {item.tag}, which this reader does not resolve")
            if not isinstance(item, str):
                return ScriptRefusal(f"{where} holds an entry that is not a command string")
            found.append(item)
    return tuple(found)


def _inherited(name: str, key: str, walk: _Walk, depth: int = 0) -> Any:
    """`key` of job `name`: its own, else the nearest `extends` parent's (the last parent wins). `_ABSENT` when no
    job of the chain has it, a `ScriptRefusal` when a parent is not defined in the files read."""
    job = walk.raw.get(name)
    if job is None:
        return ScriptRefusal(f"{name} is not defined in {GITLAB_CI_RELPATH} or its local includes")
    parents = job.get("extends")
    parents = [parents] if isinstance(parents, str) else parents if isinstance(parents, list) else []
    parents = [p for p in parents if isinstance(p, str)]
    if depth >= _MAX_EXTENDS_DEPTH and parents:
        return ScriptRefusal(f"{name} extends too deep")
    for parent in parents:  # an unread parent could define the key: refuse even when the job has its own
        if parent not in walk.raw:
            return ScriptRefusal(f"{name} extends {parent}, which is not defined in the files read")
    if key in job:
        return job[key]
    for parent in reversed(parents):
        found = _inherited(parent, key, walk, depth + 1)
        if found is not _ABSENT:
            return found
    return _ABSENT


def job_script(text: str, load: Load, name: str) -> JobScript | ScriptRefusal:
    """The commands of job `name` of the CI file `text` (and its local includes through `load`): `before_script` (own,
    through `extends`, else `default:`) and `script`. Custom tags, a job or parent from an include that is not read, and
    a file that does not parse refuse (CI-002's reader, which flattens tags, is not used)."""
    walk, parsed = _read_files(text, load, GITLAB_CI_RELPATH, _StrictLoader)
    if not parsed or walk.problems:
        return ScriptRefusal("; ".join(walk.problems) or f"{GITLAB_CI_RELPATH} does not parse")
    if name not in walk.raw or name.startswith("."):
        note = f" (not read: {', '.join(walk.not_checked)})" if walk.not_checked else ""
        return ScriptRefusal(f"job {name} is not defined in {GITLAB_CI_RELPATH} or its local includes{note}")
    for message in walk.not_checked:
        if message.startswith("nested includes"):
            return ScriptRefusal(f"{GITLAB_CI_RELPATH} has {message}")
    script = _inherited(name, "script", walk)
    if isinstance(script, ScriptRefusal):
        return script
    if script is _ABSENT:
        return ScriptRefusal(f"job {name} has no script")
    before = _inherited(name, "before_script", walk)
    if isinstance(before, ScriptRefusal):
        return before
    if before is _ABSENT:
        inherit = walk.raw[name].get("inherit")
        defaults_off = isinstance(inherit, dict) and (
            inherit.get("default") is False
            or (isinstance(inherit.get("default"), list) and "before_script" not in inherit["default"])
        )
        before = [] if defaults_off or walk.default_before is _ABSENT else walk.default_before
    first = _commands(before if before is not None else [], "before_script")
    if isinstance(first, ScriptRefusal):
        return first
    second = _commands(script, "script")
    if isinstance(second, ScriptRefusal):
        return second
    return JobScript(first, second)
