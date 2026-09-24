import io
from unittest.mock import patch
import pytest
from screen_context.config import Settings
from screen_context import store, viking


def test_push_success_dedup_and_namespace(tmp_path):
    cfg = Settings(tmp_path, plaintext=True); store.initialize(cfg)
    def success(request, timeout):
        import json
        body = json.loads(request.data)
        assert body["to"] == "viking://resources/screen_context/2026-09-12"
        assert timeout == 35
        return io.BytesIO(b'{"status":"success"}')
    with patch.object(viking.urllib.request, "urlopen", side_effect=success) as request:
        assert viking.push(cfg, "2026-09-12")["status"] == "uploaded"
        assert viking.push(cfg, "2026-09-12")["status"] == "unchanged"
        assert request.call_count == 1


def test_push_timeout_not_acknowledged(tmp_path):
    cfg = Settings(tmp_path, plaintext=True); store.initialize(cfg)
    with patch.object(viking.urllib.request, "urlopen", side_effect=TimeoutError):
        with pytest.raises(TimeoutError): viking.push(cfg, "2026-09-12")
    assert not list((tmp_path/"exports").glob("*.receipt"))
    with pytest.raises(ValueError): viking.push(cfg, "2026-09-12", endpoint="https://example.com")
