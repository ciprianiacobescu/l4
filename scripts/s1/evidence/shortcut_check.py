"""Label-shortcut check on an `l4 s1 export` data set (M1.6b evidence, 2026-10-05).

For every (question set, qid): is there one token (or one adjacent token pair) of the state text whose presence alone
predicts the label? A decision stump per feature: present -> the majority label of the train rows that contain it,
absent -> the majority label of those that do not. The feature is chosen on train only and then scored on test (and
calib), next to the majority-class baseline and the balanced accuracy, so a high number on a skewed question is not
mistaken for a shortcut. Only the `state` field is read (tags and the expected labels are never features).

usage: python shortcut_check.py <dataset dir> [--json out.json]
"""

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?|[^\sA-Za-z0-9_]")


def tokens(text: str) -> list[str]:
    return [t.lower() for t in TOKEN.findall(text)]


def features(text: str) -> tuple[set[str], set[str]]:
    toks = tokens(text)
    return set(toks), {f"{a} {b}" for a, b in zip(toks, toks[1:])}


def set_of(row: dict) -> str:
    return next((t[4:] for t in row["tags"] if t.startswith("set:")), "?")


def project_of(row: dict) -> str:
    return next((t[8:] for t in row["tags"] if t.startswith("project:")), "?")


def load(data: Path) -> dict[str, list[dict]]:
    return {s: [json.loads(x) for x in (data / f"{s}.jsonl").read_text().splitlines() if x.strip()]
            for s in ("train", "calib", "test")}


def majority(labels: list) -> object:
    return Counter(map(json.dumps, labels)).most_common(1)[0][0] if labels else None


def acc(pred: list, gold: list) -> float | None:
    return sum(p == g for p, g in zip(pred, gold)) / len(gold) if gold else None


def balanced(pred: list, gold: list) -> float | None:
    by: dict[str, list[bool]] = defaultdict(list)
    for p, g in zip(pred, gold):
        by[g].append(p == g)
    return sum(sum(v) / len(v) for v in by.values()) / len(by) if by else None


def best_stump(train: list[tuple[set[str], str]]) -> tuple[str, str, str, float, float]:
    """(feature, label when present, label when absent, balanced acc, acc) of the best stump on `train`, ranked by
    balanced accuracy, then accuracy, then the feature text (deterministic)."""
    gold = [g for _, g in train]
    maj = majority_raw(gold)
    best = ("", maj, maj, balanced([maj] * len(gold), gold), acc([maj] * len(gold), gold))
    vocab = Counter(f for fs, _ in train for f in fs)
    for feat in sorted(vocab):
        if vocab[feat] == len(train):
            continue
        on = [g for fs, g in train if feat in fs]
        off = [g for fs, g in train if feat not in fs]
        p_on, p_off = majority_raw(on), majority_raw(off)
        pred = [p_on if feat in fs else p_off for fs, _ in train]
        cand = (feat, p_on, p_off, balanced(pred, gold), acc(pred, gold))
        if (cand[3], cand[4]) > (best[3], best[4]):
            best = cand
    return best


def majority_raw(gold: list[str]) -> str:
    return Counter(gold).most_common(1)[0][0]


def apply(stump: tuple, rows: list[tuple[set[str], str]]) -> tuple[float | None, float | None]:
    feat, p_on, p_off = stump[0], stump[1], stump[2]
    pred = [p_on if feat in fs else p_off for fs, _ in rows]
    gold = [g for _, g in rows]
    return acc(pred, gold), balanced(pred, gold)


def main(argv: list[str]) -> int:
    data = Path(argv[0])
    out_json = Path(argv[argv.index("--json") + 1]) if "--json" in argv else None
    splits = load(data)
    qids = sorted({(set_of(r), q) for rows in splits.values() for r in rows for q in r["expected"]})
    report = []
    for set_name, qid in qids:
        entry: dict = {"set": set_name, "qid": qid}
        for kind in ("unigram", "bigram"):
            def rows_of(split: str) -> list[tuple[set[str], str]]:
                out = []
                for r in splits[split]:
                    if set_of(r) == set_name and qid in r["expected"]:
                        uni, bi = features(r["state"])
                        out.append((uni if kind == "unigram" else bi, json.dumps(r["expected"][qid])))
                return out

            tr, ca, te = rows_of("train"), rows_of("calib"), rows_of("test")
            if not tr:
                continue
            stump = best_stump(tr)
            maj = majority_raw([g for _, g in tr])
            entry[kind] = {
                "feature": stump[0], "present": stump[1], "absent": stump[2],
                "train": {"n": len(tr), "acc": round(stump[4], 3), "bal_acc": round(stump[3], 3),
                          "majority_acc": round(acc([maj] * len(tr), [g for _, g in tr]), 3)},
            }
            for name, rows in (("calib", ca), ("test", te)):
                a, b = apply(stump, rows)
                entry[kind][name] = {
                    "n": len(rows), "acc": None if a is None else round(a, 3), "bal_acc": None if b is None else round(b, 3),
                    "majority_acc": None if not rows else round(acc([maj] * len(rows), [g for _, g in rows]), 3),
                    "labels": dict(Counter(g for _, g in rows)),
                }
        report.append(entry)
    for e in report:
        u = e.get("unigram")
        if not u:
            continue
        t = u["test"]
        print(f"{e['set']:<26} {e['qid']:<14} uni {u['feature']!r:<22} train acc {u['train']['acc']:.3f} "
              f"bal {u['train']['bal_acc']:.3f} | test n={t['n']} acc {t['acc']} bal {t['bal_acc']} "
              f"maj {t['majority_acc']} | bi {e['bigram']['feature']!r} train {e['bigram']['train']['acc']:.3f} "
              f"test {e['bigram']['test']['acc']}")
    if out_json:
        out_json.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
