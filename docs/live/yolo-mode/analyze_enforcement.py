"""Were a delivery plan's dependencies enforced? Reads git only (no l4 code), so it is an independent check.

usage: analyze_enforcement.py --repo CLONE --plan ID [--target BRANCH] [--json]

Before running, fetch everything into the clone:
    git fetch origin '+refs/heads/*:refs/remotes/origin/*' '+refs/l4/*:refs/l4/*'

Sources:
- the plan file `.l4/plans/<id>.json` on `origin/<target>` (or the newest one in the plan ledger's history);
- the plan ledger `refs/l4/plans/<id>:ledger.jsonl` (unit.dispatched, unit.merged, unit.integrated, plan.* events);
- every unit ledger `**/.l4/ledger/r-*.jsonl` and `ledger-pending/r-*.jsonl` in every ref (run.started per unit).

Checks, per unit u with prerequisites P(u) (its depends_on, plus every unit of every batch its batch depends on):
- C1 dispatched after prerequisites: the first unit.dispatched{u} is later than unit.integrated{p} for every p in P(u);
- C2 no run before prerequisites: the first run.started of u in any ledger is later than unit.integrated{p};
- C3 serial: no run of u started while another plan unit was dispatched and not yet integrated;
- C4 complete: every unit of the plan was integrated (else the plan's stop or wait is shown).
Exit 0 when C1-C3 hold for every unit (C4 is reported, not required), 1 otherwise, 2 on a usage or read error.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime

LEDGER = re.compile(r"(\.l4/ledger/|ledger-pending/)r-[^/]+\.jsonl$")


def git(repo: str, *args: str, check: bool = True) -> str:
    done = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if check and done.returncode != 0:
        raise SystemExit(f"git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout


def when(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def plan_events(repo: str, plan: str) -> list[dict]:
    raw = git(repo, "show", f"refs/l4/plans/{plan}:ledger.jsonl")
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def plan_file(repo: str, plan: str, target: str | None, events: list[dict]) -> dict:
    refs = [f"refs/remotes/origin/{target}"] if target else []
    for ref in refs:
        text = git(repo, "show", f"{ref}:.l4/plans/{plan}.json", check=False)
        if text.strip():
            return json.loads(text)
    raise SystemExit(f"no .l4/plans/{plan}.json on {refs or 'any ref'}: pass --target")


def prerequisites(plan: dict) -> dict[str, set[str]]:
    batch_units = {b["id"]: [u["id"] for u in b["units"]] for b in plan["batches"]}
    pre: dict[str, set[str]] = {}
    for batch in plan["batches"]:
        induced = {u for dep in batch.get("depends_on", []) for u in batch_units.get(dep, [])}
        for unit in batch["units"]:
            pre[unit["id"]] = set(unit.get("depends_on", [])) | induced
    return pre


def first_runs(repo: str) -> dict[str, datetime]:
    """unit id -> earliest run.started over every ledger blob of every ref (deduplicated by blob)."""
    refs = [
        r
        for r in git(repo, "for-each-ref", "--format=%(refname)", "refs/remotes/origin/", "refs/l4/").split()
        if not r.endswith("/HEAD") and not r.startswith("refs/l4/plans/")
    ]
    seen: set[str] = set()
    first: dict[str, datetime] = {}
    for ref in refs:
        for line in git(repo, "ls-tree", "-r", ref).splitlines():
            meta, path = line.split("\t", 1)
            sha = meta.split()[2]
            if sha in seen or not LEDGER.search(path):
                continue
            seen.add(sha)
            for raw in git(repo, "cat-file", "-p", sha).splitlines():
                if '"run.started"' not in raw:
                    continue
                event = json.loads(raw)
                if event.get("type") == "run.started" and event.get("unit") and event.get("ts"):
                    at = when(event["ts"])
                    unit = event["unit"]
                    if unit not in first or at < first[unit]:
                        first[unit] = at
    return first


def run_starts(repo: str) -> dict[str, list[datetime]]:
    """unit id -> every run.started time (all ledgers, deduplicated by run id)."""
    refs = [
        r
        for r in git(repo, "for-each-ref", "--format=%(refname)", "refs/remotes/origin/", "refs/l4/").split()
        if not r.endswith("/HEAD") and not r.startswith("refs/l4/plans/")
    ]
    seen_blobs: set[str] = set()
    seen_runs: set[str] = set()
    starts: dict[str, list[datetime]] = {}
    for ref in refs:
        for line in git(repo, "ls-tree", "-r", ref).splitlines():
            meta, path = line.split("\t", 1)
            sha = meta.split()[2]
            if sha in seen_blobs or not LEDGER.search(path):
                continue
            seen_blobs.add(sha)
            for raw in git(repo, "cat-file", "-p", sha).splitlines():
                if '"run.started"' not in raw:
                    continue
                event = json.loads(raw)
                run = event.get("run_id")
                if event.get("type") == "run.started" and run not in seen_runs and event.get("unit"):
                    seen_runs.add(run)
                    starts.setdefault(event["unit"], []).append(when(event["ts"]))
    return starts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--target")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    events = plan_events(args.repo, args.plan)
    plan = plan_file(args.repo, args.plan, args.target, events)
    pre = prerequisites(plan)
    units = [u["id"] for b in plan["batches"] for u in b["units"]]
    dispatched: dict[str, datetime] = {}
    integrated: dict[str, datetime] = {}
    merged: dict[str, datetime] = {}
    for e in events:
        unit, at = e.get("unit"), when(e["at"])
        if e["type"] == "unit.dispatched" and unit not in dispatched:
            dispatched[unit] = at
        elif e["type"] == "unit.merged" and unit not in merged:
            merged[unit] = at
        elif e["type"] == "unit.integrated" and unit not in integrated:
            integrated[unit] = at
    first = first_runs(args.repo)
    starts = run_starts(args.repo)
    # the interval in which each plan unit was the plan's current unit
    current = {u: (dispatched[u], integrated.get(u)) for u in units if u in dispatched}
    rows, failures = [], []
    for u in units:
        row = {
            "unit": u,
            "prerequisites": sorted(pre[u]),
            "dispatched": dispatched.get(u),
            "first_run": first.get(u),
            "merged": merged.get(u),
            "integrated": integrated.get(u),
            "checks": {},
        }
        late = [p for p in pre[u] if p not in integrated or (u in dispatched and integrated[p] >= dispatched[u])]
        row["checks"]["C1"] = "n/a" if u not in dispatched else ("ok" if not late else f"FAIL before {late}")
        early = [p for p in pre[u] if u in first and (p not in integrated or integrated[p] >= first[u])]
        row["checks"]["C2"] = "n/a" if u not in first else ("ok" if not early else f"FAIL before {early}")
        # runs of u up to its integration (a later archive or sweep run is not the unit's work)
        own = [t for t in starts.get(u, []) if u not in integrated or t < integrated[u]]
        overlap = [
            other
            for other, (start, end) in current.items()
            if other != u
            for t in own
            if start <= t and (end is None or t < end)
        ]
        row["checks"]["C3"] = "ok" if not overlap else f"FAIL during {sorted(set(overlap))}"
        row["checks"]["C4"] = "ok" if u in integrated else "not integrated"
        for c in ("C1", "C2", "C3"):
            if row["checks"][c].startswith("FAIL"):
                failures.append(f"{u} {c}: {row['checks'][c]}")
        rows.append(row)
    tail = [e for e in events if e["type"].startswith("plan.") and e["type"] not in ("plan.charged",)]
    result = {
        "plan": args.plan,
        "units": rows,
        "failures": failures,
        "plan_events": [
            {"type": e["type"], "at": e["at"], **{k: e[k] for k in ("reason", "unit", "detail") if k in e}}
            for e in tail
        ],
    }
    if args.json:
        print(json.dumps(result, default=str, indent=2))
    else:
        fmt = lambda t: t.strftime("%m-%d %H:%M:%S") if t else "-"  # noqa: E731
        print(f"plan {args.plan}: {len(units)} units, {sum(1 for u in units if u in integrated)} integrated")
        print(
            f"{'unit':34} {'prerequisites':44} {'dispatched':15} {'first run':15} {'integrated':15} C1   C2   C3   C4"
        )
        for r in rows:
            short = ",".join(p.split(":", 1)[1] for p in r["prerequisites"]) or "-"
            c = r["checks"]
            print(
                f"{r['unit']:34} {short[:44]:44} {fmt(r['dispatched']):15} {fmt(r['first_run']):15} "
                f"{fmt(r['integrated']):15} {c['C1'][:4]:4} {c['C2'][:4]:4} {c['C3'][:4]:4} {c['C4'][:4]}"
            )
        print(
            "plan events: "
            + "; ".join(
                f"{e['type']}{'(' + e.get('reason', '') + ')' if e.get('reason') else ''}"
                for e in result["plan_events"]
            )
        )
        print(
            "RESULT: "
            + (
                "dependencies enforced (C1-C3 hold for every unit)"
                if not failures
                else "FAILED: " + "; ".join(failures)
            )
        )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
