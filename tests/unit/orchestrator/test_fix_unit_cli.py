"""A fix unit is run through its parent: `l4 run` never selects one, and `--unit` naming one is a usage error."""

import json

from l4.cli import main

from ..conftest import UNIT
from ..implementer.conftest import green_step, red_step
from .conftest import new_origin_main

FIX_UNIT = "add-discount-codes-fix-1"


def put_fix_unit_on_main(tdd, raw) -> None:
    fix = tdd.repo / "openspec" / "changes" / FIX_UNIT
    (fix / ".l4").mkdir(parents=True)
    (fix / "tasks.md").write_text("## 1. Fix\n\n- [x] 1.1 something (F-aaaaaaaa)\n")
    marker = {"schema": "l4/fix-unit@1", "parent": UNIT, "round": 1, "findings": ["F-aaaaaaaa"], "chores": []}
    (fix / ".l4" / "fix.json").write_text(json.dumps(marker))
    new_origin_main(tdd, raw, {})


def test_run_unit_naming_a_fix_unit_exits_2(run_l4, tdd_repo, raw):
    put_fix_unit_on_main(tdd_repo, raw)
    run = run_l4([], f"--unit=openspec:{FIX_UNIT}", unit=False)
    assert run.code == 2 and run.adapter.requests == []
    assert not (tdd_repo.cache / "units" / "openspec" / FIX_UNIT).exists()  # no lease, no worktree


def test_l4_run_without_a_unit_leaves_the_fix_unit_alone(run_l4, tdd_repo, raw, capsys):
    put_fix_unit_on_main(tdd_repo, raw)
    capsys.readouterr()
    main(["plan", "--json", "--repo", str(tdd_repo.repo)], environ=tdd_repo.environ)
    plan = {u["unit"]: u for u in json.loads(capsys.readouterr().out)["units"]}
    assert plan[f"openspec:{FIX_UNIT}"]["next_action"] == "none"
    assert plan[f"openspec:{FIX_UNIT}"]["reason"] == f"fix unit of {UNIT}: run the parent"
    assert plan[UNIT]["next_action"] == "implement"
    run = run_l4([red_step(), green_step()], unit=False)
    assert run.code == 0 and [u["unit"] for u in run.outcome["units"]] == [UNIT]  # only the parent was selected
