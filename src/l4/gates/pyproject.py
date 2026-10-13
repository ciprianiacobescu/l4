"""What `pyproject.toml` says about a uv/pytest/ruff project: extras, dependency groups and the dev tools (M1.8 A2).

Read by `l4 init` (which gates to propose) and by the doctor's suggestions (which extra provides a missing module).
Names are PEP 503 normalised (`-`, `_` and `.` are one, case-folded). Only the declared names are read; nothing is
resolved or installed.
"""

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from l4.fsutil import UnsafeFile, read_regular_file

_NAME = re.compile(r"^\s*([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)")
# import names that are not their distribution's name
ALIASES = {
    "yaml": "pyyaml", "pil": "pillow", "cv2": "opencv_python", "sklearn": "scikit_learn", "bs4": "beautifulsoup4",
    "dateutil": "python_dateutil", "attr": "attrs", "git": "gitpython", "dotenv": "python_dotenv",
    "serial": "pyserial", "jwt": "pyjwt", "magic": "python_magic", "google": "protobuf",
}  # fmt: skip


def normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "_", name).lower()


def requirement_name(requirement: str) -> str | None:
    found = _NAME.match(requirement)
    return normalise(found.group(1)) if found else None


def distribution_for(module: str) -> str:
    """The distribution that provides the top-level import name `module`, as far as names tell."""
    top = module.split(".")[0]
    return ALIASES.get(top.lower(), normalise(top))


@dataclass(frozen=True)
class PyProject:
    present: bool = False
    name: str = ""
    dependencies: tuple[str, ...] = ()
    extras: dict[str, tuple[str, ...]] = field(default_factory=dict)  # extra -> normalised distribution names
    groups: dict[str, tuple[str, ...]] = field(default_factory=dict)  # PEP 735 groups and uv's dev-dependencies
    has_lock: bool = False
    has_ruff_config: bool = False

    def everywhere(self) -> set[str]:
        names = set(self.dependencies)
        for table in (self.extras, self.groups):
            for values in table.values():
                names.update(values)
        return names

    def extras_providing(self, distribution: str) -> list[str]:
        return sorted(e for e, names in self.extras.items() if distribution in names)

    def groups_providing(self, distribution: str) -> list[str]:
        return sorted(g for g, names in self.groups.items() if distribution in names)


def _names(items: object) -> tuple[str, ...]:
    if not isinstance(items, list):
        return ()
    return tuple(n for item in items if isinstance(item, str) and (n := requirement_name(item)))


def read_pyproject(repo: Path) -> PyProject:
    path = repo / "pyproject.toml"
    try:
        data = tomllib.loads(read_regular_file(path, limit=1024 * 1024).decode("utf-8"))
    except FileNotFoundError:
        return PyProject(has_lock=(repo / "uv.lock").is_file())
    except (OSError, UnsafeFile, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return PyProject(present=False, has_lock=(repo / "uv.lock").is_file())
    project = data.get("project") if isinstance(data.get("project"), dict) else {}
    optional = project.get("optional-dependencies") if isinstance(project.get("optional-dependencies"), dict) else {}
    groups_raw = data.get("dependency-groups") if isinstance(data.get("dependency-groups"), dict) else {}
    groups = {name: _names([i for i in items if isinstance(i, str)]) for name, items in groups_raw.items()
              if isinstance(items, list)}  # fmt: skip
    tool = data.get("tool") if isinstance(data.get("tool"), dict) else {}
    uv = tool.get("uv") if isinstance(tool.get("uv"), dict) else {}
    if "dev" not in groups and isinstance(uv.get("dev-dependencies"), list):
        groups["dev"] = _names(uv["dev-dependencies"])  # the older uv form: still the `dev` group
    return PyProject(
        True, str(project.get("name") or ""), _names(project.get("dependencies")),
        {name: _names(items) for name, items in optional.items()}, groups, (repo / "uv.lock").is_file(),
        isinstance(tool.get("ruff"), dict) or (repo / "ruff.toml").is_file() or (repo / ".ruff.toml").is_file(),
    )  # fmt: skip


MAX_PROJECT_DIRS = 4
CONVENTIONAL_DIRS = ("src", "tests", "test")


def _table(data: object, *keys: str) -> object:
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def _path_values(value: object) -> list[str]:
    if isinstance(value, str):
        return value.split()
    if isinstance(value, dict):
        return [v for v in value.values() if isinstance(v, str)]
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _inside(repo: Path, relative: str) -> str | None:
    """`relative` as a clean repository-relative directory name that exists inside `repo`; None otherwise."""
    cleaned = relative.strip().removeprefix("./").rstrip("/")
    parts = Path(cleaned).parts
    if not cleaned or cleaned.startswith("/") or ".." in parts or cleaned in (".", "~"):
        return None
    target = repo / cleaned
    try:
        inside = target.is_dir() and target.resolve().is_relative_to(repo.resolve())
    except OSError:
        return None
    return Path(*parts).as_posix() if inside else None


def project_dirs(repo: Path, pyproject: PyProject) -> tuple[str, ...]:
    """The source and test directories of the project that exist in `repo`, at most four, in this order (M1.10
    decision 15): `tool.ruff.src`, `tool.pytest.ini_options.testpaths`, hatch `packages`, setuptools
    `packages.find.where` and `package-dir`; then `src`, a top-level package named after the project, `tests` and
    `test`. What names a directory outside the repository, or one that does not exist, is left out, and so is a
    directory that lies inside another of the list."""
    try:
        data = tomllib.loads(read_regular_file(repo / "pyproject.toml", limit=1024 * 1024).decode("utf-8"))
    except (OSError, UnsafeFile, UnicodeDecodeError, tomllib.TOMLDecodeError):
        data = {}
    declared = [
        *_path_values(_table(data, "tool", "ruff", "src")),
        *_path_values(_table(data, "tool", "pytest", "ini_options", "testpaths")),
        *_path_values(_table(data, "tool", "hatch", "build", "targets", "wheel", "packages")),
        *_path_values(_table(data, "tool", "hatch", "build", "packages")),
        *_path_values(_table(data, "tool", "setuptools", "packages", "find", "where")),
        *_path_values(_table(data, "tool", "setuptools", "package-dir")),
    ]
    named = [pyproject.name.replace("-", "_").replace(".", "_")] if pyproject.name else []
    found: list[str] = []
    for candidate in (*declared, "src", *named, *CONVENTIONAL_DIRS[1:]):
        if (clean := _inside(repo, candidate)) is not None and clean not in found:
            found.append(clean)
    found = [d for d in found if not any(d != o and d.startswith(o + "/") for o in found)]  # `src` holds `src/pkg`
    return tuple(found[:MAX_PROJECT_DIRS])
