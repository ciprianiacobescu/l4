"""Auditing the ground truth by hand (M16-G14): `l4 s1 audit`.

`write_checklist` draws a seeded sample of the test split into a Markdown file. The maintainer writes `agree` or
`disagree: <label>` after `verdict:` on each row; `import_checklist` turns every answer into a `label` record with
source `human:audit` (a disagreement overrides the deterministic label in the next export) and reports the noise rate
of the deterministic labels with a Wilson interval. Reads no engine answer.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from l4.s1.questions import SETS, label_name, label_names, truth_from_label
from l4.s1.records import LabelRecord, append_records
from l4.s1.stats import wilson

SOURCE = "human:audit"
MAX_STATE_CHARS = 700
_ITEM = re.compile(r"^### item ([0-9a-f]{32})\b.*$")
_VERDICT = re.compile(r"^verdict:\s*(.*?)\s*$")


def _tag(tags: list[str], prefix: str) -> str | None:
    return next((t[len(prefix) :] for t in tags if t.startswith(prefix)), None)


def write_checklist(dataset_dir: Path, out: Path, *, sample: int, seed: int) -> int:
    """Rows are drawn from `test.jsonl` in stable hash order; returns how many were written."""
    rows = [json.loads(x) for x in (dataset_dir / "test.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    keyed = [(r, _tag(r["tags"], "item:"), _tag(r["tags"], "set:")) for r in rows]
    usable = [(r, k, s) for r, k, s in keyed if k and s in SETS and label_name(s, r["expected"])]
    usable.sort(key=lambda t: hashlib.sha256(f"{seed}:{t[1]}".encode()).hexdigest())
    chosen = usable[:sample]
    lines = ["# S1 ground-truth audit", ""]
    lines.append(f"{len(chosen)} rows of `test.jsonl`, seed {seed}. After `verdict:` write")
    lines += ["`agree`, or `disagree: <label>` with the label you believe is right. Leave a row empty to skip it.", ""]
    for row, key, set_name in chosen:
        name = set_name or ""
        yes, no = label_names(name)
        state = row["state"]
        state = state if len(state) <= MAX_STATE_CHARS else state[:MAX_STATE_CHARS] + "\n[...]"
        lines += [f"### item {key}", "", f"set `{name}`; deterministic label: **{label_name(name, row['expected'])}**"]
        lines += [f"(labels: {yes}, {no})", "", "```", state, "```", "", "verdict: ", ""]
    out.write_text("\n".join(lines), encoding="utf-8")
    return len(chosen)


@dataclass
class AuditResult:
    audited: int = 0
    agreed: int = 0
    disagreed: int = 0
    skipped: int = 0
    invalid: list[str] = field(default_factory=list)
    labels: list[LabelRecord] = field(default_factory=list)

    @property
    def noise(self) -> float | None:
        return self.disagreed / self.audited if self.audited else None

    @property
    def noise_interval(self) -> tuple[float, float]:
        return wilson(self.disagreed, self.audited)


def import_checklist(checklist: Path, dataset_dir: Path, labels_out: Path, *, by: str = "human") -> AuditResult:
    """Appends one `label{source: human:audit}` per disagreement. Agreements add nothing to the label file (the
    deterministic label stands) but count in the noise rate."""
    sets: dict[str, str] = {}
    for line in (dataset_dir / "test.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            tags = json.loads(line)["tags"]
            if (key := _tag(tags, "item:")) and (name := _tag(tags, "set:")):
                sets[key] = name
    result = AuditResult()
    current: str | None = None
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    for line in checklist.read_text(encoding="utf-8").splitlines():
        if match := _ITEM.match(line):
            current = match.group(1)
        elif current and (match := _VERDICT.match(line)):
            key, current, text = current, None, match.group(1)
            if not text:
                result.skipped += 1
            elif key not in sets:
                result.invalid.append(f"{key}: not a row of this data set")
            elif text == "agree":
                result.audited += 1
                result.agreed += 1
            elif text.startswith("disagree:"):
                label = text.split(":", 1)[1].strip()
                try:
                    truth = truth_from_label(sets[key], label)
                except ValueError as exc:
                    result.invalid.append(f"{key}: {exc}")
                    continue
                result.audited += 1
                result.disagreed += 1
                result.labels.append(LabelRecord(key, truth, label, SOURCE, by, stamp))
            else:
                result.invalid.append(f"{key}: expected 'agree' or 'disagree: <label>'")
    append_records([labels_out], result.labels)
    return result
