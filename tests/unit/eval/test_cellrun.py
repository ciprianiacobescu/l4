import json
import subprocess
from pathlib import Path

import yaml

from l4.eval.cellrun import Cell, CellRaw, RunnerOutput, read_ledger, run_cell
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
SECRET = "sk-ant-abcdefghijklmnopqrstuvwx"


class Recorder:
    """An injected runner: records the call, optionally writes into the workspace, returns a canned output."""

    def __init__(self, returncode: int = 0, output: str = "ok", write=None, raises: Exception | None = None) -> None:
        self.calls: list[tuple] = []
        self.returncode, self.output, self.write, self.raises = returncode, output, write, raises

    def __call__(self, argv, env, cwd, timeout):
        self.calls.append((list(argv), dict(env), Path(cwd), timeout))
        if self.write:
            self.write(Path(cwd))
        if self.raises:
            raise self.raises
        return RunnerOutput(self.returncode, self.output)


def _cell_args(seeds_root: Path, tmp_path: Path, **over):
    seeds = load_seed_set(seeds_root)
    args = dict(
        seeds=seeds, base_cfg=BASE, cell_dir=tmp_path / "cell", ref_judge="judge",
        environ={"PATH": "/usr/bin", "HOME": "/h"},
        timeout_s=3000.0, redactor=Redactor({"K": SECRET}), identity=ID, uv_cache=None,
    )  # fmt: skip
    args.update(over)
    return args


def test_a_cell_calls_the_runner_once_with_the_real_command(seeds_root: Path, tmp_path: Path) -> None:
    runner = Recorder()
    raw = run_cell(Cell("implementer", "impl", "add-shelf-code", 0), runner=runner, **_cell_args(seeds_root, tmp_path))
    assert isinstance(raw, CellRaw) and raw.returncode == 0 and raw.invalid is None
    ((argv, env, cwd, timeout),) = runner.calls
    assert argv[1:3] == ["-m", "l4"] and argv[3] == "run"
    assert argv[argv.index("--unit") + 1] == "openspec:add-shelf-code"
    cfg_path = Path(argv[argv.index("--config") + 1])
    assert cfg_path == tmp_path / "cell" / "cfg.yaml"
    assert yaml.safe_load(cfg_path.read_text())["roles"]["implementer"] == ["impl"]
    assert Path(argv[argv.index("--repo") + 1]) == cwd and cwd.parent.parent == tmp_path / "cell"
    assert timeout == 3000.0
    assert raw.wall_s >= 0.0


def test_the_cache_is_private_to_the_cell_and_nothing_else_is_touched(seeds_root: Path, tmp_path: Path) -> None:
    runner = Recorder()
    run_cell(
        Cell("implementer", "impl", "add-shelf-code", 0), runner=runner,
        **_cell_args(seeds_root, tmp_path, environ={"PATH": "/usr/bin", "HOME": "/h", "L4_CACHE": "/real/cache"}),
    )  # fmt: skip
    env = runner.calls[0][1]
    cache = Path(env["L4_CACHE"])
    assert tmp_path / "cell" in cache.parents and env["L4_CACHE"] != "/real/cache"
    assert env["HOME"] == "/h" and env["PATH"] == "/usr/bin"  # the operator's HOME: logins are never copied
    cwd = runner.calls[0][2]
    assert not (cwd / ".l4").exists()  # the config is passed with --config, nothing is written under the repo's .l4


def test_a_timeout_is_invalid_and_keeps_the_log(seeds_root: Path, tmp_path: Path) -> None:
    exc = subprocess.TimeoutExpired(["l4"], 3000, output=f"partial {SECRET}".encode())
    raw = run_cell(
        Cell("implementer", "impl", "add-shelf-code", 0), runner=Recorder(raises=exc),
        **_cell_args(seeds_root, tmp_path),
    )  # fmt: skip
    assert raw.invalid == "cell_timeout" and raw.returncode is None
    assert "partial" in raw.log_text and SECRET not in raw.log_text


def test_the_log_is_redacted(seeds_root: Path, tmp_path: Path) -> None:
    raw = run_cell(
        Cell("implementer", "impl", "add-shelf-code", 0), runner=Recorder(output=f"token {SECRET} end"),
        **_cell_args(seeds_root, tmp_path),
    )  # fmt: skip
    assert SECRET not in raw.log_text and "[REDACTED" in raw.log_text


