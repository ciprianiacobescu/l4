from pathlib import Path

import pytest

from l4.exitcodes import ExitCode, L4Exit
from l4.specs.base import (
    Framework,
    MarkerNotAllowed,
    OpenSpecUnavailable,
    SpecError,
    SpecProvider,
    UnitRef,
    parse_unit_id,
)


def test_unit_ref_id_and_error_hierarchy(tmp_path: Path):
    ref = UnitRef(Framework.OPENSPEC, "add-login", tmp_path / "openspec" / "changes" / "add-login")
    assert ref.id == "openspec:add-login"
    assert parse_unit_id("openspec:add-login") == (Framework.OPENSPEC, "add-login")
    for bad in ("add-login", "git:x", "openspec:", "openspec:../x", "openspec:a/b", "openspec:-x"):
        with pytest.raises(ValueError):
            parse_unit_id(bad)
    with pytest.raises(ValueError):
        UnitRef(Framework.OPENSPEC, "../escape", tmp_path)
    # provider errors are L4Exits, so classify_exception maps them without a special case
    assert issubclass(SpecError, L4Exit)
    assert OpenSpecUnavailable("no node").code is ExitCode.DOCTOR_FAILED
    assert MarkerNotAllowed("no").code is ExitCode.INTERNAL_ERROR


def test_protocol_names_the_m0_provider_members():
    assert {"list_units", "load", "tasks", "criteria", "set_marker", "validate", "unit_dir"} <= set(
        SpecProvider.__protocol_attrs__
    )


@pytest.mark.parametrize("text", ["openspec:a..b", "openspec:..", "openspec:a..", "openspec:..a"])
def test_dotdot_in_a_unit_name_is_refused(text: str, tmp_path: Path):
    with pytest.raises(ValueError):
        parse_unit_id(text)
    with pytest.raises(ValueError):
        UnitRef(Framework.OPENSPEC, text.partition(":")[2], tmp_path)
