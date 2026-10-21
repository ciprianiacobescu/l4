"""The project's own pipelines for a sha: the jobs of every pipeline, one per name (the newest pipeline's), and the end
of a job's log (forge-and-ci 1.1, 2.2; M1.9 decision 8)."""

from l4.forge.base import JobResult

from .conftest import FakeGitLab

SHA = "a" * 40


def test_jobs_listed_for_sha_across_pipelines(gitlab: FakeGitLab, make_forge_client):
    forge = make_forge_client()
    push = gitlab.add_pipeline(SHA, [("lint", "success"), ("test", "failed", {"stage": "test"})])
    web = gitlab.add_pipeline(SHA, [("build", "running", {"stage": "build", "allow_failure": True})])
    gitlab.add_pipeline("b" * 40, [("other", "failed")])  # another sha: not ours
    jobs = forge.list_pipeline_jobs(SHA)
    assert {j.name for j in jobs} == {"lint", "test", "build"}
    by_name = {j.name: j for j in jobs}
    assert by_name["test"] == JobResult(
        "test", "test", "failed", False, push, by_name["test"].job_id, by_name["test"].web_url
    )
    assert (
        by_name["build"].pipeline_id == web and by_name["build"].allow_failure and by_name["build"].status == "running"
    )
    assert by_name["test"].web_url.startswith("https://gitlab.example.test/") and "/-/jobs/" in by_name["test"].web_url
    assert forge.list_pipeline_jobs("c" * 40) == []
    assert all(m == "GET" for m, _ in [(m, p) for m, p, _, _ in gitlab.requests])  # reads only


def test_newest_pipeline_wins_per_job_name(gitlab: FakeGitLab, make_forge_client):
    forge = make_forge_client()
    gitlab.add_pipeline(SHA, [("test", "failed"), ("lint", "success")])
    newest = gitlab.add_pipeline(SHA, [("test", "success")])  # the job was retried or rerun by a later pipeline
    jobs = {j.name: j for j in forge.list_pipeline_jobs(SHA)}
    assert jobs["test"].status == "success" and jobs["test"].pipeline_id == newest
    assert len(jobs) == 2 and jobs["test"].workflow == "" and jobs["test"].key == "test"  # SCN-CI-057
    assert jobs["lint"].status == "success"  # only the older pipeline has it: it stays


def test_pages_are_followed(gitlab: FakeGitLab, make_forge_client):
    forge = make_forge_client()
    gitlab.add_pipeline(SHA, [(f"job{i}", "success") for i in range(250)])  # PER_PAGE is 100
    assert len(forge.list_pipeline_jobs(SHA)) == 250


def test_job_log_tail_is_capped_and_ansi_stripped(gitlab: FakeGitLab, make_forge_client):
    forge = make_forge_client()
    log = "\r\n".join(f"\x1b[31mline {i}\x1b[0m" for i in range(500)) + "\r\n\x1b[1;32mFAILED test_x\x1b[0m\n"
    gitlab.add_pipeline(SHA, [("test", "failed", {"trace": log})])
    (job,) = forge.list_pipeline_jobs(SHA)
    tail = forge.job_log_tail(job.job_id, 40)
    lines = tail.splitlines()
    assert len(lines) == 40 and lines[-1] == "FAILED test_x" and lines[0] == "line 461"
    assert "\x1b" not in tail and "\r" not in tail
    assert len(forge.job_log_tail(job.job_id, 400)) <= 3000  # characters are capped too, keeping the end
    assert forge.job_log_tail(job.job_id, 400).endswith("FAILED test_x")
    assert forge.job_log_tail(99999, 40) == ""  # a log that cannot be read is no evidence, not an error


def test_settled_keeps_the_newest_finished_attempt_of_each_name(gitlab: FakeGitLab, make_forge_client):
    """For the base comparison: a pipeline still running on the sha (the one the sweep itself runs in) does not hide an
    earlier finished attempt of the same job; a job with no finished attempt keeps its newest, unfinished one."""
    forge = make_forge_client()
    done = gitlab.add_pipeline(SHA, [("test", "failed"), ("lint", "success")])
    gitlab.add_pipeline(SHA, [("test", "running"), ("lint", "pending"), ("build", "running"), ("l4", "running")])
    plain = {j.name: j.status for j in forge.list_pipeline_jobs(SHA)}
    assert plain == {"test": "running", "lint": "pending", "build": "running", "l4": "running"}  # newest wins
    settled = {j.name: j for j in forge.list_pipeline_jobs(SHA, settled=True)}
    assert {n: j.status for n, j in settled.items()} == {
        "test": "failed", "lint": "success", "build": "running", "l4": "running",
    }  # fmt: skip
    assert settled["test"].pipeline_id == done


