"""Doubles for the installers: a fetcher that serves canned bytes and a runner that behaves like the installers."""

import hashlib
import io
import tarfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from l4.config.defaults import openspec_entrypoint
from l4.doctor.context import CmdResult
from l4.provision.runner import OfflineError, Paths

NODE_V = "22.23.0"
NODE_NAME = f"node-v{NODE_V}-linux-x64"


def node_tarball(top: str = NODE_NAME) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:xz") as tar:
        for name, body in {f"{top}/bin/node": b"#!/bin/sh\n", f"{top}/bin/npm": b"#!/bin/sh\n"}.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(body), 0o755
            tar.addfile(info, io.BytesIO(body))
        link = tarfile.TarInfo(f"{top}/bin/npx")
        link.type, link.linkname = tarfile.SYMTYPE, "npm"
        tar.addfile(link)
    return buffer.getvalue()


def shasums(tarball: bytes, name: str = f"{NODE_NAME}.tar.xz") -> str:
    return f"{hashlib.sha256(tarball).hexdigest()}  {name}\n"


class FakeFetcher:
    """`download(url, dest)` writes `files[url]`; a URL that is not served raises `OfflineError`."""

    def __init__(self, files: Mapping[str, bytes] | None = None, *, offline: bool = False) -> None:
        self.files = dict(files or {})
        self.offline = offline
        self.calls: list[str] = []

    def download(self, url: str, dest: Path) -> Path:
        self.calls.append(url)
        host = url.split("/")[2]
        if self.offline or url not in self.files:
            raise OfflineError(host, "ConnectError")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.files[url])
        return dest

    def reachable(self, host: str) -> bool:
        return not self.offline


class InstallRunner:
    """Answers `<tool> --version` from `versions`, and plays the installers: a saved script whose second line is
    `# installs <tool>` creates that tool's binary; `npm install` creates the package's entry point or `.bin` file."""

    def __init__(self, paths: Paths, env: Mapping[str, str], versions: Mapping[str, str]) -> None:
        self.paths, self.env = paths, env
        self.versions = dict(versions)
        self.calls: list[tuple[str, ...]] = []
        self.envs: list[Mapping[str, str]] = []
        self.cwds: list[Path] = []

    def _make(self, directory: Path, name: str) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / name).write_text("#!/bin/sh\n")
        (directory / name).chmod(0o755)

    def __call__(self, argv: Sequence[str], cwd: Path, env: Mapping[str, str], timeout: float) -> CmdResult:
        self.calls.append(tuple(argv))
        self.envs.append(dict(env))
        self.cwds.append(cwd)
        name = Path(argv[0]).name
        if len(argv) > 1 and argv[1] == "install":  # npm install --prefix P ... <package>@<version>
            package = argv[-1].rpartition("@")[0]
            if package == "@fission-ai/openspec":
                entry = openspec_entrypoint(self.env)
                entry.parent.mkdir(parents=True, exist_ok=True)
                entry.write_text("// fake")
            else:
                self._make(self.paths.npm_prefix / "node_modules" / ".bin", package.rpartition("/")[2].split("-")[0])
            return CmdResult(0, "", "")
        if name in ("sh", "bash"):
            script = Path(argv[1]).read_text().splitlines()
            tool = script[1].removeprefix("# installs ")
            self._make(self.paths.local_bin, tool)
            return CmdResult(0, "", "")
        key = "openspec" if any(a.endswith("openspec.js") for a in argv) else name
        out = self.versions.get(argv[0], self.versions.get(key))  # a path entry wins over the tool's name
        return CmdResult(0, out + "\n", "") if out is not None else CmdResult(127, "", "")


def installer(tool: str) -> bytes:
    return f"#!/bin/sh\n# installs {tool}\n".encode()