def test_a_vendor_veto_starts_nothing(seeds_root: Path, tmp_path: Path) -> None:
    base = {"profiles": {**BASE["profiles"], "same": {"adapter": "opencode", "model": "o/b", "vendor": "anthropic"}}}
    runner = Recorder()
    raw = run_cell(
        Cell("implementer", "same", "add-shelf-code", 0), runner=runner,
        **_cell_args(seeds_root, tmp_path, base_cfg=base),
    )  # fmt: skip
    assert raw.invalid == "vendor_veto" and runner.calls == []


def test_a_judge_cell_gets_the_reference_and_its_own_judge(seeds_root: Path, tmp_path: Path) -> None:
    runner = Recorder()
    raw = run_cell(
        Cell("judge", "judge", "add-late-fee", 0), runner=runner, **_cell_args(seeds_root, tmp_path, ref_judge=None)
    )  # fmt: skip
    assert raw.invalid is None
    argv = runner.calls[0][0]
    cfg = yaml.safe_load(Path(argv[argv.index("--config") + 1]).read_text())
    assert cfg["roles"]["judges"] == ["judge"] and cfg["roles"]["implementer"] == ["eval-reference"]
    assert (tmp_path / "cell" / "reference" / "green" / "src" / "billing" / "fees.py").is_file()


def test_outcome_and_ledger_are_read_back(seeds_root: Path, tmp_path: Path) -> None:
    def write(repo: Path) -> None:
        (repo / ".l4-out").mkdir()
        (repo / ".l4-out" / "outcome.json").write_text(json.dumps({"exit_code": 0, "units": []}))
        env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
        branch = "l4/openspec/add-shelf-code"
        rel = "openspec/changes/add-shelf-code/.l4/ledger/r-1.jsonl"
        (repo / "openspec/changes/add-shelf-code/.l4/ledger").mkdir(parents=True)
        (repo / rel).write_text(
            json.dumps({"ts": "2026-10-07T00:00:01Z", "run_id": "r-1", "seq": 1, "type": "run.started"}) + "\n"
            + json.dumps({"ts": "2026-10-07T00:00:02Z", "run_id": "r-1", "seq": 2, "type": "run.finished"}) + "\n"
        )  # fmt: skip
        for args in (["checkout", "-q", "-b", branch], ["add", "-f", rel], ["commit", "-q", "-m", "ledger"],
                     ["push", "-q", "origin", branch]):  # fmt: skip
            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@e.i", *args], cwd=repo, env=env, check=True)

    raw = run_cell(
        Cell("implementer", "impl", "add-shelf-code", 0),
        runner=Recorder(write=write),
        **_cell_args(seeds_root, tmp_path),
    )
    assert raw.outcome_json == {"exit_code": 0, "units": []}
    assert [e["type"] for e in raw.ledger_events] == ["run.started", "run.finished"]


def test_read_ledger_of_an_origin_without_the_branch_is_empty(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", "--bare", str(tmp_path / "o.git")], check=True)
    assert read_ledger(tmp_path / "o.git", "add-shelf-code") == []


def test_a_cell_key_and_directory_name() -> None:
    cell = Cell("judge", "p/one", "add-late-fee", 2)
    assert cell.key == "judge|p/one|add-late-fee|2"
    assert cell.dirname == "judge-p-one-add-late-fee-k2"


def test_a_run_that_pushed_nothing_is_read_from_the_unit_worktree(seeds_root: Path, tmp_path: Path) -> None:
    """A rate-limited first step parks the unit before any push: its ledger exists only in the cell's cache."""

    def write(repo: Path) -> None:
        ledger = tmp_path / "cell" / "cache" / "worktrees" / "shelf-0123456789" / "openspec" / "add-shelf-code"
        ledger = ledger / "openspec" / "changes" / "add-shelf-code" / ".l4" / "ledger"
        ledger.mkdir(parents=True)
        (ledger / "r-9.jsonl").write_text(
            json.dumps({"ts": "2026-10-07T00:00:01Z", "run_id": "r-9", "seq": 1, "type": "availability.limit"}) + "\n"
        )

    raw = run_cell(
        Cell("implementer", "impl", "add-shelf-code", 0), runner=Recorder(write=write),
        **_cell_args(seeds_root, tmp_path),
    )  # fmt: skip
    assert [e["type"] for e in raw.ledger_events] == ["availability.limit"]
