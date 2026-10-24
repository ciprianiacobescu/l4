"""SCN-OCG-01 (L4-OCG-001): the major version of an agent CLI is read from both `--version` forms."""

from pathlib import Path

import pytest

from l4.config.schema import Profile
from l4.provision import catalog
from l4.versions import major_of, parse_version

FIXTURES = Path(__file__).parents[1] / "fixtures" / "cli_major" / "opencode"
REASON_V2 = (
    "opencode 2.0.32 is OpenCode v2; this profile runs v1 (opencode-ai 1.x): install opencode-ai@1.18.34 "
    "(l4 doctor --fix installs it user-locally) or set options.cli_major: 2 to run OpenCode 2 (experimental)"
)


def test_major_of_reads_both_recorded_forms():
    assert major_of((FIXTURES / "v1-1.18.34.version.txt").read_text()) == 1
    assert major_of((FIXTURES / "v2-2.0.32.version.txt").read_text()) == 2


def test_major_of_is_none_without_a_version():
    assert major_of("") is None
    assert major_of("no version here") is None


def test_the_supported_major_follows_the_pin():
    assert catalog.SUPPORTED_MAJORS == {"opencode": 1, "opencode2": 2, "kiro-cli": 2, "copilot-cli": 1}
    assert catalog.SUPPORTED_MAJORS["opencode2"] == parse_version(catalog.OPENCODE2_VERSION)[0]
    assert catalog.SUPPORTED_MAJORS["opencode"] == parse_version(catalog.OPENCODE_VERSION)[0]


def test_major_problem_names_the_found_version_and_both_ways_out():
    assert catalog.major_problem("opencode", "opencode", "opencode v2.0.32", "1.18.34") == REASON_V2


def test_major_problem_is_none_for_the_supported_major_an_ungated_adapter_and_no_version():
    assert catalog.major_problem("opencode", "opencode", "1.18.34", "1.18.34") is None
    assert catalog.major_problem("opencode", "opencode", "1.19.3\n", "1.18.34") is None
    assert catalog.major_problem("codex", "codex", "codex-cli 9.0.0", "0.160.0") is None
    assert catalog.major_problem("opencode", "opencode", "no version here", "1.18.34") is None


REASON_V2_PROFILE = (
    "opencode2 1.18.34 is OpenCode v1; this profile runs v2 (options.cli_major: 2, @opencode/cli 2.x): install "
    "@opencode/cli@2.0.32 (l4 doctor --fix installs it user-locally) or remove options.cli_major"
)


def test_the_v1_reason_ends_with_the_way_to_opt_in_to_v2():  # amendment E2, SCN-OCG-02
    reason = catalog.major_problem("opencode", "opencode", "opencode v2.0.32", "1.18.34")
    assert reason is not None and reason.endswith("or set options.cli_major: 2 to run OpenCode 2 (experimental)")
    assert "support comes in a later" not in reason


def test_a_v2_profile_with_a_v1_binary_gets_the_v2_reason():  # SCN-OCV-02
    assert catalog.major_problem("opencode2", "opencode2", "1.18.34", "2.0.32") == REASON_V2_PROFILE
    assert catalog.major_problem("opencode2", "opencode2", "opencode v1.18.34", "2.0.32") == REASON_V2_PROFILE


def test_a_v2_profile_with_a_v2_binary_of_another_patch_is_not_a_major_problem():
    assert catalog.major_problem("opencode2", "opencode2", "opencode v2.0.32", "2.0.32") is None
    assert catalog.major_problem("opencode2", "opencode2", "opencode v2.1.4", "2.0.32") is None
    assert catalog.major_problem("opencode2", "opencode2", "no version here", "2.0.32") is None


def test_the_v2_key_has_its_own_words():
    words = catalog.MAJOR_WORDS["opencode2"]
    assert words.product == "OpenCode"
    assert words.need.format(supported=2) == "@opencode/cli 2.x"
    assert catalog.major_plan_reason("opencode2", "1.18.34", 1, "2.0.32") == (
        "found 1.18.34 (OpenCode v1), need @opencode/cli 2.x (pinned 2.0.32)"
    )
    assert catalog.major_no_version_text("opencode2", "opencode2") == (
        "opencode2 reports no version, so its OpenCode major cannot be checked"
    )


def oc(**options) -> Profile:
    return Profile(adapter="opencode", model="opencode-go/m", auth="api_key", options=options)


def test_profile_cli_is_the_gate_key_and_the_binary():  # amendment E2
    assert catalog.profile_cli(Profile(adapter="opencode", model="opencode/big-pickle")) == ("opencode", "opencode")
    assert catalog.profile_cli(oc()) == ("opencode", "opencode")
    assert catalog.profile_cli(oc(cli_major=1)) == ("opencode", "opencode")
    assert catalog.profile_cli(oc(cli_major=2)) == ("opencode2", "opencode2")


@pytest.mark.parametrize("adapter", sorted(catalog.ADAPTER_BINARIES))
def test_profile_cli_of_any_other_adapter_is_the_adapter(adapter):
    if adapter == "opencode":
        return
    assert catalog.profile_cli(Profile(adapter=adapter)) == (adapter, catalog.ADAPTER_BINARIES[adapter])
