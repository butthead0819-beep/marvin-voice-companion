"""Phase 3b (Lane D) idle mode 整合測試。

只驗合約層 — UI HTML/CSS 的視覺細節不測，但
- root HTML 必須包含 idle mode 預期的 element id（bubble grid、feedback、atmos、voice button）
- /static/ 下的 CSS/JS 必須可達
- WS bridge → browser 廣播 round-trip 仍然成立
- bridge_client 預設 mock_mode 應為 False（production-ready）
- COMPANION_BRIDGE_MOCK=1 時 BridgeClient.from_env() 走 mock 模式
"""

import os

import pytest
from fastapi.testclient import TestClient

from companion.bridge_client import BridgeClient
from companion.server import create_app


@pytest.fixture
def app_and_bridge():
    bridge = BridgeClient(url="ws://localhost:8766", mock_mode=True)
    app = create_app(bridge=bridge)
    return app, bridge


# ------------------------------------------------------------------ index.html

def test_index_html_served_at_root_has_required_ids(app_and_bridge):
    app, _ = app_and_bridge
    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200
        html = r.text
        # 預期的 element id（idle mode 必備元件）
        assert 'id="bubble-grid"' in html
        assert 'id="utterance-card"' in html
        assert 'id="feedback-row"' in html
        assert 'id="atmos-grid"' in html
        assert 'id="voice-button"' in html
        assert 'id="side-panel"' in html
        assert 'id="float-input"' in html
        assert 'id="ws-status"' in html


def test_index_html_uses_fraunces_and_instrument_sans(app_and_bridge):
    app, _ = app_and_bridge
    with TestClient(app) as client:
        html = client.get("/").text
        # 沿用 mockup-v2.html 的字體
        assert "Fraunces" in html
        assert "Instrument+Sans" in html or "Instrument Sans" in html


def test_index_html_contains_traditional_chinese_strings(app_and_bridge):
    """匹配 mockup-v2.html 的關鍵字串（聆聽中、按住說話等）。"""
    app, _ = app_and_bridge
    with TestClient(app) as client:
        html = client.get("/").text
        assert "聆聽中" in html or "Marvin" in html
        assert "按住說話" in html
        # 氛圍快速控制 4 顆按鈕的文字
        assert "安靜" in html
        assert "嚴肅" in html
        assert "完全閉嘴" in html or "閉嘴" in html
        assert "恢復預設" in html or "預設" in html


# ------------------------------------------------------------------ static assets

def test_static_app_js_served(app_and_bridge):
    app, _ = app_and_bridge
    with TestClient(app) as client:
        r = client.get("/static/app.js")
        assert r.status_code == 200
        assert "WebSocket" in r.text or "ws" in r.text.lower()


def test_static_style_css_served(app_and_bridge):
    app, _ = app_and_bridge
    with TestClient(app) as client:
        r = client.get("/static/style.css")
        assert r.status_code == 200
        # 主要色票應該在 CSS 內
        assert "--amber" in r.text


# ------------------------------------------------------------------ WS round-trip

def test_stt_chunk_broadcast_reaches_browser(app_and_bridge):
    app, bridge = app_and_bridge
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            evt = {
                "type": "stt_chunk",
                "payload": {"speaker": "狗與露", "text": "你好", "engine": "Whisper"},
                "ts": 1.5,
            }

            async def emit():
                await bridge.simulate_incoming(evt)

            client.portal.call(emit)
            assert ws.receive_json() == evt


def test_atmosphere_feedback_browser_to_bridge_forwarded(app_and_bridge):
    app, bridge = app_and_bridge
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            evt = {
                "type": "atmosphere_feedback",
                "payload": {"snapshot_ts": 100.0, "label": "too_sharp"},
                "ts": 101.0,
            }
            ws.send_json(evt)
            import time
            time.sleep(0.1)
            assert evt in bridge.sent_messages


# ------------------------------------------------------------------ bridge_client defaults

def test_bridge_client_default_mock_mode_is_false():
    """production-ready：預設要連真 bridge，不再 mock。"""
    bc = BridgeClient(url="ws://localhost:8766")
    assert bc.mock_mode is False


def test_bridge_client_from_env_honors_companion_bridge_mock(monkeypatch):
    monkeypatch.setenv("COMPANION_BRIDGE_MOCK", "1")
    bc = BridgeClient.from_env()
    assert bc.mock_mode is True


def test_bridge_client_from_env_defaults_to_real_mode(monkeypatch):
    monkeypatch.delenv("COMPANION_BRIDGE_MOCK", raising=False)
    bc = BridgeClient.from_env()
    assert bc.mock_mode is False


# ------------------------------------------------------------------ Lane E: music mode

def test_index_html_has_music_panel_elements(app_and_bridge):
    """音樂模式必備 element id：music-panel、dj-panel 與內含關鍵子元素。"""
    app, _ = app_and_bridge
    with TestClient(app) as client:
        html = client.get("/").text
        assert 'id="music-panel"' in html
        assert 'id="dj-panel"' in html
        # 子元素：now playing / 控制鈕 / 反應清單 / quick buttons / dj picks / taste bars
        assert 'id="music-title"' in html
        assert 'id="music-target"' in html
        assert 'id="music-reactions"' in html
        assert 'id="music-quick"' in html
        assert 'id="dj-target-tabs"' in html
        assert 'id="dj-picks"' in html


def test_index_html_music_panel_initially_hidden(app_and_bridge):
    """idle 預設下 music-panel 與 dj-panel 應為 hidden（avoid flash）。"""
    app, _ = app_and_bridge
    with TestClient(app) as client:
        html = client.get("/").text
        # hidden 屬性或 hidden class 都接受
        assert ('id="music-panel"' in html and 'hidden' in html)


