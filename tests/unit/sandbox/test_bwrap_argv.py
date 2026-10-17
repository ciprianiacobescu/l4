from dataclasses import replace
from pathlib import Path

import pytest

from l4.sandbox.base import CacheMount, SandboxSpec
from l4.sandbox.bwrap import BwrapSandbox

BASE = [
    "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
    "--unshare-pid", "--unshare-ipc",
]  # fmt: skip
EMPTY_ROOT = Path("/nonexistent-l4-host-root")  # no /run, no /var/run: the argv does not depend on the machine
ENV = {"PATH": "/usr/bin", "HOME": "/h", "L4_RESULT_PATH": "/r/result.json"}


def build(spec: SandboxSpec, argv=("true",), env=ENV) -> list[str]:
    return BwrapSandbox("/usr/bin/bwrap", host_root=EMPTY_ROOT).build_argv(list(argv), spec, env)


def pairs(argv: list[str], flag: str) -> list[tuple[str, ...]]:
    arity = {"--bind": 2, "--ro-bind": 2, "--tmpfs": 1, "--setenv": 2}[flag]
    return [tuple(argv[i + 1 : i + 1 + arity]) for i, a in enumerate(argv) if a == flag]


def test_gate_argv_shape(make_spec):
    spec = make_spec("gate", network=False)
    argv = build(spec, ["pytest", "-q"])
    assert argv[0] == "/usr/bin/bwrap" and argv[1 : 1 + len(BASE)] == BASE
    assert "--unshare-net" in argv and "--share-net" not in argv
    assert "--die-with-parent" in argv and "--clearenv" in argv
    assert argv[-5:] == ["--chdir", str(spec.worktree), "--", "pytest", "-q"]
    # worktree and the private dir are writable, nothing else is
    assert pairs(argv, "--bind") == [(str(spec.worktree),) * 2, (str(spec.tmp_dir),) * 2]
    # no login path of any adapter is visible to code the agent wrote
    home = spec.home
    # (and the home itself is a tmpfs, L4-SEC-030, so the login masks sit on top of an empty directory)
    assert set(pairs(argv, "--tmpfs")) == {
        ("/tmp",), (str(home),), (str(home / ".codex"),), (str(home / ".local/share/opencode"),),
    }  # fmt: skip
    assert ("/dev/null", str(home / ".claude.json")) in pairs(argv, "--ro-bind")


def test_gate_network_follows_the_spec(make_spec):
    assert "--share-net" in build(make_spec("gate", network=True))


def test_agent_argv_binds_only_own_credentials(make_spec):
    spec = make_spec("agent", "codex")
    argv = build(spec)
    home = spec.home
    assert (str(home / ".codex"),) * 2 in pairs(argv, "--bind")
    # every OTHER adapter's login is hidden: dir -> tmpfs, file -> /dev/null, missing -> skipped
    assert (str(home / ".local/share/opencode"),) in pairs(argv, "--tmpfs")
    assert ("/dev/null", str(home / ".claude.json")) in pairs(argv, "--ro-bind")
    assert str(home / ".claude") not in argv  # does not exist: nothing to hide, and bwrap cannot mkdir under ro /
    assert (str(home / ".codex"),) not in pairs(argv, "--tmpfs")
    assert "--share-net" in argv


def test_agent_of_another_adapter_gets_its_own_logins_and_hides_codex(make_spec):
    spec = make_spec("agent", "claude-code")
    argv = build(spec)
    assert (str(spec.home / ".claude.json"),) * 2 in pairs(argv, "--bind")
    assert (str(spec.home / ".codex"),) in pairs(argv, "--tmpfs")


def test_main_repo_git_dir_is_read_only_and_after_the_writable_binds(make_spec):
    spec = make_spec("agent", "codex")
    argv = build(spec)
    ro = pairs(argv, "--ro-bind")
    assert (str(spec.git_common_dir),) * 2 in ro
    assert argv.index(str(spec.git_common_dir)) > argv.index(str(spec.tmp_dir))


def test_env_is_cleared_then_exactly_the_allow_list_is_set(make_spec):
    argv = build(make_spec("agent", "codex"))
    assert sorted(pairs(argv, "--setenv")) == sorted((k, v) for k, v in ENV.items())
    assert argv.index("--clearenv") < argv.index("--setenv")


