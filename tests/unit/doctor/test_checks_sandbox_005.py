"""SANDBOX-005 (L4-SEC-039): a Go project whose gates.setup has no `go mod download` fails in the gates that follow,
because GOMODCACHE is read-only there and a checksum lookup (GOPATH/pkg/sumdb) cannot write."""

import pytest

from l4.config.schema import L4Config
from l4.doctor import checks_sandbox as sb
from l4.doctor.context import DoctorContext
from l4.doctor.registry import Check, Registry, exit_code, run_checks


def row(repo, setup, files=("go.mod",)):
    for name in files:
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text("module x\n")
    cfg = L4Config.model_validate({"gates": {"setup": list(setup)}})
    ctx = DoctorContext(repo, cfg, {"HOME": str(repo)}, lambda name: None, lambda *a, **k: None, (3, 12, 1))
    registry = Registry()
    registry.register(Check("SANDBOX-005", "go modules", "warn", sb._sandbox_005))
    (result,) = run_checks(ctx, registry=registry)
    return result


def test_a_go_project_without_go_mod_download_in_setup_is_a_warning(tmp_path):
    result = row(tmp_path, ["uv sync"])
    assert result.status == "fail" and result.severity == "warn"
    assert "go mod download" in result.message and "go mod verify" in repr(result)
    assert int(exit_code([result])) == 0


@pytest.mark.parametrize("setup", [["go mod download all && go mod verify"], ["go mod download"]])
def test_setup_with_go_mod_download_passes(tmp_path, setup):
    assert row(tmp_path, setup).status == "pass"


def test_a_go_module_below_the_root_counts_and_a_project_without_go_passes(tmp_path):
    assert row(tmp_path, [], files=("services/api/go.mod",)).status == "fail"
    (tmp_path / "services/api/go.mod").unlink()
    assert row(tmp_path, ["make deps"], files=()).status == "pass"
