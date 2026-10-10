"""Per-question accuracy per engine on (a) every row it scored and (b) the rows all engines scored (Jev's capped
subset), each split into real (dummy-agentic) and synthetic (py_multi) rows, and untouched (mutation:none) vs mutated.
Reuses `l4.s1.report`'s own outcome and metric code; `expected` is read as the reference only (as `report` does).

usage: uv run python slices.py <test.jsonl> <name>=<scores.jsonl>... --real git-xxxx --synthetic git-yyyy [--json F]
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

from l4.llm.system_one import Answer
from l4.s1.report import _metrics, _outcome, _read_scores, _tag
from l4.s1.score import file_sha256, read_rows


def main(argv: list[str]) -> int:
    dataset = Path(argv[0])
    real = argv[argv.index("--real") + 1]
    synth = argv[argv.index("--synthetic") + 1]
    out_json = Path(argv[argv.index("--json") + 1]) if "--json" in argv else None
    engines = {}
    for arg in argv[1:]:
        if "=" in arg and not arg.startswith("--"):
            name, path = arg.split("=", 1)
            header, scored = _read_scores(Path(path))
            assert header["dataset_sha256"] == file_sha256(dataset), f"{path} scored on other bytes"
            engines[name] = {i: line for i, line in scored.items() if "answers" in line and not line.get("error")}
    rows = read_rows(dataset)
    common = set.intersection(*(set(s) for s in engines.values()))
    project_name = {real: "real", synth: "synthetic"}
    result: dict = {"rows": len(rows), "scored": {k: len(v) for k, v in engines.items()}, "common_rows": len(common)}
    for scope_name, keep in (("all_scored", None), ("common", common)):
        table: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        for name, scored in engines.items():
            for index, line in scored.items():
                if keep is not None and index not in keep:
                    continue
                row = rows[index]
                set_name = _tag(row["tags"], "set:") or "?"
                proj = project_name.get(_tag(row["tags"], "project:") or "", "other")
                mutation = _tag(row["tags"], "mutation:") or "?"
                untouched = "untouched" if mutation == "none" else "mutated"
                for qid, expected in row["expected"].items():
                    raw = line["answers"].get(qid)
                    if raw is None:
                        continue
                    one = _outcome(Answer.from_json(raw), expected, None)
                    key = f"{set_name.split('/')[-1]}/{qid}"
                    for group in ("all", proj, f"{proj}/{untouched}"):
                        table[group][key][name].append(one)
        result[scope_name] = {
            g: {k: {e: _metrics(v) for e, v in sorted(per.items())} for k, per in sorted(qs.items())}
            for g, qs in sorted(table.items())
        }
    if out_json:
        out_json.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    names = list(engines)
    for scope_name in ("all_scored", "common"):
        print(f"\n## {scope_name} (rows: {result['scored'] if scope_name == 'all_scored' else result['common_rows']})")
        for group, qs in result[scope_name].items():
            print(f"\n### {group}")
            print("| question | " + " | ".join(f"{n} acc (n)" for n in names) + " |")
            print("|---|" + "---|" * len(names))
            for key, per in qs.items():
                cells = []
                for n in names:
                    m = per.get(n)
                    cells.append("-" if not m else f"{m['accuracy']:.3f} ({m['n']})")
                print(f"| {key} | " + " | ".join(cells) + " |")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
