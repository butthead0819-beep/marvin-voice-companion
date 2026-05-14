"""測試 BridgeClient — companion-server 連到 Marvin bridge 的 WS 客戶端。

Lane B (Marvin 端 bridge) 尚未實作，這裡測 mock_mode：
- send() 把訊息塞進本地 buffer 而非 WS
- on_event() 註冊 handler，模擬收到事件時觸發
- is_connected 屬性反映 start/stop 狀態
"""

import asyncio

import pytest

from companion.bridge_client import BridgeClient


class TestBridgeClientMockMode:
    async def test_is_connected_false_before_start(self):
        client = BridgeClient(url="ws://localhost:8766", mock_mode=True)
        assert client.is_connected is False

    async def test_is_connected_true_after_start_in_mock_mode(self):
        client = BridgeClient(url="ws://localhost:8766", mock_mode=True)
        await client.start()
        try:
            assert client.is_connected is True
        finally:
            await client.stop()

    async def test_is_connected_false_after_stop(self):
        client = BridgeClient(url="ws://localhost:8766", mock_mode=True)
        await client.start()
        await client.stop()
        assert client.is_connected is False

    async def test_send_captures_messages_locally_in_mock_mode(self):
        client = BridgeClient(url="ws://localhost:8766", mock_mode=True)
        await client.start()
        try:
            evt = {"type": "atmosphere_feedback", "payload": {"label": "too_sharp"}, "ts": 1.0}
            await client.send(evt)
            assert evt in client.sent_messages
        finally:
            await client.stop()

    async def test_on_event_registers_handler_and_simulate_incoming_fires_it(self):
        client = BridgeClient(url="ws://localhost:8766", mock_mode=True)
        await client.start()
        try:
            received = []

            async def handler(event):
                received.append(event)

            client.on_event(handler)
            sample = {"type": "stt_chunk", "payload": {"speaker": "jack"}, "ts": 1.0}
            await client.simulate_incoming(sample)
            # 給 handler 一個 tick 跑完
            await asyncio.sleep(0)
            assert received == [sample]
        finally:
            await client.stop()

    async def test_multiple_handlers_all_fire(self):
        client = BridgeClient(url="ws://localhost:8766", mock_mode=True)
        await client.start()
        try:
            calls = []

            async def h1(e):
                calls.append(("h1", e["type"]))

            async def h2(e):
                calls.append(("h2", e["type"]))

            client.on_event(h1)
            client.on_event(h2)
            await client.simulate_incoming({"type": "tts_started", "payload": {}, "ts": 1.0})
            await asyncio.sleep(0)
            assert ("h1", "tts_started") in calls
            assert ("h2", "tts_started") in calls
        finally:
            await client.stop()
