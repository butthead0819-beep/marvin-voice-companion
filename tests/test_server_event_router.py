"""測試事件路由邏輯：

- 未知 type → log 後 drop，不 crash 不 forward
- 已知 browser→bridge 事件 → forward 到 bridge client 並保留原 shape
- bridge→browser 事件 → 廣播保留原 shape
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


def test_unknown_event_type_does_not_crash_and_not_forwarded(app_and_bridge):
    app, bridge = app_and_bridge
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "made_up_thing", "payload": {}, "ts": 1.0})
            import time
            time.sleep(0.1)
            # bridge.sent_messages 不應該有這個垃圾事件
            assert not any(m.get("type") == "made_up_thing" for m in bridge.sent_messages)


def test_malformed_message_does_not_crash(app_and_bridge):
    app, bridge = app_and_bridge
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"hello": "world"})  # missing type/payload/ts
            import time
            time.sleep(0.1)
            assert len(bridge.sent_messages) == 0


def test_browser_event_forwarded_preserves_shape(app_and_bridge):
    app, bridge = app_and_bridge
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            evt = {
                "type": "memory_delete",
                "payload": {"doc_id": "abc123"},
                "ts": 99.0,
            }
            ws.send_json(evt)
            import time
            time.sleep(0.1)
            assert evt in bridge.sent_messages


def test_bridge_event_broadcast_preserves_shape(app_and_bridge):
    app, bridge = app_and_bridge
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            evt = {
                "type": "atmosphere_snapshot",
                "payload": {"score": 0.7},
                "ts": 5.0,
            }

            async def emit():
                await bridge.simulate_incoming(evt)

            client.portal.call(emit)
            got = ws.receive_json()
            assert got == evt
