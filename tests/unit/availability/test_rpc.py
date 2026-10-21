import sys

from l4.availability.rpc import run_rpc_session

SERVER = """
import json, sys
for line in sys.stdin:
    msg = json.loads(line)
    if "id" in msg and msg["method"] != "silent":
        print(json.dumps({"id": msg["id"], "result": {"echo": msg["method"]}}), flush=True)
    elif "id" not in msg:
        print(json.dumps({"method": "note", "params": {}}), flush=True)
"""


def test_every_request_is_answered_by_id_and_notifications_are_ignored(tmp_path):
    messages = [{"method": "a", "id": 1}, {"method": "initialized"}, {"method": "b", "id": 2}]
    got = run_rpc_session([sys.executable, "-c", SERVER], tmp_path, {}, 10, messages)
    assert got == {1: {"id": 1, "result": {"echo": "a"}}, 2: {"id": 2, "result": {"echo": "b"}}}


def test_an_unanswered_request_is_absent_after_the_timeout(tmp_path):
    messages = [{"method": "a", "id": 1}, {"method": "silent", "id": 2}]
    got = run_rpc_session([sys.executable, "-c", SERVER], tmp_path, {}, 1.0, messages)
    assert set(got) == {1}


def test_a_missing_binary_gives_no_answers(tmp_path):
    assert run_rpc_session([str(tmp_path / "nope")], tmp_path, {}, 1, [{"method": "a", "id": 1}]) == {}


def test_a_child_that_exits_at_once_gives_what_it_said(tmp_path):
    got = run_rpc_session(
        [sys.executable, "-c", 'print(\'{"id": 1, "result": 5}\')'], tmp_path, {}, 5, [{"method": "a", "id": 1}]
    )
    assert got == {1: {"id": 1, "result": 5}}
