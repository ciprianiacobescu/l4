import os
import shlex
import shutil
import socket
import time
from pathlib import Path

import pytest

from l4.config.schema import E2eGate
from l4.exitcodes import ExitCode, L4Exit
from l4.gates.e2e import SNAPSHOT_RELPATH, e2e_configured, launcher_command, run_e2e

from .._web_helpers import PY, e2e_config, free_port, stage


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def gone(pid: int, within: float = 5.0) -> bool:
    end = time.time() + within
    while time.time() < end:
        if not alive(pid):
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def bench(make_bench):  # noqa: F811
    port = free_port()
    bench = make_bench([], e2e=e2e_config(port))
    stage(bench.wb.worktree)
    bench.port = port
    return bench


def test_server_and_tests_share_one_spawn_and_group_is_killed(bench):
    wb = bench.wb
    began = time.time()
    run = run_e2e(wb)
    assert time.time() - began < 60  # a server helper that survived its server would hold the gate's pipes for 120 s
    assert run.gate.status == "pass", run.gate.reason
    assert run.report is not None and run.report.executed == 1
    assert [c.status for c in run.report.tests.values()] == ["passed"]  # the test reached the server: one namespace
    finished = [e for e in bench.events("gate.finished") if e["name"] == "e2e"]
    assert len(finished) == 1 and finished[0]["exit_code"] == 0 and finished[0]["tests"] == 1
    server = int((wb.worktree / ".l4-out/serve.pid").read_text())
    child = int((wb.worktree / ".l4-out/child.pid").read_text())
    assert gone(server) and gone(child)  # the whole process group, not just the server
    with socket.socket() as sock:  # and the port is free again
        assert sock.connect_ex(("127.0.0.1", bench.port)) != 0


def test_never_ready_is_internal_error(bench):
    wb = bench.wb
    wb.cfg.gates.e2e.serve.command = f"{PY} -c 'import time; time.sleep(120)'"
    wb.cfg.gates.e2e.serve.timeout = "1s"
    began = time.time()
    with pytest.raises(L4Exit) as err:
        run_e2e(wb)
    assert err.value.code == ExitCode.INTERNAL_ERROR and "not ready" in str(err.value)
    assert time.time() - began < 15
    (event,) = [e for e in bench.events("gate.finished") if e["name"] == "e2e"]
    assert event["exit_code"] == 97


def test_a_server_that_exits_early_is_internal_error_at_once(bench):
    wb = bench.wb
    wb.cfg.gates.e2e.serve.command = f"{PY} -c 'raise SystemExit(4)'"
    began = time.time()
    with pytest.raises(L4Exit) as err:
        run_e2e(wb)
    assert err.value.code == ExitCode.INTERNAL_ERROR
    assert time.time() - began < 10


def test_snapshot_written(bench):
    wb = bench.wb
    run = run_e2e(wb)
    assert 'data-testid="item-count"' in run.snapshot_text


def test_snapshot_is_capped_at_200_kb_and_never_stale(bench):
    wb = bench.wb
    (wb.worktree / "app.py").write_text(
        "import http.server, sys\n"
        "class H(http.server.BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        body = b'x' * 300000\n"
        "        self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers()\n"
        "        self.wfile.write(body)\n"
        "    def log_message(self, *a): pass\n"
        "http.server.ThreadingHTTPServer(('127.0.0.1', int(sys.argv[1])), H).serve_forever()\n"
    )
    (wb.worktree / "e2e/test_smoke.py").write_text("def test_ok():\n    pass\n")
    run = run_e2e(wb)
    assert run.snapshot_text is not None and len(run.snapshot_text) == 200 * 1024
    # a later run that serves nothing must not report the old page
    wb.cfg.gates.e2e.serve.command = f"{PY} -c 'import time; time.sleep(120)'"
    wb.cfg.gates.e2e.serve.timeout = "1s"
    with pytest.raises(L4Exit):
        run_e2e(wb)
    assert not (wb.worktree / SNAPSHOT_RELPATH).exists()


def test_a_failing_e2e_test_is_a_failed_gate_with_its_report_not_an_internal_error(bench):
    wb = bench.wb
    (wb.worktree / "e2e/test_smoke.py").write_text(
        "import os, urllib.request\n\n\ndef test_wrong():\n"
        "    page = urllib.request.urlopen(os.environ['L4_E2E_BASE_URL'] + '/').read().decode()\n"
        "    assert 'items: 9' in page\n"
    )
    run = run_e2e(wb)
    assert run.gate.status == "fail" and run.gate.exit_code == 1
    assert run.report is not None and run.report.ids_with("failed")