def test_no_credential_variable_reaches_the_argv(make_spec):
    argv = build(make_spec("agent", "codex"), env={**ENV, "PATH": "/usr/bin"})
    assert not [a for a in argv if a.endswith(("_TOKEN", "_KEY"))]


def test_caches_are_bound_read_write_or_read_only(make_spec):
    rw, ro = make_spec.cache("uv"), make_spec.cache("playwright", read_only=True)
    argv = build(make_spec("gate", caches=(rw, ro)))
    assert (str(rw.path),) * 2 in pairs(argv, "--bind")
    assert (str(ro.path),) * 2 in pairs(argv, "--ro-bind")


def test_an_existing_credential_directory_that_is_a_symlink_is_still_hidden(tmp_path: Path, make_spec):
    spec = make_spec("gate")
    link = tmp_path / "link"
    link.symlink_to(spec.home / ".codex")
    argv = build(make_spec("gate", credential_paths={"codex": (link,)}))
    assert (str(link),) in pairs(argv, "--tmpfs")


def test_an_agent_spec_needs_an_adapter_and_a_gate_spec_must_not_have_one(make_spec):
    with pytest.raises(ValueError):
        make_spec("agent", None)
    with pytest.raises(ValueError):
        make_spec("gate", force_adapter="codex")


def test_credential_paths_expand_the_tilde_and_refuse_relative_paths(tmp_path):
    from l4.sandbox.base import expand_credential_paths

    out = expand_credential_paths({"codex": ["~/.codex"], "x": ["/abs/p"]}, tmp_path)
    assert out == {"codex": (tmp_path / ".codex",), "x": (Path("/abs/p"),)}
    with pytest.raises(ValueError, match="sandbox.credential_paths.bad"):
        expand_credential_paths({"bad": [".codex"]}, tmp_path)


def test_a_user_override_replaces_only_what_is_mounted_never_what_is_hidden_from_others(tmp_path, make_spec):
    """SEC-005: `sandbox.credential_paths.codex` moves the codex login for the codex agent; the default ~/.codex must
    still be hidden from the claude-code agent and from gates, next to the new path."""
    moved = tmp_path / "elsewhere" / "codex"
    moved.mkdir(parents=True)
    spec = make_spec("agent", "claude-code")
    override = {**spec.credential_paths, "codex": (moved,)}
    hidden = pairs(build(make_spec("agent", "claude-code", credential_paths=override)), "--tmpfs")
    assert (str(moved),) in hidden and (str(spec.home / ".codex"),) in hidden
    gate_hidden = pairs(build(make_spec("gate", credential_paths=override)), "--tmpfs")
    assert (str(moved),) in gate_hidden and (str(spec.home / ".codex"),) in gate_hidden
    own = build(make_spec("agent", "codex", credential_paths=override))
    assert (str(moved),) * 2 in pairs(own, "--bind")  # what is mounted is the override alone
    assert (str(spec.home / ".codex"),) * 2 not in pairs(own, "--bind")


def test_the_runner_tmp_dir_is_covered_by_a_tmpfs_in_both_kinds_before_any_bind(tmp_path, make_spec):
    """The runner keeps the job-token insteadOf config and the CA file in `<CI_PROJECT_DIR>.tmp`."""
    secret = tmp_path / "builds" / "g" / "p.tmp"
    secret.mkdir(parents=True)
    for kind in ("agent", "gate"):
        argv = build(make_spec(kind, runner_tmp=(secret,)))
        assert (str(secret),) in pairs(argv, "--tmpfs")
        assert argv.index(str(secret)) < argv.index("--bind")  # hidden first, so a later bind could still re-expose
    missing = tmp_path / "builds" / "g" / "q.tmp"
    assert str(missing) not in build(make_spec("gate", runner_tmp=(missing,)))  # nothing to hide, bwrap cannot mkdir


def test_runner_tmp_paths_come_from_ci_project_dir(tmp_path):
    from l4.sandbox.base import runner_tmp_paths

    assert runner_tmp_paths({}) == ()
    assert runner_tmp_paths({"CI_PROJECT_DIR": "rel/dir"}) == ()  # a relative path would mean whatever bwrap's cwd is
    assert runner_tmp_paths({"CI_PROJECT_DIR": "/b/g/p"}) == (Path("/b/g/p.tmp"),)
    assert runner_tmp_paths({"CI_PROJECT_DIR": "/b/g/p/"}) == (Path("/b/g/p.tmp"),)
    both = runner_tmp_paths({"CI_PROJECT_DIR": "/b/g/p", "CI_BUILDS_DIR": "/b", "CI_PROJECT_PATH": "g/p"})
    assert both == (Path("/b/g/p.tmp"),)  # the builds-dir level is the same path: listed once


