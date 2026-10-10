"""The warmed uv cache reaches a cell as a private copy inside the cell's own `L4_CACHE` (review of M1.14).

Before: every cell's config named the shared `<L4_CACHE>/eval/uv` while the child ran with `L4_CACHE=<cell>/cache`, so
`l4 run`'s preflight refused the config ("the path must stay inside the runner cache", exit 2) before any agent ran,
and every live cell scored `fail`. The integration test could not see it: its stand-in runner replaced the whole
`sandbox` section, `caches` included."""

import os
from pathlib import Path

import yaml

from l4.config.loader import load_config
from l4.config.preflight import preflight_run_config
from l4.context import AppContext
from l4.eval.cellrun import Cell, RunnerOutput, run_cell
from l4.eval.seeds import load_seed_set
from l4.eval.workspace import Identity
from l4.redact import Redactor

ID = Identity("t", "t@example.invalid")
BASE = {
    "profiles": {
        "impl": {"adapter": "opencode", "model": "opencode/a", "vendor": "acme"},
        "judge": {"adapter": "claude-code", "vendor": "anthropic"},
    }
}


class Recorder:
    def __init__(self, write=None) -> None:
        self.calls: list[tuple] = []
        self.write = write

    def __call__(self, argv, env, cwd, timeout):
        self.calls.append((list(argv), dict(env), Path(cwd)))
        if self.write:
            self.write(Path(env["L4_CACHE"]))
        return RunnerOutput(0, "ok")


def _warmed(tmp_path: Path) -> Path:
    """A stand-in for `<L4_CACHE>/eval/uv` after `l4 eval --warm-cache`, with uv's absolute symlinks from a wheel
    entry to its unpacked archive, and one planted symlink that leaves the cache."""
    shared = tmp_path / "operator-cache" / "eval" / "uv"
    archive = shared / "archive-v0" / "abc123"
    (archive / "pytest").mkdir(parents=True)
    (archive / "pytest" / "__init__.py").write_text("# pytest\n")
    wheel = shared / "wheels-v6" / "pypi" / "pytest"
    wheel.mkdir(parents=True)
    (wheel / "9.1.1-py3-none-any.msgpack").write_bytes(b"\x81meta")
    os.symlink(archive, wheel / "9.1.1-py3-none-any")  # absolute, as uv writes it
    secret = tmp_path / "home" / ".ssh" / "id_ed25519"
    secret.parent.mkdir(parents=True)
    secret.write_text("PRIVATE KEY\n")
    os.symlink(secret, shared / "planted")
    os.symlink(shared / "wheels-v6", shared / "wheels-v6" / "loop")  # a link to its own ancestor
    return shared


def _listing(root: Path) -> list[str]:
    """Every entry under `root`, links not followed (the planted loop would never end)."""
    out = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        out += [str((Path(directory) / name).relative_to(root)) for name in (*dirs, *files)]
    return sorted(out)


def _run(seeds_root: Path, tmp_path: Path, shared: Path | None, runner: Recorder) -> None:
    run_cell(
        Cell("implementer", "impl", "add-shelf-code", 0), seeds=load_seed_set(seeds_root), base_cfg=BASE,
        cell_dir=tmp_path / "cell", ref_judge="judge", runner=runner,
        environ={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path / "home"), "L4_CACHE": str(tmp_path / "operator-cache")},
        timeout_s=60.0, redactor=Redactor({}), identity=ID, uv_cache=None if shared is None else str(shared),
    )  # fmt: skip


def _cell_cfg(runner: Recorder) -> tuple[Path, dict]:
    argv = runner.calls[0][0]
    path = Path(argv[argv.index("--config") + 1])
    return path, yaml.safe_load(path.read_text())


def test_the_rendered_cell_passes_the_preflight_of_l4_run(seeds_root: Path, tmp_path: Path) -> None:
    runner = Recorder()
    _run(seeds_root, tmp_path, _warmed(tmp_path), runner)
    cfg_path, _ = _cell_cfg(runner)
    argv, env, cwd = runner.calls[0]
    app = AppContext(cwd, cfg_path, "human", 0, "r-20261007T1200Z-abcd", env, Redactor({}))
    preflight_run_config(app, load_config(cwd, config_path=cfg_path))  # raised L4Exit(2) before the fix


def test_the_cell_gets_a_private_copy_of_the_warmed_cache(seeds_root: Path, tmp_path: Path) -> None:
    shared = _warmed(tmp_path)
    before = _listing(shared)

    def agent_writes(cell_cache: Path) -> None:  # what a cell's `uv sync` or a hostile agent may write
        uv = cell_cache / "eval-uv"
        (uv / "archive-v0" / "abc123" / "pytest" / "__init__.py").write_text("poisoned\n")
        (uv / "new-entry").write_text("x")

    runner = Recorder(write=agent_writes)
    _run(seeds_root, tmp_path, shared, runner)
    _, cfg = _cell_cfg(runner)
    env = runner.calls[0][1]
    uv_path = cfg["sandbox"]["caches"]["uv"]["path"]
    assert str(shared) not in uv_path and str(tmp_path / "operator-cache") not in yaml.safe_dump(cfg)
    copy = Path(uv_path.replace("$L4_CACHE", env["L4_CACHE"]))
    assert Path(env["L4_CACHE"]) in copy.parents
    entry = copy / "wheels-v6" / "pypi" / "pytest" / "9.1.1-py3-none-any"
    assert entry.is_dir() and not entry.is_symlink()  # dereferenced: nothing links back to the shared cache
    assert (entry / "pytest" / "__init__.py").read_text() == "# pytest\n"
    assert (copy / "wheels-v6" / "pypi" / "pytest" / "9.1.1-py3-none-any.msgpack").read_bytes() == b"\x81meta"
    assert not (copy / "planted").exists()  # a link that leaves the shared cache is not followed
    assert not (copy / "wheels-v6" / "loop").exists()
    assert not any(p.is_symlink() for p in copy.rglob("*"))
    # the cell never wrote the shared cache
    assert _listing(shared) == before
    assert (shared / "archive-v0" / "abc123" / "pytest" / "__init__.py").read_text() == "# pytest\n"


def test_a_cold_shared_cache_gives_the_cell_an_empty_private_one(seeds_root: Path, tmp_path: Path) -> None:
    runner = Recorder()
    _run(seeds_root, tmp_path, tmp_path / "operator-cache" / "eval" / "uv", runner)
    cfg_path, cfg = _cell_cfg(runner)
    assert cfg["sandbox"]["caches"]["uv"]["path"].startswith("$L4_CACHE/")
    assert not (tmp_path / "operator-cache").exists()  # the operator's real cache is not created or touched
