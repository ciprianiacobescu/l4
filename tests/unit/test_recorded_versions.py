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

    assert set(ADAPTER_BINARIES) <= set(recordedversions.load())


def test_scn_fac_48_the_byok_and_no_token_fixtures_are_not_a_recorded_version(tmp_path: Path) -> None:
    suffixed = ("1.0.102-byok", "1.0.102-notoken", "1.0.102-firstcalls")
    for name in suffixed:  # the tree before the live recording
        (tmp_path / "copilot-cli" / name).mkdir(parents=True)
    before = recordedversions.generate(tmp_path)
    assert "copilot-cli" not in before
    assert recordedversions.unrecorded("copilot-cli", "1.0.102", before) is None  # LIVE-005 reports nothing
    for name in suffixed:
        assert (FIXTURES / "copilot-cli" / name).is_dir()
    generated = recordedversions.generate(FIXTURES)
    assert generated["copilot-cli"] == ["1.0.102"]  # only the bare version counts
    assert "copilot" not in generated


def test_the_packaged_file_lists_opencode_two() -> None:
    assert "2.0.32" in recordedversions.load()["opencode"]
