"""W-D2: a cancelled CI job must stop `l4 run` (SPEC 2.3 L4-CLI-003). The process-wide cancel flag, its signal handlers
and the job-alive watchdog."""

import os
import signal
import threading

import pytest

from l4 import cancel
from l4.cancel import RunCancelled


@pytest.fixture(autouse=True)
def _clean_flag():
    cancel.reset()
    yield
    cancel.reset()


def test_a_fresh_process_is_not_cancelled():
    assert not cancel.is_cancelled()
    cancel.check()  # no raise


def test_check_raises_once_cancelled_and_carries_the_signal():
    cancel.request(signal.SIGTERM)
    assert cancel.is_cancelled()
    with pytest.raises(RunCancelled) as raised:
        cancel.check()
    assert raised.value.signum == signal.SIGTERM
    assert not isinstance(raised.value, Exception)  # a cleanup `except Exception` must never swallow a cancel


def test_run_cancelled_is_not_an_exception_subclass():
    assert issubclass(RunCancelled, BaseException)
    assert not issubclass(RunCancelled, Exception)


def test_the_signal_handler_raises_the_first_time_and_ignores_later_ones():
    with cancel.handlers():
        with pytest.raises(RunCancelled):
            signal.raise_signal(signal.SIGTERM)
        assert cancel.is_cancelled()
        signal.raise_signal(signal.SIGTERM)  # cleanup is running: the second is a no-op
        signal.raise_signal(signal.SIGHUP)


def test_handlers_are_restored_afterwards():
    before = signal.getsignal(signal.SIGTERM)
    with cancel.handlers():
        assert signal.getsignal(signal.SIGTERM) is not before
    assert signal.getsignal(signal.SIGTERM) is before


def test_handlers_do_nothing_off_the_main_thread():
    seen: list[object] = []

    def work() -> None:
        with cancel.handlers():
            seen.append(signal.getsignal(signal.SIGTERM))

    thread = threading.Thread(target=work)
    thread.start()
    thread.join()
    assert seen == [signal.SIG_DFL] or seen == [signal.getsignal(signal.SIGTERM)]


def test_exit_code_of_a_cancel_is_the_cancelled_code():
    assert RunCancelled(signal.SIGTERM).exit_code == 16


# --- the job watchdog -------------------------------------------------------------------------------------------

ENV = {"GITLAB_CI": "true", "CI_JOB_TOKEN": "tok", "CI_API_V4_URL": "https://forge.test/api/v4"}


def test_no_watchdog_outside_gitlab_ci():
    assert cancel.job_alive_verdict({}, fetch=lambda url, token: pytest.fail("no request")) is True
    assert cancel.job_alive_verdict({"CI_JOB_TOKEN": "x"}, fetch=lambda url, token: pytest.fail("no request")) is True


def test_a_running_job_is_alive():
    assert cancel.job_alive_verdict(ENV, fetch=lambda url, token: (200, {"status": "running"})) is True


def test_a_canceled_job_is_dead():
    assert cancel.job_alive_verdict(ENV, fetch=lambda url, token: (200, {"status": "canceled"})) is False
    assert cancel.job_alive_verdict(ENV, fetch=lambda url, token: (200, {"status": "canceling"})) is False


@pytest.mark.parametrize("status", [401, 403])
def test_a_dead_job_token_means_dead(status):
    assert cancel.job_alive_verdict(ENV, fetch=lambda url, token: (status, {})) is False


@pytest.mark.parametrize("status", [404, 500, 502])
def test_other_statuses_fail_open(status):
    assert cancel.job_alive_verdict(ENV, fetch=lambda url, token: (status, {})) is True


def test_a_network_error_fails_open():
    def boom(url, token):
        raise OSError("unreachable")

    assert cancel.job_alive_verdict(ENV, fetch=boom) is True


def test_the_token_goes_to_fetch_not_into_the_url():
    seen = []

    def spy(url, token):
        seen.append((url, token))
        return 200, {"status": "running"}

    cancel.job_alive_verdict(ENV, fetch=spy)
    assert seen == [("https://forge.test/api/v4/job", "tok")]


def test_a_gone_session_leader_is_dead():
    assert cancel.session_alive(sid=os.getpid()) is True  # we lead our own session in that case: trivially alive
    assert cancel.session_alive(sid=_dead_pid()) is False


