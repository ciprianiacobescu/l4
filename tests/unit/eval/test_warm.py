"""L4-EVAL-019: `l4 eval --warm-cache` is the one path allowed to reach an index, and it does nothing else."""

from pathlib import Path

import pytest
import yaml

from l4.eval.run import Deps, eval_uv_cache
from l4.exitcodes import ExitCode, L4Exit

from ._fakerun import ScriptedRunner
from ._go import go


class Warm:
    def __init__(self, code: int = 0) -> None:
        self.calls: list[tuple[Path, dict[str, str], list[str]]] = []
        self.code = code

    def __call__(self, project: Path, env: dict[str, str]) -> int:
        self.calls.append((project, dict(env), sorted(p.name for p in project.iterdir())))
        return self.code


def test_it_syncs_the_base_project_once_into_the_eval_cache(make_app, seeds_root: Path, tmp_path: Path) -> None:
    warm, scripted = Warm(), ScriptedRunner()
    app = make_app({"L4_CACHE": str(tmp_path / "cache")})
    code = go(app, seeds_root, warm_cache=True, dry_run=False, deps=Deps(warm=warm, runner=scripted))
    assert code == ExitCode.OK and scripted.calls == []
    ((project, env, names),) = warm.calls
    assert "pyproject.toml" in names and "uv.lock" in names
    assert env["UV_CACHE_DIR"] == str(tmp_path / "cache" / "eval" / "uv") == str(eval_uv_cache(app.environ))
    assert not (tmp_path / "out").exists()


def test_it_is_refused_together_with_impl_or_judge(make_app, seeds_root: Path) -> None:
    for kw in ({"impl": ("p1",), "ref_judge": "j1"}, {"judge": ("j1",)}):
        with pytest.raises(L4Exit, match="--warm-cache") as info:
            go(make_app(), seeds_root, warm_cache=True, deps=Deps(warm=Warm()), **kw)
        assert info.value.code == ExitCode.USAGE_ERROR


def test_a_failed_sync_is_a_not_ready_exit(make_app, seeds_root: Path) -> None:
    with pytest.raises(L4Exit, match="uv sync") as info:
        go(make_app(), seeds_root, warm_cache=True, deps=Deps(warm=Warm(code=2)))
    assert info.value.code == ExitCode.DOCTOR_FAILED


def test_a_run_gives_every_cell_a_private_copy_of_the_warmed_cache(make_app, seeds_root: Path, tmp_path: Path) -> None:
    configs: list[dict] = []
    copies: list[bool] = []
    scripted = ScriptedRunner()
    warmed = tmp_path / "cache" / "eval" / "uv"
    (warmed / "wheels-v6").mkdir(parents=True)
    (warmed / "wheels-v6" / "pytest.msgpack").write_text("m")

    def runner(argv, env, cwd, timeout):
        configs.append(yaml.safe_load(Path(argv[argv.index("--config") + 1]).read_text()))
        copies.append((Path(env["L4_CACHE"]) / "eval-uv" / "wheels-v6" / "pytest.msgpack").is_file())
        return scripted(argv, env, cwd, timeout)

    app = make_app({"L4_CACHE": str(tmp_path / "cache")})
    go(
        app, seeds_root, judge=("j1",), units=("add-shelf-code",), out=tmp_path / "o", dry_run=False,
        deps=Deps(runner=runner, version_of=lambda a: "1"),
    )  # fmt: skip
    # inside the cell's own L4_CACHE, so `l4 run`'s preflight accepts it (the shared path was refused, exit 2)
    assert configs[0]["sandbox"]["caches"]["uv"]["path"] == "$L4_CACHE/eval-uv"
    assert copies == [True]
    assert scripted.calls[0]["env"]["L4_CACHE"] != str(tmp_path / "cache")  # the cell's own cache stays private


def test_a_run_without_a_warmed_cache_does_not_create_one(make_app, seeds_root: Path, tmp_path: Path) -> None:
    app = make_app({"L4_CACHE": str(tmp_path / "cache")})
    go(
        app, seeds_root, judge=("j1",), units=("add-shelf-code",), out=tmp_path / "o", dry_run=False,
        deps=Deps(runner=ScriptedRunner(), version_of=lambda a: "1"),
    )  # fmt: skip
    assert not (tmp_path / "cache").exists()  # the operator's real cache is not touched by a run
