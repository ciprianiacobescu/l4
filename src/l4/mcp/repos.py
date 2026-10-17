"""The repositories an `l4 mcp serve` instance serves (L4-MCP-005, design D5).

A tool never runs anywhere else: the `repo` argument of a call is matched against this fixed list, by folder name or by
path (compared after resolving symlinks), and anything that matches nothing is refused, never resolved."""

import subprocess
from dataclasses import dataclass
from pathlib import Path


class RepoError(Exception):
    """A `--repo` path that is not a git repository with `.l4/config.yaml` (the server exits 2 before it serves)."""


class Refused(Exception):
    """A call named a repository the instance does not serve (or none, where it must): nothing runs."""


class NoRepository(Refused):
    """No `--repo`, and the working directory is not an L4 repository."""


def resolve_root(path: Path) -> Path:
    """The root of the git repository that holds `path`, when it has `.l4/config.yaml`; else `RepoError`."""
    try:
        folder = Path(path).expanduser().resolve(strict=True)
    except OSError:
        raise RepoError(f"{path}: does not exist") from None
    if not folder.is_dir():
        raise RepoError(f"{path}: not a folder")
    done = subprocess.run(
        ["git", "-C", str(folder), "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False
    )
    if done.returncode != 0 or not done.stdout.strip():
        raise RepoError(f"{path}: not a git repository")
    root = Path(done.stdout.strip()).resolve()
    if not (root / ".l4" / "config.yaml").is_file():
        raise RepoError(f"{root}: has no .l4/config.yaml (an L4 repository is one that ran `l4 init`)")
    return root


@dataclass(frozen=True)
class Repos:
    roots: tuple[Path, ...]  # resolved repository roots given with --repo (empty: the working directory decides)
    cwd: Path
    project_dir: str | None = None  # CLAUDE_PROJECT_DIR: with no --repo it is looked at before the working directory

    @classmethod
    def from_paths(cls, paths: list[Path], *, cwd: Path, project_dir: str | None = None) -> "Repos":
        roots: dict[Path, None] = {}
        for path in paths:
            roots[resolve_root(path)] = None
        names: dict[str, Path] = {}
        for root in roots:
            if root.name in names:
                raise RepoError(
                    f"{names[root.name]} and {root}: the same folder name {root.name!r}; a call could not name one"
                )
            names[root.name] = root
        return cls(tuple(roots), cwd, project_dir or None)

    def _served(self) -> tuple[Path, ...]:
        if self.roots:
            return self.roots
        if self.project_dir:
            try:
                return (resolve_root(Path(self.project_dir)),)
            except RepoError:
                pass  # a stale variable: the working directory still decides
        try:
            return (resolve_root(self.cwd),)
        except RepoError as exc:
            raise NoRepository(
                f"this server was not started for a repository ({exc}); start it in one, or with --repo PATH "
                "(`l4 mcp install --repo PATH` writes that)"
            ) from None

    def served(self) -> tuple[Path, ...]:
        """The repositories served; `NoRepository` when none was named and the working directory is not one."""
        return self._served()

    @property
    def needs_repo_argument(self) -> bool:
        return len(self.roots) > 1

    def listing(self) -> str:
        return ", ".join(str(r) for r in self.roots) if self.roots else "(the working directory)"

    def select(self, argument: object) -> Path:
        served = self._served()
        listed = "; ".join(f"{r.name} = {r}" for r in served)
        if argument is None:
            if len(served) > 1:
                raise Refused(f"the argument repo is required; this server serves: {listed}")
            return served[0]
        if not isinstance(argument, str) or not argument:
            raise Refused(f"repo must name a served repository; this server serves: {listed}")
        by_name = [r for r in served if r.name == argument]
        if len(by_name) == 1:
            return by_name[0]
        try:
            resolved = Path(argument).expanduser().resolve()
        except (OSError, RuntimeError):
            resolved = None
        if resolved is not None and resolved in served:
            return resolved
        raise Refused(f"{argument!r} is not a repository this server serves; it serves: {listed}")
