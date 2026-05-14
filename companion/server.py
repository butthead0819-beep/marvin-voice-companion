"""FastAPI server — companion-server 的 WebSocket hub。

職責（注意：零業務邏輯）：
- 靜態檔案：GET / 回 static/index.html、GET /static/* 直接送檔
- WS /ws：瀏覽器（Mac + iPhone）連進來，雙向中繼到 bridge
- 啟動時起 BridgeClient（mock 或 real），bridge → all browsers 廣播
- 斷線清理：瀏覽器 disconnect → 從 registry 移除
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from companion.bridge_client import BridgeClient
from companion.event_protocol import (
    BROWSER_TO_BRIDGE_EVENTS,
    validate_event,
)

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"


def create_app(bridge: Optional[BridgeClient] = None) -> FastAPI:
    """工廠：建立 FastAPI app。

    bridge 可由外部傳入（測試常用 mock_mode 的 instance）；不傳則自動建一個 real-mode。
    """
    _bridge = bridge or BridgeClient.from_env()

    @asynccontextmanager
    async def lifespan(fa: FastAPI):
        await fa.state.bridge.start()
        logger.info("[Companion] server startup complete")
        try:
            yield
        finally:
            for cid, ws in list(fa.state.clients.items()):
                try:
                    await ws.close()
                except Exception:
                    pass
            fa.state.clients.clear()
            await fa.state.bridge.stop()
            logger.info("[Companion] server shutdown complete")

    app = FastAPI(lifespan=lifespan)
    app.state.bridge = _bridge
    app.state.clients: Dict[str, WebSocket] = {}

    # ---------- bridge → browsers 廣播 handler ----------
    async def _broadcast_to_browsers(event: dict) -> None:
        # 防呆：bridge 端理論上送合規格事件；不合規就 drop + log
        if not validate_event(event):
            logger.warning("[Companion] dropped invalid bridge event: %s", event)
            return
        dead = []
        for cid, ws in list(app.state.clients.items()):
            try:
                await ws.send_json(event)
            except Exception as exc:
                logger.warning("[Companion] broadcast to %s failed: %s", cid, exc)
                dead.append(cid)
        for cid in dead:
            app.state.clients.pop(cid, None)

    app.state.bridge.on_event(_broadcast_to_browsers)

    # ---------- HTTP routes ----------
    @app.get("/")
    async def root():
        if INDEX_HTML.exists():
            return FileResponse(str(INDEX_HTML))
        # Fallback：static 還沒被填滿時也要能回應
        return HTMLResponse("<html><body>Companion connecting…</body></html>")

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # ---------- WebSocket ----------
    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket):
        await websocket.accept()
        client_id = uuid.uuid4().hex[:8]
        app.state.clients[client_id] = websocket
        logger.info("[Companion] browser connected id=%s (total=%d)", client_id, len(app.state.clients))
        try:
            while True:
                msg = await websocket.receive_json()
                await _handle_browser_message(app, msg)
        except WebSocketDisconnect:
            logger.info("[Companion] browser disconnected id=%s", client_id)
        except Exception as exc:
            logger.warning("[Companion] ws error id=%s: %s", client_id, exc)
        finally:
            app.state.clients.pop(client_id, None)

    return app


async def _handle_browser_message(app: FastAPI, msg: dict) -> None:
    """瀏覽器 → companion → bridge 的路由邏輯。

    - 不合規 shape：log 後 drop
    - 已知 browser→bridge 事件：forward
    - 其他（bridge→browser 事件從瀏覽器送來、或未知 type）：log 後 drop
    """
    if not validate_event(msg):
        logger.warning("[Companion] dropped invalid browser msg: %s", msg)
        return
    evt_type = msg["type"]
    if evt_type not in BROWSER_TO_BRIDGE_EVENTS:
        logger.warning("[Companion] dropped non-browser-side event: type=%s", evt_type)
        return
    await app.state.bridge.send(msg)


# 預設 app（uvicorn companion.server:app 用）
app = create_app()