def test_a_session_leader_we_may_not_signal_is_alive(monkeypatch):
    def deny(pid, sig):
        raise PermissionError

    monkeypatch.setattr(os, "kill", deny)
    assert cancel.session_alive(sid=1) is True


def _dead_pid() -> int:
    import subprocess

    child = subprocess.Popen(["true"])
    child.wait()
    return child.pid


def test_the_watchdog_calls_on_dead_once_when_the_job_dies():
    dead = threading.Event()
    answers = iter([True, True, False])
    stop = cancel.start_watchdog(
        ENV, poll_s=0.01, alive=lambda env: next(answers, False), on_dead=dead.set, grace_s=None, sid=None
    )
    assert dead.wait(2)
    stop()


def test_the_watchdog_does_not_start_outside_ci():
    assert cancel.start_watchdog({}, poll_s=0.01, on_dead=lambda: None) is None


def test_a_signal_during_a_cancellable_command_is_exit_16_and_the_outcome_says_so(tmp_path, monkeypatch):
    import json

    from l4 import cli

    def handler(app, **options):
        signal.raise_signal(signal.SIGTERM)
        raise AssertionError("unreachable: the handler raised RunCancelled")

    monkeypatch.setattr(cli, "dispatch", lambda name, app, **options: handler(app, **options))
    code = cli.main(["run", "--repo", str(tmp_path), "--unit", "openspec:x"], environ={})
    assert code == 16
    assert json.loads((tmp_path / ".l4-out" / "outcome.json").read_text())["exit_code"] == 16


def test_the_handlers_are_not_left_installed_after_a_command(tmp_path, monkeypatch):
    from l4 import cli
    from l4.outcome import CommandResult

    before = signal.getsignal(signal.SIGTERM)
    monkeypatch.setattr(cli, "dispatch", lambda name, app, **options: CommandResult(0))
    assert cli.main(["run", "--repo", str(tmp_path)], environ={}) == 0
    assert signal.getsignal(signal.SIGTERM) is before


# --- review: no 30 s blind spot at the start, nor before a push --------------------------------------------------

NO_API = {"GITLAB_CI": "true", "CI_JOB_TOKEN": "tok"}  # no forge URL: the job API check stays out of it


def test_the_watchdog_checks_at_once_not_only_after_the_first_interval():
    """A job cancelled while `l4 doctor` or `l4 plan` ran leaves its shell to start `l4 run` as an orphan: that run
    must stop before it does anything, not 30 s later."""
    dead = threading.Event()
    stop = cancel.start_watchdog(ENV, poll_s=3600, alive=lambda env: False, on_dead=dead.set, grace_s=None, sid=None)
    try:
        assert dead.wait(2)
    finally:
        stop()


def test_the_poll_interval_comes_from_the_environment(monkeypatch):
    assert cancel.poll_seconds({}) == 30.0
    assert cancel.poll_seconds({"L4_CANCEL_POLL_S": "0.2"}) == 0.2
    assert cancel.poll_seconds({"L4_CANCEL_POLL_S": "soon"}) == 30.0
    assert cancel.poll_seconds({"L4_CANCEL_POLL_S": "0"}) == 30.0


def _leader_that_goes(monkeypatch, answers):
    """A session leader that exists at the start and is gone later: `session_alive` answers from the list."""
    seq = iter(answers)
    monkeypatch.setattr(cancel, "session_alive", lambda sid=None: next(seq, False))


def test_a_gone_session_leader_cancels_at_the_next_check_before_the_watchdog_polls(monkeypatch):
    """A push between two polls must not slip through: `check()` asks the session leader itself (a local syscall)."""
    _leader_that_goes(monkeypatch, [True])  # alive at the start, gone from then on
    stop = cancel.start_watchdog(NO_API, poll_s=3600, alive=None, on_dead=lambda: None, grace_s=None, sid=4242)
    try:
        with pytest.raises(RunCancelled):
            cancel.check()
        assert cancel.is_cancelled()
    finally:
        stop()
    cancel.reset()
    cancel.check()  # the probe went with the watchdog


def test_a_live_session_leader_lets_check_pass():
    stop = cancel.start_watchdog(NO_API, poll_s=3600, alive=None, on_dead=lambda: None, grace_s=None, sid=os.getsid(0))
    try:
        cancel.check()
        assert not cancel.is_cancelled()
    finally:
        stop()


def test_reset_drops_the_session_probe_of_a_watchdog_that_was_never_stopped(monkeypatch):
    _leader_that_goes(monkeypatch, [True])
    cancel.start_watchdog(NO_API, poll_s=3600, alive=None, on_dead=lambda: None, grace_s=None, sid=4242)
    cancel.reset()
    cancel.check()  # no probe left behind to cancel a later push in this process


