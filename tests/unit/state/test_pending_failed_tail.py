"""L4-RACE-002 (review fix 3): the tail a run publishes after its push of the unit branch failed holds only what the
forge can trust: the events that reached the branch, the money spent, and the run's end with the reason."""

import json

from l4.state.ledger import parse_ledger_files
from l4.state.pending import failed_push_tail

RUN = "r-20261030T0100Z-0001"


def line(seq: int, kind: str, **data) -> bytes:
    body = {"ts": f"2026-10-30T01:00:{seq:02d}.000000Z", "run_id": RUN, "unit": "openspec:x", "seq": seq, "type": kind}
    return (json.dumps({**body, **data}) + "\n").encode()


LOCAL = [
    line(1, "run.started"),
    line(2, "phase.changed", to="implementing"),
    line(3, "task.done", task="1.1"),
    line(4, "delegate.result", status="answered"),
    line(5, "budget.cost", role="delegate", usd=0.5),
    line(6, "phase.changed", to="in_review"),
    line(7, "lock.released"),
    line(8, "run.finished", exit_code=1),
]


def kinds(data: bytes) -> list[str]:
    return [e["type"] for e in map(json.loads, data.splitlines())]


def test_what_reached_the_branch_the_cost_and_the_end_are_kept_the_rest_is_not():
    pushed = b"".join(LOCAL[:3])
    tail = failed_push_tail(b"".join(LOCAL), pushed, "the push failed: moved")
    assert kinds(tail) == ["run.started", "phase.changed", "task.done", "budget.cost", "lock.released", "run.finished"]
    [finished] = [e for e in map(json.loads, tail.splitlines()) if e["type"] == "run.finished"]
    assert finished["reason"] == "the push failed: moved" and finished["exit_code"] == 1


def test_the_kept_lines_keep_their_numbers_and_read_back_with_the_branch_copy():
    from l4.state.pending import merge_ledgers

    pushed = b"".join(LOCAL[:3])
    tail = failed_push_tail(b"".join(LOCAL), pushed, "r")
    read = parse_ledger_files({f"{RUN}.jsonl": tail})
    assert [e.seq for e in read.events] == [1, 2, 3, 5, 7, 8]  # a gap is fine: a seq only ever grows
    merged = merge_ledgers(parse_ledger_files({f"{RUN}.jsonl": pushed}), read)
    assert [e.seq for e in merged.events] == [1, 2, 3, 5, 7, 8]


def test_a_run_that_never_pushed_publishes_the_cost_and_the_end_only():
    tail = failed_push_tail(b"".join(LOCAL), b"", "r")
    assert kinds(tail) == ["budget.cost", "lock.released", "run.finished"]


def test_an_end_that_reached_the_branch_is_not_rewritten_and_a_torn_last_line_is_skipped():
    pushed = b"".join(LOCAL)
    local = b"".join(LOCAL) + b'{"ts": "2026'
    tail = failed_push_tail(local, pushed, "r")
    assert tail == b"".join(LOCAL)
