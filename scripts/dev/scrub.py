#!/usr/bin/env python3
"""Replace internal names in a repository's tracked files, driven by a private rules file.

This script holds no names. The rules file (never committed) has the shape
{"untrack": ["dir/", ...], "rules": [{"lit": "...", "to": "..."} | {"re": "...", "to": "...", "i": true}]}.
Rules apply in order; `to` may use \\g<1> group references.

  scrub.py apply --rules FILE [--repo DIR]   untrack, then rewrite tracked text files
  scrub.py check (--rules FILE | --rules-env NAME) [--repo DIR]
                                              exit 1 when any rule would still change a tracked text file or path

Output names rules by index and files by path only; it never prints a pattern, a replacement or matched text.
Exit codes: 0 ok, 1 check found a hit, 2 malformed rules file.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

MAX_HITS = 200


class RulesError(Exception):
    pass


def parse_rules(text: str) -> tuple[list[str], list]:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise RulesError("rules are not valid JSON") from exc
    if not isinstance(data, dict):
        raise RulesError("rules must be a JSON object")
    untrack = data.get("untrack", [])
    rules = data.get("rules", [])
    if not isinstance(untrack, list) or not all(isinstance(u, str) and u for u in untrack):
        raise RulesError("'untrack' must be a list of non-empty strings")
    if not isinstance(rules, list):
        raise RulesError("'rules' must be a list")
    compiled = []
    for i, rule in enumerate(rules):
        if not isinstance(rule, dict) or not isinstance(rule.get("to"), str):
            raise RulesError(f"rule {i}: needs a string 'to'")
        if ("lit" in rule) == ("re" in rule):
            raise RulesError(f"rule {i}: needs exactly one of 'lit' or 're'")
        if "lit" in rule:
            if not isinstance(rule["lit"], str) or not rule["lit"]:
                raise RulesError(f"rule {i}: 'lit' must be a non-empty string")
            compiled.append(("lit", rule["lit"], rule["to"]))
        else:
            if not isinstance(rule["re"], str):
                raise RulesError(f"rule {i}: 're' must be a string")
            try:
                rx = re.compile(rule["re"], re.IGNORECASE if rule.get("i") else 0)
                rx.sub(rule["to"], "")
            except (re.error, IndexError):
                raise RulesError(f"rule {i}: invalid regex or replacement") from None
            compiled.append(("re", rx, rule["to"]))
    return untrack, compiled


def sub(rule, text: str) -> tuple[str, int]:
    kind, pat, to = rule
    if kind == "lit":
        n = text.count(pat)
        return (text.replace(pat, to) if n else text), n
    return pat.subn(to, text)


def matches(rule, text: str) -> bool:
    """True when the rule would still change the text (a replacement that matches its own pattern is clean)."""
    return sub(rule, text)[0] != text


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=check)


def tracked(repo: Path) -> list[str]:
    out = git(repo, "ls-files", "-z").stdout
    return [p.decode("utf-8", "surrogateescape") for p in out.split(b"\0") if p]


def read_text(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\0" in raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def is_tracked(repo: Path, entry: str) -> bool:
    return bool(git(repo, "ls-files", "-z", "--", entry).stdout)


def untrack_entries(repo: Path, entries: list[str]) -> None:
    gi = repo / ".gitignore"
    for entry in entries:
        if is_tracked(repo, entry):
            git(repo, "rm", "-r", "-q", "--cached", "--", entry)
        # an entry already ignored by any pattern (e.g. a broader directory) is not appended again: the appended
        # line would itself be rewritten by the rules on the next apply and pile up
        ignored = git(repo, "check-ignore", "-q", "--no-index", "--", entry, check=False).returncode == 0
        if not ignored:
            prefix = "\n" if gi.exists() and gi.read_text() and not gi.read_text().endswith("\n") else ""
            with gi.open("a") as fh:
                fh.write(f"{prefix}{entry}\n")


def cmd_apply(args) -> int:
    repo = Path(args.repo).resolve()
    try:
        untrack, rules = parse_rules(Path(args.rules).read_text())
    except (RulesError, OSError) as exc:
        print(f"scrub: {exc}", file=sys.stderr)
        return 2
    untrack_entries(repo, untrack)
    counts = [0] * len(rules)
    files = [0] * len(rules)
    for rel in tracked(repo):
        path = repo / rel
        if not path.is_file() or path.is_symlink():
            continue
        text = read_text(path)
        if text is None:
            continue
        new = text
        for i, rule in enumerate(rules):
            new, n = sub(rule, new)
            if n:
                counts[i] += n
                files[i] += 1
        if new != text:
            mode = path.stat().st_mode
            path.write_bytes(new.encode("utf-8"))
            os.chmod(path, mode)
    for i in range(len(rules)):
        print(f"rule {i}: {counts[i]} replacements in {files[i]} files")
    return 0


def cmd_check(args) -> int:
    repo = Path(args.repo).resolve()
    try:
        if args.rules_env:
            src = os.environ.get(args.rules_env)
            if not src:
                raise RulesError("rules environment variable is unset or empty")
        else:
            src = Path(args.rules).read_text()
        untrack, rules = parse_rules(src)
    except (RulesError, OSError) as exc:
        print(f"scrub: {exc}", file=sys.stderr)
        return 2
    hits: list[str] = []
    for entry in untrack:
        if is_tracked(repo, entry):
            hits.append(f"untrack: {entry}")
    names = tracked(repo)
    scanned = 0
    for rel in names:
        for i, rule in enumerate(rules):
            if matches(rule, rel):
                hits.append(f"rule {i}: {rel}")
        path = repo / rel
        if not path.is_file() or path.is_symlink():
            continue
        text = read_text(path)
        if text is None:
            continue
        scanned += 1
        for i, rule in enumerate(rules):
            if matches(rule, text):
                hits.append(f"rule {i}: {rel}")
    if hits:
        for line in hits[:MAX_HITS]:
            print(line)
        print(f"scrub check: {len(hits)} hits")
        return 1
    print(f"scrub check: clean ({scanned} files, {len(rules)} rules)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("apply")
    a.add_argument("--rules", required=True)
    a.add_argument("--repo", default=".")
    c = sp.add_parser("check")
    g = c.add_mutually_exclusive_group(required=True)
    g.add_argument("--rules")
    g.add_argument("--rules-env")
    c.add_argument("--repo", default=".")
    args = ap.parse_args(argv)
    return cmd_apply(args) if args.cmd == "apply" else cmd_check(args)


if __name__ == "__main__":
    sys.exit(main())
