from ...live.protocol_m14 import command_output, created_before, log_text, plan_rows

# The shape of a GitLab 17 job log (job 5475, M1.4 P2): every line carries a timestamp and a stream marker.
LOG = """\
2026-10-04T17:41:00.564064Z 01O $ .l4/bin/l4 doctor --ci --fix || .l4/bin/l4 ci map-exit $?
2026-10-04T17:41:05.385036Z 01O SPEC-001  error     pass    openspec, kiro                       -
2026-10-04T17:41:05.429266Z 01O $ .l4/bin/l4 plan --sweep || .l4/bin/l4 ci map-exit $?
2026-10-04T17:41:07.100000Z 01E [l4] sweeper: openspec:add-discount-codes: archive MR !3 is open
2026-10-04T17:41:07.200000Z 01O UNIT                         PHASE           TASKS  NEXT       REASON
2026-10-04T17:41:07.200001Z 01O kiro:add-loyalty-points      -               0/4    implement  pending tasks
2026-10-04T17:41:07.200002Z 01O openspec:add-average-price   in_review       1/1    none       in_review: waiting
2026-10-04T17:41:07.200003Z 01O openspec:add-vat             awaiting_human  2/2    none       awaiting_human
2026-10-04T17:41:08.008390Z 01O $ .l4/bin/l4 run || .l4/bin/l4 ci map-exit $?
2026-10-04T17:41:09.000000Z 01E [l4] kiro:add-loyalty-points phase none → intake (unit_discovered_pending)
2026-10-04T17:44:23.884371Z 01O $ .l4/bin/l4 status
2026-10-04T17:44:24.000000Z 01O kiro:add-loyalty-points      in_review       1     4/4    -       PASS         branch
2026-10-04T17:44:24.000001Z 00O+Uploading artifacts for successful job
"""


def test_log_text_drops_the_timestamp_and_stream_marker_only():
    row = "kiro:add-loyalty-points  -  0/4"
    assert log_text(f"2026-10-04T17:41:07.200001Z 01O {row}") == row
    assert log_text("2026-10-04T17:44:24.000001Z 00O+Uploading artifacts") == "Uploading artifacts"
    assert log_text(row) == row  # an undecorated log


def test_command_output_stops_at_the_next_script_line():
    out = command_output(LOG, ".l4/bin/l4 plan --sweep")
    assert out[0] == "[l4] sweeper: openspec:add-discount-codes: archive MR !3 is open"
    assert out[-1].startswith("openspec:add-vat ")
    assert not any("phase none → intake" in line for line in out)
    assert command_output(LOG, ".l4/bin/l4 verify") == []


def test_plan_rows_read_the_plan_table_not_the_status_table():
    rows = plan_rows(command_output(LOG, ".l4/bin/l4 plan --sweep"))
    assert list(rows) == ["kiro:add-loyalty-points", "openspec:add-average-price", "openspec:add-vat"]
    assert " implement " in rows["kiro:add-loyalty-points"]  # the status table's row says in_review
    assert "openspec:add-discount-codes" not in rows  # the sweeper's [l4] line is not a table row


def test_created_before_compares_instants():
    mrs = [{"iid": 13, "created_at": "2026-10-04T17:42:08.100Z"}, {"iid": 3, "created_at": "2026-10-04T19:00:00+03:00"}]
    assert [m["iid"] for m in created_before(mrs, "2026-10-04T17:41:00.000Z")] == [3]  # 16:00Z is earlier
    assert [m["iid"] for m in created_before(mrs, None)] == [13, 3]  # no anchor: every merge request counts
