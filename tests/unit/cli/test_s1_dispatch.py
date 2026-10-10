import contextlib
import json
import subprocess
from pathlib import Path

import pytest

from l4 import commands
from l4.cli import main
from l4.s1 import records as r

from ..s1._make import make_item


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    return {
        "L4_CACHE": str(tmp_path / "cache"),
        "HOME": str(tmp_path / "home"),
        "L4_S1_CANARY_ROOTS": str(tmp_path / "ok"),
    }


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    return path


def calibration(tmp_path: Path) -> Path:
    items = [make_item(f"k{n:030d}", unit=f"openspec:u{n}", truth={"tests_ok": n % 2 == 0}) for n in range(30)]
    path = tmp_path / "cal.jsonl"
    r.append_records([path], items)
    return path


def test_s1_subcommands_dispatch(tmp_path: Path, repo: Path, env: dict[str, str], capsys: pytest.CaptureFixture[str]):
    assert commands.HANDLERS["s1"] == "l4.s1.cli:run_s1_cli" and "s1" in commands.OWNING_CHANGE
    cal, out = calibration(tmp_path), tmp_path / "ds"
    base = ["--repo", str(repo)]

    assert main(["s1", "export", "--out", str(out), "--source", str(cal), "--seed", "5", *base], environ=env) == 0
    manifest = json.loads((out / "manifest.json").read_text())
    assert sum(manifest["counts"]["rows"].values()) > 0 and "dataset_sha256" in capsys.readouterr().out

    # report on answers made for this data set; score refuses a data set whose file no longer matches its manifest
    answers = tmp_path / "a.jsonl"
    test_file = out / "test.jsonl"
    from l4.s1 import score

    header = {"schema": score.SCORES_SCHEMA, "kind": "header", "profile": "jev", "engine": "jev", "model": "m",
              "dataset_sha256": score.file_sha256(test_file)}  # fmt: skip
    answers.write_text(json.dumps(header) + "\n")
    report = tmp_path / "report.md"
    ungated = ["s1", "report", str(answers), "--dataset", str(test_file), "--out", str(report), *base]
    assert main(ungated, environ=env) == 2  # D1: nothing is reported on the test split before the gate
    assert "before the gate" in capsys.readouterr().err
    gate = tmp_path / "gate.json"
    gate.write_text(json.dumps({"passed": True, "test_sha256": score.file_sha256(test_file)}))
    assert main([*ungated, "--gate", str(gate)], environ=env) == 0
    assert "# S1 comparison" in report.read_text() and report.with_suffix(".json").exists()
    assert main(["s1", "report", str(answers), *base], environ=env) == 2  # --dataset missing
    test_file.write_text(test_file.read_text() + "\n")
    assert (
        main(
            ["s1", "score", "--profile", "jev", "--dataset", str(test_file), "--out", str(tmp_path / "s.jsonl"), *base],
            environ=env,
        )
        == 2
    )
    assert "differs from the sha256" in capsys.readouterr().err
    stray = tmp_path / "stray.jsonl"
    stray.write_text("{}\n")
    assert (
        main(
            ["s1", "score", "--profile", "jev", "--dataset", str(stray), "--out", str(tmp_path / "s.jsonl"), *base],
            environ=env,
        )
        == 2
    )

    # audit writes a checklist and imports it
    ds2 = tmp_path / "ds2"
    main(["s1", "export", "--out", str(ds2), "--source", str(cal), "--seed", "0", *base], environ=env)
    assert (ds2 / "test.jsonl").read_text().strip(), "this seed puts a unit in the test split"
    checklist = tmp_path / "audit.md"
    assert (
        main(["s1", "audit", "--dataset", str(ds2), "--sample", "3", "--out", str(checklist), *base], environ=env) == 0
    )
    assert main(["s1", "audit", "--dataset", str(ds2), "--import", str(checklist), *base], environ=env) == 0
    assert "audited 0" in capsys.readouterr().out

    # usage errors exit 2
    for argv in (["s1"], ["s1", "frobnicate"], ["s1", "export"], ["s1", "export", "extra", "--out", str(out)]):
        assert main([*argv, *base], environ=env) == 2


def test_canary_refuses_a_repository_outside_the_allow_list(tmp_path: Path, repo: Path, env: dict[str, str], capsys):
    assert main(["s1", "canary", "--repo", str(repo)], environ=env) == 2
    assert "outside the canary allow-list" in capsys.readouterr().err


def test_canary_then_export_end_to_end(tmp_path: Path, env: dict[str, str], capsys: pytest.CaptureFixture[str]):
    from ..evidence._multi import build_repo

    root = tmp_path / "ok"
    root.mkdir()
    build_repo(root / "py_multi")
    argv = ["s1", "canary", "--repo", str(root / "py_multi"), "--seed", "3", "--target", "60", "--min-test", "0"]
    assert main([*argv, "--max-variants", "1"], environ=env) == 0
    canary_file = Path(env["L4_CACHE"]) / "s1" / "canary.jsonl"
    items = r.read_records(canary_file, ("item",))
    assert len(items) >= 60 and all(i.origin == "canary" for i in items if isinstance(i, r.ItemRecord))
    assert not (Path(env["L4_CACHE"]) / "s1" / "canary-work").exists()  # scratch worktrees are gone
    capsys.readouterr()
    out = tmp_path / "ds"
    assert (
        main(["s1", "export", "--out", str(out), "--repo", str(root / "py_multi"), "--allow-gaps"], environ=env) == 0
    )  # default sources; --allow-gaps waives a missing label in calib or test, never an empty split
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["counts"]["origin"] == {"canary": sum(manifest["counts"]["rows"].values())}
    assert set(manifest["counts"]["label_source"]) <= {
        f"deterministic:{c}" for c in ("scope", "diff-coverage", "tests-ran")
    }


