"""The GitLab job reader (forge-and-ci 2.19, M1.8): jobs, stages and tags of `.gitlab-ci.yml` and its local includes."""

from pathlib import Path

from l4.ci.gitlab_jobs import gitlab_jobs, parse_gitlab_ci


def put(repo: Path, relpath: str, text: str) -> None:
    path = repo / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_jobs_come_from_the_file_and_its_local_includes_in_order(tmp_path):
    put(
        tmp_path,
        ".gitlab-ci.yml",
        "include:\n  - local: /ci/a.yml\nstages: [test]\nzeta:\n  script: [x]\nalpha:\n  script: [y]\n",
    )
    put(tmp_path, "ci/a.yml", "from_include:\n  stage: build\n  tags: [t]\n  script: [z]\n")
    ci = gitlab_jobs(tmp_path)
    assert ci.present and [j.name for j in ci.jobs] == ["from_include", "zeta", "alpha"]
    assert ci.jobs[0].tags == ("t",) and ci.jobs[0].stage == "build" and ci.jobs[1].tags is None


def test_reserved_keys_hidden_jobs_and_non_jobs_are_not_jobs(tmp_path):
    text = (
        "stages: [a]\nvariables: {X: 1}\nworkflow: {}\ndefault: {tags: [d]}\n.hidden:\n  script: [x]\n"
        "real:\n  script: [x]\n"
    )
    put(tmp_path, ".gitlab-ci.yml", text)
    ci = gitlab_jobs(tmp_path)
    assert [j.name for j in ci.jobs] == ["real"] and ci.default_tags == ("d",)


def test_not_checked_includes_and_unreadable_files_are_reported(tmp_path):
    text = (
        "include:\n  - remote: https://x.test/a.yml\n  - project: g/p\n    file: f.yml\n  - template: Jobs/Build.yml\n"
        "  - local: missing.yml\nj:\n  script: [x]\n"
    )
    put(tmp_path, ".gitlab-ci.yml", text)
    ci = gitlab_jobs(tmp_path)
    assert len(ci.not_checked) == 3 and any("https://x.test/a.yml" in n for n in ci.not_checked)
    assert any("missing.yml" in p for p in ci.problems)


def test_reference_tags_and_a_scalar_include_parse(tmp_path):
    put(tmp_path, ".gitlab-ci.yml", "include: ci/a.yml\nj:\n  script:\n    - !reference [.x, script]\n")
    put(tmp_path, "ci/a.yml", "k:\n  script: [x]\n")
    assert [j.name for j in gitlab_jobs(tmp_path).jobs] == ["k", "j"]


def test_no_file_and_broken_yaml(tmp_path):
    assert not gitlab_jobs(tmp_path).present
    put(tmp_path, ".gitlab-ci.yml", "a: [unclosed\n")
    ci = gitlab_jobs(tmp_path)
    assert ci.present and ci.jobs == () and ci.problems


def test_parse_takes_the_text_and_a_loader_for_includes():
    seen = []

    def load(path: str) -> str | None:
        seen.append(path)
        return "inc:\n  script: [x]\n"

    ci = parse_gitlab_ci("include:\n  - local: .l4/ci/l4.gitlab-ci.yml\nj:\n  script: [y]\n", load)
    assert seen == [".l4/ci/l4.gitlab-ci.yml"] and [j.name for j in ci.jobs] == ["inc", "j"]


# --- the script reader (M1.10 line 3): what a job runs, for the failing-step check ---


def test_script_and_before_script_through_extends_and_default():
    from l4.ci.gitlab_jobs import JobScript, job_script

    text = (
        "default:\n  before_script: [echo default]\n"
        ".base:\n  before_script: [uv sync]\n  script: [make base]\n"
        "test:\n  extends: .base\n  script:\n    - uv run pytest\n    - [uv run ruff check, uv run mypy]\n"
        "lint:\n  script: [ruff check .]\n"
        "own:\n  extends: [.base]\n  before_script: [echo own]\n"
        "bare:\n  inherit:\n    default: false\n  script: [make]\n"
    )
    nowhere: str | None = None
    assert job_script(text, lambda p: nowhere, "test") == JobScript(
        ("uv sync",), ("uv run pytest", "uv run ruff check", "uv run mypy")
    )  # own script (one nested list flattened), before_script from extends
    assert job_script(text, lambda p: nowhere, "lint") == JobScript(("echo default",), ("ruff check .",))
    assert job_script(text, lambda p: nowhere, "own") == JobScript(("echo own",), ("make base",))
    assert job_script(text, lambda p: nowhere, "bare") == JobScript((), ("make",))


def test_a_reference_tag_refuses():
    from l4.ci.gitlab_jobs import ScriptRefusal, job_script

    text = ".x:\n  script: [a]\nj:\n  script:\n    - !reference [.x, script]\n    - b\n"
    refusal = job_script(text, lambda p: None, "j")
    assert isinstance(refusal, ScriptRefusal) and "!reference" in refusal.reason
    via_default = "default:\n  before_script:\n    - !reference [.x, script]\n.x:\n  script: [a]\nj:\n  script: [b]\n"
    assert isinstance(job_script(via_default, lambda p: None, "j"), ScriptRefusal)


def test_a_job_from_a_remote_include_refuses():
    from l4.ci.gitlab_jobs import ScriptRefusal, job_script

    text = "include:\n  - remote: https://x.test/a.yml\nlocal_job:\n  script: [x]\n"
    refusal = job_script(text, lambda p: None, "remote_job")
    assert isinstance(refusal, ScriptRefusal) and "include" in refusal.reason
    extending = "include:\n  - remote: https://x.test/a.yml\nj:\n  extends: .from_remote\n  script: [x]\n"
    assert isinstance(job_script(extending, lambda p: None, "j"), ScriptRefusal)  # the parent is unread
