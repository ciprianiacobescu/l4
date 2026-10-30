"""Small file primitives shared by the marker writer, `questions.md` and the state files."""

import contextlib
import errno
import fnmatch
import os
import secrets
import stat
import tempfile
from pathlib import Path, PurePosixPath

MAX_SOURCE_BYTES = 256 * 1024  # a spec or steering file is read up to this size (kiro-prompt-context)


class UnsafeFile(OSError):
    """A repo-controlled path that must not be read or replaced: a symlink, a non-regular file, or too large."""


class LinkedPath(UnsafeFile):
    """A component of a root-relative path is a symbolic link: nothing is read or written through it."""

    def __init__(self, link: str) -> None:
        super().__init__(f"{link} is a symbolic link")
        self.link = link  # the linked component, relative to the root (for example "src/pytdd")


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


# --- confined operations below a root (L4-SEC-020) --------------------------------------------------------------------
# Every component below `root` is opened relative to a directory descriptor with `O_NOFOLLOW`, so the check and the
# operation are one step: a link that a gate planted cannot be followed, and no process can swap one in between. `root`
# itself is opened normally (the worktree's own absolute path may hold a link, such as `/var` on macOS).

_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _parts(rel: str) -> list[str]:
    path = PurePosixPath(rel)
    if path.is_absolute() or not path.parts or ".." in path.parts or "" in rel.split("/")[:-1]:
        raise ValueError(f"{rel!r} is not a path relative to the root without '..'")
    return list(path.parts)


def _open_dir(root: Path, parts: list[str], *, create: bool) -> int | None:
    """A descriptor of `root/parts...`, every component opened without following a link; None when one is missing and
    `create` is false. A link raises `LinkedPath`, a file where a directory should be raises `UnsafeFile`."""
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for index, part in enumerate(parts):
            try:
                nxt = os.open(part, _DIR_FLAGS, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    return None
                os.mkdir(part, 0o777, dir_fd=fd)
                nxt = os.open(part, _DIR_FLAGS, dir_fd=fd)
            except OSError as exc:
                if exc.errno not in (errno.ELOOP, errno.ENOTDIR):
                    raise
                info = os.stat(part, dir_fd=fd, follow_symlinks=False)  # macOS says ENOTDIR for a linked directory
                if stat.S_ISLNK(info.st_mode):
                    raise LinkedPath("/".join(parts[: index + 1])) from None
                raise UnsafeFile(f"{'/'.join(parts[: index + 1])} is not a directory") from None
            os.close(fd)
            fd = nxt
        result, fd = fd, -1
        return result
    finally:
        if fd >= 0:
            os.close(fd)


def linked_component(root: Path, rel: str) -> str | None:
    """The first component of `rel` (the last one included) that is a symbolic link, relative to `root`; None when there
    is none. A missing component ends the walk."""
    current = root
    parts = _parts(rel)
    for index, part in enumerate(parts):
        current = current / part
        try:
            info = os.lstat(current)
        except OSError:
            return None
        if stat.S_ISLNK(info.st_mode):
            return "/".join(parts[: index + 1])
    return None


def remove_link(root: Path, link: str) -> bool:
    """Remove exactly the component `link` if it is still a symbolic link, never following it. True when removed."""
    *parents, name = _parts(link)
    try:
        fd = _open_dir(root, parents, create=False)
    except UnsafeFile:
        return False
    if fd is None:
        return False
    try:
        try:
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        except OSError:
            return False
        if not stat.S_ISLNK(info.st_mode):
            return False
        os.unlink(name, dir_fd=fd)
        return True
    finally:
        os.close(fd)


def _open_inside(root: Path, rel: str) -> int | None:
    """A read-only, non-blocking descriptor of `root/rel`, every component opened without following a link; None when
    it or a parent is absent. `LinkedPath` for a link at any component."""
    *parents, name = _parts(rel)
    fd = _open_dir(root, parents, create=False)
    if fd is None:
        return None
    try:
        try:
            return os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=fd)
        except FileNotFoundError:
            return None
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise LinkedPath(rel) from None
            raise
    finally:
        os.close(fd)