def test_canary_exits_nonzero_when_the_quotas_are_not_met(
    tmp_path: Path, env: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    from l4.s1 import canary as canary_mod

    repo = tmp_path / "ok" / "repo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    gaps = ["10 of 500 rows after the class balance (12 items)"]
    monkeypatch.setattr(canary_mod, "generate", lambda *a, **k: canary_mod.Generated(gaps=gaps))
    out = tmp_path / "canary.jsonl"
    argv = ["s1", "canary", "--repo", str(repo), "--out", str(out)]
    assert main(argv, environ=env) == 2  # a data shortfall is not an internal error (SPEC 2.2)
    assert "quotas not met" in capsys.readouterr().err and out.exists()  # the items are still written
    assert main([*argv, "--allow-gaps"], environ=env) == 0
    assert "quotas not met" in capsys.readouterr().err


def test_score_with_a_profile_that_is_not_system_one_is_a_usage_error(
    tmp_path: Path, repo: Path, env: dict[str, str], capsys: pytest.CaptureFixture[str]
):
    out = tmp_path / "ds"
    base = ["--repo", str(repo)]
    assert main(["s1", "export", "--out", str(out), "--source", str(calibration(tmp_path)), *base], environ=env) == 0
    argv = ["s1", "score", "--dataset", str(out / "test.jsonl"), "--out", str(tmp_path / "s.jsonl"), *base]
    assert main([*argv, "--profile", "no-such-profile"], environ=env) == 2
    assert "not a `backend: system-one` profile" in capsys.readouterr().err


def test_export_exits_2_naming_the_split_when_a_split_is_unusable(
    tmp_path: Path, repo: Path, env: dict[str, str], capsys: pytest.CaptureFixture[str]
):
    few = [make_item(f"k{n:030d}", unit=f"openspec:u{n % 2}", truth={"tests_ok": n % 2 == 0}) for n in range(8)]
    cal, out = tmp_path / "few.jsonl", tmp_path / "ds"
    r.append_records([cal], few)
    argv = ["s1", "export", "--repo", str(repo), "--source", str(cal), "--out", str(out)]
    assert main(argv, environ=env) == 2
    assert "split is empty" in capsys.readouterr().err and not out.exists()
    assert main([*argv, "--allow-gaps"], environ=env) == 2  # an empty split is a hard error, gaps allowed or not
    assert "split is empty" in capsys.readouterr().err and not out.exists()


def test_a_hosted_engine_does_not_score_calib_or_test_before_the_gate(
    tmp_path: Path, repo: Path, env: dict[str, str], capsys: pytest.CaptureFixture[str]
):
    from l4.s1 import score

    (repo / ".l4").mkdir()
    (repo / ".l4" / "config.yaml").write_text(
        "profiles:\n  jev:\n    backend: system-one\n    engine: jev\n    api_key_env: TYPESAFE_API_KEY\n"
    )
    out, base = tmp_path / "ds", ["--repo", str(repo)]
    assert main(["s1", "export", "--out", str(out), "--source", str(calibration(tmp_path)), *base], environ=env) == 0
    for split in ("calib", "test"):
        argv = ["s1", "score", "--profile", "jev", "--dataset", str(out / f"{split}.jsonl"), *base]
        argv += ["--out", str(tmp_path / "s.jsonl")]
        assert main(argv, environ=env) == 2
        assert "only after the gate" in capsys.readouterr().err
        wrong = tmp_path / "wrong-gate.json"
        wrong.write_text(json.dumps({"test_sha256": "0" * 64}))
        assert main([*argv, "--gate", str(wrong)], environ=env) == 2
    assert not (tmp_path / "s.jsonl").exists()
    right = tmp_path / "gate.json"
    right.write_text(json.dumps({"test_sha256": score.file_sha256(out / "test.jsonl")}))
    argv = ["s1", "score", "--profile", "jev", "--dataset", str(out / "test.jsonl"), "--gate", str(right), *base]
    assert "only after the gate" not in _stderr_of(argv, env, tmp_path, capsys)


def _stderr_of(argv, env, tmp_path, capsys) -> str:
    """The run past the guard needs a key and a network; whatever it says, it is not the guard's refusal."""
    capsys.readouterr()
    with contextlib.suppress(Exception):
        main([*argv, "--out", str(tmp_path / "s2.jsonl")], environ=env)
    return capsys.readouterr().err


@pytest.mark.parametrize("garbage", ["{not json", "[1, 2]", "", '{"files": []}'])
def test_a_corrupt_manifest_is_a_usage_error_for_score_and_report(
    tmp_path: Path, repo: Path, env: dict[str, str], capsys: pytest.CaptureFixture[str], garbage: str
):
    out = tmp_path / "ds"
    base = ["--repo", str(repo)]
    assert main(["s1", "export", "--out", str(out), "--source", str(calibration(tmp_path)), *base], environ=env) == 0
    (out / "manifest.json").write_text(garbage)
    capsys.readouterr()
    score = ["s1", "score", "--profile", "x", "--dataset", str(out / "test.jsonl"), "--out", str(tmp_path / "s"), *base]
    assert main(score, environ=env) == 2
    assert "manifest" in capsys.readouterr().err
    answers = tmp_path / "a.jsonl"
    answers.write_text("")
    report = ["s1", "report", str(answers), "--dataset", str(out / "test.jsonl"), *base]
    assert main(report, environ=env) == 2  # not "an ordinary file": a corrupt manifest does not lift the gate order
    assert "manifest" in capsys.readouterr().err
