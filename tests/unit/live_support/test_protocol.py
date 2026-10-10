from ...live.protocol import happened_after, started_by_a_lock_ref_push


def test_merge_request_refs_are_not_lock_refs():
    assert not started_by_a_lock_ref_push({"ref": "refs/merge-requests/2/head", "source": "merge_request_event"})
    assert not started_by_a_lock_ref_push({"ref": "main"}) and not started_by_a_lock_ref_push({"ref": "l4/openspec/x"})


def test_the_lock_namespaces_are_lock_refs():
    assert started_by_a_lock_ref_push({"ref": "refs/l4/locks/openspec/add-vat"})
    assert started_by_a_lock_ref_push({"ref": "l4-lock/openspec/add-vat"})


def test_instants_are_compared_across_utc_offsets():
    assert happened_after("2026-10-04T02:00:00.000Z", "2026-10-04T04:30:00.000+03:00")
    assert not happened_after("2026-10-04T01:10:00Z", "2026-10-04T04:30:00.000+03:00")
    assert happened_after("2026-10-04T01:30:00Z", "2026-10-04T04:30:00.000+03:00")
