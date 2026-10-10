import httpx
import pytest

from l4.provision.runner import HttpxFetcher, IntegrityError, OfflineError, save_installer, verify_sha256

SCRIPT = b"#!/bin/sh\necho installed\n"


def fetcher(handler) -> HttpxFetcher:
    return HttpxFetcher(httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True))


def test_download_writes_the_body(tmp_path):
    f = fetcher(lambda request: httpx.Response(200, content=SCRIPT))
    assert f.download("https://example.invalid/install.sh", tmp_path / "a" / "install.sh").read_bytes() == SCRIPT


def test_transport_error_becomes_offline_error(tmp_path):
    def handler(request):
        raise httpx.ConnectError("dns", request=request)

    with pytest.raises(OfflineError) as err:
        fetcher(handler).download("https://nodejs.org/dist/x.tar.xz", tmp_path / "x")
    assert err.value.host == "nodejs.org" and err.value.reason == "ConnectError"
    assert not (tmp_path / "x").exists()
    enriched = err.value.for_tool("node", "curl -O https://nodejs.org/dist/x.tar.xz")
    assert "to install node" in str(enriched) and enriched.manual_command.startswith("curl")


def test_one_retry_on_5xx_and_none_on_4xx(tmp_path):
    calls = []

    def flaky(request):
        calls.append(1)
        return httpx.Response(503) if len(calls) == 1 else httpx.Response(200, content=b"ok")

    assert fetcher(flaky).download("https://h.invalid/f", tmp_path / "f").read_bytes() == b"ok"
    assert len(calls) == 2
    calls.clear()
    with pytest.raises(OfflineError, match="HTTP 503"):
        fetcher(lambda r: (calls.append(1), httpx.Response(503))[1]).download("https://h.invalid/f", tmp_path / "g")
    assert len(calls) == 2
    calls.clear()
    with pytest.raises(OfflineError, match="HTTP 404"):
        fetcher(lambda r: (calls.append(1), httpx.Response(404))[1]).download("https://h.invalid/f", tmp_path / "h")
    assert len(calls) == 1


def test_reachable_is_false_when_the_connection_fails(monkeypatch):
    import socket

    def refuse(*_a, **_k):
        raise OSError("no route")

    monkeypatch.setattr(socket, "create_connection", refuse)
    assert HttpxFetcher().reachable("nodejs.org") is False


class StubFetcher:
    def __init__(self, body: bytes) -> None:
        self.body, self.urls = body, []

    def download(self, url, dest):
        self.urls.append(url)
        dest.write_bytes(self.body)
        return dest

    def reachable(self, host):
        return True


def test_mismatch_removes_partial_files_and_raises(tmp_path):
    dest = tmp_path / "install.sh"
    with pytest.raises(IntegrityError, match="does not match"):
        save_installer(StubFetcher(SCRIPT), "https://h.invalid/install.sh", dest, expected="0" * 64)
    assert list(tmp_path.iterdir()) == []
    path = tmp_path / "blob"
    path.write_bytes(b"data")
    with pytest.raises(IntegrityError):
        verify_sha256(path, "f" * 64)
    assert not path.exists()


def test_save_installer_returns_and_logs_the_digest_and_makes_a_private_file(tmp_path, caplog):
    import hashlib
    import logging
    import stat

    dest = tmp_path / "install.sh"
    with caplog.at_level(logging.INFO, logger="l4.provision"):
        digest = save_installer(StubFetcher(SCRIPT), "https://h.invalid/install.sh", dest)
    assert digest == hashlib.sha256(SCRIPT).hexdigest()
    assert digest in caplog.text
    assert dest.read_bytes() == SCRIPT
    assert stat.S_IMODE(dest.stat().st_mode) == 0o700
    assert [p.name for p in tmp_path.iterdir()] == ["install.sh"]
    verify_sha256(dest, digest.upper())  # an upper-case published digest still matches
