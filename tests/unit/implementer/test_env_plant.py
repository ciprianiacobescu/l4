"""implementer-2 (L4-SEC-036, SCN-SEC-88): a file a green agent step plants in `.venv` site-packages must not decide
the verdict. Ported from the review's test_verify_impl2_venv.py, which asserted the opposite (green passed on the plant
with the stub unimplemented)."""

import sys

from l4.agents.fake import Step
from l4.implementer.tdd import run_green, run_red

from ._env_helpers import MKREALVENV, PLUGIN, PTH, SITE, TASK
from .conftest import STUB, red_step, result


def test_a_pth_planted_by_green_does_not_make_green_pass(make_bench, tmp_path):
    script = tmp_path / "mkrealvenv.py"
    script.write_text(MKREALVENV)
    green = Step(writes={f"{SITE}/zz_l4.pth": PTH, f"{SITE}/l4plant.py": PLUGIN}, structured=result("green"))
    bench = make_bench([red_step(), green], setup=[f"{sys.executable} {script}"])
    wb = bench.wb
    red = run_red(wb, TASK, attempt=1)
    assert red.status == "ok", red.reason
    out = run_green(wb, TASK, red, attempt=1)
    assert out.status != "ok"  # the stub is still a stub: the plant did not turn the failure into a pass
    assert (wb.worktree / "src/pytdd/pricing.py").read_text() == STUB
    assert "feat(" not in " ".join(bench.subjects())  # no green commit
    assert not (wb.worktree / SITE / "zz_l4.pth").exists() and not (wb.worktree / SITE / "l4plant.py").exists()
    violations = [e for e in bench.events("guard.violation") if e.get("rule") == "environment"]
    assert [v["path"] for v in violations if v["path"].endswith("zz_l4.pth")]
    assert any(".venv" in e["dirs"] for e in bench.events("env.rebuilt"))
