"""OpenViking push (#73): VIKING_API_KEY reaches only the loopback endpoint the user's `push DATE`
targets, never a proxy or a redirect target. A real HTTP server on 127.0.0.1 stands in for Viking;
the key is a dummy."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import pytest
from screen_context.config import Settings
from screen_context import store, viking

KEY = "dummy-viking-key"


class Server:
    """Records each request; answers with `reply(handler)` (status, headers, body)."""
    def __init__(self, reply):
        self.seen = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def handle_one(self):
                length = int(self.headers.get("Content-Length") or 0)
                outer.seen.append({"method": self.command, "path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()},
                                   "body": self.rfile.read(length) if length else b""})
                status, headers, body = reply(self)
                self.send_response(status)
                for k, v in headers.items(): self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            do_POST = do_GET = handle_one
            def log_message(self, *args): pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self): self.httpd.shutdown(); self.httpd.server_close()


@pytest.fixture
def cfg(tmp_path):
    value = Settings(tmp_path, plaintext=True)
    store.initialize(value)
    return value


def ok(handler): return 200, {"Content-Type": "application/json"}, b'{"status":"success"}'


def test_push_success_dedup_and_namespace(cfg, monkeypatch):
    monkeypatch.setenv("VIKING_API_KEY", KEY)
    server = Server(ok)
    try:
        assert viking.push(cfg, "2026-09-12", endpoint=server.url)["status"] == "uploaded"
        assert viking.push(cfg, "2026-09-12", endpoint=server.url)["status"] == "unchanged"
    finally: server.close()
    [request] = server.seen
    assert request["method"] == "POST" and request["path"] == "/api/v1/resources"
    assert json.loads(request["body"])["to"] == "viking://resources/screen_context/2026-09-12"
    assert request["headers"]["x-api-key"] == KEY


def test_no_key_header_without_a_key(cfg, monkeypatch):
    monkeypatch.delenv("VIKING_API_KEY", raising=False)
    server = Server(ok)
    try: viking.push(cfg, "2026-09-12", endpoint=server.url)
    finally: server.close()
    assert "x-api-key" not in server.seen[0]["headers"]


def test_a_redirect_is_not_followed_and_the_key_goes_nowhere_else(cfg, monkeypatch):
    monkeypatch.setenv("VIKING_API_KEY", KEY)
    elsewhere = Server(ok)                      # stands in for a host the redirect points to
    for code in (301, 302, 303, 307, 308):
        server = Server(lambda h: (code, {"Location": elsewhere.url + "/stolen"}, b""))
        try:
            with pytest.raises(Exception): viking.push(cfg, "2026-09-12", endpoint=server.url)
        finally: server.close()
    elsewhere.close()
    assert elsewhere.seen == []
    assert not list((cfg.root / "exports").glob("*.receipt"))


def test_a_proxy_from_the_environment_is_not_used(cfg, monkeypatch):
    monkeypatch.setenv("VIKING_API_KEY", KEY)
    proxy = Server(ok)                          # would see the request if HTTP_PROXY were honoured
    target = Server(ok)
    for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY"): monkeypatch.setenv(name, proxy.url)
    monkeypatch.delenv("NO_PROXY", raising=False); monkeypatch.delenv("no_proxy", raising=False)
    try: viking.push(cfg, "2026-09-12", endpoint=target.url)
    finally: proxy.close(); target.close()
    assert proxy.seen == [] and target.seen[0]["headers"]["x-api-key"] == KEY


@pytest.mark.parametrize("endpoint", ["https://example.com", "http://192.168.1.10:1933", "http://localhost.example.com:1933",
                                      "ftp://127.0.0.1:1933", "file:///etc/passwd", "http://127.0.0.1.nip.io:1933"])
def test_only_loopback_endpoints(cfg, monkeypatch, endpoint):
    monkeypatch.setenv("VIKING_API_KEY", KEY)
    with pytest.raises(ValueError): viking.push(cfg, "2026-09-12", endpoint=endpoint)
    assert not list((cfg.root / "exports").glob("*.json"))      # refused before anything is exported


def test_push_timeout_not_acknowledged(cfg):
    class Slow:
        def open(self, request, timeout): raise TimeoutError
    with pytest.raises(TimeoutError): viking.push(cfg, "2026-09-12", opener=Slow())
    assert not list((cfg.root / "exports").glob("*.receipt"))


def test_a_failed_answer_is_not_acknowledged(cfg):
    server = Server(lambda h: (200, {"Content-Type": "application/json"}, b'{"status":"error"}'))
    try:
        with pytest.raises(RuntimeError): viking.push(cfg, "2026-09-12", endpoint=server.url)
    finally: server.close()
    assert not list((cfg.root / "exports").glob("*.receipt"))
