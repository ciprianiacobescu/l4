"""A task that delivers documentation which a test glob covers (test-path-intake 1.1; L4-YOLO-094; SCN-YOLO-256 to
259 at the function level)."""

from pathlib import Path

from l4.config.defaults import SCOPE_EXEMPT, TEST_GLOBS, TEST_SUPPORT_GLOBS
from l4.config.schema import L4Config
from l4.implementer.guards import _matches
from l4.specs.base import Framework, UnitRef
from l4.yolo.forbidden import PathFinding
from l4.yolo.testpaths import test_path_named as named  # not collected as a test

FIXTURES = "docs/waitlist/fixtures/*.json"


def unit(tmp_path: Path, tasks: str) -> UnitRef:
    folder = tmp_path / "openspec" / "changes" / "add-x"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "tasks.md").write_text(tasks, encoding="utf-8")
    return UnitRef(Framework.OPENSPEC, "add-x", folder)


def tasks_of(*lines: str) -> str:
    return "## 2. Docs\n\n" + "\n".join(lines) + "\n"


def found(ref: UnitRef, test=TEST_GLOBS, support=TEST_SUPPORT_GLOBS, exempt=SCOPE_EXEMPT) -> list[PathFinding]:
    return named(ref, test, support, exempt)


def test_a_docs_fixture_task_is_a_warning_with_both_fixes(tmp_path):  # SCN-YOLO-256
    ref = unit(tmp_path, tasks_of(f"- [ ] 2.1 Write the client fixtures `{FIXTURES}`"))
    (finding,) = found(ref)
    assert not finding.blocker and finding.code == "test_path"
    assert finding.path == "docs/waitlist/fixtures/" and finding.rule == "**/fixtures/**"
    assert finding.body.startswith("task 2.1 names docs/waitlist/fixtures/, which the test glob **/fixtures/** matches")
    assert "[test-infra]" in finding.body and "tdd.test_globs" in finding.body
    assert "tdd.test_support_globs" in finding.body and "base branch" in finding.body
    assert finding.message.startswith("test_path: task 2.1 names")


def test_a_file_token_is_matched_as_the_file(tmp_path):
    ref = unit(tmp_path, tasks_of("- [ ] 2.1 Add docs/x/fixtures/a.json to the docs"))
    (finding,) = found(ref)
    assert finding.path == "docs/x/fixtures/a.json" and finding.rule == "**/fixtures/**"


def test_a_directory_token_without_a_slash_counts_as_its_directory(tmp_path):
    ref = unit(tmp_path, tasks_of("- [ ] 2.1 Fill docs/x/fixtures with the samples"))
    assert [f.path for f in found(ref)] == ["docs/x/fixtures"]


def test_a_markdown_file_that_a_test_glob_matches_is_a_warning(tmp_path):
    ref = unit(tmp_path, tasks_of("- [ ] 2.1 Write `docs/test_plan.md`"))
    (finding,) = found(ref)
    assert finding.path == "docs/test_plan.md" and finding.rule == "**/test_*.*"


def test_a_support_glob_is_named_as_such(tmp_path):
    ref = unit(tmp_path, tasks_of("- [ ] 2.1 Write `docs/x/fixtures/a.json`"))
    (finding,) = found(ref, test=("**/tests/**",))
    assert finding.rule == "**/fixtures/**" and "the test support glob **/fixtures/** matches" in finding.body


def test_a_test_infra_task_gives_nothing(tmp_path):  # SCN-YOLO-257
    ref = unit(tmp_path, tasks_of(f"- [ ] 2.1 [test-infra] Write the client fixtures `{FIXTURES}`"))
    assert found(ref) == []


def test_narrowed_globs_give_nothing(tmp_path):  # SCN-YOLO-257: the effective globs replace the defaults
    ref = unit(tmp_path, tasks_of(f"- [ ] 2.1 Write the client fixtures `{FIXTURES}`"))
    narrowed = tuple(g for g in TEST_GLOBS if g != "**/fixtures/**")
    support = tuple(g for g in TEST_SUPPORT_GLOBS if g != "**/fixtures/**")
    assert found(ref, test=narrowed, support=support) == []
    cfg = L4Config.model_validate({"tdd": {"test_globs": ["**/tests/**"], "test_support_globs": []}})
    assert found(ref, test=cfg.tdd.test_globs, support=cfg.tdd.test_support_globs) == []


def test_extra_globs_are_part_of_the_effective_globs(tmp_path):
    ref = unit(tmp_path, tasks_of("- [ ] 2.1 Write `docs/golden/a.txt`"))
    cfg = L4Config.model_validate({"tdd": {"extra_test_globs": ["**/golden/**"]}})
    assert [f.rule for f in found(ref, test=cfg.tdd.test_globs, support=cfg.tdd.test_support_globs)] == ["**/golden/**"]


def test_an_ordinary_test_path_gives_nothing(tmp_path):  # SCN-YOLO-258
    ref = unit(tmp_path, tasks_of("- [ ] 2.1 Add `tests/fixtures/users.json`", "- [ ] 2.2 Add `src/app/test_x.py`"))
    assert found(ref) == []


