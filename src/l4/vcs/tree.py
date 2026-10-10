"""Reading files out of a commit without a checkout (raw bytes: text-mode git would change line endings)."""

from typing import NamedTuple

from l4.vcs.git import Git


class Blob(NamedTuple):
    path: str
    oid: str


def regular_blobs(git: Git, ref: str, path: str, limit: int) -> list[Blob]:
    """Regular files at `path` (or directly under it, when it ends in `/`) no larger than `limit`. A symlink, a
    tree, a submodule or an oversized blob is not something this harness wrote, so it is left out unread."""
    listing = git.run_bytes("ls-tree", "-z", "-l", ref, "--", path, check=False)
    blobs = []
    for record in filter(None, listing.split(b"\0")):
        meta, _, name = record.partition(b"\t")
        fields = meta.split()
        if len(fields) != 4 or fields[0] not in (b"100644", b"100755") or fields[1] != b"blob":
            continue
        if int(fields[3]) <= limit:
            blobs.append(Blob(name.decode("utf-8", "surrogateescape"), fields[2].decode("ascii")))
    return blobs