def test_opencode_cache_hidden_from_codex(make_spec):
    """G17: `~/.cache/opencode` (its models cache and plugin store) is mounted for opencode and for no one else."""
    from l4.config.defaults import CREDENTIAL_PATHS
    from l4.sandbox.base import expand_credential_paths

    spec = make_spec("agent", "codex")
    cache = spec.home / ".cache" / "opencode"
    cache.mkdir(parents=True)
    creds = expand_credential_paths({k: list(v) for k, v in CREDENTIAL_PATHS.items()}, spec.home)
    assert cache in creds["opencode"]
    codex = build(SandboxSpec(**{**spec.__dict__, "credential_paths": creds}))
    assert (str(cache),) in pairs(codex, "--tmpfs") and (str(cache),) * 2 not in pairs(codex, "--bind")
    own = build(SandboxSpec(**{**spec.__dict__, "credential_paths": creds, "adapter": "opencode"}))
    assert (str(cache),) * 2 in pairs(own, "--bind") and (str(cache),) not in pairs(own, "--tmpfs")
    gate = build(SandboxSpec(**{**spec.__dict__, "credential_paths": creds, "kind": "gate", "adapter": None}))
    assert (str(cache),) in pairs(gate, "--tmpfs")


def test_chdir_follows_the_requested_cwd_and_defaults_to_the_worktree(make_spec, tmp_path):
    spec = make_spec("agent", "codex")
    empty = spec.tmp_dir / "judge-cwd"
    argv = BwrapSandbox("/usr/bin/bwrap").build_argv(["codex", "exec"], spec, ENV, empty)
    assert argv[-5:] == ["--chdir", str(empty), "--", "codex", "exec"]
    assert argv.count("--chdir") == 1
    default = build(spec, ["x"])
    assert default[default.index("--chdir") + 1] == str(spec.worktree)
    # the empty directory is below a read-write mount (the step's private dir), so it exists inside the sandbox
    assert (str(spec.tmp_dir),) * 2 in pairs(argv, "--bind") and empty.is_relative_to(spec.tmp_dir)
    wrapped = BwrapSandbox("/usr/bin/bwrap").wrap(["x"], spec, ENV, empty)
    assert wrapped.argv[wrapped.argv.index("--chdir") + 1] == str(empty)


RESOLV = "../run/systemd/resolve/stub-resolv.conf"


def host_root(tmp_path: Path, *, var_run: str | None = "../run", resolv: str | None = RESOLV) -> Path:
    """A stand-in for `/`: /run is a directory, /var/run a symlink (or a directory, or a link elsewhere),
    /etc/resolv.conf a symlink into /run, as on Ubuntu."""
    root = tmp_path / "hostroot"
    (root / "run" / "systemd" / "resolve").mkdir(parents=True)
    (root / "var").mkdir()
    (root / "etc").mkdir()
    if var_run == "dir":
        (root / "var" / "run").mkdir()
    elif var_run:
        (root / "var" / "run").symlink_to(var_run)
    if resolv:
        (root / "etc" / "resolv.conf").symlink_to(resolv)
    return root


def masked(root: Path, make_spec, kind: str) -> list[str]:
    return BwrapSandbox("/usr/bin/bwrap", host_root=root).build_argv(["true"], make_spec(kind), ENV)


@pytest.mark.parametrize("kind", ["agent", "gate"])
def test_run_is_masked_so_a_container_daemon_socket_is_unreachable_in_both_kinds(tmp_path, make_spec, kind):
    """HB-1: `--ro-bind / /` does not stop connect() on /var/run/docker.sock (the runner user is in group docker)."""
    argv = masked(host_root(tmp_path), make_spec, kind)
    assert ("/run",) in pairs(argv, "--tmpfs")
    # the mask comes right after the root bind and before any bind that could put something back
    assert argv.index("/run") > argv.index("/tmp") and argv.index("/run") < argv.index("--unshare-pid")
    # /var/run -> ../run is covered by the /run mask: no second tmpfs
    assert ("/var/run",) not in pairs(argv, "--tmpfs")
    # only the resolver file is put back, read-only (Ubuntu's /etc/resolv.conf points into /run)
    resolver = "/run/systemd/resolve/stub-resolv.conf"
    at = argv.index("--ro-bind-try")
    assert argv[at : at + 3] == ["--ro-bind-try", resolver, resolver] and argv.count("--ro-bind-try") == 1
    assert argv.index("--tmpfs") < at < argv.index("--unshare-pid")
    assert "/run/user" not in " ".join(argv) and "docker.sock" not in " ".join(argv)


