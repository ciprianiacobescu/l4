"""L4-PRV-040/041: a key or credential file left by a killed run is removed when the unit's next workbench is built, a
run that ended normally leaves nothing to remove, and the unit's directories are 0700."""

import dataclasses
import stat

from l4.agents.credentials import CREDENTIAL_FILE
from l4.agents.fake import Step
from l4.agents.opencode import CONFIG_DIR
from l4.agents.opencode_provider import KEY_FILE
from l4.implementer import workbench as wbmod
from l4.implementer.tdd import agent_step

from ._env_helpers import TASK
from .conftest import result


def test_a_key_left_by_a_killed_run_is_removed(make_bench):  # SCN-PRV-102
    wb = make_bench([]).wb
    config = wb.agent_tmp / CONFIG_DIR
    config.mkdir()
    (config / KEY_FILE).write_text("sk-left-by-a-killed-run")
    (wb.agent_tmp / CREDENTIAL_FILE).write_text("sk-loader-left-by-a-killed-run")
    other = wb.agent_tmp / "result.json"
    other.write_text("{}")
    again = dataclasses.replace(wb)  # a second workbench for the unit: __post_init__ runs again
    assert not (again.agent_tmp / CONFIG_DIR / KEY_FILE).exists() and not (again.agent_tmp / CREDENTIAL_FILE).exists()
    assert other.exists()  # only the two credential files are removed


def test_a_normal_end_leaves_nothing_to_remove(make_bench):  # SCN-PRV-104
    bench = make_bench([Step(structured=result("green"))])
    wb = bench.wb
    agent_step(wb, "green", TASK, 1, None)  # a step of the fake adapter writes no key file
    assert wbmod.remove_leftover_credentials(wb.agent_tmp) == []
    again = dataclasses.replace(wb)
    assert again.agent_tmp.is_dir() and stat.S_IMODE(again.agent_tmp.stat().st_mode) == 0o700
    assert stat.S_IMODE(again.unit_cache.stat().st_mode) == 0o700
    assert stat.S_IMODE((again.unit_cache / "gate-tmp").stat().st_mode) == 0o700
    wb.reset_agent_tmp()
    assert stat.S_IMODE(wb.agent_tmp.stat().st_mode) == 0o700
