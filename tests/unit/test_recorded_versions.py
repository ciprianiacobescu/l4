"""HB-17: the packaged `recorded_versions.json` is generated from `tests/fixtures/recorded/*/<version>/`."""

from pathlib import Path

from l4 import recordedversions

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "recorded"


def test_the_packaged_file_is_what_the_fixture_tree_generates() -> None:
    assert recordedversions.load() == recordedversions.generate(FIXTURES)


def test_generate_reads_version_directories_only(tmp_path: Path) -> None:
    for name in ("opencode/1.18.33", "opencode/1.18.9", "opencode/notes", "pytest/x.xml", "codex/0.160.0"):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.mkdir() if not name.endswith(".xml") else target.write_text("<x/>")
    assert recordedversions.generate(tmp_path) == {"codex": ["0.160.0"], "opencode": ["1.18.9", "1.18.33"]}


def test_a_version_without_recordings_is_unrecorded() -> None:
    recorded = {"opencode": ["1.18.33"]}
    assert recordedversions.unrecorded("opencode", "1.18.34", recorded) == ["1.18.33"]
    assert recordedversions.unrecorded("opencode", "1.18.33", recorded) is None


def test_an_adapter_without_any_recordings_is_not_judged() -> None:
    assert recordedversions.unrecorded("command", "9.9.9", {"opencode": ["1.18.33"]}) is None


def test_every_adapter_the_doctor_checks_has_recordings() -> None:
    from l4.provision.catalog import ADAPTER_BINARIES

    # copilot-cli has none until task 8.1 (the release gate, design D17): LIVE-005 judges nothing for it meanwhile
    assert set(ADAPTER_BINARIES) - {"copilot-cli"} <= set(recordedversions.load())


def test_copilot_cli_has_no_recorded_version() -> None:
    generated = recordedversions.generate(FIXTURES)
    assert "copilot-cli" not in generated
    assert "copilot" not in generated
