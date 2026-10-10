"""The Laya tuning loop on the Mac (M1.6 Stage C): build-items, train, gate.

Runs in the isolated uv project of this directory (`uv run --project scripts/s1 python scripts/s1/laya_tune.py ...`);
torch is imported only inside the commands that need it, so the pure helpers can be tested without it.

Ground truth only. The data set comes from `l4 s1 export`, and every command refuses a manifest that lists a label
source outside the allow-list. No engine answer (Jev's or any other) is read here: the checkpoint is selected by the
final epoch and the gate scores it against the ground-truth labels of `test.jsonl`.
"""

import argparse
import hashlib
import json
import math
import os
import resource
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
VENDOR = HERE / "vendor"

# a copy of l4.s1.export.ALLOWED_SOURCES (tests/unit/s1/test_tune_items.py pins the two together): this script
# runs in an environment that does not have the harness installed
ALLOWED_SOURCES = (
    "deterministic:scope",
    "deterministic:diff-coverage",
    "deterministic:tests-ran",
    "deterministic:traceability",
    "human:verdict",
    "human:audit",
)
BASES = ("typed-decisions", "english", "multilingual")  # sub-directories of the bundle repo (english = repo root)
BUNDLE_REPO = "convaiinnovations/laya"
MIN_ACCURACY = 0.85  # [G]
MAX_ECE = 0.10  # [G]
MIN_NOUL_GAIN = 0.05  # [G] tuned must beat base Laya on the same split
MIN_LABEL_RECALL = 0.80  # [G] every label of a noul or choice question must be found at least this often
SLICE_PREFIXES = ("mutation:", "origin:")
RECORD_NAME = "l4-train.json"
GATE_NAME = "gate.json"  # the gate document, kept in the checkpoint; l4-train.json stores its sha256
ACCEPT_PRECISION = 0.95  # [G] lower Wilson bound for an accept (or reject) threshold
SANITY_QID = "all_passed"  # tests-ok: a state that states its own answer; a wrong answer means a broken engine
SPLITS = ("train", "calib", "test")
Z95 = 1.959964


# ---------------------------------------------------------------- pure helpers (no torch)


def parse_base(spec: str) -> tuple[str, str]:
    """`typed-decisions@<40 hex>` -> (name, revision). A moving ref is refused: the base must be reproducible."""
    name, sep, revision = spec.partition("@")
    if not sep or name not in BASES or len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
        raise ValueError(f"--base must be <{'|'.join(BASES)}>@<40-hex HF commit>, got {spec!r}")
    return name, revision


def gold_probabilities(question: Mapping[str, Any], expected: Any) -> dict[str, dict[str, float]]:
    """The vendored script's gold shape, `{"probabilities": {...}}`, as a one-hot of the exported label."""
    kind, criteria = question["type"], question.get("criteria")
    if kind == "noul":
        if not isinstance(expected, bool):
            raise ValueError(f"a noul label must be a boolean, got {expected!r}")
        return {"probabilities": {"true": float(expected), "false": float(not expected)}}
    if kind == "choice":
        if expected not in (criteria or {}):
            raise ValueError(f"choice label {expected!r} is not one of {list(criteria or {})}")
        return {"probabilities": {key: float(key == expected) for key in criteria}}
    if kind == "score":
        levels = len(criteria) if isinstance(criteria, list) else 4
        if isinstance(expected, bool) or not isinstance(expected, int) or not 0 <= expected < levels:
            raise ValueError(f"score label {expected!r} is not a level of 0..{levels - 1}")
        return {"probabilities": {str(i): float(i == expected) for i in range(levels)}}
    raise ValueError(f"unknown question type {kind!r}")


def check_manifest(data_dir: Path) -> dict[str, Any]:
    """The data set's manifest, or ValueError when it is missing or lists a label source outside the allow-list."""
    path = data_dir / "manifest.json"
    if not path.is_file():
        raise ValueError(f"{data_dir} has no manifest.json: export it with `l4 s1 export`")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    sources = manifest.get("counts", {}).get("label_source", {})
    bad = sorted(set(sources) - set(ALLOWED_SOURCES))
    if bad:
        raise ValueError(f"label source outside the ground-truth allow-list: {', '.join(bad)}")
    return manifest


