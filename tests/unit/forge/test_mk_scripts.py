"""The Mintkey wrappers under scripts/ (M1.8 A10, A12): fake `curl` and a fake `l4` on PATH, a temp HOME with a fake
`~/.claude.json`. No Mintkey, no GitLab, no network."""

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
FORGE = ROOT / "scripts" / "forge"
DEV = ROOT / "scripts" / "dev"
JWT = "JWT-FAKE-ABC123-brokered"
AGENT_KEY = "mk_agent_FAKEKEY0123456789"
SECRET_VALUE = "typesafe-secret-value-777"

FAKE_CURL = r"""#!/bin/sh
# a fake curl: reads the config from stdin when given `-K -`, answers by URL, records the argv it saw
config=""
url=""
mode_fail=0
while [ $# -gt 0 ]; do
  case "$1" in
    -K) shift; config=$(cat);;
    -s|-S|-f|-fsS|-sS|-fS) ;;
    -X|-H|-d|-o|-w|--write-out|--output) shift;;
    http*) url=$1;;
  esac
  shift
done
echo "$url" >> "$FAKE_CURL_LOG"
printf '%s\n' "$config" >> "$FAKE_CURL_LOG"
case "$url" in
  */v1/tools/list_services) echo '{"services":[{"id":"svc_1","slug":"example-gitlab"},{"id":"svc_2","slug":"other"}]}';;
  */v1/tools/request_token) echo '{"token":"JWT-FAKE-ABC123-brokered","expires_at":4102444800}';;
  */v1/tools/secret_list*) echo '{"secrets":[{"secret_id":"sec_9","name":"typesafe-jev-api-key"}],"next_cursor":null}';;
  */v1/tools/secret_get*) echo '{"value":"typesafe-secret-value-777"}';;
  *) echo "fake curl: no route for $url" >&2; exit 22;;
esac
"""

FAKE_L4 = r"""#!/bin/sh
{
  for a in "$@"; do echo "ARG $a"; done
  echo "ENV MK_JWT=${MK_JWT:-}"
  echo "ENV L4_MK_SECRET_TYPESAFE_API_KEY=${L4_MK_SECRET_TYPESAFE_API_KEY:-}"
} > "$FAKE_L4_LOG"
exit "${FAKE_L4_EXIT:-0}"
"""


@pytest.fixture
def world(tmp_path):
    bin_dir, home = tmp_path / "bin", tmp_path / "home"
    for d in (bin_dir, home, tmp_path / "out"):
        d.mkdir()
    (home / ".claude.json").write_text(
        json.dumps({"mcpServers": {"mintkey": {"headers": {"Authorization": f"Bearer {AGENT_KEY}"}}}})
    )
    for name, text in (("curl", FAKE_CURL), ("l4fake", FAKE_L4)):
        (bin_dir / name).write_text(text)
        (bin_dir / name).chmod(0o755)
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(home), "L4_BIN": str(bin_dir / "l4fake"),
        "FAKE_CURL_LOG": str(tmp_path / "out" / "curl.log"), "FAKE_L4_LOG": str(tmp_path / "out" / "l4.log"),
        "GITLAB_API": "https://gitlab.example.test/api/v4",
    }  # fmt: skip
    return tmp_path, env


def run(script: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(script), *args], env=env, capture_output=True, text=True, check=False)