def test_a_job_api_that_cannot_be_asked_is_logged_once(caplog):
    """The forge layer fails open; the job log must say so, or a live check cannot tell it never worked."""

    def boom(url, token):
        raise OSError("certificate verify failed")

    cancel.reset()
    with caplog.at_level("WARNING", logger="l4.cancel"):
        assert cancel.job_alive_verdict(ENV, fetch=boom) is True
        assert cancel.job_alive_verdict(ENV, fetch=boom) is True
        assert cancel.job_alive_verdict(ENV, fetch=lambda url, token: (404, {})) is True
    warned = [r.getMessage() for r in caplog.records if r.name == "l4.cancel"]
    assert len(warned) == 1 and "certificate verify failed" in warned[0] and "session" in warned[0]


def test_a_running_job_logs_nothing(caplog):
    cancel.reset()
    with caplog.at_level("WARNING", logger="l4.cancel"):
        assert cancel.job_alive_verdict(ENV, fetch=lambda url, token: (200, {"status": "running"})) is True
    assert not [r for r in caplog.records if r.name == "l4.cancel"]


# --- polish: the log says the watchdog is armed (F4) -------------------------------------------------------------


def _armed(caplog, environ, **kw):
    cancel.reset()
    with caplog.at_level("INFO", logger="l4.cancel"):
        stop = cancel.start_watchdog(environ, poll_s=3600, alive=lambda env: True, grace_s=None, sid=os.getpid(), **kw)
    assert stop is not None
    stop()
    return [r.getMessage() for r in caplog.records if r.name == "l4.cancel"]


def test_an_armed_watchdog_says_so_and_never_prints_the_token(caplog):
    lines = _armed(caplog, {**ENV, "CI_JOB_TOKEN": "glcbt-SECRET-xyz", "CI_JOB_ID": "77"})
    assert lines == [f"watching CI job 77 (job API every 3600s + job session {os.getpid()})"]
    assert "glcbt-SECRET-xyz" not in lines[0] and "forge.test" not in lines[0]  # neither the token nor the API URL


def test_a_watchdog_without_the_job_api_says_it_is_not_used(caplog):
    [line] = _armed(caplog, {**NO_API, "CI_JOB_ID": "77"})
    assert "job API not used" in line and "no CI_API_V4_URL" in line and f"job session {os.getpid()}" in line


def test_a_watchdog_without_the_job_id_still_says_so(caplog):
    [line] = _armed(caplog, ENV)
    assert line.startswith("watching CI job ") and "job API every" in line


def test_gitlab_ci_without_the_job_token_says_there_is_no_watchdog(caplog):
    """F4 asks for the line when the job API is not used for want of CI_JOB_TOKEN too: without it no watchdog runs,
    and silence would again prove that only by absence."""
    cancel.reset()
    environ = {"GITLAB_CI": "true", "CI_API_V4_URL": "https://forge.test/api/v4", "CI_JOB_ID": "77"}
    with caplog.at_level("INFO", logger="l4.cancel"):
        assert cancel.start_watchdog(environ, poll_s=1, on_dead=lambda: None) is None
    [line] = [r.getMessage() for r in caplog.records if r.name == "l4.cancel"]
    assert line.startswith("not watching CI job 77 ") and "no CI_JOB_TOKEN" in line and "forge.test" not in line


def test_no_watchdog_outside_ci_logs_nothing(caplog):
    cancel.reset()
    with caplog.at_level("INFO", logger="l4.cancel"):
        assert cancel.start_watchdog({}, poll_s=1, on_dead=lambda: None) is None
    assert not [r for r in caplog.records if r.name == "l4.cancel"]


# --- hotfix 0.4.23: a runner whose job session leader exits at the start --------------------------------------------

RUNNING = lambda url, token: (200, {"status": "running"})  # noqa: E731


def _watch(caplog, *, sid, fetch, poll_s=3600):
    cancel.reset()
    dead = threading.Event()
    with caplog.at_level("INFO", logger="l4.cancel"):
        stop = cancel.start_watchdog(ENV, poll_s=poll_s, on_dead=dead.set, grace_s=None, sid=sid, fetch=fetch)
    assert stop is not None
    return dead, stop


