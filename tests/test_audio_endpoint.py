"""POST /audio 端點測試。

範圍：
- 缺 GROQ_API_KEY → 503
- mock Groq STT → 回傳意圖 + action
- 非 unknown 意圖 → forward 到 bridge
- 缺 audio 欄位 → 400
"""

import io
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from companion.server import create_app
from companion.bridge_client import BridgeClient


def _make_audio_blob() -> bytes:
    """假音檔 bytes（內容無關緊要，Groq 呼叫會被 mock 掉）。"""
    return b"\x00" * 1024


@pytest.fixture
def app_and_bridge():
    bridge = BridgeClient(url="ws://localhost:8766", mock_mode=True)
    app = create_app(bridge=bridge)
    return app, bridge


def test_audio_endpoint_missing_groq_key_returns_503(app_and_bridge, monkeypatch):
    """缺 GROQ_API_KEY → 503 + 友善錯誤訊息，不 crash。"""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    app, _ = app_and_bridge
    with TestClient(app) as client:
        r = client.post(
            "/audio",
            files={"audio": ("blob.webm", io.BytesIO(_make_audio_blob()), "audio/webm")},
        )
        assert r.status_code == 503
        body = r.json()
        # 訊息只要有提示就好
        assert "groq" in (body.get("detail") or "").lower() or "GROQ" in (body.get("detail") or "")


def test_audio_endpoint_with_mock_groq_returns_intent(app_and_bridge, monkeypatch):
    """mock Groq → 端點回傳 text + intent + action。"""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    app, _ = app_and_bridge
    with TestClient(app) as client:
        # patch 對 Groq 的呼叫，回固定文字
        async def _fake(_path: str, _api_key: str) -> str:
            return "閉嘴五分鐘"

        with patch("companion.server._call_groq_stt", new=_fake):
            r = client.post(
                "/audio",
                files={"audio": ("blob.webm", io.BytesIO(_make_audio_blob()), "audio/webm")},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["text"] == "閉嘴五分鐘"
            assert body["intent"] == "mode_silent"
            assert body["action"] == "mode_change"


def test_audio_endpoint_forwards_event_to_bridge(app_and_bridge, monkeypatch):
    """非 unknown 意圖 → bridge.send 被呼叫且 type 正確。"""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    app, bridge = app_and_bridge
    with TestClient(app) as client:
        async def _fake(_path: str, _api_key: str) -> str:
            return "嚴肅模式"

        with patch("companion.server._call_groq_stt", new=_fake):
            r = client.post(
                "/audio",
                files={"audio": ("blob.webm", io.BytesIO(_make_audio_blob()), "audio/webm")},
            )
            assert r.status_code == 200

        # mock_mode bridge：sent_messages 應該有一個 mode_change
        assert len(bridge.sent_messages) == 1
        sent = bridge.sent_messages[0]
        assert sent["type"] == "mode_change"
        assert sent["payload"]["mode"] == "serious"
        assert isinstance(sent["ts"], (int, float))


def test_audio_endpoint_unknown_intent_does_not_forward(app_and_bridge, monkeypatch):
    """unknown 意圖 → 不 forward 到 bridge。"""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    app, bridge = app_and_bridge
    with TestClient(app) as client:
        async def _fake(_path: str, _api_key: str) -> str:
            return "今天天氣不錯"

        with patch("companion.server._call_groq_stt", new=_fake):
            r = client.post(
                "/audio",
                files={"audio": ("blob.webm", io.BytesIO(_make_audio_blob()), "audio/webm")},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["intent"] == "unknown"
        assert bridge.sent_messages == []


def test_audio_endpoint_no_audio_field_returns_400(app_and_bridge, monkeypatch):
    """缺 audio 欄位 → 400/422 之類的請求錯誤，不可 500。"""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    app, _ = app_and_bridge
    with TestClient(app) as client:
        r = client.post("/audio")
        assert r.status_code in (400, 422)