def check_dataset(data_dir: Path) -> dict[str, Any]:
    """`check_manifest`, and every split file must be the one the manifest hashed: a file edited or swapped after the
    export is refused."""
    manifest = check_manifest(data_dir)
    files = manifest.get("files", {})
    for split in SPLITS:
        recorded = files.get(f"{split}.jsonl", {}).get("sha256")
        path = data_dir / f"{split}.jsonl"
        if recorded is None or not path.is_file() or file_sha256(path) != recorded:
            raise ValueError(f"{path.name} is missing or differs from the sha256 in {data_dir / 'manifest.json'}")
    return manifest


def check_gate_target(record: Mapping[str, Any], manifest: Mapping[str, Any], data_dir: Path) -> None:
    """A checkpoint is gated only on the data set it was trained on: its test split is then held out by construction.
    ValueError otherwise, before anything is scored or recorded."""
    if record.get("dataset_sha256") != manifest.get("dataset_sha256"):
        raise ValueError("the checkpoint was trained on another data set than the one being gated")
    for split in SPLITS:
        if record.get("split_sha256", {}).get(split) != file_sha256(data_dir / f"{split}.jsonl"):
            raise ValueError(f"{split}.jsonl is not the {split} split the checkpoint was trained with")


def apply_temperatures(raw: Sequence[float], low: float, high: float) -> tuple[list[float], list[int]]:
    """What Laya serves for each fitted temperature (it clamps to [low, high]) and the indices of the fits that sit on
    or beyond a bound: those say the calibration split could not support a fit."""
    applied = [min(max(t, low), high) for t in raw]
    return applied, [i for i, t in enumerate(raw) if t <= low or t >= high]


def sanity_failures(
    tuned: Sequence[Mapping[str, Any]], base: Sequence[Mapping[str, Any]], *, minimum: float = MIN_ACCURACY
) -> list[str]:
    """The tests-ok rows are the stated sanity question: the tuned checkpoint must answer them at least as well as base
    Laya and at `minimum`. No rows is a failure too: nothing was measured."""

    def accuracy(rows: Sequence[Mapping[str, Any]]) -> float | None:
        mine = [r for r in rows if r["qid"] == SANITY_QID and r["type"] == "noul"]
        return sum((r["p_true"] >= 0.5) == r["truth"] for r in mine) / len(mine) if mine else None

    got, ref = accuracy(tuned), accuracy(base)
    if got is None:
        return [f"the test split has no {SANITY_QID} rows: the sanity question was not measured"]
    out = []
    if got < minimum:
        out.append(f"sanity question {SANITY_QID}: tuned accuracy {got:.2f} is below {minimum}")
    if ref is not None and got < ref:
        out.append(f"sanity question {SANITY_QID}: tuned accuracy {got:.2f} is below base Laya's {ref:.2f}")
    return out


def wilson_lower(successes: int, n: int, z: float = Z95) -> float:
    if n == 0:
        return 0.0
    p = successes / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - margin) / (1 + z * z / n)


def wilson_threshold(samples: Sequence[tuple[float, bool]], precision: float = ACCEPT_PRECISION) -> float | None:
    """The lowest score t such that the answers scoring >= t have a Wilson lower bound on precision >= `precision`."""
    for t in sorted({score for score, _ in samples}):
        chosen = [ok for score, ok in samples if score >= t]
        if wilson_lower(sum(chosen), len(chosen)) >= precision:
            return t
    return None


