"""Read and validate `.l4/config.yaml`. Messages carry paths and key names, never values."""

import difflib
import re
import types
import typing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_args, get_origin

import yaml
from pydantic import BaseModel, ValidationError

from l4.config.schema import L4Config, ValueFree
from l4.exitcodes import ExitCode, L4Exit
from l4.redact import Redactor

CONFIG_RELPATH = Path(".l4") / "config.yaml"
_SHAPES_ONLY = Redactor({})


class _Yaml12Loader(yaml.SafeLoader):
    """SafeLoader with YAML 1.2 booleans: only true/false, so the legal value `off` stays a string."""


_Yaml12Loader.yaml_implicit_resolvers = {
    first: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:bool"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_BOOL_12 = re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$")
_Yaml12Loader.add_implicit_resolver("tag:yaml.org,2002:bool", _BOOL_12, list("tTfF"))


@dataclass(frozen=True)
class ConfigIssue:
    path: str
    message: str
    suggestion: str | None = None

    def __str__(self) -> str:
        hint = f" (did you mean '{self.suggestion}'?)" if self.suggestion else ""
        return f"{self.message} at {self.path}{hint}"


class ConfigSchemaError(L4Exit):
    """Invalid configuration: exit 2 in every command."""

    def __init__(self, issues: list[ConfigIssue]) -> None:
        super().__init__(ExitCode.USAGE_ERROR, "\n".join(str(i) for i in issues))
        self.issues = issues


def load_config(repo: Path, *, config_path: Path | None = None) -> L4Config:
    """Defaults when the default file is absent; an explicit `config_path` must exist. Raises ConfigSchemaError."""
    path = config_path if config_path is not None else repo / CONFIG_RELPATH
    if not path.is_file():
        if config_path is not None:
            raise ConfigSchemaError([ConfigIssue("$", f"config file not found: {config_path}")])
        return L4Config()
    raw = _parse_yaml(path)
    try:
        return L4Config.model_validate(raw)
    except ValidationError as exc:
        raise ConfigSchemaError(_issues(exc)) from None


def _parse_yaml(path: Path) -> dict[str, Any]:
    try:
        loaded = yaml.load(path.read_text(encoding="utf-8"), Loader=_Yaml12Loader)  # noqa: S506 (SafeLoader subclass)
    except yaml.YAMLError as exc:
        # PyYAML's own message quotes the offending source line, which could be a secret: position only.
        mark = getattr(exc, "problem_mark", None)
        where = f"line {mark.line + 1}, column {mark.column + 1}" if mark else "unknown position"
        raise ConfigSchemaError([ConfigIssue("$", f"invalid YAML ({where})")]) from None
    except UnicodeDecodeError:
        raise ConfigSchemaError([ConfigIssue("$", "config file is not valid UTF-8")]) from None
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigSchemaError([ConfigIssue("$", "the top level must be a mapping")])
    return loaded


def _issues(exc: ValidationError) -> list[ConfigIssue]:
    issues: list[ConfigIssue] = []
    for err in exc.errors(include_input=False, include_url=False):
        loc = err["loc"]
        if err["type"] == "extra_forbidden":
            key = str(loc[-1])
            container = _render_path(loc[:-1])
            allowed = _allowed_keys(loc[:-1])
            match = difflib.get_close_matches(key, allowed, n=1, cutoff=0.7)
            safe_key = _SHAPES_ONLY.redact_text(key)
            issues.append(ConfigIssue(container, f"unknown key '{safe_key}'", match[0] if match else None))
        elif err["type"] in ("value_error", "assertion_error"):
            # custom validators may echo their input: only the ones that promise not to are shown
            cause = err.get("ctx", {}).get("error")
            message = str(cause) if isinstance(cause, ValueFree) else "invalid value"
            issues.append(ConfigIssue(_render_path(loc), message))
        else:
            issues.append(ConfigIssue(_render_path(loc), err["msg"]))
    return issues


def _walk(loc: tuple[int | str, ...]) -> tuple[str, Any]:
    """Follow `loc` through the model tree: the rendered path (`$.profiles.judge-sol`, `$.spec.frameworks[1]`)
    and the annotation reached. Pydantic's union-branch tags are dropped from the path."""
    path, ann = "$", typing.cast(Any, L4Config)
    for seg in loc:
        ann = _strip(ann)
        origin = get_origin(ann)
        if isinstance(ann, type) and issubclass(ann, BaseModel):
            path += f".{seg}"
            field = ann.model_fields.get(str(seg))
            ann = field.annotation if field else None
        elif origin is dict:
            path += f".{seg}"
            ann = get_args(ann)[1]
        elif origin is list:
            path += f"[{seg}]"
            ann = get_args(ann)[0]
        elif _is_union(ann):
            ann = _structured_member(ann)  # `seg` is the failing branch's type label
        else:
            path += f"[{seg}]" if isinstance(seg, int) else f".{seg}"
            ann = None
    return path, ann


def _render_path(loc: tuple[int | str, ...]) -> str:
    return _walk(loc)[0]


def _allowed_keys(loc: tuple[int | str, ...]) -> list[str]:
    ann = _strip(_walk(loc)[1])
    return list(ann.model_fields) if isinstance(ann, type) and issubclass(ann, BaseModel) else []


def _is_union(ann: Any) -> bool:
    return get_origin(ann) in (typing.Union, types.UnionType)


def _strip(ann: Any) -> Any:
    """Unwrap Annotated and Optional."""
    while True:
        if get_origin(ann) is typing.Annotated:
            ann = get_args(ann)[0]
            continue
        if _is_union(ann):
            members = [a for a in get_args(ann) if a is not type(None)]
            if len(members) == 1:
                ann = members[0]
                continue
        return ann


def _structured_member(union: Any) -> Any:
    for member in get_args(union):
        if get_origin(member) in (list, dict) or (isinstance(member, type) and issubclass(member, BaseModel)):
            return member
    return None