def _runner_line(n: int, text: str, cont: bool = False) -> str:
    """One line of a GitLab trace as the runner writes it with timestamps: `<time>Z <stream><O|E><' '|'+'><text>`."""
    return f"2026-10-05T23:57:{n:02d}.000000Z 01O{'+' if cont else ' '}{text}"


# The end of a real failed job trace (dummy-agentic job 5604, M1.9 live check): per-line runner timestamps, section
# markers, and the runner's cleanup section after the job's own error.
RUNNER_TRACE = "\n".join(
    [_runner_line(0, "\x1b[0KRunning with gitlab-runner 18.9.0\x1b[0;m")]
    + [_runner_line(1, f"Downloading package {i}") for i in range(60)]
    + [
        _runner_line(2, "section_start:1791244620:step_script\r\x1b[0K\x1b[36;1mExecuting step_script\x1b[0;m"),
        _runner_line(2, "\x1b[32;1m$ uv run ruff check --select E501 --line-length 92 src\x1b[0;m"),
        _runner_line(3, "E501 Line too long (108 > 92)"),
        _runner_line(3, " --> src/pricing/notices.py:2:93"),
        _runner_line(3, "  |"),
        _runner_line(3, "1 | def return_policy() -> str:"),
        _runner_line(3, '2 |     return "Unused items may be returned within 30 days of delivery for a full refund."'),
        _runner_line(3, "  |" + " " * 89 + "^" * 16),
        _runner_line(3, ""),
        _runner_line(3, "Found 1 error."),
        _runner_line(4, "section_end:1791244623:step_script\r"),
        _runner_line(4, "\x1b[0Ksection_start:1791244623:upload_artifacts_on_failure\r", cont=True),
        _runner_line(4, "\x1b[0K\x1b[0K\x1b[36;1mUploading artifacts for failed job\x1b[0;m\x1b[0;m", cont=True),
        _runner_line(4, "\x1b[32;1mUploading artifacts...\x1b[0;m"),
        _runner_line(4, "junit.xml: found 1 matching artifact files and directories\x1b[0;m"),
        _runner_line(
            4, 'Uploading artifacts as "junit" to coordinator... 201 Created\x1b[0;m  id=5604 responseStatus=201'
        ),
        _runner_line(4, "section_end:1791244623:upload_artifacts_on_failure\r"),
        _runner_line(4, "\x1b[0Ksection_start:1791244623:cleanup_file_variables\r", cont=True),
        _runner_line(
            4, "\x1b[0K\x1b[0K\x1b[36;1mCleaning up project directory and file based variables\x1b[0;m", cont=True
        ),
        _runner_line(5, "section_end:1791244624:cleanup_file_variables\r"),
        _runner_line(5, "\x1b[0K", cont=True),
        _runner_line(5, "\x1b[31;1mERROR: Job failed: exit code 1\x1b[0;m"),
    ]
)


def test_job_log_tail_drops_the_runner_framing_so_the_end_is_the_jobs_error(gitlab: FakeGitLab, make_forge_client):
    """M1.9 live check: the fix task keeps the end of the flattened tail (`ci_detail`), and on GitLab that end was the
    runner's timestamps, section markers and cleanup chatter, so the job's own error never reached the fix agent."""
    from l4.verifier.preconditions import ci_detail

    forge = make_forge_client()
    gitlab.add_pipeline(SHA, [("test", "failed", {"trace": RUNNER_TRACE})])
    (job,) = forge.list_pipeline_jobs(SHA)
    tail = forge.job_log_tail(job.job_id, 40)
    lines = tail.splitlines()
    assert not [line for line in lines if line.startswith("2026-10-05T")]  # no runner timestamps
    assert "section_" not in tail and "Cleaning up project directory" not in tail and "Uploading artifacts" not in tail
    assert lines[-2:] == ["Found 1 error.", "ERROR: Job failed: exit code 1"]
    assert (
        "E501 Line too long (108 > 92)" in lines and "$ uv run ruff check --select E501 --line-length 92 src" in lines
    )
    summary = ci_detail("test", "test", SHA, "", tail).split("\n\n")[0]  # what a fix task keeps
    assert "E501 Line too long (108 > 92)" in summary and "notices.py:2:93" in summary


