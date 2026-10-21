"""`merge_include`: the `.gitlab-ci.yml` edit of `l4 init` (forge-and-ci 1.22, M1.8 A1, SCN-INS-12 narrowed).

Every test that edits a file asserts the same property: the parsed document after the edit equals the one before,
with the include list extended, and the keys (jobs) are the same, in the same order."""

import pytest
import yaml

from l4.ci.gitlab_jobs import _Loader
from l4.ci.render import INCLUDE_SNIPPET, TEMPLATE_RELPATH
from l4.init.ciedit import merge_include

GATES = {
    "setup": ["uv sync --frozen --extra dev"],
    "test": {"command": ".venv/bin/python -m pytest --junitxml=.l4-out/junit.xml"},
    "lint": [],
}
INCLUDE_ITEM = {"local": TEMPLATE_RELPATH}


def parse(text: str) -> dict:
    return yaml.load(text, Loader=_Loader)  # noqa: S506  (the SafeLoader subclass of the job reader)


def assert_only_the_include_changed(before: str, after: str) -> None:
    old, new = parse(before), parse(after)
    new_include = new.pop("include")
    old_include = old.pop("include", [])
    old_include = old_include if isinstance(old_include, list) else [old_include]
    assert old == new and list(old) == list(new)  # the same jobs, the same order
    assert sorted(map(str, new_include)) == sorted(map(str, [*old_include, INCLUDE_ITEM]))


EXISTING = """\
# the project's pipeline
stages:
  - build
  - test

build:
  stage: build
  script:
    - make

test:
  stage: test
  script:
    - make test
"""


def test_absent_file_gets_include_and_a_tagged_test_job():
    edit = merge_include(None, ["agentic"], GATES)
    assert edit.action == "create" and edit.text is not None
    doc = parse(edit.text)
    assert doc["include"] == [INCLUDE_ITEM]
    job = doc["test"]
    assert job["stage"] == "test" and job["tags"] == ["agentic"]
    script = job["script"]
    assert "schedule" in script[0] and "exit 0" in script[0]  # the sweep's pipeline needs a job, which does nothing
    assert script[1:] == ["uv sync --frozen --extra dev", ".venv/bin/python -m pytest --junitxml=.l4-out/junit.xml"]
    assert edit.warnings == ()


def test_no_include_is_prepended_and_bytes_are_kept():
    edit = merge_include(EXISTING, ["agentic"], GATES)
    assert edit.action == "insert-include" and edit.text is not None
    assert edit.text.startswith("# the project's pipeline\n" + INCLUDE_SNIPPET)  # after the leading comment block
    assert edit.text.endswith(EXISTING.split("\n", 1)[1])  # the rest, byte for byte
    assert_only_the_include_changed(EXISTING, edit.text)


@pytest.mark.parametrize(
    "block",
    [
        "include:\n  - local: ci/a.yml\n  - project: g/p\n    file: f.yml\n",
        "include:\n- local: ci/a.yml\n- remote: https://x.test/a.yml\n",
        "include:   # shared\n    # a comment\n    - local: ci/a.yml\n    - template: Jobs/Build.gitlab-ci.yml\n",
    ],
)
def test_block_list_include_gets_one_item(block):
    text = "# head\n" + block + "\nbuild:\n  script:\n    - make\n"
    edit = merge_include(text, ["agentic"], GATES)
    assert edit.action == "extend-include" and edit.text is not None
    assert edit.text.count(TEMPLATE_RELPATH) == 1
    new_lines = set(edit.text.splitlines()) - set(text.splitlines())
    [added] = new_lines
    assert added.strip() == f"- local: {TEMPLATE_RELPATH}"
    first_item = next(line for line in text.splitlines() if line.lstrip().startswith("- "))
    assert added[: len(added) - len(added.lstrip())] == first_item[: len(first_item) - len(first_item.lstrip())]
    assert_only_the_include_changed(text, edit.text)


def test_already_included_is_a_noop():
    for text in (
        f"include:\n  - local: {TEMPLATE_RELPATH}\nbuild:\n  script: [make]\n",
        f"include:\n  - local: /{TEMPLATE_RELPATH}\n",
        f"include:\n  - {TEMPLATE_RELPATH}\n",
    ):
        edit = merge_include(text, ["agentic"], GATES)
        assert edit.action == "noop" and edit.text is None


@pytest.mark.parametrize(
    "text",
    [
        "include: ci/a.yml\nbuild:\n  script: [make]\n",
        "include: [{local: ci/a.yml}]\nbuild:\n  script: [make]\n",
        "include:\n  local: ci/a.yml\nbuild:\n  script: [make]\n",
        "include: {local: ci/a.yml}\nbuild:\n  script: [make]\n",
        "a: [unclosed\n",
        "- not\n- a mapping\n",
    ],
)
def test_scalar_flow_or_mapping_include_refuses_with_the_snippet(text):
    edit = merge_include(text, ["agentic"], GATES)
    assert edit.action == "refuse" and edit.text is None and edit.reason
    assert edit.snippet == INCLUDE_SNIPPET


