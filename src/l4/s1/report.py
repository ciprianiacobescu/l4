"""Comparison report (M16-G13): per engine and per question, accuracy, ECE, Brier, n and a Wilson interval.

The data set's `expected` is read here as a reference to score against and is never written anywhere. Answer files
must have been produced on the same data set bytes (sha256), or the report refuses. Confidence is
`answer_confidence` (the probability the engine puts on its own answer), not the server's `confidence` field.
"""

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from l4.llm.system_one import Answer
from l4.s1.score import REV, SCORES_SCHEMA, exported_split, file_sha256, read_rows
from l4.s1.stats import wilson

REPORT_SCHEMA = "l4/s1-report@1"
ECE_BINS = 15


def ece(pairs: Sequence[tuple[float, bool]], bins: int = ECE_BINS) -> float:
    """Expected calibration error: equal-width bins over the answer confidence."""
    if not pairs:
        return 0.0
    grouped: dict[int, list[tuple[float, bool]]] = defaultdict(list)
    for confidence, correct in pairs:
        grouped[min(int(confidence * bins), bins - 1)].append((confidence, correct))
    total = len(pairs)
    return sum(
        len(g) / total * abs(sum(c for _, c in g) / len(g) - sum(conf for conf, _ in g) / len(g))
        for g in grouped.values()
    )


def _brier_noul(p: float, y: bool) -> float:
    return (p - (1.0 if y else 0.0)) ** 2


def _brier_multi(probs: Mapping[str, float], truth: str) -> float:
    return sum((p - (1.0 if k == truth else 0.0)) ** 2 for k, p in probs.items()) + (1.0 if truth not in probs else 0.0)


def _avg(a: Mapping[str, float], b: Mapping[str, float]) -> dict[str, float]:
    return {k: (a.get(k, 0.0) + b.get(k, 0.0)) / 2 for k in sorted({*a, *b})}


def _outcome(answer: Answer, expected: Any, rev: Answer | None) -> tuple[bool, float | None, float | None]:
    """(correct, confidence, brier) of one answer against the reference; the average of both orders when `rev`."""
    if answer.kind == "noul":
        assert answer.p_true is not None
        y = bool(expected)
        return (answer.p_true >= 0.5) == y, answer.answer_confidence, _brier_noul(answer.p_true, y)
    probs = dict(answer.probabilities or {})
    if rev is not None and rev.probabilities:
        probs = _avg(probs, dict(rev.probabilities))
    if not probs:
        return answer.predicted == expected, None, None
    best = max(probs, key=lambda k: probs[k])
    truth = str(expected)
    predicted: Any = best if answer.kind == "choice" else int(best)
    return predicted == expected, probs[best], _brier_multi(probs, truth)


def _metrics(outcomes: Sequence[tuple[bool, float | None, float | None]]) -> dict[str, Any]:
    n = len(outcomes)
    correct = sum(o[0] for o in outcomes)
    low, high = wilson(correct, n)
    confident = [(c, ok) for ok, c, _ in outcomes if c is not None]
    briers = [b for _, _, b in outcomes if b is not None]
    return {
        "n": n,
        "accuracy": correct / n if n else None,
        "wilson95": [round(low, 4), round(high, 4)],
        "ece": round(ece(confident), 4) if confident else None,
        "brier": round(sum(briers) / len(briers), 4) if briers else None,
    }


