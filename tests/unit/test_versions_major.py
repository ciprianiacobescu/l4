"""SCN-OCG-01 (L4-OCG-001): the major version of an agent CLI is read from both `--version` forms."""

from pathlib import Path

from l4.provision import catalog
from l4.versions import major_of, parse_version

FIXTURES = Path(__file__).parents[1] / "fixtures" / "cli_major" / "opencode"
REASON_V2 = (
    "opencode 2.0.32 is OpenCode v2; this profile runs v1 (opencode-ai 1.x): install opencode-ai@1.18.34 "
    "(l4 doctor --fix installs it user-locally) or set options.cli_major: 2 when supported"
)


def test_major_of_reads_both_recorded_forms():
    assert major_of((FIXTURES / "v1-1.18.34.version.txt").read_text()) == 1
    assert major_of((FIXTURES / "v2-2.0.32.version.txt").read_text()) == 2


def test_major_of_is_none_without_a_version():
    assert major_of("") is None
    assert major_of("no version here") is None


def test_the_supported_major_follows_the_pin():
    assert catalog.SUPPORTED_MAJORS == {"opencode": 1}
    assert catalog.SUPPORTED_MAJORS["opencode"] == parse_version(catalog.OPENCODE_VERSION)[0]


def test_major_problem_names_the_found_version_and_both_ways_out():
    assert catalog.major_problem("opencode", "opencode", "opencode v2.0.32", "1.18.34") == REASON_V2


def test_major_problem_is_none_for_the_supported_major_an_ungated_adapter_and_no_version():
    assert catalog.major_problem("opencode", "opencode", "1.18.34", "1.18.34") is None
    assert catalog.major_problem("opencode", "opencode", "1.19.3\n", "1.18.34") is None
    assert catalog.major_problem("codex", "codex", "codex-cli 9.0.0", "0.160.0") is None
    assert catalog.major_problem("opencode", "opencode", "no version here", "1.18.34") is None