def read_inside(root: Path, rel: str, *, limit: int) -> tuple[bytes, int] | None:
    """(content, st_mode) of a regular file of at most `limit` bytes below `root`; None when it or a parent is absent.
    `LinkedPath` for a link at any component, `UnsafeFile` for a non-regular file (a FIFO never blocks) or a large
    one."""
    file_fd = _open_inside(root, rel)
    if file_fd is None:
        return None
    with os.fdopen(file_fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise UnsafeFile(f"{rel} is not a regular file")
        if info.st_size > limit:
            raise UnsafeFile(f"{rel} is larger than {limit} bytes")
        return handle.read(), info.st_mode


def read_inside_prefix(root: Path, rel: str, *, limit: int) -> tuple[bytes, int] | None:
    """(the first `limit` bytes, st_mode) of a regular file below `root`, whatever its size: the rules of `read_inside`
    except that a large file is read up to the limit instead of refused. Never reads more than `limit` bytes."""
    file_fd = _open_inside(root, rel)
    if file_fd is None:
        return None
    with os.fdopen(file_fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise UnsafeFile(f"{rel} is not a regular file")
        return handle.read(limit), info.st_mode


def write_inside(root: Path, rel: str, data: bytes, *, mode: int | None = None) -> None:
    """Write `data` as a new file in the directory of `rel` and rename it over the name: a link, a hard link or a FIFO
    in its place neither receives the bytes nor blocks. Missing parents are made as real directories."""
    *parents, name = _parts(rel)
    fd = _open_dir(root, parents, create=True)
    assert fd is not None
    tmp = f".{name}.l4tmp.{secrets.token_hex(4)}"
    try:
        try:
            if stat.S_ISDIR(os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode):
                raise UnsafeFile(f"{rel} is a directory")
        except FileNotFoundError:
            pass
        file_fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o666, dir_fd=fd)
        try:
            with os.fdopen(file_fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                if mode is not None:
                    os.fchmod(handle.fileno(), mode & 0o7777)
            os.rename(tmp, name, src_dir_fd=fd, dst_dir_fd=fd)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp, dir_fd=fd)
            raise
    finally:
        os.close(fd)


def unlink_inside(root: Path, rel: str) -> bool:
    """Remove the last component of `rel`: a file or a link, never a link's target. False when it or a parent is
    absent; `LinkedPath` for a linked parent; `UnsafeFile` for a directory at the name."""
    *parents, name = _parts(rel)
    fd = _open_dir(root, parents, create=False)
    if fd is None:
        return False
    try:
        try:
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        if stat.S_ISDIR(info.st_mode):
            raise UnsafeFile(f"{rel} is a directory")
        os.unlink(name, dir_fd=fd)
        return True
    finally:
        os.close(fd)


def unlink_matching_inside(root: Path, rel_dir: str, pattern: str) -> int:
    """Remove the regular files of `rel_dir` whose name matches the `fnmatch` `pattern`; the number removed. A link as
    the last component of `rel_dir` is removed itself, a link above it ends the call: nothing is followed."""
    parts = _parts(rel_dir)
    try:
        fd = _open_dir(root, parts, create=False)
    except LinkedPath as exc:
        if exc.link == rel_dir:
            remove_link(root, rel_dir)
        return 0
    except UnsafeFile:
        return 0
    if fd is None:
        return 0
    removed = 0
    try:
        for name in os.listdir(fd):
            if not fnmatch.fnmatchcase(name, pattern):
                continue
            try:
                if stat.S_ISREG(os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode):
                    os.unlink(name, dir_fd=fd)
                    removed += 1
            except OSError:
                continue
    finally:
        os.close(fd)
    return removed
