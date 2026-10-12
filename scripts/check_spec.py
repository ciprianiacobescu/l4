"""Mechanical self-consistency checks for docs/SPEC.md (SPEC §26)."""
import re, sys

t = open(sys.argv[1], encoding="utf-8").read()
part1, part2 = t.split("# Part II", 1)
problems = 0

# 1. requirement ↔ scenario coverage
defined = set(re.findall(r"\*\*(L4-[A-Z]+-\d{3}[a-z]?)", part1)) | set(re.findall(r"^\| (L4-[A-Z]+-\d{3}) \|", part1, re.M))
scen = re.findall(r"^#### (SCN-[A-Z]+-\d+) \(([^)]*)\) (.*)$", part2, re.M)
refs = set()
for m in re.finditer(r"(L4-[A-Z]+-)(\d{3}[a-z]?)(?:…(\d{3}))?", part2):
    p, a, b = m.group(1), m.group(2), m.group(3)
    if b:
        for n in range(int(a[:3]), int(b) + 1):
            refs.add(f"{p}{n:03d}")
    else:
        refs.add(p + a)
uncovered = sorted(defined - refs)
undefined = sorted(r for r in refs - defined if r[:-1] not in defined)  # tolerate 002 vs 002a prefix refs
ids = [s for s, _, _ in scen]
dups = sorted({s for s in ids if ids.count(s) > 1})
print(f"requirements: {len(defined)} | scenarios: {len(scen)} | (+): {sum('+' in p for _, p, _ in scen)} | (−): {sum('−' in p for _, p, _ in scen)}")
for label, items in (("UNCOVERED requirements", uncovered), ("UNDEFINED refs", undefined), ("duplicate scenario ids", dups)):
    print(f"{label}: {items}")
    problems += bool(items)

# 2. exit codes and phases named in scenarios
sec22 = re.search(r"### 2\.2 Exit codes(.*?)\n### |\n## 3\.", part1, re.S)
sec22 = sec22.group(1) if sec22 and sec22.group(1) else part1[part1.index("### 2.2"):part1.index("## 3.")]
codes = {int(c) for c in re.findall(r"^\| (\d+) \| `[a-z_]+` \|", sec22, re.M)}
states = set(re.findall(r"`([a-z_]+)`", re.search(r"States: (.*?)\. The orchestrator", part1, re.S).group(1)))
table = re.search(r"### 12\.0 Lifecycle.*?\n\| From \|.*?\n\|---.*?\n(.*?)\n\n", part1, re.S).group(1)
exits_for = {}
for row in table.splitlines():
    cols = [c.strip() for c in row.strip().strip("|").split("|")]
    if len(cols) < 4:
        continue
    to_states = re.findall(r"`([a-z_]+)`", cols[2])
    ex = set(int(x) for x in re.findall(r"\b(\d+)\b", cols[3]))
    for s in to_states[:1]:
        exits_for.setdefault(s, set()).update(ex if ex else {None})
bad = []
for block in re.split(r"^#### ", part2, flags=re.M)[1:]:
    sid = block.split(" ", 1)[0]
    then = block.split("**Then**", 1)[1] if "**Then**" in block else ""
    for c in re.findall(r"\bexit (\d+)\b", block):
        if int(c) not in codes:
            bad.append(f"{sid}: unknown exit {c}")
    for s in re.findall(r"phase `([a-z_]+)`", block):
        if s not in states:
            bad.append(f"{sid}: unknown phase {s}")
    ph = re.findall(r"phase `([a-z_]+)`", then)
    ex = re.findall(r"\bexit (\d+)\b", then)
    if len(set(ph)) == 1 and len(set(ex)) == 1 and ph[0] in exits_for:
        allowed = exits_for[ph[0]]
        if None not in allowed and int(ex[0]) not in allowed:
            bad.append(f"{sid}: phase {ph[0]} with exit {ex[0]} not in §12.0 ({sorted(x for x in allowed if x is not None)})")
print(f"exit codes: {sorted(codes)} | states: {len(states)}")
print("scenario phase/exit problems:", bad)
problems += bool(bad)

# 3. config keys referenced in backticks must exist in the §3.2 reference configuration (rule 2)
try:
    import yaml
    block = re.search(r"### 3\.2 Reference configuration.*?```yaml\n(.*?)```", t, re.S).group(1)
    cfg = yaml.safe_load(block)
    paths = set()

    def walk(d, pre=""):
        if isinstance(d, dict):
            for k, v in d.items():
                p = f"{pre}.{k}" if pre else str(k)
                paths.add(p)
                walk(v, p)

    walk(cfg)
    events = set(re.findall(r"`([a-z_]+\.[a-z_.]+)`", part1[part1.index("### 12.1"):part1.index("### 12.2")]))
    allow = {"ci.skip", "feedback.md"} | events  # feedback.md is the file, not a config key (L4-FBK-001)
    tops = sorted(cfg.keys(), key=len, reverse=True)
    refs = set(m.group(1) for m in re.finditer(r"`((?:%s)(?:\.[a-z_0-9]+)+)`" % "|".join(tops), t))
    unknown = sorted(r for r in refs - allow if r not in paths
                     and not r.startswith(("profiles.", "roles.", "sandbox.credential_paths.", "sandbox.caches.",
                                           "sandbox.user_per_profile.", "budgets.price_table."))
                     and not re.match(r"^(availability|clarifier|archive|budget|verify|question|task|guard|lock|"
                                      r"phase|unit|run|step|agent|gate|fix|pr|lessons|human|bootstrap|push)\.[a-z_]+$", r)
                     or (r.split(".")[0] in ("gates", "verifier", "tdd", "odd", "sandbox", "spec", "memory", "forge",
                                              "ci", "locks", "implementer", "harness", "sdd", "observability")
                         and r not in paths))
    print("config keys not in §3.2:", unknown)
    problems += bool(unknown)
except ImportError:
    print("pyyaml missing: config-key rule skipped")

# 4. banned terms from retired designs
banned = ["at the tip", "in_branch_tip", "refresh_on_base_move", "fails on the base commit", "min_judges",
          "npx -y @fission-ai", "archive commit at the branch tip"]
hits = [(b, t.count(b)) for b in banned if b in t]
print("retired-design terms:", hits)
problems += bool(hits)
sys.exit(1 if problems else 0)
