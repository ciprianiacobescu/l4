"""The OpenCode v2 parser on the live recordings of `@opencode/cli` 2.2.6 (`tests/fixtures/recorded/opencode/2.2.6`;
L4-OCV-006 to -009, -013, -016, -019; SCN-OCV-32, -35, -36, -44 to -47). Every value below was obtained by running the
parser of 0.4.55 on the raw files: this group changes no parser. The rows the recordings settle are [V] on 2.2.6."""

import json
from datetime import UTC, datetime
from pathlib import Path

from l4.agents.base import RunResult
from l4.agents.opencode_v2 import OpenCodeV2Adapter, _scan_v2, usage_from_export
from l4.implementer.result import FILE_RESULT_SCHEMA

LIVE = Path(__file__).parents[2] / "fixtures" / "recorded" / "opencode" / "2.2.6"
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
JUDGE_SCHEMA = {"type": "object", "required": ["verdict"], "properties": {"verdict": {"type": "string"}}}
IMPLEMENTED = '{"status": "done", "summary": "recorded"}'
NAMES = (
    "live-judge", "live-judge-free", "live-implement", "live-bounded", "live-tools-permission", "live-cli-denied",
    "live-cli-disturbed", "live-error-no-route",
)  # fmt: skip


def stream(name: str) -> list[str]:
    return (LIVE / f"{name}.jsonl").read_text().splitlines()


def export_of(name: str) -> dict:
    return json.loads((LIVE / f"{name}.export.json").read_text())


def parse(name: str, tmp_path: Path, *, export: object = ..., judge: bool = False, **kw) -> RunResult:
    kw.setdefault("exit_code", 0)
    kw.setdefault("step_bound", 3 if judge else 200)
    if judge:
        kw.setdefault("schema", JUDGE_SCHEMA)
    else:
        kw.setdefault("result_text", IMPLEMENTED)
        kw.setdefault("schema", FILE_RESULT_SCHEMA)
    return OpenCodeV2Adapter().parse(
        stream(name), raw_events_path=tmp_path / "raw-001.jsonl", judge=judge, now=NOW,
        export=export_of(name) if export is ... else export, **kw,
    )  # fmt: skip


def usage_of(out: RunResult) -> tuple:
    u = out.usage
    return (u.input_tokens, u.output_tokens, u.cached_input_tokens, u.cost_usd, u.context_peak_tokens)


def test_the_recordings_of_2_2_6_are_all_there():
    assert (LIVE / "live-version.stdout.txt").read_text() == "opencode v2.2.6\n"
    for name in NAMES:
        assert (LIVE / f"{name}.jsonl").is_file() and (LIVE / f"{name}.export.json").is_file(), name


# --- SCN-OCV-32: the core paths hold on 2.2.6 ---


def test_scn_ocv_32_the_recorded_judges_and_implementer_are_ok_with_no_denial(tmp_path):
    expected = {
        "live-judge": (True, (756, 44, 0, 0.0, 756)),
        "live-judge-free": (True, (1247, 43, 128, 0.0, 1375)),
        "live-implement": (False, (2773, 278, 7936, 0.0, 2851)),
    }
    for name, (judge, usage) in expected.items():
        out = parse(name, tmp_path, judge=judge)
        assert out.status == "ok" and out.permission_denials == [], name
        assert usage_of(out) == usage, name
        info = export_of(name)["info"]["tokens"]  # the export's own totals: input, output, cache read
        assert (info["input"], info["output"], info["cache"]["read"]) == usage[:3], name


# --- SCN-OCV-35: a refused CLI call is a denial and the step goes on (L4-OCV-016) ---


def test_scn_ocv_35_the_recorded_refused_cli_call_is_a_denial_and_the_step_is_ok(tmp_path):
    out = parse("live-cli-denied", tmp_path)
    assert out.status == "ok"
    assert out.permission_denials == [
        {"tool_name": "shell", "tool_input": {"command": "opencode2 api GET /api/project"}}
    ]


# --- SCN-OCV-36: export_decides (U5 [V] on 2.2.6, `live-cli-disturbed`) ---


