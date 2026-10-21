"""Write the "=== FILE <path>" sections of `record-probes.sh` (read on stdin) as files under a root directory."""

import sys
from pathlib import Path

MARK = "=== FILE "


def main(root: Path, lines: list[str]) -> list[Path]:
    written: list[Path] = []
    current: list[str] | None = None
    target: Path | None = None
    for line in [*lines, MARK + "\n"]:
        if line.startswith(MARK):
            if target is not None and current is not None:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("".join(current), encoding="utf-8")
                written.append(target)
            name = line[len(MARK) :].strip()
            target = (root / name) if name else None
            if target is not None and (".." in Path(name).parts or Path(name).is_absolute()):
                raise SystemExit(f"refusing to write outside the root: {name}")
            current = []
        elif current is not None:
            current.append(line)
    return written


if __name__ == "__main__":
    for path in main(Path(sys.argv[1]), sys.stdin.readlines()):
        print(path)
