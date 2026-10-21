"""M1.13 line 27 (W-C6, M1.11 W11): the proxy's intermittent 502 ("vault error") is retried more than once, with a
backoff, by `scripts/dev/mk-gitlab-api.sh`; `L4GL_RETRIES=0` keeps the single try."""

import json

from .test_mk_scripts import DEV, api_world, count, run, world  # noqa: F401 (fixtures)


def api(env, extra: dict, *path: str):
    return run(DEV / "mk-gitlab-api.sh", {**env, **extra, "L4GL_ENV": env["L4GL_ENV"] + str(len(extra))}, "GET", *path)


def test_two_502_in_a_row_are_retried_with_the_default_tries(api_world):  # noqa: F811
    _, env = api_world
    done = api(env, {"FAKE_PROXY_CODES": "502,502,200"}, "projects/119")
    assert done.returncode == 0 and json.loads(done.stdout) == {"id": 119} and done.stderr == ""
    assert count(env, "/projects/119") == 3 and count(env, "/v1/tools/request_token") == 1  # one token throughout


def test_a_502_that_never_ends_stops_after_the_retries_with_exit_22(api_world):  # noqa: F811
    _, env = api_world
    done = api(env, {"FAKE_PROXY_CODES": "502,502,502,502,200"}, "projects/119")
    assert done.returncode == 22 and "HTTP 502 GET projects/119" in done.stderr
    assert count(env, "/projects/119") == 4  # the first try and three more, then it stops


def test_the_number_of_retries_is_configurable_and_zero_keeps_one_try(api_world):  # noqa: F811
    _, env = api_world
    once = api(env, {"FAKE_PROXY_CODES": "502,200", "L4GL_RETRIES": "0"}, "projects/119")
    assert once.returncode == 22 and count(env, "/projects/119") == 1
    many = api(env, {"FAKE_PROXY_CODES": "502,502,502,502,200", "L4GL_RETRIES": "5"}, "projects/119")
    assert many.returncode == 0 and json.loads(many.stdout) == {"id": 119}


def test_two_502_of_a_mintkey_tools_call_are_retried_too(api_world):  # noqa: F811
    _, env = api_world
    done = api(env, {"FAKE_TOOLS_CODES": "502,502,200"}, "projects/119")
    assert done.returncode == 0, done.stderr
    assert count(env, "/v1/tools/list_services") == 3


def test_a_401_is_still_refreshed_once_and_not_retried_like_a_502(api_world):  # noqa: F811
    _, env = api_world
    done = api(env, {"FAKE_PROXY_CODES": "401,401,200"}, "projects/119")
    assert done.returncode == 22 and "HTTP 401" in done.stderr
