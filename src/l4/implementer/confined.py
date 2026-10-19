"""File operations that never follow a link (SPEC L4-IMP-065, the replay guard).

Test code run by a gate can replace a folder of the work tree by a link while the harness is restoring files. So every
operation here reaches the folder that holds the entry one component at a time from the work tree root, each time with
`O_NOFOLLOW | O_DIRECTORY`, and then acts relative to that folder's file descriptor (`dir_fd=`): there is no moment at
which a path string is resolved by the system, so a link planted before or during the operation is refused (or, if it
appears after the folder was opened, cannot redirect anything: the descriptor names the folder itself). An entry is
removed by its own type (a link, a FIFO, a socket or a device is unlinked, never opened or followed), and a file is
created `O_CREAT | O_EXCL | O_NOFOLLOW`. `os.O_NOFOLLOW`, `O_DIRECTORY` and `dir_fd` exist on Linux and macOS alike (the
two platforms the harness runs on); Windows is not supported by the harness.
"""

import errno
import os
import shutil
import stat
from pathlib import Path

Entry = tuple  # ("link", target) | ("file", bytes, mode) | ("dir",): what an entry is; None: absent
_LINKED = (errno.ELOOP, errno.EMLINK)  # O_NOFOLLOW met a link (EMLINK: FreeBSD's spelling)


class LinkedParent(Exception):
    """A folder above the entry is a link: `rel` is the path of that link (relative to the work tree)."""

    def __init__(self, rel: str) -> None:
        super().__init__(rel)
        self.rel = rel


Root = Path | int  # the work tree by name, or the descriptor of the folder the caller opened (and keeps)
MAX_READ_BYTES = 64 * 1024 * 1024  # the largest file `read_entry` reads when nothing says what to expect


class TooLarge(Exception):
    """A regular file over `MAX_READ_BYTES` that no expectation asked to be read."""

    def __init__(self, size: int) -> None:
        super().__init__(size)
        self.size = size


NO_EXPECTATION = object()


def open_parent(root: Root, rel: str, *, create: bool = False) -> tuple[int, str]:
    """(fd of the folder that holds `rel`, the entry's name). Raises `LinkedParent` when a folder on the way is a link,
    `FileNotFoundError` when one is absent (and `create` is false). With `create`, a missing folder is made and a
    non-folder (a file, a FIFO) standing where a folder belongs is removed first."""
    parts = rel.rstrip("/").split("/")
    fd = os.dup(root) if isinstance(root, int) else os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    walked: list[str] = []
    try:
        for part in parts[:-1]:
            walked.append(part)
            while True:
                try:
                    nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    break
                except FileNotFoundError:
                    if not create:
                        raise
                    os.mkdir(part, dir_fd=fd)
                except OSError as exc:
                    if exc.errno in _LINKED:
                        raise LinkedParent("/".join(walked)) from exc
                    if exc.errno == errno.ENOTDIR:
                        if stat.S_ISLNK(os.stat(part, dir_fd=fd, follow_symlinks=False).st_mode):
                            raise LinkedParent("/".join(walked)) from exc
                        if not create:
                            raise FileNotFoundError(errno.ENOENT, "not a folder", part) from exc
                        os.unlink(part, dir_fd=fd)  # a stray file where a folder belongs
                        continue
                    raise
            os.close(fd)
            fd = nxt
        return fd, parts[-1]
    except BaseException:
        os.close(fd)
        raise


