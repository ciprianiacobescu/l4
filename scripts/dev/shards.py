#!/usr/bin/env python3
"""Split the unit test files into N deterministic shards (L4-ACT-007).

    python scripts/dev/shards.py --shard K --of N     # prints the files of shard K (1-based), one per line

The weight of a file is the number of test functions found by an AST walk (a `parametrize` over a literal list
counts once per case). Files are placed largest first onto the lightest shard, ties broken by path, so the result
depends only on the file contents, never on the machine, the clock or the order the filesystem lists them.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

TEST_DIR = "tests/unit"


def test_files(root: Path) -> list[str]:
    """Repository-relative posix paths of tests/unit/**/test_*.py, sorted."""
    base = root / TEST_DIR
    return sorted(p.relative_to(root).as_posix() for p in base.rglob("test_*.py"))


def _cases(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    count = 1
    for dec in node.decorator_list:
        call = dec if isinstance(dec, ast.Call) else None
        if call is None or not isinstance(call.func, ast.Attribute) or call.func.attr != "parametrize":
            continue
        if len(call.args) >= 2 and isinstance(call.args[1], ast.List | ast.Tuple):
            count *= max(1, len(call.args[1].elts))
    return count


def weight(path: Path) -> int:
    """Test functions in the file (parametrized literal cases counted); at least 1."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return 1
    total = sum(
        _cases(n)
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name.startswith("test")
    )
    return max(1, total)


def assign(root: Path, of: int) -> list[list[str]]:
    """All shards, each a sorted list of relative paths."""
    weighed = sorted(((weight(root / f), f) for f in test_files(root)), key=lambda wf: (-wf[0], wf[1]))
    loads = [0] * of
    shards: list[list[str]] = [[] for _ in range(of)]
    for w, f in weighed:
        i = min(range(of), key=lambda j: (loads[j], j))
        loads[i] += w
        shards[i].append(f)
    return [sorted(s) for s in shards]


def shard(root: Path, k: int, of: int) -> list[str]:
    return assign(root, of)[k - 1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--shard", type=int, required=True, help="1-based shard number")
    parser.add_argument("--of", type=int, required=True, help="number of shards")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--weights", action="store_true", help="print 'weight path' lines instead of paths")
    args = parser.parse_args(argv)
    if args.of < 1 or not 1 <= args.shard <= args.of:
        print(f"shards: need 1 <= shard <= of, got shard={args.shard} of={args.of}", file=sys.stderr)
        return 2
    for f in shard(args.root, args.shard, args.of):
        print(f"{weight(args.root / f)} {f}" if args.weights else f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
