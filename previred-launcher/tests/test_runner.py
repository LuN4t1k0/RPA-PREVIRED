import requests as _requests

import runner


def test_wait_for_server_success(monkeypatch):
    class _Resp:
        status_code = 200

    monkeypatch.setattr(runner.requests, "get", lambda url, timeout: _Resp())
    assert runner.wait_for_server(8501, timeout=2) is True


def test_wait_for_server_timeout(monkeypatch):
    def _fail(url, timeout):
        raise _requests.ConnectionError()

    monkeypatch.setattr(runner.requests, "get", _fail)
    assert runner.wait_for_server(8501, timeout=0.1) is False
