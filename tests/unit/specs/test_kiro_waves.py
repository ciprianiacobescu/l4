import logging

from l4.specs.kiro import order_leaves, parse_kiro_tasks, read_waves, with_waves

TASKS = (
    b"- [ ] 1. P1\n  - [ ] 1.1 a\n  - [ ] 1.2 b\n- [ ] 2. P2\n  - [ ] 2.1 c\n  - [ ] 2.2 d\n  - [ ]* 2.3 opt\n"
    b"  - [x] 2.4 done\n"
)


def graph(body: str) -> str:
    return f"# Tasks\n\n## Task Dependency Graph\n\n```json\n{body}\n```\n"


def keys(tasks):
    return [t.key for t in tasks]


def test_valid_graph_sets_waves_and_reorders():
    waves = read_waves(graph('{"waves":[{"id":0,"tasks":["2.1","1.1"]},{"id":1,"tasks":["1.2","2.2"]}]}'))
    assert waves is not None
    tasks = with_waves(parse_kiro_tasks(TASKS), waves)
    assert {t.key: t.wave for t in tasks if t.wave is not None} == {"2.1": 0, "1.1": 0, "1.2": 1, "2.2": 1}
    assert keys(order_leaves(tasks)) == ["1.1", "2.1", "1.2", "2.2"]  # wave first, document order inside a wave


def test_waves_fallback_and_missing_leaf_insertion(caplog):
    tasks = parse_kiro_tasks(TASKS)
    # SCN-KSP-N3: broken JSON -> document order and a warning
    with caplog.at_level(logging.WARNING, logger="l4.spec"):
        assert read_waves(graph('{"waves": [')) is None
    assert "Task Dependency Graph" in caplog.text
    assert keys(order_leaves(tasks)) == ["1.1", "1.2", "2.1", "2.2"]  # optional 2.3 and done 2.4 are not pending leaves
    # SCN-KSP-N4: 1.2 is missing from the graph; it stays between its neighbours
    waves = read_waves(graph('{"waves":[{"id":0,"tasks":["2.1"]},{"id":1,"tasks":["1.1","2.2"]}]}'))
    assert keys(order_leaves(with_waves(tasks, waves))) == ["2.1", "1.1", "1.2", "2.2"]


def test_leaf_before_every_listed_leaf_is_inserted_first():
    tasks = with_waves(parse_kiro_tasks(TASKS), read_waves(graph('{"waves":[{"id":0,"tasks":["2.2","2.1"]}]}')))
    assert keys(order_leaves(tasks)) == ["1.1", "1.2", "2.1", "2.2"]


def test_invalid_shapes_are_rejected():
    bad = [
        '{"waves":[{"id":0,"tasks":["1.1"]},{"id":0,"tasks":["1.2"]}]}',  # repeated id
        '{"waves":[{"id":0,"tasks":["1.1"]},{"id":1,"tasks":["1.1"]}]}',  # task in two waves
        '{"waves":[{"id":"0","tasks":["1.1"]}]}',
        '{"waves":[{"id":0,"tasks":[1.1]}]}',
        '{"waves":{"id":0}}',
        "[]",
    ]
    for body in bad:
        assert read_waves(graph(body)) is None, body
    assert read_waves("# Tasks\n\n## Task Dependency Graph\n\nno block\n") is None


def test_unknown_task_ids_invalidate_the_graph_when_the_tasks_are_known(caplog):
    body = '{"waves":[{"id":0,"tasks":["9.9"]}]}'
    assert read_waves(graph(body)) is not None
    with caplog.at_level(logging.WARNING, logger="l4.spec"):
        assert read_waves(graph(body), known={"1.1"}) is None
    assert "9.9" in caplog.text


def test_no_graph_section_is_silent(caplog):
    with caplog.at_level(logging.WARNING, logger="l4.spec"):
        assert read_waves("# Tasks\n- [ ] 1.1 x\n") is None
    assert caplog.text == ""


def test_graph_block_after_another_section_is_ignored():
    text = '## Task Dependency Graph\n\nprose\n\n## Notes\n\n```json\n{"waves":[]}\n```\n'
    assert read_waves(text) is None
