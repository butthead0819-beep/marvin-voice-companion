"""WebSocket client：companion-server → Marvin 端 bridge。

Lane B（Marvin 端的 companion_bridge.py）尚未實作，這裡支援 mock_mode=True
讓 server 與測試可以在 bridge 不存在的情況下跑通。

未來 Lane B 上線時，real-WS 分支會打到 ws://localhost:8766，
測試與 server 介面不需改動。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Awaitable, Callable, List, Optional

logger = logging.getLogger(__name__)

EventHandler = Callable[[dict], Awaitable[None]]

RECONNECT_DELAY_SEC = 5.0

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


class BridgeClient:
    """負責與 Marvin 端 bridge 的 WS 連線。

    對外只暴露 start/stop/send/on_event/is_connected。
    Mock 模式：send() 寫入 self.sent_messages；simulate_incoming() 主動觸發 handlers。
    """

    @classmethod
    def from_env(cls) -> "BridgeClient":
        """從環境變數建構 BridgeClient。

        - COMPANION_BRIDGE_URL：bridge WS URL（預設 ws://localhost:8766/companion-ws）
        - COMPANION_BRIDGE_MOCK：1/true/yes/on 走 mock，其餘預設 real
        - MARMO_TOKEN：沿用主 bot 的認證 token，透過 X-Marmo-Token header 送出
        """
        url = os.environ.get("COMPANION_BRIDGE_URL", "ws://localhost:8766/companion-ws")
        mock_raw = os.environ.get("COMPANION_BRIDGE_MOCK", "").strip().lower()
        mock = mock_raw in _TRUE_VALUES
        token = os.environ.get("MARMO_TOKEN", "")
        return cls(url=url, mock_mode=mock, token=token)

    def __init__(self, url: str = "ws://localhost:8766/companion-ws", mock_mode: bool = False, token: str = "") -> None:
        self.url = url
        self.mock_mode = mock_mode
        self._token = token
        self._handlers: List[EventHandler] = []
        self._connected = False
        self._task: Optional[asyncio.Task] = None
        self._stop = False
        # Mock 模式用 buffer
        self.sent_messages: List[dict] = []
        self._ws = None  # real 模式才會用到

    # ------------------------------------------------------------------ public

    @property
    def is_connected(self) -> bool:
        return self._connected

    def on_event(self, handler: EventHandler) -> None:
        """註冊 incoming event handler。多次呼叫會註冊多個。"""
        self._handlers.append(handler)

    async def start(self) -> None:
        if self.mock_mode:
            self._connected = True
            logger.info("[Companion] BridgeClient started in mock_mode (url=%s)", self.url)
            return
        # 啟動背景重連 loop
        self._stop = False
        self._task = asyncio.create_task(self._reconnect_loop())
        logger.info("[Companion] BridgeClient real-mode start, target=%s", self.url)

    async def stop(self) -> None:
        self._stop = True
        if self.mock_mode:
            self._connected = False
            return
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        self._connected = False

    async def send(self, event: dict) -> None:
        """送一則事件到 bridge。

        Mock 模式存 self.sent_messages；real 模式 WS write。
        Bridge 未連線時：mock 仍接受；real 則 log 後 drop（優雅降級）。
        """
        if self.mock_mode:
            self.sent_messages.append(event)
            return
        if not self._connected or self._ws is None:
            logger.warning("[Companion] send dropped — bridge disconnected: type=%s", event.get("type"))
            return
        try:
            await self._ws.send(json.dumps(event))
        except Exception as exc:
            logger.warning("[Companion] bridge send failed: %s", exc)
            self._connected = False

    async def simulate_incoming(self, event: dict) -> None:
        """測試 helper：模擬從 bridge 收到事件，觸發所有 handler。"""
        await self._dispatch(event)

    # ----------------------------------------------------------------- internal

    async def _dispatch(self, event: dict) -> None:
        for h in self._handlers:
            try:
                await h(event)
            except Exception as exc:
                logger.exception("[Companion] handler error on %s: %s", event.get("type"), exc)

    async def _reconnect_loop(self) -> None:
        """背景任務：連線 → 收訊息 → 斷線 → 等 5 秒 → 再連。"""
        try:
            import websockets  # 延遲匯入，測試 mock_mode 不用
        except ImportError:
            logger.error("[Companion] websockets package missing; bridge cannot run")
            return

        while not self._stop:
            try:
                headers = {"X-Marmo-Token": self._token} if self._token else {}
                async with websockets.connect(self.url, additional_headers=headers) as ws:
                    self._ws = ws
                    self._connected = True
                    logger.info("[Companion] bridge connected: %s", self.url)
                    async for raw in ws:
                        try:
                            event = json.loads(raw)
                        except Exception:
                            logger.warning("[Companion] bridge sent non-JSON, ignored")
                            continue
                        await self._dispatch(event)
            except Exception as exc:
                logger.warning("[Companion] bridge connect/recv failed: %s", exc)
            finally:
                self._connected = False
                self._ws = None

            if self._stop:
                break
            await asyncio.sleep(RECONNECT_DELAY_SEC)
