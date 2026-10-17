"""The repository's own CI jobs and whether the gates mirror them (adoption-lessons 6.1, design D6)."""

from pathlib import Path

from l4.ci.repo_jobs import normalise, repo_ci_jobs, unmirrored
from l4.config.schema import L4Config

CI = """\
name: ci
on:
  push:
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: uv run pytest
  conformance:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
    steps:
      - run: |
          uv sync
          uv run pytest -m postgres
"""


def put(repo: Path, relpath: str, text: str) -> None:
    path = repo / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def cfg(**gates) -> L4Config:
    return L4Config.model_validate({"gates": gates})


def test_normalise_splits_and_strips_prefixes():
    assert normalise("uv run .venv/bin/python -m pytest  -q\n# comment\n\n  ruff check && uv run ruff format; x") == [
        "pytest -q", "ruff check", "ruff format", "x",
    ]  # fmt: skip


def test_jobs_of_push_workflows_with_their_services(tmp_path: Path):
    put(tmp_path, ".github/workflows/ci.yml", CI)
    put(tmp_path, ".github/workflows/l4.yml", CI.replace("name: ci", "name: l4"))
    put(
        tmp_path,
        ".github/workflows/nightly.yaml",
        "on:\n  schedule:\n    - cron: '0 0 * * *'\njobs:\n  a:\n    steps:\n      - run: x\n",
    )
    found = repo_ci_jobs(tmp_path)
    assert found.present and not found.problems
    assert [(j.file, j.name, j.services) for j in found.jobs] == [
        ("ci.yml", "test", ()),
        ("ci.yml", "conformance", ("postgres",)),
    ]
    assert found.jobs[1].commands == ("uv sync", "pytest -m postgres")


def test_on_as_string_and_list(tmp_path: Path):
    put(tmp_path, ".github/workflows/a.yml", "on: push\njobs:\n  j:\n    steps:\n      - run: make a\n")
    put(
        tmp_path,
        ".github/workflows/b.yml",
        "on: [pull_request, workflow_dispatch]\njobs:\n  k:\n    steps:\n      - run: make b\n",
    )
    assert [j.name for j in repo_ci_jobs(tmp_path).jobs] == ["j", "k"]


def test_a_container_job_is_marked(tmp_path: Path):
    put(
        tmp_path,
        ".github/workflows/a.yml",
        "on: push\njobs:\n  j:\n    container: node:20\n    steps:\n      - run: make a\n",
    )
    job = repo_ci_jobs(tmp_path).jobs[0]
    assert job.container and unmirrored([job], cfg()) == [job]


def test_unmirrored_lists_only_the_job_with_a_command_no_gate_contains(tmp_path: Path):
    put(tmp_path, ".github/workflows/ci.yml", CI)
    jobs = repo_ci_jobs(tmp_path).jobs
    config = cfg(setup=["uv sync"], test={"command": ".venv/bin/pytest --junitxml=.l4-out/junit.xml"})
    assert [j.name for j in unmirrored(jobs, config)] == ["conformance"]


def test_a_typecheck_or_build_gate_counts_without_a_profile(tmp_path: Path):
    """Step 2 of every verification round runs `build` and `typecheck` (L4-ADO-006): they mirror a job."""
    put(tmp_path, ".github/workflows/ci.yml", "on: push\njobs:\n  t:\n    steps:\n      - run: uv run mypy src\n")
    jobs = repo_ci_jobs(tmp_path).jobs
    assert unmirrored(jobs, L4Config.model_validate({"gates": {"typecheck": ["mypy src"]}})) == []
    assert unmirrored(jobs, L4Config.model_validate({"gates": {"build": ["mypy src"]}})) == []


def test_an_extra_gate_counts_only_when_a_yolo_profile_names_it(tmp_path: Path):
    put(tmp_path, ".github/workflows/ci.yml", "on: push\njobs:\n  t:\n    steps:\n      - run: make docs\n")
    jobs = repo_ci_jobs(tmp_path).jobs
    gates = {"extra": [{"name": "docs", "command": "make docs"}]}
    plain = L4Config.model_validate({"gates": gates})
    named = L4Config.model_validate({"gates": gates, "yolo": {"profiles": {"docs": ["extra:docs"]}}})
    assert unmirrored(jobs, plain) == list(jobs)  # no profile names the extra gate
    assert unmirrored(jobs, named) == []


def test_uv_run_options_are_ignored_on_both_sides(tmp_path: Path):
    """A workspace member's gate runs `uv run --directory <member> …`, its CI job `cd <member>` then `uv run …`."""
    put(
        tmp_path,
        ".github/workflows/ci.yml",
        "on: push\njobs:\n  t:\n    steps:\n      - run: uv run mypy --strict src/\n",
    )
    jobs = repo_ci_jobs(tmp_path).jobs
    gate = cfg(typecheck=["uv run --frozen --directory apps/api mypy --strict src/"])
    assert unmirrored(jobs, gate) == []
    assert normalise("uv run --project=apps/api --locked --package api pytest -q") == ["pytest -q"]


def test_unparseable_file_is_named_not_a_crash(tmp_path: Path):
    put(tmp_path, ".github/workflows/bad.yml", "on: [push\njobs: {")
    put(tmp_path, ".github/workflows/ok.yml", "on: push\njobs:\n  j:\n    steps:\n      - run: make a\n")
    found = repo_ci_jobs(tmp_path)
    assert [j.name for j in found.jobs] == ["j"]
    assert len(found.problems) == 1 and "bad.yml" in found.problems[0]


def test_no_ci_file(tmp_path: Path):
    put(tmp_path, ".github/workflows/l4.yml", "on: push\njobs: {}\n")
    assert not repo_ci_jobs(tmp_path).present


def test_gitlab_jobs_leave_out_the_harness_job(tmp_path: Path):
    put(
        tmp_path, ".gitlab-ci.yml",
        "l4:\n  script:\n    - l4 ci run\ntest:\n  script:\n    - uv run pytest\n"
        "lint:\n  script:\n    - ruff check .\n",
    )  # fmt: skip
    found = repo_ci_jobs(tmp_path)
    assert found.present and [(j.file, j.name) for j in found.jobs] == [
        (".gitlab-ci.yml", "test"), (".gitlab-ci.yml", "lint"),
    ]  # fmt: skip
    assert [j.name for j in unmirrored(found.jobs, cfg(test={"command": "pytest"}))] == ["lint"]


USES_ONLY = """\
on: [push, pull_request]
jobs:
  docker:
    steps:
      - uses: actions/checkout@v4
      - uses: docker/build-push-action@v6
  helm:
    steps:
      - uses: helm/chart-testing-action@v2
  reusable:
    uses: ./.github/workflows/pg.yml
  pg:
    services:
      postgres: {image: postgres:16}
    steps:
      - run: uv run pytest -q
  plain:
    steps:
      - uses: actions/checkout@v4
      - run: uv run pytest -q
"""


def test_a_job_with_only_uses_steps_or_with_services_is_not_mirrored(tmp_path: Path):
    put(tmp_path, ".github/workflows/ci.yml", USES_ONLY)
    jobs = repo_ci_jobs(tmp_path).jobs
    config = cfg(test={"command": "pytest -q"})
    assert [j.name for j in unmirrored(jobs, config)] == ["docker", "helm", "reusable", "pg"]
    assert [j.name for j in jobs if j.name == "plain"] == ["plain"]
