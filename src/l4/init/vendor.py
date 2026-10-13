"""The harness source `l4 init --vendor` copies into `.l4/vendor/` (forge-and-ci 2.28 and 1.20, reduced).

The pin is the commit the harness checkout is at (`git rev-parse HEAD`); what is copied is that commit's tree, read
through `git archive`, never the working tree, so `harness.commit` in the config names exactly what was copied. A
checkout whose tracked files differ from HEAD is refused for the same reason. Only what `uv run --project` needs is
taken: `src/`, `pyproject.toml`, `uv.lock` and the README and LICENSE files that exist (`pyproject.toml` names the
README, and the build refuses a missing one), never tests, docs, openspec or scripts.
M1: forge-and-ci 2.28 the `v<version>` tag lookup and the temp clone of `L4_HARNESS_URL`.
"""

import io
import tarfile
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import l4
from l4.exitcodes import ExitCode, L4Exit
from l4.vcs.errors import GitError
from l4.vcs.git import Git

REQUIRED = ("src", "pyproject.toml", "uv.lock")
OPTIONAL = ("README.md", "README", "README.rst", "README.txt", "LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING")
COMMIT_FILE = "src/l4/_commit.py"
DISTRIBUTION = "l4harness"
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 50 * 1024 * 1024
PACKAGE_FILE = Path(l4.__file__)  # the running package; tests point it elsewhere


@dataclass(frozen=True)
class VendorFile:
    data: bytes
    executable: bool


@dataclass(frozen=True)
class VendorSource:
    commit: str
    files: Mapping[str, VendorFile]  # path below `.l4/vendor/`


def _refuse(message: str) -> L4Exit:
    return L4Exit(ExitCode.USAGE_ERROR, f"init --vendor: {message}")


def harness_root(harness: Path | None) -> Path:
    """`--harness PATH`, else the checkout the running package was imported from (`<repo>/src/l4/__init__.py`)."""
    if harness is not None:
        return harness.resolve()
    guess = PACKAGE_FILE.resolve().parents[2]
    if (guess / ".git").exists() and (guess / "src" / "l4").is_dir():
        return guess
    raise _refuse("the running l4 is not a git checkout of the harness; pass --harness PATH")


def collect_vendor_source(root: Path, environ: Mapping[str, str]) -> VendorSource:
    git = Git(root, environ=environ)
    try:
        top = git.run("rev-parse", "--show-toplevel").stdout.strip()
        commit = git.run("rev-parse", "--verify", "HEAD^{commit}").stdout.strip()
        present = set(git.run("ls-tree", "--name-only", "HEAD").stdout.splitlines())
    except GitError:
        raise _refuse(f"{root} is not a git repository with a commit") from None
    if Path(top).resolve() != root:
        raise _refuse(f"{root} is not the top of a git repository")
    missing = [name for name in REQUIRED if name not in present]
    if missing:
        raise _refuse(f"the harness checkout has no {', '.join(missing)} at HEAD")
    paths = [*REQUIRED, *(name for name in OPTIONAL if name in present)]
    _check_project_name(git)
    if git.run("diff", "--quiet", "HEAD", "--", *paths, check=False).returncode != 0:
        raise _refuse("tracked harness files differ from HEAD; commit them first, the pin must name what is copied")
    files = _read_tree(git.run_bytes("archive", "--format=tar", "HEAD", "--", *paths))
    files[COMMIT_FILE] = VendorFile(f'COMMIT = "{commit}"\n'.encode(), False)  # read back by `l4.buildinfo`
    return VendorSource(commit, files)


def _check_project_name(git: Git) -> None:
    try:
        name = tomllib.loads(git.run("show", "HEAD:pyproject.toml").stdout)["project"]["name"]
    except (GitError, tomllib.TOMLDecodeError, KeyError):
        name = None
    if name != DISTRIBUTION:
        raise _refuse(f"pyproject.toml at HEAD does not name the distribution {DISTRIBUTION}")


def _read_tree(archive: bytes) -> dict[str, VendorFile]:
    files: dict[str, VendorFile] = {}
    total = 0
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
        for member in tar:
            if member.isdir():
                continue
            pure = PurePosixPath(member.name)
            if not member.isreg() or pure.is_absolute() or ".." in pure.parts:
                raise _refuse(f"{member.name} is not a regular file inside the harness tree")
            if member.size > MAX_FILE_BYTES:
                raise _refuse(f"{member.name} is larger than {MAX_FILE_BYTES} bytes")
            total += member.size
            if total > MAX_TOTAL_BYTES:
                raise _refuse(f"the harness tree is larger than {MAX_TOTAL_BYTES} bytes")
            handle = tar.extractfile(member)
            assert handle is not None
            files[member.name] = VendorFile(handle.read(), bool(member.mode & 0o111))
    return files
