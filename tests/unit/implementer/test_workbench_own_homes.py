"""L4-OCV-018 (SCN-OCV-41): `Workbench.agent_spec` hides OpenCode's own data and config homes for a profile that
needs no stored login, and builds the spec it always built for every other profile."""

from dataclasses import replace

import pytest

from l4.config.schema import Profile
from l4.sandbox.bwrap import BwrapSandbox

OPENCODE_LOGINS = (".local/share/opencode", ".config/opencode", ".cache/opencode")


def v2(model: str, **extra) -> Profile:
    return Profile(adapter="opencode", model=model, vendor="unknown", options={"cli_major": 2}, **extra)


def bench_with(make_bench, profile: Profile):
    wb = make_bench([]).wb
    wb.selected = replace(wb.selected, profile=profile)
    for rel in OPENCODE_LOGINS:
        (wb.home / rel).mkdir(parents=True, exist_ok=True)
    return wb


def argv_of(wb, spec) -> list[str]:
    return BwrapSandbox("/usr/bin/bwrap").build_argv(["true"], spec, {})


@pytest.mark.parametrize(
    "profile",
    [
        pytest.param(
            Profile(adapter="opencode", model="opencode-go/deepseek-v4.1-flash", vendor="deepseek", auth="api_key"),
            id="v1-api-key",
        ),
        pytest.param(
            Profile(adapter="opencode", model="opencode-go/deepseek-v4.1-flash", vendor="deepseek"),
            id="v1-subscription",
        ),
        pytest.param(v2("openrouter/openai/gpt-5.4-mini"), id="v2-openrouter"),
    ],
)
def test_scn_ocv_41_v1_profiles_and_stored_login_v2_profiles_bind_as_before(make_bench, profile):
    wb = bench_with(make_bench, profile)
    spec = wb.agent_spec()
    assert spec.hide_own_homes is False
    argv = argv_of(wb, spec)
    logins = [str(wb.home / rel) for rel in OPENCODE_LOGINS]
    # the 0.4.55 expression, written out and not rebuilt from the spec: the three login paths of the adapter are bound
    # read-write (a `--bind` pair each, in the configured order), and none of them is covered by a tmpfs
    assert [p for p in spec.credential_paths["opencode"]] == [wb.home / rel for rel in OPENCODE_LOGINS]
    bound = [(argv[i + 1], argv[i + 2]) for i, a in enumerate(argv) if a == "--bind" and argv[i + 1] in logins]
    assert bound == [(path, path) for path in logins]
    assert not set(logins) & {argv[i + 1] for i, a in enumerate(argv) if a == "--tmpfs"}
    assert not any(argv[i : i + 3] == ["--ro-bind", "/dev/null", path] for i in range(len(argv) - 2) for path in logins)
    assert argv == argv_of(wb, replace(spec, hide_own_homes=False))  # and the flag at its default changes nothing


@pytest.mark.parametrize(
    "profile",
    [
        pytest.param(v2("opencode-go/deepseek-v4.1-flash", auth="api_key"), id="v2-api-key"),
        pytest.param(v2("opencode/big-pickle"), id="v2-free"),
    ],
)
def test_a_v2_profile_that_needs_no_stored_login_hides_the_data_and_config_homes(make_bench, profile):
    wb = bench_with(make_bench, profile)
    spec = wb.agent_spec()
    assert spec.hide_own_homes is True
    argv = argv_of(wb, spec)
    share, config, cache = (str(wb.home / rel) for rel in OPENCODE_LOGINS)
    binds = [tuple(argv[i + 1 : i + 3]) for i, a in enumerate(argv) if a == "--bind"]
    tmpfs = [argv[i + 1] for i, a in enumerate(argv) if a == "--tmpfs"]
    assert share in tmpfs and config in tmpfs
    assert (share, share) not in binds and (config, config) not in binds and (cache, cache) in binds
