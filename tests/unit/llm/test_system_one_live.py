"""M1.5 Exit B, live: a real `laya-serve` answers byte-identically three times and is gone afterwards. Needs
`L4_LIVE=1`, `laya-serve` on PATH and the `typed-decisions` checkpoint in the Hugging Face cache."""

import os
import socket

import httpx
import pytest

from l4.config.defaults import resolve_executable
from l4.llm.system_one import LAYA_MODEL, LayaServe, Question, SystemOneBackend, laya_checkpoint_present
from l4.redact import Redactor

pytestmark = pytest.mark.live
STATE = "Help! Payouts to our customers have been failing since this morning."
ASK = {"q": Question("noul", "Is the sender describing an urgent problem?")}


def test_laya_answers_identically_and_the_process_is_gone_afterwards():
    argv0 = resolve_executable("laya-serve", os.environ)
    if argv0 is None or not laya_checkpoint_present(os.environ, LAYA_MODEL):
        pytest.skip("laya-serve or its checkpoint is missing")
    serve = LayaServe([argv0], os.environ, model=LAYA_MODEL)
    answers, raw = [], []
    with serve as base_url:
        port = int(base_url.rsplit(":", 1)[1])
        assert serve._proc is not None
        pgid = serve._proc.pid  # started with start_new_session: the group leader
        body = {"state": STATE, "model": LAYA_MODEL, "questions": {"q": ASK["q"].wire()}}
        for _ in range(3):  # the bytes the server sent, not only the parsed floats
            raw.append(httpx.post(f"{base_url}/v1/systemone", json=body, timeout=60).content)
        # through the harness's own parser: the real reply carries a `usage` that is not all integers
        with SystemOneBackend(
            "remote", model=LAYA_MODEL, base_url=base_url, redactor=Redactor({}), timeout_s=60
        ) as backend:
            for _ in range(3):
                answers.append(backend.ask(STATE, ASK))
    assert raw[0] == raw[1] == raw[2]
    assert answers[0]["q"] == answers[1]["q"] == answers[2]["q"]
    with socket.socket() as sock:
        assert sock.connect_ex(("127.0.0.1", port)) != 0  # nothing listens any more
    with pytest.raises(ProcessLookupError):
        os.killpg(pgid, 0)  # and no worker of the group is left
