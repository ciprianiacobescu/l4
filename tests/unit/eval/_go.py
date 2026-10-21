from pathlib import Path

from l4.eval.run import Deps, run_eval


def go(app, seeds_root: Path, **kw):
    options = dict(
        impl=(), judge=(), ref_judge=None, units=(), k=1, out=None, cell_timeout="50m", runner=False, dry_run=True,
        resume=False, idle_check=None, idle_wait="30m", warm_cache=False, seeds=seeds_root, compare=None, new=None,
        baseline_dir=None, max_drop=0.2, allow_seed_change=False, require_all=False, as_json=False,
    )  # fmt: skip
    options.update(kw)
    options.setdefault("deps", Deps())
    return run_eval(app, **options)
