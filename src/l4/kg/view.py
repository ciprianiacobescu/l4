"""A read-only view over the nodes and edges of the index, shared by `report`, `why` and `propose` (L4-KG-009,
L4-KG-010, L4-KG-012, design D8, D9, D10).

The index is a flat set of nodes and edges (design D4). The three readers need the same few questions answered: the
edges of one type, the edges that leave or reach one node, and the chain run -> attempt -> unit (a run belongs to the
attempt that has it, an attempt to its unit, a round to the attempt in its id). `View` answers them from dictionaries
built once. It sorts every list by the canonical text of the record, so the order of a result never depends on the
order the index was read in, and equal inputs give equal reports (design D8). It reads nothing but its arguments: no
file, no git, no network.

The helpers here fix the wording that the three readers share. `n_of(2, "unit")` is `n = 2 units`: every number that a
reader prints names its n (L4-KG-009). `clean_text` is the last step before any text leaves a reader: `redact_text`,
then `scrub_for_commit` (L4-KG-011). The index text is clean already; this covers a redaction rule added after the
index was built.
"""

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from l4.kg.model import Edge, Node, canonical_json
from l4.kg.normalise import KEY_SEPARATOR
from l4.redact import Redactor

_SEQ = re.compile(r"#(\d+)$")
UNKNOWN_UNIT = "(unknown unit)"


def event_seq(src: str) -> int | None:
    """The `seq` at the end of a ledger `src` (`<sha10>:<path>#<seq>`); None for a `verdict.json` pointer."""
    match = _SEQ.search(src)
    return int(match.group(1)) if match else None


def plural(n: int, one: str, many: str | None = None) -> str:
    return one if n == 1 else (many or one + "s")


def n_of(n: int, one: str, many: str | None = None) -> str:
    """`n = 2 units`, `n = 1 unit`: the form of every counted line."""
    return f"n = {n} {plural(n, one, many)}"


def display_key(key: str) -> str:
    """A recurrence key as text: the empty scenario part and its separator are dropped."""
    return key.removesuffix(KEY_SEPARATOR)


def short(text: str, limit: int = 120) -> str:
    one = " ".join(text.split())
    return one if len(one) <= limit else one[: limit - 1].rstrip() + "…"


def clean_text(text: str, redactor: Redactor | None) -> str:
    if redactor is None:
        return text
    return redactor.scrub_for_commit(redactor.redact_text(text))


def _order(item: Node | Edge) -> str:
    return canonical_json(item.to_dict())


class View:
    def __init__(self, nodes: Iterable[Node], edges: Iterable[Edge]) -> None:
        self.nodes: dict[str, Node] = {}
        for node in sorted(set(nodes), key=_order):
            self.nodes.setdefault(node.id, node)
        self.edges: list[Edge] = sorted(set(edges), key=_order)
        self._of_type: dict[str, list[Edge]] = defaultdict(list)
        self._out: dict[tuple[str, str], list[Edge]] = defaultdict(list)
        self._in: dict[tuple[str, str], list[Edge]] = defaultdict(list)
        for edge in self.edges:
            self._of_type[edge.type].append(edge)
            self._out[(edge.from_id, edge.type)].append(edge)
            self._in[(edge.to_id, edge.type)].append(edge)
        self._run_attempt: dict[str, str] = {}
        for edge in self._of_type["HAS_RUN"]:
            self._run_attempt.setdefault(edge.to_id, edge.from_id)

    # --- lookups ---------------------------------------------------------------------------------------------------

    def of_type(self, type: str) -> list[Edge]:
        return self._of_type.get(type, [])

    def out(self, node_id: str, type: str) -> list[Edge]:
        return self._out.get((node_id, type), [])

    def into(self, node_id: str, type: str) -> list[Edge]:
        return self._in.get((node_id, type), [])

    def nodes_of(self, type: str) -> list[Node]:
        return [node for node in self.nodes.values() if node.type == type]

    def attr(self, node_id: str, key: str, default: Any = None) -> Any:
        node = self.nodes.get(node_id)
        return node.attrs.get(key, default) if node is not None else default

    # --- the chain run -> attempt -> unit --------------------------------------------------------------------------

    def attempt_of_run(self, run_id: str) -> str | None:
        return self._run_attempt.get(run_id)

    def unit_of_attempt(self, attempt_id: str) -> str:
        unit = self.attr(attempt_id, "unit")
        return unit if isinstance(unit, str) and unit else attempt_id.rsplit("@", 1)[0]

    def unit_of_run(self, run_id: str) -> str:
        attempt = self.attempt_of_run(run_id)
        return self.unit_of_attempt(attempt) if attempt is not None else UNKNOWN_UNIT

    def attempt_of_round(self, round_id: str) -> str:
        return round_id.split("#", 1)[0]

    def unit_of_round(self, round_id: str) -> str:
        return self.unit_of_attempt(self.attempt_of_round(round_id))

    def rounds_of_finding(self, finding_id: str) -> list[Edge]:
        return self.into(finding_id, "RAISED")

    # --- blame -----------------------------------------------------------------------------------------------------

    def blame_of(self, from_id: str, *, of: str | None = None, src: str | None = None) -> list[str]:
        """The blame values (`security`, `spec`, ...) of the CLASSIFIED edges that leave `from_id`; `of` and `src`
        narrow them (a run has one CLASSIFIED per stop and failure, told apart by `of` and `src`)."""
        values = []
        for edge in self.out(from_id, "CLASSIFIED"):
            if (of is None or edge.attrs.get("of") == of) and (src is None or edge.src == src):
                values.append(edge.to_id.removeprefix("blame:"))
        return values


def count_lines(counter: Mapping[str, int]) -> str:
    """`red n = 2, green n = 1`: the counts of a small table, largest first, then by name."""
    ordered = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    return ", ".join(f"{name} n = {count}" for name, count in ordered) or "none (n = 0)"


def joined(names: Sequence[str], limit: int = 10) -> str:
    shown = ", ".join(names[:limit])
    return shown + (f", +{len(names) - limit} more" if len(names) > limit else "")
