"""`l4 s1 <export|canary|score|report|audit>` (M16-G11 to G14). Thin: each subcommand calls the module that owns it.

Nothing here sends ground truth to an engine and nothing reads an engine answer except `report`. `score` refuses a
data set that was not exported (no manifest, or files that differ from it): the data set is hashed before any engine
scores it (plan D1).
"""

import json
import os
import shutil
from pathlib import Path

import click

from l4.config.defaults import cache_root
from l4.config.loader import load_config
from l4.config.redaction import load_app_config
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.s1 import audit as audit_mod
from l4.s1 import canary as canary_mod
from l4.s1 import export as export_mod
from l4.s1 import records
from l4.s1 import report as report_mod
from l4.s1 import score as score_mod

USAGE = (
    "usage: l4 s1 export --out DIR [--allow-gaps] | canary [--also-repo P]... [--allow-gaps] | "
    "score --profile P --dataset F --out F [--gate gate.json] | "
    "report ANSWERS... --dataset F [--gate gate.json --profile TUNED] | "
    "audit --dataset DIR [--sample N | --import FILE]"
)
DEFAULT_TARGET = 600


def _usage(message: str = USAGE) -> L4Exit:
    return L4Exit(ExitCode.USAGE_ERROR, message)


def _s1_cache(app: AppContext) -> Path:
    return cache_root(app.environ, repo=app.repo) / "s1"


def run_s1_cli(
    app: AppContext,
    *,
    words: tuple[str, ...] = (),
    out: Path | None = None,
    source: tuple[Path, ...] = (),
    also_repo: tuple[Path, ...] = (),
    seed: int | None = None,
    target: int | None = None,
    min_test: int | None = None,
    allow_gaps: bool = False,
    max_variants: int | None = None,
    test_command: str | None = None,
    profile: str | None = None,
    dataset: Path | None = None,
    max_requests: int | None = None,
    sample: int | None = None,
    import_file: Path | None = None,
    gate: Path | None = None,
) -> ExitCode:
    if not words:
        raise _usage()
    command, rest = words[0], words[1:]
    if command == "export" and not rest:
        return _export(app, out, source, seed, allow_gaps)
    if command == "canary" and not rest:
        return _canary(app, out, also_repo, seed, target, min_test, max_variants, test_command, allow_gaps)
    if command == "score" and not rest:
        return _score(app, profile, dataset, out, max_requests, gate)
    if command == "report" and rest:
        return _report(rest, dataset, out, gate, profile)
    if command == "audit" and not rest:
        return _audit(app, dataset, out, sample, import_file, seed)
    raise _usage()


def _default_sources(app: AppContext) -> list[Path]:
    root = cache_root(app.environ, repo=app.repo)
    found = [root / "s1-calibration.jsonl", root / "s1" / "canary.jsonl", root / "s1" / "audit-labels.jsonl"]
    return [p for p in found if p.exists()]


def _export(
    app: AppContext, out: Path | None, source: tuple[Path, ...], seed: int | None, allow_gaps: bool = False
) -> ExitCode:
    if out is None:
        raise _usage("l4 s1 export needs --out DIR")
    sources = list(source) or _default_sources(app)
    if not sources:
        raise _usage("no calibration files to export: pass --source or run `l4 s1 canary` first")
    truth = export_mod.ground_truth_rows(sources)
    try:
        manifest = export_mod.write_dataset(
            truth, out, seed=canary_mod.DEFAULT_SPLIT_SEED if seed is None else seed, allow_gaps=allow_gaps
        )
    except export_mod.ExportError as exc:
        raise _usage(f"unusable data set, nothing written: {exc}") from None
    counts = manifest["counts"]
    click.echo(f"rows {counts['rows']}; units {counts['units']}; dataset_sha256 {manifest['dataset_sha256']}")
    ingest = {k: v for k, v in counts["ingest"].items() if k.startswith(("rejected", "skipped", "dropped", "legacy"))}
    if ingest:
        click.echo(f"not exported: {json.dumps(ingest, sort_keys=True)}", err=True)
    return ExitCode.OK


