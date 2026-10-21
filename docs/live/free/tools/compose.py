"""compose.py GOT DOCS_FREE DOCS_ARTIFACTS LABEL...: copy fetched runs into the harness docs (ANSI stripped).

docs/live/free/runs/<label>/: meta, run.log, status, cfg, CI overlap, rate-limit lines, branch commits, src/tests diff
and the unit folder at the branch head (verification.md, ledger, questions, evidence).
docs/live/artifacts/free-<label>/l4-out/: the run's .l4-out (agent prompts and raw events, gate logs, logs, outcome).
"""

import re
import shutil
import sys
from pathlib import Path

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def text_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    data = src.read_bytes()
    try:
        s = data.decode("utf-8")
    except UnicodeDecodeError:
        dst.write_bytes(data)
        return
    s = ANSI.sub("", s).replace("\r\n", "\n")
    dst.write_text(s, encoding="utf-8")


def main() -> None:
    got, free, arts = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    for label in sys.argv[4:]:
        run = got / label
        out = free / "runs" / label
        if out.exists():
            shutil.rmtree(out)
        for name in ("meta.txt", "run.log", "status.txt", "cfg.yaml", "ci-overlap.txt", "ratelimit.txt"):
            if (run / name).is_file():
                text_copy(run / name, out / name)
        exp = run / "export"
        for name in ("branch-commits.txt", "src-tests.diff"):
            if (exp / name).is_file():
                text_copy(exp / name, out / name)
        for unit_dir in exp.glob("openspec/changes/*"):
            for p in unit_dir.rglob("*"):
                if p.is_file():
                    text_copy(p, out / "unit" / p.relative_to(unit_dir))
        l4out = run / "repo" / ".l4-out"
        dest = arts / f"free-{label}" / "l4-out"
        if dest.exists():
            shutil.rmtree(dest)
        for p in l4out.rglob("*"):
            if p.is_file() and p.name != ".gitignore":
                text_copy(p, dest / p.relative_to(l4out))
        print(label, sum(1 for _ in out.rglob("*") if _.is_file()), sum(1 for _ in dest.rglob("*") if _.is_file()))


if __name__ == "__main__":
    main()