def test_export_decides_on_the_recorded_disturbed_run(tmp_path):
    """export_decides (U5, [V] on 2.2.6): the stream of `live-cli-disturbed` ends with a `step_start` after a
    `step_finish` of reason `tool-calls`, so it has no final stop; its export says `succeeded` and decides."""
    assert parse("live-cli-disturbed", tmp_path).status == "ok"
    out = parse("live-cli-disturbed", tmp_path, export=None, export_problem="no export")
    assert out.status == "error"
    assert out.detail == "opencode2 session export failed (no export) and the stream has no final stop"


# --- SCN-OCV-44: not_ok_named (U7 [V], `live-bounded`) and the bound (U9 in part) ---


def test_scn_ocv_44_the_recorded_bounded_judge_is_a_step_bound_error_though_its_export_says_succeeded(tmp_path):
    """not_ok_named (U7, [V] on 2.2.6): a bounded run's export says `succeeded`, and the bound rule decides first.
    U9 in part: `steps: 2` made step 2 the forced summary."""
    assert export_of("live-bounded")["info"]["outcome"] == "succeeded"
    out = parse("live-bounded", tmp_path, judge=True, step_bound=2)
    assert out.status == "error" and out.detail == "step_bound: opencode2 stopped at agents.build.steps 2"
    assert out.permission_denials == []  # the `skill` call that loaded nothing is not a denial


# --- SCN-OCV-45: tools_by_permission (U2 [V], `live-tools-permission`) ---


def test_scn_ocv_45_the_recorded_tools_permission_run_had_no_shell_tool(tmp_path):
    """tools_by_permission (U2, [V] on 2.2.6): with `options.tools: [read, edit]` the request held no `shell` tool."""
    out = parse("live-tools-permission", tmp_path)
    assert out.status == "ok" and out.permission_denials == []
    called = [
        json.loads(line)["part"]["tool"] for line in stream("live-tools-permission") if '"type":"tool_use"' in line
    ]
    assert called and "shell" not in called


# --- SCN-OCV-46: sum_messages (U11 [V], `live-implement`, `live-cli-disturbed`) ---


def test_scn_ocv_46_a_recorded_multi_step_export_sums_to_info_tokens(tmp_path):
    """sum_messages (U11, [V] on 2.2.6): one assistant message per finished step, summing to `info.tokens` in the
    recorded exports; the `synthetic` message of `live-cli-disturbed` is not counted."""
    for name, expected, peak in (
        ("live-implement", (2773, 278, 7936), 2851),
        ("live-cli-disturbed", (3722, 1039, 15616), 5155),
    ):
        document = export_of(name)
        usage = usage_from_export(document)
        assert usage is not None
        assert (usage.input_tokens, usage.output_tokens, usage.cached_input_tokens) == expected, name
        tokens = document["info"]["tokens"]
        assert (tokens["input"], tokens["output"], tokens["cache"]["read"]) == expected, name
        assert usage.context_peak_tokens == peak, name
        kinds = [message["type"] for message in document["messages"]]
        assert kinds.count("assistant") == 4, name
    assert "synthetic" in [m["type"] for m in export_of("live-cli-disturbed")["messages"]]


# --- SCN-OCV-47: a status-less error is classed by its words (L4-OCV-009) ---


def test_scn_ocv_47_the_recorded_no_route_error_is_a_retryable_error(tmp_path):
    out = parse("live-error-no-route", tmp_path, judge=True, exit_code=1, model="opencode/nemotron-3-ultra-free")
    assert out.status == "error"
    assert out.detail == "opencode2 reported an error (provider.no-route), retryable"
    assert out.transient is True and out.limit is None
    assert export_of("live-error-no-route")["info"]["outcome"] == "failed"  # the stream's error decides first


# --- U5: how often the final `step_finish` is missing ---


def test_census_a_final_stop_is_missing_only_in_the_disturbed_and_the_no_route_run():
    missing = [name for name in NAMES if _scan_v2(stream(name)).last_reason != "stop"]
    assert sorted(missing) == ["live-cli-disturbed", "live-error-no-route"]
