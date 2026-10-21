"""Check the vendored Laya script against vendor/SHA256. Standard library only (no torch)."""

import hashlib
import sys
from pathlib import Path

VENDOR = Path(__file__).resolve().parent / "vendor"


def mismatches(vendor: Path = VENDOR) -> list[str]:
    bad = []
    for line in (vendor / "SHA256").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split(None, 1)
        target = vendor / name.strip().lstrip("*")
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            bad.append(target.name)
    return bad


if __name__ == "__main__":
    problems = mismatches()
    if problems:
        sys.exit("vendored file differs from vendor/SHA256: " + ", ".join(problems))
    print("vendor ok")