def _lines(caplog, level=None):
    return [r.getMessage() for r in caplog.records if r.name == "l4.cancel" and (level is None or r.levelname == level)]


def test_a_leader_gone_at_the_start_with_a_live_job_api_does_not_cancel(caplog):
    dead, stop = _watch(caplog, sid=_dead_pid(), fetch=RUNNING, poll_s=0.01)
    try:
        assert not dead.wait(0.3)  # several polls later the run still goes on
        cancel.check()
        assert not cancel.is_cancelled()
    finally:
        stop()
    [warning] = _lines(caplog, "WARNING")
    assert "session leader" in warning and "is not running at the start" in warning
    assert "only the job API watches this CI job" in warning
    assert any("no job session check: its leader was gone at the start" in line for line in _lines(caplog, "INFO"))


def test_a_leader_gone_at_the_start_still_lets_the_job_api_cancel(caplog):
    dead, stop = _watch(caplog, sid=_dead_pid(), fetch=lambda url, token: (200, {"status": "canceled"}))
    try:
        assert dead.wait(2)
    finally:
        stop()
    [fired] = _lines(caplog, "ERROR")
    assert "the job API says canceled" in fired and "session" not in fired and "\n" not in fired


def test_a_refused_job_token_is_named_in_the_firing_message(caplog):
    dead, stop = _watch(caplog, sid=None, fetch=lambda url, token: (401, {}))
    try:
        assert dead.wait(2)
    finally:
        stop()
    assert "the job API says token refused" in _lines(caplog, "ERROR")[0]


def test_a_leader_alive_at_the_start_and_gone_later_fires_naming_the_session(caplog, monkeypatch):
    _leader_that_goes(monkeypatch, [True, True])  # the start check, the first poll; then gone
    dead, stop = _watch(caplog, sid=4242, fetch=RUNNING, poll_s=0.01)
    try:
        assert dead.wait(2)
    finally:
        stop()
    fired = _lines(caplog, "ERROR")[0]
    assert "its session leader 4242 is gone" in fired and "job API" not in fired
    assert any("job API every 0.01s + job session 4242" in line for line in _lines(caplog, "INFO"))


def test_check_does_not_consult_a_leader_that_was_gone_at_the_start(caplog):
    dead, stop = _watch(caplog, sid=_dead_pid(), fetch=RUNNING)
    try:
        cancel.check()  # must not raise: the leader is not asked
        assert not cancel.is_cancelled() and not dead.is_set()
    finally:
        stop()


def test_a_dropped_session_check_without_the_job_api_says_only_a_signal_stops_the_run(caplog):
    cancel.reset()
    with caplog.at_level("INFO", logger="l4.cancel"):
        stop = cancel.start_watchdog(NO_API, poll_s=3600, on_dead=lambda: None, grace_s=None, sid=_dead_pid())
    assert stop is not None
    stop()
    assert any("only a signal stops this run" in line for line in _lines(caplog, "WARNING"))


# --- hotfix 0.4.24: a CI/CD variable named CI_JOB_TOKEN overrides the job token --------------------------------------

URL_ENV = {
    **ENV,
    "CI_JOB_TOKEN": "group-var",
    "CI_REPOSITORY_URL": "https://gitlab-ci-token:job-tok@forge.test/grp/proj.git",
}
OVERRIDE_WARNING = "CI_JOB_TOKEN is not this job's token"


def test_the_job_token_is_the_one_in_the_repository_url_when_the_variable_differs(caplog):
    cancel.reset()
    seen = []

    def spy(url, token):
        seen.append(token)
        return 200, {"status": "running"}

    with caplog.at_level("INFO", logger="l4.cancel"):
        assert cancel.job_over(URL_ENV, fetch=spy) is None
        assert cancel.job_over(URL_ENV, fetch=spy) is None
    assert seen == ["job-tok", "job-tok"]
    [warning] = _lines(caplog, "WARNING")  # once per process
    assert warning.startswith(OVERRIDE_WARNING) and "Rename that variable" in warning
    assert "group-var" not in warning and "job-tok" not in warning


def test_reset_lets_the_override_warning_come_again(caplog):
    cancel.reset()
    with caplog.at_level("INFO", logger="l4.cancel"):
        cancel.job_over(URL_ENV, fetch=RUNNING)
        cancel.reset()
        cancel.job_over(URL_ENV, fetch=RUNNING)
    assert len(_lines(caplog, "WARNING")) == 2