def test_it_serves_and_tests_the_worktree_it_is_given(bench, tmp_path: Path):
    other = tmp_path / "base-worktree"
    stage(other)
    bench.wb.git.at(other).run("init", "-q")  # the base tree is a checkout of the repository
    (other / "e2e/test_smoke.py").write_text("def test_base():\n    pass\n")
    run = run_e2e(bench.wb, other, name="e2e-base")
    assert run.gate.status == "pass"
    assert (other / ".l4-out/e2e.xml").is_file() and (other / ".l4-out/serve.pid").is_file()
    assert not (bench.wb.worktree / ".l4-out/serve.pid").exists()  # the unit's own tree was not touched
    assert any(e["name"] == "e2e-base" for e in bench.events("gate.finished"))


def test_missing_expected_test_fails_the_gate(bench):
    run = run_e2e(bench.wb, must_contain=["e2e.test_smoke::test_generated_not_there"])
    assert run.gate.status == "fail" and "expected tests missing" in run.gate.reason


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"reports": []}, "reports must name"),
        ({"format": "playwright-json"}, "not supported yet"),
        ({"command": ""}, "must all be set"),
    ],
)
def test_misconfiguration_is_a_usage_error_before_anything_runs(bench, change, message):
    for key, value in change.items():
        setattr(bench.wb.cfg.gates.e2e, key, value)
    with pytest.raises(L4Exit, match=message) as err:
        run_e2e(bench.wb)
    assert err.value.code == ExitCode.USAGE_ERROR
    assert not bench.events("gate.finished") or all(e["name"] != "e2e" for e in bench.events("gate.finished"))


def test_launcher_command_is_one_shlex_line_with_the_isolated_interpreter():
    gate = E2eGate.model_validate(e2e_config(4321) | {"command": "pytest -k 'a b' e2e"})
    parts = shlex.split(launcher_command(gate, "L4_E2E_BASE_URL"))
    assert parts[:2] == [PY, "-I"] and parts[2].endswith("e2e_launch.py")
    assert parts[parts.index("--serve") + 1] == f"{PY} serve.py 4321"
    assert parts[parts.index("--timeout") + 1] == "20"
    assert parts[parts.index("--") + 1 :] == ["pytest", "-k", "a b", "e2e"]
    assert not e2e_configured(__import__("l4.config.schema", fromlist=["L4Config"]).L4Config())


def test_a_project_command_that_exits_97_is_a_failed_gate_not_an_internal_error(bench):
    wb = bench.wb
    wb.cfg.gates.e2e.command = f"{PY} -c 'raise SystemExit(97)'"
    run = run_e2e(wb)
    assert run.gate.status == "fail" and run.gate.exit_code == 97


def test_a_snapshot_replaced_by_a_symlink_is_not_read(bench, tmp_path: Path):
    wb = bench.wb
    secret = tmp_path / "auth.json"
    secret.write_text("HOST SECRET")
    (wb.worktree / "e2e/test_smoke.py").write_text(
        "import os\n\n\ndef test_swap():\n"
        "    os.unlink('.l4-out/e2e/page.html')\n"
        f"    os.symlink({str(secret)!r}, '.l4-out/e2e/page.html')\n"
    )
    run = run_e2e(wb)
    assert run.gate.status == "pass" and run.snapshot_text is None


def test_a_symlinked_out_dir_is_refused_before_anything_is_deleted(bench, tmp_path: Path):
    wb = bench.wb
    outside = tmp_path / "outside"
    (outside / "e2e").mkdir(parents=True)
    victim = outside / "e2e" / "page.html"
    victim.write_text("host file")
    shutil.rmtree(wb.worktree / ".l4-out", ignore_errors=True)
    (wb.worktree / ".l4-out").symlink_to(outside)
    with pytest.raises(L4Exit) as err:
        run_e2e(wb)
    assert err.value.code == ExitCode.INTERNAL_ERROR and victim.read_text() == "host file"


def test_a_test_cannot_forge_the_not_ready_marker(bench):
    wb = bench.wb
    wb.cfg.gates.e2e.command = (
        f"{PY} -c \"import pathlib, sys; pathlib.Path('.l4-out/e2e/not-ready').write_text('97'); sys.exit(97)\""
    )
    run = run_e2e(wb)  # not ServerNotReady
    assert run.gate.status == "fail" and run.gate.exit_code == 97
    assert not (wb.worktree / ".l4-out/e2e/not-ready").exists()


def test_a_missing_e2e_executable_is_a_usage_error_not_a_traceback(bench):
    wb = bench.wb
    wb.cfg.gates.e2e.command = "no-such-e2e-tool --flag"
    with pytest.raises(L4Exit) as err:
        run_e2e(wb)
    assert err.value.code == ExitCode.USAGE_ERROR and "cannot be started" in str(err.value)