def _read_scores(path: Path) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    header: dict[str, Any] = {}
    rows: dict[int, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        data = json.loads(line)
        if data.get("schema") != SCORES_SCHEMA:
            raise ValueError(f"{path.name} is not an {SCORES_SCHEMA} file")
        if data["kind"] == "header":
            header = data
        else:
            rows[int(data["row"])] = data
    return header, rows


def _tag(tags: Sequence[str], prefix: str) -> str | None:
    return next((t[len(prefix) :] for t in tags if t.startswith(prefix)), None)


def build_report(
    answers: Sequence[Path], dataset: Path, *, gate: Path | None = None, tuned: Sequence[str] = ()
) -> dict[str, Any]:
    """`tuned` names the profiles that serve a tuned checkpoint: their numbers are only reported next to a
    `gate.json` of the same test split (whether it passed or failed), and are cross-checked against it (M16-G19).
    The same holds for every engine on the calib or test file of an `l4 s1 export` (D1: the gate comes first)."""
    rows = read_rows(dataset)
    sha = file_sha256(dataset)
    if tuned and gate is None:
        raise ValueError("a tuned checkpoint is compared only after its gate: pass gate.json (laya_tune.py gate)")
    if gate is None and (split := exported_split(dataset)):
        raise ValueError(
            f"{dataset.name} is the {split} split of an export: no engine is reported on it before the gate "
            "(pass gate.json of the test split, TypeSafe MCA 2.3(b))"
        )
    gate_doc = _read_gate(gate, sha) if gate is not None else None
    engines: dict[str, Any] = {}
    tuned = list(tuned)
    for path in answers:
        header, scored = _read_scores(path)
        if header.get("dataset_sha256") != sha:
            raise ValueError(f"{path.name} was scored on another data set than {dataset.name}")
        if header.get("checkpoint_sha256"):  # the file says it was made by a tuned checkpoint: no name can hide that
            _require_gate_for(path.name, header, gate_doc)
            if "gate_passed" in header and header["gate_passed"] is not bool(gate_doc and gate_doc.get("passed")):
                raise ValueError(f"{path.name}: its gate_passed={header['gate_passed']} differs from gate.json")
            if header["profile"] not in tuned:
                tuned.append(header["profile"])
        canonical: dict[str, list] = defaultdict(list)
        maes: dict[str, list[float]] = defaultdict(list)
        averaged: dict[str, list] = defaultdict(list)
        sliced: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
        errors = 0
        for index, line in scored.items():
            if line.get("error") or "answers" not in line:
                errors += 1
                continue
            row = rows[index]
            set_name = _tag(row["tags"], "set:") or "unknown"
            for qid, expected in row["expected"].items():
                raw = line["answers"].get(qid)
                if raw is None:
                    continue
                answer = Answer.from_json(raw)
                rev_raw = line["answers"].get(qid + REV)
                rev = Answer.from_json(rev_raw) if rev_raw else None
                key = f"{set_name}/{qid}"
                one = _outcome(answer, expected, None)
                canonical[key].append(one)
                if answer.kind == "score" and answer.score is not None:
                    maes[key].append(abs(answer.score - expected))
                if answer.kind == "choice" and rev is not None:
                    averaged[key].append(_outcome(answer, expected, rev))
                for prefix in ("origin:", "mutation:", "project:"):
                    if (value := _tag(row["tags"], prefix)) is not None:
                        sliced[prefix + value][key].append(one)
        engines[header["profile"]] = {
            "engine": header.get("engine"),
            "model": header.get("model"),
            **({"gate_passed": header["gate_passed"]} if "gate_passed" in header else {}),
            "rows_scored": len(scored),
            "rows_failed": errors,
            "questions": {
                key: {
                    "canonical": _metrics(canonical[key])
                    | ({"score_mae": round(sum(maes[key]) / len(maes[key]), 4)} if maes[key] else {}),
                    "averaged": _metrics(averaged[key]) if averaged[key] else None,
                }
                for key in sorted(canonical)
            },
            "slices": {
                tag: {key: _metrics(v) for key, v in sorted(per.items())} for tag, per in sorted(sliced.items())
            },
        }  # fmt: skip
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "dataset_sha256": sha,
        "dataset": dataset.name,
        "engines": engines,
    }
    if gate_doc is not None:
        report["gate"] = {"passed": bool(gate_doc.get("passed")), "failures": gate_doc.get("failures", []),
                          "cross_check": _cross_check(engines, rows, gate_doc, tuned)}  # fmt: skip
    return report


def _require_gate_for(name: str, header: Mapping[str, Any], gate: Mapping[str, Any] | None) -> None:
    """D1's order: a tuned checkpoint's numbers appear only next to the gate record of that very checkpoint, trained
    on the data set the gate ran on."""
    if gate is None:
        raise ValueError(f"{name} was made by a tuned checkpoint: compare it only after its gate (pass --gate)")
    if gate.get("checkpoint_sha256") != header["checkpoint_sha256"]:
        raise ValueError(f"{name} was made by a different checkpoint than the one gate.json gated")
    trained_on = header.get("checkpoint_dataset_sha256")
    if not trained_on or gate.get("dataset_sha256") != trained_on:
        raise ValueError(f"{name}: the checkpoint was not trained on the data set its gate ran on")


