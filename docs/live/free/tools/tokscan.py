"""tokscan.py DIR...: files holding a token shape (GitLab, OpenAI-style sk-, Mintkey agent keys, JWTs, apikey_)."""
import re
import sys
from pathlib import Path

PATS = {
    "glpat": re.compile(rb"glpat-[A-Za-z0-9_\-]{10,}"), "glcbt": re.compile(rb"glcbt-[A-Za-z0-9_\-]{10,}"),
    "glptt": re.compile(rb"glptt-[A-Za-z0-9_\-]{10,}"), "apikey_": re.compile(rb"apikey_[A-Za-z0-9]{8,}"),
    "sk-": re.compile(rb"\bsk-[A-Za-z0-9_\-]{16,}"), "mk_agent_": re.compile(rb"mk_agent_[A-Za-z0-9]{20,}"),
    "jwt": re.compile(rb"eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
    "bearer": re.compile(rb"[Bb]earer [A-Za-z0-9_\-\.]{24,}"),
}
files = hits = 0
for root in sys.argv[1:]:
    for p in sorted(Path(root).rglob("*")):
        if not p.is_file():
            continue
        files += 1
        data = p.read_bytes()
        found = [k for k, rx in PATS.items() if rx.search(data)]
        if found:
            hits += 1
            print(f"HIT {p}: {found}")
print(f"scanned {files} files, {hits} with a token shape")
