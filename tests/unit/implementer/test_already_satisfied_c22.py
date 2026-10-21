"""Contract C22 for the `already-satisfied` commit (the M1.3 merge): like M1.4's red and green, its `task.red_ok` and
`task.done` are written before the commit, name the step base and travel inside the commit; the sha follows in
`task.red_committed` and `task.green_committed`."""

import json

from l4.implementer.loop import run_task

from .conftest import RUN_ID, Bench
from .test_already_satisfied import EXISTING, TASK, step


def test_already_satisfied_events_travel_inside_their_commit_and_the_sha_follows(make_bench):
    bench: Bench = make_bench([step(EXISTING)])
    base = bench.wb.head()
    assert run_task(bench.wb, TASK).status == "done"
    sha = bench.wb.head()
    red_ok, done = bench.events("task.red_ok")[0], bench.events("task.done")[0]
    assert (red_ok["base"], done["base"], done["tdd"]) == (base, base, "already-satisfied")
    assert red_ok["tdd"] == "already-satisfied"  # the trace prints "already satisfied", not "red ok"
    assert "sha" not in red_ok and "sha" not in done
    [red_committed], [green_committed] = bench.events("task.red_committed"), bench.events("task.green_committed")
    assert (red_committed["base"], red_committed["sha"]) == (base, sha)
    assert (green_committed["base"], green_committed["sha"]) == (base, sha)
    ledger = (bench.wb.ref.path.relative_to(bench.wb.worktree) / ".l4" / "ledger" / f"{RUN_ID}.jsonl").as_posix()
    committed = [json.loads(line) for line in bench.wb.git.run("show", f"{sha}:{ledger}").stdout.splitlines()]
    assert {"task.red_ok", "task.done"} <= {e["type"] for e in committed if e.get("task") == TASK.key}