def test_crlf_stays_crlf():
    text = EXISTING.replace("\n", "\r\n")
    edit = merge_include(text, ["agentic"], GATES)
    assert edit.text is not None and "\r\n" in edit.text
    assert edit.text.replace("\r\n", "").count("\n") == 0  # no bare LF was introduced
    assert_only_the_include_changed(EXISTING, edit.text.replace("\r\n", "\n"))
    listed = "include:\r\n  - local: ci/a.yml\r\nbuild:\r\n  script: [make]\r\n"
    added = merge_include(listed, ["agentic"], GATES).text
    assert added is not None and added.replace("\r\n", "").count("\n") == 0 and TEMPLATE_RELPATH in added


def test_a_document_start_marker_stays_first():
    text = "---\n# c\nbuild:\n  script: [make]\n"
    edit = merge_include(text, ["agentic"], GATES)
    assert edit.text is not None and edit.text.startswith("---\n")
    assert_only_the_include_changed(text, edit.text)


@pytest.mark.parametrize(
    "text",
    [
        "%YAML 1.1\n---\nbuild:\n  script: [make]\n",  # a directive: the include went above it
        "# c\n{build: {script: [make]}}\n",  # a flow mapping at the top: a block key before it breaks it
        "include:\n  - local: ci/a.yml\nbuild:\n  script: [make]\ninclude:\n  - local: ci/b.yml\n",  # the last one wins
    ],
)
def test_an_edit_that_does_not_parse_back_to_the_same_pipeline_refuses(text):
    """The parsed-document property is checked by the edit itself, not only by these tests: a form the textual edit
    gets wrong is refused with the snippet, never written (the file would break, or the include would not count)."""
    edit = merge_include(text, ["agentic"], GATES)
    assert edit.action == "refuse" and edit.text is None, edit.text
    assert "parse back" in edit.reason and edit.snippet == INCLUDE_SNIPPET


@pytest.mark.parametrize(
    ("text", "action"),
    [
        ("﻿# the pipeline\nbuild:\n  script: [make]\n", "insert-include"),
        ("﻿build:\n  script: [make]\n", "insert-include"),
        ("﻿include:\n  - local: ci/a.yml\nbuild:\n  script: [make]\n", "extend-include"),
    ],
)
def test_a_byte_order_mark_stays_first(text, action):
    edit = merge_include(text, ["agentic"], GATES)
    assert edit.action == action and edit.text is not None
    assert edit.text.startswith("﻿") and edit.text.count("﻿") == 1
    assert_only_the_include_changed(text, edit.text)


def test_only_post_jobs_warns():
    text = "stages: [.post]\nreport:\n  stage: .post\n  script: [make report]\n"
    edit = merge_include(text, ["agentic"], GATES)
    assert edit.action == "insert-include" and len(edit.warnings) == 1
    assert ".pre" in edit.warnings[0] and ".post" in edit.warnings[0] and "no pipeline" in edit.warnings[0]
    include_only = merge_include("include:\n  - local: a.yml\n", ["agentic"], GATES)
    assert len(include_only.warnings) == 1  # nothing of the project's own runs before `.post`
    assert merge_include(EXISTING, ["agentic"], GATES).warnings == ()  # real jobs in `test` and `build`


def test_the_include_is_idempotent_across_two_edits():
    first = merge_include(EXISTING, ["agentic"], GATES).text
    assert first is not None and merge_include(first, ["agentic"], GATES).action == "noop"


def test_created_file_passes_ci002(tmp_path):
    """The file init creates must satisfy the doctor row that checks tags (line 15)."""
    from l4.ci.render import render_gitlab_ci
    from l4.config.schema import L4Config
    from l4.doctor import checks_ci
    from l4.doctor.context import CmdResult, DoctorContext

    edit = merge_include(None, ["agentic"], GATES)
    assert edit.text is not None
    (tmp_path / ".l4/ci").mkdir(parents=True)
    (tmp_path / TEMPLATE_RELPATH).write_text(render_gitlab_ci())
    (tmp_path / ".gitlab-ci.yml").write_text(edit.text)
    ctx = DoctorContext(tmp_path, L4Config(), {}, lambda name: None, lambda *a, **k: CmdResult(0, "", ""), (3, 12, 0))
    result = checks_ci.CI_002.run(ctx)
    assert result.status == "pass", result.message


def test_the_created_test_job_runs_nothing_on_a_schedule_pipeline():
    import subprocess

    edit = merge_include(None, ["agentic"], GATES)
    assert edit.text is not None
    first = parse(edit.text)["test"]["script"][0]  # GitLab runs the lines of a job in one shell, so `exit 0` ends it
    script = f"{first}\necho went-on"
    sched = subprocess.run(["sh", "-c", script], env={"CI_PIPELINE_SOURCE": "schedule"}, capture_output=True, text=True)
    push = subprocess.run(["sh", "-c", script], env={"CI_PIPELINE_SOURCE": "push"}, capture_output=True, text=True)
    assert sched.returncode == 0 and "went-on" not in sched.stdout
    assert push.returncode == 0 and "went-on" in push.stdout