def test_setup_wrapper_passes_the_proxy_form_and_no_jwt_in_argv(world):
    tmp_path, env = world
    done = run(
        FORGE / "mk-l4-setup-gitlab.sh", env, "--project", "g/p", "--watch",
        "--mk-secret", "TYPESAFE_API_KEY=typesafe-jev-api-key",
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    seen = (tmp_path / "out" / "l4.log").read_text().splitlines()
    args = [line.removeprefix("ARG ") for line in seen if line.startswith("ARG ")]
    at = args.index("--token-command")  # the wrapper's own refresh (M1.10): checked by its own test below
    assert args[at : at + 2] == ["--token-command", f"{FORGE / 'mk-l4-setup-gitlab.sh'} --print-jwt"]
    args = args[:at] + args[at + 2 :]
    assert args == [
        "setup", "gitlab", "--api-base", "http://localhost:8000/v1/call/svc_1", "--auth-env", "MK_JWT",
        "--auth-scheme", "bearer", "--verify-base", "https://gitlab.example.test/api/v4", "--project", "g/p",
        "--watch", "--secret", "TYPESAFE_API_KEY=L4_MK_SECRET_TYPESAFE_API_KEY",
    ]  # fmt: skip
    assert f"ENV MK_JWT={JWT}" in seen  # the brokered JWT reached l4 through the environment ...
    assert f"ENV L4_MK_SECRET_TYPESAFE_API_KEY={SECRET_VALUE}" in seen
    for secret in (JWT, SECRET_VALUE, AGENT_KEY):  # ... and nowhere in an argv
        assert not any(secret in a for a in args)
        assert secret not in done.stdout + done.stderr
    # the Mintkey agent key goes to curl through its config on stdin, not its argv; the JWT is never written to disk
    log = (tmp_path / "out" / "curl.log").read_text()
    assert f"Bearer {AGENT_KEY}" in log
    written = [  # what the wrapper could have written: HOME and the temp dir the fakes log to (not the fakes)
        p
        for d in ("home", "out")
        for p in (tmp_path / d).rglob("*")
        if p.is_file() and p.name not in ("l4.log", "curl.log")
    ]
    for path in written:
        assert JWT not in path.read_text(errors="ignore") and SECRET_VALUE not in path.read_text(errors="ignore")


def test_setup_wrapper_without_secrets_and_with_a_failing_l4(world):
    tmp_path, env = world
    done = run(FORGE / "mk-l4-setup-gitlab.sh", env, "--project", "119")
    assert done.returncode == 0
    args = [
        x.removeprefix("ARG ") for x in (tmp_path / "out" / "l4.log").read_text().splitlines() if x.startswith("ARG ")
    ]
    assert args[-2:] == ["--project", "119"] and "--secret" not in args and "--token-command" in args
    failing = run(FORGE / "mk-l4-setup-gitlab.sh", {**env, "FAKE_L4_EXIT": "3"}, "--project", "119")
    assert failing.returncode == 3  # l4's own exit code is the wrapper's (it `exec`s)


def test_print_jwt_prints_to_a_pipe_and_refuses_a_terminal(world):
    """`--print-jwt` is what `l4 --token-command` runs to get a fresh JWT: it prints it to a pipe and never to a
    terminal (M1.10 decision 14). A fake `curl` answers the broker."""
    import pty

    tmp_path, env = world
    done = run(FORGE / "mk-l4-setup-gitlab.sh", env, "--print-jwt")
    assert done.returncode == 0 and done.stdout == f"{JWT}\n"  # exactly one line: the credential
    assert not (tmp_path / "out" / "l4.log").exists()  # l4 was not run
    master, slave = pty.openpty()
    try:
        tty = subprocess.run(
            ["bash", str(FORGE / "mk-l4-setup-gitlab.sh"), "--print-jwt"], env=env, stdout=slave,
            stderr=subprocess.PIPE, text=True, check=False,
        )  # fmt: skip
        os.close(slave)
        shown = os.read(master, 4096).decode()
    finally:
        os.close(master)
    assert tty.returncode == 2 and JWT not in shown and JWT not in tty.stderr
    assert "terminal" in tty.stderr  # it says why


def test_the_wrapper_passes_its_own_token_command(world):
    tmp_path, env = world
    done = run(FORGE / "mk-l4-setup-gitlab.sh", env, "--project", "119")
    assert done.returncode == 0, done.stderr
    args = [
        x.removeprefix("ARG ") for x in (tmp_path / "out" / "l4.log").read_text().splitlines() if x.startswith("ARG ")
    ]
    command = args[args.index("--token-command") + 1]
    assert command == f"{FORGE / 'mk-l4-setup-gitlab.sh'} --print-jwt"  # its absolute path, no credential in it
    assert JWT not in command and AGENT_KEY not in command
    import shlex

    assert shlex.split(command) == [str(FORGE / "mk-l4-setup-gitlab.sh"), "--print-jwt"]
    spaced = tmp_path / "with space" / "mk-l4-setup-gitlab.sh"  # a path with a space survives the shlex split
    spaced.parent.mkdir()
    spaced.write_text((FORGE / "mk-l4-setup-gitlab.sh").read_text())
    assert run(spaced, env, "--project", "119").returncode == 0
    args = [
        x.removeprefix("ARG ") for x in (tmp_path / "out" / "l4.log").read_text().splitlines() if x.startswith("ARG ")
    ]
    assert shlex.split(args[args.index("--token-command") + 1]) == [str(spaced), "--print-jwt"]


def test_setup_wrapper_stops_when_the_service_is_not_there(world):
    tmp_path, env = world
    done = run(FORGE / "mk-l4-setup-gitlab.sh", {**env, "MINTKEY_GITLAB_SLUG": "no-such-slug"}, "--project", "119")
    assert done.returncode != 0 and not (tmp_path / "out" / "l4.log").exists()


@pytest.mark.parametrize("script", ["gitlab_bot_token.py", "gitlab_ci_var_from_mintkey.py"])
def test_the_old_scripts_point_to_the_command(script):
    text = (FORGE / script).read_text()
    assert "l4 setup gitlab" in text.split('"""')[1]  # in the docstring, where `--help` shows it
    assert "mk-gitlab-bot-token.sh" not in script
    assert "l4 setup gitlab" in (FORGE / "mk-gitlab-bot-token.sh").read_text()


# --- scripts/dev/mk-gitlab-api.sh (A12) ---------------------------------------------------------------------------

API_CURL = r"""#!/bin/sh
# a fake curl that honours -f, -o and -w, and answers by URL. FAKE_PROXY_CODES and FAKE_TOOLS_CODES ("502,200") script
# the status of the n-th call of the proxy (`/v1/call/...`) and of Mintkey's tools API (`/v1/tools/...`); the last one
# repeats. FAKE_CURL_LOG names a file, and `$FAKE_CURL_LOG.<kind>` counts the calls.
nth() {  # nth <kind> <list> <default>: the status of this call of that kind
  n=$(( $(cat "$FAKE_CURL_LOG.$1" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$FAKE_CURL_LOG.$1"
  [ -z "$2" ] && { echo "$3"; return; }
  list=$(echo "$2" | tr ',' ' '); pick=""; i=0
  for c in $list; do i=$((i + 1)); pick=$c; [ "$i" -ge "$n" ] && break; done
  echo "$pick"
}
out=""; fmt=""; url=""; fail=0
while [ $# -gt 0 ]; do
  case "$1" in
    -o) shift; out=$1;;
    -w) shift; fmt=$1;;
    -f|-fsS|-fS) fail=1;;
    -X|-H|-d) shift;;
    http*) url=$1;;
  esac
  case "$1" in -*f*) case "$1" in -fsS|-fS|-f) fail=1;; esac;; esac
  shift
done
echo "$url" >> "$FAKE_CURL_LOG"
case "$url" in
  */v1/tools/list_services)
    code=$(nth tools "${FAKE_TOOLS_CODES:-}" "${FAKE_LIST_CODE:-200}")
    body='{"services":[{"id":"svc_1","slug":"example-gitlab"}]}';;
  */v1/tools/request_token)
    code=$(nth tools "${FAKE_TOOLS_CODES:-}" 200)
    body='{"token":"JWT-FAKE-ABC123-brokered","expires_at":4102444800}';;
  */v1/call/svc_1/projects/119) code=$(nth proxy "${FAKE_PROXY_CODES:-}" 200); body='{"id":119}';;
  */v1/call/svc_1/projects/999) code=404; body='{"message":"404 Project Not Found"}';;
  *) code=500; body='{"message":"unexpected"}';;
esac
if [ "$fail" = 1 ] && [ "$code" -ge 400 ]; then echo "curl: (22) returned error: $code" >&2; exit 22; fi
if [ -n "$out" ]; then printf '%s' "$body" > "$out"; else printf '%s\n' "$body"; fi
if [ -n "$fmt" ]; then printf '%s' "$code"; fi
exit 0
"""


@pytest.fixture
def api_world(world):
    tmp_path, env = world
    (tmp_path / "bin" / "curl").write_text(API_CURL)
    return tmp_path, {**env, "L4GL_ENV": str(tmp_path / "out" / "l4gl.env"), "L4GL_RETRY_WAIT": "0"}


def test_mk_gitlab_api_exits_22_on_404_and_prints_the_body(api_world):
    tmp_path, env = api_world
    ok = run(DEV / "mk-gitlab-api.sh", env, "GET", "projects/119")
    assert ok.returncode == 0 and json.loads(ok.stdout) == {"id": 119} and ok.stderr == ""
    missing = run(DEV / "mk-gitlab-api.sh", env, "GET", "projects/999")
    assert missing.returncode == 22
    assert "404 Project Not Found" in missing.stdout  # the body is still printed
    assert "HTTP 404 GET projects/999" in missing.stderr  # and the status is said, on stderr


def test_a_failing_mintkey_call_stops_the_script(api_world):
    tmp_path, env = api_world
    done = run(DEV / "mk-gitlab-api.sh", {**env, "FAKE_LIST_CODE": "503"}, "GET", "projects/119")
    assert done.returncode != 0 and done.stdout == ""  # `-fsS`: the script stops, the error is on stderr
    assert "returned error: 503" in done.stderr
    assert not (tmp_path / "out" / "l4gl.env").exists()


def test_cache_path_is_overridable(api_world):
    tmp_path, env = api_world
    real = Path("/tmp/l4gl.env")
    before = (real.exists(), real.stat().st_mtime if real.exists() else None)
    assert run(DEV / "mk-gitlab-api.sh", env, "GET", "projects/119").returncode == 0
    cache = tmp_path / "out" / "l4gl.env"
    assert cache.is_file() and cache.stat().st_mode & 0o777 == 0o600
    assert f"JWT={JWT}" in cache.read_text()
    assert (
        real.exists(),
        real.stat().st_mtime if real.exists() else None,
    ) == before  # the maintainer's cache is untouched
    assert run(DEV / "mk-gitlab-api.sh", env, "GET", "projects/119").returncode == 0
    log = Path(env["FAKE_CURL_LOG"]).read_text().splitlines()
    assert sum(1 for line in log if line.endswith("/v1/tools/request_token")) == 1  # the second call reuses the JWT


# --- M1.11 W11: the service id is cached with the token; one retry for a 502 or a 401 ---------------------------------


def urls(env: dict) -> list[str]:
    return [line for line in Path(env["FAKE_CURL_LOG"]).read_text().splitlines() if line.startswith("http")]


def count(env: dict, suffix: str) -> int:
    return sum(1 for line in urls(env) if line.endswith(suffix))


def test_the_service_id_is_cached_with_the_token(api_world):
    tmp_path, env = api_world
    assert run(DEV / "mk-gitlab-api.sh", env, "GET", "projects/119").returncode == 0
    assert run(DEV / "mk-gitlab-api.sh", env, "GET", "projects/119").returncode == 0
    assert count(env, "/v1/tools/list_services") == 1 and count(env, "/v1/tools/request_token") == 1
    assert count(env, "/projects/119") == 2  # one `list_services` for two calls
    cache = (tmp_path / "out" / "l4gl.env").read_text()
    assert "SVC=svc_1" in cache and f"JWT={JWT}" in cache and "EXP=" in cache


def test_a_502_is_retried_once(api_world):
    _, env = api_world
    done = run(DEV / "mk-gitlab-api.sh", {**env, "FAKE_PROXY_CODES": "502,200"}, "GET", "projects/119")
    assert done.returncode == 0 and json.loads(done.stdout) == {"id": 119} and done.stderr == ""
    assert count(env, "/projects/119") == 2 and count(env, "/v1/tools/request_token") == 1  # same token
    tools = run(
        DEV / "mk-gitlab-api.sh",
        {**env, "FAKE_TOOLS_CODES": "502,200", "L4GL_ENV": env["L4GL_ENV"] + "2"},
        "GET",
        "projects/119",
    )
    assert tools.returncode == 0, tools.stderr  # the Mintkey tools calls get the same single retry


def test_a_401_refreshes_the_token_and_retries_once(api_world):
    tmp_path, env = api_world
    done = run(DEV / "mk-gitlab-api.sh", {**env, "FAKE_PROXY_CODES": "401,200"}, "GET", "projects/119")
    assert done.returncode == 0 and json.loads(done.stdout) == {"id": 119}
    assert count(env, "/v1/tools/list_services") == 2 and count(env, "/v1/tools/request_token") == 2
    assert count(env, "/projects/119") == 2  # the cache was dropped, the services listed and a token minted again
    assert f"JWT={JWT}" in (tmp_path / "out" / "l4gl.env").read_text()
    tools = run(
        DEV / "mk-gitlab-api.sh",
        {**env, "FAKE_TOOLS_CODES": "401,200", "L4GL_ENV": env["L4GL_ENV"] + "2"},
        "GET",
        "projects/119",
    )
    assert tools.returncode == 0, tools.stderr  # a 401 of a tools call: once more


def test_a_second_failure_exits_22_with_the_status(api_world):
    _, env = api_world
    for codes in ("502,502", "401,401"):
        done = run(
            DEV / "mk-gitlab-api.sh", {**env, "FAKE_PROXY_CODES": codes, "L4GL_ENV": env["L4GL_ENV"] + codes[:3]},
            "GET", "projects/119",
        )  # fmt: skip
        assert done.returncode == 22, done.stderr
        assert f"HTTP {codes[:3]} GET projects/119" in done.stderr
    stopped = run(
        DEV / "mk-gitlab-api.sh",
        {**env, "FAKE_TOOLS_CODES": "502,502", "L4GL_ENV": env["L4GL_ENV"] + "t"},
        "GET",
        "projects/119",
    )
    assert stopped.returncode == 22 and "returned error: 502" in stopped.stderr and stopped.stdout == ""


def test_the_jwt_is_never_printed(api_world):
    _, env = api_world
    for extra in (
        {},
        {"FAKE_PROXY_CODES": "401,200"},
        {"FAKE_PROXY_CODES": "502,502"},
        {"FAKE_TOOLS_CODES": "502,200"},
    ):
        done = run(
            DEV / "mk-gitlab-api.sh",
            {**env, **extra, "L4GL_ENV": env["L4GL_ENV"] + str(len(extra))},
            "GET",
            "projects/119",
        )
        assert JWT not in done.stdout + done.stderr and AGENT_KEY not in done.stdout + done.stderr
