import hashlib
import re
from datetime import date
from pathlib import Path

import pytest

from l4.memory.lessons import (
    EMPTY_TEMPLATE,
    Lesson,
    LessonsFile,
    lesson_id,
    lint,
    parse_lessons,
    render_lessons,
    select_lessons,
    write_lessons,
)

SPEC = Path(__file__).resolve().parents[3] / "docs" / "SPEC.md"


def spec_example() -> str:
    text = SPEC.read_text(encoding="utf-8")
    start = text.index("**L4-MEM-001**")
    return re.search(r"```markdown\n(.*?)\n```", text[start:], re.S).group(1) + "\n"


def make(key: str, **kw) -> Lesson:
    return Lesson(id=lesson_id(key), title=kw.pop("title", key), dedupe_key=key, **kw)


def test_lesson_id_is_sha256_prefix_of_key():
    expected = "L-" + hashlib.sha256(b"ui-criterion-without-e2e-test").hexdigest()[:8]
    assert lesson_id("ui-criterion-without-e2e-test") == expected == "L-09421538"
    assert lesson_id("  ui-criterion-without-e2e-test\n") == expected  # stripped, nothing else normalised
    assert lesson_id("UI-criterion-without-e2e-test") != expected  # no case folding


def test_spec_example_parses():
    result = parse_lessons(spec_example())
    assert result.problems == []
    (lesson,) = result.file.lessons
    assert lesson.id == "L-3f9a1c2e"
    assert lesson.title == "Playwright selectors must use data-testid"
    assert lesson.scope_globs == ("web/**",) and lesson.scope_kinds == ("ui",)
    assert lesson.source == "verifier finding F-002 (openspec:add-login round 1), 2026-10-03"
    assert lesson.dedupe_key == "e2e-selector-brittle"
    assert lesson.supersedes == "L-77b0d415"
    assert lesson.reinforced_count == 1 and lesson.last_reinforced is None
    assert lesson.body.startswith("Use `getByTestId`") and lesson.body.endswith("twice.")


def test_crlf_parses_like_lf():
    lf = spec_example()
    assert parse_lessons(lf.replace("\n", "\r\n")).file == parse_lessons(lf).file


def test_empty_header_only_and_missing_header_files():
    assert parse_lessons("").file.lessons == [] and parse_lessons("").problems == []
    assert parse_lessons("\n \n").problems == []
    header_only = parse_lessons(EMPTY_TEMPLATE)
    assert header_only.file.lessons == [] and header_only.problems == []
    headless = parse_lessons("## L-3f9a1c2e · T\n- **Dedupe key:** k\nbody\n")
    assert headless.file.lessons == [] and "no lessons header" in headless.problems[0].message


def test_malformed_section_skipped_and_v2_header_refused():
    text = (
        "<!-- l4:lessons v1 -->\n"
        "## L-3f9a1c2e · Good\n- **Dedupe key:** good\nbody one\n\n"
        "## not a lesson heading\n- **Dedupe key:** x\n\n"
        "## L-aaaaaaaa · No key\n- **Source:** nowhere\nbody\n\n"
        "## L-bbbbbbbb · Bad count\n- **Dedupe key:** y\n- **Reinforced:** many\n\n"
        "## L-cccccccc · Also good\n- **Dedupe key:** z\nbody two\n"
    )
    result = parse_lessons(text)
    assert [lesson.id for lesson in result.file.lessons] == ["L-3f9a1c2e", "L-cccccccc"]
    assert [p.line for p in result.problems] == [6, 9, 13]
    v2 = parse_lessons("<!-- l4:lessons v2 -->\n## L-3f9a1c2e · T\n- **Dedupe key:** k\nb\n")
    assert v2.file.lessons == []
    assert "unsupported lessons format v2" in v2.problems[0].message


