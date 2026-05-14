"""測試 FastAPI WebSocket 端點生命週期。

範圍：
- 瀏覽器接得上 /ws
- bridge 事件廣播到所有連線中的瀏覽器
- 瀏覽器送來的事件會 forward 到 bridge client
- 斷線清除 registry
"""

import json

import pytest
from fastapi.testclient import TestClient

from companion.server import create_app
from companion.bridge_client import BridgeClient


@pytest.fixture
def app_and_bridge():
    bridge = BridgeClient(url="ws://localhost:8766", mock_mode=True)
    app = create_app(bridge=bridge)
    return app, bridge


def test_get_root_returns_index_html(app_and_bridge):
    app, _ = app_and_bridge
    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200
        assert "Companion" in r.text or "companion" in r.text


def test_browser_can_connect_to_ws(app_and_bridge):
    app, _ = app_and_bridge
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            # 連線就好；不一定要收到任何訊息
            assert ws is not None


def test_bridge_event_broadcasts_to_all_connected_browsers(app_and_bridge):
    app, bridge = app_and_bridge
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws1:
            with client.websocket_connect("/ws") as ws2:
                # 模擬 bridge 收到事件
                import asyncio
                evt = {"type": "stt_chunk", "payload": {"speaker": "jack"}, "ts": 1.0}

                async def emit():
                    await bridge.simulate_incoming(evt)

                # 用 TestClient 的 portal 跑 async
                client.portal.call(emit)

                m1 = ws1.receive_json()
                m2 = ws2.receive_json()
                assert m1 == evt
                assert m2 == evt


def test_browser_event_forwarded_to_bridge(app_and_bridge):
    app, bridge = app_and_bridge
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            evt = {
                "type": "atmosphere_feedback",
                "payload": {"snapshot_ts": 1.0, "label": "too_sharp"},
                "ts": 2.0,
            }
            ws.send_json(evt)
            # 給 server 一個 tick 處理
            import time
            time.sleep(0.1)
            assert evt in bridge.sent_messages


def test_browser_disconnect_cleans_up_registry(app_and_bridge):
    app, _ = app_and_bridge
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            pass  # 進出 context manager 即斷線
        # 此時 server.state.clients 應該是空的
        import time
        time.sleep(0.1)
        assert len(app.state.clients) == 0
