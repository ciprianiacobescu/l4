"""Nodes, edges and the canonical JSONL writer (L4-KG-003, L4-KG-005, SCN-KG-04)."""

import random

import pytest

from l4.kg.model import EDGE_TYPES, NODE_TYPES, Edge, Node, canonical_json, jsonl_bytes


def _nodes():
    return [
        Node("openspec:a", "unit", {"framework": "openspec", "name": "a"}),
        Node("openspec:b", "unit", {"name": "b", "framework": "openspec"}),
        Node("L-09421538", "lesson", {"title": "Playwright tests belong under e2e/ — ünï"}),
        Node("blame:spec", "blame"),
    ]


def _edges():
    ledger = "abc1234567:.l4/ledger/r.jsonl"
    return [
        Edge("HAS_RUN", "openspec:a", "r-20261005T0815Z-5946", f"{ledger}#3", "2026-10-05T08:15:00Z"),
        Edge("INJECTED", "r-20261005T0815Z-5946", "L-09421538", f"{ledger}#4", "2026-10-05T08:16:00Z",
             {"task": "1.1", "role": "red"}),
        Edge("VERDICT", "openspec:a@0#round-1", "openspec:a@0", "abc1234567:.l4/evidence/round-1/verdict.json#/verdict",
             "2026-10-05T09:00:00Z", {"verdict": "PASS"}),
    ]  # fmt: skip


def test_two_writes_of_the_same_set_in_a_different_order_are_byte_identical():
    nodes, edges = _nodes(), _edges()
    first_n, first_e = jsonl_bytes(nodes), jsonl_bytes(edges)
    for seed in range(5):
        shuffled_n, shuffled_e = nodes[:], edges[:]
        random.Random(seed).shuffle(shuffled_n)
        random.Random(seed).shuffle(shuffled_e)
        assert jsonl_bytes(shuffled_n) == first_n
        assert jsonl_bytes(shuffled_e) == first_e


def test_the_bytes_are_sorted_keys_sorted_lines_lf_utf8_and_not_escaped():
    data = jsonl_bytes(_nodes())
    assert b"\r" not in data and data.endswith(b"\n") and not data.endswith(b"\n\n")
    text = data.decode("utf-8")
    assert "ünï" in text and "\\u" not in text
    lines = text.splitlines()
    assert lines == sorted(lines)
    assert '{"attrs":{"framework":"openspec","name":"a"},"id":"openspec:a","type":"unit"}' in lines


def test_a_repeated_record_is_one_line_and_an_empty_set_is_no_bytes():
    node = _nodes()[0]
    assert jsonl_bytes([node, node]) == jsonl_bytes([node])
    assert jsonl_bytes([]) == b""


def test_the_order_of_attrs_does_not_change_the_bytes():
    assert jsonl_bytes([Node("u", "unit", {"a": 1, "b": 2})]) == jsonl_bytes([Node("u", "unit", {"b": 2, "a": 1})])


def test_a_record_round_trips_through_its_dict():
    for item in _nodes():
        assert Node.from_dict(item.to_dict()) == item
    for edge in _edges():
        assert Edge.from_dict(edge.to_dict()) == edge


def test_records_are_frozen_hashable_and_equal_by_value():
    node = Node("u", "unit", {"a": [1, 2]})
    with pytest.raises(AttributeError):
        node.id = "x"  # type: ignore[misc]
    assert node == Node("u", "unit", {"a": [1, 2]}) and len({node, Node("u", "unit", {"a": [1, 2]})}) == 1
    edge = _edges()[0]
    assert len({edge, Edge.from_dict(edge.to_dict())}) == 1


def test_an_unknown_node_or_edge_type_is_refused():
    with pytest.raises(ValueError, match="node type"):
        Node("x", "bogus")
    with pytest.raises(ValueError, match="edge type"):
        Edge("BOGUS", "a", "b", "s", "t")


def test_the_types_are_those_of_design_d4():
    nodes = "unit attempt run round finding criterion capability lesson question stop profile failure_class"
    nodes += " recurrence_key gate blame"
    edges = "HAS_ATTEMPT HAS_RUN HAS_ROUND VERDICT RAISED ABOUT IN_CAPABILITY KEYED GATE_FAILED INJECTED"
    edges += " ATTEMPT_FAILED USED_PROFILE ASKED STOPPED RETRIED RESTARTED CLASSIFIED"
    assert set(nodes.split()) == NODE_TYPES
    assert set(edges.split()) == EDGE_TYPES


def test_a_value_json_cannot_hold_is_refused_not_written_as_nan():
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})