@pytest.mark.parametrize("separator", [" · ", ", "])
def test_reinforced_bullet_reads_both_spellings_and_writes_the_design_form(separator):
    text = (
        f"<!-- l4:lessons v1 -->\n## L-3f9a1c2e · T\n- **Dedupe key:** k\n- **Reinforced:** 3{separator}2026-10-04\nb\n"
    )
    result = parse_lessons(text)
    assert result.problems == []
    (lesson,) = result.file.lessons
    assert (lesson.reinforced_count, lesson.last_reinforced) == (3, date(2026, 10, 4))
    assert "- **Reinforced:** 3 · 2026-10-04\n" in render_lessons(LessonsFile([lesson]))


def test_scoped_and_unscoped_selected():
    web = make("web-rule", scope_globs=("web/**",))
    anywhere = make("everywhere")
    docs = make("docs-rule", scope_globs=("docs/*.md", "README.md"))
    ui_kind = make("kind-rule", scope_globs=("web/**",), scope_kinds=("ui",))
    file = LessonsFile([web, anywhere, docs, ui_kind])
    by_id = lambda *ls: [x.id for x in sorted(ls, key=lambda x: x.id)]  # noqa: E731
    assert [x.id for x in select_lessons(file, ["web/login.tsx"])] == by_id(web, anywhere)
    assert [x.id for x in select_lessons(file, ["README.md"])] == by_id(anywhere, docs)
    assert [x.id for x in select_lessons(file, [])] == by_id(anywhere)
    assert [x.id for x in select_lessons(file, ["web/a.tsx"], ["ui"])] == by_id(web, anywhere, ui_kind)


def test_render_is_canonical_and_lossless():
    b = make(
        "b-key", scope_globs=("web/**", "app/*.tsx"), scope_kinds=("ui", "css"), source="s", supersedes="L-77b0d415",
        reinforced_count=4, last_reinforced=date(2026, 10, 4), body="line one\n\nline two",
        extra_bullets=(("Owner", "someone"),),
    )  # fmt: skip
    a = make("a-key", body="- **Looks:** like a bullet\nrest")
    c = make("c-key")
    file = LessonsFile([b, a, c])
    text = render_lessons(file)
    assert "\r" not in text and text.endswith("\n") and not text.endswith("\n\n")
    assert [m for m in re.findall(r"^## (L-\w+)", text, re.M)] == sorted(x.id for x in file.lessons)
    again = parse_lessons(text)
    assert again.problems == []
    assert sorted(again.file.lessons, key=lambda x: x.id) == sorted(file.lessons, key=lambda x: x.id)
    assert render_lessons(again.file) == text
    assert render_lessons(parse_lessons(spec_example()).file).startswith(EMPTY_TEMPLATE.splitlines()[0])


def test_write_is_atomic_and_reports_no_change(tmp_path: Path):
    path = tmp_path / ".serena" / "memories" / "harness" / "lessons.md"
    file = LessonsFile([make("k", body="b")])
    assert write_lessons(path, file) is True
    assert path.read_text(encoding="utf-8") == render_lessons(file)
    assert write_lessons(path, file) is False
    assert [p.name for p in path.parent.iterdir()] == ["lessons.md"]  # no temp file left behind


def test_lint_reports_duplicates_wrong_ids_scopes_and_caps():
    good = make("good")
    wrong = Lesson(id="L-deadbeef", title="t", dedupe_key="other")
    bad_scope = make("scopes", scope_globs=("../x", "/abs", "ok/**"))
    dangling = make("dangling", supersedes="L-00000000")
    archived = make("archived-ref", supersedes="L-11111111")
    file = LessonsFile([good, good, wrong, bad_scope, dangling, archived])
    messages = [p.message for p in lint(file, max_lessons=3, max_bytes=100, archived_ids={"L-11111111"})]
    joined = "\n".join(messages)
    assert "duplicate lesson id" in joined
    assert f"expected {lesson_id('other')}" in joined
    assert "invalid scope glob '../x'" in joined and "invalid scope glob '/abs'" in joined and "ok/**" not in joined
    assert "supersedes unknown lesson L-00000000" in joined and "L-11111111" not in joined
    assert "exceed memory.max_lessons (3)" in joined and "exceed memory.max_bytes (100)" in joined
    assert lint(LessonsFile([good]), max_lessons=40, max_bytes=12000) == []
