"""Lane F：遊戲模式 UI 整合測試。

- index.html 必須含 game-panel / game-side-panel 與關鍵 element id
- WS：server 廣播 game_phase_changed 給 browser 不會被 protocol 過濾
- WS：browser 送 game_force_skip_round → bridge 收到
- WS：browser 送 game_end → bridge 收到
- 事件協定常數已知
"""

import pytest
from fastapi.testclient import TestClient

from companion.bridge_client import BridgeClient
from companion.server import create_app


@pytest.fixture
def app_and_bridge():
    bridge = BridgeClient(url="ws://localhost:8766", mock_mode=True)
    app = create_app(bridge=bridge)
    return app, bridge


def test_index_html_has_game_panel_elements(app_and_bridge):
    """遊戲模式必備 element id：game-panel、game-side-panel 與內含關鍵子元素。"""
    app, _ = app_and_bridge
    with TestClient(app) as client:
        html = client.get("/").text
        assert 'id="game-panel"' in html
        assert 'id="game-side-panel"' in html
        # 子元素：標題、phase 文字、scoreboard、events log、控制鈕、氛圍 gauge
        assert 'id="game-title"' in html
        assert 'id="game-round"' in html
        assert 'id="game-timer"' in html
        assert 'id="game-phase-text"' in html
        assert 'id="game-scoreboard"' in html
        assert 'id="game-events-log"' in html
        assert 'id="game-controls"' in html
        assert 'id="atmos-gauge-pointer"' in html
        assert 'id="atmos-status"' in html


def test_index_html_game_panel_initially_hidden(app_and_bridge):
    """idle 預設下 game-panel 必須是 hidden。"""
    app, _ = app_and_bridge
    with TestClient(app) as client:
        html = client.get("/").text
        # Locate the game-panel section line and verify it has 'hidden' attribute nearby
        # 簡易檢查：game-panel 與 hidden 都在 HTML 內
        assert 'id="game-panel"' in html
        # game-panel section line includes hidden
        idx = html.index('id="game-panel"')
        snippet = html[max(0, idx - 200): idx + 200]
        assert 'hidden' in snippet


def test_game_phase_changed_event_routes_through_ws(app_and_bridge):
    """server 廣播 game_phase_changed 給 browser，不會被 protocol 過濾掉。"""
    app, bridge = app_and_bridge
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            evt = {
                "type": "game_phase_changed",
                "payload": {
                    "game": "detective",
                    "phase": "declaring",
                    "round": 2,
                    "round_total": 4,
                    "scoreboard": [{"user": "Jack", "score": 4}],
                    "current_player": "Bob",
                    "timer_seconds": 60,
                    "last_event": "輪到 Bob 宣告",
                },
                "ts": 101.0,
            }

            async def emit():
                await bridge.simulate_incoming(evt)

            client.portal.call(emit)
            received = ws.receive_json()
            assert received["type"] == "game_phase_changed"
            assert received["payload"]["phase"] == "declaring"
            assert received["payload"]["current_player"] == "Bob"


def test_game_force_skip_round_event_forwarded(app_and_bridge):
    """browser 送 game_force_skip_round → bridge 收到。"""
    app, bridge = app_and_bridge
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            evt = {
                "type": "game_force_skip_round",
                "payload": {"game": "detective"},
                "ts": 1.0,
            }
            ws.send_json(evt)
            import time
            time.sleep(0.1)
            assert evt in bridge.sent_messages


def test_game_end_event_forwarded(app_and_bridge):
    """browser 送 game_end → bridge 收到。"""
    app, bridge = app_and_bridge
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            evt = {
                "type": "game_end",
                "payload": {"game": "detective"},
                "ts": 1.0,
            }
            ws.send_json(evt)
            import time
            time.sleep(0.1)
            assert evt in bridge.sent_messages


def test_game_event_protocol_constants_known():
    """game_phase_changed / game_force_skip_round / game_end 已在事件協定常數中。"""
    from companion.event_protocol import (
        KNOWN_EVENT_TYPES,
        BRIDGE_TO_BROWSER_EVENTS,
        BROWSER_TO_BRIDGE_EVENTS,
    )
    assert "game_phase_changed" in BRIDGE_TO_BROWSER_EVENTS
    assert "game_force_skip_round" in BROWSER_TO_BRIDGE_EVENTS
    assert "game_end" in BROWSER_TO_BRIDGE_EVENTS
    assert "game_force_skip_round" in KNOWN_EVENT_TYPES
    assert "game_end" in KNOWN_EVENT_TYPES
