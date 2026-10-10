"""SANDBOX-002 (HB-1, SPEC L4-SEC-005): no container-daemon socket is reachable from the bwrap sandboxes. Registered
at import.

`--ro-bind / /` does not stop `connect()` on a unix socket, so a runner user in group `docker` reached
`/var/run/docker.sock` (root on the host) from inside the sandbox. The check runs a tiny probe with the real base argv
(`l4.sandbox.bwrap.base_flags`, the part both kinds share) once with the network shared (the agent kind) and once
unshared (a gate with `gates.network: none`), and FAILS when a socket is visible or connectable. It is the narrow
check; the full SANDBOX-001 (credentials, ancestor environment) is separate.
"""

from l4.doctor.context import DoctorContext
from l4.doctor.registry import Check, CheckResult, register
from l4.sandbox.bwrap import base_flags

CLEAN = "L4-SOCKETS-OK"
REACHABLE = "L4-SOCKETS-REACHABLE:"
PROBE_TIMEOUT_S = 30.0

# Runs INSIDE the sandbox. Known daemon sockets are connected to; anything that is a socket under /run or /var/run is
# also reported, because after the mask nothing but a resolver file is supposed to be there.
PROBE = f"""
import os, socket, stat
found = []
uid = os.getuid()
for path in ("/var/run/docker.sock", "/run/docker.sock", "/run/containerd/containerd.sock", "/run/podman/podman.sock",
             "/run/dbus/system_bus_socket", f"/run/user/{{uid}}/podman/podman.sock", f"/run/user/{{uid}}/bus"):
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(3)
    try:
        s.connect(path)
        found.append("connect:" + path)
    except OSError:
        pass
    finally:
        s.close()
for top in ("/run", "/var/run"):
    for dirpath, dirs, files in os.walk(top, onerror=lambda e: None):
        if dirpath.count("/") > 5:
            dirs[:] = []
        for name in dirs + files:
            full = os.path.join(dirpath, name)
            try:
                if stat.S_ISSOCK(os.lstat(full).st_mode):
                    found.append("socket:" + full)
            except OSError:
                pass
print({REACHABLE!r} + " " + ", ".join(sorted(set(found))) if found else {CLEAN!r})
"""

KINDS = ((True, "agent sandbox (network shared)"), (False, "gate sandbox (--unshare-net)"))


def _sandbox_002(ctx: DoctorContext) -> CheckResult:
    if ctx.cfg.sandbox.mode not in ("auto", "bwrap"):
        return CheckResult("skip", f"sandbox.mode is {ctx.cfg.sandbox.mode}: not a bwrap sandbox")
    bwrap, python = ctx.which("bwrap"), ctx.which("python3")
    if not bwrap:
        return CheckResult("skip", "bwrap was not found on PATH (the sandbox is unavailable, so nothing runs in it)")
    if not python:
        return CheckResult("fail", "python3 was not found on PATH: the sandbox probe cannot run")
    leaks: list[str] = []
    for network, label in KINDS:
        argv = [bwrap, *base_flags(network=network), "--", python, "-c", PROBE]
        done = ctx.run(argv, timeout=PROBE_TIMEOUT_S, env={"PATH": "/usr/bin:/bin"})
        out = done.stdout.strip().splitlines()
        last = out[-1] if out else ""
        if last.startswith(REACHABLE):
            leaks.append(f"{label}: {last.removeprefix(REACHABLE).strip()}")
        elif last != CLEAN:
            detail = (done.stderr.strip().splitlines() or [f"exit {done.returncode}"])[-1][:200]
            return CheckResult("fail", f"the sandbox probe did not run in the {label}: {detail}")
    if leaks:
        return CheckResult(
            "fail",
            "a daemon socket is reachable from inside the sandbox (root-equivalent if it is the docker socket): "
            + "; ".join(leaks),
            "the bwrap argv must cover /run and /var/run with a tmpfs (l4.sandbox.bwrap.daemon_socket_masks); "
            "also check for a socket outside /run, and remove the runner user from the docker group if no job needs it",
        )
    return CheckResult("pass", "no container-daemon socket is reachable from the agent or the gate sandbox")


SANDBOX_002 = register(Check("SANDBOX-002", "No daemon socket reachable from the sandboxes", "error", _sandbox_002))
