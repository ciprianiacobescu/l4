"""Copy kiro-e2e H3 evidence into the harness docs: ANSI stripped, e-mail shapes redacted, token shapes refused.

    python3 h3collect.py all         # everything under the scratch h3/ dir, plus the job artefacts
    python3 h3collect.py scan DIR    # token-shape scan of a tree (exit 1 when one is found)
"""

import re
import sys
from pathlib import Path

S = Path("/tmp/scratch/kiro-fu")
DOCS = Path("/Users/USER/src/l4/docs/live")
OUT = DOCS / "kiro-e2e" / "h3"
ANSI = re.compile(rb"\x1b\[[0-9;?]*[A-Za-z]")
EMAIL = re.compile(rb"[A-Za-z0-9._%+-]+@(?!users\.noreply\.invalid|example\.invalid|pytest\.)[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
KEEP_EMAIL = {b"maintainer@example.invalid", b"git@gitlab.example.com"}
TOKEN = re.compile(rb"glpat-[A-Za-z0-9_-]{10,}|glcbt-[A-Za-z0-9_-]{10,}|apikey_[A-Za-z0-9]{10,}|\bsk-[A-Za-z0-9_-]{20,}|"
                   rb"mk_agent_[A-Z0-9]{20,}|eyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}|aoa[A-Za-z0-9]{40,}|"
                   rb"sk-ant-[A-Za-z0-9_-]{10,}")
RUNNER_TOKEN = re.compile(rb"token=[A-Za-z0-9_-]+")  # the runner's artefact-upload line prints a job-token prefix
SKIP_SUFFIX = (".zip",)
SKIP_NAMES = {".gitignore"}  # .l4-out/.gitignore is `*`: copied, it would hide the evidence from git
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


def tree(src: Path, dst: Path) -> None:
    for p in sorted(src.rglob("*")):
        if p.is_file() and not p.name.endswith(SKIP_SUFFIX) and p.name not in SKIP_NAMES and not SKIP_DIRS & set(p.parts):
            if any(part.startswith("a") and part[1:].isdigit() for part in p.relative_to(src).parts[:-1]):
                continue  # unzipped job artefacts (ci/a<job>/) go to docs/live/artifacts, not here
            put(p, dst / p.relative_to(src))


def scan(root: Path) -> int:
    bad = [p for p in root.rglob("*") if p.is_file() and TOKEN.search(p.read_bytes())]
    for p in bad:
        print(f"TOKEN SHAPE FOUND: {p}")
    print(f"scanned {sum(1 for p in root.rglob('*') if p.is_file())} files under {root}: {len(bad)} with a token shape")
    return 1 if bad else 0


def collect() -> int:
    tree(S / "h3", OUT)
    code = scan(OUT)
    for job in sorted((S / "h3" / "ci").glob("a*")):
        if job.is_dir() and job.name[1:].isdigit():
            dst = DOCS / "artifacts" / f"job-{job.name[1:]}" / "l4-out"
            tree(job / ".l4-out", dst)
            code |= scan(dst)
    return code


if __name__ == "__main__":
    if sys.argv[1] == "all":
        sys.exit(collect())
    if sys.argv[1] == "scan":
        sys.exit(scan(Path(sys.argv[2])))
    raise SystemExit(__doc__)
