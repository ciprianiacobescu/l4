"""M1.13 line 27 (W-C6): `scripts/dev/l4_idle.py`, the quiet-window check before a push that starts l4 jobs. A 502
of the proxy is retried and, if it lasts, is "unknown" (exit 2), never "busy" (wave C: idle.py read a 502 as busy)."""

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "dev" / "l4_idle.py"
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def idle():
    spec = importlib.util.spec_from_file_location("l4_idle", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Api:
    """A scripted GitLab: `jobs` per project, the last main commit's age, and `fail` (codes of the next calls)."""

    def __init__(self, idle, *, jobs=(), age_min=60.0, fail=()):
        self.idle, self.jobs, self.age_min, self.fail, self.calls = idle, list(jobs), age_min, list(fail), []

    def __call__(self, path: str):
        self.calls.append(path)
        if self.fail:
            code = self.fail.pop(0)
            if code:
                raise self.idle.ApiError(code, path)
        if "/pipelines?" in path:
            return [{"id": 7}] if self.jobs else []
        if path.endswith("/jobs?per_page=50"):
            return [{"name": n, "status": s, "id": i} for n, s, i in self.jobs]
        if "/repository/commits" in path:
            created = NOW - timedelta(minutes=self.age_min)
            return [{"created_at": created.isoformat(), "short_id": "abc1234"}]
        raise AssertionError(path)


def run(idle, api, **kw):
    sleeps: list[float] = []
    verdict = idle.check(api, now=NOW, sleep=sleeps.append, **kw)
    return verdict, sleeps


def test_no_job_and_an_old_main_commit_is_idle(idle):
    verdict, _ = run(idle, Api(idle))
    assert verdict.state == "idle" and verdict.code == 0


def test_a_running_l4_job_is_busy(idle):
    verdict, _ = run(idle, Api(idle, jobs=[("l4", "running", 5895)]))
    assert verdict.state == "busy" and verdict.code == 1 and "5895" in verdict.text


def test_a_job_that_is_not_the_l4_job_or_is_done_is_not_busy(idle):
    verdict, _ = run(idle, Api(idle, jobs=[("test", "running", 1), ("l4", "success", 2)]))
    assert verdict.state == "idle"


def test_a_main_commit_younger_than_the_quiet_window_is_busy(idle):
    verdict, _ = run(idle, Api(idle, age_min=3.0))
    assert verdict.state == "busy" and "3." in verdict.text


def test_a_502_is_retried_and_the_next_answer_decides(idle):
    api = Api(idle, fail=[502, 502])
    verdict, sleeps = run(idle, api)
    assert verdict.state == "idle" and len(sleeps) == 2 and sleeps[0] < sleeps[1]  # a backoff
    assert api.calls[0] == api.calls[1] == api.calls[2]  # the same call, three times


def test_a_502_that_lasts_is_unknown_never_busy(idle):
    verdict, sleeps = run(idle, Api(idle, fail=[502] * 40), retries=2)
    assert verdict.state == "unknown" and verdict.code == 2 and "502" in verdict.text and len(sleeps) == 2


def test_another_failure_is_unknown_at_once_without_a_retry(idle):
    verdict, sleeps = run(idle, Api(idle, fail=[401]))
    assert verdict.state == "unknown" and verdict.code == 2 and sleeps == []


def test_a_busy_answer_is_not_hidden_by_an_earlier_502(idle):
    verdict, _ = run(idle, Api(idle, fail=[502], jobs=[("l4", "pending", 9)]))
    assert verdict.state == "busy"


def test_the_helper_calls_the_mk_script_and_reads_its_status_from_stderr(idle, tmp_path):
    fake = tmp_path / "mk.sh"
    fake.write_text('#!/bin/sh\necho \'{"message":"vault error"}\'\necho "HTTP 502 GET $2" >&2\nexit 22\n')
    fake.chmod(0o755)
    with pytest.raises(idle.ApiError) as caught:
        idle.mk_get(str(fake))("projects/118")
    assert caught.value.status == 502
    good = tmp_path / "good.sh"
    good.write_text("#!/bin/sh\necho '[1, 2]'\n")
    good.chmod(0o755)
    assert idle.mk_get(str(good))("projects/118") == [1, 2]


def test_main_exit_codes(idle, monkeypatch, capsys):
    monkeypatch.setattr(idle, "mk_get", lambda script=None: Api(idle, jobs=[("l4", "running", 1)]))
    assert idle.main([]) == 1
    assert "busy" in capsys.readouterr().out
    monkeypatch.setattr(idle, "mk_get", lambda script=None: Api(idle, fail=[502] * 99))
    monkeypatch.setattr(idle.time, "sleep", lambda s: None)
    assert idle.main([]) == 2
    assert "unknown" in capsys.readouterr().out
