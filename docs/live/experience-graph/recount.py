"""Independent recount of five KG report numbers from raw git objects (no l4.kg code)."""
import collections, json, re, subprocess, sys

def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True, check=True).stdout

refs = [r for r in git("for-each-ref", "--format=%(refname)", "refs/remotes/origin/", "refs/l4/").split() if not r.endswith("/HEAD")]
blobs = {}  # blob sha -> (ref, path)
for ref in refs:
    for line in git("ls-tree", "-r", ref).splitlines():
        meta, path = line.split("\t", 1)
        sha = meta.split()[2]
        if re.search(r"(\.l4/ledger/|ledger-pending/)r-[^/]+\.jsonl$", path) or re.search(r"\.l4/evidence/round-\d+/verdict\.json$", path):
            blobs.setdefault(sha, (ref, path))
runs, rounds = set(), set()
events = {}  # (run_id, seq) -> event
for sha, (ref, path) in blobs.items():
    text = git("cat-file", "-p", sha)
    if path.endswith("verdict.json"):
        rounds.add(sha)
        continue
    for line in text.splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        runs.add(e.get("run_id"))
        events[(e.get("run_id"), e.get("seq"))] = e
vac = [e for e in events.values() if e.get("type") == "task.attempt_failed" and str(e.get("reason", "")).startswith("vacuous")]
stops = collections.Counter()
for e in events.values():
    if e.get("type") in ("unit.stopped", "run.stopped", "stop.recorded") or (e.get("type", "").startswith("unit.") and "reason" in e and e.get("type") not in ("unit.started",)):
        pass
inj = [e for e in events.values() if e.get("type") == "lessons.injected"]
print("runs (distinct run_id):", len(runs))
print("round verdict blobs (distinct):", len(rounds))
print("vacuous attempt failures:", len(vac), "units:", sorted({e.get("unit") for e in vac}))
types = collections.Counter(e.get("type") for e in events.values())
print("stop-like event types:", {t: n for t, n in types.items() if "stop" in t or "halt" in t or "escalat" in t})
print("lessons.injected events:", len(inj), "sample keys:", sorted(inj[0].keys()) if inj else None)
for e in inj[:3]: print("  ", {k: str(v)[:60] for k, v in e.items() if k not in ("ts",)})
