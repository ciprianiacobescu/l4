from inventory.audit import AuditLog


def test_records_movements_in_order():
    log = AuditLog()
    log.record("A1", 5)
    log.record("A1", -2)
    assert log.entries() == [("A1", 5), ("A1", -2)]


def test_entries_are_a_copy():
    log = AuditLog()
    log.record("A1", 1)
    log.entries().clear()
    assert log.entries() == [("A1", 1)]
