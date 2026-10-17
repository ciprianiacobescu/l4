"""Small file primitives shared by the marker writer, `questions.md` and the state files."""

import contextlib
import os
import stat
import tempfile
from pathlib import Path

MAX_SOURCE_BYTES = 256 * 1024  # a spec or steering file is read up to this size (kiro-prompt-context)


class UnsafeFile(OSError):
    """A repo-controlled path that must not be read or replaced: a symlink, a non-regular file, or too large."""


def reject_symlinks(base: Path, *parts: str) -> None:
    """Refuse when any component of `base/parts...` below `base` is a symlink. `O_NOFOLLOW` and `lstat` only guard the
    last component, so `openspec -> /elsewhere` or `<unit>/.l4 -> ../outside` would otherwise redirect reads and
    writes out of the checkout. A component that does not exist yet is fine."""
    current = base
    for part in parts:
        current = current / part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            return
        if stat.S_ISLNK(info.st_mode):
            raise UnsafeFile(f"{current} is a symlink")


def read_regular_file(path: Path, *, limit: int) -> bytes:
    """Read a regular file of at most `limit` bytes; never follows a symlink (paths from repo content are untrusted)."""
    info = os.lstat(path)  # FileNotFoundError propagates: absence is not unsafe
    if stat.S_ISLNK(info.st_mode):
        raise UnsafeFile(f"{path} is a symlink")
    if not stat.S_ISREG(info.st_mode):
        raise UnsafeFile(f"{path} is not a regular file")
    if info.st_size > limit:
        raise UnsafeFile(f"{path} is larger than {limit} bytes")
    return path.read_bytes()


def read_regular_prefix(path: Path, limit: int) -> tuple[bytes, int]:
    """The first `limit` bytes of a regular file and its size; never follows a symlink. The rules of
    `read_regular_file`, except that a file over the limit is read up to it instead of refused."""
    info = os.lstat(path)  # FileNotFoundError propagates: absence is not unsafe
    if stat.S_ISLNK(info.st_mode):
        raise UnsafeFile(f"{path} is a symlink")
    if not stat.S_ISREG(info.st_mode):
        raise UnsafeFile(f"{path} is not a regular file")
    with path.open("rb") as handle:
        return handle.read(limit), info.st_size


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Temp file next to `path`, fsync, rename over it, fsync the directory. An existing file keeps its mode."""
    mode = stat.S_IMODE(os.lstat(path).st_mode) if path.exists() else None
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".l4tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        with contextlib.suppress(OSError):
            os.close(dir_fd)


SEAL_CONTENT = "*\n"


def seal_out_dir(path: Path) -> None:
    """`.l4-out/` ignores itself (M1.8 A8): whoever creates it writes `.gitignore` with `*` first, so a repository whose
    own `.gitignore` does not name `.l4-out/` yet (`l4 init` has not run, or never will) is not left with untracked
    reports. A `.gitignore` that is already there is not touched; a symlink is never followed; best effort, an
    `OSError` is ignored (the directory is an output, not a precondition)."""
    try:
        if path.is_symlink():
            return
        path.mkdir(parents=True, exist_ok=True)
        marker = path / ".gitignore"
        if not marker.exists():
            atomic_write_bytes(marker, SEAL_CONTENT.encode())
    except OSError:
        return