def test_a_docs_path_no_test_glob_matches_gives_nothing(tmp_path):
    ref = unit(tmp_path, tasks_of("- [ ] 2.1 Write `docs/waitlist/guide.md` and `docs/api/`"))
    assert found(ref) == []


def test_a_ticked_task_gives_nothing(tmp_path):  # SCN-YOLO-259
    ref = unit(tmp_path, tasks_of("- [x] 2.1 Write `docs/x/fixtures/a.json`"))
    assert found(ref) == []


def test_a_line_that_says_not_to_touch_the_path_gives_nothing(tmp_path):  # SCN-YOLO-259
    ref = unit(tmp_path, tasks_of("- [ ] 2.1 Add the guide; do not change `docs/x/fixtures/a.json`"))
    assert found(ref) == []


def test_without_scope_exempt_globs_or_test_globs_there_is_nothing(tmp_path):
    ref = unit(tmp_path, tasks_of("- [ ] 2.1 Write `docs/x/fixtures/a.json`"))
    assert found(ref, exempt=()) == [] and found(ref, test=(), support=()) == []


def test_one_finding_per_path_of_a_task(tmp_path):
    ref = unit(tmp_path, tasks_of("- [ ] 2.1 Write docs/x/fixtures/a.json, then check docs/x/fixtures/a.json again"))
    assert len(found(ref)) == 1


def test_it_uses_the_freezes_matcher(tmp_path):
    ref = unit(tmp_path, tasks_of("- [ ] 2.1 Write `docs/x/fixtures/a.json` and `docs/test_plan.md`"))
    for finding in found(ref):
        probe = finding.path
        assert _matches(TEST_GLOBS, probe) and _matches(SCOPE_EXEMPT, probe)


# --- review fixes ---


def test_test_code_under_docs_is_not_documentation(tmp_path):
    ref = unit(tmp_path, tasks_of("- [ ] 2.1 Add `docs/tests/test_examples.py` and `docs/conftest.py`"))
    assert found(ref) == []
    ref = unit(
        tmp_path, tasks_of("- [ ] 2.1 Add docs/e2e/app.spec.ts, docs/x/fixtures/seed.go and docs/x/fixtures/*.py")
    )
    assert found(ref) == []


def test_docs_and_data_under_a_test_glob_still_warn(tmp_path):
    ref = unit(tmp_path, tasks_of("- [ ] 2.1 Write `docs/test_plan.md` and `docs/x/fixtures/a.json`"))
    assert [f.path for f in found(ref)] == ["docs/test_plan.md", "docs/x/fixtures/a.json"]


def test_every_matching_glob_is_named_once_in_list_order(tmp_path):
    ref = unit(tmp_path, tasks_of("- [ ] 2.1 Write `docs/tests/fixtures/a.json`"))
    (finding,) = found(ref)
    assert finding.rule == "**/tests/**, **/fixtures/**"
    assert "the test globs **/tests/**, **/fixtures/** match" in finding.body
    assert "leave all of them out" in finding.body
    (single,) = found(unit(tmp_path, tasks_of("- [ ] 2.1 Write `docs/x/fixtures/a.json`")))
    assert single.rule == "**/fixtures/**" and "the test glob **/fixtures/** matches" in single.body
    assert "leave all of them out" not in single.body


def test_globs_from_both_lists_are_named(tmp_path):
    ref = unit(tmp_path, tasks_of("- [ ] 2.1 Write `docs/tests/mocks/a.json`"))
    (finding,) = found(ref)
    assert finding.rule == "**/tests/**, **/mocks/**"
    assert "the test and test support globs **/tests/**, **/mocks/** match" in finding.body


def test_a_glob_token_keeps_its_file_pattern(tmp_path):
    ref = unit(tmp_path, tasks_of("- [ ] 2.1 Write `docs/x/fixtures/*.json`"))
    (finding,) = found(ref, test=("**/fixtures/*.json",), support=())
    assert finding.path == "docs/x/fixtures/" and finding.rule == "**/fixtures/*.json"
    assert found(ref, test=("**/fixtures/*.csv",), support=()) == []  # another extension is not covered
    ref = unit(tmp_path, tasks_of("- [ ] 2.1 Write the pages `docs/x/test_*.md`"))
    (finding,) = found(ref, test=("docs/x/test_*.md",), support=())
    assert finding.path == "docs/x/" and finding.rule == "docs/x/test_*.md"
    assert [f.path for f in found(ref)] == ["docs/x/"]  # the defaults' `**/test_*.*` covers it too


def test_a_negated_glob_token_gives_nothing(tmp_path):
    ref = unit(tmp_path, tasks_of("- [ ] 2.1 Add the guide; do not write `docs/x/fixtures/*.json`"))
    assert found(ref) == []


def test_the_function_is_not_collected_as_a_test():
    from l4.yolo import testpaths

    assert testpaths.test_path_named.__test__ is False