def _lstat(fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def exists_entry(root: Root, rel: str) -> bool:
    """Whether anything stands at `rel` (decided by `lstat`, nothing is read). `LinkedParent` as `open_parent`."""
    try:
        fd, name = open_parent(root, rel)
    except FileNotFoundError:
        return False
    try:
        return _lstat(fd, name) is not None
    finally:
        os.close(fd)


def read_entry(root: Root, rel: str, *, expect: object = NO_EXPECTATION) -> Entry | None:
    """What `rel` is, without following anything: a link and its target, a regular file with its bytes and mode, a
    folder; None for an absent entry or one that is none of these (a FIFO, a socket, a device are never opened).
    `LinkedParent` when a folder above it is a link. With `expect` (what the caller compares with; None means "absent"),
    a regular file is read only when `expect` is a file of the same size, and then at most one byte past it; in every
    other case its bytes come back as None, which equals nothing, and nothing is read. Without `expect` (the snapshot)
    a file over `MAX_READ_BYTES` raises `TooLarge`."""
    try:
        fd, name = open_parent(root, rel)
    except FileNotFoundError:
        return None
    try:
        st = _lstat(fd, name)
        if st is None:
            return None
        if stat.S_ISLNK(st.st_mode):
            return ("link", os.readlink(name, dir_fd=fd))
        if stat.S_ISDIR(st.st_mode):
            return ("dir",)
        if not stat.S_ISREG(st.st_mode):
            return None
        mode = stat.S_IMODE(st.st_mode)
        if expect is NO_EXPECTATION:
            if st.st_size > MAX_READ_BYTES:
                raise TooLarge(st.st_size)
            want = None
        else:
            want = expect[1] if isinstance(expect, tuple) and expect[0] == "file" else None
            if want is None or st.st_size != len(want):
                return ("file", None, mode)  # decided from lstat: nothing to compare the bytes with
        out = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(out, "rb") as handle:
            return ("file", handle.read() if want is None else handle.read(len(want) + 1), mode)
    finally:
        os.close(fd)


def remove_entry(root: Root, rel: str) -> None:
    """Remove `rel` whatever it is (a folder with all it holds, by a walk that follows no link); nothing if absent."""
    try:
        fd, name = open_parent(root, rel)
    except FileNotFoundError:
        return
    try:
        _remove(fd, name)
    finally:
        os.close(fd)


def _remove(fd: int, name: str) -> None:
    st = _lstat(fd, name)
    if st is None:
        return
    if stat.S_ISDIR(st.st_mode):
        shutil.rmtree(name, dir_fd=fd)
    else:
        os.unlink(name, dir_fd=fd)  # a file, a link, a FIFO, a socket: the entry, never what it points to


def put_entry(root: Root, rel: str, expected: Entry | None) -> None:
    """Make `rel` hold `expected` (None: nothing) by removing what is there and creating the entry anew."""
    try:
        fd, name = open_parent(root, rel, create=expected is not None)
    except FileNotFoundError:
        return  # a folder is absent and there is nothing to create
    try:
        _remove(fd, name)
        if expected is None or expected[0] == "dir":
            return
        if expected[0] == "link":
            os.symlink(expected[1], name, dir_fd=fd)
            return
        out = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        with os.fdopen(out, "wb") as handle:
            handle.write(expected[1])
            os.fchmod(handle.fileno(), expected[2])
    finally:
        os.close(fd)


def remove_link(root: Root, rel: str) -> None:
    """Remove `rel` only if it is a link (the link itself, never what it points to); nothing otherwise."""
    try:
        fd, name = open_parent(root, rel)
    except (FileNotFoundError, LinkedParent):
        return
    try:
        st = _lstat(fd, name)
        if st is not None and stat.S_ISLNK(st.st_mode):
            os.unlink(name, dir_fd=fd)
    finally:
        os.close(fd)


def check_parents(root: Root, rel: str) -> None:
    """Raise `LinkedParent` if a folder above `rel` is a link; return quietly when they are folders or absent."""
    try:
        fd, _ = open_parent(root, rel)
    except FileNotFoundError:
        return
    os.close(fd)


def repair_dir_modes(root: Root, rel: str) -> None:
    """Best effort after a `PermissionError`: give the folders above `rel` that a gate made unreadable their owner's
    access back, so the step can be discarded. A link is never followed: the chmod is `fchmodat` without following
    where the platform has it, and everywhere the folder is looked at again afterwards (still a folder, same inode)."""
    fd = os.dup(root) if isinstance(root, int) else os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in rel.rstrip("/").split("/")[:-1]:
            try:
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except PermissionError:
                before = _lstat(fd, part)
                if before is None or not stat.S_ISDIR(before.st_mode):
                    return
                mode = stat.S_IMODE(before.st_mode) | 0o700
                if os.chmod in os.supports_follow_symlinks:
                    os.chmod(part, mode, dir_fd=fd, follow_symlinks=False)
                else:
                    os.chmod(part, mode, dir_fd=fd)
                after = _lstat(fd, part)
                if after is None or not stat.S_ISDIR(after.st_mode) or after.st_ino != before.st_ino:
                    return  # swapped meanwhile: go no further
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
    except OSError:
        return
    finally:
        os.close(fd)
