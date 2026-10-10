"""Copy the wave D live-check evidence into the harness docs: ANSI stripped, e-mail shapes redacted, token shapes refused.

    python3 collect.py all         # everything under the scratch ev/ dir (zips skipped; unzipped artefacts kept)
    python3 collect.py scan DIR    # token-shape scan of a tree (exit 1 when one is found)
"""

import re
import sys
from pathlib import Path

S = Path(__file__).resolve().parents[1]  # the ev/ dir (this file lives in ev/tools/)
OUT = Path("/Users/USER/src/l4/docs/live/wave-d-live")
ANSI = re.compile(rb"\x1b\[[0-9;?]*[A-Za-z]")
EMAIL = re.compile(rb"[A-Za-z0-9._%+-]+@(?!users\.noreply\.invalid|example\.invalid|pytest\.)[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
KEEP_EMAIL = {b"maintainer@example.invalid", b"git@gitlab.example.com"}
TOKEN = re.compile(rb"glpat-[A-Za-z0-9_-]{10,}|glcbt-[A-Za-z0-9_-]{10,}|glptt-[A-Za-z0-9_-]{10,}|apikey_[A-Za-z0-9]{10,}|"
                   rb"\bsk-[A-Za-z0-9_-]{20,}|mk_agent_[A-Z0-9]{20,}|eyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}|"
                   rb"aoa[A-Za-z0-9]{40,}|sk-ant-[A-Za-z0-9_-]{10,}|mag-[A-Za-z0-9]{20,}")
RUNNER_TOKEN = re.compile(rb"token=[A-Za-z0-9_-]+")  # the runner's artefact-upload line prints a job-token prefix
SKIP_SUFFIX = (".zip",)
SKIP_NAMES = {".gitignore"}
SKIP_DIRS = {"__pycache__"}


def clean(data: bytes) -> bytes:
    data = ANSI.sub(b"", data)
    data = RUNNER_TOKEN.sub(b"token=<redacted>", data)
    return EMAIL.sub(lambda m: m.group(0) if m.group(0) in KEEP_EMAIL else b"<redacted-email>", data)


def put(src: Path, dst: Path) -> None:
    data = clean(src.read_bytes())
    if TOKEN.search(data):
        raise SystemExit(f"TOKEN SHAPE FOUND in {src}: not copied")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(data)


def scan(root: Path) -> int:
    files = [p for p in root.rglob("*") if p.is_file()]
    bad = [p for p in files if TOKEN.search(p.read_bytes())]
    for p in bad:
        print(f"TOKEN SHAPE FOUND: {p}")
    print(f"scanned {len(files)} files under {root}: {len(bad)} with a token shape")
    return 1 if bad else 0


def collect() -> int:
    for p in sorted(S.rglob("*")):
        if p.is_file() and not p.name.endswith(SKIP_SUFFIX) and p.name not in SKIP_NAMES and not SKIP_DIRS & set(p.parts):
            put(p, OUT / p.relative_to(S))
    return scan(OUT)


if __name__ == "__main__":
    if sys.argv[1] == "all":
        sys.exit(collect())
    if sys.argv[1] == "scan":
        sys.exit(scan(Path(sys.argv[2])))
    raise SystemExit(__doc__)
