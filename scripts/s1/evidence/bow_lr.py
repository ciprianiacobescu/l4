"""Bag-of-words logistic regression per question (train -> test), and the best single token chosen within each
project (real dummy-agentic / synthetic py_multi). Only `state` is a feature. Context for the single-token check."""
import json, re, sys
from collections import Counter
from pathlib import Path
import numpy as np
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score
sys.path.insert(0, str(Path(__file__).parent))
from shortcut_check import best_stump, features, apply, majority_raw, acc

P = {"git-35b5a131ecf1": "real", "git-e13e7b2e670c": "synthetic"}
data = Path(sys.argv[1])
tag = lambda r, p: next((t[len(p):] for t in r["tags"] if t.startswith(p)), None)
rows = {s: [json.loads(l) for l in (data / f"{s}.jsonl").read_text().splitlines() if l.strip()] for s in ("train", "test")}
out = {}
for set_name, qid in [("l4/file-relevant@1", "relevant"), ("l4/change-covered@1", "exercised"), ("l4/tests-ok@2", "all_passed"),
                      ("l4/file-relevant@1", "relatedness"), ("l4/change-covered@1", "extent")]:
    pick = lambda s: [r for r in rows[s] if tag(r, "set:") == set_name and qid in r["expected"]]
    tr, te = pick("train"), pick("test")
    vec = CountVectorizer(token_pattern=r"[A-Za-z_][A-Za-z0-9_]*|\d+", ngram_range=(1, 2), binary=True, lowercase=True)
    Xtr, Xte = vec.fit_transform([r["state"] for r in tr]), vec.transform([r["state"] for r in te])
    ytr, yte = [json.dumps(r["expected"][qid]) for r in tr], [json.dumps(r["expected"][qid]) for r in te]
    lr = LogisticRegression(C=1.0, max_iter=5000).fit(Xtr, ytr)
    pred = lr.predict(Xte)
    entry = {"lr_test_acc": round(accuracy_score(yte, pred), 3), "lr_test_bal": round(balanced_accuracy_score(yte, pred), 3),
             "lr_train_acc": round(accuracy_score(ytr, lr.predict(Xtr)), 3), "n_train": len(tr), "n_test": len(te)}
    for proj in ("real", "synthetic"):
        idx = [i for i, r in enumerate(te) if P[tag(r, "project:")] == proj]
        if idx:
            entry[f"lr_test_acc_{proj}"] = round(accuracy_score([yte[i] for i in idx], [pred[i] for i in idx]), 3)
            entry[f"n_test_{proj}"] = len(idx)
        trp = [(features(r["state"])[0], json.dumps(r["expected"][qid])) for r in tr if P[tag(r, "project:")] == proj]
        tep = [(features(r["state"])[0], json.dumps(r["expected"][qid])) for r in te if P[tag(r, "project:")] == proj]
        if trp and len({g for _, g in trp}) > 1:
            st = best_stump(trp)
            a, b = apply(st, tep) if tep else (None, None)
            entry[f"stump_{proj}"] = {"feature": st[0], "train_acc": round(st[4], 3), "train_bal": round(st[3], 3),
                                      "train_majority": round(acc([majority_raw([g for _, g in trp])] * len(trp), [g for _, g in trp]), 3),
                                      "test_acc": a and round(a, 3), "test_bal": b and round(b, 3), "n_train": len(trp), "n_test": len(tep)}
        else:
            entry[f"stump_{proj}"] = {"note": "one label only in train", "labels": dict(Counter(g for _, g in trp))}
    out[f"{set_name}/{qid}"] = entry
    print(f"{set_name}/{qid}: {json.dumps(entry)}")
Path(sys.argv[2]).write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
