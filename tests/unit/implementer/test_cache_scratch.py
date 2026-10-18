"""Review F1 (R3) at workbench level: an agent step works in a private scratch cache that is discarded, and the
verifier builds from a cache of its own that no implementer step touched."""

import dataclasses
from pathlib import Path

from l4.agents.fake import Step
from l4.implementer.tdd import agent_step
from l4.sandbox.caches import SCRATCH_DIR, VERIFY_SCOPE, verifier_caches

from ._env_helpers import TASK
from .conftest import result


def test_an_agent_step_works_in_a_private_scratch_cache_that_is_discarded(make_bench):  # SCN-PRV-110
    bench = make_bench([Step(structured=result("green"))])
    wb = bench.wb
    shared = next(c.path for c in wb.caches if c.env == "UV_CACHE_DIR")
    (shared / "archive-v0" / "abc").mkdir(parents=True)  # what the harness's setup built
    seen: dict[str, object] = {}
    real = bench.adapter.run

    def run(req):
        scratch = Path(req.env["UV_CACHE_DIR"])
        seen["scratch"] = scratch
        (scratch / "archive-v0" / "abc").mkdir(parents=True)  # the reviewer's plant, written where the agent can write
        (scratch / "archive-v0" / "abc" / "zz_marker.pth").write_text("import os\n")
        return real(req)

    bench.adapter.run = run  # type: ignore[method-assign]
    mounts = {c.env: c for c in wb.agent_spec().caches}
    assert mounts["UV_CACHE_DIR"].read_only and mounts["UV_CACHE_DIR"].path == shared
    agent_step(wb, "green", TASK, 1, None)
    scratch = seen["scratch"]
    assert isinstance(scratch, Path) and scratch != shared and wb.agent_tmp in scratch.parents
    assert not (shared / "archive-v0" / "abc" / "zz_marker.pth").exists()  # the shared cache never saw the plant
    assert not (wb.agent_tmp / SCRATCH_DIR).exists()  # discarded after the step


def test_the_verifier_builds_from_a_cache_of_its_own_emptied_each_round(make_bench):  # SCN-PRV-111
    wb = make_bench([]).wb
    mine = {c.env: c.path for c in wb.caches if not c.read_only}
    first = verifier_caches(wb.cfg.sandbox.caches, wb.cache_root, wb.ref.id, wb.repo_key)
    theirs = {c.env: c.path for c in first if not c.read_only}
    assert theirs.keys() == mine.keys()
    for env, path in theirs.items():
        assert path != mine[env] and VERIFY_SCOPE in path.parts and wb.repo_key in path.parts
        assert not (path == mine[env] or mine[env] in path.parents or path in mine[env].parents)
    (theirs["UV_CACHE_DIR"] / "archive-v0").mkdir()
    (theirs["UV_CACHE_DIR"] / "archive-v0" / "stale").write_text("from the last round")
    second = verifier_caches(wb.cfg.sandbox.caches, wb.cache_root, wb.ref.id, wb.repo_key)
    assert list(next(c.path for c in second if c.env == "UV_CACHE_DIR").iterdir()) == []  # emptied
    assert dataclasses.replace(wb, caches=second).caches == second  # a workbench takes them as its own