def test_an_equal_token_in_the_url_changes_nothing(caplog):
    cancel.reset()
    env = {**URL_ENV, "CI_JOB_TOKEN": "job-tok"}
    seen = []
    with caplog.at_level("INFO", logger="l4.cancel"):
        cancel.job_over(env, fetch=lambda url, token: seen.append(token) or (200, {"status": "running"}))
    assert seen == ["job-tok"] and not _lines(caplog, "WARNING")


def test_a_url_without_a_job_token_leaves_the_variable_in_use(caplog):
    cancel.reset()
    seen = []
    env = {**URL_ENV, "CI_REPOSITORY_URL": "https://forge.test/grp/proj.git"}
    cancel.job_over(env, fetch=lambda url, token: seen.append(token) or (200, {"status": "running"}))
    assert seen == ["group-var"] and not _lines(caplog, "WARNING")


def test_a_repository_url_token_alone_is_enough_to_watch(caplog):
    cancel.reset()
    env = {k: v for k, v in URL_ENV.items() if k != "CI_JOB_TOKEN"}
    seen = []
    dead = threading.Event()
    with caplog.at_level("INFO", logger="l4.cancel"):
        stop = cancel.start_watchdog(
            env,
            poll_s=3600,
            on_dead=dead.set,
            grace_s=None,
            sid=None,
            fetch=lambda url, token: seen.append(token) or (200, {"status": "running"}),
        )
        assert stop is not None
        stop()
    assert seen[:1] == ["job-tok"]


def test_the_secrets_never_reach_a_log_line_or_the_firing_message(caplog):
    dead, stop = _watch_with(caplog, URL_ENV, sid=None, fetch=lambda url, token: (401, {}))
    try:
        assert dead.wait(2)
    finally:
        stop()
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "group-var" not in text and "job-tok" not in text


def _watch_with(caplog, environ, *, sid, fetch, poll_s=3600):
    cancel.reset()
    dead = threading.Event()
    with caplog.at_level("INFO", logger="l4.cancel"):
        stop = cancel.start_watchdog(environ, poll_s=poll_s, on_dead=dead.set, grace_s=None, sid=sid, fetch=fetch)
    assert stop is not None
    return dead, stop


def test_a_first_refusal_with_a_live_session_is_not_a_cancel(caplog):
    asked = []

    def refuse(url, token):
        asked.append(token)
        return 401, {}

    dead, stop = _watch_with(caplog, ENV, sid=os.getpid(), fetch=refuse, poll_s=0.01)
    try:
        assert not dead.wait(0.3)  # several polls later the session check alone still watches
        cancel.check()
    finally:
        stop()
    assert len(asked) == 1  # the job API is not asked again for this run
    [warning] = [w for w in _lines(caplog, "WARNING") if "refused the job token at the start" in w]
    assert "only the job session watches this CI job" in warning


def test_a_session_that_goes_after_a_refused_start_still_fires(caplog, monkeypatch):
    _leader_that_goes(monkeypatch, [True, True])
    dead, stop = _watch_with(caplog, ENV, sid=4242, fetch=lambda url, token: (401, {}), poll_s=0.01)
    try:
        assert dead.wait(2)
    finally:
        stop()
    assert "its session leader 4242 is gone" in _lines(caplog, "ERROR")[0]


def test_a_refusal_after_an_accepted_first_answer_still_fires(caplog):
    answers = iter([(200, {"status": "running"}), (401, {})])
    dead, stop = _watch_with(
        caplog, ENV, sid=os.getpid(), fetch=lambda url, token: next(answers, (401, {})), poll_s=0.01
    )
    try:
        assert dead.wait(2)
    finally:
        stop()
    assert "the job API says token refused" in _lines(caplog, "ERROR")[0]


def test_a_first_refusal_after_a_leader_gone_at_the_start_fires(caplog):
    dead, stop = _watch_with(caplog, ENV, sid=_dead_pid(), fetch=lambda url, token: (401, {}))
    try:
        assert dead.wait(2)
    finally:
        stop()
    assert "the job API says token refused" in _lines(caplog, "ERROR")[0]


def test_neither_check_left_says_only_a_signal_stops_the_run(caplog):
    cancel.reset()
    with caplog.at_level("INFO", logger="l4.cancel"):
        stop = cancel.start_watchdog(NO_API, poll_s=3600, on_dead=lambda: None, grace_s=None, sid=None)
    assert stop is not None
    stop()
    assert any("only a signal stops this run" in line for line in _lines(caplog, "WARNING"))
