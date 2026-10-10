"""Best single-token stump ranked by plain accuracy (complements shortcut_check.py, which ranks by balanced accuracy).
Train-chosen, scored on test; also the in-sample maximum over the train+calib+test union (an upper bound)."""
import json, sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from shortcut_check import features, load, set_of, majority_raw

def best(rows):
    gold = [g for _, g in rows]; vocab = Counter(f for fs, _ in rows for f in fs)
    maj = majority_raw(gold); top = ("<majority>", maj, maj, sum(g == maj for g in gold) / len(gold))
    for feat in sorted(vocab):
        on = [g for fs, g in rows if feat in fs]; off = [g for fs, g in rows if feat not in fs]
        p_on = majority_raw(on); p_off = majority_raw(off) if off else p_on
        a = sum((p_on if feat in fs else p_off) == g for fs, g in rows) / len(rows)
        if a > top[3]: top = (feat, p_on, p_off, a)
    return top

splits = load(Path(sys.argv[1])); out = {}
for set_name, qid in sorted({(set_of(r), q) for rs in splits.values() for r in rs for q in r["expected"]}):
    get = lambda s: [(features(r["state"])[0], json.dumps(r["expected"][qid])) for r in splits[s] if set_of(r) == set_name and qid in r["expected"]]
    tr, te = get("train"), get("test")
    b = best(tr); ta = sum((b[1] if b[0] in fs else b[2]) == g for fs, g in te) / len(te)
    u = best(tr + get("calib") + te)
    out[f"{set_name}/{qid}"] = {"train_best": b[0], "train_acc": round(b[3], 3), "test_acc": round(ta, 3),
                                "union_best": u[0], "union_acc": round(u[3], 3), "n_train": len(tr), "n_test": len(te)}
    print(f"{set_name}/{qid}: {out[f'{set_name}/{qid}']}")
Path(sys.argv[2]).write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
