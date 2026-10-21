import pytest

from l4.specs.openspec import parse_openspec_tasks


def cli_view(tasks):
    """What `instructions apply --json` reports: progress counts every checkbox, tasks[] only those with text."""
    done = sum(t.done for t in tasks)
    return (
        {"total": len(tasks), "complete": done, "remaining": len(tasks) - done},
        [(t.line, t.done, t.title) for t in tasks if t.title],
    )


@pytest.mark.parametrize("fixture", ["apply-task-grammar.json", "apply-task-grammar-crlf.json"])
def test_parser_agrees_with_the_recorded_cli_on_the_grammar_file(fixture, recorded, grammar_lf, grammar_crlf):
    body = grammar_crlf if "crlf" in fixture else grammar_lf
    expected = recorded(fixture)
    progress, listed = cli_view(parse_openspec_tasks(body))
    assert progress == expected["progress"] == {"total": 29, "complete": 8, "remaining": 21}
    assert listed == [(t["line"], t["done"], t["description"]) for t in expected["tasks"]]


def test_only_x_counts_as_done_and_link_bullets_excluded():
    data = "\n".join(
        [
            "- [ ] a", "- [x] b", "- [X] c", "- [-] d", "- [~] e", "- [] f", "- [ x] g",
            "- [A](https://example.com) link", "- [WIP] word", "- [ ](https://example.com) blank",
        ]
    ).encode()  # fmt: skip
    by_title = {t.title: t for t in parse_openspec_tasks(data)}
    assert {k: v.done for k, v in by_title.items()} == {
        "a": False, "b": True, "c": True, "d": False, "e": False, "f": False, "g": True,
        "(https://example.com) blank": False,
    }  # fmt: skip
    assert not any("link" in title or "word" in title for title in by_title)  # (`Task.links` is a field name now)


def test_task_keys_follow_the_spec_regex_not_the_cli_ordinal():
    data = b"- [ ] 1.1 first\n- [ ] 2. Login\n  - [x] 2.1 child\n- [ ] 3.1a lettered\n- [ ] no number\n- [ ]\n"
    tasks = parse_openspec_tasks(data)
    assert [(t.key, t.number, t.depth) for t in tasks] == [
        ("1.1", "1.1", 0), ("L2", None, 0), ("2.1", "2.1", 2), ("3.1a", "3.1a", 0), ("L5", None, 0), ("L6", None, 0),
    ]  # fmt: skip
    assert tasks[-1].title == ""  # a text-less checkbox still counts in progress


def test_marker_offsets_are_bytes_and_only_exact_single_byte_brackets_have_one():
    bom = "\ufeff".encode()
    data = bom + "- [ ] é first\n".encode() + b"- [x] done\n- [] empty\n- [ x] padded\n  - [ ]* 1.1 optional\n- [ ]"
    tasks = parse_openspec_tasks(data)
    assert [t.title for t in tasks] == ["é first", "done", "empty", "padded", "* 1.1 optional", ""]
    assert [t.marker_offset is None for t in tasks] == [False, False, True, True, False, False]
    assert tasks[0].marker_offset == len(bom) + 3
    for task in tasks:
        if task.marker_offset is not None:
            assert data[task.marker_offset : task.marker_offset + 1] == task.marker_char.encode()
    # a star after the bracket makes a required task with a writable bracket (L4-OSP-004)
    assert tasks[4].marker_char == " " and not tasks[4].done


def test_depth_ignores_a_leading_bom():
    tasks = parse_openspec_tasks("\ufeff- [ ] 1.1 a\n\t- [ ] 1.2 b\n    - [ ] 1.3 c".encode())
    assert [t.depth for t in tasks] == [0, 1, 4]