def _read_gate(path: Path, dataset_sha: str) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read gate.json: {exc}") from None
    if doc.get("test_sha256") != dataset_sha:
        raise ValueError("gate.json was produced on another data set than the one being compared")
    return doc


CROSS_CHECK_TOLERANCE = 0.01
GATE_METRIC = {"noul": ("accuracy", "noul_accuracy"), "choice": ("accuracy", "choice_accuracy"),
               "score": ("score_mae", "score_mae")}  # fmt: skip


def _cross_check(
    engines: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], gate: Mapping[str, Any], tuned: Sequence[str]
) -> str:
    """The tuned profiles' canonical numbers against laya-evals' own metric code in gate.json (the independent
    oracle). The averaged choice column has no laya-evals counterpart and is not checked."""
    if not tuned:
        return "no tuned engine compared"
    kinds = {qid: spec["type"] for row in rows for qid, spec in row["questions"].items()}
    by_qid = gate.get("tuned", {}).get("slices", {}).get("qid", {})
    problems = []
    for profile in tuned:
        if profile not in engines:
            raise ValueError(f"tuned profile {profile!r} has no answers file")
        compared = 0
        for key, data in engines[profile]["questions"].items():
            qid = key.rsplit("/", 1)[1]
            mine_key, theirs_key = GATE_METRIC[kinds[qid]]
            mine, theirs = data["canonical"].get(mine_key), by_qid.get(qid, {}).get(theirs_key)
            if mine is None or theirs is None:
                continue
            compared += 1
            if abs(mine - theirs) > CROSS_CHECK_TOLERANCE:
                problems.append(f"{profile} {qid} {theirs_key}: report {mine:.3f}, gate.json {theirs:.3f}")
        if not compared:
            raise ValueError(f"nothing of {profile!r} could be cross-checked against gate.json: no metric in common")
    if problems:
        raise ValueError("the report disagrees with gate.json: " + "; ".join(problems))
    return "ok"


def _fmt(value: Any) -> str:
    return "-" if value is None else f"{value:.3f}" if isinstance(value, float) else str(value)


def render_markdown(report: Mapping[str, Any]) -> str:
    out = [f"# S1 comparison on `{report['dataset']}`", ""]
    gate = report.get("gate")
    if gate and not gate["passed"]:  # first, before anything a reader could stop at
        out += ["**GATE FAILED: the tuned checkpoint did not pass the laya-evals gate. It is not deployable; its "
                "numbers below are for comparison only.**", ""]  # fmt: skip
        out += [f"* gate failure: {failure}" for failure in gate.get("failures", [])]
        out += [""] if gate.get("failures") else []
    out += [f"dataset sha256 `{report['dataset_sha256']}`", ""]
    out.append("Scored against ground truth only. Engine answers were never used as labels (TypeSafe MCA 2.3(b)).")
    if gate:
        check = "cross-check against laya-evals ok" if gate["cross_check"] == "ok" else gate["cross_check"]
        out += ["", f"Tuned checkpoint gate: {'passed' if gate['passed'] else 'FAILED'}; {check}."
                + ("" if gate["passed"] else " Not deployable.")]  # fmt: skip
    for profile, data in report["engines"].items():
        out += ["", f"## {profile} ({data['engine']}, {data['model']})", ""]
        out += [f"{data['rows_scored']} rows scored, {data['rows_failed']} failed.", ""]
        out += [
            "| question | n | accuracy | 95% Wilson | ECE | Brier | averaged acc |",
            "|---|---|---|---|---|---|---|",
        ]
        for key, m in data["questions"].items():
            c, a = m["canonical"], m["averaged"]
            low, high = c["wilson95"]
            out.append(
                f"| {key} | {c['n']} | {_fmt(c['accuracy'])} | {low:.2f}-{high:.2f} | {_fmt(c['ece'])} | "
                f"{_fmt(c['brier'])} | {_fmt(a['accuracy']) if a else '-'} |"
            )
        if data["slices"]:
            out += ["", "Slices (canonical, accuracy and n):", ""]
            for tag, per in data["slices"].items():
                cells = ", ".join(f"{k.split('/', 1)[1]} {_fmt(m['accuracy'])} (n={m['n']})" for k, m in per.items())
                out.append(f"* `{tag}`: {cells}")
    return "\n".join(out) + "\n"