def test_a_trace_without_runner_timestamps_is_cleaned_too(gitlab: FakeGitLab, make_forge_client):
    """Older runners write the section markers inline (`section_start:<t>:<name>\\r\\x1b[0K<header>`), no timestamps."""
    forge = make_forge_client()
    log = (
        "\x1b[0Ksection_start:1:step_script\r\x1b[0K\x1b[0K\x1b[36;1mExecuting step_script\x1b[0;m\n"
        "AssertionError: 2 != 3\n"
        "\x1b[0Ksection_end:2:step_script\r\x1b[0K\n"
        "\x1b[0Ksection_start:2:cleanup_file_variables\r\x1b[0K\x1b[0K\x1b[36;1mCleaning up project directory and file "
        "based variables\x1b[0;m\n"
        "\x1b[0Ksection_end:3:cleanup_file_variables\r\x1b[0K\n"
        "\x1b[31;1mERROR: Job failed: exit code 1\x1b[0;m\n"
    )
    gitlab.add_pipeline(SHA, [("test", "failed", {"trace": log})])
    (job,) = forge.list_pipeline_jobs(SHA)
    assert forge.job_log_tail(job.job_id, 40).splitlines() == [
        "Executing step_script", "AssertionError: 2 != 3", "ERROR: Job failed: exit code 1",
    ]  # fmt: skip


def test_failing_step_is_the_last_echo_in_step_script(gitlab: FakeGitLab, make_forge_client):
    forge = make_forge_client()
    gitlab.add_pipeline(SHA, [("test", "failed", {"trace": RUNNER_TRACE})])
    (job,) = forge.list_pipeline_jobs(SHA)
    log = forge.job_log(job.job_id, 40)
    assert log.step == "uv run ruff check --select E501 --line-length 92 src"
    assert log.tail == forge.job_log_tail(job.job_id, 40)
    assert forge.job_log(99999, 40).step is None and forge.job_log(99999, 40).tail == ""


def test_an_after_script_echo_is_not_the_failing_step(gitlab: FakeGitLab, make_forge_client):
    forge = make_forge_client()
    trace = (
        "section_start:1:step_script\r\x1b[0K\x1b[36;1mExecuting step_script\x1b[0;m\n"
        "\x1b[32;1m$ make test\x1b[0;m\n"
        "FAILED\n"
        "\x1b[32;1m$ echo second step\x1b[0;m\n"
        "section_end:2:step_script\r\x1b[0K\n"
        "section_start:2:after_script\r\x1b[0K\x1b[36;1mRunning after_script\x1b[0;m\n"
        "\x1b[32;1m$ ./cleanup.sh\x1b[0;m\n"
        "section_end:3:after_script\r\x1b[0K\n"
    )
    gitlab.add_pipeline(SHA, [("test", "failed", {"trace": trace})])
    (job,) = forge.list_pipeline_jobs(SHA)
    assert forge.job_log(job.job_id, 40).step == "echo second step"  # the last echo of step_script, not after_script


def test_a_trace_without_sections_has_no_step(gitlab: FakeGitLab, make_forge_client):
    forge = make_forge_client()
    gitlab.add_pipeline(SHA, [("test", "failed", {"trace": "$ make test\nFAILED\n"})])
    (job,) = forge.list_pipeline_jobs(SHA)
    log = forge.job_log(job.job_id, 40)
    assert log.step is None and "$ make test" in log.tail


def test_an_unfinished_pipeline_without_a_project_job_is_a_running_job(gitlab: FakeGitLab, make_forge_client):
    """F2 (SCN-CI-065, L4-CI-014): a pipeline that is created or pending has no job to read yet, and is not "no CI"."""
    forge = make_forge_client()
    for status in ("created", "pending", "running", "waiting_for_resource", "preparing", "scheduled"):
        gitlab.pipelines.clear()
        gitlab.add_pipeline(SHA, [], status=status)
        (job,) = forge.list_pipeline_jobs(SHA)
        assert job.status == "pending" and job.web_url == ""
    gitlab.pipelines.clear()
    gitlab.add_pipeline(SHA, [("l4", "running")], status="running")  # the harness's own job is not the project's CI
    assert [j.status for j in forge.list_pipeline_jobs(SHA) if j.name != "l4"] == ["pending"]
    gitlab.pipelines.clear()
    gitlab.add_pipeline(SHA, [("test", "success")], status="running")
    assert [j.name for j in forge.list_pipeline_jobs(SHA)] == ["test"]  # its jobs speak for it
    gitlab.pipelines.clear()
    gitlab.add_pipeline(SHA, [], status="success")
    assert forge.list_pipeline_jobs(SHA) == []