def _canary(
    app: AppContext, out: Path | None, also_repo: tuple[Path, ...], seed: int | None, target: int | None,
    min_test: int | None, max_variants: int | None, test_command: str | None, allow_gaps: bool = False,
) -> ExitCode:  # fmt: skip
    repos = [canary_mod.check_repo_allowed(r, app.environ) for r in (app.repo, *also_repo)]
    work = _s1_cache(app) / "canary-work"
    shutil.rmtree(work, ignore_errors=True)
    chosen_seed = canary_mod.DEFAULT_SPLIT_SEED if seed is None else seed
    canaries = [
        canary_mod.Canary(
            repo, cfg=load_config(repo), seed=chosen_seed, work_dir=work / repo.name, redactor=app.redactor,
            test_command=test_command,
        )
        for repo in repos
    ]  # fmt: skip
    quota = canary_mod.Quota(
        target=target or DEFAULT_TARGET, **({"min_test": min_test} if min_test is not None else {}),
        split_seed=chosen_seed,
    )  # fmt: skip
    done = canary_mod.generate(
        canaries, quota, max_variants=max_variants or 6, on_run=lambda line: click.echo(line, err=True)
    )  # fmt: skip
    path = out or _s1_cache(app) / "canary.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(path.name + ".tmp")  # a crash must not leave a truncated canary file
    staged.write_text("", encoding="utf-8")
    records.append_records([staged], list(done.items.values()))
    os.replace(staged, path)
    shutil.rmtree(work, ignore_errors=True)
    by_set: dict[str, dict[str, int]] = {}
    for item in done.items.values():
        label = str(item.expected.get(canary_mod.CLASS_QUESTION[item.question_set]))
        by_set.setdefault(item.question_set, {}).setdefault(label, 0)
        by_set[item.question_set][label] += 1
    click.echo(f"{len(done.items)} items to {path}; classes {json.dumps(by_set, sort_keys=True)}")
    click.echo(f"runs {json.dumps(dict(sorted(done.counts.items())))}")
    if done.gaps:
        message = "quotas not met: " + "; ".join(done.gaps)
        if not allow_gaps:
            # not 1: a data shortfall is not a harness bug and retrying does not fix it (SPEC 2.2)
            raise _usage(f"{message} (the items were written; --allow-gaps accepts them)")
        click.echo(message, err=True)
    return ExitCode.OK


def _verified_dataset(dataset: Path) -> Path:
    try:
        manifest = score_mod.read_manifest(dataset)
    except ValueError as exc:
        raise _usage(str(exc)) from None
    if not dataset.is_file() or manifest is None:
        raise _usage(f"{dataset} was not exported by `l4 s1 export` (no manifest.json beside it)")
    entry = manifest["files"].get(dataset.name)
    recorded = entry.get("sha256") if isinstance(entry, dict) else None
    if recorded != score_mod.file_sha256(dataset):
        raise _usage(f"{dataset.name} differs from the sha256 in its manifest: export it again")
    return dataset


def _require_gate(dataset: Path, split: str, gate: Path | None) -> None:
    """D1: a hosted or remote engine does not see calib or test before the gate of that test split is on record."""
    try:
        recorded = json.loads(gate.read_text(encoding="utf-8")).get("test_sha256") if gate else None
    except (OSError, ValueError, AttributeError):
        recorded = None
    if recorded != score_mod.file_sha256(dataset):
        raise _usage(
            f"{dataset.name} is the {split} split: score it with this engine only after the gate "
            "(pass --gate gate.json of this test split; laya_tune.py gate writes it)"
        )


def _score(
    app: AppContext, profile: str | None, dataset: Path | None, out: Path | None, cap: int | None, gate: Path | None
) -> ExitCode:
    if not profile or dataset is None or out is None:
        raise _usage("l4 s1 score needs --profile, --dataset and --out")
    _verified_dataset(dataset)
    app, cfg = load_app_config(app)
    chosen = cfg.profiles.get(profile)
    if chosen is None or chosen.backend != "system-one":
        raise _usage(f"{profile!r} is not a `backend: system-one` profile of the configuration")
    if chosen.engine != "laya-local" and (split := score_mod.exported_split(dataset)):
        _require_gate(dataset, split, gate)
    summary = score_mod.run_score(
        cfg, profile, dataset, out, redactor=app.redactor, environ=app.environ, max_requests=cap
    )
    click.echo(f"{profile}: asked {summary.asked}, failed {summary.errors}, not asked {summary.skipped} -> {out}")
    return ExitCode.OK


def _report(
    answers: tuple[str, ...], dataset: Path | None, out: Path | None, gate: Path | None, tuned: str | None
) -> ExitCode:
    if dataset is None:
        raise _usage("l4 s1 report needs --dataset")
    try:
        report = report_mod.build_report([Path(a) for a in answers], dataset, gate=gate, tuned=[tuned] if tuned else [])
    except (ValueError, OSError) as exc:
        raise _usage(str(exc)) from None
    text = report_mod.render_markdown(report)
    if out is None:
        click.echo(text)
    else:
        out.write_text(text, encoding="utf-8")
        out.with_suffix(".json").write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        click.echo(f"report -> {out}")
    return ExitCode.OK


def _audit(
    app: AppContext, dataset: Path | None, out: Path | None, sample: int | None, import_file: Path | None,
    seed: int | None,
) -> ExitCode:  # fmt: skip
    if dataset is None:
        raise _usage("l4 s1 audit needs --dataset DIR")
    if import_file is not None:
        labels = out or _s1_cache(app) / "audit-labels.jsonl"
        result = audit_mod.import_checklist(import_file, dataset, labels)
        low, high = result.noise_interval
        click.echo(
            f"audited {result.audited}: {result.agreed} agree, {result.disagreed} disagree "
            f"(noise {result.noise if result.noise is not None else 'n/a'}, 95% Wilson {low:.2f}-{high:.2f}); "
            f"{result.skipped} skipped; labels -> {labels}"
        )
        for problem in result.invalid:
            click.echo(f"invalid: {problem}", err=True)
        return ExitCode.OK
    path = out or dataset / "audit.md"
    count = audit_mod.write_checklist(
        dataset, path, sample=sample or 50, seed=canary_mod.DEFAULT_SPLIT_SEED if seed is None else seed
    )
    click.echo(f"{count} rows -> {path}")
    return ExitCode.OK
