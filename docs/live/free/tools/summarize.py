"""summarize.py GOT_DIR [LABEL...]: one JSON line per fetched run (implementer and judge measurements)."""

import contextlib
import json
import re
import sys
from pathlib import Path

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def ledger_events(run: Path) -> list[dict]:
    out = []
    for p in sorted(run.glob("export/openspec/changes/*/.l4/ledger/*.jsonl")):
        for line in p.read_text(errors="replace").splitlines():
            with contextlib.suppress(ValueError):
                out.append(json.loads(line))
    return out


def findings(run: Path) -> list[dict]:
    res = []
    for v in run.glob("export/openspec/changes/*/verification.md"):
        text = v.read_text(errors="replace")
        sec = text.split("## Findings", 1)[1].split("\n## ", 1)[0] if "## Findings" in text else ""
        for m in re.finditer(r"^- \[(\w+), (\w+)\] (.+)$", sec, re.M):
            res.append({"severity": m.group(1), "source": m.group(2), "text": m.group(3)[:300]})
    return res


def summarize(run: Path) -> dict:
    meta = (run / "meta.txt").read_text()
    kv = dict(re.findall(r"(\w+)=(\S*)", meta.splitlines()[0]))
    end = re.search(r"END rc=(\d+) secs=(\d+)", meta)
    log = ANSI.sub("", (run / "run.log").read_text(errors="replace"))
    l4 = [ln[ln.index("[l4]"):] for ln in log.splitlines() if "[l4]" in ln]
    ev = ledger_events(run)
    steps = [e for e in ev if e.get("type") == "step.finished"]
    agents = [e for e in ev if e.get("type") == "agent.finished"]
    judges = [e for e in ev if e.get("type") == "verify.judge"]
    verdicts = [e for e in ev if e.get("type") == "verify.verdict"]
    durations = re.findall(r"agent (\w+) task ([\d.]+) (\w+) \(([\d.]+)s\)", "\n".join(l4))
    fails = [ln for ln in l4 if re.search(r"attempt \d+ failed|halted|escalat|guard violation|question Q-", ln)]
    judge_lines = [ln for ln in l4 if "verify judge" in ln or "judges:" in ln]
    cost = re.findall(r"cost \+\$([\d.]+) \((judge|clarifier|[^)]*)\)", "\n".join(l4))
    finished = re.search(r"run finished: exit (\d+) in ([\d.]+)s, cost \$([\d.]+)", "\n".join(l4))
    verdict_line = [ln for ln in l4 if " verdict " in ln]
    fnd = findings(run)
    return {
        "label": kv.get("LABEL"), "kind": kv.get("KIND"), "unit": kv.get("UNIT"), "impl": kv.get("IMPL"),
        "judges": kv.get("JUDGES"),
        "rc": int(end.group(1)) if end else None,
        "secs": int(end.group(2)) if end else None,
        "finished": finished.groups() if finished else None,
        "steps": [(s.get("task"), s.get("phase"), s.get("attempt"), s.get("status")) for s in steps],
        "agents": [(a.get("phase"), a.get("status"), a.get("detail"), a.get("input_tokens"), a.get("output_tokens"),
                    a.get("permission_denials"), a.get("denied_tools")) for a in agents],
        "agent_durations": durations,
        "judge": [
            (j.get("profile"), j.get("status"), j.get("calls"), j.get("model"), j.get("detail")) for j in judges
        ],
        "verdict": [
            (v.get("round"), v.get("verdict"), v.get("criteria_passed"), v.get("criteria_total"), v.get("findings"))
            for v in verdicts
        ],
        "verdict_line": verdict_line[-1:] if verdict_line else [],
        "costs": cost,
        "fails": fails[:12],
        "judge_lines": judge_lines[:6],
        "findings": fnd,
        "ratelimit": (run / "ratelimit.txt").read_text()[:500] if (run / "ratelimit.txt").exists() else "",
        "ci_overlap": (
            len((run / "ci-overlap.txt").read_text().splitlines()) if (run / "ci-overlap.txt").exists() else 0
        ),
    }


if __name__ == "__main__":
    got = Path(sys.argv[1])
    labels = sys.argv[2:] or sorted(p.name for p in got.iterdir() if p.is_dir())
    for name in labels:
        print(json.dumps(summarize(got / name)))