def test_an_after_script_after_the_failure_is_not_in_the_tail(gitlab: FakeGitLab, make_forge_client):
    """SCN-VER-223: the runner runs `after_script` after a failed script; its chatter must not push the error out."""
    forge = make_forge_client()
    after = [f"after_script line {i}" for i in range(60)]
    trace = "\n".join(
        [
            "section_start:1:step_script\r\x1b[0K\x1b[36;1mExecuting step_script\x1b[0;m",
            "\x1b[32;1m$ make test\x1b[0;m",
            "Traceback (most recent call last):",
            "GitError: push refused",
            "l4 exit 1 (internal_error): harness bug or infrastructure failure",
            "section_end:2:step_script\r\x1b[0K",
            "section_start:2:after_script\r\x1b[0K\x1b[36;1mRunning after_script\x1b[0;m",
            *after,
            "section_end:3:after_script\r\x1b[0K",
            "\x1b[31;1mERROR: Job failed: exit status 1\x1b[0;m",
        ]
    )
    gitlab.add_pipeline(SHA, [("test", "failed", {"trace": trace})])
    (job,) = forge.list_pipeline_jobs(SHA)
    log = forge.job_log(job.job_id, 40)
    lines = log.tail.splitlines()
    assert lines[-2:] == [
        "l4 exit 1 (internal_error): harness bug or infrastructure failure",
        "ERROR: Job failed: exit status 1",
    ]
    assert not [line for line in lines if line.startswith("after_script line") or line == "Running after_script"]
    assert log.step == "make test"


def test_the_cache_sections_are_runner_sections(gitlab: FakeGitLab, make_forge_client):
    forge = make_forge_client()
    trace = "\n".join(
        [
            "Getting source from Git repository",
            "fatal: unable to access the repository",
            "section_start:1:archive_cache_on_failure\r\x1b[0K\x1b[36;1mSaving cache for failed job\x1b[0;m",
            "Creating cache default...",
            "section_end:2:archive_cache_on_failure\r\x1b[0K",
            "ERROR: Job failed: exit code 1",
        ]
    )
    gitlab.add_pipeline(SHA, [("test", "failed", {"trace": trace})])
    (job,) = forge.list_pipeline_jobs(SHA)
    tail = forge.job_log_tail(job.job_id, 40)
    assert "Creating cache" not in tail and "Saving cache" not in tail
    assert tail.splitlines() == [
        "Getting source from Git repository",
        "fatal: unable to access the repository",
        "ERROR: Job failed: exit code 1",
    ]


def test_a_trace_without_a_script_section_keeps_todays_tail(gitlab: FakeGitLab, make_forge_client):
    """SCN-VER-224: no markers at all, and a job that failed in `get_sources` before its script."""
    forge = make_forge_client()
    plain = "\n".join(f"line {i}" for i in range(70))
    early = "\n".join(
        ["section_start:1:get_sources\r\x1b[0K\x1b[36;1mGetting source\x1b[0;m"]
        + [f"git line {i}" for i in range(60)]
        + ["fatal: repository not found", "section_end:2:get_sources\r\x1b[0K", "ERROR: Job failed: exit code 1"]
    )
    gitlab.add_pipeline(SHA, [("a", "failed", {"trace": plain}), ("b", "failed", {"trace": early})])
    jobs = {j.name: j for j in forge.list_pipeline_jobs(SHA)}
    assert forge.job_log_tail(jobs["a"].job_id, 40).splitlines() == [f"line {i}" for i in range(30, 70)]
    tail = forge.job_log_tail(jobs["b"].job_id, 40).splitlines()
    assert len(tail) == 40 and tail[-2:] == ["fatal: repository not found", "ERROR: Job failed: exit code 1"]


def test_a_long_script_keeps_its_failures(gitlab: FakeGitLab, make_forge_client):
    """SCN-VER-225 on GitLab: `FAILED` lines that come before the last 40 lines of the script stay in the excerpt."""
    forge = make_forge_client()
    trace = "\n".join(
        ["section_start:1:step_script\r\x1b[0K\x1b[36;1mExecuting step_script\x1b[0;m", "$ pytest -q"]
        + [f"FAILED tests/test_a.py::test_{i} - AssertionError" for i in range(3)]
        + [f"output {i}" for i in range(100)]
        + ["3 failed, 90 passed in 4s", "section_end:2:step_script\r\x1b[0K", "ERROR: Job failed: exit code 1"]
    )
    gitlab.add_pipeline(SHA, [("test", "failed", {"trace": trace})])
    (job,) = forge.list_pipeline_jobs(SHA)
    tail = forge.job_log_tail(job.job_id, 40)
    lines = tail.splitlines()
    assert lines[:3] == [f"FAILED tests/test_a.py::test_{i} - AssertionError" for i in range(3)]
    assert "..." in lines and lines[-2:] == ["3 failed, 90 passed in 4s", "ERROR: Job failed: exit code 1"]
    assert len(tail) <= 3000