def fit_thresholds(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per question: `accept` (noul: p_true at or above it is a safe true; others: confidence of the argmax) and, for
    noul, `reject` (p_true at or below it is a safe false). None where the calibration split cannot support one."""
    by_qid: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        by_qid.setdefault(row["qid"], []).append(row)
    out: dict[str, dict[str, Any]] = {}
    for qid, group in sorted(by_qid.items()):
        kind = group[0]["type"]
        if kind == "noul":
            accept = wilson_threshold([(r["p_true"], r["truth"]) for r in group])
            mirror = wilson_threshold([(1 - r["p_true"], not r["truth"]) for r in group])
            reject = None if mirror is None else round(1 - mirror, 10)
        else:
            accept = wilson_threshold([(r["confidence"], r["correct"]) for r in group])
            reject = None
        out[qid] = {"type": kind, "accept": accept, "reject": reject, "n": len(group)}
    return out


def default_cache() -> Path:
    """$L4_CACHE/s1/bases, else $XDG_CACHE_HOME/l4/s1/bases, else ~/.cache/l4/s1/bases (L4-CFG-005): base weights are
    never downloaded into the repository."""
    root = os.environ.get("L4_CACHE") or str(Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "l4")
    return Path(root) / "s1" / "bases"


def write_atomic(path: Path, text: str) -> None:
    """Same directory, then rename: a crash leaves the old file or the new one, never half of it."""
    staged = path.with_name(path.name + ".tmp")
    staged.write_text(text, encoding="utf-8")
    os.replace(staged, path)


def checkpoint_files(root: Path) -> dict[str, str]:
    """sha256 of every file under a checkpoint directory except its own record and gate document: what a gate
    vouches for. A symlink is refused (it could point anywhere)."""
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"{path.relative_to(root)} is a symlink: a checkpoint holds only regular files")
        if path.is_file() and path not in (root / RECORD_NAME, root / GATE_NAME):
            out[path.relative_to(root).as_posix()] = file_sha256(path)
    return out


def checkpoint_drift(root: Path, record: Mapping[str, Any]) -> list[str]:
    """Files that changed, vanished or appeared since `train` recorded them."""
    recorded, now = record.get("files") or {}, checkpoint_files(root)
    out = [
        f"{name} differs from the sha256 train recorded"
        for name in sorted(recorded)
        if name in now and now[name] != recorded[name]
    ]
    out += [f"{name} was recorded by train and is gone" for name in sorted(set(recorded) - set(now))]
    out += [f"{name} is in the checkpoint but was not recorded by train" for name in sorted(set(now) - set(recorded))]
    return out


def _by_slice(cases: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], list[bool]]:
    """(slice tag, qid) -> correctness of the noul and choice cases carrying a `mutation:` or `origin:` tag."""
    out: dict[tuple[str, str], list[bool]] = {}
    for case in cases:
        if case.get("correct") is None:
            continue
        for tag in case["tags"]:
            if tag.startswith(SLICE_PREFIXES):
                out.setdefault((tag, case["qid"]), []).append(bool(case["correct"]))
    return out


def shortcut_failures(
    tuned: Sequence[Mapping[str, Any]], base: Sequence[Mapping[str, Any]], *, min_recall: float = MIN_LABEL_RECALL
) -> list[str]:
    """Overall accuracy and per-question minimums hide a checkpoint that learned the canary templates: right on every
    synthetic mutation, wrong on the real untouched code. So (1) on every `mutation:` and `origin:` slice present,
    whatever its size, tuned accuracy must be at least base Laya's; (2) every label of a noul or choice question must
    be recalled at `min_recall` (a class-skewed win cannot pass). Cases are `EvalResult.to_json()["cases"]`."""
    out: list[str] = []
    base_slices = _by_slice(base)
    for key, hits in sorted(_by_slice(tuned).items()):
        reference = base_slices.get(key)
        if reference and sum(hits) / len(hits) < sum(reference) / len(reference):
            out.append(
                f"slice {key[0]} on {key[1]}: tuned accuracy {sum(hits) / len(hits):.2f} (n={len(hits)}) is below "
                f"base Laya's {sum(reference) / len(reference):.2f} (n={len(reference)})"
            )
    labels: dict[tuple[str, str], list[bool]] = {}
    for case in tuned:
        if case.get("correct") is not None:
            labels.setdefault((case["qid"], json.dumps(case["expected"])), []).append(bool(case["correct"]))
    for (qid, label), hits in sorted(labels.items()):
        if sum(hits) / len(hits) < min_recall:
            out.append(
                f"question {qid}, label {label}: recall {sum(hits) / len(hits):.2f} (n={len(hits)}) is below {min_recall}"
            )
    return out


def policy_qids(policy: Mapping[str, Any]) -> list[str]:
    return sorted({rule["slice"]["qid"] for rule in policy["rules"]})


def improves(base_noul_accuracy: float | None, tuned_noul_accuracy: float | None) -> bool:
    if base_noul_accuracy is None or tuned_noul_accuracy is None:
        return False
    return tuned_noul_accuracy - base_noul_accuracy >= MIN_NOUL_GAIN - 1e-9


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _peak_rss_gb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9, 2)  # bytes on macOS


# ---------------------------------------------------------------- commands that need torch / laya


def _vendored() -> Any:
    sys.path.insert(0, str(VENDOR))
    import laya_finetune_mps  # type: ignore[import-not-found]

    return laya_finetune_mps


def fetch_base(spec: str, cache: Path) -> Path:
    """Download one bundle sub-directory at its pinned revision; returns the checkpoint directory."""
    from huggingface_hub import snapshot_download

    name, revision = parse_base(spec)
    pattern = "*" if name == "english" else f"{name}/*"
    root = Path(snapshot_download(BUNDLE_REPO, revision=revision, allow_patterns=[pattern], local_dir=str(cache)))
    return root if name == "english" else root / name


def build_items(data_dir: Path, split: str, base_dir: Path, *, max_rows: int | None = None, seed: int = 0) -> list[Any]:
    """Training items of one split. Refuses a manifest with a label source outside the allow-list."""
    import random

    from laya.agent import _fix_tokenizer_config
    from transformers import AutoTokenizer

    check_dataset(data_dir)
    rows = read_rows(data_dir / f"{split}.jsonl")
    if max_rows is not None and len(rows) > max_rows:
        rows = random.Random(seed).sample(rows, max_rows)
    ft = _vendored()
    _fix_tokenizer_config(str(base_dir))
    tokenizer = AutoTokenizer.from_pretrained(base_dir / "tokenizer")
    cfg = {**json.loads((base_dir / "rl_agent_config.json").read_text()), "max_len": 1024, "head_max_len": 256}
    items = []
    for row in rows:
        for qid, question in row["questions"].items():
            gold = gold_probabilities(question, row["expected"][qid])
            item = ft.build_training_item(tokenizer, cfg, row["state"], question, gold)
            if item is not None:
                items.append({**item, "qid": qid})
    return items


def refit_temperatures(ckpt: Path, calib_items: Sequence[Any], device: Any) -> list[float]:
    """One raw temperature per question type on the calibration split (the vendored `fit_temperature`, which clamps
    to [0.1, 10]; `train` then applies Laya's own range)."""
    import torch
    from laya.common import build_model
    from safetensors.torch import load_file
    from transformers import AutoTokenizer

    ft = _vendored()
    cfg = json.loads((ckpt / "rl_agent_config.json").read_text())
    tokenizer = AutoTokenizer.from_pretrained(ckpt / "tokenizer")
    model = build_model(cfg, encoder_dir=ckpt / "encoder")
    model.load_state_dict(load_file(str(ckpt / "model.safetensors")), strict=True)
    model.float().to(device).eval()
    groups: list[list[Any]] = [[] for _ in range(3)]
    with torch.no_grad():
        for item in calib_items:
            ids, attention, positions, mask, _target, qtype = ft.collate([item], tokenizer.pad_token_id)
            logits, _ = model(
                ids.to(device), attention.to(device), positions.to(device), mask.to(device), qtype.to(device)
            )
            groups[item["qtype"]].append((logits[0, : len(item["markers"])].cpu(), item["target"]))
    del model
    return [ft.fit_temperature(group) if group else 1.0 for group in groups]


def _agent_rows(agent: Any, rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The calibration rows `fit_thresholds` reads: the checkpoint's own answers against the exported labels."""
    out: list[dict[str, Any]] = []
    for row in rows:
        answers = agent.predict(row["state"], row["questions"])["answers"]
        for qid, truth in row["expected"].items():
            answer, kind = answers[qid], row["questions"][qid]["type"]
            if kind == "noul":
                out.append({"qid": qid, "type": kind, "p_true": answer["noul"], "truth": bool(truth)})
                continue
            probabilities = answer["probabilities"]
            predicted = max(probabilities, key=probabilities.__getitem__)
            out.append({"qid": qid, "type": kind, "confidence": answer["answer_confidence"],
                        "correct": predicted == str(truth)})  # fmt: skip
    return out


def train(args: argparse.Namespace) -> int:
    import torch

    data_dir, out = Path(args.data), Path(args.out)
    manifest = check_dataset(data_dir)
    name, revision = parse_base(args.base)
    started = time.time()
    base_dir = fetch_base(args.base, Path(args.cache))
    ft = _vendored()
    device = ft.choose_device(args.device)
    torch.manual_seed(args.seed)
    train_items = build_items(data_dir, "train", base_dir, max_rows=args.max_rows, seed=args.seed)
    calib_items = build_items(data_dir, "calib", base_dir)
    out.mkdir(parents=True, exist_ok=True)
    items_path = out / "train_items.pt"
    torch.save(train_items, items_path)
    run_args = argparse.Namespace(
        epochs=args.epochs, micro_batch=args.micro_batch, grad_accum=args.grad_accum, calib_max=0,
        no_checkpointing=False, output_dir=str(out),
    )  # fmt: skip
    ft.train(run_args, str(base_dir), str(items_path), device)  # calib_max=0: the vendored in-train fit is unused
    from laya.agent import TEMP_MAX, TEMP_MIN

    raw_temperatures = refit_temperatures(out, calib_items, device)
    temperatures, on_bound = apply_temperatures(raw_temperatures, TEMP_MIN, TEMP_MAX)
    cfg = json.loads((out / "rl_agent_config.json").read_text())
    cfg["temperature"] = temperatures
    cfg.pop("temperature_by_options", None)
    write_atomic(out / "rl_agent_config.json", json.dumps(cfg, indent=2))
    _drop_scratch(out)
    import laya

    agent = laya.load(str(out), device=str(device))
    thresholds = fit_thresholds(_agent_rows(agent, read_rows(data_dir / "calib.jsonl")))
    write_atomic(out / "thresholds.json", json.dumps(thresholds, indent=1, sort_keys=True) + "\n")
    record = {
        "schema": "l4/s1-train@1",
        "base": {"name": name, "revision": revision, "repo": BUNDLE_REPO},
        "dataset_sha256": manifest.get("dataset_sha256"),
        "split_sha256": {s: file_sha256(data_dir / f"{s}.jsonl") for s in ("train", "calib", "test")},
        "label_sources": manifest["counts"]["label_source"],
        "seed": args.seed,
        "hyperparameters": {
            "epochs": args.epochs, "micro_batch": args.micro_batch, "grad_accum": args.grad_accum,
            "max_rows": args.max_rows, "train_items": len(train_items), "calib_items": len(calib_items),
            "encoder_lr": 2.5e-5, "head_lr": 1e-4, "selection": "final-epoch",
        },
        "temperatures": temperatures,
        "temperatures_raw": raw_temperatures,
        "temperatures_on_bound": on_bound,
        "thresholds": "thresholds.json",
        "wall_seconds": round(time.time() - started, 1),
        "peak_rss_gb": _peak_rss_gb(),
        "device": str(device),
        "files": checkpoint_files(out),
        "gate": {"passed": False, "ran": False},
    }  # fmt: skip
    write_atomic(out / RECORD_NAME, json.dumps(record, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: record[k] for k in ("wall_seconds", "peak_rss_gb", "temperatures")}))
    return 0


def _drop_scratch(out: Path) -> None:
    import shutil

    shutil.rmtree(out / "checkpoint_latest", ignore_errors=True)
    (out / "train_items.pt").unlink(missing_ok=True)


class _AgentRunner:
    """laya.evals runner over one checkpoint directory (T1-eval: `laya-evals run --model` takes only registry names)."""

    def __init__(self, agent: Any):
        self.agent = agent

    def predict(self, state: Any, questions: Mapping[str, Any], model: str | None = None, min_confidence: Any = None):
        return self.agent.predict(state, dict(questions))


def evaluate(model_dir: Path, dataset: Path, *, device: str) -> Any:
    import laya
    from laya import evals

    runner = _AgentRunner(laya.load(str(model_dir), device=device))
    data = evals.Dataset.from_jsonl(str(dataset))
    config = {"dataset": str(dataset), "model": str(model_dir), "device": device,
              "dataset_sha256": evals.file_fingerprint(str(dataset))}  # fmt: skip
    return evals.evaluate(runner, data, evaluators=evals.default_evaluators(), config=config)


def _load_agent(model_dir: Path, device: str) -> Any:
    import laya

    return laya.load(str(model_dir), device=device)


def train_record_failures(record: Mapping[str, Any]) -> list[str]:
    """Facts of the training run that void a pass: a fit on Laya's temperature bound, a subset of the train split."""
    out = [
        f"temperature[{i}] sits on Laya's clamp ({record['temperatures_raw'][i]:.2f}): the confidences are uncalibrated"
        for i in record.get("temperatures_on_bound", ())
    ]
    cap = record.get("hyperparameters", {}).get("max_rows")
    if cap is not None:
        out.append(f"trained on a subset of the train split (--max-rows {cap})")
    if "temperatures_raw" not in record:
        out.append("l4-train.json has no raw temperatures: it was not written by this version of train")
    return out


def accuracy_floors(overall: Mapping[str, float]) -> dict[str, float]:
    """MIN_ACCURACY applies to every accuracy the run produced: choice rows no longer take the noul floor away."""
    return {key: MIN_ACCURACY for key in ("noul_accuracy", "choice_accuracy") if key in overall}


def record_gate(ckpt: Path, record: dict[str, Any], document: Mapping[str, Any], json_path: str | Path) -> None:
    """Write the gate document to `json_path` and into the checkpoint, and bind the recorded flag to it: the record
    stores the document's sha256, so a boolean flipped by hand in `l4-train.json` no longer matches `gate.json`
    (`checkpoint_problem`, `deploy_checkpoint.sh`)."""
    text = json.dumps(document, indent=1, sort_keys=True) + "\n"
    write_atomic(ckpt / GATE_NAME, text)
    write_atomic(Path(json_path), text)
    record["gate"] = {
        "ran": True, "passed": document["passed"], "dataset_sha256": document.get("dataset_sha256"),
        "test_sha256": document.get("test_sha256"), "failures": document.get("failures", []),
        "document_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }  # fmt: skip
    write_atomic(ckpt / RECORD_NAME, json.dumps(record, indent=1, sort_keys=True) + "\n")


def gate(args: argparse.Namespace) -> int:
    ckpt, data_dir = Path(args.ckpt), Path(args.data)
    manifest = check_dataset(data_dir)
    record_path = ckpt / RECORD_NAME
    record = json.loads(record_path.read_text(encoding="utf-8"))
    check_gate_target(record, manifest, data_dir)
    if drift := checkpoint_drift(ckpt, record):
        raise ValueError("the checkpoint changed after train: " + "; ".join(drift))
    from laya import _eval_policy
    from laya.evals_cli import _check_thresholds

    base_name, base_revision = record["base"]["name"], record["base"]["revision"]
    base_dir = fetch_base(f"{base_name}@{base_revision}", Path(args.cache))  # the base train started from, not a path
    test = data_dir / "test.jsonl"
    policy = _eval_policy.load_policy(args.gate_policy)
    tuned = evaluate(ckpt, test, device=args.device)
    base = evaluate(base_dir, test, device=args.device)
    sanity_rows = [
        {
            **r,
            "questions": {SANITY_QID: r["questions"][SANITY_QID]},
            "expected": {SANITY_QID: r["expected"][SANITY_QID]},
        }
        for r in read_rows(test)
        if SANITY_QID in r["expected"]
    ]
    failures = _check_thresholds(tuned.overall, accuracy_floors(tuned.overall), {"ece": MAX_ECE})
    failures += _eval_policy.check_policy(tuned, policy)
    base_noul, tuned_noul = base.overall.get("noul_accuracy"), tuned.overall.get("noul_accuracy")
    if not improves(base_noul, tuned_noul):
        failures.append(f"tuned noul accuracy {tuned_noul} does not beat base {base_noul} by {MIN_NOUL_GAIN}")
    failures += shortcut_failures(tuned.to_json()["cases"], base.to_json()["cases"])
    failures += train_record_failures(record)
    failures += sanity_failures(*(_agent_rows(_load_agent(d, args.device), sanity_rows) for d in (ckpt, base_dir)))
    if drift := checkpoint_drift(ckpt, record):  # evaluating must not have written into the checkpoint either
        failures.append("the gate run changed the checkpoint directory: " + "; ".join(drift))
    passed = not failures
    document = {
        "schema": "l4/s1-gate@1",
        "passed": passed,
        "failures": failures,
        "dataset_sha256": manifest.get("dataset_sha256"),
        "checkpoint_id": ckpt.name,
        "checkpoint_sha256": record["files"]["model.safetensors"],
        "test_sha256": file_sha256(test),
        "thresholds": {
            "min_accuracy": MIN_ACCURACY,
            "max_ece": MAX_ECE,
            "min_noul_gain": MIN_NOUL_GAIN,
            "min_label_recall": MIN_LABEL_RECALL,
        },  # fmt: skip
        "tuned": tuned.to_json(),
        "base": {"overall": base.overall, "slices": base.slices},
    }
    record_gate(ckpt, record, document, args.json)
    for line in failures:
        print("FAIL: " + line, file=sys.stderr)
    print(f"gate {'passed' if passed else 'failed'}: tuned {tuned.overall} vs base {base.overall}")
    return 0 if passed else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    items = sub.add_parser("build-items", help="build the training items of a split and print their count")
    items.add_argument("--data", required=True)
    items.add_argument("--split", default="train")
    items.add_argument("--base", required=True, help="typed-decisions@<40-hex HF commit>")
    items.add_argument("--cache", default=str(default_cache()))
    tr = sub.add_parser("train", help="fine-tune on the train split, refit temperatures and thresholds on calib")
    tr.add_argument("--data", required=True)
    tr.add_argument("--base", required=True)
    tr.add_argument("--out", required=True)
    tr.add_argument("--cache", default=str(default_cache()))
    tr.add_argument("--epochs", type=int, default=2)
    tr.add_argument("--micro-batch", type=int, default=1)
    tr.add_argument("--grad-accum", type=int, default=16)
    tr.add_argument("--max-rows", type=int, default=None)
    tr.add_argument("--seed", type=int, default=1606)
    tr.add_argument("--device", choices=["auto", "mps", "cpu"], default="auto")
    gt = sub.add_parser("gate", help="score the checkpoint (and the base) on test.jsonl against the ground truth")
    gt.add_argument("--ckpt", required=True)
    gt.add_argument("--data", required=True)
    gt.add_argument(
        "--cache", default=str(default_cache()), help="where the base is fetched (at the revision train used)"
    )
    gt.add_argument("--gate-policy", default=str(HERE / "gates.json"))
    gt.add_argument("--json", required=True)
    gt.add_argument("--device", default="mps")
    args = parser.parse_args(argv)
    try:
        if args.command == "build-items":
            base_dir = fetch_base(args.base, Path(args.cache))
            built = build_items(Path(args.data), args.split, base_dir)
            print(f"{len(built)} items from {args.split}")
            return 0
        return train(args) if args.command == "train" else gate(args)
    except (ValueError, OSError) as exc:  # json.JSONDecodeError is a ValueError
        print(f"laya_tune: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
