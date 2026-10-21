from l4.specs.kiro import KIRO_TASK_RE, parse_kiro_tasks


def parse(text: str, newline: str = "\n"):
    return parse_kiro_tasks(text.replace("\n", newline).encode())


def test_kiro_grammar_and_space_before_star():
    tasks = parse(
        "- [ ] 1. Parent\n"
        "  - [x] 1.1 done\n"
        "  - [X] 1.2 DONE\n"
        "  - [-] 1.3 in progress\n"
        "  - [~] 1.4 queued\n"
        "  - [ ]* 1.5 optional\n"
        "  - [ ]\\* 1.6 escaped star\n"
        "  - [ ] * 1.7 Write docs\n"
        "1. [ ] ordered bullet\n"
        "- [] empty brackets\n"
        "- [ ]no space\n"
        "- [ ]\n"
        "* [ ] 2.1 star bullet\n"
        "+ [ ] 2.2 plus bullet\n"
    )
    by_key = {t.key: t for t in tasks}
    assert list(by_key) == ["1", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "L8", "2.1", "2.2"]
    assert [by_key[k].done for k in ("1.1", "1.2", "1.3", "1.4")] == [True, True, False, False]
    assert [by_key[k].marker_char for k in ("1.1", "1.3", "1.4", "1")] == ["x", "-", "~", " "]
    assert [by_key[k].optional for k in ("1.5", "1.6", "L8", "1.1")] == [True, True, False, False]
    assert by_key["L8"].title == "* 1.7 Write docs"  # SCN-TMW-03: a space before `*` is not optional, and the title
    # no longer starts with a number, so the key is the line
    assert by_key["1.5"].title == "1.5 optional"


def test_ordered_bullets_and_empty_brackets_are_not_tasks():
    tasks = parse("1. [ ] Draft\n- [] Review\n- [ ] 3.1 Ship\n")
    assert [t.key for t in tasks] == ["3.1"]  # SCN-KSP-N1


def test_regex_is_kiros_verbatim():
    assert KIRO_TASK_RE.pattern == r"^(\s*)([-*+])\s+\[([ xX\-~])\](\\?\*?)\s+(.+)$"


def test_marker_offsets_are_byte_offsets_with_crlf_bom_and_multibyte():
    text = "﻿- [ ] 1. éé parent\n  - [ ] 1.1 child ☃\n- [ ] 2. last"
    data = text.replace("\n", "\r\n").encode()
    for task in parse_kiro_tasks(data):
        assert data[task.marker_offset - 1 : task.marker_offset + 2] == b"[ ]"


def test_hierarchy_by_number_then_indent():
    numbered = parse("- [ ] 1. A\n- [ ] 1.1 flat child\n- [ ] 1.1.1 grandchild\n- [ ] 2. B\n")
    assert [(t.key, t.depth) for t in numbered] == [("1", 0), ("1.1", 1), ("1.1.1", 2), ("2", 0)]
    indented = parse("- [ ] parent\n  - [ ] child\n    - [ ] grandchild\n  - [ ] child two\n- [ ] sibling\n")
    assert [t.depth for t in indented] == [0, 1, 2, 1, 0]
    assert [t.key for t in indented] == ["L1", "L2", "L3", "L4", "L5"]
    tabs = parse("- [ ] parent\n\t- [ ] child\n")
    assert [t.depth for t in tabs] == [0, 1]


def test_unnumbered_task_in_a_numbered_list_follows_indentation():
    tasks = parse("- [ ] 1. A\n  - [ ] 1.1 B\n    - [ ] plain note task\n- [ ] 2. C\n")
    assert [t.depth for t in tasks] == [0, 1, 2, 0]


def test_branch_under_an_optional_task_is_optional():
    tasks = parse("- [ ]* 1. Extras\n  - [ ] 1.1 inside\n- [ ] 2. Core\n  - [ ] 2.1 leaf\n")
    assert [t.optional for t in tasks] == [True, True, False, False]


def test_requirement_links_are_read_below_the_task():
    tasks = parse(
        "- [ ] 1.1 A\n  - _Requirements: 2.1, 3.3_\n- [ ] 1.2 B\n- _Requirements: 4.4_\n  prose\n"
        "- [ ] 1.3 C\n  - _Requirements: 1.1, 1.1_\n\n## Heading\n_Requirements: 9.9_\n"
    )
    assert [t.links for t in tasks] == [("2.1", "3.3"), ("4.4",), ("1.1",)]


def test_empty_file_and_no_trailing_newline():
    assert parse_kiro_tasks(b"") == []
    assert [t.key for t in parse_kiro_tasks(b"- [ ] 1.1 last line")] == ["1.1"]
