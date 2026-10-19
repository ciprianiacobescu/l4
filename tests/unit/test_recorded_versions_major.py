"""SCN-OCV-24 (unit part): an unrecorded version is compared with the recordings of its own major only."""

from l4 import recordedversions

RECORDED = {"opencode": ["1.18.33", "1.18.34", "2.0.32"]}


def test_a_newer_v2_patch_lists_only_the_v2_recordings() -> None:
    assert recordedversions.unrecorded("opencode", "2.0.33", RECORDED) == ["2.0.32"]


def test_a_newer_v1_patch_lists_only_the_v1_recordings() -> None:
    assert recordedversions.unrecorded("opencode", "1.18.35", RECORDED) == ["1.18.33", "1.18.34"]


def test_a_recorded_v2_version_is_not_reported() -> None:
    assert recordedversions.unrecorded("opencode", "2.0.32", RECORDED) is None


def test_a_major_without_any_recording_gets_the_full_list() -> None:
    assert recordedversions.unrecorded("opencode", "3.0.0", RECORDED) == ["1.18.33", "1.18.34", "2.0.32"]


def test_the_packaged_table_lists_the_v2_recording() -> None:
    assert "2.0.32" in recordedversions.load()["opencode"]
    assert recordedversions.unrecorded("opencode", "2.0.33") == ["2.0.32"]
    assert recordedversions.unrecorded("opencode", "1.18.35") == ["1.18.33", "1.18.34"]


def test_an_unparsable_version_lists_the_full_table() -> None:
    assert recordedversions.unrecorded("opencode", "dev", RECORDED) == ["1.18.33", "1.18.34", "2.0.32"]