def test_a_var_run_that_is_a_real_directory_is_masked_too(tmp_path, make_spec):
    argv = masked(host_root(tmp_path, var_run="dir"), make_spec, "agent")
    assert {("/run",), ("/var/run",)} <= set(pairs(argv, "--tmpfs"))


def test_a_var_run_that_links_elsewhere_masks_the_target(tmp_path, make_spec):
    root = host_root(tmp_path, var_run="../srv/daemons")
    (root / "srv" / "daemons").mkdir(parents=True)
    argv = masked(root, make_spec, "gate")
    assert ("/srv/daemons",) in pairs(argv, "--tmpfs") and ("/var/run",) not in pairs(argv, "--tmpfs")


def test_a_resolver_that_is_not_in_run_adds_nothing(tmp_path, make_spec):
    argv = masked(host_root(tmp_path, resolv=None), make_spec, "agent")
    assert "--ro-bind-try" not in argv and ("/run",) in pairs(argv, "--tmpfs")
    root = host_root(tmp_path / "b", resolv="/etc/real-resolv.conf")  # a link to a file outside /run
    assert "--ro-bind-try" not in masked(root, make_spec, "agent")


def test_a_resolver_in_run_user_is_never_put_back(tmp_path, make_spec):
    """/run/user/<uid> may hold dbus, podman and gpg sockets."""
    argv = masked(host_root(tmp_path, resolv="/run/user/1000/resolv.conf"), make_spec, "agent")
    assert "--ro-bind-try" not in argv


def test_a_resolver_link_chain_is_followed_to_its_end(tmp_path, make_spec):
    root = host_root(tmp_path, resolv="resolv-link")
    (root / "etc" / "resolv-link").symlink_to("../run/resolvconf/resolv.conf")
    argv = masked(root, make_spec, "agent")
    at = argv.index("--ro-bind-try")
    assert argv[at + 1 : at + 3] == ["/run/resolvconf/resolv.conf"] * 2


def test_nothing_is_masked_on_a_host_without_run(make_spec):
    argv = build(make_spec("agent"))
    assert "/run" not in argv and "--ro-bind-try" not in argv  # bwrap cannot mkdir a mount point under a read-only /


def guidance(spec: SandboxSpec, *dirs: str) -> None:
    for rel in dirs:
        (spec.worktree / rel).mkdir(parents=True, exist_ok=True)


@pytest.mark.parametrize("kind", ["agent", "gate"])
def test_repo_guidance_directories_are_covered_by_a_tmpfs_after_the_binds(make_spec, kind):
    """HB-X1: no switch of Codex (skills) removes `.agents/skills` and `.codex/skills`, so no CLI sees a repo
    guidance directory at all; they are contract-protected, so an agent step has no use
    for them. Gates run agent-written code."""
    spec = make_spec(kind)
    guidance(spec, ".claude/skills", ".agents/skills", ".codex/skills", ".opencode", ".hermes", ".kiro/steering")
    argv = build(spec)
    masked = {p for (p,) in pairs(argv, "--tmpfs")}
    wt = spec.worktree
    assert {str(wt / d) for d in (".claude", ".agents", ".codex", ".opencode", ".hermes")} <= masked
    assert str(wt / ".kiro" / "steering") in masked
    assert argv.index(str(wt / ".claude")) > argv.index("--bind")  # a mount over a path needs the bind below it first
    assert argv.index(str(wt / ".claude")) > argv.index(str(spec.tmp_dir))  # after every bind
    # nothing the harness hands the step is under a masked path: the private dir, caches, `.git`; the base `/tmp`
    # tmpfs comes before every bind, so a private dir under the host's /tmp (pytest's, on Linux) is bound over it
    assert not any(str(spec.tmp_dir).startswith(m + "/") for m in masked - {"/tmp"})


