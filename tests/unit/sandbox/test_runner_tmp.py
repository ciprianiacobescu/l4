"""github-parity D10 (L4-GHP-010, SCN-GHP-15): GitHub's `$RUNNER_TEMP` holds the harness's deploy key; no agent or
gate may read it, so it joins the runner's scratch directories that bwrap covers with a tmpfs."""

from pathlib import Path

from l4.sandbox.base import runner_tmp_paths
from l4.sandbox.bwrap import BwrapSandbox

from .test_bwrap_argv import ENV, pairs


def test_runner_temp_is_hidden(tmp_path, make_spec):
    assert runner_tmp_paths({"RUNNER_TEMP": "/home/runner/work/_temp"}) == (Path("/home/runner/work/_temp"),)
    assert runner_tmp_paths({"RUNNER_TEMP": "/home/runner/work/_temp/"}) == (Path("/home/runner/work/_temp"),)
    assert runner_tmp_paths({"RUNNER_TEMP": "relative/tmp"}) == ()  # bwrap's cwd would decide what it means
    assert runner_tmp_paths({"RUNNER_TEMP": ""}) == ()
    both = runner_tmp_paths({"CI_PROJECT_DIR": "/b/g/p", "RUNNER_TEMP": "/r/_temp"})
    assert both == (Path("/b/g/p.tmp"), Path("/r/_temp"))  # GitLab's stays, and both kinds are covered
    temp = tmp_path / "work" / "_temp"
    temp.mkdir(parents=True)
    (temp / "l4-harness-key").write_text("secret")
    for kind in ("agent", "gate"):
        spec = make_spec(kind, runner_tmp=runner_tmp_paths({"RUNNER_TEMP": str(temp)}))
        argv = BwrapSandbox("/usr/bin/bwrap").build_argv(["true"], spec, ENV, None)
        assert (str(temp),) in pairs(argv, "--tmpfs")


def test_the_outcome_record_directory_is_bound_writable_for_a_gate(
    tmp_path, make_spec
):  # detect-test-tamper, fifth review
    records = tmp_path / "records"
    records.mkdir()
    spec = make_spec("gate", record_dir=records)
    argv = BwrapSandbox("/usr/bin/bwrap").build_argv(["true"], spec, ENV, None)
    assert (str(records), str(records)) in pairs(argv, "--bind")
    plain = BwrapSandbox("/usr/bin/bwrap").build_argv(["true"], make_spec("gate"), ENV, None)
    assert (str(records), str(records)) not in pairs(plain, "--bind")
