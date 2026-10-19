"""The label set that setup creates (delegate-answers 12.1; L4-CLR-004): `needs-person` is in it, next to
`needs-answers`, under the configured prefix."""

from l4.setup.github import managed_labels
from l4.state.lifecycle import Phase


def test_needs_person_is_in_the_label_set():
    labels = managed_labels("l4:")
    assert "l4:needs-person" in labels and "l4:needs-answers" in labels
    assert {f"l4:{phase.value}" for phase in Phase} <= set(labels)
    assert "x-needs-person" in managed_labels("x-")