def test_music_started_event_routes_through_ws(app_and_bridge):
    """server 廣播 music_started 給 browser，不會被 protocol 過濾掉。"""
    app, bridge = app_and_bridge
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            evt = {
                "type": "music_started",
                "payload": {
                    "title": "Midnight in Taipei",
                    "style": "lo-fi",
                    "target": "Jack",
                    "source": "suno",
                    "requested_by": "Jack",
                    "started_ts": 100.0,
                },
                "ts": 101.0,
            }

            async def emit():
                await bridge.simulate_incoming(evt)

            client.portal.call(emit)
            received = ws.receive_json()
            assert received["type"] == "music_started"
            assert received["payload"]["title"] == "Midnight in Taipei"


def test_music_recommendations_request_routes_browser_to_bridge(app_and_bridge):
    """browser 送 music_recommendations_request → bridge 收到。"""
    app, bridge = app_and_bridge
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            evt = {
                "type": "music_recommendations_request",
                "payload": {"target_username": "Jack"},
                "ts": 1.0,
            }
            ws.send_json(evt)
            import time
            time.sleep(0.1)
            assert evt in bridge.sent_messages


def test_music_recommendations_response_protocol_known():
    """music_recommendations_response 為已知 bridge→browser 事件。"""
    from companion.event_protocol import KNOWN_EVENT_TYPES, BRIDGE_TO_BROWSER_EVENTS
    assert "music_recommendations_response" in BRIDGE_TO_BROWSER_EVENTS
    assert "music_recommendations_request" in KNOWN_EVENT_TYPES


# ------------------------------------------------------------------ Lane B2: voice_channel_snapshot

def test_voice_channel_snapshot_event_constant_exists():
    """VOICE_CHANNEL_SNAPSHOT 必須被收錄為 bridge→browser 事件。"""
    from companion import event_protocol as ep
    assert hasattr(ep, "VOICE_CHANNEL_SNAPSHOT")
    assert ep.VOICE_CHANNEL_SNAPSHOT == "voice_channel_snapshot"
    assert ep.VOICE_CHANNEL_SNAPSHOT in ep.BRIDGE_TO_BROWSER_EVENTS
    assert ep.VOICE_CHANNEL_SNAPSHOT in ep.KNOWN_EVENT_TYPES


def test_app_js_routes_voice_channel_snapshot():
    """app.js 必須將 voice_channel_snapshot 接到 onVoiceChannelSnapshot handler。"""
    import pathlib
    js = pathlib.Path(__file__).resolve().parent.parent / "companion" / "static" / "app.js"
    text = js.read_text(encoding="utf-8")
    assert "voice_channel_snapshot" in text, "app.js 應該路由 voice_channel_snapshot 事件"
    assert "onVoiceChannelSnapshot" in text, "app.js 應該有 onVoiceChannelSnapshot handler"


def test_voice_channel_snapshot_event_routes_through_ws(app_and_bridge):
    """server 廣播 voice_channel_snapshot 到 browser，不會被 protocol 過濾掉。"""
    app, bridge = app_and_bridge
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            evt = {
                "type": "voice_channel_snapshot",
                "payload": {
                    "members": [
                        {"speaker": "Jack", "name": "狗與露", "marvin": False},
                    ],
                    "snapshot_ts": 100.0,
                },
                "ts": 101.0,
            }

            async def emit():
                await bridge.simulate_incoming(evt)

            client.portal.call(emit)
            received = ws.receive_json()
            assert received["type"] == "voice_channel_snapshot"
            assert received["payload"]["members"][0]["speaker"] == "Jack"


# ------------------------------------------------------------------ Lane F2: 防呆雷達 radar

def test_game_alert_event_type_constant():
    """event_protocol 須有 GAME_ALERT 與 GAME_ALERT_RESPONSE 常數，且納入 KNOWN_EVENT_TYPES。"""
    from companion.event_protocol import (
        GAME_ALERT,
        GAME_ALERT_RESPONSE,
        BRIDGE_TO_BROWSER_EVENTS,
        BROWSER_TO_BRIDGE_EVENTS,
        KNOWN_EVENT_TYPES,
    )
    assert GAME_ALERT == "game_alert"
    assert GAME_ALERT_RESPONSE == "game_alert_response"
    assert GAME_ALERT in BRIDGE_TO_BROWSER_EVENTS
    assert GAME_ALERT_RESPONSE in BROWSER_TO_BRIDGE_EVENTS
    assert GAME_ALERT in KNOWN_EVENT_TYPES
    assert GAME_ALERT_RESPONSE in KNOWN_EVENT_TYPES


def test_index_html_has_alert_card_elements(app_and_bridge):
    """index.html 須包含防呆雷達 UI element id：alert-card-warn、alert-msg、按鈕。"""
    app, _ = app_and_bridge
    with TestClient(app) as client:
        html = client.get("/").text
        assert 'id="alert-card-warn"' in html
        assert 'id="alert-msg"' in html
        assert 'id="alert-btn-veto"' in html
        assert 'id="alert-btn-approve"' in html
        # 預設隱藏（hidden 屬性）
        assert 'id="alert-card-warn"' in html and "hidden" in html


def test_game_alert_response_browser_to_bridge_forwarded(app_and_bridge):
    """browser 送 game_alert_response → server forward 到 bridge。"""
    app, bridge = app_and_bridge
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            evt = {
                "type": "game_alert_response",
                "payload": {"alert_id": "abc-123", "decision": "veto"},
                "ts": 101.0,
            }
            ws.send_json(evt)
            import time
            time.sleep(0.1)
            assert evt in bridge.sent_messages
