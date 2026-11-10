"""L4-OCV-018 (SCN-OCV-40, -42): the sandbox of an opencode profile that needs no stored login hides OpenCode's real
data and config homes and still binds its cache home. The argv half only: no bwrap is started."""

from pathlib import Path

import pytest

from l4.sandbox.base import OWN_HOMES, SandboxSpec, hidden_credential_paths, own_login_binds
from l4.sandbox.bwrap import BwrapSandbox

EMPTY_ROOT = Path("/nonexistent-l4-host-root")
ENV = {"PATH": "/usr/bin", "HOME": "/h"}


def build(spec: SandboxSpec) -> list[str]:
    return BwrapSandbox("/usr/bin/bwrap", host_root=EMPTY_ROOT).build_argv(["true"], spec, ENV)


def pairs(argv: list[str], flag: str) -> list[tuple[str, ...]]:
    arity = {"--bind": 2, "--ro-bind": 2, "--tmpfs": 1}[flag]
    return [tuple(argv[i + 1 : i + 1 + arity]) for i, a in enumerate(argv) if a == flag]


@pytest.fixture
def homes(make_spec):
    """An opencode agent spec with all three OpenCode homes present and configured as the built-in defaults are."""
    home = make_spec("agent", "opencode").home
    share, config, cache = (home / ".local/share/opencode", home / ".config/opencode", home / ".cache/opencode")
    for path in (config, cache):
        path.mkdir(parents=True)

    def make(*, hide: bool, paths: tuple[Path, ...] = (share, config, cache)) -> SandboxSpec:
        return make_spec("agent", "opencode", credential_paths={"opencode": paths}, hide_own_homes=hide)

    return make, share, config, cache


def test_the_own_homes_are_the_data_and_the_config_home_of_opencode():
    assert OWN_HOMES == {"opencode": ("~/.local/share/opencode", "~/.config/opencode")}


def test_scn_ocv_40_such_a_profiles_sandbox_hides_the_data_and_config_homes_and_binds_the_cache(homes):
    make, share, config, cache = homes
    argv = build(make(hide=True))
    assert (str(share),) in pairs(argv, "--tmpfs") and (str(config),) in pairs(argv, "--tmpfs")
    assert (str(share),) * 2 not in pairs(argv, "--bind") and (str(config),) * 2 not in pairs(argv, "--bind")
    assert (str(cache),) * 2 in pairs(argv, "--bind") and (str(cache),) not in pairs(argv, "--tmpfs")


def test_without_the_flag_all_three_homes_are_bound_as_before(homes):
    make, share, config, cache = homes
    argv = build(make(hide=False))
    for path in (share, config, cache):
        assert (str(path),) * 2 in pairs(argv, "--bind") and (str(path),) not in pairs(argv, "--tmpfs")


def test_the_flag_changes_nothing_for_another_adapter(make_spec):
    plain = make_spec("agent", "codex")
    assert build(make_spec("agent", "codex", hide_own_homes=True)) == build(plain)
    assert own_login_binds(make_spec("agent", "codex", hide_own_homes=True)) == plain.credential_paths["codex"]


def test_a_gate_sandbox_is_unchanged(make_spec):
    assert build(make_spec("gate", hide_own_homes=True)) == build(make_spec("gate"))


def test_scn_ocv_42_a_configured_login_path_inside_a_hidden_home_is_hidden_too(tmp_path, homes):
    make, share, _config, cache = homes
    auth = share / "auth.json"
    auth.write_text("{}")
    other = tmp_path / "oc-login"
    other.mkdir()
    argv = build(make(hide=True, paths=(auth, cache, other)))
    assert ("/dev/null", str(auth)) in pairs(argv, "--ro-bind")  # a file: covered by /dev/null, never bound
    assert (str(auth),) * 2 not in pairs(argv, "--bind")
    assert (str(cache),) * 2 in pairs(argv, "--bind") and (str(other),) * 2 in pairs(argv, "--bind")


@pytest.mark.parametrize("rel", [".local/share", ".local/share/opencode/sub", ".config", ".config/opencode"])
def test_a_path_that_is_contains_or_lies_inside_an_own_home_is_dropped(make_spec, rel):
    """Fails closed for an odd configured path: one that holds the data home is dropped too."""
    path = make_spec("agent", "opencode").home / rel
    path.mkdir(parents=True, exist_ok=True)
    spec = make_spec("agent", "opencode", credential_paths={"opencode": (path,)}, hide_own_homes=True)
    assert own_login_binds(spec) == ()
    assert path in hidden_credential_paths(spec)
    assert (str(path),) * 2 not in pairs(build(spec), "--bind")


def test_a_sibling_of_an_own_home_is_kept(make_spec):
    sibling = make_spec("agent", "opencode").home / ".local/share/opencode-other"
    sibling.mkdir(parents=True)
    spec = make_spec("agent", "opencode", credential_paths={"opencode": (sibling,)}, hide_own_homes=True)
    assert own_login_binds(spec) == (sibling,)
    assert (str(sibling),) * 2 in pairs(build(spec), "--bind")