def test_only_existing_guidance_directories_are_masked_never_created(make_spec):
    """Under a read-only root bwrap cannot create a mount point: bwrap would write into the real worktree."""
    spec = make_spec("agent", "codex")
    argv = build(spec)
    assert not [a for a in argv if str(spec.worktree) + "/" in a]
    assert not list(spec.worktree.iterdir())  # building the argv created nothing in the worktree
    guidance(spec, ".claude")
    (spec.worktree / ".agents").write_text("a file, not a skill root")
    assert pairs(build(spec), "--tmpfs").count((str(spec.worktree / ".claude"),)) == 1
    assert str(spec.worktree / ".agents") not in build(spec)


def test_the_kiro_spec_root_stays_visible(make_spec):
    """`.kiro/specs/**` is the spec root (read by the step, L4-SEC-004): only the Kiro CLI's own guidance
    (`steering`, `agents`, `settings`, `hooks`, `prompts`) is masked, never `.kiro` as a whole."""
    spec = make_spec("agent", "codex")
    guidance(spec, ".kiro/specs/x", ".kiro/steering", ".kiro/agents", ".kiro/settings", ".kiro/hooks", ".kiro/prompts")
    masked = {p for (p,) in pairs(build(spec), "--tmpfs")}
    kiro = spec.worktree / ".kiro"
    assert str(kiro) not in masked and str(kiro / "specs") not in masked
    assert {str(kiro / d) for d in ("steering", "agents", "settings", "hooks", "prompts")} <= masked


def test_a_guidance_directory_that_is_a_symlink_is_not_mounted_over(tmp_path, make_spec):
    """bwrap resolves a symlink destination: `.claude -> /etc` would put a tmpfs over `/etc`."""
    spec = make_spec("agent", "codex")
    (spec.worktree / ".claude").symlink_to("/etc")
    argv = build(spec)
    assert str(spec.worktree / ".claude") not in argv and ("/etc",) not in pairs(argv, "--tmpfs")


@pytest.mark.parametrize("kind", ["agent", "gate"])
def test_no_later_mount_re_exposes_a_masked_guidance_directory(make_spec, kind):
    """A bind of a path at or above the worktree after the tmpfs puts the host directory back, `.claude` included
    (seen live in the HB-X1 canary: a bind of the parent after the mask ran the repo's hook). `sandbox.caches` accepts
    any path inside `$L4_CACHE`, `$L4_CACHE/worktrees` too: the masks come after every bind."""
    spec = make_spec(kind)
    above = CacheMount(spec.worktree.parent, "ABOVE_CACHE")
    spec = replace(spec, caches=(above,))
    guidance(spec, ".claude/skills", ".agents/skills")
    argv = build(spec)
    masks = [i for i, a in enumerate(argv) if a == "--tmpfs" and argv[i + 1].startswith(str(spec.worktree) + "/")]
    mounts = [i for i, a in enumerate(argv) if a in ("--bind", "--ro-bind") and i < argv.index("--clearenv")]
    assert len(masks) == 2 and min(masks) > max(mounts)
    assert argv[max(masks) + 2] == "--clearenv"


def test_kiro_token_store_is_mounted_for_kiro_and_hidden_from_every_other_spawn(make_spec):
    """K2: the login of kiro-cli lives in its data store, not in `~/.kiro` (2.28.0: `data.sqlite3`, table `auth_kv`)."""
    from l4.config.defaults import CREDENTIAL_PATHS
    from l4.sandbox.base import expand_credential_paths

    assert {"~/.local/share/kiro-cli", "~/Library/Application Support/kiro-cli"} <= set(CREDENTIAL_PATHS["kiro-cli"])
    spec = make_spec("agent", "codex")
    store = spec.home / ".local" / "share" / "kiro-cli"
    store.mkdir(parents=True)
    creds = expand_credential_paths({k: list(v) for k, v in CREDENTIAL_PATHS.items()}, spec.home)
    for adapter in ("codex", "claude-code", "opencode"):
        argv = build(SandboxSpec(**{**spec.__dict__, "credential_paths": creds, "adapter": adapter}))
        assert (str(store),) in pairs(argv, "--tmpfs") and (str(store),) * 2 not in pairs(argv, "--bind")
    gate = build(SandboxSpec(**{**spec.__dict__, "credential_paths": creds, "kind": "gate", "adapter": None}))
    assert (str(store),) in pairs(gate, "--tmpfs")
    own = build(SandboxSpec(**{**spec.__dict__, "credential_paths": creds, "adapter": "kiro-cli"}))
    assert (str(store),) * 2 in pairs(own, "--bind") and (str(store),) not in pairs(own, "--tmpfs")
